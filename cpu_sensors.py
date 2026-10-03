# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Read-only client for the workspace-local LibreHardwareMonitor CPU helper."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
HELPER_DLL = APP_DIR / "sensor_helper" / "bin" / "Release" / "net8.0" / "HafCpuSensors.dll"
ELEVATED_PROBE_SCRIPT = APP_DIR / "sensor_helper" / "run_elevated_probe.ps1"
ELEVATED_STREAM_SCRIPT = APP_DIR / "sensor_helper" / "run_elevated_stream.ps1"
LOG_DIR = APP_DIR / "logs"


def select_load_weighted_frequency(snapshot: dict) -> int:
    """Return the rounded LHM load-weighted candidate selected for LCD transmission."""
    weighted = snapshot.get("load_weighted_clock_mhz")
    if weighted is None:
        raise ValueError("LHM snapshot has no load-weighted clock")
    return round(float(weighted))


def select_cpu_package_temperature(snapshot: dict) -> int:
    """Return the rounded LHM CPU Package temperature selected for LCD transmission."""
    temperature = snapshot.get("cpu_package_temperature_c")
    if temperature is None:
        raise ValueError("LHM snapshot has no CPU Package temperature")
    return round(float(temperature))


def select_cpu_total_load(snapshot: dict) -> int:
    """Return rounded LHM CPU Total load for mode-5 LCD transmission."""
    load = snapshot.get("cpu_total_load_percent")
    if load is None:
        raise ValueError("LHM snapshot has no CPU Total load")
    value = round(float(load))
    if not 0 <= value <= 100:
        raise ValueError(f"LHM CPU Total load {value}% is outside 0-100%")
    return value


def _select_bounded(snapshot: dict, field: str, label: str, minimum: int, maximum: int) -> int:
    """Round one compact helper value and reject bad data before transport."""
    raw = snapshot.get(field)
    if raw is None:
        raise ValueError(f"LHM snapshot has no {label}")
    value = round(float(raw))
    if not minimum <= value <= maximum:
        raise ValueError(f"LHM {label} {value} is outside {minimum}-{maximum}")
    return value


def select_gpu_core_frequency(snapshot: dict) -> int:
    return _select_bounded(snapshot, "gpu_core_clock_mhz", "GPU Core clock", 0, 6000)


def select_gpu_core_temperature(snapshot: dict) -> int:
    return _select_bounded(snapshot, "gpu_core_temperature_c", "GPU Core temperature", 0, 100)


def select_gpu_core_load(snapshot: dict) -> int:
    return _select_bounded(snapshot, "gpu_core_load_percent", "GPU Core load", 0, 100)


def select_memory_load(snapshot: dict) -> int:
    return _select_bounded(snapshot, "memory_load_percent", "Memory load", 0, 100)


def select_cpu_fan_rpm(snapshot: dict) -> int:
    """Return the explicitly selected or sole-active non-GPU fan speed."""
    return _select_bounded(snapshot, "cpu_fan_rpm", "CPU fan", 0, 10000)


def summarize_snapshot(snapshot: dict) -> dict[str, object]:
    sensors = snapshot.get("sensors", [])

    def find(identifier: str):
        return next((sensor for sensor in sensors if sensor.get("sensor_identifier") == identifier), None)

    clocks = []
    for sensor in sensors:
        identifier = str(sensor.get("sensor_identifier", ""))
        if sensor.get("sensor_type") != "Clock" or sensor.get("value") is None:
            continue
        try:
            clock_index = int(identifier.rsplit("/", 1)[-1])
        except ValueError:
            continue
        if identifier.startswith("/intelcpu/0/clock/") and clock_index >= 1:
            clocks.append(sensor)
    average_clock = (
        sum(float(sensor["value"]) for sensor in clocks) / len(clocks) if clocks else None
    )
    return {
        "timestamp": snapshot.get("timestamp"),
        "is_elevated": bool(snapshot.get("is_elevated")),
        "sensor_count": int(snapshot.get("sensor_count", len(sensors))),
        "hardware_name": sensors[0].get("hardware_name") if sensors else None,
        "cpu_total": find("/intelcpu/0/load/0"),
        "cpu_package_temperature": find("/intelcpu/0/temperature/26"),
        "core_average_temperature": find("/intelcpu/0/temperature/1"),
        "live_clock_count": len(clocks),
        "arithmetic_mean_clock_mhz": average_clock,
    }


