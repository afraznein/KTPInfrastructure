#!/usr/bin/env python3
"""
KTP HLTV Demo Renamer

Watches each game host's amxx log for `[KTP HLTV] MATCH_WINDOW_OPEN` /
`MATCH_WINDOW_CLOSE` lines emitted by KTPHLTVRecorder v1.7.0+. On each closed
match window, scans the data server's HLTV demos directory for `auto_*-*.dem`
files whose mtime falls inside the window and renames them to the canonical
format the existing `ktp-organize-hltv-demos.sh` recognizes:

    <matchtype>_<match_id>-<UPPER_FRIENDLY>(_h1|_h2)?-<hltv_ts>-<map>.dem

Multi-segment matches (HLTV source-reconnect mid-match) are preserved as
`_part2`, `_part3` ... appended before the `.dem` extension.

Service runs on the data server (74.91.112.242) as root.

Pipeline order (cron):
  1. THIS SERVICE (continuous) — renames auto-*.dem → canonical
  2. ktp-organize-hltv-demos.sh @ 04:00 ET — sorts canonical → demos/<F>/<T>/
  3. ktp-demo-cleanup-auto.sh   @ 04:45 ET — sweeps unmatched auto-*.dem >7d
  4. ktp-demo-retention.sh      @ 04:30 ET — per-tier age retention

Config: /etc/ktp/hltv-demo-renamer.conf  (KEY=value, sourced as env)
State:  /var/lib/hltv-demo-renamer/state.json
Logs:   journalctl -u hltv-demo-renamer
"""

import json
import logging
import os
import re
import signal
import socket
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import paramiko


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Demos directory on the data server — same one ktp-organize-hltv-demos.sh
# operates on. Auto-* files arrive here, get renamed in place.
DEMOS_DIR = Path("/home/hltvserver/hlds/dod")

# Where we persist tail offsets + open windows across restarts.
STATE_DIR = Path("/var/lib/hltv-demo-renamer")
STATE_FILE = STATE_DIR / "state.json"

# How often the main loop polls each host for new log content.
POLL_INTERVAL_SEC = 30

# Match windows older than this without a CLOSE are abandoned (server crash,
# plugin reload mid-match, etc.). 4 hours covers OT + tech pauses + extra
# slack; matches finishing later just don't get renamed automatically.
WINDOW_ABANDON_AGE_SEC = 4 * 3600

# How far back from CLOSE event to look for matching auto-* files. Keep
# generous to absorb mtime/clock skew + HLTV's 60s delay buffer.
MTIME_WINDOW_PAD_BEFORE_SEC = 90
MTIME_WINDOW_PAD_AFTER_SEC = 90

# Fleet topology — kept here in code rather than config so a typo can't
# silently mis-route renames. Maintained alongside the canonical mapping
# in fleet_alias_convention memory + KTPInfrastructure TECHNICAL_GUIDE.
GAME_HOSTS: Dict[str, Dict] = {
    "ATL": {"ip": "74.91.121.9",   "user": "dodserver", "ports": [27015, 27016, 27017, 27018, 27019]},
    "DAL": {"ip": "74.91.126.55",  "user": "dodserver", "ports": [27015, 27016, 27017, 27018, 27019]},
    "DEN": {"ip": "66.163.114.109","user": "dodserver", "ports": [27015, 27016, 27017, 27018, 27019]},
    "NY":  {"ip": "74.91.123.64",  "user": "dodserver", "ports": [27015, 27016, 27017, 27018, 27019]},
    "CHI": {"ip": "172.238.176.101","user": "dodserver","ports": [27015, 27016, 27017, 27018]},  # 27019 disabled
}

# HLTV port → UPPER_FRIENDLY (must match existing /demos/ directory tree).
HLTV_PORT_BASE_TO_REGION = {
    27020: "ATL",
    27025: "DAL",
    27030: "DEN",
    27035: "NY",
    27040: "CHI",
}


