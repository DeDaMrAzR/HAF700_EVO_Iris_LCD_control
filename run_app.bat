@echo off
rem This Source Code Form is subject to the terms of the Mozilla Public
rem License, v. 2.0. If a copy of the MPL was not distributed with this
rem file, You can obtain one at https://mozilla.org/MPL/2.0/.
cd /d "%~dp0"
rem Normal launches use pythonw so a console does not remain behind the GUI.
rem A batch file itself may flash very briefly; run_app.vbs avoids even that.
if exist "%LOCALAPPDATA%\Python\bin\pythonw.exe" (
  start "" "%LOCALAPPDATA%\Python\bin\pythonw.exe" "%~dp0app.py"
) else (
  start "" pythonw.exe "%~dp0app.py"
)
