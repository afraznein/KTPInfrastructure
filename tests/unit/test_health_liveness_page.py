"""ktp-data-server-health.sh: a lost HLTV page is found by its latch, not by a failed unit.

`ktp-hltv-liveness.sh` exits 4 when it detected a fault and could not deliver the
page, and that exit is deliberately outside the unit's `SuccessExitStatus`. But the
check runs every 5 minutes and the next run that exits 0, 1 or 2 clears the failed
state, while the only sweep that reads `systemctl --failed` is this hourly cron at
:17. So the exit is a ~5-in-60 sample of the common case -- one refused POST, which
is exactly what the check's `--fail` was added to catch.

The check therefore latches the epoch of the lost send into its state file and does
not clear it on a later success. This leg reads that. It is the same reasoning as
the renamer's `state.json` mtime leg: alert on work done, never on process state.

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


WINDOW = shipped_default("LIVENESS_SEND_FAIL_SEC")


def verdict(tmp_path, state_body, window=None, absent=False):
    """Ask the shipped leg what it makes of a liveness state file."""
    state = tmp_path / "liveness-state"
    if not absent:
        state.write_text(state_body, encoding="utf-8", newline="\n")
    body = (
        "set -Eeuo pipefail\n"
        "down=()\n"
        'LIVENESS_STATE_FILE="%s"\n'
        "LIVENESS_SEND_FAIL_SEC=%d\n"
        "%s\n"
        'printf "%%s\\n" "${down[@]:-}"\n'
    ) % (state.as_posix(), WINDOW if window is None else window, block("ktp-hltv-liveness-page"))
    probe = tmp_path / "probe.sh"
    probe.write_text(body, encoding="utf-8", newline="\n")
    r = subprocess.run([BASH, probe.as_posix()], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def state(send_fail_age=None, fails=0, last_alert=0, field=True):
    now = int(time.time())
    lines = ["FAILS=%d" % fails, "LAST_ALERT=%d" % last_alert]
    if field:
        lines.append("LAST_SEND_FAIL=%d" % (0 if send_fail_age is None else now - send_fail_age))
    return "\n".join(lines) + "\n"


# -- it fires ----------------------------------------------------------------

def test_a_page_lost_an_hour_ago_is_reported(tmp_path):
    """The case the failed unit misses: one refused POST, cleared from
    `systemctl --failed` 5 minutes later, sampled here an hour afterwards."""
    assert verdict(tmp_path, state(send_fail_age=3600)) == "hltv-liveness-page=undelivered"


def test_a_page_lost_just_now_is_reported(tmp_path):
    assert verdict(tmp_path, state(send_fail_age=1)) == "hltv-liveness-page=undelivered"


def test_the_window_outlives_the_sweeps_own_cadence(tmp_path):
    """The whole point of the latch. The cron is hourly, so a window at or under
    an hour could still be missed entirely -- that would be the 8% surface again
    with extra steps."""
    assert WINDOW > 3600, "the window no longer guarantees an hourly sample"
    assert verdict(tmp_path, state(send_fail_age=WINDOW - 600)) == "hltv-liveness-page=undelivered"


# -- it does not fire --------------------------------------------------------

def test_a_clean_check_is_silent(tmp_path):
    """LAST_SEND_FAIL=0 means every page landed."""
    assert verdict(tmp_path, state()) == ""


def test_a_page_lost_long_ago_self_clears(tmp_path):
    """Latched is not permanent. An item that can never clear becomes a perpetual
    row that gets tuned out, which is how the renamer wedge went unnoticed."""
    assert verdict(tmp_path, state(send_fail_age=WINDOW + 600)) == ""


def test_a_state_file_predating_the_field_is_not_a_page(tmp_path):
    """Negative control. The deployed check writes a 2-field state file today, so
    the first sweep after this leg lands reads one with no LAST_SEND_FAIL at all.
    Inventing a lost page from a missing field would alert on the deploy itself."""
    assert verdict(tmp_path, state(field=False)) == ""


def test_an_absent_state_file_is_not_a_page(tmp_path):
    """Before the check has ever run. CRITICAL_TIMERS already covers the timer
    being stopped, so a second item here would double-count one fault."""
    assert verdict(tmp_path, "", absent=True) == ""


def test_a_garbage_value_is_not_a_page(tmp_path):
    """Fails toward silence on purpose: the sed only matches digits, so a hand-
    edited state file cannot make this leg emit, nor crash the whole sweep -- and
    this leg runs before most of the others."""
    for junk in ("LAST_SEND_FAIL=notanumber", "LAST_SEND_FAIL=", "LAST_SEND_FAIL=-5",
                 "LAST_SEND_FAIL=1e9", "LAST_SEND_FAIL=$(date)"):
        assert verdict(tmp_path, "FAILS=0\nLAST_ALERT=0\n%s\n" % junk) == "", junk


def test_the_token_is_fixed_and_not_the_age(tmp_path):
    """The hourly report is a set-diff, so a ticking value would read as a fresh
    failure every run -- the cumulative-counter-under-a-windowed-headline trap."""
    a = verdict(tmp_path, state(send_fail_age=600))
    b = verdict(tmp_path, state(send_fail_age=4000))
    assert a == b == "hltv-liveness-page=undelivered"
