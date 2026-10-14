"""ktp-data-server-health.sh: the hltv-api drift check is watched by its log.

The wrapper posts NOTHING on a clean run, by design -- a drift report re-posted every
morning trains everyone to mute the channel. That design choice is exactly what makes a
work-done check necessary: with no alert on a good day, "quiet" and "stopped running" are
the same observation from outside.

It is also structurally unwatchable by the mechanism that watches most things here. It is
a `cron.d` job at 06:50, and CRITICAL_TIMERS is checked against `systemctl list-timers`,
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
# ⚠️ A bare `bash` on Windows is WSL's and cannot read a C:\... path; see the sibling
# drift-cron test. Point KTP_TEST_BASH at git-bash there.
BASH = os.environ.get("KTP_TEST_BASH", "bash")

pytestmark = pytest.mark.skipif(shutil.which(BASH) is None, reason="needs bash")


def block(name):
    begin, end = "# >>> %s" % name, "# <<< %s" % name
    text = SCRIPT.read_text(encoding="utf-8")
    # BOTH markers, required. Tolerating a missing end marker returns everything to EOF,
    # which then RUNS the rest of the health script -- it does not fail, it does something
    # else entirely.
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
    script = "down=()\n" + block("ktp-hltv-api-drift") + '\nprintf "%s\\n" "${down[@]}"\n'
    env = dict(os.environ,
               HLTV_DRIFT_LOG=str(log_path),
               HLTV_DRIFT_STALE_SEC=str(stale_sec if stale_sec is not None
                                        else shipped_default("HLTV_DRIFT_STALE_SEC")))
    p = subprocess.run([BASH, "-c", script], capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stderr
    # Without this a broken comparison inside the leg reads as "no tokens", which is how a
    # sibling test once passed while it could not fire at all.
    assert p.stderr == "", "the leg wrote to stderr, so a quiet result proves nothing: %s" % p.stderr
    return [t for t in p.stdout.split("\n") if t.strip()]


def test_a_fresh_log_is_quiet(tmp_path):
    """The direction that must stay silent, or the check is noise on every hourly run."""
    log = tmp_path / "ktp-hltv-api-drift.log"
    log.write_text("hltv-api: no drift\n")
    assert run(log, age_seconds=60) == []


def test_a_stale_log_pages(tmp_path):
    """And the direction that must fire -- a check that cannot page proves nothing."""
    log = tmp_path / "ktp-hltv-api-drift.log"
    log.write_text("hltv-api: no drift\n")
    stale = int(shipped_default("HLTV_DRIFT_STALE_SEC"))
    assert run(log, age_seconds=stale + 3600) == ["ktp-hltv-api-drift=stale"]


def test_an_absent_log_is_distinguished_from_a_stale_one(tmp_path):
    """'Never ran' and 'stopped running' are different facts and get different tokens.

    Absent is the state on the day this is fielded, so it must not read as stale.
    """
    assert run(tmp_path / "does-not-exist.log") == ["ktp-hltv-api-drift-log=absent"]


def test_the_token_carries_no_age(tmp_path):
    """The report is a set-diff, so a ticking value would re-page every hourly run."""
    log = tmp_path / "ktp-hltv-api-drift.log"
    log.write_text("hltv-api: no drift\n")
    stale = int(shipped_default("HLTV_DRIFT_STALE_SEC"))
    assert run(log, age_seconds=stale + 3600) == run(log, age_seconds=stale + 7200)


def test_one_missed_daily_run_does_not_page():
    """The check is daily at 06:50, so the window must tolerate a single miss."""
    assert int(shipped_default("HLTV_DRIFT_STALE_SEC")) > 86400


def test_it_does_not_key_on_the_exit_code_or_the_state_file(tmp_path):
    """A non-zero exit already alerts for itself. What nothing else reports is the run
    that never happened -- and the wrapper writes its state file BEFORE the verdict
    branch, so a state file is not evidence the check completed."""
    # CODE lines only. The leg's comment explains why it does not key on the exit code,
    # so it necessarily contains the word -- and an assert over the whole block fires on
    # its own explanation rather than on a regression.
    leg = block("ktp-hltv-api-drift")
    code = "\n".join(l for l in leg.split("\n")
                     if l.strip() and not l.strip().startswith("#"))
    assert "/last" not in code
    assert "exit" not in code.lower()
    # and the explanation must survive, or the next reader re-adds the coupling
    assert "already alerts for itself" in leg


def test_this_leg_and_the_corpus_leg_stay_distinct(tmp_path):
    """Two legs of the same shape, one script. A copy-paste that left the corpus log in
    place would make this leg report on the wrong file and always read healthy."""
    leg = block("ktp-hltv-api-drift")
    assert "HLTV_DRIFT_LOG" in leg
    assert "CORPUS_GUARD" not in leg
    assert "ktp-hltv-api-drift" in leg and "ktp-corpus-integrity" not in leg
