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

## The three gates that silently discard bot events

`hlstats.pl` reads its per-server config ONCE, in `readDatabaseConfig`
(hlstats.pl:1655-1670), from `hlstats_Servers_Config`. Three of its defaults
are fatal to a bot-driven lane, and all three fail the same way: the line
parses, the daemon prints `(IGNORED) ...`, and nothing is written.

| Parameter | Default | Why it matters here |
|---|---|---|
| `IgnoreBots` | **1** | Every Lane B player is a bot. `doEvent_PlayerPlayerAction` short-circuits to `(IGNORED) BOT:` (HLstats_EventHandlers.plib:1459) and no row is recorded. This is the single biggest trap in the daemon leg. |
| `MinPlayers` | **6** | Below it, `(IGNORED) NOTMINPLAYERS:` (plib:1454). 12 bots clears it, but a short debug run with 4 does not, and the failure looks identical to broken capture. |
| `BonusRoundIgnore` | 0 | Off by default, but set it explicitly so a stray end-of-round window cannot eat the tail of a match. |

`ensure_server_row()` writes all three. Note it does NOT need `hlstats_Games`
to be populated: server lookup LEFT JOINs it with `IFNULL(c.realgame,'hl2mp')`
(hlstats.pl:811), and DoD takes no `play_game`-specific branch on the action
path. The row is inserted anyway, for parity with production.

## `<BOT>` authids are accepted, and are not the interesting question

`botidcheck` (hlstats.pl:1415-1424) returns true for `BOT`, `0`, and
`00000000:N:0`. A bot player is then given a synthetic
`BOT:md5(name + server_addr)` uniqueid and created like any other player
(hlstats.pl:1186-1190). Both authid shapes Lane B produces are covered: the
unpatched stack logs `<0>`, the patched one logs `<BOT>`.

Because the uniqueid is derived from the **name**, two bots sharing a name
would collapse into one player row. new_bot's roster is unique, but a bot kit
that recycles names would produce quietly-wrong attribution rather than an
error.

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