def read_once(timeout_seconds: float = 15.0) -> tuple[dict, dict[str, object]]:
    if not HELPER_DLL.exists():
        raise RuntimeError(f"CPU sensor helper is not built: {HELPER_DLL}")
    result = subprocess.run(
        ["dotnet", str(HELPER_DLL), "--once"],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"sensor helper exited {result.returncode}")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("sensor helper returned no JSON snapshot")
    snapshot = json.loads(lines[-1])
    return snapshot, summarize_snapshot(snapshot)


def read_once_elevated(timeout_seconds: float = 90.0) -> tuple[dict, dict[str, object], Path]:
    """Request UAC only for the helper and return its file-backed snapshot."""
    if not HELPER_DLL.exists():
        raise RuntimeError(f"CPU sensor helper is not built: {HELPER_DLL}")
    if not ELEVATED_PROBE_SCRIPT.exists():
        raise RuntimeError(f"elevated probe launcher is missing: {ELEVATED_PROBE_SCRIPT}")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    output = LOG_DIR / f"cpu_probe_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.jsonl"
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ELEVATED_PROBE_SCRIPT),
            "-HelperDll",
            str(HELPER_DLL),
            "-OutputPath",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        if result.returncode == 1223 or "canceled" in detail.lower():
            raise RuntimeError("UAC elevation was canceled")
        raise RuntimeError(detail or f"elevated sensor helper exited {result.returncode}")
    if not output.exists():
        raise RuntimeError("elevated helper completed without creating a sensor snapshot")
    lines = [line for line in output.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"elevated helper created an empty snapshot: {output}")
    snapshot = json.loads(lines[-1])
    if not snapshot.get("is_elevated"):
        raise RuntimeError("helper completed but did not obtain a genuinely elevated token")
    return snapshot, summarize_snapshot(snapshot), output


class ElevatedFrequencyStream:
    """One persistent elevated LHM process with file-backed compact snapshots."""

    def __init__(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.output_path = LOG_DIR / f"lhm_telemetry_stream_{stamp}.jsonl"
        self.stop_path = LOG_DIR / f"lhm_telemetry_stream_{stamp}.stop"
        self.process: subprocess.Popen[str] | None = None
        self._line_count = 0

    def start(self) -> None:
        if not HELPER_DLL.exists():
            raise RuntimeError(f"CPU sensor helper is not built: {HELPER_DLL}")
        if not ELEVATED_STREAM_SCRIPT.exists():
            raise RuntimeError(f"elevated stream launcher is missing: {ELEVATED_STREAM_SCRIPT}")
        self.stop_path.unlink(missing_ok=True)
        self.process = subprocess.Popen(
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                str(ELEVATED_STREAM_SCRIPT), "-HelperDll", str(HELPER_DLL),
                "-OutputPath", str(self.output_path), "-StopFile", str(self.stop_path),
                "-OwnerPid", str(os.getpid()),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def read_new(self) -> list[dict]:
        if self.process is None:
            raise RuntimeError("LHM frequency stream has not been started")
        if not self.output_path.exists():
            if self.process.poll() is not None:
                _stdout, stderr = self.process.communicate()
                raise RuntimeError(stderr.strip() or f"elevated helper exited {self.process.returncode}")
            return []
        text = self.output_path.read_text(encoding="utf-8")
        lines = text.splitlines()
        if text and not text.endswith(("\n", "\r")):
            # The elevated helper may be midway through its append operation.
            lines = lines[:-1]
        lines = [line for line in lines if line.strip()]
        new_lines = lines[self._line_count:]
        self._line_count = len(lines)
        return [json.loads(line) for line in new_lines]

    def stop(self, timeout_seconds: float = 0.0) -> None:
        self.stop_path.touch(exist_ok=True)
        if self.process is not None and timeout_seconds > 0:
            try:
                self.process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                # Do not force-kill an elevated helper from the normal GUI. It will
                # observe the sentinel after its current two-second cycle.
                pass
            # The application session JSONL already contains every compact
            # reading and transmitted frame. A normally completed helper file
            # is redundant and was the largest source of log accumulation.
            if self.process.poll() == 0:
                self.output_path.unlink(missing_ok=True)
                self.stop_path.unlink(missing_ok=True)
