# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Initial HAF 700 EVO Iris control GUI using confirmed protocol behavior."""

from __future__ import annotations

import threading
import tkinter as tk
import sys
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from app_state import AppSettings, DisplayCycle, MetricStats

from cpu_sensors import (
    ElevatedFrequencyStream,
    read_once_elevated,
    select_cpu_fan_rpm,
    select_cpu_package_temperature,
    select_cpu_total_load,
    select_gpu_core_frequency,
    select_gpu_core_load,
    select_gpu_core_temperature,
    select_load_weighted_frequency,
    select_memory_load,
)
from haf_device import (
    EventLog,
    HafDevice,
    SHUTDOWN_WAIT_SECONDS,
    STARTUP_WAIT_SECONDS,
    TARGET_SERIAL,
    WAKE_STABILIZATION_SECONDS,
)
from haf_protocol import (
    MAX_MHZ,
    MAX_TEMPERATURE_C,
    MIN_MHZ,
    MIN_TEMPERATURE_C,
    build_cpu_frequency_frame,
    build_cpu_temperature_frame,
    build_provisional_metric_frame,
)
from windows_cpu_counters import read_once as read_windows_cpu_counters
from windows_startup import is_enabled as startup_is_enabled, set_enabled as set_startup_enabled
from tray_controller import TrayController, available as tray_available
from log_housekeeping import cleanup_candidates, remove_candidates
from version import __version__

