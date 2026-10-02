# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Optional system-tray adapter.

The main application does not fail if pystray is absent. This keeps source-tree
development simple while allowing packaged builds to include full tray support.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PIL import Image

try:
    import pystray
except ImportError:  # Covered by the GUI's visible fallback message.
    pystray = None


def available() -> bool:
    return pystray is not None


class TrayController:
    def __init__(
        self,
        icon_path: Path,
        show: Callable[[], None],
        toggle_live: Callable[[], None],
        next_display: Callable[[], None],
        exit_app: Callable[[], None],
    ) -> None:
        self._show = show
        self._icon = None
        if pystray is None:
            return
        # pystray owns a background message loop. Every callback immediately
        # hands work back to Tk through the wrappers supplied by app.py.
        menu = pystray.Menu(
            pystray.MenuItem("Show", lambda _icon, _item: show(), default=True),
            pystray.MenuItem("Start / stop LHM", lambda _icon, _item: toggle_live()),
            pystray.MenuItem("Next display", lambda _icon, _item: next_display()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", lambda _icon, _item: exit_app()),
        )
        self._icon = pystray.Icon("haf700_evo_iris", Image.open(icon_path), "HAF 700 EVO Iris", menu)

    def start(self) -> bool:
        if self._icon is None:
            return False
        self._icon.run_detached()
        return True

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()
