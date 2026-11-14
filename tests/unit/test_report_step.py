"""report_step.sh: every ktp-reports step leaves a start and an end, or says it was killed.

The journal records only `code=killed` when the unit's TimeoutStartSec fires, so
the log has to say which of generate, aggregate and sync was running.
"""
import os
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "report_step.sh"
UNIT = ROOT / "systemd" / "ktp-reports.service"
# On a Windows workstation "bash" may be WSL's, which cannot see these paths.
BASH = os.environ.get("KTP_TEST_BASH", "bash")

STAMP = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ"

needs_bash = pytest.mark.skipif(shutil.which(BASH) is None, reason="needs bash")


def sh_path(p):
    posix = pathlib.Path(p).as_posix()
    if os.name != "nt":
        return posix
    out = subprocess.run(["cygpath", "-u", posix], capture_output=True, text=True)
    assert out.returncode == 0, "cygpath failed; set KTP_TEST_BASH to Git Bash"
    return out.stdout.strip()


def run(*cmd, script=SCRIPT, timeout=20):
    return subprocess.run([BASH, sh_path(script), *cmd],
                          capture_output=True, text=True, timeout=timeout)


@needs_bash
def test_a_clean_step_is_bracketed_and_keeps_its_output():
    p = run("generate", "/bin/sh", "-c", "echo step-output")
    assert p.returncode == 0, p.stderr
    lines = p.stdout.splitlines()
    assert re.fullmatch(STAMP + r" ktp-reports step=generate start pid=\d+", lines[0]), lines
    assert lines[1] == "step-output"
    assert re.fullmatch(STAMP + r" ktp-reports step=generate end rc=0 elapsed=\d+s", lines[2]), lines


@needs_bash
def test_a_failing_step_passes_its_code_through():
    # systemd stops the unit at the first non-zero ExecStart; the wrapper must not mask it.
    p = run("aggregate", "/bin/sh", "-c", "exit 3")
    assert p.returncode == 3
    assert re.search(r"step=aggregate end rc=3 ", p.stdout), p.stdout


@needs_bash
def test_a_timeout_names_the_step_and_does_not_wait_out_the_child():
    # The child TERMs the wrapper, as systemd's timeout would. If the wrapper did
    # not forward it, the 30 s sleep would outlive the 20 s test timeout.
    p = run("sync", "/bin/sh", "-c", "kill -TERM $PPID; exec sleep 30")
    assert p.returncode == 143, (p.returncode, p.stdout, p.stderr)
    assert re.search(STAMP + r" ktp-reports step=sync killed signal=TERM elapsed=\d+s", p.stdout), p.stdout
    assert "step=sync end" not in p.stdout


@needs_bash
def test_mutation_without_the_trap_the_killed_line_is_missing(tmp_path):
    text = SCRIPT.read_text(encoding="utf-8")
    needle = "trap on_term TERM\n"
    assert needle in text, "the trap moved; this mutation no longer bites"
    mutant = tmp_path / "mutant-report-step.sh"
    mutant.write_text(text.replace(needle, ""), encoding="utf-8", newline="\n")
    p = run("sync", "/bin/sh", "-c", "kill -TERM $PPID; exit 0", script=mutant)
    assert "killed signal=TERM" not in p.stdout


@needs_bash
def test_usage_refuses_a_missing_command():
    p = run("generate")
    assert p.returncode == 64


def test_every_pipeline_step_in_the_unit_goes_through_the_wrapper():
    unit = UNIT.read_text(encoding="utf-8")
    steps = re.findall(r"^ExecStart=(.*)$", unit, re.M)
    assert len(steps) == 3, steps
    names = []
    for line in steps:
        m = re.match(r"/bin/bash scripts/report_step\.sh (\w+) /usr/bin/python3 -m scripts\.report_(service|sync) ", line)
        assert m, line
        names.append(m.group(1))
    assert names == ["generate", "aggregate", "sync"]


def test_the_season_floor_still_parses_through_the_wrapper():
    import sys
    sys.path.insert(0, str(ROOT))
    from scripts import report_regen_guard as guard

    assert guard.unit_floor(UNIT.read_text(encoding="utf-8")) == "2026-09-13"