def hltv_port_to_friendly(hltv_port: int) -> Optional[str]:
    """Map an HLTV port (27020-27044) to its UPPER fleet alias (ATL1..CHI5).

    Returns None for ports outside the fleet — caller should warn + skip.
    """
    for base, region in HLTV_PORT_BASE_TO_REGION.items():
        if base <= hltv_port < base + 5:
            return f"{region}{hltv_port - base + 1}"
    return None


# ---------------------------------------------------------------------------
# Log line parsing
# ---------------------------------------------------------------------------

# AMXX log_amx() format:
#   L 04/29/2026 - 21:50:57: [KTPHLTVRecorder.amxx] [KTP HLTV] MATCH_WINDOW_OPEN ...
#
# We match the [KTP HLTV] portion and split key=value pairs.
_RE_WINDOW_OPEN = re.compile(
    r"\[KTP HLTV\] MATCH_WINDOW_OPEN\s+(?P<kv>.+?)$"
)
_RE_WINDOW_CLOSE = re.compile(
    r"\[KTP HLTV\] MATCH_WINDOW_CLOSE\s+(?P<kv>.+?)$"
)
_RE_KV = re.compile(r"(\w+)=(\S+)")


def parse_window_line(line: str) -> Optional[Tuple[str, Dict[str, str]]]:
    """Parse a MATCH_WINDOW_OPEN/CLOSE line.

    Returns (kind, kv_dict) where kind is "open" or "close", or None if the
    line is unrelated.
    """
    m = _RE_WINDOW_OPEN.search(line)
    if m:
        kv = dict(_RE_KV.findall(m.group("kv")))
        return ("open", kv)
    m = _RE_WINDOW_CLOSE.search(line)
    if m:
        kv = dict(_RE_KV.findall(m.group("kv")))
        return ("close", kv)
    return None


# Source filename produced by HLTV when cfg has `record auto_<friendly>`.
# HLTV appends `-<YYMMDDHHMM>-<map>` automatically on each source-rotate.
# Confirmed 2026-04-29 against production v1.6.0 log: HLTV's auto-suffix
# behavior preserves the configured basename verbatim.
_RE_AUTO_DEMO = re.compile(
    r"^auto_(?P<friendly>[a-zA-Z0-9]+)-(?P<hltv_ts>\d{10})-(?P<map>.+)\.dem$"
)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class OpenWindow:
    hltv_port: int
    match_id: str
    half: str           # "h1" / "h2" / "ot1" / etc.
    match_type: str     # "ktp" / "scrim" / "12man" / "draft" (lowercase)
    map: str
    open_unix: int
    close_unix: Optional[int] = None  # set on CLOSE event

    def key(self) -> Tuple[int, str, str]:
        return (self.hltv_port, self.match_id, self.half)


@dataclass
class State:
    # Per-(host, port, date) byte offset into that day's L<YYYYMMDD>.log
    log_offsets: Dict[str, int] = field(default_factory=dict)
    # Open windows awaiting CLOSE
    open_windows: List[OpenWindow] = field(default_factory=list)

    @classmethod
    def load(cls) -> "State":
        if not STATE_FILE.exists():
            return cls()
        try:
            data = json.loads(STATE_FILE.read_text())
            return cls(
                log_offsets=data.get("log_offsets", {}),
                open_windows=[OpenWindow(**w) for w in data.get("open_windows", [])],
            )
        except Exception as e:
            logging.error("State load failed (%s) — starting clean", e)
            return cls()

    def save(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "log_offsets": self.log_offsets,
            "open_windows": [asdict(w) for w in self.open_windows],
        }, indent=2))
        tmp.replace(STATE_FILE)


# ---------------------------------------------------------------------------
# SSH log tailer
# ---------------------------------------------------------------------------

