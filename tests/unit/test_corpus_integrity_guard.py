"""scripts/ktp-corpus-integrity-guard.sh -- the daily accrual check.

The first version of this guard PARSED `mysql --table` output to pull a named metric out
of the two pinned reports. That cannot work: the position file is row-oriented key/value
(the metric name is a VALUE in a name column) while the producer-clock file is
column-oriented per stream. A trial run proved it -- it read `orphan_max_id=9` (the row
NUMBER, while every real cell was NULL), `epoch_zero_rows=58442` against a true 326,429,
and produced the SAME watermark for two different tables.

So the parser is gone and the question is asked directly. What is left to test is the
things that can still be silently wrong: the predicates, the sentinel that stops a
corpus-wide false finding, read-only-ness, and agreement across the four files that have
to name the same log. A mismatch in that last group is the shape where every file is
correct alone and the chain does nothing.
"""
import os
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts" / "ktp-corpus-integrity-guard.sh"
CRON = ROOT / "scripts" / "cron.d" / "ktp-corpus-integrity-guard"
ROTATE = ROOT / "scripts" / "ktp-corpus-integrity-guard.logrotate"
HEALTH = ROOT / "scripts" / "ktp-data-server-health.sh"
BASH = os.environ.get("KTP_TEST_BASH", "bash")

pytestmark = pytest.mark.skipif(shutil.which(BASH) is None, reason="needs bash")
LOG_PATH = "/var/log/ktp-corpus-integrity-guard.log"
TEXT = GUARD.read_text(encoding="utf-8")


def block(name):
    begin, end = "# >>> %s" % name, "# <<< %s" % name
    assert begin in TEXT and end in TEXT, "%s markers are gone" % name
    return TEXT.split(begin, 1)[1].split("\n", 1)[1].split(end, 1)[0]


def test_it_is_syntactically_valid():
    p = subprocess.run([BASH, "-n", str(GUARD)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


def test_the_parser_is_gone_and_must_not_come_back():
    """The regression that matters. It did not fail loudly -- it returned the wrong
    number for the right-looking metric, which is worse than an error."""
    assert "metric_of" not in TEXT
    assert "awk" not in TEXT, "parsing --table output is what produced orphan_max_id=9"


def test_epoch_zero_uses_the_function_not_a_literal():
    """FROM_UNIXTIME(0) renders 1969-12-31 19:00:00 on an ET server. Hardcoding either
    that or a UTC literal is how this breaks on a box with a different clock -- and the
    ledger already warns not to carry a UTC literal into a follow-up query."""
    # Assert on CODE, not prose: the comment deliberately names the literal in order to
    # forbid it, and an earlier version of this test failed on its own explanation.
    pred = block("ktp-corpus-guard-predicates")
    code = "\n".join(ln for ln in pred.split("\n") if not ln.lstrip().startswith("#"))
    assert "FROM_UNIXTIME(0)" in code
    assert "1969-12-31" not in code
    assert "1970-01-01" not in code
    # and the forbidding comment must survive, or the next reader loses the reason
    assert "never hardcode that literal" in pred


def test_the_orphan_predicate_excludes_null_and_empty_match_ids():
    """`rows_match_id_null` is 72,062 on the position corpus and the .sql files flag it
    NOT a defect. Without these guards every one of them would score as an orphan."""
    pred = block("ktp-corpus-guard-predicates")
    assert "match_id IS NOT NULL" in pred
    assert 'match_id <> ""' in pred or "match_id <> ''" in pred


def test_there_is_a_sentinel_for_an_unreadable_ktp_matches():
    """An ungranted or empty ktp_matches turns EVERY row into an orphan. The .sql files
    halt on that rather than report it, and so must this -- a corpus-wide false finding
    is worse than no finding."""
    assert "ktp_matches" in TEXT
    assert "every row would score as an orphan" in TEXT
    # and it must DIE rather than carry on
    sentinel = TEXT.split("matches_rows=", 1)[1].split("log ", 1)[0]
    assert sentinel.count("die ") >= 2, "the sentinel must refuse on both unreadable and 0 rows"


def test_every_stream_entry_names_a_report_file_that_exists():
    streams = block("ktp-corpus-guard-streams")
    entries = re.findall(r'^\s*"([^"]+)"', streams, re.M)
    assert entries, "no stream entries parsed"
    for e in entries:
        parts = e.split(":")
        assert len(parts) == 4, "entry is not <label>:<table>:<idcol>:<report>: %r" % e
        assert (ROOT / "sql" / "integrity" / parts[3]).is_file(), \
            "stream names a missing report: %s" % parts[3]


def test_the_streams_are_the_two_that_have_carried_a_defect():
    streams = block("ktp-corpus-guard-streams")
    assert "ktp_position_samples" in streams
    assert "ktp_flag_state_events" in streams


def test_the_session_is_read_only_on_every_query():
    """Belt to the .sql files' braces: the server refuses a write even if a definition
    gains one later."""
    assert TEXT.count("SET SESSION TRANSACTION READ ONLY") >= 2, \
        "both the scalar helper and the report path must set it"


def test_the_guard_issues_no_writes_of_its_own():
    up = TEXT.upper()
    for kw in ("INSERT INTO", "UPDATE ", "DELETE FROM", "DROP ", "TRUNCATE ", "ALTER TABLE"):
        assert kw not in up, "the guard contains a write keyword: %s" % kw


def test_the_pinned_report_runs_only_on_accrual():
    """A clean day must cost two COUNTs, not a 3-minute unscoped corpus scan. The report
    call has to sit inside the accrual branch."""
    branch = TEXT.split('if [ "$ez" -gt 0 ]', 1)[1].split("printf '%s\\n' \"$new_wm\"", 1)[0]
    assert "$SQL_DIR/$report" in branch, "the pinned report is not inside the accrual branch"


def test_exit_codes_are_distinct_and_documented():
    assert "0 = read, no accrual" in TEXT
    assert "1 = read, accrual found" in TEXT
    assert "2 = could not look" in TEXT


def test_cron_logrotate_and_health_all_name_the_same_log():
    """The silent-break shape: each file correct alone, the chain doing nothing."""
    assert LOG_PATH in CRON.read_text(encoding="utf-8")
    assert LOG_PATH in ROTATE.read_text(encoding="utf-8")
    assert LOG_PATH in HEALTH.read_text(encoding="utf-8")


def test_cron_runs_the_extensionless_installed_name():
    """A cron entry pointing at the .sh name is 203/EXEC, which is exactly how
    ktp-weekly-outliers sat dead for a week."""
    cron = CRON.read_text(encoding="utf-8")
    assert "/usr/local/bin/ktp-corpus-integrity-guard " in cron \
        or "/usr/local/bin/ktp-corpus-integrity-guard\n" in cron
    assert "/usr/local/bin/ktp-corpus-integrity-guard.sh" not in cron


def test_cron_is_daily_and_clear_of_the_freshness_window():
    cron = CRON.read_text(encoding="utf-8")
    m = re.search(r"^(\d+)\s+(\d+)\s+\*\s+\*\s+\*\s+root\s", cron, re.M)
    assert m, "no daily root entry found"
    minute, hour = int(m.group(1)), int(m.group(2))
    assert hour == 6 and minute >= 30, "expected 06:30 or later, got %02d:%02d" % (hour, minute)