FREQUENCY_MODE = "CPU frequency"
GPU_FREQUENCY_MODE = "GPU frequency"
TEMPERATURE_MODE = "CPU temperature"
GPU_TEMPERATURE_MODE = "GPU temperature"
CPU_USAGE_MODE = "CPU usage"
GPU_USAGE_MODE = "GPU usage"
RAM_USAGE_MODE = "RAM usage"
CPU_FAN_MODE = "CPU fan"
LIVE_MODES = (
    FREQUENCY_MODE,
    GPU_FREQUENCY_MODE,
    TEMPERATURE_MODE,
    GPU_TEMPERATURE_MODE,
    CPU_USAGE_MODE,
    GPU_USAGE_MODE,
    RAM_USAGE_MODE,
    CPU_FAN_MODE,
)
CYCLE_SLOT_OFF = "Off"
MODE_CONFIGS = {
    FREQUENCY_MODE: (1, MIN_MHZ, MAX_MHZ, 1500, "MHz", "extended range"),
    TEMPERATURE_MODE: (3, MIN_TEMPERATURE_C, MAX_TEMPERATURE_C, 45, "°C", "extended range"),
    "GPU frequency": (2, 0, 6000, 1500, "MHz", "confirmed"),
    "GPU temperature": (4, 0, 100, 45, "°C", "confirmed"),
    "CPU usage": (5, 0, 100, 50, "%", "confirmed"),
    "GPU usage": (6, 0, 100, 50, "%", "confirmed"),
    "RAM usage": (7, 0, 100, 50, "%", "confirmed"),
    "CPU fan": (8, 0, 10000, 1200, "RPM", "confirmed"),
    "Case fan 1": (9, 0, 10000, 1000, "RPM", "confirmed"),
    "Case fan 2": (10, 0, 10000, 1000, "RPM", "confirmed"),
    "Case fan 3": (11, 0, 10000, 1000, "RPM", "confirmed"),
    "Case fan 4": (12, 0, 10000, 1000, "RPM", "confirmed"),
    "Case fan 5": (13, 0, 10000, 1000, "RPM", "confirmed"),
}
class HafApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"HAF 700 EVO Iris Control v{__version__}")
        # Seven live cards and the evidence log fit comfortably on the 1080p
        # development display at this size without forcing tiny fonts.
        self.geometry("1450x930")
        self.minsize(1200, 780)
        self._set_icon()
        self._configure_styles()
        log_name = datetime.now().strftime("session_%Y%m%d_%H%M%S.jsonl")
        self.log_path = Path(__file__).parent / "logs" / log_name
        self.device = HafDevice(EventLog(self.log_path, self._device_event))
        self.settings_path = Path(__file__).parent / "settings.json"
        self.settings = AppSettings.load(self.settings_path)
        self.mode = tk.StringVar(value=FREQUENCY_MODE)
        self.value = tk.IntVar(value=1500)
        self.status = tk.StringVar(value="Disconnected - no device action has occurred")
        self.connection_status = tk.StringVar(value="DISCONNECTED")
        self.sensor_status = tk.StringVar(value="Not sampled")
        self.connected_ui = False
        self.lhm_live_running = False
        self._lhm_live_stop = threading.Event()
        self._lhm_stream: ElevatedFrequencyStream | None = None
        self.lhm_live_mode: str | None = None
        self.last_expected_lcd: str | None = None
        self.metric_stats = {
            FREQUENCY_MODE: MetricStats(),
            GPU_FREQUENCY_MODE: MetricStats(),
            TEMPERATURE_MODE: MetricStats(),
            GPU_TEMPERATURE_MODE: MetricStats(),
            CPU_USAGE_MODE: MetricStats(),
            GPU_USAGE_MODE: MetricStats(),
            RAM_USAGE_MODE: MetricStats(),
            CPU_FAN_MODE: MetricStats(),
        }
        self.metric_current_vars = {mode: tk.StringVar(value="--") for mode in self.metric_stats}
        self.metric_range_vars = {mode: tk.StringVar(value="Min --  |  Max --") for mode in self.metric_stats}
        self.metric_progress_vars = {mode: tk.DoubleVar(value=0) for mode in self.metric_stats}
        self.cycle_enabled = tk.BooleanVar(value=self.settings.cycle_enabled)
        self.cycle_seconds = tk.IntVar(value=self.settings.cycle_seconds)
        self.cycle_status = tk.StringVar(value="Cycle off")
        saved_cycle_modes = list(self.settings.cycle_modes[: len(LIVE_MODES)])
        saved_cycle_modes.extend([CYCLE_SLOT_OFF] * (len(LIVE_MODES) - len(saved_cycle_modes)))
        self.cycle_slot_vars = [tk.StringVar(value=mode) for mode in saved_cycle_modes]
        self._display_cycle: DisplayCycle | None = None
        # Tkinter widgets may only be touched by the main thread. The helper
        # worker posts snapshots with `after`; this timer also lives in Tk.
        self._cycle_after_id: str | None = None
        self.start_minimized = tk.BooleanVar(value=self.settings.start_minimized)
        self.auto_connect = tk.BooleanVar(value=self.settings.auto_connect)
        self.auto_start_lhm = tk.BooleanVar(value=self.settings.auto_start_lhm)
        self.minimize_to_tray = tk.BooleanVar(value=self.settings.minimize_to_tray)
        self.start_with_windows = tk.BooleanVar(value=startup_is_enabled(Path(__file__)))
        self._tray: TrayController | None = None
        self._exiting = False
        # Keep one pending auto-start callback at most. Without this guard a
        # quick reconnect and a preferences save could start two helpers.
        self._auto_lhm_after_id: str | None = None
        self._power_transition_running = False
        self._lcd_transmission_paused = threading.Event()
        self._power_resume_mode: str | None = None
        self._lcd_power_state: str | None = None
        self.lcd_power_status = tk.StringVar(value="UNKNOWN")
        self._build_ui()
        self.status.trace_add("write", self._status_changed)
        self._append_activity(self.status.get())
        self._append_activity(f"Target: {TARGET_SERIAL}")
        self._append_activity(f"Session log: {self.log_path.name}")
        self.protocol("WM_DELETE_WINDOW", self._window_close_requested)
        self.after(500, self._apply_launch_preferences)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"))
        style.configure("Subtitle.TLabel", foreground="#555555")
        style.configure("Disconnected.Status.TLabel", font=("Segoe UI", 9, "bold"), foreground="#9B1C1C")
        style.configure("Connected.Status.TLabel", font=("Segoe UI", 9, "bold"), foreground="#16733A")
        style.configure("Primary.TButton", font=("Segoe UI", 9, "bold"))
        style.configure("Section.TLabelframe.Label", font=("Segoe UI", 10, "bold"))
        style.configure("MetricValue.TLabel", font=("Segoe UI", 17, "bold"))
        style.configure("MetricTitle.TLabel", font=("Segoe UI", 9, "bold"), foreground="#444444")

    def _status_changed(self, *_args) -> None:
        self._append_activity(self.status.get())

    def _append_activity(self, message: str) -> None:
        if not hasattr(self, "log_text"):
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{stamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _device_event(self, record: dict[str, object]) -> None:
        """Render transport evidence in the UI without blocking its JSONL capture."""
        event = str(record.get("event", "event"))
        lines: list[str] = []
        frame_hex = str(record.get("frame_hex", ""))
        if frame_hex and event == "frame_send_started":
            try:
                frame = bytes.fromhex(frame_hex)
                command = frame[0]
                mode = frame[6]
                raw_value = int.from_bytes(frame[7:9], "big")
                value = raw_value - 0x10000 if raw_value >= 0x8000 else raw_value
                minimum = int.from_bytes(frame[9:11], "big")
                maximum = int.from_bytes(frame[11:13], "big")
                lines.append(
                    f"TX  cmd=0x{command:02X} mode={mode} value={value} min={minimum} max={maximum}"
                )
            except (ValueError, IndexError):
                lines.append("TX  frame")
            lines.append(f"    {frame_hex}")

        ack_hex = str(record.get("ack_hex", ""))
        if event == "frame_sent" and record.get("expect_ack"):
            result = "MATCH" if record.get("ack_matches") is True else "UNEXPECTED"
            lines.append(f"RX  ACK {result}: {ack_hex or '<empty>'}")
        elif event == "frame_sent" and not record.get("expect_ack"):
            lines.append("TX  completed; live response frame does not require an ACK")

        if event == "connected":
            lines.append(
                f"ADB forward ready: localhost:{record.get('local_port')} -> "
                f"{record.get('serial')}:{record.get('device_port')}"
            )
        elif event == "live_socket_opened":
            lines.append(
                f"Persistent live socket opened: localhost:{record.get('local_port')} -> "
                f"device:{record.get('device_port')}"
            )
        elif event == "live_socket_closed":
            lines.append(f"Persistent live socket closed ({record.get('reason')})")
        elif event == "disconnected":
            lines.append(f"ADB forward removed (exit {record.get('returncode')})")
        elif event == "pre_reboot_forward_cleanup":
            lines.append(f"Pre-reboot forward cleanup exit {record.get('returncode')}")
        elif event == "reboot_requested":
            lines.append(f"ADB reboot request exit {record.get('returncode')}")
        elif event == "power_transition_keyevent":
            lines.append(
                f"LCD power step: {record.get('step')} key={record.get('keycode')} "
                f"exit={record.get('returncode')}"
            )
        elif event == "gentle_power_off_started":
            lines.append(
                f"Gentle LCD OFF started; shutdown wait={record.get('shutdown_wait_seconds')}s"
            )
        elif event == "gentle_power_off_completed":
            lines.append(f"Gentle LCD OFF completed; wakefulness={record.get('wakefulness')}")
        elif event == "gentle_power_on_started":
            lines.append(
                "Gentle LCD ON started; "
                f"wake wait={record.get('wake_stabilization_seconds')}s, "
                f"startup wait={record.get('startup_wait_seconds')}s"
            )
        elif event == "stock_server_ready":
            lines.append(f"Stock LCD protocol server ready on port {record.get('port')}")
        elif event == "stock_startup_activity_ready":
            lines.append(f"Stock startup path ready: {record.get('launch_path')}")
        elif event == "gentle_power_on_completed":
            lines.append(f"Gentle LCD ON completed; wakefulness={record.get('wakefulness')}")
        elif event == "lcd_power_state_read":
            lines.append(f"LCD power state: {record.get('wakefulness')}")
        elif event.endswith("failed"):
            lines.append(f"{event}: {record.get('stderr') or record.get('error') or 'unknown error'}")

        for line in lines:
            self.after(0, self._append_activity, line)

    def _set_icon(self) -> None:
        ico_path = Path(__file__).parent / "haf_iris.ico"
        icon_path = Path(__file__).parent / "avatar small.jpg"
        try:
            if ico_path.exists():
                self.iconbitmap(default=str(ico_path))
            image = Image.open(icon_path)
            image.thumbnail((64, 64), Image.Resampling.LANCZOS)
            self._icon_image = ImageTk.PhotoImage(image)
            self.iconphoto(True, self._icon_image)
        except Exception:
            self._icon_image = None

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=20)
        root.pack(fill="both", expand=True)

        content = ttk.Panedwindow(root, orient="horizontal")
        content.pack(fill="both", expand=True)
        left = ttk.Frame(content, padding=(0, 0, 14, 0))
        right = ttk.Frame(content, padding=(14, 0, 0, 0))
        content.add(left, weight=3)
        content.add(right, weight=2)

        header = ttk.Frame(left)
        header.pack(fill="x", pady=(0, 16))
        header_text = ttk.Frame(header)
        header_text.pack(side="left", fill="x", expand=True)
        ttk.Label(header_text, text="HAF 700 EVO Iris", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header_text,
            text="LCD control and telemetry development",
            style="Subtitle.TLabel",
        ).pack(anchor="w")

        connection = ttk.LabelFrame(
            left, text="Device connection", padding=12, style="Section.TLabelframe"
        )
        connection.pack(fill="x", pady=(0, 14))
        ttk.Label(connection, text=f"ADB serial  {TARGET_SERIAL}").pack(side="left")
        self.connection_label = ttk.Label(
            connection,
            textvariable=self.connection_status,
            style="Disconnected.Status.TLabel",
        )
        self.connection_label.pack(side="right", padx=(14, 0))
        self.disconnect_button = ttk.Button(
            connection, text="Disconnect", command=self._disconnect, state="disabled"
        )
        self.disconnect_button.pack(side="right", padx=(8, 0))
        self.connect_button = ttk.Button(
            connection, text="Connect", command=self._connect, style="Primary.TButton"
        )
        self.connect_button.pack(side="right")

        controls = ttk.LabelFrame(
            left, text="Display", padding=14, style="Section.TLabelframe"
        )
        controls.pack(fill="x", pady=(0, 14))
        ttk.Label(controls, text="Mode").grid(row=0, column=0, sticky="w")
        self.mode_selector = ttk.Combobox(
            controls,
            textvariable=self.mode,
            values=tuple(MODE_CONFIGS),
            state="readonly",
            width=32,
        )
        self.mode_selector.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(12, 0))
        self.mode_selector.bind("<<ComboboxSelected>>", self._mode_changed)

        self.value_label = ttk.Label(controls, text="Displayed frequency (MHz)")
        self.value_label.grid(row=1, column=0, sticky="w", pady=(12, 0))
        self.spin = ttk.Spinbox(
            controls,
            from_=MIN_MHZ,
            to=MAX_MHZ,
            increment=1,
            textvariable=self.value,
            width=10,
        )
        self.spin.grid(row=1, column=1, padx=12, pady=(12, 0))
        self.apply_button = ttk.Button(
            controls,
            text="Apply to LCD",
            command=self._apply,
            state="disabled",
            style="Primary.TButton",
        )
        self.apply_button.grid(row=1, column=2, pady=(12, 0))
        controls.columnconfigure(1, weight=1)

        dashboard = ttk.LabelFrame(
            left, text="Live dashboard", padding=12, style="Section.TLabelframe"
        )
        dashboard.pack(fill="x", pady=(0, 14))
        metric_specs = (
            (FREQUENCY_MODE, "CPU FREQUENCY", 6000.0, " MHz"),
            (GPU_FREQUENCY_MODE, "GPU FREQUENCY", 6000.0, " MHz"),
            (TEMPERATURE_MODE, "CPU TEMPERATURE", 110.0, " °C"),
            (GPU_TEMPERATURE_MODE, "GPU TEMPERATURE", 110.0, " °C"),
            (CPU_USAGE_MODE, "CPU USAGE", 100.0, "%"),
            (GPU_USAGE_MODE, "GPU USAGE", 100.0, "%"),
            (RAM_USAGE_MODE, "RAM USAGE", 100.0, "%"),
            (CPU_FAN_MODE, "CPU FAN", 3000.0, " RPM"),
        )
        for index, (metric_mode, title, maximum, unit) in enumerate(metric_specs):
            row, column = divmod(index, 4)
            card = ttk.Frame(dashboard, padding=(10, 6))
            card.grid(row=row, column=column, sticky="nsew", padx=4, pady=2)
            ttk.Label(card, text=title, style="MetricTitle.TLabel").pack(anchor="w")
            ttk.Label(card, textvariable=self.metric_current_vars[metric_mode], style="MetricValue.TLabel").pack(anchor="w")
            ttk.Progressbar(
                card,
                variable=self.metric_progress_vars[metric_mode],
                maximum=maximum,
                length=145,
            ).pack(fill="x", pady=(5, 4))
            ttk.Label(card, textvariable=self.metric_range_vars[metric_mode]).pack(anchor="w")
            dashboard.columnconfigure(column, weight=1)
        controls_row = 2
        ttk.Button(dashboard, text="Reset min/max", command=self._reset_metric_extrema).grid(
            row=controls_row, column=0, sticky="w", padx=4, pady=(10, 0)
        )
        ttk.Checkbutton(
            dashboard, text="Cycle selected displays", variable=self.cycle_enabled,
            command=self._cycle_setting_changed,
        ).grid(row=controls_row, column=1, sticky="w", padx=4, pady=(10, 0))
        cycle_controls = ttk.Frame(dashboard)
        cycle_controls.grid(row=controls_row, column=2, columnspan=2, sticky="e", padx=4, pady=(10, 0))
        ttk.Spinbox(cycle_controls, from_=5, to=300, width=5, textvariable=self.cycle_seconds).pack(side="left")
        ttk.Label(cycle_controls, text=" sec").pack(side="left")
        ttk.Button(cycle_controls, text="Next", command=self._cycle_next).pack(side="left", padx=(8, 0))
        ttk.Label(dashboard, text="Display order").grid(
            row=3, column=0, sticky="w", padx=4, pady=(8, 2)
        )
        cycle_slot_frame = ttk.Frame(dashboard)
        cycle_slot_frame.grid(row=4, column=0, columnspan=4, sticky="ew", padx=4)
        for index, variable in enumerate(self.cycle_slot_vars):
            slot = ttk.Frame(cycle_slot_frame)
            slot.grid(row=index // 4, column=index % 4, sticky="ew", padx=(0, 8), pady=2)
            ttk.Label(slot, text=f"{index + 1}").pack(side="left", padx=(0, 4))
            selector = ttk.Combobox(
                slot,
                textvariable=variable,
                values=(CYCLE_SLOT_OFF, *LIVE_MODES),
                state="readonly",
                width=18,
            )
            selector.pack(side="left", fill="x", expand=True)
            selector.bind("<<ComboboxSelected>>", self._cycle_slots_changed)
            cycle_slot_frame.columnconfigure(index % 4, weight=1)
        ttk.Label(dashboard, textvariable=self.cycle_status, style="Subtitle.TLabel").grid(
            row=5, column=0, columnspan=4, sticky="w", padx=4, pady=(7, 0)
        )

        sensors = ttk.LabelFrame(
            left, text="CPU sensors", padding=14, style="Section.TLabelframe"
        )
        sensors.pack(fill="x", pady=(0, 14))
        ttk.Label(sensors, textvariable=self.sensor_status, wraplength=420).pack(
            side="left", fill="x", expand=True
        )
        self.sensor_probe_button = ttk.Button(
            sensors, text="Read CPU sensors...", command=self._probe_cpu_sensors
        )
        self.sensor_probe_button.pack(side="right", padx=(12, 0))
        self.lhm_stop_button = ttk.Button(
            sensors, text="Stop LHM", command=self._stop_lhm_live, state="disabled"
        )
        self.lhm_stop_button.pack(side="right", padx=(8, 0))
        self.lhm_start_button = ttk.Button(
            sensors, text="Start LHM live...", command=self._start_lhm_live, state="disabled"
        )
        self.lhm_start_button.pack(side="right", padx=(12, 0))

        advanced = ttk.LabelFrame(
            left, text="Tests and recovery", padding=14, style="Section.TLabelframe"
        )
        advanced.pack(fill="x", pady=(0, 14))
        ttk.Label(advanced, text="Restart Android LCD controller").grid(
            row=0, column=0, sticky="w"
        )
        self.reboot_button = ttk.Button(
            advanced, text="Reboot LCD...", command=self._reboot, state="disabled"
        )
        self.reboot_button.grid(row=0, column=2, sticky="e")
        power_buttons = ttk.Frame(advanced)
        power_buttons.grid(row=0, column=1, padx=(12, 12), sticky="e")
        ttk.Label(power_buttons, textvariable=self.lcd_power_status, style="Subtitle.TLabel").pack(
            side="left", padx=(0, 8)
        )
        self.lcd_on_button = ttk.Button(
            power_buttons, text="LCD ON", command=self._gentle_power_on, state="disabled"
        )
        self.lcd_on_button.pack(side="left")
        self.lcd_off_button = ttk.Button(
            power_buttons, text="LCD OFF", command=self._gentle_power_off, state="disabled"
        )
        self.lcd_off_button.pack(side="left", padx=(8, 0))
        ttk.Label(advanced, text="Read active Android LCD value").grid(
            row=1, column=0, sticky="w", pady=(10, 0)
        )
        self.read_lcd_ui_button = ttk.Button(
            advanced, text="Read LCD UI", command=self._read_lcd_ui, state="disabled"
        )
        self.read_lcd_ui_button.grid(row=1, column=2, sticky="e", pady=(10, 0))
        advanced.columnconfigure(1, weight=1)

        preferences = ttk.LabelFrame(
            right, text="Startup and window", padding=12, style="Section.TLabelframe"
        )
        preferences.pack(fill="x", pady=(0, 14))
        ttk.Checkbutton(preferences, text="Start minimized", variable=self.start_minimized).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(preferences, text="Connect to LCD on launch", variable=self.auto_connect).grid(row=0, column=1, sticky="w", padx=(14, 0))
        ttk.Checkbutton(preferences, text="Start LHM after connection", variable=self.auto_start_lhm).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Checkbutton(preferences, text="Start with Windows", variable=self.start_with_windows).grid(row=1, column=1, sticky="w", padx=(14, 0), pady=(6, 0))
        tray_check = ttk.Checkbutton(preferences, text="Close to notification area", variable=self.minimize_to_tray)
        tray_check.grid(row=2, column=0, sticky="w", pady=(6, 0))
        if not tray_available():
            tray_check.configure(state="disabled")
            self.minimize_to_tray.set(False)
            ttk.Label(preferences, text="Tray component not installed", style="Subtitle.TLabel").grid(row=2, column=1, sticky="w", padx=(14, 0), pady=(6, 0))
        ttk.Button(preferences, text="Save preferences", command=self._save_preferences).grid(row=0, column=2, rowspan=3, sticky="e", padx=(14, 0))
        ttk.Button(preferences, text="Clean old logs...", command=self._clean_old_logs).grid(
            row=3, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Label(
            preferences,
            text="Keeps 10 sessions, 5 helper streams and 5 probes",
            style="Subtitle.TLabel",
        ).grid(row=3, column=1, columnspan=2, sticky="w", padx=(14, 0), pady=(8, 0))
        preferences.columnconfigure(1, weight=1)

        activity = ttk.LabelFrame(
            right, text="Activity log", padding=10, style="Section.TLabelframe"
        )
        activity.pack(fill="both", expand=True)
        self.log_text = tk.Text(
            activity,
            wrap="word",
            state="disabled",
            font=("Consolas", 9),
            relief="flat",
            padx=8,
            pady=8,
        )
        log_scrollbar = ttk.Scrollbar(activity, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scrollbar.pack(side="right", fill="y")

    def _set_connected_ui(self, connected: bool) -> None:
        self.connected_ui = connected
        self.connection_status.set("CONNECTED" if connected else "DISCONNECTED")
        self.connection_label.configure(
            style="Connected.Status.TLabel" if connected else "Disconnected.Status.TLabel"
        )
        self.connect_button.configure(state="disabled" if connected else "normal")
        self.disconnect_button.configure(state="normal" if connected else "disabled")
        self.reboot_button.configure(state="normal" if connected else "disabled")
        if not connected:
            self._update_lcd_power_state(None)
        else:
            self._refresh_power_button_states()
        self.read_lcd_ui_button.configure(state="normal" if connected else "disabled")
        self.apply_button.configure(state="normal" if connected else "disabled")
        self.lhm_start_button.configure(
            state="normal" if connected and not self.lhm_live_running else "disabled"
        )
        if not connected:
            self._cancel_auto_lhm_start()
            self._stop_lhm_live("Live LHM test stopped because the LCD disconnected")

    def _start_lhm_live(self) -> None:
        if self.lhm_live_running:
            self._append_activity("LHM START ignored; live helper is already running")
            return
        if not self.connected_ui:
            messagebox.showerror("Not connected", "Connect to the HAF LCD first")
            return
        selected = self.mode.get()
        if selected not in LIVE_MODES:
            messagebox.showerror(
                "Unsupported live mode",
                "Select one of the live display modes 1-8 before starting LHM.",
            )
            return
        self.lhm_live_mode = selected
        self.lhm_live_running = True
        self._lhm_live_stop.clear()
        self._lhm_stream = ElevatedFrequencyStream()
        self.lhm_start_button.configure(state="disabled")
        self.lhm_stop_button.configure(state="normal")
        self.mode_selector.configure(state="disabled")
        self._append_activity(
            f"LHM LIVE START: mode={selected}, persistent helper, 2s cadence; approve UAC"
        )
        # The helper already returns frequency, package temperature, and total
        # load together. Cycling therefore changes only which value we encode;
        # it does not start another sensor process or add another poll.
        self._start_display_cycle()
        threading.Thread(target=self._lhm_live_worker, daemon=True).start()

    def _stop_lhm_live(self, message: str = "Live LHM test stopped") -> None:
        was_running = self.lhm_live_running
        self.lhm_live_running = False
        self.mode_selector.configure(state="readonly")
        self._lhm_live_stop.set()
        self._stop_display_cycle()
        stream = self._lhm_stream
        if stream is not None:
            try:
                stream.stop(0.0)
            except Exception as exc:
                self._append_activity(f"LHM LIVE stop sentinel failed: {exc}")
        if hasattr(self, "lhm_stop_button"):
            self.lhm_stop_button.configure(state="disabled")
            self.lhm_start_button.configure(state="normal" if self.connected_ui else "disabled")
        if was_running:
            self.device.close_live_session("lhm_live_stop")
            self._append_activity(message)

    def _lhm_live_worker(self) -> None:
        stream = self._lhm_stream
        previous_cpu_ms: float | None = None
        previous_sample_time: datetime | None = None
        try:
            if stream is None:
                raise RuntimeError("LHM frequency stream was not initialized")
            stream.start()
            while not self._lhm_live_stop.is_set():
                for sample in stream.read_new():
                    if self._lhm_live_stop.is_set():
                        break
                    if not sample.get("is_elevated"):
                        raise RuntimeError("persistent LHM helper is not elevated")
                    winner = sample.get("highest_loaded_core") or {}
                    raw_clock = winner.get("clock_mhz")
                    weighted_clock = sample.get("load_weighted_clock_mhz")
                    package_temp = sample.get("cpu_package_temperature_c")
                    core_average_temp = sample.get("core_average_temperature_c")
                    gpu_clock = sample.get("gpu_core_clock_mhz")
                    gpu_temp = sample.get("gpu_core_temperature_c")
                    gpu_load = sample.get("gpu_core_load_percent")
                    memory_load = sample.get("memory_load_percent")
                    cpu_fan_rpm = sample.get("cpu_fan_rpm")
                    # lhm_live_mode may be advanced by the main-thread cycle
                    # timer. Reading the string here makes the next complete
                    # snapshot the atomic boundary between two LCD modes.
                    live_mode = self.lhm_live_mode
                    if live_mode == FREQUENCY_MODE:
                        value = select_load_weighted_frequency(sample)
                        if not MIN_MHZ <= value <= MAX_MHZ:
                            raise ValueError(f"LHM sample {value} MHz is outside {MIN_MHZ}-{MAX_MHZ} MHz")
                        frame = build_cpu_frequency_frame(value, persist=False, ring_profile="stock")
                        expected = self._format_expected_frequency(value)
                        metric_message = (
                            f"clock winner={winner.get('name')} raw={raw_clock} MHz "
                            f"load={winner.get('load_percent')}% weighted={float(weighted_clock):.1f} MHz "
                            f"-> encoded={value} MHz"
                        )
                        strategy = "load_weighted_core_clock"
                        source_identifier = "derived:load_weighted_core_clock"
                    elif live_mode == GPU_FREQUENCY_MODE:
                        value = select_gpu_core_frequency(sample)
                        frame = build_provisional_metric_frame(2, value, persist=False)
                        expected = self._format_expected_frequency(value)
                        metric_message = f"GPU Core clock={gpu_clock} MHz -> encoded={value} MHz"
                        strategy = "gpu_core_clock"
                        source_identifier = sample.get("gpu_core_clock_identifier")
                    elif live_mode == TEMPERATURE_MODE:
                        value = select_cpu_package_temperature(sample)
                        if not MIN_TEMPERATURE_C <= value <= MAX_TEMPERATURE_C:
                            raise ValueError(
                                f"LHM CPU Package {value} C is outside {MIN_TEMPERATURE_C}-{MAX_TEMPERATURE_C} C"
                            )
                        frame = build_cpu_temperature_frame(value, persist=False)
                        expected = str(value)
                        metric_message = (
                            f"CPU Package={package_temp} C Core Average={core_average_temp} C "
                            f"-> encoded={value} C"
                        )
                        strategy = "cpu_package_temperature"
                        source_identifier = "/intelcpu/0/temperature/26"
                    elif live_mode == GPU_TEMPERATURE_MODE:
                        value = select_gpu_core_temperature(sample)
                        frame = build_provisional_metric_frame(4, value, persist=False)
                        expected = str(value)
                        metric_message = f"GPU Core temperature={gpu_temp} C -> encoded={value} C"
                        strategy = "gpu_core_temperature"
                        source_identifier = sample.get("gpu_core_temperature_identifier")
                    elif live_mode == CPU_USAGE_MODE:
                        value = select_cpu_total_load(sample)
                        frame = build_provisional_metric_frame(5, value, persist=False)
                        expected = str(value)
                        metric_message = (
                            f"CPU Total={sample.get('cpu_total_load_percent')}% "
                            f"-> encoded={value}%"
                        )
                        strategy = "cpu_total_load"
                        source_identifier = "/intelcpu/0/load/0"
                    elif live_mode == GPU_USAGE_MODE:
                        value = select_gpu_core_load(sample)
                        frame = build_provisional_metric_frame(6, value, persist=False)
                        expected = str(value)
                        metric_message = f"GPU Core load={gpu_load}% -> encoded={value}%"
                        strategy = "gpu_core_load"
                        source_identifier = sample.get("gpu_core_load_identifier")
                    elif live_mode == RAM_USAGE_MODE:
                        value = select_memory_load(sample)
                        frame = build_provisional_metric_frame(7, value, persist=False)
                        expected = str(value)
                        metric_message = f"Memory load={memory_load}% -> encoded={value}%"
                        strategy = "memory_load"
                        source_identifier = sample.get("memory_load_identifier")
                    elif live_mode == CPU_FAN_MODE:
                        value = select_cpu_fan_rpm(sample)
                        frame = build_provisional_metric_frame(8, value, persist=False)
                        expected = str(value)
                        metric_message = (
                            f"CPU fan={cpu_fan_rpm} RPM source={sample.get('cpu_fan_hardware_name')} "
                            f"{sample.get('cpu_fan_name')} -> encoded={value} RPM"
                        )
                        strategy = "cpu_named_or_sole_active_non_gpu_fan"
                        source_identifier = sample.get("cpu_fan_identifier")
                    else:
                        raise RuntimeError(f"unsupported LHM live mode: {live_mode}")
                    sample_time = datetime.fromisoformat(str(sample["timestamp"]))
                    cpu_ms = float(sample.get("process_cpu_milliseconds", 0.0))
                    helper_cpu_percent = None
                    if previous_cpu_ms is not None and previous_sample_time is not None:
                        wall_ms = (sample_time - previous_sample_time).total_seconds() * 1000.0
                        if wall_ms > 0:
                            helper_cpu_percent = 100.0 * (cpu_ms - previous_cpu_ms) / wall_ms
                    previous_cpu_ms = cpu_ms
                    previous_sample_time = sample_time
                    # Update all cards from this one snapshot, including values
                    # that are not currently being transmitted to the LCD.
                    self.after(0, self._update_dashboard_from_sample, sample)
                    self.device.log.write(
                        "lhm_live_sample",
                        sample_timestamp=sample.get("timestamp"),
                        core_name=winner.get("name"),
                        clock_identifier=winner.get("clock_identifier"),
                        source_clock_mhz=raw_clock,
                        core_load_percent=winner.get("load_percent"),
                        cpu_total_load_percent=sample.get("cpu_total_load_percent"),
                        load_weighted_clock_mhz=weighted_clock,
                        cpu_package_temperature_c=package_temp,
                        core_average_temperature_c=core_average_temp,
                        gpu_core_clock_mhz=gpu_clock,
                        gpu_core_temperature_c=gpu_temp,
                        gpu_core_load_percent=gpu_load,
                        memory_load_percent=memory_load,
                        cpu_fan_rpm=cpu_fan_rpm,
                        cpu_fan_name=sample.get("cpu_fan_name"),
                        cpu_fan_hardware_name=sample.get("cpu_fan_hardware_name"),
                        live_mode=live_mode,
                        transmit_strategy=strategy,
                        source_identifier=source_identifier,
                        encoded_value=value,
                        encoded_unit=(
                            "MHz" if live_mode in (FREQUENCY_MODE, GPU_FREQUENCY_MODE)
                            else "C" if live_mode in (TEMPERATURE_MODE, GPU_TEMPERATURE_MODE)
                            else "RPM" if live_mode == CPU_FAN_MODE
                            else "%"
                        ),
                        helper_process_cpu_milliseconds=cpu_ms,
                        helper_single_core_cpu_percent=helper_cpu_percent,
                    )
                    self.after(
                        0,
                        self._append_activity,
                        f"LHM READ {metric_message}; total_load={sample.get('cpu_total_load_percent')}% "
                        f"helper_cpu={helper_cpu_percent if helper_cpu_percent is not None else '--'}% of one core",
                    )
                    if self._lcd_transmission_paused.is_set():
                        # Keep consuming fresh LHM snapshots so the helper does
                        # not build a stale queue while the stock videos own the
                        # LCD. The first post-wake send will therefore be fresh.
                        self.after(
                            0,
                            self._append_activity,
                            f"TX paused for LCD power transition; sampled {live_mode}={expected}",
                        )
                        continue
                    # Disconnect/Stop can occur after this sample entered the
                    # loop. Recheck immediately before I/O so an expected user
                    # disconnect does not become a noisy transport error.
                    if self._lhm_live_stop.is_set() or not self.connected_ui:
                        break
                    self.device.send(frame, expect_ack=False)
                    self.last_expected_lcd = expected
                    self.after(
                        0,
                        self._append_activity,
                        f"TX complete mode={live_mode} expected_LCD={expected} "
                        "app_acceptance=unverified physical_display=unverified",
                    )
                self._lhm_live_stop.wait(0.5)
        except Exception as exc:
            self.after(0, self._append_activity, f"LHM LIVE ERROR: {type(exc).__name__}: {exc}")
        finally:
            if stream is not None:
                try:
                    stream.stop(8.0)
                except Exception:
                    pass
            self.after(0, self._lhm_live_finished)

    def _lhm_live_finished(self) -> None:
        self.lhm_live_running = False
        self.lhm_live_mode = None
        self._stop_display_cycle()
        self.mode_selector.configure(state="readonly")
        self.lhm_stop_button.configure(state="disabled")
        self.lhm_start_button.configure(state="normal" if self.connected_ui else "disabled")

    def _update_dashboard_from_sample(self, sample: dict[str, object]) -> None:
        """Render one helper snapshot without doing any additional hardware I/O."""
        candidates = {
            FREQUENCY_MODE: sample.get("load_weighted_clock_mhz"),
            GPU_FREQUENCY_MODE: sample.get("gpu_core_clock_mhz"),
            TEMPERATURE_MODE: sample.get("cpu_package_temperature_c"),
            GPU_TEMPERATURE_MODE: sample.get("gpu_core_temperature_c"),
            CPU_USAGE_MODE: sample.get("cpu_total_load_percent"),
            GPU_USAGE_MODE: sample.get("gpu_core_load_percent"),
            RAM_USAGE_MODE: sample.get("memory_load_percent"),
            CPU_FAN_MODE: sample.get("cpu_fan_rpm"),
        }
        for metric_mode, raw in candidates.items():
            if raw is None:
                continue
            numeric = float(raw)
            stats = self.metric_stats[metric_mode]
            stats.update(numeric)
            self.metric_progress_vars[metric_mode].set(numeric)
            if metric_mode in (FREQUENCY_MODE, GPU_FREQUENCY_MODE):
                current = f"{numeric / 1000:.2f} GHz"
                extrema = f"Min {stats.minimum / 1000:.2f}  |  Max {stats.maximum / 1000:.2f} GHz"
            elif metric_mode in (TEMPERATURE_MODE, GPU_TEMPERATURE_MODE):
                current = f"{numeric:.0f} °C"
                extrema = f"Min {stats.minimum:.0f}  |  Max {stats.maximum:.0f} °C"
            elif metric_mode == CPU_FAN_MODE:
                current = f"{numeric:.0f} RPM"
                extrema = f"Min {stats.minimum:.0f}  |  Max {stats.maximum:.0f} RPM"
            else:
                current = f"{numeric:.0f}%"
                extrema = f"Min {stats.minimum:.0f}  |  Max {stats.maximum:.0f}%"
            self.metric_current_vars[metric_mode].set(current)
            self.metric_range_vars[metric_mode].set(extrema)

    def _reset_metric_extrema(self) -> None:
        """Reset every min/max pair to its current value, as one user action."""
        for stats in self.metric_stats.values():
            stats.reset_extrema()
        # Re-render from the retained current values without inventing a sample.
        for metric_mode, stats in self.metric_stats.items():
            if stats.current is None:
                self.metric_range_vars[metric_mode].set("Min --  |  Max --")
            elif metric_mode in (FREQUENCY_MODE, GPU_FREQUENCY_MODE):
                self.metric_range_vars[metric_mode].set(
                    f"Min {stats.current / 1000:.2f}  |  Max {stats.current / 1000:.2f} GHz"
                )
            elif metric_mode in (TEMPERATURE_MODE, GPU_TEMPERATURE_MODE):
                self.metric_range_vars[metric_mode].set(f"Min {stats.current:.0f}  |  Max {stats.current:.0f} °C")
            elif metric_mode == CPU_FAN_MODE:
                self.metric_range_vars[metric_mode].set(
                    f"Min {stats.current:.0f}  |  Max {stats.current:.0f} RPM"
                )
            else:
                self.metric_range_vars[metric_mode].set(f"Min {stats.current:.0f}  |  Max {stats.current:.0f}%")
        self._append_activity("Dashboard session min/max reset to current readings")

    def _cycle_setting_changed(self) -> None:
        """Apply cycle checkbox changes immediately during a live session."""
        if self.lhm_live_running and self.cycle_enabled.get():
            self._start_display_cycle()
        else:
            self._stop_display_cycle()

    def _selected_cycle_modes(self) -> tuple[str, ...]:
        """Return enabled slots in their visible order; Off slots disappear."""
        return tuple(
            variable.get() for variable in self.cycle_slot_vars
            if variable.get() in LIVE_MODES
        )

    def _cycle_slots_changed(self, _event=None) -> None:
        """Apply edited ordering immediately without starting cycling itself."""
        modes = self._selected_cycle_modes()
        self.settings.cycle_modes = modes
        self._append_activity(
            "DISPLAY ORDER: " + (" -> ".join(modes) if modes else "no displays selected")
        )
        if self.lhm_live_running and self.cycle_enabled.get():
            self._start_display_cycle()

    def _start_display_cycle(self) -> None:
        if not self.lhm_live_running or not self.cycle_enabled.get():
            self.cycle_status.set("Cycle off")
            return
        try:
            seconds = max(5, min(300, int(self.cycle_seconds.get())))
        except (TypeError, ValueError, tk.TclError):
            seconds = 15
            self.cycle_seconds.set(seconds)
        modes = self._selected_cycle_modes()
        if not modes:
            self._stop_display_cycle()
            self._append_activity("DISPLAY CYCLE not started; all display-order slots are Off")
            return
        active = self.lhm_live_mode or modes[0]
        self._display_cycle = DisplayCycle(modes, seconds, active)
        self.lhm_live_mode = self._display_cycle.active
        self.mode.set(self._display_cycle.active)
        self._schedule_cycle_tick()
        self._append_activity(
            f"DISPLAY CYCLE START: {' -> '.join(self._display_cycle.modes)}, {seconds}s per display"
        )

    def _schedule_cycle_tick(self) -> None:
        if self._cycle_after_id is not None:
            self.after_cancel(self._cycle_after_id)
        self._update_cycle_status()
        self._cycle_after_id = self.after(1000, self._cycle_tick)

    def _cycle_tick(self) -> None:
        self._cycle_after_id = None
        cycle = self._display_cycle
        if cycle is None or not self.lhm_live_running or not self.cycle_enabled.get():
            self.cycle_status.set("Cycle off")
            return
        changed = cycle.tick()
        if changed:
            self._select_cycle_mode(cycle.active, "timer")
        self._schedule_cycle_tick()

    def _cycle_next(self) -> None:
        """Advance one live display, whether timed cycling is on or off.

        The button is a manual display selector, not an enable-cycling button.
        When automatic cycling is active we advance its existing state so the
        countdown restarts.  Otherwise a short-lived DisplayCycle gives us the
        exact same ordering and wraparound behavior without starting a timer.
        """
        if not self.lhm_live_running:
            self._append_activity("DISPLAY NEXT ignored; start LHM live mode first")
            return

        cycle = self._display_cycle
        if cycle is None:
            try:
                seconds = max(5, min(300, int(self.cycle_seconds.get())))
            except (TypeError, ValueError, tk.TclError):
                seconds = 15
            active = self.lhm_live_mode or self.mode.get()
            modes = self._selected_cycle_modes()
            if not modes:
                self._append_activity("DISPLAY NEXT ignored; all display-order slots are Off")
                return
            manual_cycle = DisplayCycle(modes, seconds, active)
            self._select_cycle_mode(manual_cycle.next(), "manual-next")
            # Manual navigation must not silently enable the automatic timer.
            self.cycle_status.set("Cycle off")
            return

        self._select_cycle_mode(cycle.next(), "manual-next")
        self._update_cycle_status()

    def _select_cycle_mode(self, mode: str, reason: str) -> None:
        # The worker will encode this mode on its next complete two-second
        # sample. We deliberately do not send a stale cached value immediately.
        previous = self.lhm_live_mode
        self.lhm_live_mode = mode
        self.mode.set(mode)
        self._append_activity(f"DISPLAY CYCLE SWITCH: {previous} -> {mode} ({reason})")
        self.device.log.write("display_cycle_switch", previous_mode=previous, live_mode=mode, reason=reason)

    def _update_cycle_status(self) -> None:
        cycle = self._display_cycle
        if cycle is None:
            self.cycle_status.set("Cycle off")
        else:
            self.cycle_status.set(f"Debug: {cycle.active} · next switch in {cycle.remaining}s")

    def _stop_display_cycle(self) -> None:
        if self._cycle_after_id is not None:
            self.after_cancel(self._cycle_after_id)
            self._cycle_after_id = None
        self._display_cycle = None
        self.cycle_status.set("Cycle off")

    def _mode_changed(self, _event=None) -> None:
        mode, minimum, maximum, default, unit, confidence = MODE_CONFIGS[self.mode.get()]
        self.value_label.configure(text=f"Displayed value ({unit})")
        self.spin.configure(from_=minimum, to=maximum)
        self.value.set(default)
        self.status.set(
            f"{self.mode.get()} selected; APK mode {mode}, {confidence} control path"
        )

    def _connect(self) -> None:
        try:
            self.device.connect()
            self._set_connected_ui(True)
            self._update_lcd_power_state(self.device.read_wakefulness())
            self.status.set(f"Connected to {TARGET_SERIAL} through localhost:18888")
            # This preference belongs to every successful connection, not just
            # the initial application-launch path. That matters when the LCD is
            # slow to boot and the user reconnects manually a little later.
            if self.auto_start_lhm.get():
                self._schedule_auto_lhm_start("successful connection")
            else:
                self._append_activity("AUTO LHM skipped: preference is disabled")
        except Exception as exc:
            self.status.set(f"Connection failed: {exc}")
            messagebox.showerror("Connection failed", str(exc))

    def _schedule_auto_lhm_start(self, reason: str) -> None:
        """Schedule one visible, cancellable helper start on Tk's main thread."""
        if not self.connected_ui:
            self._append_activity(f"AUTO LHM skipped ({reason}): LCD is not connected")
            return
        if self.lhm_live_running:
            self._append_activity(f"AUTO LHM skipped ({reason}): helper is already running")
            return
        self._cancel_auto_lhm_start()
        self._append_activity(f"AUTO LHM scheduled in 0.25s after {reason}")
        self._auto_lhm_after_id = self.after(250, self._run_scheduled_auto_lhm)

    def _run_scheduled_auto_lhm(self) -> None:
        self._auto_lhm_after_id = None
        if not self.connected_ui:
            self._append_activity("AUTO LHM canceled before start: LCD disconnected")
            return
        if not self.auto_start_lhm.get():
            self._append_activity("AUTO LHM canceled before start: preference was disabled")
            return
        self._append_activity("AUTO LHM starting now")
        self._start_lhm_live()

    def _cancel_auto_lhm_start(self) -> None:
        if self._auto_lhm_after_id is not None:
            try:
                self.after_cancel(self._auto_lhm_after_id)
            except tk.TclError:
                pass
            self._auto_lhm_after_id = None

    def _probe_cpu_sensors(self) -> None:
        self.sensor_probe_button.configure(state="disabled")
        self.sensor_status.set("Waiting for UAC sensor helper...")
        self._append_activity("CPU sensor probe started; approve the UAC prompt for the helper")
        threading.Thread(target=self._read_cpu_sensors_worker, daemon=True).start()

    def _read_cpu_sensors_worker(self) -> None:
        try:
            _snapshot, summary, evidence_path = read_once_elevated()
            windows_counters = read_windows_cpu_counters()
            self.after(0, self._show_cpu_sensor_summary, summary, evidence_path, windows_counters)
        except Exception as exc:
            self.after(0, self.sensor_status.set, f"Sensor read failed: {exc}")
            self.after(0, self._append_activity, f"CPU sensor probe failed: {exc}")
        finally:
            self.after(0, self.sensor_probe_button.configure, {"state": "normal"})

    def _show_cpu_sensor_summary(
        self,
        summary: dict[str, object],
        evidence_path: Path,
        windows_counters: dict[str, object],
    ) -> None:
        total = summary.get("cpu_total") or {}
        package = summary.get("cpu_package_temperature") or {}
        core_average = summary.get("core_average_temperature") or {}
        cpu_load = total.get("value")
        package_temp = package.get("value")
        core_average_temp = core_average.get("value")
        average_clock = summary.get("arithmetic_mean_clock_mhz")
        throughput_equivalent = windows_counters.get("throughput_equivalent_mhz")
        elevated = summary.get("is_elevated")
        self.sensor_status.set(
            f"Load {cpu_load if cpu_load is not None else '--'}%  |  "
            f"Package {package_temp if package_temp is not None else '--'} °C  |  "
            f"Core avg {core_average_temp if core_average_temp is not None else '--'} °C  |  "
            f"Throughput eq. {round(float(throughput_equivalent)) if throughput_equivalent is not None else '--'} MHz"
        )
        self._append_activity(
            f"LHM CPU: {summary.get('hardware_name')} | sensors={summary.get('sensor_count')} | "
            f"elevated={elevated}"
        )
        self._append_activity(f"Sensor evidence: {evidence_path.name}")
        self._append_activity(
            f"CPU readings: load={cpu_load}% package={package_temp} C "
            f"core_average={core_average_temp} C mean_clock={average_clock} MHz"
        )
        self._append_activity(
            "Windows counters: "
            f"nominal={windows_counters.get('nominal_frequency_mhz')} MHz "
            f"performance={windows_counters.get('processor_performance_percent')}% "
            f"utility={windows_counters.get('processor_utility_percent')}% "
            f"time={windows_counters.get('processor_time_percent')}%"
        )
        self._append_activity(
            f"Frequency estimates: active={windows_counters.get('active_frequency_estimate_mhz')} MHz "
            f"throughput_equivalent={throughput_equivalent} MHz (not a clock reading)"
        )
        self._append_activity(
            f"Windows counter evidence: {Path(str(windows_counters.get('evidence_path'))).name}"
        )
        if package_temp is None or average_clock is None:
            self._append_activity(
                "Temperature/clock unavailable: LibreHardwareMonitor low-level CPU access requires a UAC-elevated helper on this system"
            )

    def _disconnect(self) -> None:
        try:
            self.device.disconnect()
            self._set_connected_ui(False)
            self.status.set("Disconnected; HAF-specific ADB forward removed")
        except Exception as exc:
            self._set_connected_ui(False)
            self.status.set(f"Disconnected with cleanup error: {exc}")
            messagebox.showerror("Disconnect error", str(exc))

    def _reboot(self) -> None:
        if not messagebox.askyesno(
            "Reboot HAF LCD?",
            f"Reboot only HAF serial {TARGET_SERIAL}?\n\nThe LCD has previously taken a long time to return.",
        ):
            return
        try:
            self.device.reboot()
            self._set_connected_ui(False)
            self.status.set("HAF LCD reboot accepted; forward removed. Wait for Android/LCD startup, then reconnect.")
        except Exception as exc:
            self.status.set(f"Reboot failed: {exc}")
            messagebox.showerror("Reboot failed", str(exc))

    def _set_power_transition_ui(self, running: bool) -> None:
        """Keep mutually exclusive recovery controls disabled during a transition."""
        self._power_transition_running = running
        self._refresh_power_button_states()
        state = "disabled" if running or not self.connected_ui else "normal"
        self.reboot_button.configure(state=state)
        self.apply_button.configure(state=state)

    def _update_lcd_power_state(self, wakefulness: str | None) -> None:
        """Normalize Android power state and make the valid next action obvious."""
        normalized = wakefulness.lower() if wakefulness else None
        self._lcd_power_state = normalized if normalized in ("awake", "asleep") else None
        label = "ON" if self._lcd_power_state == "awake" else "OFF" if self._lcd_power_state == "asleep" else "UNKNOWN"
        self.lcd_power_status.set(label)
        self._refresh_power_button_states()

    def _refresh_power_button_states(self) -> None:
        can_use = self.connected_ui and not self._power_transition_running
        self.lcd_on_button.configure(
            state="normal" if can_use and self._lcd_power_state == "asleep" else "disabled"
        )
        self.lcd_off_button.configure(
            state="normal" if can_use and self._lcd_power_state == "awake" else "disabled"
        )
    def _gentle_power_off(self) -> None:
        if self._power_transition_running:
            return
        if not messagebox.askyesno(
            "Turn the HAF LCD off?",
            "Play the complete stock shutdown animation, then turn off the LCD and backlight?",
        ):
            return
        self._power_resume_mode = self.lhm_live_mode or self.mode.get()
        self._lcd_transmission_paused.set()
        self._stop_display_cycle()
        self.device.close_live_session("gentle_power_off_pause")
        self._set_power_transition_ui(True)
        self.status.set(
            f"LCD OFF: playing stock shutdown animation; power-off follows after {SHUTDOWN_WAIT_SECONDS:g} seconds"
        )
        self._append_activity(
            f"LCD OFF START: TX/cycling paused; Volume Down -> wait {SHUTDOWN_WAIT_SECONDS:g}s -> Power"
        )
        threading.Thread(target=self._gentle_power_off_worker, daemon=True).start()

    def _gentle_power_off_worker(self) -> None:
        try:
            wakefulness = self.device.gentle_power_off()
            self.after(0, self._gentle_power_off_finished, wakefulness, None)
        except Exception as exc:
            self.after(0, self._gentle_power_off_finished, None, exc)

    def _gentle_power_off_finished(self, wakefulness: str | None, error: Exception | None) -> None:
        if error is not None:
            # A failed transition must not silently freeze an otherwise live
            # dashboard. Resume traffic because the final LCD state is unknown.
            self._lcd_transmission_paused.clear()
            if self.lhm_live_running and self.cycle_enabled.get():
                self._start_display_cycle()
            self.status.set(f"LCD OFF failed: {error}")
            self._append_activity(f"LCD OFF ERROR: {type(error).__name__}: {error}")
            messagebox.showerror("LCD OFF failed", str(error))
            self._set_power_transition_ui(False)
            return
        self._update_lcd_power_state(wakefulness)
        self._set_power_transition_ui(False)
        self.status.set("LCD OFF complete; Android is Asleep and the backlight should be off")
        self._append_activity(f"LCD OFF COMPLETE: wakefulness={wakefulness}; TX remains paused")

    def _gentle_power_on(self) -> None:
        if self._power_transition_running:
            return
        self._lcd_transmission_paused.set()
        self._stop_display_cycle()
        self.device.close_live_session("gentle_power_on_pause")
        self._set_power_transition_ui(True)
        self.status.set("LCD ON: waking Android and playing the stock startup animation")
        self._append_activity(
            f"LCD ON START: Power -> wait {WAKE_STABILIZATION_SECONDS:g}s -> "
            f"restart stock app -> wait {STARTUP_WAIT_SECONDS:g}s"
        )
        threading.Thread(target=self._gentle_power_on_worker, daemon=True).start()

    def _gentle_power_on_worker(self) -> None:
        try:
            wakefulness = self.device.gentle_power_on()
            self.after(0, self._gentle_power_on_finished, wakefulness, None)
        except Exception as exc:
            self.after(0, self._gentle_power_on_finished, None, exc)

    def _gentle_power_on_finished(self, wakefulness: str | None, error: Exception | None) -> None:
        if error is not None:
            self.status.set(f"LCD ON failed: {error}")
            self._append_activity(f"LCD ON ERROR: {type(error).__name__}: {error}")
            messagebox.showerror("LCD ON failed", str(error))
            self._set_power_transition_ui(False)
            return

        if self._power_resume_mode in LIVE_MODES:
            self.lhm_live_mode = self._power_resume_mode
            self.mode.set(self._power_resume_mode)
        self._lcd_transmission_paused.clear()
        if self.lhm_live_running and self.cycle_enabled.get():
            self._start_display_cycle()
        self._update_lcd_power_state(wakefulness)
        self._set_power_transition_ui(False)
        if self.lhm_live_running:
            self.status.set("LCD ON complete; startup animation ended and live TX resumed")
        else:
            self.status.set("LCD ON complete; startup animation ended and the LCD is ready")
        self._append_activity(
            f"LCD ON COMPLETE: wakefulness={wakefulness}; restored_mode={self._power_resume_mode}; "
            f"TX={'resumed' if self.lhm_live_running else 'idle'}"
        )

    @staticmethod
    def _format_expected_frequency(value_mhz: int) -> str:
        return str((Decimal(value_mhz) / Decimal(1000)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    def _read_lcd_ui(self) -> None:
        if self.lhm_live_running:
            messagebox.showinfo(
                "Stop live updates first",
                "Stop the live source before reading the LCD UI so the four-second hierarchy read can be compared with a stable final value.",
            )
            return
        self.read_lcd_ui_button.configure(state="disabled")
        self._append_activity("LCD UI read started; this may take about four seconds")
        threading.Thread(target=self._read_lcd_ui_worker, daemon=True).start()

    def _read_lcd_ui_worker(self) -> None:
        try:
            state = self.device.read_lcd_ui()
            self.after(0, self._show_lcd_ui_state, state)
        except Exception as exc:
            self.after(0, self._append_activity, f"LCD UI READ ERROR: {exc}")
        finally:
            self.after(
                0,
                self.read_lcd_ui_button.configure,
                {"state": "normal" if self.connected_ui else "disabled"},
            )

    def _show_lcd_ui_state(self, state: dict[str, str]) -> None:
        actual = state.get("value", "")
        expected = self.last_expected_lcd
        match = "MATCH" if expected is not None and actual == expected else "DIFFERENT/UNKNOWN"
        self._append_activity(
            f"LCD UI TREE value={actual} {state.get('unit', '')} title={state.get('title', '')} "
            f"latest_expected={expected or '--'} result={match}; physical scanout unverified"
        )

    def _validated_value(self) -> int:
        try:
            value = int(self.value.get())
        except (TypeError, ValueError) as exc:
            raise ValueError("Enter a whole-number display value") from exc
        _mode, minimum, maximum, _default, unit, _confidence = MODE_CONFIGS[self.mode.get()]
        if not minimum <= value <= maximum:
            raise ValueError(f"Value must be between {minimum} and {maximum} {unit}")
        return value

    def _apply(self) -> None:
        try:
            value = self._validated_value()
            selected = self.mode.get()
            mode, _minimum, _maximum, _default, unit, _confidence = MODE_CONFIGS[selected]
            if selected == FREQUENCY_MODE:
                frame = build_cpu_frequency_frame(value, persist=True, ring_profile="stock")
            elif selected == TEMPERATURE_MODE:
                frame = build_cpu_temperature_frame(value, persist=True)
            else:
                frame = build_provisional_metric_frame(mode, value, persist=True)
            self.device.send(frame, expect_ack=True)
            displayed = f"{value / 1000:.2f} GHz" if unit == "MHz" else f"{value} {unit}"
            self.last_expected_lcd = self._format_expected_frequency(value) if unit == "MHz" else str(value)
            self.status.set(f"ACK confirmed; LCD {selected} persisted at {displayed}")
        except Exception as exc:
            self.status.set(f"Apply failed: {exc}")
            messagebox.showerror("Apply failed", str(exc))

    def _save_preferences(self) -> None:
        """Persist user choices and explicitly synchronize the HKCU Run entry."""
        try:
            seconds = max(5, min(300, int(self.cycle_seconds.get())))
            self.cycle_seconds.set(seconds)
            self.settings.cycle_enabled = self.cycle_enabled.get()
            self.settings.cycle_seconds = seconds
            self.settings.cycle_modes = self._selected_cycle_modes()
            self.settings.start_minimized = self.start_minimized.get()
            self.settings.auto_connect = self.auto_connect.get()
            self.settings.auto_start_lhm = self.auto_start_lhm.get()
            self.settings.minimize_to_tray = self.minimize_to_tray.get() and tray_available()
            if self.settings.minimize_to_tray:
                self._ensure_tray()
            elif self._tray is not None:
                self._tray.stop()
                self._tray = None
            set_startup_enabled(Path(__file__), self.start_with_windows.get())
            self.settings.start_with_windows = startup_is_enabled(Path(__file__))
            self.start_with_windows.set(self.settings.start_with_windows)
            self.settings.save(self.settings_path)
            cycle_order = " -> ".join(self.settings.cycle_modes) or "all slots Off"
            self._append_activity(
                "Preferences saved: "
                f"cycle={self.settings.cycle_enabled}/{seconds}s "
                f"order={cycle_order}; "
                f"startup={self.settings.start_with_windows} minimized={self.settings.start_minimized} "
                f"auto_connect={self.settings.auto_connect} auto_lhm={self.settings.auto_start_lhm}"
            )
            self.status.set("Preferences saved")
            # Saving an enabled auto-start option while already connected should
            # do what the label says immediately; it should not require another
            # application restart or disconnect/reconnect cycle.
            if self.settings.auto_start_lhm and self.connected_ui and not self.lhm_live_running:
                self._schedule_auto_lhm_start("preferences save")
            elif not self.settings.auto_start_lhm:
                self._cancel_auto_lhm_start()
        except Exception as exc:
            messagebox.showerror("Could not save preferences", str(exc))

    def _clean_old_logs(self) -> None:
        """Preview exact retention targets and require confirmation to delete."""
        protected = [self.log_path]
        if self._lhm_stream is not None:
            protected.extend((self._lhm_stream.output_path, self._lhm_stream.stop_path))
        candidates = cleanup_candidates(Path(__file__).parent / "logs", protected=tuple(protected))
        total_bytes = sum(path.stat().st_size for path in candidates if path.exists())
        if not candidates:
            messagebox.showinfo("Diagnostic logs", "No old logs exceed the retention limits.")
            return
        size_mb = total_bytes / (1024 * 1024)
        if not messagebox.askyesno(
            "Clean old diagnostic logs?",
            f"Remove {len(candidates)} old workspace-local log files ({size_mb:.1f} MiB)?\n\n"
            "The current session and active helper files are excluded. This cannot be undone.",
        ):
            self._append_activity("LOG CLEANUP canceled by user")
            return
        removed, removed_bytes = remove_candidates(candidates)
        self._append_activity(
            f"LOG CLEANUP removed {removed} old files ({removed_bytes / (1024 * 1024):.1f} MiB)"
        )

    def _apply_launch_preferences(self) -> None:
        """Run opt-in launch actions only after the complete Tk window exists."""
        startup_launch = "--startup" in sys.argv
        if self.settings.minimize_to_tray and tray_available():
            self._ensure_tray()
        if startup_launch and self.settings.start_minimized:
            self.withdraw() if self._tray is not None else self.iconify()
            self._append_activity("Startup launch minimized")
        if self.settings.auto_connect:
            # Connection remains fixed to the known HAF serial. If it is still
            # booting, the normal error is logged and no other device is tried.
            self._connect()

    def _ensure_tray(self) -> bool:
        if self._tray is not None:
            return True
        if not tray_available():
            return False
        icon_path = Path(__file__).parent / "haf_iris.ico"
        self._tray = TrayController(
            icon_path,
            show=lambda: self.after(0, self._restore_window),
            toggle_live=lambda: self.after(0, self._toggle_lhm_from_tray),
            next_display=lambda: self.after(0, self._cycle_next),
            exit_app=lambda: self.after(0, self._exit_application),
        )
        if not self._tray.start():
            self._tray = None
            return False
        self._append_activity("Notification-area icon started")
        return True

    def _restore_window(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def _toggle_lhm_from_tray(self) -> None:
        if self.lhm_live_running:
            self._stop_lhm_live()
        else:
            self._start_lhm_live()

    def _window_close_requested(self) -> None:
        """Honor close-to-tray without turning every close into a hidden exit."""
        if not self._exiting and self.minimize_to_tray.get() and self._ensure_tray():
            self.withdraw()
            self._append_activity("Window hidden in notification area; telemetry remains active")
            return
        self._exit_application()

    def _exit_application(self) -> None:
        self._exiting = True
        self._cancel_auto_lhm_start()
        self._stop_lhm_live()
        try:
            self.device.disconnect()
        except Exception as exc:
            messagebox.showerror("Cleanup error", f"Could not remove the HAF forward: {exc}")
        if self._tray is not None:
            self._tray.stop()
        self.destroy()


if __name__ == "__main__":
    HafApp().mainloop()
