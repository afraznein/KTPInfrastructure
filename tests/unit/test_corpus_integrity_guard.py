"""scripts/ktp-corpus-integrity-guard.sh -- the wrapper around two pinned SQL definitions.

The wrapper issues no SELECT of its own, so there is little logic to test except the one
bespoke part: `metric_of`, which pulls a named column out of mysql's --table output. That
parser is the whole trust boundary. If it silently returns the wrong cell the guard writes
a wrong watermark, and a wrong watermark makes every later run scope from the wrong place.

The rest of this file tests AGREEMENT ACROSS FILES -- guard, cron, logrotate and the health
check must name the same log path, and the stream table must name SQL files that exist. A
mismatch there is the silent-break shape this estate keeps hitting: each file is correct on
its own and the chain does nothing.
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

# A realistic slice of `mysql --table` output: a header row, a separator, a value row.
TABLE = """\
+------------+--------------+-----------------+
| rows_total | rows_max_id  | epoch_zero_rows |
+------------+--------------+-----------------+
|    6556003 |      6556415 |          326429 |
+------------+--------------+-----------------+
"""

REORDERED = """\
+-----------------+-------------+------------+
| epoch_zero_rows | rows_max_id | rows_total |
+-----------------+-------------+------------+
|               0 |     6700001 |    6700001 |
+-----------------+-------------+------------+
"""


def block(name):
    text = GUARD.read_text(encoding="utf-8")
    begin, end = "# >>> %s" % name, "# <<< %s" % name
    assert begin in text and end in text, "%s markers are gone from the shipped script" % name
    return text.split(begin, 1)[1].split("\n", 1)[1].split(end, 1)[0]


def metric_of(table_text, name):
    """Run the shipped parser, not a reimplementation of it."""
    script = block("ktp-corpus-guard-metric") + '\nmetric_of "$1" "$2"\n'
    p = subprocess.run([BASH, "-c", script, "_", table_text, name],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert p.stderr == "", "the parser wrote to stderr: %s" % p.stderr
    return p.stdout.strip()


def test_it_reads_the_named_column():
    assert metric_of(TABLE, "rows_max_id") == "6556415"


def test_it_does_not_confuse_neighbouring_columns():
    """The failure that matters: returning the cell next door writes a wrong watermark."""
    assert metric_of(TABLE, "rows_total") == "6556003"
    assert metric_of(TABLE, "epoch_zero_rows") == "326429"


def test_column_order_does_not_matter():
    """The .sql files may reorder sections; the parser keys on the NAME, not a position."""
    assert metric_of(REORDERED, "rows_max_id") == "6700001"
    assert metric_of(REORDERED, "epoch_zero_rows") == "0"


def test_a_zero_is_returned_rather_than_treated_as_missing():
    """0 is the GOOD answer for a defect metric, so it must not read as absent."""
    assert metric_of(REORDERED, "epoch_zero_rows") == "0"


def test_an_absent_metric_returns_EMPTY_so_the_guard_can_refuse():
    """Empty is what the guard turns into exit 2. If this returned 0 instead, a renamed
    column would read as 'no defects' -- the single worst outcome available here."""
    assert metric_of(TABLE, "a_column_that_does_not_exist") == ""


def test_the_stream_table_names_sql_files_that_exist():
    """A typo here is silent: the guard dies 2, but only once it is scheduled on a box."""
    streams = block("ktp-corpus-guard-streams")
    files = re.findall(r"^\s*\"[a-z_]+:([a-z_]+\.sql):", streams, re.M)
    assert files, "no stream entries parsed -- the table shape changed"
    for f in files:
        assert (ROOT / "sql" / "integrity" / f).is_file(), "stream names a missing SQL file: %s" % f


def test_every_stream_entry_has_all_four_fields():
    streams = block("ktp-corpus-guard-streams")
    entries = re.findall(r'^\s*"([^"]+)"', streams, re.M)
    assert entries, "no stream entries parsed"
    for e in entries:
        assert len(e.split(":")) == 4, "entry is not <label>:<file>:<watermark>:<defects>: %r" % e


def test_the_guard_opens_the_session_read_only():
    """Both .sql files are pure SELECT, and this is the belt to that braces: the server
    refuses a write even if one is added to a definition later."""
    assert "SET SESSION TRANSACTION READ ONLY" in GUARD.read_text(encoding="utf-8")


def test_the_guard_issues_no_writes_of_its_own():
    text = GUARD.read_text(encoding="utf-8").upper()
    for kw in ("INSERT INTO", "UPDATE ", "DELETE FROM", "DROP ", "TRUNCATE ", "ALTER "):
        assert kw not in text, "the wrapper contains a write keyword: %s" % kw


def test_cron_logrotate_and_health_all_name_the_same_log():
    """The silent-break shape: each file correct alone, the chain doing nothing."""
    assert LOG_PATH in CRON.read_text(encoding="utf-8")
    assert LOG_PATH in ROTATE.read_text(encoding="utf-8")
    assert LOG_PATH in HEALTH.read_text(encoding="utf-8")


def test_cron_runs_the_extensionless_installed_name():
    """Installed as /usr/local/bin/ktp-corpus-integrity-guard, as the review guard is --
    a cron entry pointing at the .sh name would be 203/EXEC, which is precisely how
    ktp-weekly-outliers sat dead for a week."""
    cron = CRON.read_text(encoding="utf-8")
    assert "/usr/local/bin/ktp-corpus-integrity-guard " in cron \
        or "/usr/local/bin/ktp-corpus-integrity-guard\n" in cron
    assert "/usr/local/bin/ktp-corpus-integrity-guard.sh" not in cron


def test_cron_is_daily_and_clear_of_the_freshness_window():
    """06:20 + up to 5 min jitter belongs to install-freshness; two readers scanning the
    position corpus at once is the thing the schedule comment is avoiding."""
    cron = CRON.read_text(encoding="utf-8")
    m = re.search(r"^(\d+)\s+(\d+)\s+\*\s+\*\s+\*\s+root\s", cron, re.M)
    assert m, "no daily root entry found"
    minute, hour = int(m.group(1)), int(m.group(2))
    assert hour == 6 and minute >= 30, "expected 06:30 or later, got %02d:%02d" % (hour, minute)
