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
  3. ktp-demo-cleanup-auto.sh   every 30 min — sweeps unmatched auto-*.dem >6h
     (skips while this service is not active — 2026-07-07 interlock)
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
    # Bug 1 fix: if HLTV is still writing to the candidate auto-*.dem at the
    # moment we'd rename, we defer the rename until either (a) a newer auto-*
    # appears for this friendly (HLTV rotated → safe to rename), or (b) the
    # window is abandoned (4h timeout → flush as combined / unlabeled).
    # `deferred_candidates` stashes the BASENAMES we identified at defer time,
    # since by the time HLTV rotates the candidate's mtime has crawled past
    # our original window and a fresh mtime-based scan would miss them.
    deferred: bool = False
    deferred_candidates: List[str] = field(default_factory=list)

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
            # Filter to known dataclass fields. Defends against schema drift
            # in either direction: a state.json from a future build with extra
            # keys won't TypeError on `OpenWindow(**w)`; a state.json from a
            # past build missing new fields uses dataclass defaults.
            known = {f.name for f in OpenWindow.__dataclass_fields__.values()}
            return cls(
                log_offsets=data.get("log_offsets", {}),
                open_windows=[
                    OpenWindow(**{k: v for k, v in w.items() if k in known})
                    for w in data.get("open_windows", [])
                ],
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

            # Advance the offset only past the last COMPLETE line. The async
            # line-buffered writer can be mid-line at read time; consuming a
            # torn MATCH_WINDOW line parses wall_time=0 (open instantly
            # abandoned / close scans the 1970 epoch) and silently loses the
            # window's rename. The remainder re-reads next poll. Byte math on
            # the raw chunk — the persisted offset is a byte offset.
            raw = chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")
            last_nl = raw.rfind(b"\n")
            if last_nl == -1:
                continue  # no complete line yet — don't advance the offset
            raw = raw[: last_nl + 1]
            text = raw.decode("utf-8", errors="replace")
            state.log_offsets[key] = offset + last_nl + 1

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

    def rename_for_window(self, window: OpenWindow, *, force: bool = False) -> List[Tuple[Path, Path]]:
        """Returns list of (original, renamed) paths actually renamed.

        Bug 1 deferred-rename: if all candidate files are the latest auto-*
        for this friendly (i.e., HLTV may still be writing to one of them),
        defer the rename. Stashes basenames on `window.deferred_candidates`
        and sets `window.deferred=True`. Caller leaves the window in state;
        subsequent calls retry. When HLTV eventually rotates, a newer auto-*
        appears and the deferred candidates can be safely renamed.

        `force=True` flushes a deferred window unconditionally (used at
        abandon-time), naming with no half marker (combined / single-file
        match) since we know HLTV never rotated.
        """
        if window.close_unix is None:
            return []

        friendly = hltv_port_to_friendly(window.hltv_port)
        if friendly is None:
            logging.error("Unknown hltv_port %d — cannot derive friendly", window.hltv_port)
            return []

        all_friendly_auto = self._all_auto_for_friendly(friendly)

        # Two paths into this method:
        # (1) First-time rename — scan DEMOS_DIR by mtime against the window's
        #     [open-90s, close+90s] range to pick candidates.
        # (2) Retry of a previously-deferred window — use the stashed basenames
        #     since their mtimes have crawled past the original window while
        #     HLTV continued writing.
        flush_combined = False
        if window.deferred and window.deferred_candidates:
            candidates = [DEMOS_DIR / b for b in window.deferred_candidates
                          if (DEMOS_DIR / b).exists()]
            if not candidates:
                # Files vanished (manual cleanup, prior rename) — un-defer + drop.
                logging.warning("Deferred candidates gone: %s/%s/%s — dropping window",
                                friendly, window.match_id, window.half)
                window.deferred = False
                return []
            has_successor = self._has_successor_auto(window, all_friendly_auto)
            if not has_successor and not force:
                # Still no rotation evidence; keep waiting.
                return []
            # On force without successor → flush as combined-name (no half marker).
            flush_combined = force and not has_successor
        else:
            mtime_lo = window.open_unix - MTIME_WINDOW_PAD_BEFORE_SEC
            mtime_hi = window.close_unix + MTIME_WINDOW_PAD_AFTER_SEC
            candidates = [p for p, mt in all_friendly_auto if mtime_lo <= mt <= mtime_hi]

            if not candidates:
                # No auto-* in our mtime range. Either genuine recording loss OR
                # HLTV-did-not-rotate-at-half-boundary case (data is in the
                # prior-half file, no separate file for us). Distinguish so the
                # log line is accurate — soak-verify can then differentiate
                # "demo missing" from "single-file match, data preserved".
                if self._sibling_demo_extends_into(window, friendly):
                    logging.info(
                        "Window %s/%s/%s: no separate auto-* file (HLTV did not rotate at half boundary; "
                        "demo data is included in the prior-half file — single-file match, no data loss)",
                        friendly, window.match_id, window.half,
                    )
                else:
                    logging.info(
                        "Window %s/%s/%s closed but no matching auto-* files in mtime [%s, %s]",
                        friendly, window.match_id, window.half,
                        _fmt_ts(mtime_lo), _fmt_ts(mtime_hi),
                    )
                return []

            # Defer if all candidates are at-or-newer than every other auto-*
            # for this friendly — i.e., HLTV may still be writing to one of
            # them. The renamer would otherwise rename a file whose FD HLTV
            # holds open, and subsequent writes (from later halves) would land
            # under the renamed path, mislabeling later-half data as h1.
            if not force:
                latest_friendly_mtime = max(mt for _, mt in all_friendly_auto)
                candidate_max_mtime = max(c.stat().st_mtime for c in candidates)
                if candidate_max_mtime >= latest_friendly_mtime:
                    window.deferred = True
                    window.deferred_candidates = [c.name for c in candidates]
                    logging.info(
                        "Deferring rename: %s/%s/%s — candidate(s) are still the latest auto-* for %s "
                        "(HLTV may still be writing). Will retry on rotation or after %ds abandon timeout.",
                        friendly, window.match_id, window.half, friendly, WINDOW_ABANDON_AGE_SEC,
                    )
                    return []

        # A multi-candidate set can include the NEXT window's file: at half
        # close (= next half's open) the successor's just-created auto-* is
        # already growing inside our [open-pad, close+pad] scan range, and the
        # deferral stash then locks it to this window — flushing renames h2's
        # demo as ..._h1-..._part2.dem. By the time we reach here every
        # candidate is settled (non-latest, successor exists, or forced), so
        # the FINAL mtime tells ownership: last write well past OUR close =
        # a later window's file. Keep a sole candidate regardless — the
        # legitimate no-rotation single-file case extends past close by design.
        if len(candidates) > 1:
            settled = []
            for c in candidates:
                try:
                    if c.stat().st_mtime <= window.close_unix + MTIME_WINDOW_PAD_AFTER_SEC:
                        settled.append(c)
                except OSError:
                    continue  # vanished under us — drop
            if settled and len(settled) < len(candidates):
                dropped = [c.name for c in candidates if c not in settled]
                logging.info(
                    "Window %s/%s/%s: excluding %s (last write past close+%ds — belongs to a later window)",
                    friendly, window.match_id, window.half, dropped, MTIME_WINDOW_PAD_AFTER_SEC,
                )
                candidates = settled

        candidates.sort(key=lambda p: p.stat().st_mtime)

        renamed: List[Tuple[Path, Path]] = []
        for idx, src in enumerate(candidates):
            m = _RE_AUTO_DEMO.match(src.name)
            if m is None:
                continue
            hltv_ts = m.group("hltv_ts")
            map_name = m.group("map")
            target_name = self._build_target_name(window, friendly, hltv_ts, map_name,
                                                  segment=idx, omit_half=flush_combined)
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

        # Successful processing — un-defer so caller drops the window.
        window.deferred = False
        window.deferred_candidates = []
        return renamed

    def _all_auto_for_friendly(self, friendly: str) -> List[Tuple[Path, float]]:
        """All current auto-*.dem files for `friendly` with their mtimes."""
        out: List[Tuple[Path, float]] = []
        for path in DEMOS_DIR.glob("auto_*-*.dem"):
            m = _RE_AUTO_DEMO.match(path.name)
            if not m or m.group("friendly").upper() != friendly.upper():
                continue
            try:
                out.append((path, path.stat().st_mtime))
            except FileNotFoundError:
                continue
        return out

    def _has_successor_auto(self, window: OpenWindow,
                            all_friendly_auto: List[Tuple[Path, float]]) -> bool:
        """True iff some auto-* file (other than our deferred candidates) has
        mtime newer than any deferred candidate — i.e., HLTV has rotated."""
        if not window.deferred_candidates:
            return False
        candidate_basenames = set(window.deferred_candidates)
        deferred_mtimes: List[float] = []
        for b in window.deferred_candidates:
            p = DEMOS_DIR / b
            try:
                deferred_mtimes.append(p.stat().st_mtime)
            except FileNotFoundError:
                continue
        if not deferred_mtimes:
            return True  # all candidates gone — treat as rotated (caller un-defers + drops)
        deferred_max = max(deferred_mtimes)
        return any(mt > deferred_max for path, mt in all_friendly_auto
                   if path.name not in candidate_basenames)

    def _sibling_demo_extends_into(self, window: OpenWindow, friendly: str) -> bool:
        """True iff a renamed sibling demo from this match (e.g. _h1-) exists
        with mtime falling inside our window's [open-pad, close+pad] range —
        indicates HLTV did not rotate at the half boundary and the data
        crossed into us via the still-open FD on the prior file.

        `match_type.lower()` mirrors `_build_target_name`'s defensive
        normalization. Without it, a stale or future plugin emitting mixed-case
        match_type (e.g., `KTP`) would skip detection because the rename writes
        lowercase but this glob would search uppercase.
        """
        pattern = f"{window.match_type.lower()}_{window.match_id}-{friendly.upper()}_*.dem"
        mtime_lo = window.open_unix - MTIME_WINDOW_PAD_BEFORE_SEC
        mtime_hi = window.close_unix + MTIME_WINDOW_PAD_AFTER_SEC
        for path in DEMOS_DIR.glob(pattern):
            try:
                mtime = path.stat().st_mtime
            except FileNotFoundError:
                continue
            if mtime_lo <= mtime <= mtime_hi:
                return True
        return False

    @staticmethod
    def _build_target_name(window: OpenWindow, friendly: str, hltv_ts: str,
                           map_name: str, segment: int, *, omit_half: bool = False) -> str:
        """Produce: <matchtype>_<match_id>(_h<n>)?-<hltv_ts>-<map>.dem
        with optional _partN suffix on additional segments (segment > 0).

        match_id is taken verbatim from the plugin's MATCH_WINDOW_OPEN line —
        whatever KTPMatchHandler emits is what the organizer + portal see.
        KTPMatchHandler.sma:1966,1971 formats match_id with the short hostname
        suffix already baked in (`<timestamp>-<shortHostname>` for standard
        matches; `1.3-<queueId>-<shortHostname>` for 1.3 community 12mans),
        because match_id is also a uniqueness primary key for HLStatsX,
        Discord embeds, and scoring. We do NOT redundantly append <FRIENDLY>
        if match_id already ends in `-<friendly>` — earlier renamer versions
        produced names like `scrim_1777594479-ATL4-ATL4_h1-...` which the
        organizer's regex (single-host) refused to recognize.

        `omit_half=True` produces the half-less form, used when force-flushing
        a deferred window at abandon time (HLTV never rotated; the file is a
        single-file whole-match recording, so labeling it `_h1` or `_h2` would
        be misleading). The organizer's `(_h[12])?` regex makes this optional
        marker — files without it still get organized.

        Defensive lowercase on match_type: the existing organizer's regex is
        `[a-z0-9]+` and rejects mixed-case (e.g., `ktpOT`). Plugin v1.7.0 emits
        lowercase, but a stale plugin or a future enum entry might not — keep
        the renamer hardened.
        """
        parts = [
            window.match_type.lower(),
            "_",
            window.match_id,
        ]
        # Append <FRIENDLY> only if match_id doesn't already end with it. See
        # docstring above for KTPMatchHandler's match_id format convention.
        if friendly and not window.match_id.endswith("-" + friendly):
            parts.extend(["-", friendly])
        # Organizer regex only matches `(_h[12])?` for the half marker. Any
        # other half value (ot1, ot2...) would BREAK the regex and the demo
        # would never auto-organize. Strip non-h1/h2 halves; OT rounds remain
        # distinguishable by the hltv_ts segment (each OT source-rotate gets
        # a fresh timestamp).
        if not omit_half and window.half in ("h1", "h2"):
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
                # Bug 3 idempotency: if a window with the EXACT same key
                # (port + match_id + half) is already open, this is a duplicate
                # OPEN — most often KTPMatchHandler's `ktp_match_start` forward
                # firing twice (genuine double-fire confirmed via wall_time
                # diffs in the 2026-05-03 logs). Suppress auto-close + replace
                # silently. Without this, the auto-close loop below would emit
                # a misleading "Auto-closing prior half: h1" line every time.
                dup = any(
                    w.key() == (hltv_port, match_id, half)
                    and w.close_unix is None
                    for w in self.state.open_windows
                )
                if dup:
                    logging.info("Duplicate OPEN ignored (idempotent): port=%d match=%s half=%s",
                                 hltv_port, match_id, half)
                    continue

                # KTPMatchHandler fires ktp_match_start once per half (h1, h2,
                # ot1...). MATCH_WINDOW_CLOSE only fires once per whole match
                # at MATCH_END. So when h2 OPEN arrives, h1's window is still
                # open — close it now using THIS event's wall_time, so h1's
                # mtime-bound doesn't bleed into h2's demo files.
                #
                # Bug 3 fix: only auto-close DIFFERENT halves. Without the
                # `w.half != half` guard, a duplicate-half OPEN (caught above
                # but kept here as defense in depth) would auto-close the
                # prior entry and emit a misleading log line.
                for w in self.state.open_windows:
                    if (w.hltv_port == hltv_port
                            and w.match_id == match_id
                            and w.half != half
                            and w.close_unix is None):
                        w.close_unix = wall_time
                        logging.info("Auto-closing prior half: port=%d match=%s half=%s",
                                     w.hltv_port, w.match_id, w.half)

                # Drop any pre-existing CLOSED window with the exact same key
                # (rare: plugin restart with re-emitted OPEN, or a stale
                # closed-pending-rename entry from a prior bug). Open same-key
                # entries already short-circuit via the duplicate guard above.
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
        """Run the renamer for any closed windows; remove successful renames from state.

        Deferred windows (Bug 1 fix): kept in state across poll cycles until
        either HLTV rotates (rename_for_window flushes them) or the abandon
        timeout expires, at which point we force-flush as a combined-name
        single-file recording.
        """
        still_open: List[OpenWindow] = []
        now = int(time.time())
        for w in self.state.open_windows:
            if w.close_unix is None:
                if now - w.open_unix > WINDOW_ABANDON_AGE_SEC:
                    logging.warning("Abandoning stale window: port=%d match=%s half=%s age=%ds",
                                    w.hltv_port, w.match_id, w.half, now - w.open_unix)
                else:
                    still_open.append(w)
                continue

            close_age = now - w.close_unix
            if w.deferred and close_age > WINDOW_ABANDON_AGE_SEC:
                # Deferred too long — HLTV never rotated. Flush as combined-name.
                logging.warning(
                    "Deferred-rename abandon: port=%d match=%s half=%s close_age=%ds — forcing combined flush",
                    w.hltv_port, w.match_id, w.half, close_age,
                )
                self.renamer.rename_for_window(w, force=True)
                # Drop after force-flush regardless of outcome.
                continue

            self.renamer.rename_for_window(w)
            if w.deferred:
                # Still waiting on HLTV rotation — keep in state for next poll.
                still_open.append(w)
            # Otherwise rename succeeded (or no-op) — drop from state.
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
