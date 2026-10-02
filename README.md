# HAF 700 EVO Iris experimental controller

This is an experimental Windows GUI replacement for the Cooler Master HAF 700 EVO Iris display control path. It implements behavior recovered from the stock Android application and physically tested on the development unit:

- fixed ADB target `1234567890ABCDEF`;
- temporary `localhost:18888 -> device:9900` forwarding;
- automatic CPU/GPU frequency, CPU/GPU temperature, CPU/GPU usage, and physical RAM usage modes;
- extended manual 0-9,990 MHz CPU-frequency display tests using command `0x12` while retaining stock 1,100/6,000 MHz style bounds;
- extended manual -20 to +150 C CPU-temperature tests using confirmed mode 3 and captured stock 40/80 style bounds;
- physically validated manual controls for numeric renderer modes 2 and 4-13: GPU clock/temperature, CPU/GPU/RAM usage, CPU fan, and case fans 1-5;
- a confirmation-gated reboot button that runs `adb -s 1234567890ABCDEF reboot` and removes the app's HAF-specific forward;
- bounded per-session JSONL logs under `logs/`;
- a timestamped activity log on the right showing decoded transmitted fields, full TX frame hex, received ACK hex/match state, ADB forwarding, CPU sensor probes, and reboot results.
- a read-only CPU sensor probe backed by the workspace-local LibreHardwareMonitor helper.
- a live dashboard showing current/session-min/session-max values and bars for CPU/GPU frequency, CPU/GPU temperature, CPU/GPU usage, and physical RAM usage;
- a configurable debug-visible cycle through automatic numeric modes 1-7 without additional per-mode polling;
- JSON-backed window/startup preferences, optional per-user Windows logon registration, automatic fixed-device connection, and automatic LHM start;
- optional notification-area operation provided by the declared `pystray` dependency.

On a fresh installation the application starts inert. Saved preferences can explicitly enable automatic connection and LHM startup on later launches. Disconnect and normal exit remove only the HAF-specific local forward. Reboot requires separate confirmation and targets only the fixed HAF serial. The application does not flash firmware, install/modify an APK, access NAND, start MasterPlus, or target another ADB serial.

`avatar small.jpg` is the source artwork and `haf_iris.ico` is the multi-resolution Windows icon. They use the V2/STW emblem under its stated good-faith, non-commercial conditions and are not MPL-licensed; see `ASSET_NOTICE.md`.

## Run

Requirements:

- Windows 10/11 x64;
- Python 3 with Tkinter;
- .NET 8 Desktop/Runtime for the included sensor helper;
- Android Platform Tools with `adb.exe` on `PATH`;
- the Python packages listed in `requirements.txt`.

For a completely console-free launch, double-click `run_app.vbs`. `run_app.bat` also starts the GUI through `pythonw.exe`, although Windows may show the batch console for a fraction of a second. Use `run_app_debug.bat` only when a hidden startup error needs to be seen.

```powershell
python .\app.py
```

<img width="1452" height="965" alt="image" src="https://github.com/user-attachments/assets/6f316dbf-dfb1-427b-998d-6b434f7e81a5" />

<img width="1452" height="960" alt="image" src="https://github.com/user-attachments/assets/d0dedf8a-e8ce-4190-ad60-cc44916e0e4c" />



Install the small GUI dependencies when needed with:

```powershell
python -m pip install -r .\requirements.txt
```

Preferences are stored in the generated `settings.json` (ignored by Git). **Start with Windows** writes only the current user's standard `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` entry and can be removed again from the same checkbox. It does not disable UAC. When enabled, **Connect to LCD on launch** still targets only `1234567890ABCDEF`; **Start LHM after connection** starts the normal helper path after that fixed connection succeeds.

**Start LHM after connection** applies to every successful connection, including a later manual reconnect after the LCD finishes booting. Saving the option while already connected also schedules the helper immediately. The activity log records `AUTO LHM scheduled`, `starting`, `skipped`, or `canceled`, so startup behavior is not silent.

## Current limitation

