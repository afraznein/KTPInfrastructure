"""ktp-run-record.sh: a scheduled run leaves a record, and a wedge leaves a different one.

journald on the data server holds about two days. Six oneshot units report by
printing and exiting non-zero, so a weekly unit that fails on a Tuesday cannot be
read by the following Tuesday -- that is the steady state, not an incident.
`docs/runbooks/UNIT_RUN_RECORDS.md` is the convention; this file is the proof that
the wrapper implementing it keeps what it claims to keep.

What is deliberately tested here, because each one has a way of passing while
being useless:

  - A failure is captured, not just a success. A retention mechanism never shown
    to capture a failure is not one, so there is a mutation test: strip the
    footer writer out of a copy and the failure assertion must go red.
  - A wedge is distinguishable from a clean pass. `Restart=`, `OnFailure=` and
    `systemctl is-active` all key on an exit a wedged process never makes --
    hltv-demo-renamer sat `active` for 53 hours inside CRITICAL_SERVICES and two
    days of demos were purged unrenamed. A promoted record naming the signal and
    an orphan `.part` are the two shapes that answer it.
  - The exit code is passed through untouched, because every one of these units
    delivers its findings BY failing.
  - Every unit that names the wrapper declares StateDirectory= and
    TimeoutStartSec=. Type=oneshot disables the start timeout by default, so the
    second one is what makes a wedge an exit at all.

The signal cases run through a small bash driver rather than Python's
terminate(): on Windows terminate() is TerminateProcess, no SIGTERM is delivered
and the trap under test never runs -- so the test would pass by not testing.
"""
import os
import pathlib
import re
import shutil
import subprocess
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ktp-run-record.sh"
UNIT_DIR = ROOT / "scripts" / "systemd"
# CI runs plain bash; on a Windows workstation "bash" may resolve to WSL's, which
# cannot see these paths -- point KTP_TEST_BASH at Git Bash there.
BASH = os.environ.get("KTP_TEST_BASH", "bash")

pytestmark = pytest.mark.skipif(shutil.which(BASH) is None, reason="needs bash")


def sh_path(p):
    """A path bash will actually write to.

    On a Windows workstation a drive-letter path is not a no-op: `mkdir -p
    "C:/Users/..."` under Git Bash SUCCEEDS and creates `./C/Users/...` instead,
    so every assertion in this file reads as "nothing was recorded" while the
    wrapper is working perfectly. cygpath is the conversion; on Linux CI there is
    nothing to convert and as_posix() is the whole answer.
    """
    posix = pathlib.Path(p).as_posix()
    if os.name != "nt":
        return posix
    out = subprocess.run(["cygpath", "-u", posix], capture_output=True, text=True)
    assert out.returncode == 0, "cygpath failed; set KTP_TEST_BASH to Git Bash"
    return out.stdout.strip()


def run(record_dir, *cmd, script=None, env=None, timeout=60):
    e = dict(os.environ)
    e["KTP_RUN_RECORD_DIR"] = sh_path(record_dir)
    e.pop("STATE_DIRECTORY", None)
    e.update(env or {})
    return subprocess.run(
        [BASH, sh_path(script or SCRIPT), *cmd],
        capture_output=True, text=True, env=e, timeout=timeout,
    )


def records(record_dir):
    runs = pathlib.Path(record_dir) / "runs"
    if not runs.is_dir():
        return []
    return sorted(p for p in runs.iterdir() if p.name.endswith(".txt"))


def parts(record_dir):
    runs = pathlib.Path(record_dir) / "runs"
    if not runs.is_dir():
        return []
    return sorted(p for p in runs.iterdir() if p.name.endswith(".part"))


# --- the two outcomes the wrapper exists for -------------------------------


def test_a_clean_run_is_recorded_and_still_reaches_the_journal(tmp_path):
    d = tmp_path / "clean"
    p = run(d, "/bin/sh", "-c", "echo on-stdout; echo on-stderr >&2")
    assert p.returncode == 0, p.stderr

    kept = records(d)
    assert len(kept) == 1, [x.name for x in kept]
    text = kept[0].read_text(encoding="utf-8")
    assert "on-stdout" in text and "on-stderr" in text
    assert re.search(r"^finished: \d{4}-", text, re.M), text
    assert re.search(r"^rc: 0$", text, re.M), text

    # The embed body is the journal tail, so the wrapper must not swallow output.
    assert "on-stdout" in p.stdout and "on-stderr" in p.stdout


