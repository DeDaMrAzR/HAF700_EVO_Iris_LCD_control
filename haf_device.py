# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Narrow ADB-forwarded transport for the in-scope HAF Iris device."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from haf_protocol import EXPECTED_ACK

TARGET_SERIAL = "1234567890ABCDEF"
LOCAL_PORT = 18888
DEVICE_PORT = 9900
LCD_VALUE_RESOURCE = "com.magic.box:id/base_view_layout_ghzValue"
STOCK_PACKAGE = "com.magic.box"
STOCK_ACTIVITY = "com.magic.box/.ui.SplashActivity"
SHUTDOWN_WAIT_SECONDS = 35.0
WAKE_STABILIZATION_SECONDS = 3.0
STARTUP_WAIT_SECONDS = 30.0


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def parse_lcd_ui_dump(output: str) -> dict[str, str]:
    start = output.find("<?xml")
    end = output.find("</hierarchy>")
    if start < 0 or end < 0:
        raise ValueError("uiautomator output contains no hierarchy XML")
    root = ET.fromstring(output[start : end + len("</hierarchy>")])
    by_resource = {node.attrib.get("resource-id", ""): node.attrib.get("text", "") for node in root.iter("node")}
    if LCD_VALUE_RESOURCE not in by_resource:
        raise ValueError("LCD value TextView is absent from the active UI hierarchy")
    return {
        "value": by_resource[LCD_VALUE_RESOURCE],
        "title": by_resource.get("com.magic.box:id/base_view_layout_ghzTitle", ""),
        "unit": by_resource.get("com.magic.box:id/base_view_layout_ghzUnit", ""),
    }


class EventLog:
    def __init__(
        self,
        path: Path,
        listener=None,
        *,
        max_bytes: int = 5 * 1024 * 1024,
        backup_count: int = 2,
    ) -> None:
        self.path = path
        self.listener = listener
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self._write_lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, **details: object) -> None:
        record = {"timestamp": timestamp(), "event": event, **details}
        line = json.dumps(record, sort_keys=True) + "\n"
        # Sensor and transport threads share this logger. Rotate under the same
        # lock used for writing so no JSON record is split or lost between files.
        with self._write_lock:
            current_size = self.path.stat().st_size if self.path.exists() else 0
            if current_size and current_size + len(line.encode("utf-8")) > self.max_bytes:
                self._rotate()
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(line)
        if self.listener is not None:
            try:
                self.listener(record)
            except Exception:
                # UI/log listeners must never interfere with device transport.
                pass

    def _rotate(self) -> None:
        """Keep the current file plus a small fixed number of older segments."""
        if self.backup_count <= 0:
            self.path.unlink(missing_ok=True)
            return
        oldest = self._part_path(self.backup_count)
        oldest.unlink(missing_ok=True)
        for index in range(self.backup_count - 1, 0, -1):
            source = self._part_path(index)
            if source.exists():
                source.replace(self._part_path(index + 1))
        if self.path.exists():
            self.path.replace(self._part_path(1))

    def _part_path(self, index: int) -> Path:
        return self.path.with_name(f"{self.path.stem}.part{index}{self.path.suffix}")


