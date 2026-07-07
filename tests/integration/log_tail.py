"""Log + witness tail helpers for Tier 2 integration tests.

Two surfaces:

  - **log_ktp event lines** (`addons/ktpamx/logs/L<MMDD>.log`). Match-flow
    state transitions emit `event=NAME ...` rows via `log_ktp()` from
    KTPMatchHandler.sma. Tests poll the latest L*.log for a target event
    name.

  - **witness JSONL** (`addons/ktpamx/logs/witness.jsonl`). KTPWitness.amxx
    appends one JSON-per-line row each time `ktp_match_start` or
    `ktp_match_end` fires. Tests read the file end-to-end + filter by
    event field.

Polling rather than inotify because: (1) cross-platform (no Linux-only
deps), (2) the tests sleep ~0.5s anyway between rcon-fire and assert,
(3) this code is a fixture helper, not a long-running monitor — total
poll volume is small.

Both helpers operate on the serverfiles dir directly. Subprocess-boot
mode reads files in-place. External-server mode (KTP_HLDS_HOST) needs
KTP_HLDS_SERVERFILES *also* set so the helpers know where to look —
since we don't have rcon-driven log access, file-system access is the
contract.
"""

from __future__ import annotations

import glob
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import NamedTuple, Union


def _logs_dir(serverfiles: Path) -> Path:
    return serverfiles / "dod" / "addons" / "ktpamx" / "logs"


class LogPosition(NamedTuple):
    """Rotation-aware log baseline: which L*.log was current + its size.

    KTPAMXX 2.7.19+ rotates the log PER MAP CHANGE in extension mode (plus the
    UTC-midnight roll), so a bare byte offset applied to whichever file is
    newest at poll time breaks the moment a test spans a changelevel: the
    offset either hides the new file's early bytes (flake) or scans from an
    arbitrary byte (stale match = false pass on negative-path tests).
    """
    path: str | None  # basename of the current log at baseline; None = no log yet
    size: int


def _scan_plan(newest: Path, after_offset: "Union[int, LogPosition]") -> list[tuple[Path, int]]:
    """Return (file, start_byte) pairs to scan for this poll."""
    if isinstance(after_offset, LogPosition):
        if after_offset.path is None or newest.name == after_offset.path:
            return [(newest, after_offset.size if after_offset.path else 0)]
        # Rotated since baseline: finish the baseline file's unread tail
        # (events can land there right up to the rotation), then the new
        # file from byte 0.
        plan: list[tuple[Path, int]] = []
        old = newest.parent / after_offset.path
        if old.exists():
            plan.append((old, after_offset.size))
        plan.append((newest, 0))
        return plan
    # Legacy int offset — pre-2026-07-07 semantics (applied to the newest file).
    return [(newest, int(after_offset))]


