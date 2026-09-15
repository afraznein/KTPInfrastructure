"""ktp-data-server-health.sh: a proxy mid-restart is not a proxy that is down.

The sweep is extracted from the real script between the `# >>> ktp-hltv-confirm`
markers, so renaming or deleting it fails this file rather than silently testing
a copy that no longer ships. `hltv_unit_state` / `hltv_unit_restarts` are the
only stubbed pieces: they are the systemd boundary, and everything these tests
assert on is our own decision logic above it.
"""
import pathlib
import shutil
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "ktp-data-server-health.sh"
BEGIN, END = "# >>> ktp-hltv-confirm", "# <<< ktp-hltv-confirm"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

# The 24 ports the check sweeps: 27020..27044 less the intentionally-excluded
# 27044. Spelled out rather than imported so a change to either end of the range
# has to be made deliberately in two places.
PORTS = [str(p) for p in range(27020, 27044)]


def sweep_source():
    text = SCRIPT.read_text(encoding="utf-8")
    assert BEGIN in text and END in text, "the hltv-confirm markers are gone from the shipped script"
    # Drop the remainder of the marker's own line: it is prose, not shell.
    return text.split(BEGIN, 1)[1].split("\n", 1)[1].split(END, 1)[0]


def bash(tmp_path, body, name="probe.sh"):
    """Run a script from a FILE.

    Not `bash -c`: msys2 re-parses a multi-line -c argument on Windows, which
    silently eats the positional parameters and executes backticks inside
    comments. The failure looks like a bug in the script under test.
    """
    p = tmp_path / name
    p.write_text(body, encoding="utf-8", newline="\n")
    r = subprocess.run(["bash", p.as_posix()], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def run_sweep(tmp_path, first, second, ports=PORTS, name="sweep.sh"):
    """Drive hltv_confirm_states with two scripted rounds of readings.

    `first` and `second` map port -> state; anything unlisted reads "active".
    The stubbed `sleep` is what advances the round, so a sweep that skipped its
    pause would read round one twice and fail the tests that need the second.
    Returns (states, sleeps) — the confirmed state per port, and how many times
    the sweep paused.
    """
    def table(round_no, mapping):
        return "\n".join('        %d:%s) echo "%s" ;;' % (round_no, k, v)
                         for k, v in mapping.items())

    # The stubs go AFTER the extracted source, never before: the shipped block
    # defines hltv_unit_state itself, so a stub declared first is overwritten by
    # the real one and every port reads `inactive`.
    body = """set -uo pipefail
%s
ROUND=1
hltv_unit_state() {
    case "$ROUND:$1" in
%s
%s
        *) echo active ;;
    esac
}
SLEEPS=0
sleep() { SLEEPS=$((SLEEPS + 1)); ROUND=2; }
hltv_confirm_states %s > "$1"
echo "SLEEPS=$SLEEPS"
""" % (sweep_source(), table(1, first), table(2, second), " ".join(ports))

    out_file = tmp_path / (name + ".out")
    p = tmp_path / name
    p.write_text(body, encoding="utf-8", newline="\n")
    r = subprocess.run(["bash", p.as_posix(), out_file.as_posix()],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    sleeps = int(r.stdout.split("SLEEPS=")[1].strip())
    states = dict(l.split(" ", 1) for l in out_file.read_text().splitlines() if l.strip())
    return states, sleeps


def reported(states):
    """Ports the check would post, i.e. everything not confirmed active."""
    return {p: s for p, s in states.items() if s != "active"}


# ---------------------------------------------------------------- the real case

def test_the_measured_restart_transient_is_not_reported(tmp_path):
    """2026-09-15 03:00, from the journal and the health log.

    hltv-restart-all.sh stopped hltv@27028 at 03:00:02 and systemd did not mark
    it Stopped until 03:00:05 — the wrapper's `( sleep 3; kill -KILL )` holding
    the control group open. The health cron sampled at 03:00:02 and posted
    `hltv@27028=deactivating` plus `hltv-instance-count=23/24`, then "recovered"
    both at 11:00. Three seconds of a scheduled restart, two Discord posts.
    """
    states, sleeps = run_sweep(tmp_path, {"27028": "deactivating"}, {})
    assert reported(states) == {}
    assert sleeps == 1


def test_every_hltv_token_ever_logged_would_now_be_silent(tmp_path):
    """Each port named in /var/log/ktp-data-server-health.log, 2026-08-31..09-15.

    All 14 of them, and every one of the 62 occurrences, read `deactivating`.
    Not one was `failed` or `inactive`.
    """
    logged = ["27020", "27021", "27022", "27023", "27025", "27027", "27028",
              "27030", "27034", "27035", "27038", "27041", "27042", "27043"]
    for port in logged:
        states, _ = run_sweep(tmp_path, {port: "deactivating"}, {}, name="s_%s.sh" % port)
        assert reported(states) == {}, port


# ------------------------------------------------- and the failures it must keep

def test_a_stop_still_deactivating_after_the_pause_is_reported(tmp_path):
    """TimeoutStopUSec is 90s, so a stop that outlives the pause is a proxy
    ignoring SIGTERM — the thing the transient was being mistaken for."""
    states, sleeps = run_sweep(tmp_path, {"27031": "deactivating"}, {"27031": "deactivating"})
    assert reported(states) == {"27031": "deactivating"}
    assert sleeps == 1


def test_a_terminal_state_is_never_re_sampled_away(tmp_path):
    """The suppression must not reach a unit that is already down.

    Round two would say `active` for both; a sweep that re-sampled terminal
    states would swallow them, so this fails on exactly that mistake.
    """
    states, sleeps = run_sweep(
        tmp_path, {"27033": "failed", "27036": "inactive"}, {"27033": "active", "27036": "active"})
    assert reported(states) == {"27033": "failed", "27036": "inactive"}
    assert sleeps == 0, "a terminal reading must not cost a pause either"


def test_an_unknown_state_is_reported_rather_than_assumed_healthy(tmp_path):
    states, _ = run_sweep(tmp_path, {"27039": "unknown"}, {})
    assert reported(states) == {"27039": "unknown"}


def test_a_crash_looper_flapping_through_activating_survives_the_confirm(tmp_path):
    """RestartSec=10 is shorter than the confirm pause, so an auto-restart hold
    resolves to `active` and the state leg goes quiet — which is why the
    NRestarts leg exists. Here the flap lands back on `activating`."""
    states, _ = run_sweep(tmp_path, {"27040": "activating"}, {"27040": "activating"})
    assert reported(states) == {"27040": "activating"}


def test_all_healthy_costs_no_pause_and_reports_nothing(tmp_path):
    states, sleeps = run_sweep(tmp_path, {}, {})
    assert reported(states) == {}
    assert sleeps == 0
    assert len(states) == 24


def test_one_pause_for_the_whole_sweep_not_one_per_port(tmp_path):
    """Twelve transitional ports must still cost a single pause. At the shipped
    15s default, per-port would be three minutes of a cron job."""
    first = {p: "deactivating" for p in PORTS[:12]}
    states, sleeps = run_sweep(tmp_path, first, {})
    assert sleeps == 1
    assert reported(states) == {}


def test_the_sweep_returns_one_line_per_port_in_order(tmp_path):
    states, _ = run_sweep(tmp_path, {"27020": "deactivating"}, {})
    assert list(states) == PORTS


# ------------------------------------------------------- keys carry no numbers

def test_no_hltv_key_carries_a_measured_count():
    """The defect fixed for the disk keys on 2026-09-15 (#388), in the one place
    it survived: `hltv-instance-count=23/24` put the count inside the key, so
    23/24 -> 22/24 read to the set diff as a recovery plus a new failure."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "hltv-instance-count" not in text
    assert 'detail[$key]="${active_hltv}/${expected_hltv} proxies active"' in text
    # Control: the pre-fix spelling is what this test has to be able to catch.
    assert "hltv-instance-count" in 'down+=("hltv-instance-count=${active_hltv}/${expected_hltv}")'


def test_the_crash_loop_key_does_not_carry_the_restart_count():
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'key="hltv@$p=crash-looping"' in text
    assert '${nrestarts} automatic restarts' in text


def test_the_confirm_pause_and_the_restart_threshold_are_overridable():
    src = sweep_source()
    assert 'HLTV_CONFIRM_SLEEP="${HLTV_CONFIRM_SLEEP:-15}"' in src
    assert 'HLTV_RESTART_WARN="${HLTV_RESTART_WARN:-3}"' in src
    # Longer than hltv@.service's RestartSec=10, or an auto-restart hold is still
    # `activating` on the second reading and the transient comes straight back.
    assert int(src.split('HLTV_CONFIRM_SLEEP:-')[1].split('}')[0]) > 10


@pytest.mark.parametrize("state", ["activating", "deactivating", "reloading", "refreshing"])
def test_transitional_states(tmp_path, state):
    out = bash(tmp_path, "%s\nif hltv_transitional %s; then echo YES; else echo NO; fi\n"
               % (sweep_source(), state), "t_%s.sh" % state)
    assert out.strip() == "YES"


@pytest.mark.parametrize("state", ["active", "inactive", "failed", "unknown", "''"])
def test_states_that_must_not_count_as_transitional(tmp_path, state):
    """The control on the test above. A blanket `return 0` would pass every case
    there and suppress the whole check; it fails here."""
    out = bash(tmp_path, "%s\nif hltv_transitional %s; then echo YES; else echo NO; fi\n"
               % (sweep_source(), state), "n_%s.sh" % (state.strip("'") or "empty"))
    assert out.strip() == "NO"


def test_the_script_still_parses():
    r = subprocess.run(["bash", "-n", SCRIPT.as_posix()], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
