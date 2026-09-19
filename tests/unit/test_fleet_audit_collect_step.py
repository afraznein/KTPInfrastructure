"""The `collect` job's shell steps, executed the way GitHub executes them.

Run 34864628747 (2026-09-14, the workflow's first scheduled fire) failed in
`Fleet drift audit` with `Process completed with exit code 2`. The audit itself
was fine -- 5/5 hosts, a normal drift result -- but GitHub runs every `run:`
under `shell: /usr/bin/bash -e {0}`, so errexit is on before the script's first
line. `set -uo pipefail` adds to that; it does not clear it. The drift exit 2
came back through pipefail and bash killed the step before `rc=` was assigned,
so the `case` never ran and `Audit found drift.` never printed.

These tests run the script text out of the workflow file itself -- not a copy of
it -- under `bash -e`, with `python3` stubbed to a chosen exit code. The bug is
the NON-ZERO path, so `test_the_pre_fix_step_still_reproduces_the_failure` runs
the same harness against the step with `set +e` removed and asserts it fails;
without that control every assertion below could be passing vacuously.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/fleet-audit.yml"

AUDIT_STEP = "Fleet drift audit"
RESTART_STEP = "Restart-script drift"

# Every named `run:` step in the file. Asserted as a set below so a renamed or
# added step fails here rather than slipping past the shape check unexamined.
EXPECTED_RUN_STEPS = {
    AUDIT_STEP,
    RESTART_STEP,
    "Data-server health state",
    "Decide whether a human needs to look",
    "Open or update the issue",
    "Post the pointer",
}

_RUN_BLOCK = re.compile(r"^(\s*)run: \|\s*$")
_STEP_NAME = re.compile(r"^\s+- name: (.+?)\s*$")


def _run_blocks() -> dict[str, str]:
    """Step name -> the literal script GitHub hands to bash, dedented."""
    blocks: dict[str, str] = {}
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    name = None
    i = 0
    while i < len(lines):
        named = _STEP_NAME.match(lines[i])
        if named:
            name = named.group(1)
        opened = _RUN_BLOCK.match(lines[i])
        if opened and name is not None:
            indent = len(opened.group(1))
            body: list[str] = []
            i += 1
            while i < len(lines):
                line = lines[i]
                if line.strip() and (len(line) - len(line.lstrip())) <= indent:
                    break
                body.append(line[indent + 2 :] if line.strip() else "")
                i += 1
            blocks[name] = "\n".join(body).rstrip() + "\n"
            continue
        i += 1
    return blocks


def _bash() -> str:
    found = shutil.which("bash")
    if not found:
        pytest.skip("no bash on PATH; this asserts bash semantics")
    return found


def _exec_step(script: str, stub_rc: int) -> subprocess.CompletedProcess[str]:
    """Run `script` the way a GitHub runner does: `bash -e <file>`.

    `python3` is shadowed by a stub exiting `stub_rc`, so the shipped script runs
    byte for byte -- nothing in it is rewritten to make it testable, and no real
    audit or fleet connection happens.
    """
    bash = _bash()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "scripts").mkdir()
        (work / "scripts" / "audit-fleet-drift.py").write_text("", encoding="utf-8")
        (work / "scripts" / "ktp-restart-drift.py").write_text("", encoding="utf-8")

        bindir = work / "bin"
        bindir.mkdir()
        stub = bindir / "python3"
        stub.write_text(
            "#!/bin/sh\n"
            'echo "stub audit output"\n'
            'exit "${KTP_STUB_RC:-0}"\n',
            encoding="utf-8",
            newline="\n",
        )
        stub.chmod(0o755)

        step = work / "step.sh"
        step.write_text(script, encoding="utf-8", newline="\n")

        env = dict(os.environ)
        env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
        env["KTP_STUB_RC"] = str(stub_rc)
        # Supplied by the step's `env:` block on a real run; `set -u` needs it.
        env["STATE_FILE"] = str(work / "state.json")

        return subprocess.run(
            [bash, "-e", str(step)],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
        )


def _strip_set_plus_e(script: str) -> str:
    """The step as it shipped before the fix: errexit never cleared."""
    out = [line for line in script.splitlines() if line.strip() != "set +e"]
    assert len(out) < len(script.splitlines()), "no `set +e` to strip -- fix regressed"
    return "\n".join(out) + "\n"


# --- controls on the probe itself -------------------------------------------


def test_the_extractor_found_every_run_step() -> None:
    """Without this the shape check below could iterate an empty dict and pass."""
    blocks = _run_blocks()
    assert set(blocks) == EXPECTED_RUN_STEPS
    for name, script in blocks.items():
        assert script.strip(), f"{name} extracted as an empty script"


def test_the_stub_controls_the_exit_code() -> None:
    """Partner control: proves the harness can observe a non-zero at all."""
    assert _exec_step("python3 anything\n", stub_rc=0).returncode == 0
    assert _exec_step("python3 anything\n", stub_rc=7).returncode == 7


def test_bash_e_is_what_github_actually_uses() -> None:
    """The premise. If this ever stops being true the rest is over-defensive."""
    assert _exec_step("false\necho reached\n", stub_rc=0).returncode != 0


# --- the property, over every step, not just the one that broke --------------


def test_no_step_enables_pipefail_without_clearing_errexit() -> None:
    """`set -uo pipefail` under `bash -e {0}` leaves errexit ON.

    Stated as a property so a step added later carrying the same shape fails
    here, rather than on a Monday six weeks from now.
    """
    offenders = []
    for name, script in _run_blocks().items():
        body = [
            line.strip()
            for line in script.splitlines()
            if line.strip().startswith("set ")
        ]
        enables_pipefail = any("pipefail" in line for line in body)
        keeps_errexit = any(re.search(r"\bset -[a-z]*e", line) for line in body)
        clears_errexit = any(re.match(r"set \+[a-z]*e\b", line) for line in body)
        if enables_pipefail and not keeps_errexit and not clears_errexit:
            offenders.append(name)
    assert offenders == [], (
        f"{offenders} enable pipefail but neither keep nor clear errexit; "
        "GitHub's `bash -e {0}` leaves it on and a non-zero kills the step"
    )


# --- the audit step's three outcomes ----------------------------------------


@pytest.mark.parametrize(
    ("stub_rc", "expect_exit", "expect_stdout"),
    [
        (0, 0, "Audit clean."),
        (2, 0, "Audit found drift."),
    ],
)
def test_audit_step_reaches_the_case(
    stub_rc: int, expect_exit: int, expect_stdout: str
) -> None:
    result = _exec_step(_run_blocks()[AUDIT_STEP], stub_rc=stub_rc)
    assert result.returncode == expect_exit, result.stderr
    assert expect_stdout in result.stdout


def test_audit_step_still_fails_the_job_on_a_broken_audit() -> None:
    """Exit 1 is the audit breaking, not drift. That must stay fatal."""
    result = _exec_step(_run_blocks()[AUDIT_STEP], stub_rc=1)
    assert result.returncode == 1
    assert "FATAL: audit exited 1" in result.stderr
    assert "Audit found drift." not in result.stdout


def test_audit_step_captures_stderr_into_the_file_the_gate_reads() -> None:
    """The delta the gate greps is printed to STDERR; `2>&1` is load-bearing."""
    script = _run_blocks()[AUDIT_STEP]
    assert "2>&1 | tee audit-stdout.txt" in script


# --- the control: this suite must fail against the shipped-broken step -------


def test_the_pre_fix_step_still_reproduces_the_failure() -> None:
    """Delete `set +e` and run 34864628747's failure comes straight back.

    A test that only proved the happy path would be worthless here: the bug IS
    the non-zero path, and the happy path passed on the broken step too.
    """
    broken = _strip_set_plus_e(_run_blocks()[AUDIT_STEP])

    clean = _exec_step(broken, stub_rc=0)
    assert clean.returncode == 0, "rc=0 passed even when broken -- that is the point"
    assert "Audit clean." in clean.stdout

    drift = _exec_step(broken, stub_rc=2)
    assert drift.returncode == 2, "the pre-fix step should die on the drift exit"
    assert "Audit found drift." not in drift.stdout
    assert "Audit clean." not in drift.stdout


def test_the_pre_fix_restart_step_reproduces_nothing() -> None:
    """Honest limit: `set +e` on `Restart-script drift` changes no outcome.

    Its pipeline is the last command, so pipefail hands the same status to the
    step either way and the gate's `steps.restart_drift.outcome` read is
    unaffected. It was cleared for the shape, not for a live bug -- recorded
    here so nobody later "proves" a fix that never did anything.
    """
    script = _run_blocks()[RESTART_STEP]
    broken = _strip_set_plus_e(script)
    for rc in (0, 2, 1):
        assert _exec_step(script, stub_rc=rc).returncode == rc
        assert _exec_step(broken, stub_rc=rc).returncode == rc


# --- the comment that sent the last reader wrong -----------------------------


def test_the_step_comment_states_that_errexit_arrives_already_on() -> None:
    """The old comment named the trap and implied the step was outside it."""
    script = _run_blocks()[AUDIT_STEP]
    assert "bash -e {0}" in script
    assert "34864628747" in script
    assert "the same trap that kept the wrapper's" not in script