def _replacement_resume_offset(current, candidate: Path, offset: int,
                               *, checkpoint_bytes: int = 4096) -> int:
    """Resume when a replacement contains bytes already consumed.

    Docker Desktop bind mounts can change ``st_ino`` for an unchanged growing
    file. Reopening such a path from byte zero duplicates every event already
    sent to HLStatsX. Compare a checkpoint immediately before the consumed
    offset; a genuine replacement resumes at zero, while a rebinding of the
    same content resumes exactly where the pump stopped.
    """
    if offset <= 0:
        return 0
    try:
        if candidate.stat().st_size < offset:
            return 0
        start = max(0, offset - checkpoint_bytes)
        current.seek(start)
        old = current.read(offset - start)
        current.seek(offset)
        with candidate.open("rb") as incoming:
            incoming.seek(start)
            new = incoming.read(offset - start)
        return offset if old == new and len(new) == offset - start else 0
    except OSError:
        return 0


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
    for mod in ("DBI", "DBD::mysql", "Syntax::Keyword::Try"):
        r = subprocess.run([perl, "-e", f"use {mod}; print 'ok'"],
                           capture_output=True, text=True)
        found[mod] = (r.returncode == 0)
    missing = [m for m, ok in found.items() if not ok]
    if missing:
        raise DaemonError(
            f"perl modules missing: {', '.join(missing)}. Install "
            f"libdbi-perl / libdbd-mysql-perl / libsyntax-keyword-try-perl. "
            f"All three fail before the daemon prints anything about itself, "
            f"so the symptom is an immediate exit rather than a useful error."
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
    # `--debug` is repeatable (`debug|d+`). Import mode is otherwise silent per
    # event, so at 0 a discarded line leaves no trace at all and a zero row
    # count has no explanation attached. Level 1 prints each event with its
    # `(IGNORED) <reason>:` prefix, which is the difference between "capture is
    # broken" and "the action row was missing".
    debug: int = 0
    _proc: subprocess.Popen | None = None
    _pump: threading.Thread | None = None
    _stop: threading.Event = field(default_factory=threading.Event)
    _fed: int = 0
    _died: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # -- schema prerequisite ----------------------------------------------

    # Columns hlstats.pl SELECTs that a production-derived base schema can be
    # missing. Not schema drift — `fetch_base_schema.sh` reconstructs
    # `hlstats_Servers` from `information_schema` because the read-only
    # analytics account is denied SHOW CREATE on it, and MySQL hides from
    # `information_schema.columns` any column the account has no privilege on.
    # `rcon_password` is exactly the column such a grant would withhold, so the
    # dump is faithful to what that account can see and still unusable by the
    # daemon, which fails at its very first server lookup:
    #
    #   DBD::mysql::st execute failed: Unknown column 'a.rcon_password'
    #
    # Re-added here rather than hand-patched into the dump, so it holds for any
    # dump anyone takes. The value is never set: --stdin mode sets $g_rcon = 0
    # and Lane B has nothing to rcon.
    _REQUIRED_SERVER_COLUMNS = {
        "rcon_password": "varchar(128) NOT NULL DEFAULT ''",
    }

    @staticmethod
    def repair_reconstructed_schema(db) -> dict:
        """Fix what `fetch_base_schema.sh` could not read off production.

        `hlstats_Servers` is the one table in the dump that is synthesised
        rather than dumped, so it is the one table that can disagree with the
        rest. Two ways it does, both of which stop the daemon at its first
        server lookup and neither of which is visible by reading the SQL:

        1. **A missing column.** MySQL hides from `information_schema.columns`
           any column the account has no privilege on, so a grant that
           withholds the rcon secret yields a faithful-but-incomplete list.
        2. **A different collation.** The synthesised DDL says `DEFAULT CHARSET
           utf8mb4` with no COLLATE, which takes the server default
           (`utf8mb4_0900_ai_ci` on MySQL 8). Every dumped table carries
           production's explicit `utf8mb4_unicode_ci`. Joining the two —
           `hlstats_Servers.game = hlstats_Games.code` — raises *Illegal mix of
           collations*, which reads like a schema bug and is really an artifact
           of how the dump was taken.

        Both are repaired against what the *dumped* tables actually say, rather
        than against a hardcoded expectation, so this keeps working if
        production's charset ever changes.
        """
        repairs: dict = {"columns": [], "collation": None}

        for column, ddl in HlstatsDaemon._REQUIRED_SERVER_COLUMNS.items():
            present = db.scalar(
                "SELECT column_name FROM information_schema.columns "
                f"WHERE table_schema='{db.database}' "
                f"AND table_name='hlstats_Servers' AND column_name='{column}'"
            )
            if not present:
                db.sql(f"ALTER TABLE hlstats_Servers ADD COLUMN `{column}` {ddl}")
                repairs["columns"].append(column)

        # The reference is the most common collation among the genuinely
        # dumped tables — majority rather than any single table, so one oddity
        # in the schema cannot drag the reconstruction off with it.
        rows = db.sql(
            "SELECT table_collation, COUNT(*) c FROM information_schema.tables "
            f"WHERE table_schema='{db.database}' AND table_name <> 'hlstats_Servers' "
            "AND table_collation IS NOT NULL "
            "GROUP BY table_collation ORDER BY c DESC LIMIT 1"
        ).strip().splitlines()
        if len(rows) >= 2:
            want = rows[1].split("\t")[0]
            have = db.scalar(
                "SELECT table_collation FROM information_schema.tables "
                f"WHERE table_schema='{db.database}' AND table_name='hlstats_Servers'"
            )
            if have and want and have != want:
                charset = want.split("_")[0]
                db.sql("ALTER TABLE hlstats_Servers CONVERT TO CHARACTER SET "
                       f"{charset} COLLATE {want}")
                repairs["collation"] = f"{have} -> {want}"
        return repairs

    @staticmethod
    def ensure_server_row(db, *, address: str, port: int, game: str = "dod",
                          name: str = "KTP Lane B ephemeral",
                          min_players: int = 2) -> int:
        """Insert the hlstats_Servers row and the config that makes bot events
        countable. Returns the serverId.

        Must run before the daemon starts — both the server list and its config
        are read once at startup. Everything here is a prerequisite, not a
        convenience: without the config rows the daemon runs happily and writes
        nothing. See the module docstring for the three defaults involved.
        """
        server_id = db.scalar(
            "SELECT serverId FROM hlstats_Servers "
            f"WHERE address='{address}' AND port={int(port)}"
        )
        if not server_id:
            db.sql(
                "INSERT INTO hlstats_Servers (address, port, name, game) "
                f"VALUES ('{address}', {int(port)}, '{name}', '{game}')"
            )
            server_id = db.scalar(
                "SELECT serverId FROM hlstats_Servers "
                f"WHERE address='{address}' AND port={int(port)}"
            )
        server_id = int(server_id)

        config = {
            # The one that matters: every Lane B player is a bot.
            "IgnoreBots": "0",
            # Default 6. Lower it so a small debug run is not silently ignored.
            "MinPlayers": str(int(min_players)),
            "BonusRoundIgnore": "0",
            # The daemon rcons servers to broadcast. --stdin already sets
            # $g_rcon = 0; these keep it off by configuration too.
            "BroadCastEvents": "0",
            "PlayerEvents": "0",
            # Match preprod migration 009. Even though this server is isolated,
            # the regression must exercise the intended no-connect-announcement
            # configuration rather than silently restoring the old default.
            "ConnectAnnounce": "0",
        }
        for parameter, value in config.items():
            db.sql(
                "DELETE FROM hlstats_Servers_Config "
                f"WHERE serverId={server_id} AND parameter='{parameter}'"
            )
            db.sql(
                "INSERT INTO hlstats_Servers_Config (serverId, parameter, value) "
                f"VALUES ({server_id}, '{parameter}', '{value}')"
            )

        # Not required (the lookup IFNULLs a missing row to realgame 'hl2mp',
        # and no DoD action path branches on it) — inserted for parity with
        # production so the lane is not quietly running a different shape.
        if not db.scalar(f"SELECT code FROM hlstats_Games WHERE code='{game}'"):
            db.sql(
                "INSERT INTO hlstats_Games (code, name, realgame, hidden) "
                f"VALUES ('{game}', 'Day of Defeat', '{game}', '0')"
            )
        return server_id

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
        argv += ["--debug"] * self.debug

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
        f = None
        identity = None
        first_open = True
        short_since = None
        try:
            while not self._stop.is_set():
                if f is None:
                    try:
                        f = self.log_source.open("rb")
                    except FileNotFoundError:
                        time.sleep(0.2)
                        continue
                    # Only the initial attachment skips existing boot noise.
                    # A replacement file belongs to the active/retried server
                    # and must be consumed from its beginning.
                    f.seek(0, os.SEEK_END if first_open else os.SEEK_SET)
                    stat = os.fstat(f.fileno())
                    identity = (stat.st_dev, stat.st_ino)
                    first_open = False

                try:
                    line = f.readline()
                except OSError:
                    # Docker Desktop bind mounts can briefly return ENODATA
                    # while HLDS writes. Retrying the same descriptor avoids
                    # replaying its prefix on a transient mount error.
                    time.sleep(0.2)
                    continue
                if line:
                    self._feed(line.decode("utf-8", "replace").rstrip("\r\n"))
                    continue

                # HLDS opens the configured console log with truncation on a
                # retry/map lifecycle. Following the old file descriptor then
                # loses the whole match while the host path keeps growing.
                # Detect replacement or truncation and follow the path again.
                try:
                    path_stat = self.log_source.stat()
                    replaced = (path_stat.st_dev, path_stat.st_ino) != identity
                    offset = f.tell()
                    truncated = path_stat.st_size < offset
                except OSError:
                    time.sleep(0.2)
                    continue

                if truncated:
                    # Bind-mounted size can briefly lag the readable file.
                    # Require a persistent short file before accepting a real
                    # HLDS truncation; otherwise reopening at zero duplicates
                    # the active match.
                    short_since = short_since or time.monotonic()
                    if time.monotonic() - short_since < 1.0:
                        time.sleep(0.2)
                        continue
                    f.close()
                    f = None
                    identity = None
                    short_since = None
                    continue
                short_since = None

                if replaced:
                    resume = _replacement_resume_offset(
                        f, self.log_source, offset)
                    f.close()
                    try:
                        f = self.log_source.open("rb")
                    except FileNotFoundError:
                        f = None
                        identity = None
                        time.sleep(0.2)
                        continue
                    f.seek(resume)
                    stat = os.fstat(f.fileno())
                    identity = (stat.st_dev, stat.st_ino)
                    continue
                time.sleep(0.2)
        finally:
            if f is not None:
                f.close()

    def _feed(self, line: str) -> None:
        if not line:
            return
        if self.strip_prefix:
            line = strip_log_prefix(line)
        proc = self._proc
        if proc is None or proc.stdin is None:
            return
        if proc.poll() is not None:
            # A dead daemon used to swallow the rest of the log in silence, and
            # the run then reported "0 rows" — indistinguishable from capture
            # never emitting. Record it once so the report can say which.
            if not self._died:
                self._died = (
                    f"hlstats.pl exited (rc={proc.returncode}) after "
                    f"{self._fed} line(s); the remainder of the log was never "
                    f"processed. Tail of {self.stdout_path}:\n"
                    + self._tail_stdout(15)
                )
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

    def stop_pump(self) -> None:
        """Stop tailing the log without stopping the daemon.

        Replay mode pushes lines in with `feed_line`, so the tailing thread has
        nothing to do — and if `log_source` happened to point at the file being
        replayed, it would feed every line a second time. Stopping it makes the
        two modes mutually exclusive by construction rather than by care.
        """
        self._stop.set()
        if self._pump is not None:
            self._pump.join(timeout=5.0)
            self._pump = None

    @property
    def lines_fed(self) -> int:
        with self._lock:
            return self._fed

    @property
    def died_early(self) -> str | None:
        """Set if the daemon exited while lines were still being fed.

        Always check this before believing a zero row count."""
        return self._died

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

    # SQL errors that are artifacts of running an all-bot lane rather than
    # defects. Each entry is (substring, why it is benign) and each one is a
    # claim that has to be justified — an unexplained entry here is a way to
    # make a real failure invisible.
    _BENIGN_SQL = ()

    def classify_sql_errors(self) -> tuple[list[str], list[str]]:
        """Split daemon SQL errors into real failures and known lane artifacts.

        Returns (real, benign). Benign ones are reported as coverage gaps, not
        as passes — the row genuinely did not get written, and pretending
        otherwise would be the same mistake as calling an unexercised scenario
        green. But failing every run on a known, understood, production-safe
        artifact produces a red that means nothing, which is worse.
        """
        real, benign = [], []
        for line in self.sql_errors():
            for needle, why in self._BENIGN_SQL:
                if needle in line:
                    benign.append(f"{line.strip()[:160]}\n      {why}")
                    break
            else:
                real.append(line)
        return real, benign

    def sql_errors(self) -> list[str]:
        """SQL_ERROR / error lines from the daemon's own output.

        The deployment plan's smoke tests all end with a journalctl grep for
        these. Same check, mechanised.
        """
        return [
            ln for ln in self._read_stdout().splitlines()
            if "SQL_ERROR" in ln or "DBD::" in ln
        ]

    def stop(self, *, grace: float = 60.0) -> None:
        """Close stdin and let the daemon finish, only then escalate.

        The grace period is the whole point, and it is not politeness.
        `recordEvent` queues rows and flushes a table only when its queue
        passes `$g_event_queue_size`; everything still queued is written by the
        `flushAll` that runs when the daemon reaches EOF on stdin. Closing
        stdin and immediately SIGTERMing pre-empts that flush.

        The failure mode is worse than losing everything, because it is
        selective: a busy table like `Frags` overflows mid-match and survives,
        while low-volume tables — exactly the ones Lane B exists to check —
        are still sitting in their queues and vanish. The run then shows 39
        frags and 0 assists, which reads precisely like the capture side being
        broken for the new stats only.
        """
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
            try:
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                # It did not act on EOF. Anything still queued is lost, so say
                # so rather than let it look like the events never arrived.
                self._died = (
                    f"hlstats.pl did not exit within {grace:.0f}s of stdin "
                    "closing; it was killed with queued events unflushed, so "
                    "low-volume tables may be short."
                )
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
