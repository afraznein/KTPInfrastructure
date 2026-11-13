"""ktp-data-server-health.sh: a unit's run records are aged, not just written.

`ktp-run-record.sh` gave every wrapped unit a dated file per run, and the runbook
said so plainly: writing a record is not coverage. A unit whose runs stop ending
-- wedged past its timeout and SIGKILLed, or simply no longer run -- left the
records in place and alerted nobody. This leg is the producer the runbook and
OBSERVABILITY_PLAN.md section 2.1 ruled it should be.

The leg is extracted from the shipped script by marker, so renaming or deleting it
fails this file rather than testing a copy that no longer ships.
"""
import os
import pathlib
import re
import shutil
import subprocess
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ktp-data-server-health.sh"
UNITS = ROOT / "scripts" / "systemd"
# CI runs plain bash; on a Windows workstation "bash" resolves to WSL's, which
# cannot see these paths -- point KTP_TEST_BASH at Git Bash there.
BASH = os.environ.get("KTP_TEST_BASH", "bash")
HOUR = 3600
DAY = 86400
# Units that use the wrapper but are aged by a dedicated leg elsewhere in the script.
OWN_LEG = {"ktp-render-banlist", "ktp-migrations-applied-check"}
# Aged units whose unit files live in another repo, so the cadence and timeout checks
# below cannot read them here. Copied from keep-the-prac
# scripts/systemd/ktp-identity-reconcile.{timer,service}; a change there must land here.
FOREIGN = {
    "ktp-identity-reconcile": {"OnCalendar": "Tue 09:00 America/New_York",
                               "TimeoutStartSec": "15min"},
}

pytestmark = pytest.mark.skipif(shutil.which(BASH) is None, reason="needs bash")


def block(name):
    begin, end = "# >>> %s" % name, "# <<< %s" % name
    text = SCRIPT.read_text(encoding="utf-8")
    assert begin in text and end in text, "%s markers are gone from the shipped script" % name
    return text.split(begin, 1)[1].split("\n", 1)[1].split(end, 1)[0]


def rows():
    """unit -> (record ceiling, .part ceiling, subdir, runner), as the shipped script has it."""
    body = block("ktp-run-record-age")
    arr = re.search(r"^RUN_RECORD_UNITS=\((.*?)^\)", body, re.M | re.S)
    assert arr, "RUN_RECORD_UNITS is gone from the shipped leg"
    found = re.findall(r'^\s*"(\S+) (\d+) (\d+)(?: (\S+))?(?: (\S+))?"', arr.group(1), re.M)
    assert found, "RUN_RECORD_UNITS parsed to nothing"
    return {u: (int(a), int(b), d or "runs", x or "ktp-run-record") for u, a, b, d, x in found}


def table():
    """unit -> (record ceiling, .part ceiling)."""
    return {u: r[:2] for u, r in rows().items()}


def wrapped_units():
    out = {}
    for f in sorted(UNITS.glob("*.service")):
        text = f.read_text(encoding="utf-8")
        if re.search(r"^ExecStart=.*ktp-run-record", text, re.M):
            out[f.stem] = text
    return out


def span(value):
    """systemd time span -> seconds, for the forms this repo uses."""
    total = 0
    for n, u in re.findall(r"(\d+)\s*(min|h|s)?", value):
        total += int(n) * {"min": 60, "h": HOUR, "s": 1, "": 1}[u]
    return total


def cadence(unit):
    """Seconds between fires, from the unit's timer. Unknown forms fail loudly."""
    if unit in FOREIGN:
        cal = FOREIGN[unit]["OnCalendar"]
    else:
        text = (UNITS / ("%s.timer" % unit)).read_text(encoding="utf-8")
        m = re.search(r"^OnUnitActiveSec=(\S+)", text, re.M)
        if m:
            return span(m.group(1))
        cal = re.search(r"^OnCalendar=(.+)$", text, re.M).group(1).strip()
    if cal == "hourly" or re.fullmatch(r"\*:\d\d", cal):
        return HOUR
    m = re.fullmatch(r"\*:0/(\d+)", cal)
    if m:
        return int(m.group(1)) * 60
    if re.match(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun) ", cal):
        return 7 * DAY
    if re.match(r"\*-\*-\* \d\d:\d\d:\d\d", cal):
        return DAY
    raise AssertionError("teach this test the timer form %r (%s)" % (cal, unit))


