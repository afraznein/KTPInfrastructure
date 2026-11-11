"""ktp-data-server-health.sh: the AC migrations-applied check is watched by its stamp.

The check writes its stamp only when it reached a verdict, so the stamp's age catches a
timer that stopped and a run that died before checking. The leg is gated on the timer
being installed, because the units ship uninstalled and an absent stamp must not page
before anyone turned them on.

Extracted from the shipped script by marker, so renaming or deleting the leg fails here.
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
NAME = "ktp-migrations-applied-check"

pytestmark = pytest.mark.skipif(shutil.which(BASH) is None, reason="needs bash")


def block(name):
    begin, end = "# >>> %s" % name, "# <<< %s" % name
    text = SCRIPT.read_text(encoding="utf-8")
    assert begin in text and end in text, "%s markers are gone from the shipped script" % name
    return text.split(begin, 1)[1].split("\n", 1)[1].split(end, 1)[0]


def shipped_default(var):
    text = SCRIPT.read_text(encoding="utf-8")
    m = re.search(r'^%s="\$\{%s:-([^}]+)\}"' % (var, var), text, re.M)
    assert m, "%s default is gone from the shipped script" % var
    return m.group(1)


def run(tmp_path, installed=True, stamp_age=None):
    timer = tmp_path / "ktp-migrations-applied-check.timer"
    if installed:
        timer.write_text("[Timer]\n")
    stamp = tmp_path / "last-checked"
    if stamp_age is not None:
        stamp.write_text("checked=x\ncommit=y\nrc=0\n")
        when = time.time() - stamp_age
        os.utime(stamp, (when, when))
    script = "down=()\n" + block(NAME) + '\nprintf "%s\\n" "${down[@]}"\n'
    env = dict(os.environ,
               MIGRATIONS_CHECK_TIMER_FILE=str(timer),
               MIGRATIONS_CHECK_STAMP=str(stamp),
               MIGRATIONS_CHECK_STALE_SEC=shipped_default("MIGRATIONS_CHECK_STALE_SEC"))
    p = subprocess.run([BASH, "-c", script], capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stderr
    # A broken comparison inside the leg would otherwise read as "no tokens".
    assert p.stderr == "", "the leg wrote to stderr, so a quiet result proves nothing: %s" % p.stderr
    return [t for t in p.stdout.split("\n") if t.strip()]


def test_a_fresh_stamp_is_quiet(tmp_path):
    assert run(tmp_path, stamp_age=60) == []


def test_a_stale_stamp_pages(tmp_path):
    stale = int(shipped_default("MIGRATIONS_CHECK_STALE_SEC"))
    assert run(tmp_path, stamp_age=stale + 3600) == ["ktp-migrations-check=stale"]


def test_an_installed_timer_with_no_stamp_is_absent_not_stale(tmp_path):
    assert run(tmp_path) == ["ktp-migrations-check-stamp=absent"]


def test_nothing_pages_while_the_timer_is_not_installed(tmp_path):
    """The units ship uninstalled; the leg must stay silent until someone installs them."""
    assert run(tmp_path, installed=False) == []
    stale = int(shipped_default("MIGRATIONS_CHECK_STALE_SEC"))
    assert run(tmp_path, installed=False, stamp_age=stale + 3600) == []


def test_the_token_carries_no_age(tmp_path):
    stale = int(shipped_default("MIGRATIONS_CHECK_STALE_SEC"))
    assert run(tmp_path, stamp_age=stale + 3600) == run(tmp_path, stamp_age=stale + 7200)


def test_one_missed_daily_run_does_not_page():
    assert int(shipped_default("MIGRATIONS_CHECK_STALE_SEC")) > 86400


def test_the_timer_is_not_in_critical_timers():
    """That leg pages on a timer that is not active AND enabled, which an uninstalled one never is."""
    text = SCRIPT.read_text(encoding="utf-8")
    timers = text.split("CRITICAL_TIMERS=(", 1)[1].split("\n)", 1)[0]
    assert "migrations-applied" not in timers
    assert "ktp-weekly-outliers.timer" in timers      # control: the block was really read