Manual values remain available. Live LHM `0x15` updates reuse one TCP connection for the live session, matching the physically successful persistent-socket test. The socket is opened lazily on the first live frame and is closed on Stop, disconnect, reboot, reconnect, application close, transport failure, or before an ACK-bearing persistent `0x12` command. Manual/persistent commands continue to use their isolated one-shot transaction and exact ACK validation.

The LibreHardwareMonitor-backed helper is under `sensor_helper/`. The main Python/ADB process remains non-administrative; one-shot probes use a short-lived elevated helper and live mode uses one persistent elevated helper. Evidence is written under `logs/`.

The **Start LHM live...** test uses one persistent elevated helper at a two-second cadence. It pairs P-core clocks with their two logical-thread load sensors and E-core clocks one-to-one, then sends the core-load-weighted clock as a non-persistent CPU-frequency update. The highest-loaded core and its clock remain logged as comparison evidence but are not transmitted. The compact JSONL evidence includes both candidates, total load, the encoded value, strategy name, and cumulative helper process CPU time. **Stop LHM**, disconnect, reboot, and window close create a stop sentinel; the helper exits after its current sampling interval. This remains a candidate-semantic test, not a finalized definition of whole-CPU frequency.

Live mode supports numeric modes 1-7. CPU frequency uses the load-weighted physical-core clock; GPU frequency, temperature, and usage use LHM `GPU Core`; CPU temperature uses CPU Package; CPU usage uses CPU Total; RAM usage uses Windows `GlobalMemoryStatusEx.dwMemoryLoad` for cheap physical-memory load. The native RAM counter is intentional: enabling LHM's complete Memory group also walks DIMM/SPD data and made a compact test exceed 30 seconds. One helper snapshot contains every value and updates every dashboard card. Optional cycling changes only the value encoded from the next complete snapshot, so it adds no per-mode process or poll.

Completed live-helper scratch logs are removed after a clean stop because the application session JSONL already records the compact reading and transmitted frame. Cleanup exists on both sides: Python handles normal Stop/Exit, and the helper removes its own scratch files after an owner-death shutdown. The main session logger rotates at 5 MiB and keeps two older segments, bounding one continuously running session to roughly 15 MiB without splitting JSON records. **Clean old logs...** previews a retention action, asks for confirmation, protects the active files, and keeps the newest 10 sessions, 5 helper streams, and 5 one-shot probes. New helpers also receive the GUI owner PID and exit automatically if that GUI disappears.

After stopping live updates, **Read LCD UI** performs a read-only `uiautomator` hierarchy dump from only the fixed HAF serial. It reads the active frequency `TextView` and compares it with the latest expected value using the APK's two-decimal rounding. This takes about four seconds and verifies Android view-tree state, not guaranteed physical panel scanout; it is therefore deliberately unavailable while either live source is running.

The same probe also samples Windows `Processor Information(_Total)` counters. It records nominal frequency, processor performance, processor utility, processor time, an active-frequency estimate, and a throughput-equivalent diagnostic (`nominal MHz * utility / 100`). The throughput-equivalent value is not a measured clock and cannot be forwarded to the LCD.

## Important device limitation

This build intentionally targets only ADB serial `1234567890ABCDEF`, the development HAF Iris unit. Change and revalidate `TARGET_SERIAL` in `haf_device.py` before attempting to use another unit. It never falls back to the first attached ADB device.

## Source, protocol, and licensing

The Python application source and C# helper source are included. Rebuild the helper with:

```powershell
dotnet build .\sensor_helper\HafCpuSensors.csproj -c Release
```

See `protocol.md` for the recovered wire protocol and evidence boundaries. Third-party licenses and credits are in `THIRD_PARTY_NOTICES.md` and `licenses/`.

## License and project status

The original Python, C#, PowerShell, and launcher source in this project is
licensed under the Mozilla Public License 2.0. See `LICENSE`. Third-party
components retain their own licenses and notices.

The project is an unofficial community effort and is not affiliated with or
endorsed by Cooler Master. Cooler Master, HAF, and related names and marks
belong to their respective owners.

The bundled V2/STW emblem artwork remains outside the MPL-2.0 grant and is
subject to the good-faith, no-monetary-gain, and no-self-promotion conditions
described in `ASSET_NOTICE.md`.
