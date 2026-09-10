"""The nightly restart's stale-socket-map sweep, and the escalation it rides on.

`stale socket_map_ entry` is KTPAMXXCurl reporting an fd in its asio map that
libcurl had already disowned. It has come back 0 on 5/5 hosts every time anyone
has looked, and by the rule it was written under only a HIT closes it -- so it
was a chore that recurred forever and could never close itself. Folding it into
the nightly turns it into a monitor.

A monitor for something that has never happened is only worth having if its zero
is a measurement, which is what most of this file is about. Three failures have
already produced a clean-looking meaningless answer by hand:

  * sweeping ONE of the two log trees per instance,
  * grepping the dod tree rather than the log trees, where the string is a
    compiled-in constant in `amxxcurl_ktp_i386.so` (24 false hits, fleet-wide),
  * reporting "no hits" for a tree that was never read.

The subject is `scripts/ktp-scheduled-restart.sh.example` -- the TRACKED lineage.
The live `~/ktp-scheduled-restart.sh` on each host is gitignored by design and is
regenerated from this file; see docs/runbooks/SCHEDULED_RESTART_LINEAGES.md.

Nothing here runs the restart script. The sweep and its escalation are extracted
by anchor (each asserted to appear exactly once, so a rename fails loudly instead
of silently testing an empty string) and run against fixture log trees.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(_ROOT, "scripts", "ktp-scheduled-restart.sh.example")

SWEEP_START = "SOCKMAP_PATTERN='stale socket_map_ entry'"
SWEEP_END = "# Identify any failed ports"
ESC_START = "# The socket-map sweep rides in on the same terms"
ESC_END = 'log "Updating Discord messages with final status..."'

COLOR_GREEN = "65280"
COLOR_ORANGE = "16750848"


@pytest.fixture(scope="module")
def body():
    with open(SCRIPT, encoding="utf-8") as fh:
        return fh.read()


def _slice(body, start, end):
    assert body.count(start) == 1, f"anchor not unique: {start!r}"
    assert body.count(end) == 1, f"anchor not unique: {end!r}"
    i = body.index(start)
    j = body.index(end, i)
    assert j > i
    return body[i:j]


# -- the block is there, and escalates ------------------------------------

def test_the_sweep_scans_both_log_trees(body):
    """One tree is the failure that returns a zero about the wrong place: the
    module logs through the AMXX logger, not the HLDS one."""
    sweep = _slice(body, SWEEP_START, SWEEP_END)
    assert "serverfiles/dod/logs" in sweep
    assert "serverfiles/dod/addons/ktpamx/logs" in sweep


def test_the_sweep_passes_grep_dash_capital_i(body):
    """Without -I, `amxxcurl_ktp_i386.so` answers with its own error-message
    constant -- one false hit per instance, 24 fleet-wide."""
    sweep = _slice(body, SWEEP_START, SWEEP_END)
    assert "grep -lI " in sweep or "grep -lI -- " in sweep


def test_the_sweep_carries_a_positive_control(body):
    sweep = _slice(body, SWEEP_START, SWEEP_END)
    assert "SOCKMAP_CONTROL=" in sweep
    assert "BLIND" in sweep


def test_the_scan_window_is_bounded_and_overridable(body):
    sweep = _slice(body, SWEEP_START, SWEEP_END)
    assert "KTP_SOCKMAP_SCAN_DAYS" in sweep
    assert '-mtime -"$SOCKMAP_DAYS"' in sweep


def test_both_a_hit_and_a_blind_tree_force_green_to_orange(body):
    """The SWAP_FAILED contract: escalate even when every server came up green."""
    esc = _slice(body, ESC_START, ESC_END)
    assert esc.count("FINAL_COLOR=$COLOR_ORANGE") == 2
    assert esc.count('[ "$FINAL_COLOR" -eq "$COLOR_GREEN" ]') == 2
    assert '[ "$SOCKMAP_HITS" -gt 0 ]' in esc
    assert "${#SOCKMAP_BLIND[@]} -gt 0" in esc


def test_the_escalation_sits_beside_the_swap_failure_one(body):
    assert body.index('if [ "$SWAP_FAILED" -gt 0 ]; then\n    FINAL_DESC=') < body.index(ESC_START)
    assert body.index(ESC_START) < body.index(ESC_END)


def test_the_sweep_does_not_touch_the_exit_code(body):
    """The exit code is the RESTART's verdict. A module bug is not a failed
    restart, and conflating them makes cron report a healthy fleet as failed
    every night until somebody fixes the module."""
    tail = body[body.index(ESC_END):]
    assert "SOCKMAP" not in tail
    assert 'if [ "$SWAP_FAILED" -gt 0 ]; then\n    exit 1' in tail


# -- and it behaves ---------------------------------------------------------

HARNESS_PRELUDE = """\
# Set inside the script rather than through the environment: an MSYS/Git-Bash
# shim rewrites a path-shaped env var on the way in, so an inherited HOME can
# arrive in a form no tree matches -- and "every tree missing" is the same
# output as a genuine BLIND result, so the cases below would pass for the wrong
# reason.
HOME=$(pwd)
log() { echo "[t] $1"; }
PORTS=(27015 27016 27017 27018)
WARMUP_PRESENT=0
COLOR_GREEN=65280
COLOR_ORANGE=16750848
FINAL_COLOR=$COLOR_GREEN
FINAL_DESC="green"
"""

HARNESS_EPILOGUE = """\
echo "RESULT hits=$SOCKMAP_HITS blind=${#SOCKMAP_BLIND[@]} color=$FINAL_COLOR"
"""


def _run(body, home):
    """Run the extracted sweep + escalation with $HOME pointed at the fixtures.

    Run from inside `home`; the harness sets HOME to its own cwd. A Windows path
    handed to a POSIX bash loses its backslashes and every tree reads as missing
    -- which is the same output as the BLIND result some of these cases assert,
    so it would pass them for the wrong reason.
    """
    with open(os.path.join(home, "_harness.sh"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(HARNESS_PRELUDE)
        fh.write(_slice(body, SWEEP_START, SWEEP_END))
        fh.write(_slice(body, ESC_START, ESC_END))
        fh.write(HARNESS_EPILOGUE)
    r = subprocess.run(["bash", "_harness.sh"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=home, timeout=120)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    res = [ln for ln in out.splitlines() if ln.startswith("RESULT ")][-1]
    fields = dict(kv.split("=", 1) for kv in res.split()[1:])
    return out, fields


@pytest.fixture
def fleet(tmp_path):
    """27015 clean · 27016 hit in the AMXX tree ONLY · 27017 no AMXX tree ·
    27018 an AMXX tree whose files carry no log stamp at all."""
    home = tmp_path / "home"
    stamped = "L 09/10/2026 - 03:00:01: Log file started\n"
    for port in (27015, 27016, 27017, 27018):
        hlds = home / f"dod-{port}/serverfiles/dod/logs"
        hlds.mkdir(parents=True)
        (hlds / "L0910.log").write_text(stamped, encoding="utf-8")
    for port in (27015, 27016, 27018):
        (home / f"dod-{port}/serverfiles/dod/addons/ktpamx/logs").mkdir(parents=True)
    amxx = "L 09/10/2026 - 03:00:05: [KTPMatchHandler.amxx] [KTP] event=X\n"
    (home / "dod-27015/serverfiles/dod/addons/ktpamx/logs/L20260910.log").write_text(
        amxx, encoding="utf-8")
    (home / "dod-27016/serverfiles/dod/addons/ktpamx/logs/L20260910.log").write_text(
        "L 09/10/2026 - 03:00:05: [amxxcurl] stale socket_map_ entry fd=42\n", encoding="utf-8")
    (home / "dod-27018/serverfiles/dod/addons/ktpamx/logs/L20260910.log").write_text(
        "no log stamp on this line at all\n", encoding="utf-8")

    # The compiled constant, in the modules dir the log trees sit beside. This is
    # what a sweep of the dod TREE finds instead of log output.
    mods = home / "dod-27015/serverfiles/dod/addons/ktpamx/modules"
    mods.mkdir(parents=True)
    (mods / "amxxcurl_ktp_i386.so").write_bytes(
        b"\x7fELF\x00binary\x00stale socket_map_ entry\x00")
    return str(home)


needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")


@needs_bash
def test_a_hit_in_the_amxx_tree_alone_is_found_and_escalates(body, fleet):
    """The discriminating case: the one tree an HLDS-only sweep never reads."""
    out, f = _run(body, fleet)
    assert f["hits"] == "1"
    assert f["color"] == COLOR_ORANGE
    assert "STALE SOCKET MAP: 1 log file" in out
    assert "dod-27016" in out


@needs_bash
def test_a_clean_instance_reports_the_control_count_not_a_bare_zero(body, fleet):
    out, _ = _run(body, fleet)
    assert "[27015] hlds: clean across 1 file(s) read" in out
    assert "[27015] amxx: clean across 1 file(s) read" in out


@needs_bash
def test_a_missing_tree_and_a_control_less_tree_are_both_BLIND(body, fleet):
    """Two different ways to read nothing. Neither may render as clean."""
    out, f = _run(body, fleet)
    assert f["blind"] == "2"
    assert "[27017] amxx: BLIND" in out and "no such tree" in out
    assert "[27018] amxx: BLIND" in out and "control matched 0 files" in out


@needs_bash
def test_blind_alone_escalates_green_to_orange(body, fleet):
    """Even with zero hits. 'I found nothing' and 'I did not look' must not
    produce the same embed -- that indistinguishability is the whole card."""
    hit = os.path.join(fleet, "dod-27016/serverfiles/dod/addons/ktpamx/logs/L20260910.log")
    with open(hit, "w", encoding="utf-8") as fh:
        fh.write("L 09/10/2026 - 03:00:05: nothing interesting\n")
    out, f = _run(body, fleet)
    assert f["hits"] == "0"
    assert int(f["blind"]) > 0
    assert f["color"] == COLOR_ORANGE
    assert "its zero is not a measurement" not in out  # that line is embed text
    assert "SOCKMAP SWEEP BLIND" in out


@needs_bash
def test_a_fully_healthy_fleet_stays_green(body, tmp_path):
    """The control for every case above: with both trees present and stamped on
    every instance, the sweep neither hits nor blinds, and does not touch the
    colour. Without this, an always-orange check would pass all of them."""
    home = tmp_path / "ok"
    for port in (27015, 27016, 27017, 27018):
        for sub in ("dod/logs", "dod/addons/ktpamx/logs"):
            d = home / f"dod-{port}/serverfiles/{sub}"
            d.mkdir(parents=True)
            (d / "L0910.log").write_text("L 09/10/2026 - 03:00:01: Log file started\n",
                                         encoding="utf-8")
    out, f = _run(body, str(home))
    assert (f["hits"], f["blind"], f["color"]) == ("0", "0", COLOR_GREEN)
    assert "BLIND" not in out


@needs_bash
def test_the_compiled_constant_is_not_counted(body, fleet):
    """`amxxcurl_ktp_i386.so` carries the string and sits one directory from the
    AMXX log tree. It is excluded twice over -- by scope and by `grep -I` -- and
    a control proves it is really there to be found."""
    so = os.path.join(fleet, "dod-27015/serverfiles/dod/addons/ktpamx/modules")
    found = subprocess.run(["grep", "-rl", "stale socket_map_ entry", so],
                           capture_output=True, text=True)
    assert found.stdout.strip(), "control failed: the fixture .so does not carry the string"

    out, f = _run(body, fleet)
    assert f["hits"] == "1"                      # 27016's log line, and nothing else
    assert "amxxcurl_ktp_i386.so" not in out


@needs_bash
def test_a_tree_whose_files_all_fall_outside_the_window_is_BLIND_not_clean(body, fleet):
    """The bound must not manufacture a clean answer. Reading zero files is
    reading zero files, whatever put them out of range."""
    old = os.path.join(fleet, "dod-27015/serverfiles/dod/addons/ktpamx/logs/L20260910.log")
    os.utime(old, (0, 0))
    out, _ = _run(body, fleet)
    assert "[27015] amxx: BLIND" in out
    assert "[27015] amxx: clean" not in out


# -- the deploy path keeps it ----------------------------------------------

def test_the_deploy_tool_tripwires_the_sweep_and_its_control():
    """`deploy-restart-script.py` verifies a candidate before the atomic swap. A
    deploy that silently drops either half would leave the fleet running a check
    that cannot tell no-hits from did-not-look."""
    with open(os.path.join(_ROOT, "scripts", "deploy-restart-script.py"), encoding="utf-8") as fh:
        deploy = fh.read()
    assert "stale socket_map_ entry" in deploy
    assert "SOCKMAP_CONTROL" in deploy