class HostTailer:
    """Maintains a paramiko SSHClient + SFTP session per game host.

    Reconnects on disconnect. Reads new bytes from each instance's current-day
    amxx log starting at the persisted offset.
    """

    def __init__(self, region: str, ip: str, user: str, ports: List[int]):
        self.region = region
        self.ip = ip
        self.user = user
        self.ports = ports
        self._ssh: Optional[paramiko.SSHClient] = None
        self._sftp: Optional[paramiko.SFTPClient] = None

    def _connect(self) -> None:
        if self._ssh is not None:
            return
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        # SSH key auth via root's id_ed25519 (set up alongside hltv-restart-all.sh).
        client.connect(
            self.ip,
            username=self.user,
            timeout=10,
            banner_timeout=10,
            auth_timeout=10,
            look_for_keys=True,
            allow_agent=False,
        )
        self._ssh = client
        self._sftp = client.open_sftp()
        logging.info("[%s] SSH connected", self.region)

    def _disconnect(self) -> None:
        for obj_name in ("_sftp", "_ssh"):
            obj = getattr(self, obj_name, None)
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
                setattr(self, obj_name, None)

    def _today_log_path(self, port: int) -> str:
        # AMXX rotates daily on the local server's date. Servers run TZ=ET so
        # match midnight ET for log rotation; here we use the data server's
        # local date which is also ET. Good enough — a few-second skew at
        # midnight will resolve next poll.
        date = datetime.now().strftime("%Y%m%d")
        return f"/home/{self.user}/dod-{port}/serverfiles/dod/addons/ktpamx/logs/L{date}.log"

    def _offset_key(self, port: int) -> str:
        date = datetime.now().strftime("%Y%m%d")
        return f"{self.region}/{port}/{date}"

    def read_new_lines(self, state: State) -> List[str]:
        """Returns concatenated new lines from all this host's instance logs."""
        try:
            self._connect()
        except Exception as e:
            logging.warning("[%s] SSH connect failed: %s", self.region, e)
            self._disconnect()
            return []

        all_lines: List[str] = []
        for port in self.ports:
            path = self._today_log_path(port)
            key = self._offset_key(port)
            try:
                stat = self._sftp.stat(path)  # type: ignore[union-attr]
            except (FileNotFoundError, IOError):
                # Log doesn't exist yet (server not started today, or no plugin
                # output yet). Skip silently — next poll will pick it up.
                continue

            offset = state.log_offsets.get(key, 0)
            if offset > stat.st_size:
                # File rotated or truncated — start over.
                logging.info("[%s/%d] log truncated (offset=%d size=%d), resetting",
                             self.region, port, offset, stat.st_size)
                offset = 0
            if offset == stat.st_size:
                continue

            try:
                with self._sftp.open(path, "r") as f:  # type: ignore[union-attr]
                    f.seek(offset)
                    chunk = f.read(stat.st_size - offset)
            except Exception as e:
                logging.warning("[%s/%d] read failed: %s", self.region, port, e)
                continue

            text = chunk.decode("utf-8", errors="replace") if isinstance(chunk, bytes) else chunk
            new_offset = offset + len(chunk)
            state.log_offsets[key] = new_offset

            # Only retain MATCH_WINDOW lines; everything else is noise.
            for line in text.splitlines():
                if "MATCH_WINDOW_" in line:
                    all_lines.append(line)

        return all_lines


# ---------------------------------------------------------------------------
# Renamer
# ---------------------------------------------------------------------------