def run(tmp_path, unit="ktp-voice-taunts", records=(), parts=(), unit_age=30 * DAY,
        installed=True, wrapped=True, ceiling=None, part_ceiling=None, exec_line=None,
        subdir=None, symlinks=()):
    """Lay down a unit file and record fixtures `age` seconds old; ask the shipped leg.

    The records subdir and runner pattern are the shipped row's, passed the way the
    sweep's own loop passes them; `subdir` only moves where the fixtures are written.
    """
    now = int(time.time())
    lib, sysd = tmp_path / "lib", tmp_path / "systemd"
    shipped = rows().get(unit, (108000, 1500, "runs", "ktp-run-record"))
    runs = lib / unit / (subdir or shipped[2])
    runs.mkdir(parents=True, exist_ok=True)
    sysd.mkdir(exist_ok=True)
    if installed:
        uf = sysd / ("%s.service" % unit)
        if exec_line is None:
            exec_line = ("ExecStart=/usr/local/bin/ktp-run-record.sh /bin/true" if wrapped
                         else "# ExecStart=/usr/local/bin/ktp-run-record.sh, someday\n"
                              "ExecStart=/bin/true")
        uf.write_text("[Service]\n%s\n" % exec_line, encoding="utf-8", newline="\n")
        os.utime(uf, (now - unit_age, now - unit_age))
    for name, age in list(records) + list(parts):
        f = runs / name
        f.write_text("fixture\n", encoding="utf-8")
        os.utime(f, (now - age, now - age))
    for name, target in symlinks:
        try:
            os.symlink(target, runs / name)
        except (OSError, NotImplementedError):
            pytest.skip("this platform cannot create a symlink fixture")
    body = "set -Eeuo pipefail\nRUN_RECORD_ROOT='%s'\nRUN_RECORD_UNIT_DIR='%s'\n%s\n" \
           "run_record_age %s %d %d %d %s %s\n" % (
               lib.as_posix(), sysd.as_posix(), block("ktp-run-record-age"), unit,
               ceiling if ceiling is not None else shipped[0],
               part_ceiling if part_ceiling is not None else shipped[1], now,
               shipped[2], shipped[3])
    probe = tmp_path / "probe.sh"
    probe.write_text(body, encoding="utf-8", newline="\n")
    r = subprocess.run([BASH, probe.as_posix()], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\t")[0] for line in r.stdout.splitlines() if line.strip()]


# ---- both directions, the pass criterion ----

def test_todays_record_is_silent(tmp_path):
    assert run(tmp_path, records=[("2026-11-12T111357Z.txt", 2 * HOUR)]) == []


def test_a_backdated_record_fires(tmp_path):
    assert run(tmp_path, records=[("2026-11-09T111357Z.txt", 3 * DAY)]) \
        == ["ktp-voice-taunts-run-record=stale"]


def test_the_newest_record_decides(tmp_path):
    """Records accumulate for 400 days; an old one must not out-vote today's."""
    assert run(tmp_path, records=[("a.txt", 300 * DAY), ("b.txt", HOUR)]) == []


def test_last_ok_counts_as_a_record(tmp_path):
    """ONLY_FAILURES units keep nothing but last-ok.txt on a clean run."""
    assert run(tmp_path, unit="ktp-stats-export",
               records=[("last-ok.txt", 600), ("2026-10-01T000000Z.txt", 40 * DAY)]) == []
    assert run(tmp_path / "x", unit="ktp-stats-export", records=[("last-ok.txt", 3 * HOUR)]) \
        == ["ktp-stats-export-run-record=stale"]


# ---- the wedge legs ----

def test_a_latest_run_that_never_finished_fires(tmp_path):
    """SIGKILL or a box going down leaves a .part nothing promoted."""
    out = run(tmp_path, records=[("old.txt", 2 * DAY)], parts=[("new.txt.part", 2 * HOUR)])
    assert out == ["ktp-voice-taunts-run-record=unfinished"], "one fault must be one item"


def test_a_run_in_progress_is_not_a_wedge(tmp_path):
    assert run(tmp_path, records=[("old.txt", 20 * HOUR)], parts=[("now.txt.part", 60)]) == []


def test_an_old_orphan_part_stops_paging_once_a_later_run_ends(tmp_path):
    """The runbook keeps orphan .parts as evidence; they must not page forever."""
    assert run(tmp_path, records=[("later.txt", HOUR)], parts=[("orphan.txt.part", 9 * DAY)]) == []


# ---- gates, and the controls that keep them honest ----

def test_a_unit_not_installed_is_not_a_fault(tmp_path):
    assert run(tmp_path, installed=False) == []


def test_a_comment_naming_the_wrapper_is_not_the_wrapper(tmp_path):
    """Negative control: only an ExecStart= line opts a unit in."""
    assert run(tmp_path, wrapped=False) == []
    assert run(tmp_path / "y", wrapped=True) == ["ktp-voice-taunts-run-record=none"]


def test_a_fresh_install_gets_one_ceiling_before_none(tmp_path):
    assert run(tmp_path, unit_age=HOUR) == []
    assert run(tmp_path / "z", unit_age=3 * DAY) == ["ktp-voice-taunts-run-record=none"]


def test_a_record_in_another_units_dir_does_not_count(tmp_path):
    """Proves the leg read the directory it was asked about, not anything ambient."""
    other = tmp_path / "lib" / "ktp-own-weapon-kills" / "runs"
    other.mkdir(parents=True)
    (other / "fresh.txt").write_text("x\n", encoding="utf-8")
    assert run(tmp_path, unit_age=3 * DAY) == ["ktp-voice-taunts-run-record=none"]


def test_the_token_carries_no_age(tmp_path):
    """The report is a set-diff, so a ticking value would page every hour."""
    a = run(tmp_path, records=[("a.txt", 3 * DAY)])
    b = run(tmp_path / "b", records=[("a.txt", 30 * DAY)])
    assert a == b == ["ktp-voice-taunts-run-record=stale"]


# ---- a unit with a runner of its own: ktp-identity-reconcile ----

RECONCILE = "ktp-identity-reconcile"
RECONCILE_EXEC = "ExecStart=/opt/keep-the-prac/scripts/reconcile-identities-run.sh"


def test_reconcile_is_aged_on_its_own_reports_dir():
    assert rows()[RECONCILE][2:] == ("reports", "reconcile-identities-run")


def test_reconcile_both_directions(tmp_path):
    assert run(tmp_path, unit=RECONCILE, exec_line=RECONCILE_EXEC,
               records=[("2026-11-10T140102Z.txt", 2 * DAY)]) == []
    assert run(tmp_path / "old", unit=RECONCILE, exec_line=RECONCILE_EXEC,
               records=[("2026-11-03T140438Z.txt", 9 * DAY)]) \
        == ["ktp-identity-reconcile-run-record=stale"]


def test_reconcile_unfinished_part_fires(tmp_path):
    out = run(tmp_path, unit=RECONCILE, exec_line=RECONCILE_EXEC,
              records=[("2026-11-03T140438Z.txt", 7 * DAY)],
              parts=[("2026-11-10T140102Z.txt.part", 2 * HOUR)])
    assert out == ["ktp-identity-reconcile-run-record=unfinished"]


def test_reconcile_reads_reports_not_runs(tmp_path):
    """A fresh file in runs/ must not vouch for a unit whose records live in reports/."""
    run(tmp_path, unit=RECONCILE, exec_line=RECONCILE_EXEC, subdir="runs",
        records=[("fresh.txt", HOUR)])
    assert run(tmp_path, unit=RECONCILE, exec_line=RECONCILE_EXEC,
               records=[("old.txt", 9 * DAY)]) == ["ktp-identity-reconcile-run-record=stale"]


def test_reconcile_gate_is_its_own_runner(tmp_path):
    """Negative controls: a mention is not the directive, and the default runner is not it."""
    assert run(tmp_path, unit=RECONCILE, records=[("old.txt", 9 * DAY)],
               exec_line="# " + RECONCILE_EXEC + "\nExecStart=/bin/true") == []
    assert run(tmp_path / "w", unit=RECONCILE, records=[("old.txt", 9 * DAY)],
               exec_line="ExecStart=/usr/local/bin/ktp-run-record.sh /bin/true") == []


def test_a_fresh_latest_symlink_does_not_hide_a_stale_report(tmp_path):
    """The runner keeps reports/latest.txt; the pointer is not a run."""
    out = run(tmp_path, unit=RECONCILE, exec_line=RECONCILE_EXEC,
              records=[("2026-11-03T140438Z.txt", 9 * DAY)],
              symlinks=[("latest.txt", "2026-11-03T140438Z.txt")])
    assert out == ["ktp-identity-reconcile-run-record=stale"]


# ---- the table cannot drift from the units ----

def test_every_wrapped_unit_is_aged_or_has_its_own_leg():
    wrapped, aged = set(wrapped_units()), set(table())
    assert wrapped, "found no wrapped units -- the glob is blind, not the repo empty"
    assert wrapped - aged - OWN_LEG == set(), "wrapped but never aged"
    assert aged - wrapped - set(FOREIGN) == set(), "aged but not wrapped in this repo"
    for unit in FOREIGN:
        assert not (UNITS / ("%s.service" % unit)).exists(), \
            "%s is in this repo now: drop it from FOREIGN and read its unit file" % unit
        assert rows()[unit][2] != "runs", "%s: a foreign runner names its own subdir" % unit
    assert aged & OWN_LEG == set(), "aged twice: one fault would be two items"
    text = SCRIPT.read_text(encoding="utf-8")
    assert "BANLIST_UNIT=" in text and "MIGRATIONS_CHECK_STAMP=" in text, \
        "an exempted unit lost its own leg"


def test_each_ceiling_sits_between_one_late_run_and_two_missed():
    """A ceiling outside the observed range is a check that cannot fire.

    The sweep itself runs hourly, so a sub-hourly unit cannot be judged finer than that.
    """
    for unit, (ceiling, _) in table().items():
        c = cadence(unit)
        assert c < ceiling <= max(3 * c, 2 * HOUR), \
            "%s: ceiling %ds vs cadence %ds" % (unit, ceiling, c)


def test_each_part_ceiling_outlasts_the_timeout_and_the_stop_window():
    units = wrapped_units()
    for unit, (_, part) in table().items():
        if unit in FOREIGN:
            timeout = FOREIGN[unit]["TimeoutStartSec"]
        else:
            m = re.search(r"^TimeoutStartSec=(\S+)", units[unit], re.M)
            assert m, "%s sets no TimeoutStartSec -- a .part could legitimately live forever" % unit
            timeout = m.group(1)
        assert part > span(timeout) + 90, unit
