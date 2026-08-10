"""Ephemeral MySQL for the stats-capture e2e lane — a second mysqld, not a container.

The operator asked for "ephemeral MySQL per run". The obvious implementation is
a Docker container, but the Tier 2 runner is deliberately Docker-free
(TEST_INFRASTRUCTURE_PLAN: "Tier 2 LIVE — Docker-free runner on the data
server"), and that box also runs production HLStatsX. Adding a container
runtime to it is a real infrastructure change, not a test detail.

Same intent, Docker-free: start a **second mysqld** with its own datadir,
socket and high port under the run's temp directory. It needs no root, cannot
see the production schema, is initialised empty every run, and is deleted on
teardown. It also proves the migration SQL applies to an empty database, which
a long-lived test schema quietly stops testing after the first run.

## Ordering matters and is enforced here

`doEvent_PlayerAction` only records an action that exists in
`hlstats_Actions`, and the daemon reads that table into memory **at startup**.
Seed after the daemon boots and every emitted line is silently discarded —
the exact failure that lost every objective capture at the Philly LAN.

`prepare()` therefore loads schema + migrations + seeds and returns; the daemon
is started afterwards by the caller. The dependency is expressed as fixture
order rather than as a note someone has to remember.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


# Sentinel distinguishing "caller said nothing, use self.database" from
# "caller explicitly wants no schema selected".
_DEFAULT_DB = object()


class MysqlUnavailable(RuntimeError):
    """No usable mysqld, or it refused to start. An error, never a skip —
    a stats lane that silently runs without a database asserts nothing."""


def _free_tcp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _is_root() -> bool:
    """True when running as uid 0 — the normal case inside the Lane B image."""
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _which(*names: str) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    # mysqld is commonly in sbin, which is off a non-root user's PATH.
    for d in ("/usr/sbin", "/usr/local/sbin", "/usr/libexec"):
        for n in names:
            cand = Path(d) / n
            if cand.is_file() and os.access(cand, os.X_OK):
                return str(cand)
    return None


@dataclass
class EphemeralMysql:
    """A private mysqld instance. Connect over its unix socket."""

    base_dir: Path
    datadir: Path
    socket_path: Path
    port: int
    database: str
    user: str
    mysqld: str
    client: str
    _proc: subprocess.Popen | None = None
    _keep: bool = False

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def start(
        cls,
        *,
        database: str = "hlstatsx_test",
        parent: Path | None = None,
        keep: bool = False,
        boot_timeout: float = 90.0,
    ) -> "EphemeralMysql":
        mysqld = _which("mysqld", "mariadbd")
        client = _which("mysql", "mariadb")
        if not mysqld:
            raise MysqlUnavailable(
                "no mysqld/mariadbd binary found. This lane needs the server "
                "binary, not just the client — check /usr/sbin."
            )
        if not client:
            raise MysqlUnavailable("no mysql/mariadb client binary found")

        base = Path(tempfile.mkdtemp(prefix="ktp-e2e-mysql-", dir=str(parent) if parent else None))
        datadir = base / "data"
        sock = base / "mysqld.sock"
        port = _free_tcp_port()

        inst = cls(
            base_dir=base,
            datadir=datadir,
            socket_path=sock,
            port=port,
            database=database,
            user=os.environ.get("USER") or "root",
            mysqld=mysqld,
            client=client,
            _keep=keep,
        )
        inst._initialise()
        inst._spawn(boot_timeout=boot_timeout)
        inst._create_database()
        return inst

    def _initialise(self) -> None:
        """Create an empty datadir. MySQL and MariaDB disagree on how."""
        self.datadir.mkdir(parents=True, exist_ok=True)
        # Both initialisers refuse to run as uid 0 without --user, same as the
        # server itself.
        as_root = ["--user=root"] if _is_root() else []
        attempts = [
            # MySQL 5.7+/8.x. --no-defaults FIRST, same as the server launch and
            # for a sharper reason here: Ubuntu's /etc/mysql/mysql.conf.d/
            # mysqld.cnf sets `user = mysql`, so without it the initialiser
            # drops privileges to the mysql user and then cannot read a
            # root-owned 0700 datadir. That surfaces as
            #   [ERROR] [MY-013276] Failed to set datadir ... (OS errno: 13)
            # which reads as a filesystem permissions problem rather than as
            # "it read a config file we did not want it to read".
            [self.mysqld, "--no-defaults", f"--datadir={self.datadir}",
             "--initialize-insecure", "--basedir=/usr",
             "--log-error-verbosity=1", *as_root],
        ]
        install_db = _which("mariadb-install-db", "mysql_install_db")
        if install_db:
            # MariaDB — the Lane B image's database. Try the explicit
            # auth-method form first; older packages don't accept the flag.
            attempts.append([install_db, f"--datadir={self.datadir}",
                             "--auth-root-authentication-method=normal", *as_root])
            attempts.append([install_db, f"--datadir={self.datadir}", *as_root])

        errors = []
        for argv in attempts:
            proc = subprocess.run(argv, capture_output=True, text=True)
            if proc.returncode == 0 and any(self.datadir.iterdir()):
                return
            errors.append(f"$ {' '.join(argv)}\n{proc.stderr.strip()[-800:]}")
        raise MysqlUnavailable(
            "could not initialise an empty datadir:\n\n" + "\n\n".join(errors)
        )

    def _spawn(self, *, boot_timeout: float) -> None:
        log = self.base_dir / "mysqld.err"
        argv = [
            self.mysqld,
            # MUST BE FIRST. --no-defaults is a "pre-option": the option parser
            # consumes it before anything else, and anywhere later in argv
            # MariaDB aborts with `unknown option '--no-defaults'` *after* a
            # full InnoDB startup, so it reads as a mysterious late crash.
            #
            # It is load-bearing rather than hygiene: without it the server
            # reads /etc/mysql/* and ~/.my.cnf, and on the data server
            # ~/.my.cnf is configured to reach the LIVE database.
            "--no-defaults",
            f"--datadir={self.datadir}",
            f"--socket={self.socket_path}",
            f"--port={self.port}",
            f"--pid-file={self.base_dir / 'mysqld.pid'}",
            f"--log-error={log}",
            # Bind loopback only. This box runs production MySQL; a private
            # instance must not be reachable from anywhere else.
            "--bind-address=127.0.0.1",
            "--skip-name-resolve",
            "--skip-grant-tables",
        ]
        # mysqld/mariadbd refuse to start as uid 0 unless told to. Containers
        # run as root by default, so without this the whole Lane B image path
        # dies at "Please consult the Knowledge Base ... running as root".
        if _is_root():
            argv.append("--user=root")
        self._proc = subprocess.Popen(
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + boot_timeout
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise MysqlUnavailable(
                    f"mysqld exited during startup (rc={self._proc.returncode}); "
                    f"see {log}"
                )
            if self.socket_path.exists() and self._ping():
                return
            time.sleep(0.5)
        self.stop()
        raise MysqlUnavailable(
            f"mysqld did not come up within {boot_timeout:.0f}s; see {log}"
        )

    def _ping(self) -> bool:
        try:
            r = subprocess.run(
                [self.client, "--no-defaults", f"--socket={self.socket_path}",
                 "-u", "root", "-e", "SELECT 1"],
                capture_output=True, text=True, timeout=5,
            )
            return r.returncode == 0
        except Exception:
            return False

    def _create_database(self) -> None:
        self.sql(f"CREATE DATABASE IF NOT EXISTS `{self.database}` "
                 "DEFAULT CHARACTER SET utf8mb4", database=None)

    # -- querying ----------------------------------------------------------

    def sql(self, statement: str, *, database: str | None = _DEFAULT_DB) -> str:
        """Run one statement. Raises on non-zero exit with stderr attached.

        `database=None` connects WITHOUT selecting a schema. That distinction
        matters: `CREATE DATABASE hlstatsx_test` cannot run with
        `hlstatsx_test` already selected, and the client fails first with
        `ERROR 1049 Unknown database` before the statement is ever sent.
        """
        argv = [self.client, "--no-defaults", f"--socket={self.socket_path}",
                "-u", "root", "--batch", "--raw"]
        target = self.database if database is _DEFAULT_DB else database
        if target:
            argv += [target]
        argv += ["-e", statement]
        r = subprocess.run(argv, capture_output=True, text=True)
        if r.returncode != 0:
            raise MysqlUnavailable(
                f"SQL failed: {statement.splitlines()[0][:120]}\n{r.stderr.strip()[-1200:]}"
            )
        return r.stdout

    def load_file(self, path: Path) -> None:
        """Apply a .sql file. Used for the HLStatsX schema, then each
        migration, then the action seeds — in that order."""
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"SQL file not found: {path}")
        argv = [self.client, "--no-defaults", f"--socket={self.socket_path}",
                "-u", "root", self.database]
        with path.open("rb") as f:
            r = subprocess.run(argv, stdin=f, capture_output=True, text=True)
        if r.returncode != 0:
            raise MysqlUnavailable(
                f"failed applying {path.name}:\n{r.stderr.strip()[-1500:]}"
            )

    def scalar(self, query: str) -> str | None:
        """First column of the first row, or None for an empty result."""
        out = self.sql(query).strip().splitlines()
        if len(out) < 2:
            return None
        return out[1].split("\t")[0]

    def count(self, query: str) -> int:
        v = self.scalar(query)
        return int(v) if v is not None else 0

    # -- schema prep -------------------------------------------------------

    def prepare(self, *, schema_files: list[Path], seed_files: list[Path]) -> None:
        """Load base schema, then migrations, then action seed rows.

        MUST complete before the hlstats.pl daemon starts — it caches
        hlstats_Actions in memory at startup, so a row inserted afterwards is
        not live and every matching log line is discarded without an error.
        """
        for f in schema_files:
            self.load_file(f)
        for f in seed_files:
            self.load_file(f)

    def assert_action_seeded(self, code: str, *, for_pa: str, for_ppa: str) -> None:
        """Verify a seed row landed with the flags the right way round.

        The two new actions want OPPOSITE flags — assists are
        PlayerPlayerActions, breaks are PlayerActions. Setting both makes the
        dispatcher record the event twice and double-apply the reward, which
        is a silent rating corruption rather than a visible error, so it is
        worth asserting rather than trusting.
        """
        out = self.sql(
            "SELECT for_PlayerActions, for_PlayerPlayerActions, reward_player "
            f"FROM hlstats_Actions WHERE game='dod' AND code='{code}'"
        ).strip().splitlines()
        if len(out) < 2:
            raise AssertionError(
                f"no hlstats_Actions row for dod/{code} — the daemon would "
                "discard every emitted line for it, with no error"
            )
        if len(out) > 2:
            raise AssertionError(f"{len(out) - 1} rows for dod/{code}, expected exactly 1")
        pa, ppa, reward = out[1].split("\t")[:3]
        if (pa, ppa) != (for_pa, for_ppa):
            raise AssertionError(
                f"dod/{code} flags are for_PlayerActions={pa} "
                f"for_PlayerPlayerActions={ppa}, expected {for_pa}/{for_ppa} — "
                "wrong way round means double-recorded events"
            )
        if reward not in ("0", "0.00"):
            raise AssertionError(
                f"dod/{code} has reward_player={reward}, expected 0 — a non-zero "
                "reward re-rates the whole ladder as a side effect of adding a stat"
            )

    # -- teardown ----------------------------------------------------------

    def stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=5)
        self._proc = None

    def cleanup(self) -> None:
        self.stop()
        if not self._keep:
            shutil.rmtree(self.base_dir, ignore_errors=True)

    def __enter__(self) -> "EphemeralMysql":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.cleanup()
