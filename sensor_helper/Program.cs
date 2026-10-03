// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

using System.Text.Json;
using System.Diagnostics;
using System.Runtime.InteropServices;
using LibreHardwareMonitor.Hardware;

const int DefaultIntervalMs = 2000;
bool once = args.Contains("--once", StringComparer.OrdinalIgnoreCase);
int intervalMs = DefaultIntervalMs;
string? outputPath = null;
string? stopFile = null;
int? ownerProcessId = null;
bool compactFrequency = args.Contains("--compact-frequency", StringComparer.OrdinalIgnoreCase);
bool allTelemetry = args.Contains("--all-telemetry", StringComparer.OrdinalIgnoreCase);
int intervalIndex = Array.FindIndex(args, value => value.Equals("--interval-ms", StringComparison.OrdinalIgnoreCase));
if (intervalIndex >= 0)
{
    if (intervalIndex + 1 >= args.Length || !int.TryParse(args[intervalIndex + 1], out intervalMs) || intervalMs < 250)
    {
        Console.Error.WriteLine("--interval-ms requires an integer of at least 250");
        return 2;
    }
}
int outputIndex = Array.FindIndex(args, value => value.Equals("--output", StringComparison.OrdinalIgnoreCase));
if (outputIndex >= 0)
{
    if (outputIndex + 1 >= args.Length)
    {
        Console.Error.WriteLine("--output requires a file path");
        return 2;
    }
    outputPath = args[outputIndex + 1];
}
int stopIndex = Array.FindIndex(args, value => value.Equals("--stop-file", StringComparison.OrdinalIgnoreCase));
if (stopIndex >= 0)
{
    if (stopIndex + 1 >= args.Length)
    {
        Console.Error.WriteLine("--stop-file requires a file path");
        return 2;
    }
    stopFile = args[stopIndex + 1];
}
int ownerIndex = Array.FindIndex(args, value => value.Equals("--owner-pid", StringComparison.OrdinalIgnoreCase));
if (ownerIndex >= 0)
{
    if (ownerIndex + 1 >= args.Length || !int.TryParse(args[ownerIndex + 1], out int parsedOwner) || parsedOwner <= 0)
    {
        Console.Error.WriteLine("--owner-pid requires a positive process ID");
        return 2;
    }
    ownerProcessId = parsedOwner;
}

// Normal one-shot CPU diagnostics stay narrow. Live telemetry also opens the
// motherboard tree for mode 8 CPU-fan RPM. We still leave disks, networking,
// controllers, batteries and PSU polling off; fan data comes from the same
// persistent two-second snapshot rather than another helper or polling loop.
Computer computer = new()
{
    IsCpuEnabled = true,
    IsGpuEnabled = allTelemetry || compactFrequency,
    IsMotherboardEnabled = allTelemetry || compactFrequency,
    // Memory is enabled only for explicit inventory. The live loop uses the
    // cheap Win32 system-memory counter below; LHM Memory also walks DIMM/SPD
    // hardware on this machine and made a compact probe exceed 30 seconds.
    IsMemoryEnabled = allTelemetry
};
try
{
    computer.Open();
    if (allTelemetry)
    {
        Console.Error.WriteLine(JsonSerializer.Serialize(new
        {
            diagnostic = "enabled_hardware",
            cpu = computer.IsCpuEnabled,
            gpu = computer.IsGpuEnabled,
            memory = computer.IsMemoryEnabled,
            discovered = computer.Hardware.Select(item => new
            {
                type = item.HardwareType.ToString(),
                name = item.Name,
                identifier = item.Identifier.ToString()
            })
        }));
    }
}
catch (Exception exception)
{
    WriteError("open_failed", exception);
    return 3;
}

JsonSerializerOptions jsonOptions = new()
{
    PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    WriteIndented = false
};