class HafDevice:
    def __init__(self, log: EventLog) -> None:
        self.log = log
        self.connected = False
        self._live_socket: socket.socket | None = None
        self._live_socket_lock = threading.Lock()

    def _close_live_socket(self, reason: str) -> None:
        with self._live_socket_lock:
            if self._live_socket is None:
                return
            try:
                self._live_socket.close()
            finally:
                self._live_socket = None
                self.log.write("live_socket_closed", serial=TARGET_SERIAL, reason=reason)

    def close_live_session(self, reason: str = "live_stop") -> None:
        """End only the reusable live socket; retain the fixed ADB forward."""
        self._close_live_socket(reason)

    def _send_live_persistent(self, frame: bytes) -> None:
        with self._live_socket_lock:
            if self._live_socket is None:
                self._live_socket = socket.create_connection(("127.0.0.1", LOCAL_PORT), timeout=3.0)
                self._live_socket.settimeout(3.0)
                self.log.write(
                    "live_socket_opened",
                    serial=TARGET_SERIAL,
                    local_port=LOCAL_PORT,
                    device_port=DEVICE_PORT,
                )
            try:
                self._live_socket.sendall(frame)
            except Exception:
                try:
                    self._live_socket.close()
                finally:
                    self._live_socket = None
                raise

    @staticmethod
    def _adb() -> str:
        executable = shutil.which("adb")
        if executable is None:
            raise RuntimeError("adb.exe was not found on PATH")
        return executable

    def _run_adb(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        command = [self._adb(), "-s", TARGET_SERIAL, *arguments]
        # The normal GUI is launched with pythonw. Hide ADB's console window as
        # well so multi-step ON/OFF operations do not flash several shells.
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def connect(self) -> None:
        self._close_live_socket("reconnect")
        # An ADB forward can be created even when nothing is listening on the
        # Android side. Check the actual stock server first so "Connected" is
        # meaningful and frames cannot disappear into a dead forward.
        self._wait_for_stock_server(3.0)
        result = self._run_adb("forward", f"tcp:{LOCAL_PORT}", f"tcp:{DEVICE_PORT}")
        if result.returncode != 0:
            self.log.write("connect_failed", returncode=result.returncode, stderr=result.stderr.strip())
            raise RuntimeError(result.stderr.strip() or "ADB forward failed")
        self.connected = True
        self.log.write(
            "connected",
            serial=TARGET_SERIAL,
            local_port=LOCAL_PORT,
            device_port=DEVICE_PORT,
        )

    def disconnect(self) -> None:
        self._close_live_socket("disconnect")
        if not self.connected:
            return
        result = self._run_adb("forward", "--remove", f"tcp:{LOCAL_PORT}")
        self.connected = False
        self.log.write(
            "disconnected",
            serial=TARGET_SERIAL,
            returncode=result.returncode,
            stderr=result.stderr.strip(),
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "ADB forward removal failed")

    def reboot(self) -> None:
        """Remove this app's forward, then reboot only the fixed HAF serial."""
        self._close_live_socket("reboot")
        cleanup = self._run_adb("forward", "--remove", f"tcp:{LOCAL_PORT}")
        self.connected = False
        self.log.write(
            "pre_reboot_forward_cleanup",
            serial=TARGET_SERIAL,
            returncode=cleanup.returncode,
            stderr=cleanup.stderr.strip(),
        )
        if cleanup.returncode != 0:
            raise RuntimeError(cleanup.stderr.strip() or "Could not remove HAF forward before reboot")
        result = self._run_adb("reboot")
        self.log.write(
            "reboot_requested",
            serial=TARGET_SERIAL,
            returncode=result.returncode,
            stdout=result.stdout.strip(),
            stderr=result.stderr.strip(),
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "HAF reboot command failed")

    def _send_keyevent(self, keycode: int, step: str) -> None:
        """Send one Android key only to the fixed HAF serial and record the result."""
        result = self._run_adb("shell", "input", "keyevent", str(keycode))
        self.log.write(
            "power_transition_keyevent",
            serial=TARGET_SERIAL,
            step=step,
            keycode=keycode,
            returncode=result.returncode,
            stderr=result.stderr.strip(),
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"Android keyevent {keycode} failed")

    def read_wakefulness(self) -> str:
        """Return Android's current Awake/Asleep state for GUI gating."""
        result = self._run_adb("shell", "dumpsys", "power")
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Could not read Android power state")
        for line in result.stdout.splitlines():
            if "mWakefulness=" in line:
                wakefulness = line.split("mWakefulness=", 1)[1].strip()
                self.log.write("lcd_power_state_read", serial=TARGET_SERIAL, wakefulness=wakefulness)
                return wakefulness
        raise RuntimeError("Android power state did not contain mWakefulness")

    def _stock_process_running(self) -> bool:
        result = self._run_adb("shell", "pidof", STOCK_PACKAGE)
        return result.returncode == 0 and bool(result.stdout.strip())

    def _wait_for_stock_server(self, timeout_seconds: float = 10.0) -> None:
        """Wait until the automatically restored HOME app owns port 9900."""
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            result = self._run_adb("shell", "netstat", "-an")
            if result.returncode == 0 and any(
                ":9900" in line and "LISTEN" in line for line in result.stdout.splitlines()
            ):
                self.log.write("stock_server_ready", serial=TARGET_SERIAL, port=DEVICE_PORT)
                return
            time.sleep(0.5)
        raise RuntimeError("Stock LCD app did not reopen port 9900 within the readiness window")

    def gentle_power_off(self, shutdown_wait_seconds: float = SHUTDOWN_WAIT_SECONDS) -> str:
        """Play the stock shutdown animation, then turn the physical LCD off.

        The 35-second delay is deliberately conservative. It is the interval
        physically proven to let the bundled shutdown video finish before the
        Power event removes the panel backlight.
        """
        self._close_live_socket("gentle_power_off")
        self.log.write(
            "gentle_power_off_started",
            serial=TARGET_SERIAL,
            shutdown_wait_seconds=shutdown_wait_seconds,
        )
        initial_wakefulness = self.read_wakefulness()
        if initial_wakefulness.lower() == "asleep":
            self.log.write("gentle_power_off_already_asleep", serial=TARGET_SERIAL)
            return initial_wakefulness
        self._send_keyevent(25, "stock_shutdown_video")
        time.sleep(shutdown_wait_seconds)
        self._send_keyevent(26, "physical_display_off")
        time.sleep(1.0)
        wakefulness = self.read_wakefulness()
        self.log.write("gentle_power_off_completed", serial=TARGET_SERIAL, wakefulness=wakefulness)
        if wakefulness.lower() != "asleep":
            raise RuntimeError(f"LCD power-off was not confirmed; Android is {wakefulness}")
        return wakefulness

    def gentle_power_on(
        self,
        wake_stabilization_seconds: float = WAKE_STABILIZATION_SECONDS,
        startup_wait_seconds: float = STARTUP_WAIT_SECONDS,
    ) -> str:
        """Wake Android and use the stock HOME activity to play start.mp4."""
        self._close_live_socket("gentle_power_on")
        self.log.write(
            "gentle_power_on_started",
            serial=TARGET_SERIAL,
            wake_stabilization_seconds=wake_stabilization_seconds,
            startup_wait_seconds=startup_wait_seconds,
        )
        wakefulness = self.read_wakefulness()
        if wakefulness.lower() != "awake":
            self._send_keyevent(26, "physical_display_on")
            time.sleep(wake_stabilization_seconds)
            wakefulness = self.read_wakefulness()
        if wakefulness.lower() != "awake":
            raise RuntimeError(f"LCD wake was not confirmed; Android is {wakefulness}")

        stop_result = self._run_adb("shell", "am", "force-stop", STOCK_PACKAGE)
        if stop_result.returncode != 0:
            raise RuntimeError(stop_result.stderr.strip() or "Could not stop the stock LCD app")

        # SplashActivity is the device's HOME activity. Android normally
        # recreates it automatically after force-stop. Starting it explicitly
        # at the same time can create a second instance; both call initSocket,
        # and the failed second bind shuts down the valid port-9900 listener.
        try:
            self._wait_for_stock_server()
            launch_path = "android_home_auto_restore"
        except RuntimeError:
            if self._stock_process_running():
                raise
            start_result = self._run_adb("shell", "am", "start", "-n", STOCK_ACTIVITY)
            if start_result.returncode != 0:
                raise RuntimeError(start_result.stderr.strip() or "Could not start the stock LCD app")
            self._wait_for_stock_server()
            launch_path = "explicit_fallback"
        self.log.write("stock_startup_activity_ready", serial=TARGET_SERIAL, launch_path=launch_path)

        # Do not reopen the protocol socket during this interval: a display
        # frame can replace the video view before the startup animation ends.
        time.sleep(startup_wait_seconds)
        self.log.write(
            "gentle_power_on_completed",
            serial=TARGET_SERIAL,
            wakefulness=wakefulness,
            stock_server_ready=True,
        )
        return wakefulness

    def read_lcd_ui(self) -> dict[str, str]:
        """Read the active Android view-tree value; this does not prove physical scanout."""
        result = self._run_adb("shell", "uiautomator", "dump", "/dev/tty")
        if result.returncode != 0:
            self.log.write("lcd_ui_read_failed", stderr=result.stderr.strip())
            raise RuntimeError(result.stderr.strip() or "uiautomator hierarchy read failed")
        state = parse_lcd_ui_dump(result.stdout)
        self.log.write("lcd_ui_read", **state, evidence_level="android_view_tree")
        return state

    def send(self, frame: bytes, *, expect_ack: bool) -> bytes:
        if not self.connected:
            raise RuntimeError("Connect to the HAF device first")
        self.log.write(
            "frame_send_started",
            serial=TARGET_SERIAL,
            frame_hex=frame.hex().upper(),
            expect_ack=expect_ack,
        )
        try:
            if expect_ack:
                self._close_live_socket("persistent_command")
                with socket.create_connection(("127.0.0.1", LOCAL_PORT), timeout=3.0) as connection:
                    connection.settimeout(3.0)
                    connection.sendall(frame)
                    acknowledgement = connection.recv(64)
            else:
                self._send_live_persistent(frame)
                acknowledgement = b""
        except Exception as exc:
            self.log.write(
                "frame_send_failed",
                serial=TARGET_SERIAL,
                frame_hex=frame.hex().upper(),
                expect_ack=expect_ack,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        self.log.write(
            "frame_sent",
            serial=TARGET_SERIAL,
            frame_hex=frame.hex().upper(),
            expect_ack=expect_ack,
            ack_hex=acknowledgement.hex().upper(),
            ack_matches=(acknowledgement == EXPECTED_ACK) if expect_ack else None,
        )
        if expect_ack and acknowledgement != EXPECTED_ACK:
            raise RuntimeError(f"Unexpected acknowledgement: {acknowledgement.hex().upper() or '<empty>'}")
        return acknowledgement
