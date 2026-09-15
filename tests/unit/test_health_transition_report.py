"""ktp-data-server-health.sh: a one-sided transition must still reach the channel.

Two helpers are extracted from the real script, between their `# >>>`/`# <<<`
markers, so renaming or deleting either fails this file rather than silently
testing a copy that no longer ships.

The bug this pins: `printf '%s\\n' "${arr[@]}" | grep -v '^$' | paste -sd, -`
prints one blank line for an empty array, grep matches nothing and exits 1, and
under `set -e -o pipefail` the assignment kills the run — before the TRANSITIONS
line and before the Discord POST. Between #207 (2026-08-31) and the fix, the live
log carried 0 one-sided transitions in 42; the month before it carried 257 in 283.
"""
import pathlib
import shutil
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "ktp-data-server-health.sh"
CRON = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "ktp-data-server-health.cron"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def block(name):
    text = SCRIPT.read_text(encoding="utf-8")
    begin, end = "# >>> %s" % name, "# <<< %s" % name
    assert begin in text and end in text, "%s markers are gone from the shipped script" % name
    return text.split(begin, 1)[1].split("\n", 1)[1].split(end, 1)[0]


def bash(tmp_path, body, name="probe.sh", expect_ok=True):
    """Run a script from a FILE.

    Not `bash -c`: msys2 re-parses a multi-line -c argument on Windows, which
    silently eats the positional parameters. The failure looks like a bug in the
    script under test.
    """
    p = tmp_path / name
    p.write_text(body, encoding="utf-8", newline="\n")
    r = subprocess.run(["bash", p.as_posix()], capture_output=True, text=True)
    if expect_ok:
        assert r.returncode == 0, "exit %d; stderr=%r" % (r.returncode, r.stderr)
    return r


STRICT = "set -euo pipefail\n"


# ---------------------------------------------------------------- join_keys

def report_line(tmp_path, new_down, recovered, name):
    """The script's own reporting lines, run under the script's own `set` flags."""
    body = STRICT + block("ktp-alert-join") + "\n"
    body += "new_down=(%s)\n" % " ".join("'%s'" % x for x in new_down)
    body += "recovered=(%s)\n" % " ".join("'%s'" % x for x in recovered)
    body += 'new_down_names=$(join_keys "${new_down[@]}")\n'
    body += 'recovered_names=$(join_keys "${recovered[@]}")\n'
    body += ('echo "TRANSITIONS: new_down=${#new_down[@]}${new_down_names:+ [${new_down_names}]}'
             ' recovered=${#recovered[@]}${recovered_names:+ [${recovered_names}]}"\n')
    return bash(tmp_path, body, name)


def test_failure_with_no_simultaneous_recovery_still_reports(tmp_path):
    """mysql dies and nothing else clears. This produced NO alert at all."""
    out = report_line(tmp_path, ["mysql.service=failed"], [], "a.sh").stdout
    assert "new_down=1 [mysql.service=failed]" in out
    assert "recovered=0" in out


def test_recovery_with_no_simultaneous_failure_still_reports(tmp_path):
    out = report_line(tmp_path, [], ["hltv@27028=deactivating"], "b.sh").stdout
    assert "new_down=0" in out
    assert "recovered=1 [hltv@27028=deactivating]" in out


def test_two_sided_transition_is_unchanged(tmp_path):
    out = report_line(tmp_path, ["a=1", "b=2"], ["c=3"], "c.sh").stdout
    assert "new_down=2 [a=1,b=2] recovered=1 [c=3]" in out


def test_pre_fix_spelling_would_have_died(tmp_path):
    """Control: the idiom that shipped must fail, or the tests above prove nothing."""
    body = STRICT + "nd=()\n"
    body += "x=$(printf '%s\\n' \"${nd[@]}\" 2>/dev/null | grep -v '^$' | paste -sd, -)\n"
    body += 'echo "REACHED"\n'
    r = bash(tmp_path, body, "control.sh", expect_ok=False)
    assert r.returncode != 0
    assert "REACHED" not in r.stdout