do
{
    try
    {
        List<SensorRecord> sensors = new();
        foreach (IHardware hardware in computer.Hardware.Where(item =>
                     item.HardwareType == HardwareType.Cpu ||
                     ((allTelemetry || compactFrequency) &&
                      item.HardwareType is HardwareType.GpuNvidia or HardwareType.GpuAmd or HardwareType.GpuIntel or HardwareType.Memory or HardwareType.Motherboard)))
        {
            UpdateRecursive(hardware);
            CollectRecursive(hardware, sensors);
        }

        object snapshot = compactFrequency
            ? BuildTelemetrySnapshot(sensors)
            : new Snapshot(DateTimeOffset.Now, Environment.IsPrivilegedProcess, sensors.Count, sensors);
        string json = JsonSerializer.Serialize(snapshot, jsonOptions);
        Console.WriteLine(json);
        Console.Out.Flush();
        if (outputPath is not null)
        {
            string? parent = Path.GetDirectoryName(Path.GetFullPath(outputPath));
            if (!string.IsNullOrEmpty(parent))
                Directory.CreateDirectory(parent);
            File.AppendAllText(outputPath, json + Environment.NewLine);
        }
    }
    catch (Exception exception)
    {
        WriteError("sample_failed", exception);
        if (once)
        {
            computer.Close();
            return 4;
        }
    }

    if (!once)
        await Task.Delay(intervalMs);
} while (!once &&
         (stopFile is null || !File.Exists(stopFile)) &&
         (ownerProcessId is null || IsProcessAlive(ownerProcessId.Value)));

computer.Close();

// The durable application session log already contains every compact sample.
// Clean normal stream scratch files here as well as in Python so owner-death
// shutdown still tidies up when the GUI is no longer alive to do it.
if (compactFrequency && !once)
{
    try
    {
        if (outputPath is not null)
            File.Delete(outputPath);
        if (stopFile is not null)
            File.Delete(stopFile);
    }
    catch (Exception exception)
    {
        WriteError("scratch_cleanup_failed", exception);
    }
}
return 0;

static void UpdateRecursive(IHardware hardware)
{
    hardware.Update();
    foreach (IHardware child in hardware.SubHardware)
        UpdateRecursive(child);
}

static bool IsProcessAlive(int processId)
{
    try
    {
        using Process process = Process.GetProcessById(processId);
        return !process.HasExited;
    }
    catch (ArgumentException)
    {
        return false;
    }
}

static void CollectRecursive(IHardware hardware, List<SensorRecord> destination)
{
    foreach (ISensor sensor in hardware.Sensors)
    {
        destination.Add(new SensorRecord(
            hardware.Name,
            hardware.HardwareType.ToString(),
            hardware.Identifier.ToString(),
            sensor.Name,
            sensor.Identifier.ToString(),
            sensor.SensorType.ToString(),
            sensor.Value,
            sensor.Min,
            sensor.Max
        ));
    }
    foreach (IHardware child in hardware.SubHardware)
        CollectRecursive(child, destination);
}

static void WriteError(string kind, Exception exception)
{
    Console.Error.WriteLine(JsonSerializer.Serialize(new
    {
        timestamp = DateTimeOffset.Now,
        kind,
        error_type = exception.GetType().FullName,
        message = exception.Message
    }));
}