def test_a_failing_run_is_recorded_with_its_findings_and_its_code(tmp_path):
    d = tmp_path / "fail"
    p = run(d, "/bin/sh", "-c", "echo CRITICAL: two identities diverge; exit 3")
    assert p.returncode == 3, (p.returncode, p.stderr)

    kept = records(d)
    assert len(kept) == 1
    text = kept[0].read_text(encoding="utf-8")
    assert "CRITICAL: two identities diverge" in text
    assert re.search(r"^rc: 3$", text, re.M), text
    assert re.search(r"^finished: ", text, re.M), text


def test_mutation_without_the_footer_writer_the_failure_assertion_goes_red(tmp_path):
    """Proof the assertion above can fail -- otherwise it is decoration.

    Strip the footer out of a copy of the shipped script and the promoted record
    no longer says the run finished or what it returned.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    needle = "        printf 'rc: %s\\n' \"$rc\"\n"
    assert needle in text, "the footer writer moved; this mutation no longer bites"
    broken = tmp_path / "mutant-run-record.sh"
    broken.write_text(text.replace(needle, ""), encoding="utf-8", newline="\n")

    d = tmp_path / "mutant"
    p = run(d, "/bin/sh", "-c", "echo CRITICAL: a finding; exit 3", script=broken)
    assert p.returncode == 3
    kept = records(d)
    assert len(kept) == 1
    mutated = kept[0].read_text(encoding="utf-8")
    assert "CRITICAL: a finding" in mutated
    # The claim the real test makes, now false.
    assert not re.search(r"^rc: 3$", mutated, re.M), (
        "the mutant still records the exit code, so the assertion proves nothing"
    )


# --- the wedge, which is the shape every process-state check misses --------


DRIVER = """#!/bin/bash
# $1 wrapper  $2 record dir  $3 signal  $4 pidfile
set -u
KTP_RUN_RECORD_DIR="$2" "$BASH_SOURCE_SHELL" "$1" /bin/sh -c \\
    'echo working; echo $$ > "'"$4"'"; exec sleep 30' &
w=$!
for _ in $(seq 1 200); do
    [ -s "$4" ] && break
    sleep 0.1
