# HAF 700 EVO Iris LCD Control

Current release: **[v0.0.3](https://github.com/DeDaMrAzR/HAF700_EVO_Iris_LCD_control/releases/tag/v0.0.3)**

An unofficial Windows controller for the Cooler Master HAF 700 EVO Iris LCD.
It replaces the MasterPlus telemetry path while preserving the stock Android
application and firmware in the LCD module. 

<img width="1446" height="958" alt="HAF 700 EVO Iris LCD Control v0.0.3" src="https://github.com/user-attachments/assets/31e23292-b16b-415d-88a1-551ef617c378" />

## Features

- Live dashboard with current, session-minimum, and session-maximum values.
- Eight configurable display-order slots. Each slot can contain any live metric
  or `Off`; timed cycling and **Next** use the same sequence.
- Gentle **LCD OFF** and **LCD ON** controls using the stock shutdown and startup
  animations, with power-state gating to prevent invalid actions.
- Automatic connection and telemetry startup, optional Windows-logon startup,
  start-minimized behavior, and notification-area operation.
- Manual LCD values and physically validated numeric renderer modes 1–13 for
  diagnostics and experimentation.
- Confirmation-gated LCD-controller reboot (if ADB is available) and read-only LCD UI inspection.
- Detailed bounded activity/JSONL logging with explicit sensor, frame, socket,
  ADB, power-transition, and error records.
- No firmware flashing, NAND access, APK replacement or MasterPlus dependency.

### Live metrics

| Display | Source |
| --- | --- |
| CPU frequency | LibreHardwareMonitor load-weighted physical-core clock |
| GPU frequency | LibreHardwareMonitor GPU Core clock |
| CPU temperature | LibreHardwareMonitor CPU Package |
| GPU temperature | LibreHardwareMonitor GPU Core temperature |
| CPU usage | LibreHardwareMonitor CPU Total |
| GPU usage | LibreHardwareMonitor GPU Core load |
| RAM usage | Windows physical-memory load |
| CPU fan | LibreHardwareMonitor motherboard fan source |

All dashboard values come from one persistent helper snapshot every two seconds (LCD limitation).
Changing the active display or cycle order does not start another sensor process.

## Installation

Requirements:

- Windows 10/11 x64;
- [Python 3 for Windows](https://www.python.org/downloads/windows/) with Tkinter;
- [Microsoft .NET 8 Runtime for Windows x64](https://dotnet.microsoft.com/en-us/download/dotnet/8.0) for the included sensor helper;
- [Android SDK Platform-Tools for Windows](https://developer.android.com/tools/releases/platform-tools), with `adb.exe` available on `PATH`;
- the Python packages listed in `requirements.txt`.

The release ZIP is a source/runtime package and does not bundle Python, .NET,
or Android Platform-Tools.

1. Download and extract the ZIP from the
   [latest release](https://github.com/DeDaMrAzR/HAF700_EVO_Iris_LCD_control/releases/latest).
2. Install the Python dependencies from the extracted directory:

   ```powershell
   python -m pip install -r .\requirements.txt
   ```

3. Ensure `adb.exe` is available on `PATH` and the Iris controller appears in
   `adb devices` as serial `1234567890ABCDEF`.
4. Double-click `run_app.vbs` for a console-free launch.

`run_app.bat` also starts through `pythonw.exe`, although its batch window may
appear briefly. Use `run_app_debug.bat` only to diagnose a hidden startup error.
The application can also be started directly:

```powershell
python .\app.py
```

## First-run setup

On a first run the application starts without automatically connecting.
Connect to the LCD, start LHM telemetry, choose the required display order, and
then save preferences. The saved options can subsequently connect to the LCD,
start LHM, minimize to the notification area, and start with Windows.

Preferences are stored in the generated `settings.json`. **Start with Windows** writes only the current user's standard `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` entry and can be removed again from the same checkbox. It does not disable UAC. When enabled, **Connect to LCD on launch** still targets only `1234567890ABCDEF`; **Start LHM after connection** starts the normal helper path after that fixed connection succeeds.

**Start LHM after connection** applies to every successful connection, including a later manual reconnect after the LCD finishes booting. Saving the option while already connected also schedules the helper immediately. The activity log records `AUTO LHM scheduled`, `starting`, `skipped`, or `canceled`, so startup behavior is not silent.

## Display order and automatic cycling

The eight numbered slots define both inclusion and order. Select a live metric
in a slot or choose `Off` to exclude that position. Repeated metrics are allowed.
When cycling is enabled, the timeout advances through this exact sequence.
**Next** advances through the same sequence whether timed cycling is enabled or
disabled. Changes apply during the current live session and are persisted by
**Save preferences**.

## Telemetry, elevation, and logs

The Python GUI and ADB controller remain non-administrative. LibreHardwareMonitor
uses one persistent elevated .NET helper because low-level sensor access requires
it. Depending on Windows UAC settings, starting telemetry may therefore display
one elevation prompt.

Live updates reuse one TCP connection and one two-second sensor snapshot. Stop,
disconnect, reboot, transport failure, and application exit close the connection
and stop the helper cleanly. CPU fan selection prefers a motherboard fan labelled
as CPU; if labels are generic, it uses a fallback only when exactly one non-GPU
fan is active. The exact selected source is recorded in the activity log.

Session JSONL logs are stored under `logs/`, rotate at 5 MiB, and retain two
older segments. **Clean old logs...** previews its retention action and asks for
confirmation before removing old files.

## Known limitations

- This release intentionally targets only ADB serial `1234567890ABCDEF` and
  never falls back to another attached Android device. Supporting configurable
  device selection requires separate validation.
- Motherboard fan labels are vendor-specific. Check the logged sensor identity
  if CPU fan is unavailable or does not match the expected header.
- Successful transmission proves that a frame reached the Android socket, not
  that the physical panel presented every intermediate frame.
- **Read LCD UI** is a slow read-only diagnostic of the Android view tree, not
  physical framebuffer acknowledgement, and is unavailable during live updates.

## Source, protocol, and licensing

The Python application source and C# helper source are included. Rebuild the helper with:

```powershell
dotnet build .\sensor_helper\HafCpuSensors.csproj -c Release
```

See `protocol.md` for the recovered wire protocol and evidence boundaries. Third-party licenses and credits are in `THIRD_PARTY_NOTICES.md` and `licenses/`.


## Licence and credits

The original Python, C#, PowerShell, and launcher source in this project is
licensed under the Mozilla Public License 2.0. See `LICENSE`. Third-party
components retain their own licenses and notices.

Hardware telemetry is provided through `LibreHardwareMonitorLib` from the
[Libre Hardware Monitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor)
open-source project. Credit and thanks go to its maintainers and contributors
for the hardware-monitoring library that makes the live sensor integration
possible. Libre Hardware Monitor remains under its own license; the applicable
notice and license text are included in `THIRD_PARTY_NOTICES.md` and `licenses/`.

The project is an unofficial community effort and is not affiliated with or
endorsed by Cooler Master. Cooler Master, HAF, and related names and marks
belong to their respective owners.

The bundled V2/STW emblem artwork remains outside the MPL-2.0 grant and is
subject to the good-faith, no-monetary-gain, and no-self-promotion conditions
described in `ASSET_NOTICE.md`.
