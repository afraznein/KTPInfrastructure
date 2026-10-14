"""ktp-data-server-health.sh: the corpus-integrity guard is watched by its log.

The guard posts NOTHING on a clean run, by design -- a standing finding re-posted every
morning trains everyone to mute the channel. That design choice is exactly what makes a
work-done check necessary: with no alert on a good day, "quiet" and "stopped running" are
the same observation from outside.

It is also structurally unwatchable by the mechanism that watches most things here. It is
a `cron.d` job at 06:35, and CRITICAL_TIMERS is checked against `systemctl list-timers`,
which cannot see cron and never could.

The leg is extracted from the shipped script by marker, so renaming or deleting it fails
this file rather than testing a copy that no longer ships.
"""
import os
import pathlib
import re
import shutil
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "ktp-data-server-health.sh"
BASH = os.environ.get("KTP_TEST_BASH", "bash")

pytestmark = pytest.mark.skipif(shutil.which(BASH) is None, reason="needs bash")


def block(name):
    begin, end = "# >>> %s" % name, "# <<< %s" % name
    text = SCRIPT.read_text(encoding="utf-8")
    # BOTH markers, required. Tolerating a missing end marker returns everything to EOF,
    # which then RUNS the rest of the health script -- it does not fail, it does something
    # else entirely, and that is how the first version of this test behaved.
    assert begin in text and end in text, \
        "%s markers are gone from the shipped script" % name
    return text.split(begin, 1)[1].split("\n", 1)[1].split(end, 1)[0]


def shipped_default(var):
    """The default the shipped script uses, not one restated here."""
    text = SCRIPT.read_text(encoding="utf-8")
    m = re.search(r'^%s="\$\{%s:-([^}]+)\}"' % (var, var), text, re.M)
    assert m, "%s default is gone from the shipped script" % var
    return m.group(1)


def run(log_path, age_seconds=None, stale_sec=None):
    """Run the shipped leg against a scratch log and return the tokens it emitted."""
    if age_seconds is not None:
        import time
        when = time.time() - age_seconds
        os.utime(log_path, (when, when))
    script = "down=()\n" + block("ktp-corpus-integrity-guard") + '\nprintf "%s\\n" "${down[@]}"\n'
    # The extracted leg does not carry its own constants, so supply the SHIPPED
    # defaults rather than numbers restated in this file.
    env = dict(os.environ,
               CORPUS_GUARD_LOG=str(log_path),
               CORPUS_GUARD_STALE_SEC=str(stale_sec if stale_sec is not None
                                          else shipped_default("CORPUS_GUARD_STALE_SEC")))
    p = subprocess.run([BASH, "-c", script], capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stderr
    # Without this a broken comparison inside the leg reads as "no tokens", which is how
    # an earlier version of the sibling retention test passed while it could not fire.
    assert p.stderr == "", "the leg wrote to stderr, so a quiet result proves nothing: %s" % p.stderr
    return [t for t in p.stdout.split("\n") if t.strip()]


def test_a_fresh_log_is_quiet(tmp_path):
    """The direction that must stay silent, or the check is noise on every hourly run."""
    log = tmp_path / "ktp-corpus-integrity-guard.log"
    log.write_text("corpus guard: no accrual\n")
    assert run(log, age_seconds=60) == []


def test_a_stale_log_pages(tmp_path):
    """And the direction that must fire -- a check that cannot page proves nothing."""
    log = tmp_path / "ktp-corpus-integrity-guard.log"
    log.write_text("corpus guard: no accrual\n")
    stale = int(shipped_default("CORPUS_GUARD_STALE_SEC"))
    assert run(log, age_seconds=stale + 3600) == ["ktp-corpus-integrity=stale"]


def test_an_absent_log_is_distinguished_from_a_stale_one(tmp_path):
    """'Never ran' and 'stopped running' are different facts and get different tokens."""
    assert run(tmp_path / "does-not-exist.log") == ["ktp-corpus-integrity-log=absent"]


def test_the_token_carries_no_age(tmp_path):
    """The report is a set-diff, so a ticking value would re-page every hourly run."""
    log = tmp_path / "ktp-corpus-integrity-guard.log"
    log.write_text("corpus guard: no accrual\n")
    stale = int(shipped_default("CORPUS_GUARD_STALE_SEC"))
    assert run(log, age_seconds=stale + 3600) == run(log, age_seconds=stale + 7200)


def test_one_missed_daily_run_does_not_page(tmp_path):
    """The guard is daily at 06:35, so the window must tolerate a single miss."""
    assert int(shipped_default("CORPUS_GUARD_STALE_SEC")) > 86400


def test_the_guard_is_not_in_critical_timers():
    """It cannot be: that list is checked against systemctl, which cannot see cron.

    Asserted so nobody 'fixes' the coverage by adding it there, where it would never
    match -- the same mistake the AC retention sweep is guarded against.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    timers = text.split("CRITICAL_TIMERS=(", 1)[1].split("\n)", 1)[0]
    assert "corpus-integrity" not in timers
    assert "ktp-weekly-outliers.timer" in timers      # control: the block was really read
