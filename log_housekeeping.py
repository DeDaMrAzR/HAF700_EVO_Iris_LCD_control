# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Bounded, previewable housekeeping for workspace-local diagnostic logs."""

from __future__ import annotations

from pathlib import Path


def cleanup_candidates(
    log_dir: Path,
    *,
    keep_sessions: int = 10,
    keep_streams: int = 5,
    keep_probes: int = 5,
    protected: tuple[Path, ...] = (),
) -> list[Path]:
    """Return exact files eligible for removal; never delete from this function."""
    protected_resolved = {path.resolve() for path in protected}
    candidates: list[Path] = []
    groups = (
        ("session_*.jsonl", keep_sessions),
        ("lhm_frequency_stream_*.jsonl", keep_streams),
        ("lhm_telemetry_stream_*.jsonl", keep_streams),
        ("cpu_probe_*.jsonl", keep_probes),
    )
    for pattern, keep in groups:
        # Timestamped filenames are the deterministic tie-breaker when NTFS
        # gives several rapidly-created files the same modification timestamp.
        files = sorted(
            log_dir.glob(pattern),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
            reverse=True,
        )
        candidates.extend(path for path in files[keep:] if path.resolve() not in protected_resolved)
    # A stop sentinel has no diagnostic content once its process is gone. Active
    # stream sentinels are protected by the caller.
    candidates.extend(
        path for path in log_dir.glob("*.stop") if path.resolve() not in protected_resolved
    )
    return sorted(set(candidates), key=lambda path: path.name)


def remove_candidates(paths: list[Path]) -> tuple[int, int]:
    """Remove only the already-previewed exact paths and return files/bytes."""
    removed = 0
    bytes_removed = 0
    for path in paths:
        try:
            size = path.stat().st_size
            path.unlink()
        except FileNotFoundError:
            continue
        removed += 1
        bytes_removed += size
    return removed, bytes_removed
