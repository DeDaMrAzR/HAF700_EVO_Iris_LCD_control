# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Read Windows CPU performance counters without elevation."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "sensor_helper" / "read_windows_cpu_counters.ps1"
LOG_DIR = Path(__file__).resolve().parent / "logs"


def calculate_estimates(nominal_mhz: float, performance_percent: float, utility_percent: float):
    return {
        "active_frequency_estimate_mhz": nominal_mhz * performance_percent / 100.0,
        "throughput_equivalent_mhz": nominal_mhz * utility_percent / 100.0,
    }


def read_once(timeout_seconds: float = 15.0) -> dict[str, object]:
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
        ],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Windows CPU counter reader failed")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Windows CPU counter reader returned no JSON")
    snapshot = json.loads(lines[-1])
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    evidence_path = LOG_DIR / f"windows_cpu_counters_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
    evidence_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
    snapshot["evidence_path"] = str(evidence_path)
    return snapshot
