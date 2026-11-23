# HAF 700 EVO Iris LCD Control

An unofficial Windows app for the Cooler Master HAF 700 EVO Iris LCD. Show live PC readings on the case display, customize the screen order, and control the LCD from your desktop.

[Download the latest release](https://github.com/DeDaMrAzR/HAF700_EVO_Iris_LCD_control/releases/latest)

<img width="1446" height="958" alt="HAF 700 EVO Iris LCD Control dashboard" src="https://github.com/user-attachments/assets/31e23292-b16b-415d-88a1-551ef617c378" />

## Features

- Show CPU and GPU frequency, temperature, and usage, plus RAM usage and CPU fan speed.
- Arrange up to eight display slots. Cycle through them automatically or use **Next**.
- Keep the ring animation moving at normal speed during long live sessions.
- Use **LCD ON** and **LCD OFF** to play the built-in startup and shutdown animations.
- Start with Windows, connect automatically, and close the window to the notification area.

## Installation

1. Download and extract the [latest Windows ZIP](https://github.com/DeDaMrAzR/HAF700_EVO_Iris_LCD_control/releases/latest).
2. On Windows 10 or 11 (64-bit), install [Python for Windows](https://www.python.org/downloads/windows/) with Tkinter, the [.NET 8 Runtime for Windows x64](https://dotnet.microsoft.com/en-us/download/dotnet/8.0), and [Android SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools). Add the Platform-Tools folder to your Windows PATH.
3. Open PowerShell in the extracted folder and install the Python dependencies:

   ```powershell
   python -m pip install -r .\requirements.txt
   ```

4. Double-click `run_app.vbs`.

## Using the LCD

1. Select **Connect**, then **Start LHM live**. Windows may ask for permission to read hardware sensors.
2. Choose the display order. Set unused slots to **Off**. Enable **Cycle selected displays** to rotate automatically, or use **Next** to change screens yourself.
3. In **Startup and window**, choose the options you want and select **Save preferences**.

Use **Clean old logs...** to preview and remove older activity logs.

## License and credits

This project is licensed under the [Mozilla Public License 2.0](LICENSE). Hardware readings use [Libre Hardware Monitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor). See the [third-party notices](THIRD_PARTY_NOTICES.md) and [artwork notice](ASSET_NOTICE.md) for credits and terms.

This is a community project independent of Cooler Master.
