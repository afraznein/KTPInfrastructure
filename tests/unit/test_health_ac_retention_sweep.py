"""ktp-data-server-health.sh: the AC retention sweep is watched by its log, not by a timer.

The sweep enforces the ruled 105-day token window. Nothing watched it at all, and it is
structurally unwatchable by the mechanism that watches everything else here: it is a
`cron.d` job, so `CRITICAL_TIMERS` -- which is checked against `systemctl list-timers` --
cannot see it and never could. Measured 2026-10-13, the deployed health script named
`ac-retention` exactly once, in a comment, with no check behind it.

A stopped sweep is silent in the worst way: nothing gets deleted, and the absence of a
delete looks exactly like a quiet night. So the question has to be whether work happened,
which is the same reasoning as the renamer's `state.json` leg -- `hltv-demo-renamer` wedged
while `systemctl is-active` kept answering `active` and two days of demos were purged
unrenamed.

The leg is extracted from the shipped script by marker, so renaming or deleting it fails
this file rather than testing a copy that no longer ships.
"""
import os
import pathlib
import re
import shutil
import subprocess
import time

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "ktp-data-server-health.sh"
BASH = os.environ.get("KTP_TEST_BASH", "bash")

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


def run(log_path, age_seconds=None, stale_sec=None):
    """Run the shipped leg against a scratch log and return the tokens it emitted."""
    if age_seconds is not None:
        when = time.time() - age_seconds
        os.utime(log_path, (when, when))
    script = "down=()\n" + block("ktp-ac-retention-sweep") + '\nprintf "%s\\n" "${down[@]}"\n'
    # The extracted leg does not carry its own constant, so supply the SHIPPED default
    # rather than a number restated here.
    env = dict(os.environ, AC_RETENTION_LOG=str(log_path),
               AC_RETENTION_STALE_SEC=str(stale_sec if stale_sec is not None
                                          else shipped_default("AC_RETENTION_STALE_SEC")))
    p = subprocess.run([BASH, "-c", script], capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stderr
    # Without this, a broken comparison inside the leg reads as "no tokens" -- which is
    # exactly how the first cut of this test passed while the check could not fire at all.
    assert p.stderr == "", "the leg wrote to stderr, so a quiet result proves nothing: %s" % p.stderr
    return [t for t in p.stdout.split("\n") if t.strip()]


def test_a_fresh_log_is_quiet(tmp_path):
    """The direction that must stay silent, or the check is noise on every hourly run."""
    log = tmp_path / "ktp-ac-retention.log"
    log.write_text("ac-retention: done\n")
    assert run(log, age_seconds=60) == []


def test_a_stale_log_pages(tmp_path):
    """And the direction that must fire -- a check that cannot page proves nothing."""
    log = tmp_path / "ktp-ac-retention.log"
    log.write_text("ac-retention: done\n")
    assert run(log, age_seconds=shipped_default("AC_RETENTION_STALE_SEC") + 3600) == \
        ["ktp-ac-retention=stale"]


def test_an_absent_log_is_distinguished_from_a_stale_one(tmp_path):
    """'Never ran' and 'stopped running' are different facts and get different tokens."""
    assert run(tmp_path / "does-not-exist.log") == ["ktp-ac-retention-log=absent"]


def test_the_token_carries_no_age(tmp_path):
    """The report is a set-diff, so a ticking value would read as a fresh failure hourly."""
    log = tmp_path / "ktp-ac-retention.log"
    log.write_text("ac-retention: done\n")
    stale = shipped_default("AC_RETENTION_STALE_SEC")
    first = run(log, age_seconds=stale + 3600)
    second = run(log, age_seconds=stale + 7200)
    assert first == second, "the token moved with the age; a set-diff would re-page every run"


def test_one_missed_daily_run_does_not_page(tmp_path):
    """The sweep is daily at 04:40, so the window must tolerate a single miss."""
    assert shipped_default("AC_RETENTION_STALE_SEC") > 86400


def test_the_install_freshness_timer_is_covered():
    """The other half of this change, and nothing guarded it until a mutation test looked.

    Deleting the entry passed the whole health suite silently, which is the same shape as the
    gap being closed: a stopped freshness timer and a clean estate both produce no output, so
    the only thing that can notice is an assertion naming it.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    timers = text.split("CRITICAL_TIMERS=(", 1)[1].split("\n)", 1)[0]
    assert "ktp-install-freshness.timer" in timers
    assert "ktp-weekly-outliers.timer" in timers      # control: the block was really read


def test_the_cron_job_is_not_in_critical_timers():
    """It cannot be: that list is checked against systemctl, which cannot see a cron job.

    Asserted so nobody 'fixes' the gap by adding it there, where it would never match.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    timers = text.split("CRITICAL_TIMERS=(", 1)[1].split("\n)", 1)[0]
    assert "ktp-ac-retention" not in timers
    assert "ktp-weekly-outliers.timer" in timers      # control: the block was really read