class Renamer:
    """Scans DEMOS_DIR for auto-* files matching a closed window, renames in place."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    def rename_for_window(self, window: OpenWindow) -> List[Tuple[Path, Path]]:
        """Returns list of (original, renamed) paths actually renamed."""
        if window.close_unix is None:
            return []

        friendly = hltv_port_to_friendly(window.hltv_port)
        if friendly is None:
            logging.error("Unknown hltv_port %d — cannot derive friendly", window.hltv_port)
            return []

        mtime_lo = window.open_unix - MTIME_WINDOW_PAD_BEFORE_SEC
        mtime_hi = window.close_unix + MTIME_WINDOW_PAD_AFTER_SEC

        candidates: List[Path] = []
        for path in DEMOS_DIR.glob("auto_*-*.dem"):
            m = _RE_AUTO_DEMO.match(path.name)
            if not m:
                continue
            # Source friendly in basename must match (case-insensitive against
            # configured `record auto_<friendly>` in HLTV cfg, which uses
            # lowercase by convention).
            if m.group("friendly").upper() != friendly.upper():
                continue
            try:
                mtime = path.stat().st_mtime
            except FileNotFoundError:
                continue
            if not (mtime_lo <= mtime <= mtime_hi):
                continue
            candidates.append(path)

        if not candidates:
            logging.info("Window %s/%s/%s closed but no matching auto-* files in mtime [%s, %s]",
                         friendly, window.match_id, window.half,
                         _fmt_ts(mtime_lo), _fmt_ts(mtime_hi))
            return []

        candidates.sort(key=lambda p: p.stat().st_mtime)

        renamed: List[Tuple[Path, Path]] = []
        for idx, src in enumerate(candidates):
            m = _RE_AUTO_DEMO.match(src.name)
            assert m is not None  # filtered above
            hltv_ts = m.group("hltv_ts")
            map_name = m.group("map")
            target_name = self._build_target_name(window, friendly, hltv_ts, map_name, segment=idx)
            dst = DEMOS_DIR / target_name

            if dst.exists():
                logging.warning("Target exists, skipping: %s -> %s", src.name, dst.name)
                continue

            if self.dry_run:
                logging.info("[DRY] %s -> %s", src.name, dst.name)
                renamed.append((src, dst))
                continue

            try:
                src.rename(dst)
                logging.info("Renamed: %s -> %s", src.name, dst.name)
                renamed.append((src, dst))
            except OSError as e:
                logging.error("Rename failed: %s -> %s: %s", src.name, dst.name, e)

        return renamed

    @staticmethod
    def _build_target_name(window: OpenWindow, friendly: str, hltv_ts: str,
                           map_name: str, segment: int) -> str:
        """Produce: <matchtype>_<match_id>-<UPPER_FRIENDLY>_<half>-<hltv_ts>-<map>.dem
        with optional _partN suffix on additional segments (segment > 0).

        match_id is taken verbatim from the plugin's MATCH_WINDOW_OPEN line —
        whatever KTPMatchHandler emits is what the organizer + portal see.

        Defensive lowercase on match_type: the existing organizer's regex is
        `[a-z0-9]+` and rejects mixed-case (e.g., `ktpOT`). Plugin v1.7.0 emits
        lowercase, but a stale plugin or a future enum entry might not — keep
        the renamer hardened.
        """
        parts = [
            window.match_type.lower(),
            "_",
            window.match_id,
            "-",
            friendly,
        ]
        # Organizer regex only matches `(_h[12])?` for the half marker. Any
        # other half value (ot1, ot2...) would BREAK the regex and the demo
        # would never auto-organize. Strip non-h1/h2 halves; OT rounds remain
        # distinguishable by the hltv_ts segment (each OT source-rotate gets
        # a fresh timestamp).
        if window.half in ("h1", "h2"):
            parts.extend(["_", window.half])
        parts.extend(["-", hltv_ts, "-", map_name])
        if segment > 0:
            parts.extend(["_part", str(segment + 1)])
        parts.append(".dem")
        return "".join(parts)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

class Service:
    def __init__(self, dry_run: bool = False):
        self.state = State.load()
        self.tailers = [
            HostTailer(region, info["ip"], info["user"], info["ports"])
            for region, info in GAME_HOSTS.items()
        ]
        self.renamer = Renamer(dry_run=dry_run)
        self._stop = False

        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)

    def _on_signal(self, signum, frame):
        logging.info("Signal %d received — shutting down", signum)
        self._stop = True

    def _ingest_lines(self, lines: List[str]) -> None:
        for line in lines:
            parsed = parse_window_line(line)
            if parsed is None:
                continue
            kind, kv = parsed
            try:
                hltv_port = int(kv.get("hltv_port", "0"))
                match_id = kv.get("match_id", "")
                half = kv.get("half", "")
                match_type = kv.get("match_type", "")
                map_name = kv.get("map", "")
                wall_time = int(kv.get("wall_time", "0"))
            except (ValueError, KeyError) as e:
                logging.warning("Malformed window line: %s (%s)", line, e)
                continue

            if not match_id or not hltv_port:
                logging.warning("Window line missing match_id/hltv_port: %s", line)
                continue

            if kind == "open":
                # KTPMatchHandler fires ktp_match_start once per half (h1, h2,
                # ot1...). MATCH_WINDOW_CLOSE only fires once per whole match
                # at MATCH_END. So when h2 OPEN arrives, h1's window is still
                # open — close it now using THIS event's wall_time, so h1's
                # mtime-bound doesn't bleed into h2's demo files.
                for w in self.state.open_windows:
                    if (w.hltv_port == hltv_port
                            and w.match_id == match_id
                            and w.close_unix is None):
                        w.close_unix = wall_time
                        logging.info("Auto-closing prior half: port=%d match=%s half=%s",
                                     w.hltv_port, w.match_id, w.half)

                # Replace any existing window with EXACT same key (plugin
                # restart mid-match, log re-replay, etc.) — last write wins.
                self.state.open_windows = [
                    w for w in self.state.open_windows
                    if w.key() != (hltv_port, match_id, half)
                ]
                self.state.open_windows.append(OpenWindow(
                    hltv_port=hltv_port, match_id=match_id, half=half,
                    match_type=match_type, map=map_name, open_unix=wall_time,
                ))
                logging.info("OPEN  %s match=%s half=%s type=%s map=%s",
                             hltv_port, match_id, half, match_type, map_name)
            else:
                # CLOSE: close the last still-open window for (port, match_id).
                # Auto-close logic above ensures only one is open at CLOSE time.
                closed_count = 0
                for w in self.state.open_windows:
                    if (w.hltv_port == hltv_port
                            and w.match_id == match_id
                            and w.close_unix is None):
                        w.close_unix = wall_time
                        closed_count += 1
                logging.info("CLOSE %s match=%s (closed %d half-window%s)",
                             hltv_port, match_id, closed_count,
                             "" if closed_count == 1 else "s")

    def _process_closed_windows(self) -> None:
        """Run the renamer for any closed windows; remove successful renames from state."""
        still_open: List[OpenWindow] = []
        now = int(time.time())
        for w in self.state.open_windows:
            if w.close_unix is not None:
                self.renamer.rename_for_window(w)
                # Drop closed windows regardless of rename outcome — log
                # captures missing/orphan cases for operator inspection.
            elif now - w.open_unix > WINDOW_ABANDON_AGE_SEC:
                logging.warning("Abandoning stale window: port=%d match=%s half=%s age=%ds",
                                w.hltv_port, w.match_id, w.half, now - w.open_unix)
            else:
                still_open.append(w)
        self.state.open_windows = still_open

    def run(self) -> None:
        logging.info("hltv-demo-renamer starting (dry_run=%s)", self.renamer.dry_run)
        logging.info("Tailing %d game hosts × %d ports each (24 active instances)",
                     len(self.tailers), 5)
        while not self._stop:
            try:
                for tailer in self.tailers:
                    if self._stop:
                        break
                    lines = tailer.read_new_lines(self.state)
                    if lines:
                        self._ingest_lines(lines)
                self._process_closed_windows()
                self.state.save()
            except Exception as e:
                logging.exception("Main loop iteration failed: %s", e)

            for _ in range(POLL_INTERVAL_SEC):
                if self._stop:
                    break
                time.sleep(1)
        logging.info("Shutdown complete")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_ts(unix: int) -> str:
    return datetime.fromtimestamp(unix).strftime("%Y-%m-%d %H:%M:%S")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    dry_run = "--dry-run" in sys.argv
    Service(dry_run=dry_run).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
