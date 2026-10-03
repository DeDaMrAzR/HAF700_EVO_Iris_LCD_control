# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Persistent preferences and metric/cycle state for the Iris GUI."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

CPU_FREQUENCY = "CPU frequency"
GPU_FREQUENCY = "GPU frequency"
CPU_TEMPERATURE = "CPU temperature"
GPU_TEMPERATURE = "GPU temperature"
CPU_USAGE = "CPU usage"
GPU_USAGE = "GPU usage"
RAM_USAGE = "RAM usage"
CPU_FAN = "CPU fan"
LIVE_MODES = (
    CPU_FREQUENCY,
    GPU_FREQUENCY,
    CPU_TEMPERATURE,
    GPU_TEMPERATURE,
    CPU_USAGE,
    GPU_USAGE,
    RAM_USAGE,
    CPU_FAN,
)
# Historical internal alias retained so older local imports do not break.
LIVE_CPU_MODES = LIVE_MODES


@dataclass
class AppSettings:
    """Small, intentionally boring JSON-backed preferences model.

    Keeping this independent from Tkinter means settings can be tested without
    opening a window and can later be reused by a packaged Windows build.
    """
    cycle_enabled: bool = False
    cycle_seconds: int = 15
    cycle_modes: tuple[str, ...] = LIVE_CPU_MODES
    minimize_to_tray: bool = True
    start_minimized: bool = False
    auto_connect: bool = False
    auto_start_lhm: bool = False
    start_with_windows: bool = False

    @classmethod
    def load(cls, path: Path) -> "AppSettings":
        # A missing or damaged settings file should never prevent the recovery
        # controls from opening. Fall back to conservative, inert defaults.
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            has_saved_modes = "cycle_modes" in data
            modes = tuple(mode for mode in data.get("cycle_modes", LIVE_CPU_MODES) if mode in LIVE_CPU_MODES)
            # The first QoL build stored only the three CPU modes because those
            # were all it could acquire. Upgrade that exact legacy default to
            # the new complete 1-7 sequence; custom future subsets stay intact.
            if modes == (CPU_FREQUENCY, CPU_TEMPERATURE, CPU_USAGE):
                modes = LIVE_CPU_MODES
            # v0.0.2 stored the exact seven-mode default. Extend only that
            # known default; a user's custom subset and order remain theirs.
            legacy_seven = LIVE_CPU_MODES[:-1]
            if modes == legacy_seven:
                modes = LIVE_CPU_MODES
            return cls(
                cycle_enabled=bool(data.get("cycle_enabled", False)),
                cycle_seconds=max(5, min(300, int(data.get("cycle_seconds", 15)))),
                # An explicitly empty list means the user turned every slot
                # Off. Only a missing setting receives the default sequence.
                cycle_modes=modes if has_saved_modes else LIVE_CPU_MODES,
                minimize_to_tray=bool(data.get("minimize_to_tray", True)),
                start_minimized=bool(data.get("start_minimized", False)),
                auto_connect=bool(data.get("auto_connect", False)),
                auto_start_lhm=bool(data.get("auto_start_lhm", False)),
                start_with_windows=bool(data.get("start_with_windows", False)),
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")


@dataclass
class MetricStats:
    """Current and session extrema for one value shown on the dashboard."""
    current: float | None = None
    minimum: float | None = None
    maximum: float | None = None

    def update(self, value: float) -> None:
        self.current = value
        self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)

    def reset_extrema(self) -> None:
        self.minimum = self.current
        self.maximum = self.current


class DisplayCycle:
    """A UI-independent countdown for rotating through selected LCD modes."""
    def __init__(self, modes: tuple[str, ...], seconds: int, active: str) -> None:
        self.modes = modes or LIVE_CPU_MODES
        self.seconds = max(5, seconds)
        self.index = self.modes.index(active) if active in self.modes else 0
        self.remaining = self.seconds

    @property
    def active(self) -> str:
        return self.modes[self.index]

    def tick(self) -> bool:
        # Return True only on the second where the caller must switch mode. The
        # Tk event loop owns the timer; this class deliberately owns no threads.
        self.remaining -= 1
        if self.remaining > 0:
            return False
        self.next()
        return True

    def next(self) -> str:
        self.index = (self.index + 1) % len(self.modes)
        self.remaining = self.seconds
        return self.active
