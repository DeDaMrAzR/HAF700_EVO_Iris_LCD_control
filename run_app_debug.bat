@echo off
rem This Source Code Form is subject to the terms of the Mozilla Public
rem License, v. 2.0. If a copy of the MPL was not distributed with this
rem file, You can obtain one at https://mozilla.org/MPL/2.0/.
cd /d "%~dp0"
rem Diagnostic launcher: keep stdout/stderr visible if pythonw hides a startup
rem exception. This is intentionally not used for normal or Windows-logon runs.
if exist "%LOCALAPPDATA%\Python\bin\python.exe" (
  "%LOCALAPPDATA%\Python\bin\python.exe" app.py
) else (
  python.exe app.py
)
if errorlevel 1 pause
