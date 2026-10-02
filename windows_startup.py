# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Explicit per-user Windows logon registration for the Iris GUI."""

from __future__ import annotations

import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Haf700EvoIris"


def command_for(app_path: Path) -> str:
    # pythonw keeps a console window from flashing at logon. During source-tree
    # development the exact interpreter path is recorded so Windows does not
    # accidentally select a different Python installation later.
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    executable = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{executable}" "{app_path.resolve()}" --startup'


def is_enabled(app_path: Path) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, VALUE_NAME)
        return str(value) == command_for(app_path)
    except FileNotFoundError:
        return False


def set_enabled(app_path: Path, enabled: bool) -> None:
    # HKCU Run affects only this Windows user and needs no administrator rights.
    # We never disable UAC or elevate the complete GUI here.
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command_for(app_path))
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
