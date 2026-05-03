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


def _logs_dir(serverfiles: Path) -> Path:
    return serverfiles / "dod" / "addons" / "ktpamx" / "logs"


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
    after_offset: int = 0,
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
        if log is not None and log.stat().st_size > after_offset:
            with log.open("rb") as f:
                f.seek(after_offset)
                # Decode best-effort — log_ktp emits ASCII but DoD names can
                # have weird chars in player-input fields. errors='replace'
                # keeps us moving.
                tail = f.read().decode("utf-8", errors="replace")
            for line in tail.splitlines():
                if target_substring in line:
                    return line
        time.sleep(poll_interval)

    raise TimeoutError(
        f"event={event_name!r} not found in {_logs_dir(serverfiles)}/L*.log "
        f"within {timeout:.1f}s (after_offset={after_offset})"
    )


def current_log_size(serverfiles: Path) -> int:
    """Return the current size in bytes of the log file. Use as
    `after_offset` baseline before triggering an rcon, then re-pass to
    `wait_for_log_event` to only scan new bytes."""
    log = _latest_log_file(Path(serverfiles).resolve())
    return log.stat().st_size if log is not None else 0


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