static TelemetrySnapshot BuildTelemetrySnapshot(IReadOnlyList<SensorRecord> sensors)
{
    // LHM 0.9.6 reports `/gpu-nvidia/0/load/3` twice on this RTX 4090 (GPU Bus
    // and GPU Memory). Identifier lookup must not let an unrelated duplicate
    // abort the complete telemetry sample.
    Dictionary<string, SensorRecord> byId = sensors
        .GroupBy(sensor => sensor.SensorIdentifier)
        .ToDictionary(group => group.Key, group => group.First());
    List<CoreFrequencyRecord> cores = new();
    for (int core = 1; core <= 24; core++)
    {
        if (!byId.TryGetValue($"/intelcpu/0/clock/{core}", out SensorRecord? clock) || clock.Value is null)
            continue;
        List<SensorRecord> loads = new();
        if (core <= 8)
        {
            int firstLoad = core * 2;
            foreach (int loadIndex in new[] { firstLoad, firstLoad + 1 })
                if (byId.TryGetValue($"/intelcpu/0/load/{loadIndex}", out SensorRecord? load) && load.Value is not null)
                    loads.Add(load);
        }
        else if (byId.TryGetValue($"/intelcpu/0/load/{core + 9}", out SensorRecord? load) && load.Value is not null)
        {
            loads.Add(load);
        }
        if (loads.Count == 0)
            continue;
        float coreLoad = loads.Max(item => item.Value!.Value);
        cores.Add(new CoreFrequencyRecord(clock.SensorName, clock.SensorIdentifier, clock.Value.Value, coreLoad));
    }
    CoreFrequencyRecord? winner = cores.OrderByDescending(core => core.LoadPercent).ThenByDescending(core => core.ClockMhz).FirstOrDefault();
    double weight = cores.Sum(core => core.LoadPercent);
    double? weighted = weight > 0
        ? cores.Sum(core => core.ClockMhz * core.LoadPercent) / weight
        : null;
    float? totalLoad = byId.TryGetValue("/intelcpu/0/load/0", out SensorRecord? total) ? total.Value : null;
    float? packageTemperature = byId.TryGetValue("/intelcpu/0/temperature/26", out SensorRecord? package) ? package.Value : null;
    float? coreAverageTemperature = byId.TryGetValue("/intelcpu/0/temperature/1", out SensorRecord? coreAverage) ? coreAverage.Value : null;

    // Sensor identifiers are stable on this machine, but matching type/name as
    // well makes the helper useful if LHM assigns another GPU index later. We
    // still return the chosen identifier so the Python log can prove exactly
    // which source fed each LCD value.
    SensorRecord? gpuClock = byId.GetValueOrDefault("/gpu-nvidia/0/clock/0")
        ?? FindPreferredSensor(sensors, "Gpu", "Clock", "GPU Core");
    SensorRecord? gpuTemperature = byId.GetValueOrDefault("/gpu-nvidia/0/temperature/0")
        ?? FindPreferredSensor(sensors, "Gpu", "Temperature", "GPU Core");
    SensorRecord? gpuLoad = byId.GetValueOrDefault("/gpu-nvidia/0/load/0")
        ?? FindPreferredSensor(sensors, "Gpu", "Load", "GPU Core");
    SensorRecord? cpuFan = FindCpuFanSensor(sensors);
    // `/vram/load/1` is page-file/virtual-memory pressure and was 39.0% in the
    // same capture where physical RAM was 33.3%. Mode 7 must use Total Memory.
    float? memoryLoad = ReadPhysicalMemoryLoad();

    return new TelemetrySnapshot(
        DateTimeOffset.Now,
        Environment.IsPrivilegedProcess,
        Environment.ProcessId,
        Process.GetCurrentProcess().TotalProcessorTime.TotalMilliseconds,
        totalLoad,
        packageTemperature,
        coreAverageTemperature,
        winner,
        weighted,
        gpuClock?.Value,
        gpuClock?.SensorIdentifier,
        gpuTemperature?.Value,
        gpuTemperature?.SensorIdentifier,
        gpuLoad?.Value,
        gpuLoad?.SensorIdentifier,
        cpuFan?.Value,
        cpuFan?.SensorIdentifier,
        cpuFan?.SensorName,
        cpuFan?.HardwareName,
        memoryLoad,
        "win32:GlobalMemoryStatusEx.dwMemoryLoad",
        cores
    );
}