def code_lines():
    """Shipped script with comment-only lines dropped — the fix's own comment
    quotes the idiom it removed, and a whole-file scan would match that."""
    return [ln for ln in SCRIPT.read_text(encoding="utf-8").splitlines()
            if not ln.lstrip().startswith("#")]


def test_join_keys_is_used_for_every_transition_list():
    """The fragile idiom must not survive anywhere in the reporting path."""
    code = "\n".join(code_lines())
    assert "grep -v '^$' | paste" not in code
    assert "grep -v '^$' | sort" not in code
    assert code.count("join_keys ") >= 3


# ------------------------------------------------------------- settled_state

def settle(tmp_path, states, name, settle_seconds=0):
    """Replay a fake `systemctl is-active` that returns `states` in order."""
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    seq = tmp_path / ("%s.seq" % name)
    seq.write_text("\n".join(states) + "\n", encoding="utf-8", newline="\n")
    (fake / "systemctl").write_text(
        "#!/bin/bash\n"
        "n=$(cat %s.n 2>/dev/null || echo 1)\n"
        "sed -n \"${n}p\" %s\n"
        "echo $((n + 1)) > %s.n\n" % (seq.as_posix(), seq.as_posix(), seq.as_posix()),
        encoding="utf-8", newline="\n")
    (fake / "systemctl").chmod(0o755)
    body = ("export PATH=%s:$PATH\n" % fake.as_posix()) + STRICT
    body += "SETTLE_SECONDS=%d\n" % settle_seconds
    body += block("ktp-alert-settle") + "\n"
    body += "settled_state some.service\n"
    body += 'echo "STATE=$SETTLED"\n'
    body += 'echo "SLEPT=$_settle_slept"\n'
    return bash(tmp_path, body, name + ".sh").stdout


def test_a_unit_caught_mid_restart_is_not_down(tmp_path):
    """The 03:00/11:00 artifact: deactivating at the sample, active moments later."""
    out = settle(tmp_path, ["deactivating", "active"], "settle_ok")
    assert "STATE=active" in out
    assert "SLEPT=1" in out


def test_a_unit_still_not_active_after_the_settle_still_alerts(tmp_path):
    out = settle(tmp_path, ["deactivating", "failed"], "settle_stuck")
    assert "STATE=failed" in out


def test_a_wedged_deactivating_unit_still_alerts(tmp_path):
    out = settle(tmp_path, ["deactivating", "deactivating"], "settle_wedged")
    assert "STATE=deactivating" in out


def test_an_active_unit_costs_no_sleep(tmp_path):
    out = settle(tmp_path, ["active"], "settle_active")
    assert "STATE=active" in out
    assert "SLEPT=0" in out


def test_a_plainly_failed_unit_is_not_given_a_grace_period(tmp_path):
    """`failed` is terminal. Re-reading it would only delay the alert."""
    out = settle(tmp_path, ["failed", "active"], "settle_failed")
    assert "STATE=failed" in out
    assert "SLEPT=0" in out


def test_settled_state_is_what_the_probes_call():
    code = "\n".join(code_lines())
    assert 'settled_state "$svc"; state=$SETTLED' in code
    assert 'settled_state "hltv@$p"; state=$SETTLED' in code
    assert 'systemctl is-active "hltv@$p"' not in code


def test_settled_state_is_never_called_in_a_subshell():
    """`s=$(settled_state x)` discards the once-per-run latch: 24 proxies would
    each pay the delay. It must answer in $SETTLED, in the caller's shell."""
    code = "\n".join(code_lines())
    assert "$(settled_state" not in code


# -------------------------------------------------------------------- cron

def test_cron_does_not_sample_on_the_restart_minute():
    """hltv-restart.timer is OnCalendar 03:00 and 11:00. :00 samples that restart."""
    line = [ln for ln in CRON.read_text(encoding="utf-8").splitlines()
            if "ktp-data-server-health.sh" in ln and not ln.startswith("#")]
    assert len(line) == 1, line
    minute = line[0].split()[0]
    assert minute != "0", "the hourly sample is back on the restart minute"
    assert 1 <= int(minute) <= 59
