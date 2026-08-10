"""Unit tests for the daemon wrapper's pure logic.

Starting a real hlstats.pl needs perl + DBD::mysql + a live MySQL socket, so
that path belongs to Phase 0 on the runner. What is testable here — and worth
testing, because getting it wrong loses rows silently — is the server-row
prerequisite, the log-prefix handling, and error detection in the daemon's
output.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .hlstats_daemon import HlstatsDaemon, strip_log_prefix


class FakeDb:
    """Records SQL instead of running it.

    `existing` is the serverId a lookup finds — None meaning "no row yet".
    Because `ensure_server_row` re-reads the id after inserting, the fake has
    to model that: a lookup after an INSERT returns an id even when the first
    one did not, or the caller sees None where real MySQL would not.
    """

    database = "hlstatsx_test"

    def __init__(self, existing=None, *, games=None, columns=None):
        self.statements: list[str] = []
        self._existing = existing
        self._inserted_server = False
        self._games = games or []
        self._columns = columns

    def scalar(self, query):
        self.statements.append(query)
        low = query.lower()
        if "information_schema.columns" in low:
            return "rcon_password" if self._columns else None
        if "hlstats_games" in low:
            return self._games[0] if self._games else None
        if "hlstats_servers" in low:
            if self._existing is not None:
                return self._existing
            return "1" if self._inserted_server else None
        return self._existing

    def sql(self, statement):
        self.statements.append(statement)
        if statement.strip().upper().startswith("INSERT INTO HLSTATS_SERVERS "):
            self._inserted_server = True
        return ""

    def inserts_into(self, table: str) -> list[str]:
        return [s for s in self.statements
                if s.strip().upper().startswith("INSERT") and table in s]


def _daemon(tmp_path, **kw):
    """An unstarted daemon — enough to exercise the pure paths."""
    defaults = dict(
        script=tmp_path / "hlstats.pl",
        db_socket=tmp_path / "mysqld.sock",
        db_name="hlstatsx_test",
        db_user="root",
        server_ip="127.0.0.1",
        server_port=27015,
        log_source=tmp_path / "game.log",
        stdout_path=tmp_path / "daemon.out",
    )
    defaults.update(kw)
    return HlstatsDaemon(**defaults)


# -- the server-row prerequisite -------------------------------------------


def test_ensure_server_row_inserts_when_absent():
    """The daemon resolves lines by address+port against hlstats_Servers. No
    row, no attribution — and nothing complains."""
    db = FakeDb(existing=None)
    HlstatsDaemon.ensure_server_row(db, address="127.0.0.1", port=27015)
    inserts = db.inserts_into("hlstats_Servers ")
    assert len(inserts) == 1
    assert "127.0.0.1" in inserts[0]
    assert "27015" in inserts[0]
    assert "'dod'" in inserts[0], "game must be dod or the daemon loads the wrong action set"


def test_ensure_server_row_is_idempotent():
    """Re-running the harness must not accumulate duplicate server rows — the
    daemon takes LIMIT 1, so a duplicate silently shadows the other."""
    db = FakeDb(existing="7")
    HlstatsDaemon.ensure_server_row(db, address="127.0.0.1", port=27015)
    assert not db.inserts_into("hlstats_Servers ")


def test_ensure_server_row_uses_the_port_it_was_given():
    """The ephemeral server binds a random free port, so a hardcoded 27015
    anywhere in this path would mean the daemon never matches the server."""
    db = FakeDb(existing=None)
    HlstatsDaemon.ensure_server_row(db, address="127.0.0.1", port=41234)
    assert any("41234" in s for s in db.inserts_into("hlstats_Servers "))


# -- the config that makes bot events countable ---------------------------


def _config_written(db) -> dict[str, str]:
    """Parameter -> value, read back out of the recorded INSERTs."""
    import re
    out = {}
    for s in db.inserts_into("hlstats_Servers_Config"):
        m = re.search(r"VALUES\s*\(\s*\d+\s*,\s*'([^']+)'\s*,\s*'([^']*)'\s*\)", s)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def test_ignore_bots_is_turned_off():
    """The single biggest trap in the daemon leg. `IgnoreBots` defaults to 1
    (hlstats.pl:2234), every Lane B player is a bot, and the handlers
    short-circuit to `(IGNORED) BOT:` — parse fine, record nothing."""
    db = FakeDb(existing=None)
    HlstatsDaemon.ensure_server_row(db, address="127.0.0.1", port=27015)
    assert _config_written(db)["IgnoreBots"] == "0"


def test_min_players_is_lowered_from_the_default_six():
    """Below `MinPlayers` the handlers answer `(IGNORED) NOTMINPLAYERS:`, which
    is indistinguishable from broken capture in a small debug run."""
    db = FakeDb(existing=None)
    HlstatsDaemon.ensure_server_row(db, address="127.0.0.1", port=27015,
                                    min_players=2)
    assert _config_written(db)["MinPlayers"] == "2"


def test_server_config_is_replaced_not_appended():
    """hlstats_Servers_Config has no unique key on (serverId, parameter), and
    the daemon reads rows into a hash — a stale duplicate would win or lose by
    row order. Each parameter is deleted before it is inserted."""
    db = FakeDb(existing="7")
    HlstatsDaemon.ensure_server_row(db, address="127.0.0.1", port=27015)
    deletes = [s for s in db.statements
               if s.strip().upper().startswith("DELETE")
               and "hlstats_Servers_Config" in s]
    assert len(deletes) == len(_config_written(db))


# -- reconstruction repairs -----------------------------------------------


def test_missing_rcon_password_column_is_added():
    """`fetch_base_schema.sh` reconstructs hlstats_Servers from
    information_schema, and MySQL hides columns the account cannot see. The
    daemon SELECTs a.rcon_password at its first server lookup and dies."""
    db = FakeDb(columns=None)
    repairs = HlstatsDaemon.repair_reconstructed_schema(db)
    assert repairs["columns"] == ["rcon_password"]
    assert any("ADD COLUMN `rcon_password`" in s for s in db.statements)


def test_present_column_is_left_alone():
    """MySQL has no ADD COLUMN IF NOT EXISTS, so a blind ALTER would error out
    on a dump that already has it."""
    db = FakeDb(columns=["rcon_password"])
    repairs = HlstatsDaemon.repair_reconstructed_schema(db)
    assert repairs["columns"] == []
    assert not [s for s in db.statements if "ADD COLUMN" in s]


# -- log-line prefix handling ---------------------------------------------


@pytest.mark.parametrize("line,expected", [
    ('L 08/09/2026 - 12:00:00: "A<1><STEAM_1:0:1><Allies>" killed "B<2><STEAM_1:0:2><Axis>"',
     '"A<1><STEAM_1:0:1><Allies>" killed "B<2><STEAM_1:0:2><Axis>"'),
    ('L 08/09/2026 - 12:00:00: "A<1><STEAM_1:0:1><Allies>" triggered "cap_break" (flag "dod_anzio_flag_2")',
     '"A<1><STEAM_1:0:1><Allies>" triggered "cap_break" (flag "dod_anzio_flag_2")'),
])
def test_strip_prefix_removes_the_engine_timestamp(line, expected):
    assert strip_log_prefix(line) == expected


def test_strip_prefix_off_by_default(tmp_path):
    """Default is to feed lines exactly as the engine wrote them — that is what
    a UDP forward would have delivered, and the daemon's own prefix handling is
    unverified (a Phase 0 question)."""
    d = _daemon(tmp_path)
    assert d.strip_prefix is False
    assert d.timestamp_flag is False


def test_a_line_without_the_prefix_survives_stripping():
    """Defensive: a line that does not match the prefix shape must pass through
    untouched rather than lose its first colon-delimited field. The STEAM_ id
    itself is full of colons, so a naive split would corrupt every line."""
    line = '"A<1><STEAM_1:0:1><Allies>" killed "B<2><STEAM_1:0:2><Axis>"'
    assert strip_log_prefix(line) == line


# -- error surfacing -------------------------------------------------------


def test_sql_errors_surfaces_daemon_failures(tmp_path):
    """Every smoke test in the deployment plan ends with a journalctl grep for
    SQL errors. Same check, mechanised."""
    out = tmp_path / "daemon.out"
    out.write_text(
        "E: UDP listen socket disabled, reading log data from STDIN.\n"
        "SQL_ERROR: Duplicate entry 'assist' for key 'code'\n"
        "DBD::mysql::st execute failed: Unknown column 'pos_x'\n"
        "I: something harmless\n"
    )
    d = _daemon(tmp_path, stdout_path=out)
    errs = d.sql_errors()
    assert len(errs) == 2
    assert any("SQL_ERROR" in e for e in errs)
    assert any("DBD::" in e for e in errs)


def test_sql_errors_empty_on_a_clean_run(tmp_path):
    out = tmp_path / "daemon.out"
    out.write_text("E: reading log data from STDIN.\nI: match_id 42 tagged\n")
    assert _daemon(tmp_path, stdout_path=out).sql_errors() == []


def test_sql_errors_tolerates_a_missing_stdout_file(tmp_path):
    """Called during teardown after a failed start, when the file may not
    exist. Must not raise and mask the original failure."""
    assert _daemon(tmp_path, stdout_path=tmp_path / "nope.out").sql_errors() == []


def test_start_rejects_a_missing_script(tmp_path):
    d = _daemon(tmp_path, script=tmp_path / "absent.pl")
    with pytest.raises(Exception, match="hlstats.pl not found"):
        d.start()


def test_drain_returns_immediately_when_nothing_is_feeding(tmp_path):
    """drain() must terminate on a quiet log rather than block for the whole
    timeout — a nightly lane that hangs is worse than one that fails."""
    d = _daemon(tmp_path)
    got = d.drain(quiet_for=0.5, timeout=10.0)
    assert got == 0
