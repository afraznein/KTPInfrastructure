"""Run hlstats.pl against the ephemeral database, fed from the test server's log.

## Why stdin rather than UDP

`hlstats.pl` normally listens on UDP for lines forwarded by `logaddress_add`.
The harness uses its `--stdin` mode instead:

    hlstats.pl --stdin --server-ip 127.0.0.1 --server-port <port> \
               --db-host ... --db-name ... --db-username ...

In that mode the daemon disables its UDP listener **and sets `$g_rcon = 0`**
(hlstats.pl:1971-1972), which is worth having for free: the production daemon
rcons servers back, and a test daemon that rcons the server under test would be
an extra moving part with no upside. Feeding the log file directly also removes
UDP loss and ordering from a test that is trying to prove attribution logic.

`--server-ip` and `--server-port` are mandatory in stdin mode — the daemon
exits 255 without them, because it has no packet source address to identify the
server by.

## The server row is not optional

The daemon resolves a server by `address` + `port` against `hlstats_Servers`
(hlstats.pl:815-819). With no matching row the lines have no server to attach
to. `ensure_server_row()` inserts it, and must run **before** the daemon
starts — same class of ordering trap as the action seeds, and for the same
reason: getting it wrong loses data quietly rather than loudly.

## Known-unverified: the log-line prefix

Game-log lines on disk carry an `L 08/09/2026 - 12:00:00: ` prefix, and the
daemon has a `--timestamp` switch that changes how it treats that. Whether
stdin mode wants lines with the prefix intact (and whether `--timestamp`
should be passed) has NOT been verified against a running daemon — it is a
Phase 0 question. `strip_prefix` and `timestamp_flag` exist so the answer is a
config change; the default is "feed lines exactly as the engine wrote them",
which is what a UDP forward would have delivered.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path


class DaemonError(RuntimeError):
    """The daemon could not run. Fatal — a Lane B run without a daemon asserts
    nothing, so this must never degrade to a skip."""


_TS_PREFIX = "L "


def strip_log_prefix(line: str) -> str:
    """Drop the engine's `L 08/09/2026 - 12:00:00: ` prefix from a log line.

    A line that does not match the shape passes through untouched — without
    that guard, any line containing a colon would lose its first field.
    """
    if not line.startswith(_TS_PREFIX):
        return line
    _, sep, rest = line.partition(": ")
    return rest if sep else line


def preflight() -> dict:
    """Check the daemon's runtime deps before booting anything expensive.

    `perl -c hlstats.pl` aborts at `use DBI` unless DBI is present, so a
    missing DBD::mysql shows up here as a clear message rather than as a daemon
    that exits three steps later with the log already flowing.
    """
    perl = shutil.which("perl")
    if not perl:
        raise DaemonError("perl not found on PATH")
    found = {}
    for mod in ("DBI", "DBD::mysql"):
        r = subprocess.run([perl, "-e", f"use {mod}; print 'ok'"],
                           capture_output=True, text=True)
        found[mod] = (r.returncode == 0)
    missing = [m for m, ok in found.items() if not ok]
    if missing:
        raise DaemonError(
            f"perl modules missing: {', '.join(missing)}. The daemon cannot "
            f"connect to MySQL without them (install libdbd-mysql-perl)."
        )
    return {"perl": perl, **found}


@dataclass
class HlstatsDaemon:
    """A private hlstats.pl process fed from a growing log file."""

    script: Path
    db_socket: Path
    db_name: str
    db_user: str
    server_ip: str
    server_port: int
    log_source: Path
    stdout_path: Path
    strip_prefix: bool = False
    timestamp_flag: bool = False
    _proc: subprocess.Popen | None = None
    _pump: threading.Thread | None = None
    _stop: threading.Event = field(default_factory=threading.Event)
    _fed: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # -- schema prerequisite ----------------------------------------------

    @staticmethod
    def ensure_server_row(db, *, address: str, port: int, game: str = "dod",
                          name: str = "KTP Lane B ephemeral") -> None:
        """Insert the hlstats_Servers row the daemon resolves lines against.

        Must run before the daemon starts. Without it the daemon finds no
        server for the incoming lines.
        """
        existing = db.scalar(
            "SELECT serverId FROM hlstats_Servers "
            f"WHERE address='{address}' AND port={int(port)}"
        )
        if existing:
            return
        db.sql(
            "INSERT INTO hlstats_Servers (address, port, name, game) "
            f"VALUES ('{address}', {int(port)}, '{name}', '{game}')"
        )

    # -- lifecycle ---------------------------------------------------------

    def start(self, *, ready_timeout: float = 30.0) -> None:
        if not self.script.is_file():
            raise DaemonError(f"hlstats.pl not found at {self.script}")
        info = preflight()

        argv = [
            info["perl"], str(self.script),
            "--stdin",
            "--server-ip", self.server_ip,
            "--server-port", str(self.server_port),
            # The client resolves `localhost` to the unix socket; pointing at
            # the private socket keeps this off the production instance even if
            # a default my.cnf is lying around.
            "--db-host", f"localhost;mysql_socket={self.db_socket}",
            "--db-name", self.db_name,
            "--db-username", self.db_user,
            "--db-password", "",
        ]
        if self.timestamp_flag:
            argv.append("--timestamp")

        self.stdout_path.parent.mkdir(parents=True, exist_ok=True)
        out = self.stdout_path.open("wb")
        self._proc = subprocess.Popen(
            argv,
            cwd=str(self.script.parent),
            stdin=subprocess.PIPE,
            stdout=out,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PERL_UNICODE": ""},
        )

        # Exit 255 is the daemon's own "you must specify --server-ip/--port";
        # anything else early is usually a DB connect failure. Either way the
        # captured stdout says which.
        deadline = time.monotonic() + ready_timeout
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise DaemonError(
                    f"hlstats.pl exited immediately (rc={self._proc.returncode}); "
                    f"see {self.stdout_path}:\n"
                    + self._tail_stdout(40)
                )
            if "reading log data" in self._read_stdout():
                break
            time.sleep(0.5)

        self._stop.clear()
        self._pump = threading.Thread(target=self._pump_log, name="hlstats-log-pump",
                                      daemon=True)
        self._pump.start()

    def _pump_log(self) -> None:
        """Tail `log_source` and write each new line to the daemon's stdin.

        Starts at the CURRENT end of file, not the beginning: the log may
        already hold boot noise and — more importantly — lines from before the
        actions were seeded, which the daemon would silently discard anyway.
        """
        while not self._stop.is_set() and not self.log_source.exists():
            time.sleep(0.2)
        if self._stop.is_set():
            return
        with self.log_source.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(0, os.SEEK_END)
            while not self._stop.is_set():
                line = f.readline()
                if not line:
                    time.sleep(0.2)
                    continue
                self._feed(line.rstrip("\r\n"))

    def _feed(self, line: str) -> None:
        if not line:
            return
        if self.strip_prefix:
            line = strip_log_prefix(line)
        proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            return
        try:
            proc.stdin.write((line + "\n").encode("utf-8", "replace"))
            proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            return
        with self._lock:
            self._fed += 1

    def feed_line(self, line: str) -> None:
        """Inject a line directly. Useful for replaying a captured log to
        reproduce a failure without re-running bots."""
        self._feed(line)

    @property
    def lines_fed(self) -> int:
        with self._lock:
            return self._fed

    def drain(self, *, quiet_for: float = 5.0, timeout: float = 90.0) -> int:
        """Wait until the log stops producing lines, then give the daemon time
        to flush.

        The plugin's own buffer flushes on a 5s task (`KSC_BUF_FLUSH_SECS`), so
        a drain shorter than that can miss the tail of a match. `quiet_for`
        defaults above it deliberately — asserting on rows before the buffer
        flushed would look exactly like the capture being broken.
        """
        deadline = time.monotonic() + timeout
        last = self.lines_fed
        last_change = time.monotonic()
        while time.monotonic() < deadline:
            time.sleep(0.5)
            now = self.lines_fed
            if now != last:
                last, last_change = now, time.monotonic()
            elif time.monotonic() - last_change >= quiet_for:
                return now
        return self.lines_fed

    def _read_stdout(self) -> str:
        try:
            return self.stdout_path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return ""

    def _tail_stdout(self, n: int) -> str:
        return "\n".join(self._read_stdout().splitlines()[-n:])

    def sql_errors(self) -> list[str]:
        """SQL_ERROR / error lines from the daemon's own output.

        The deployment plan's smoke tests all end with a journalctl grep for
        these. Same check, mechanised.
        """
        return [
            ln for ln in self._read_stdout().splitlines()
            if "SQL_ERROR" in ln or "DBD::" in ln
        ]

    def stop(self) -> None:
        self._stop.set()
        if self._pump is not None:
            self._pump.join(timeout=5.0)
            self._pump = None
        proc = self._proc
        if proc is not None:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:
                pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            self._proc = None

    def __enter__(self) -> "HlstatsDaemon":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()