def _latest_log_file(serverfiles: Path) -> Path | None:
    """Return the L<MMDD>.log file the engine is currently writing to.
    AMXX rolls per UTC date; mid-test it's whichever has the newest mtime.
    Returns None if no L*.log exists yet (server hasn't logged anything)."""
    candidates = list(_logs_dir(serverfiles).glob("L*.log"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def wait_for_log_event(
    serverfiles: Path,
    event_name: str,
    *,
    timeout: float = 5.0,
    poll_interval: float = 0.1,
    after_offset: "Union[int, LogPosition]" = 0,
) -> str:
    """Poll the latest `addons/ktpamx/logs/L*.log` for `event=<event_name>`
    and return the matching line. Raises TimeoutError on timeout.

    `after_offset` (bytes) lets a test record the log file size BEFORE
    triggering the rcon, then pass it here so we only scan new bytes —
    avoids matching against a stale event from a prior test. Default 0
    (scan everything; fine for the first event in a fresh log).
    """
    serverfiles = Path(serverfiles).resolve()
    deadline = time.monotonic() + timeout
    target_substring = f"event={event_name}"

    while time.monotonic() < deadline:
        log = _latest_log_file(serverfiles)
        if log is not None:
            for path, start in _scan_plan(log, after_offset):
                try:
                    if path.stat().st_size <= start:
                        continue
                    with path.open("rb") as f:
                        f.seek(start)
                        # Decode best-effort — log_ktp emits ASCII but DoD
                        # names can have weird chars in player-input fields.
                        # errors='replace' keeps us moving.
                        tail = f.read().decode("utf-8", errors="replace")
                except OSError:
                    continue
                for line in tail.splitlines():
                    if target_substring in line:
                        return line
        time.sleep(poll_interval)

    raise TimeoutError(
        f"event={event_name!r} not found in {_logs_dir(serverfiles)}/L*.log "
        f"within {timeout:.1f}s (after_offset={after_offset})"
    )


def current_log_size(serverfiles: Path) -> LogPosition:
    """Return the current log baseline (file identity + size). Capture BEFORE
    triggering an rcon, then pass as `after_offset` so only newer bytes are
    scanned — now rotation-aware (see LogPosition). Callers treat the return
    as opaque; plain-int offsets are still accepted for the `0` fallback."""
    log = _latest_log_file(Path(serverfiles).resolve())
    if log is None:
        return LogPosition(None, 0)
    return LogPosition(log.name, log.stat().st_size)


def wait_for_log_substring(
    serverfiles: Path,
    substring: str,
    *,
    timeout: float = 5.0,
    poll_interval: float = 0.1,
    after_offset: "Union[int, LogPosition]" = 0,
) -> str:
    """Like `wait_for_log_event` but greps by literal substring instead of
    `event=NAME`. Use for HLStatsX-shape lines (`log_message` output) or
    other formats that don't follow the `[KTP] event=...` AMXX log_ktp
    convention.

    Example:
        line = wait_for_log_substring(sf, 'KTP_MATCH_START')
        # Matches `L MM/DD/YYYY - HH:MM:SS: KTP_MATCH_START (matchid "...") ...`

    Returns the matching line. Raises TimeoutError on timeout.
    """
    serverfiles = Path(serverfiles).resolve()
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        log = _latest_log_file(serverfiles)
        if log is not None:
            for path, start in _scan_plan(log, after_offset):
                try:
                    if path.stat().st_size <= start:
                        continue
                    with path.open("rb") as f:
                        f.seek(start)
                        tail = f.read().decode("utf-8", errors="replace")
                except OSError:
                    continue
                for line in tail.splitlines():
                    if substring in line:
                        return line
        time.sleep(poll_interval)

    raise TimeoutError(
        f"substring {substring!r} not found in {_logs_dir(serverfiles)}/L*.log "
        f"within {timeout:.1f}s (after_offset={after_offset})"
    )


def read_witness_jsonl(serverfiles: Path) -> list[dict]:
    """Return all rows from `addons/ktpamx/logs/witness.jsonl` as parsed
    dicts. Empty list if the file doesn't exist (witness has never fired).
    Best-effort on malformed lines: skip + return what parses cleanly."""
    path = _logs_dir(Path(serverfiles).resolve()) / "witness.jsonl"
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def wait_for_witness_event(
    serverfiles: Path,
    event_name: str,
    *,
    timeout: float = 5.0,
    poll_interval: float = 0.1,
    after_count: int = 0,
) -> dict:
    """Poll witness.jsonl for a row with `event == event_name` after
    `after_count` rows (use `len(read_witness_jsonl(...))` before firing
    the rcon to baseline). Returns the matching row dict.

    Raises TimeoutError on timeout. Tests use this as the proof-of-fire
    check for `ktp_match_start` / `ktp_match_end` forwards — the row
    being there means at least one downstream consumer (the witness)
    received the dispatch.
    """
    serverfiles = Path(serverfiles).resolve()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = read_witness_jsonl(serverfiles)
        for row in rows[after_count:]:
            if row.get("event") == event_name:
                return row
        time.sleep(poll_interval)
    raise TimeoutError(
        f"witness event={event_name!r} not found within {timeout:.1f}s "
        f"(after_count={after_count})"
    )


def witness_count(serverfiles: Path) -> int:
    """Return the number of rows currently in witness.jsonl. Use as
    `after_count` baseline before firing an rcon that should append."""
    return len(read_witness_jsonl(serverfiles))