static SensorRecord? FindCpuFanSensor(IReadOnlyList<SensorRecord> sensors)
{
    // Board vendors do not expose a portable "CPU fan" identifier. Prefer an
    // explicitly named CPU channel. If labels are generic, accept a fallback
    // only when exactly one non-GPU fan is spinning; choosing arbitrarily from
    // several active headers would put a confidently wrong value on the LCD.
    List<SensorRecord> fans = sensors.Where(sensor =>
        sensor.SensorType.Equals("Fan", StringComparison.OrdinalIgnoreCase) &&
        !sensor.HardwareType.StartsWith("Gpu", StringComparison.OrdinalIgnoreCase) &&
        sensor.Value is not null).ToList();
    SensorRecord? namedCpuFan = fans.FirstOrDefault(sensor =>
        sensor.SensorName.Contains("CPU", StringComparison.OrdinalIgnoreCase));
    if (namedCpuFan is not null)
        return namedCpuFan;
    List<SensorRecord> active = fans.Where(sensor => sensor.Value > 0).ToList();
    return active.Count == 1 ? active[0] : null;
}

static float? ReadPhysicalMemoryLoad()
{
    MemoryStatusEx status = new() { Length = (uint)Marshal.SizeOf<MemoryStatusEx>() };
    return GlobalMemoryStatusEx(ref status) ? status.MemoryLoad : null;
}

[DllImport("kernel32.dll", SetLastError = true)]
static extern bool GlobalMemoryStatusEx(ref MemoryStatusEx buffer);

static SensorRecord? FindPreferredSensor(
    IReadOnlyList<SensorRecord> sensors,
    string hardwareType,
    string sensorType,
    string preferredName)
{
    IEnumerable<SensorRecord> candidates = sensors.Where(sensor =>
        sensor.HardwareType.StartsWith(hardwareType, StringComparison.OrdinalIgnoreCase) &&
        sensor.SensorType.Equals(sensorType, StringComparison.OrdinalIgnoreCase) &&
        sensor.Value is not null);
    return candidates.FirstOrDefault(sensor =>
               sensor.SensorName.Equals(preferredName, StringComparison.OrdinalIgnoreCase))
           ?? candidates.FirstOrDefault();
}

internal sealed record Snapshot(
    DateTimeOffset Timestamp,
    bool IsElevated,
    int SensorCount,
    IReadOnlyList<SensorRecord> Sensors
);

internal sealed record SensorRecord(
    string HardwareName,
    string HardwareType,
    string HardwareIdentifier,
    string SensorName,
    string SensorIdentifier,
    string SensorType,
    float? Value,
    float? Min,
    float? Max
);

internal sealed record CoreFrequencyRecord(
    string Name,
    string ClockIdentifier,
    float ClockMhz,
    float LoadPercent
);

[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Auto)]
internal struct MemoryStatusEx
{
    public uint Length;
    public uint MemoryLoad;
    public ulong TotalPhysical;
    public ulong AvailablePhysical;
    public ulong TotalPageFile;
    public ulong AvailablePageFile;
    public ulong TotalVirtual;
    public ulong AvailableVirtual;
    public ulong AvailableExtendedVirtual;
}

internal sealed record TelemetrySnapshot(
    DateTimeOffset Timestamp,
    bool IsElevated,
    int ProcessId,
    double ProcessCpuMilliseconds,
    float? CpuTotalLoadPercent,
    float? CpuPackageTemperatureC,
    float? CoreAverageTemperatureC,
    CoreFrequencyRecord? HighestLoadedCore,
    double? LoadWeightedClockMhz,
    float? GpuCoreClockMhz,
    string? GpuCoreClockIdentifier,
    float? GpuCoreTemperatureC,
    string? GpuCoreTemperatureIdentifier,
    float? GpuCoreLoadPercent,
    string? GpuCoreLoadIdentifier,
    float? CpuFanRpm,
    string? CpuFanIdentifier,
    string? CpuFanName,
    string? CpuFanHardwareName,
    float? MemoryLoadPercent,
    string? MemoryLoadIdentifier,
    IReadOnlyList<CoreFrequencyRecord> Cores
);