done
# systemd signals every process in the unit's cgroup; do the same, or bash
# defers the trap until a child that was never signalled finishes on its own.
child="$(cat "$4" 2>/dev/null)"
[ -n "$child" ] && kill -"$3" "$child" 2>/dev/null
kill -"$3" "$w" 2>/dev/null
wait "$w"
echo "wrapper_rc=$?"
"""


def drive(tmp_path, record_dir, signal):
    driver = tmp_path / ("drive-%s.sh" % signal)
    driver.write_text(DRIVER.replace("$BASH_SOURCE_SHELL", BASH), encoding="utf-8")
    pidfile = tmp_path / ("child-%s.pid" % signal)
    pidfile.write_text("", encoding="utf-8")
    return subprocess.run(
        [BASH, sh_path(driver), sh_path(SCRIPT),
         sh_path(record_dir), signal, sh_path(pidfile)],
        capture_output=True, text=True, timeout=120,
    )


def test_a_run_cut_short_by_sigterm_is_not_a_clean_pass(tmp_path):
    """TimeoutStartSec= expiring is this shape. The record has to say so."""
    d = tmp_path / "term"
    out = drive(tmp_path, d, "TERM")
    kept = records(d)
    assert len(kept) == 1, (out.stdout, out.stderr, [x.name for x in parts(d)])
    text = kept[0].read_text(encoding="utf-8")
    assert "working" in text
    assert re.search(r"^killed: SIGTERM$", text, re.M), text
    # Still promoted, and still says it ended: the discriminator is `killed:`,
    # never the absence of a footer.
    assert re.search(r"^finished: ", text, re.M), text
    assert not parts(d), [x.name for x in parts(d)]


def test_a_run_killed_outright_leaves_an_unpromoted_part(tmp_path):
    """No timeout set, or TimeoutStopSec expired after the TERM, or the box went
    down. Nothing runs to promote the record, and the file left behind is the
    only trace -- which is why the runbook says not to clean these up."""
    d = tmp_path / "kill"
    out = drive(tmp_path, d, "KILL")
    orphans = parts(d)
    assert len(orphans) == 1, (out.stdout, out.stderr, [x.name for x in records(d)])
    text = orphans[0].read_text(encoding="utf-8")
    assert "working" in text
    assert "finished:" not in text, text
    assert not records(d), [x.name for x in records(d)]


# --- refusals, so a mis-install is loud rather than silent -----------------


def test_without_a_state_directory_it_refuses_and_runs_nothing(tmp_path):
    sentinel = tmp_path / "ran"
    e = dict(os.environ)
    e.pop("STATE_DIRECTORY", None)
    e.pop("KTP_RUN_RECORD_DIR", None)
    p = subprocess.run(
        [BASH, sh_path(SCRIPT), "/bin/sh", "-c", 'touch "%s"' % sh_path(sentinel)],
        capture_output=True, text=True, env=e, timeout=60,
    )
    assert p.returncode == 78, (p.returncode, p.stdout, p.stderr)
    assert "StateDirectory" in p.stderr
    assert not sentinel.exists(), "it ran the command anyway, keeping nothing"


def test_a_non_numeric_horizon_refuses_rather_than_silently_not_pruning(tmp_path):
    p = run(tmp_path / "keep", "/bin/true", env={"KTP_RUN_RECORD_KEEP_DAYS": "forever"})
    assert p.returncode == 78, (p.returncode, p.stderr)
    assert "KEEP_DAYS" in p.stderr


def test_no_command_is_a_usage_error(tmp_path):
    p = run(tmp_path / "usage")
    assert p.returncode == 64, (p.returncode, p.stderr)


# --- the high-cadence mode -------------------------------------------------


def test_only_failures_stamps_a_success_and_archives_a_failure(tmp_path):
    d = tmp_path / "cheap"
    env = {"KTP_RUN_RECORD_ONLY_FAILURES": "1"}

    ok = run(d, "/bin/sh", "-c", "echo rendered 41 bans", env=env)
    assert ok.returncode == 0, ok.stderr
    assert [p.name for p in records(d)] == ["last-ok.txt"]
    stamp = (d / "runs" / "last-ok.txt").read_text(encoding="utf-8")
    assert "rendered 41 bans" in stamp
    assert re.search(r"^rc: 0$", stamp, re.M), stamp

    bad = run(d, "/bin/sh", "-c", "echo api 503 >&2; exit 4", env=env)
    assert bad.returncode == 4, bad.stderr
    names = [p.name for p in records(d)]
    assert "last-ok.txt" in names
    dated = [n for n in names if n != "last-ok.txt"]
    assert len(dated) == 1, names
    assert "api 503" in (d / "runs" / dated[0]).read_text(encoding="utf-8")


def test_pruning_drops_an_old_record_and_spares_last_ok(tmp_path):
    """last-ok.txt is the newest success even when that success is old. Deleting
    it on age would turn a long outage into "this unit has never worked"."""
    d = tmp_path / "prune"
    runs = d / "runs"
    runs.mkdir(parents=True)
    stale = runs / "2024-01-01T000000Z.txt"
    stale.write_text("old\n", encoding="utf-8")
    old_ok = runs / "last-ok.txt"
    old_ok.write_text("old success\n", encoding="utf-8")
    long_ago = time.time() - 500 * 86400
    for p in (stale, old_ok):
        os.utime(p, (long_ago, long_ago))

    p = run(d, "/bin/sh", "-c", "exit 1", env={"KTP_RUN_RECORD_KEEP_DAYS": "30"})
    assert p.returncode == 1, p.stderr
    assert not stale.exists(), "a record past the horizon was kept"
    assert old_ok.exists(), "last-ok.txt was pruned"


# --- the unit files -------------------------------------------------------


def wrapped_units():
    out = []
    for unit in sorted(UNIT_DIR.glob("*.service")):
        text = unit.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("ExecStart=") and "ktp-run-record.sh" in line:
                out.append((unit, text))
                break
    return out


def test_some_units_are_wrapped_at_all():
    """Positive control: every assertion below is vacuous on an empty list, and
    this test is what notices if the wrapper is quietly unwired."""
    assert len(wrapped_units()) >= 6, [u.name for u, _ in wrapped_units()]


@pytest.mark.parametrize("unit,text", wrapped_units(), ids=lambda v: getattr(v, "name", ""))
def test_a_wrapped_unit_declares_its_directory_and_a_timeout(unit, text):
    assert re.search(r"^StateDirectory=\S", text, re.M), (
        "%s wraps ktp-run-record.sh but declares no StateDirectory=; the wrapper "
        "refuses to run (exit 78) rather than keeping nothing" % unit.name
    )
    assert re.search(r"^TimeoutStartSec=\S", text, re.M), (
        "%s is Type=oneshot, where systemd DISABLES the start timeout by default, "
        "so a wedged run never fails, never fires OnFailure and leaves no record "
        "at all -- see docs/runbooks/UNIT_RUN_RECORDS.md" % unit.name
    )


def test_the_wrapper_is_referenced_by_absolute_installed_path():
    for unit, text in wrapped_units():
        line = next(l for l in text.splitlines()
                    if l.startswith("ExecStart=") and "ktp-run-record.sh" in l)
        assert "/usr/local/bin/ktp-run-record.sh" in line, (unit.name, line)
