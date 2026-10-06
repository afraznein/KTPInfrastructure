"""ktp-data-server-health.sh: the weekly precache audit is watched by its report, not its process.

Nothing watched this job at all. Its cron sets `MAILTO=''` and the audit posts to
Discord only on actionable severity, so a green week and an audit that stopped
running produce the identical silence -- and the stop is the one that lets a
fleet-wide asset gap sit until players see missing textures in a match.

The precedent this copies is the renamer's `state.json` mtime leg a few lines
above it in the shipped script, and the reason is the same: `hltv-demo-renamer`
wedged while `systemctl is-active` kept answering `active`, and two days of match
demos were purged unrenamed. A hung process reads as active, so the question has
to be whether work happened.

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

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "ktp-data-server-health.sh"
# CI runs plain bash; on a Windows workstation "bash" resolves to WSL's, which
# cannot see these paths -- point KTP_TEST_BASH at Git Bash there.
BASH = os.environ.get("KTP_TEST_BASH", "bash")
DAY = 86400

pytestmark = pytest.mark.skipif(shutil.which(BASH) is None, reason="needs bash")


def block(name):
    begin, end = "# >>> %s" % name, "# <<< %s" % name
    text = SCRIPT.read_text(encoding="utf-8")
    assert begin in text and end in text, "%s markers are gone from the shipped script" % name
    return text.split(begin, 1)[1].split("\n", 1)[1].split(end, 1)[0]


def shipped_default(var):
    """The default the shipped script actually uses, not one restated here."""
    text = SCRIPT.read_text(encoding="utf-8")
    m = re.search(r'^%s="\$\{%s:-(\d+)\}"' % (var, var), text, re.M)
    assert m, "%s default is gone from the shipped script" % var
    return int(m.group(1))


def verdict(tmp_path, ages, glob=None, max_age=None, names=None):
    """Lay down report fixtures `ages` seconds old, then ask the shipped leg.

    `names` overrides the filenames one for one, so a case can point the glob at
    something that is NOT a report and see whether it still counts.
    """
    now = int(time.time())
    reports = tmp_path / "log"
    reports.mkdir(exist_ok=True)
    for i, age in enumerate(ages):
        name = names[i] if names else "ktp-precache-audit-2026010%d.md" % (i + 1)
        f = reports / name
        f.write_text("# fixture\n", encoding="utf-8")
        os.utime(f, (now - age, now - age))
    body = "set -Eeuo pipefail\n%s\nprecache_freshness '%s' %d %d\n" % (
        block("ktp-precache-freshness"),
        glob if glob else (reports / "ktp-precache-audit-*.md").as_posix(),
        max_age if max_age is not None else shipped_default("PRECACHE_STALE_SEC"),
        now,
    )
    probe = tmp_path / "probe.sh"
    probe.write_text(body, encoding="utf-8", newline="\n")
    r = subprocess.run([BASH, probe.as_posix()], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_a_report_from_this_weeks_run_is_silent(tmp_path):
    assert verdict(tmp_path, [3600]) == ""


def test_a_missed_sunday_is_reported(tmp_path):
    """One skipped run reaches 14d before the next; 9d is already past the ceiling."""
    assert verdict(tmp_path, [9 * DAY]) == "ktp-precache-audit=stale"


def test_a_run_that_merely_started_late_is_not_a_page(tmp_path):
    """The whole point of slack: Sunday 06:00 slipping by hours must stay quiet."""
    assert verdict(tmp_path, [7 * DAY + 6 * 3600]) == ""


def test_no_report_at_all_is_loud_not_silent(tmp_path):
    """A renamed --output path must surface as a false alarm, never as silence."""
    assert verdict(tmp_path, []) == "ktp-precache-audit=no-report"
    assert verdict(tmp_path, [], glob=(tmp_path / "gone" / "*.md").as_posix()) \
        == "ktp-precache-audit=no-report"


def test_the_newest_report_decides_not_the_oldest(tmp_path):
    """Reports accumulate in /var/log; an ancient one must not out-vote this week's."""
    assert verdict(tmp_path, [400 * DAY, 2 * DAY]) == ""
    assert verdict(tmp_path, [2 * DAY, 400 * DAY]) == ""


def test_the_crons_own_log_does_not_certify_the_audit(tmp_path):
    """Negative control 1.

    /var/log/ktp-precache-audit-cron.log is appended to by the cron wrapper even
    when the audit dies before auditing anything, so a glob loose enough to match
    it would report work that never happened. Fresh log, stale report: stale.
    """
    out = verdict(
        tmp_path,
        [9 * DAY, 60],
        names=["ktp-precache-audit-20260101.md", "ktp-precache-audit-cron.log"],
    )
    assert out == "ktp-precache-audit=stale"


def test_a_fresh_report_somewhere_else_does_not_count(tmp_path):
    """Negative control 2.

    Proves the leg read the directory it was given rather than anything ambient:
    the same fresh fixture, found by its own glob, is silent.
    """
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    f = elsewhere / "ktp-precache-audit-20260101.md"
    f.write_text("# fixture\n", encoding="utf-8")
    assert verdict(tmp_path, [], glob=(tmp_path / "log" / "*.md").as_posix()) \
        == "ktp-precache-audit=no-report"
    assert verdict(tmp_path, [60]) == ""


def test_the_ceiling_sits_between_a_late_run_and_a_missed_one(tmp_path):
    """A threshold outside the observed range is a check that cannot fire.

    Read from the shipped script, so widening it past a missed Sunday fails here.
    """
    default = shipped_default("PRECACHE_STALE_SEC")
    assert 7 * DAY < default < 14 * DAY
    assert verdict(tmp_path, [default - 3600]) == ""
    assert verdict(tmp_path, [default + 3600]) == "ktp-precache-audit=stale"


def test_the_token_carries_no_age(tmp_path):
    """The report is a set-diff, so a ticking value would page every hour."""
    first = verdict(tmp_path, [9 * DAY])
    second = verdict(tmp_path, [30 * DAY])
    assert first == second == "ktp-precache-audit=stale"
