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
    """Records SQL instead of running it."""

    def __init__(self, existing=None):
        self.statements: list[str] = []
        self._existing = existing

    def scalar(self, query):
        self.statements.append(query)
        return self._existing

    def sql(self, statement):
        self.statements.append(statement)
        return ""


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
    inserts = [s for s in db.statements if s.strip().upper().startswith("INSERT")]
    assert len(inserts) == 1
    assert "hlstats_Servers" in inserts[0]
    assert "127.0.0.1" in inserts[0]
    assert "27015" in inserts[0]
    assert "'dod'" in inserts[0], "game must be dod or the daemon loads the wrong action set"


def test_ensure_server_row_is_idempotent():
    """Re-running the harness must not accumulate duplicate server rows — the
    daemon takes LIMIT 1, so a duplicate silently shadows the other."""
    db = FakeDb(existing="7")
    HlstatsDaemon.ensure_server_row(db, address="127.0.0.1", port=27015)
    assert not [s for s in db.statements if s.strip().upper().startswith("INSERT")]


def test_ensure_server_row_uses_the_port_it_was_given():
    """The ephemeral server binds a random free port, so a hardcoded 27015
    anywhere in this path would mean the daemon never matches the server."""
    db = FakeDb(existing=None)
    HlstatsDaemon.ensure_server_row(db, address="127.0.0.1", port=41234)
    assert "41234" in db.statements[-1]


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
