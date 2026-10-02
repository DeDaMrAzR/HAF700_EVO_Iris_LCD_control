# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Confirmed HAF Iris CPU-frequency frame construction."""

from __future__ import annotations

SYNC = bytes.fromhex("800001")
EXPECTED_ACK = bytes.fromhex("128000010000")
CPU_MODE = 1
MIN_MHZ = 0
MAX_MHZ = 9990
CPU_TEMPERATURE_MODE = 3
MIN_TEMPERATURE_C = -20
MAX_TEMPERATURE_C = 150

# Numeric renderer modes recovered from BaseView. The user has physically
# confirmed every mode below with changing manual values. These are still kept
# separate from automatic sensor support: proving that mode 9 renders an RPM
# value does not tell us which motherboard sensor should feed it.
PROVISIONAL_MODE_SPECS = {
    2: (0, 6000, 0, 6000),
    4: (0, 100, 40, 80),
    5: (0, 100, 0, 100),
    6: (0, 100, 0, 100),
    7: (0, 100, 0, 100),
    8: (0, 10000, 500, 3000),
    9: (0, 10000, 500, 3000),
    10: (0, 10000, 500, 3000),
    11: (0, 10000, 500, 3000),
    12: (0, 10000, 500, 3000),
    13: (0, 10000, 500, 3000),
}


def build_cpu_frequency_frame(
    value_mhz: int, *, persist: bool, ring_profile: str = "stock"
) -> bytes:
    """Build the confirmed CPU-only mode frame (0x15 live or 0x12 persistent)."""
    if not isinstance(value_mhz, int) or isinstance(value_mhz, bool):
        raise TypeError("frequency must be an integer MHz value")
    if not MIN_MHZ <= value_mhz <= MAX_MHZ:
        raise ValueError(f"frequency must be between {MIN_MHZ} and {MAX_MHZ} MHz")
    if ring_profile == "stock":
        style_minimum, style_maximum = 1100, 6000
    elif ring_profile == "three_band":
        style_minimum, style_maximum = 2000, 4500
    else:
        raise ValueError(f"unknown frequency ring profile: {ring_profile}")

    return _build_mode_frame(
        CPU_MODE,
        value_mhz,
        style_minimum=style_minimum,
        style_maximum=style_maximum,
        persist=persist,
    )


def build_cpu_temperature_frame(value_c: int, *, persist: bool) -> bytes:
    """Build confirmed stock mode 3 with a provisional manual Celsius value."""
    if not isinstance(value_c, int) or isinstance(value_c, bool):
        raise TypeError("temperature must be a whole-number Celsius value")
    if not MIN_TEMPERATURE_C <= value_c <= MAX_TEMPERATURE_C:
        raise ValueError(
            f"temperature must be between {MIN_TEMPERATURE_C} and {MAX_TEMPERATURE_C} C"
        )
    return _build_mode_frame(
        CPU_TEMPERATURE_MODE,
        value_c,
        style_minimum=40,
        style_maximum=80,
        persist=persist,
    )


def build_provisional_metric_frame(mode: int, value: int, *, persist: bool) -> bytes:
    """Build a physically confirmed numeric renderer frame.

    The historical function name is retained for compatibility with the app
    and tests; "provisional" now applies only to future automatic sensor
    mappings, not to the LCD mode IDs or their ability to show manual values.
    """
    if mode not in PROVISIONAL_MODE_SPECS:
        raise ValueError(f"unsupported provisional numeric mode: {mode}")
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("metric value must be a whole number")
    minimum, maximum, style_minimum, style_maximum = PROVISIONAL_MODE_SPECS[mode]
    if not minimum <= value <= maximum:
        raise ValueError(f"mode {mode} value must be between {minimum} and {maximum}")
    return _build_mode_frame(
        mode,
        value,
        style_minimum=style_minimum,
        style_maximum=style_maximum,
        persist=persist,
    )


def _build_mode_frame(
    mode: int, current_value: int, *, style_minimum: int, style_maximum: int, persist: bool
) -> bytes:
    body = b"".join(
        (
            bytes((mode,)),
            current_value.to_bytes(2, "big", signed=current_value < 0),
            style_minimum.to_bytes(2, "big"),
            style_maximum.to_bytes(2, "big"),
            bytes.fromhex("0000000000"),
            bytes.fromhex("FFFFFFFF"),
            bytes.fromhex("00"),
            bytes.fromhex("03"),
            bytes.fromhex("FF000000"),
            bytes.fromhex("0000"),
        )
    )
    command = 0x12 if persist else 0x15
    return bytes((command,)) + SYNC + len(body).to_bytes(2, "big") + body
