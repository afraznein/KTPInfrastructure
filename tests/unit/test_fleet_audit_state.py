"""fleet-audit.yml spends its "since last run" delta only after the run reported it.

Every collect-job check used to write its baseline into /var/lib as it ran, so a
run whose triage or Discord notice failed had already consumed the delta and the
next run reported nothing. scripts/fleet-audit-state.sh splits that into seed
(candidate copies the checks write) and promote (the last job, gated on the
reporting having succeeded).

Two halves here: the script's behaviour, driven against a temp state dir with
the real gate script standing in for a check; and the workflow's wiring, read
out of the YAML. `test_the_main_workflow_shape_fails_the_wiring_check` is the
control -- the wiring assertions must reject the pre-fix workflow text.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "scripts" / "fleet-audit-state.sh"
GATE = ROOT / "scripts" / "fleet-audit-gate.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "fleet-audit.yml"
BASH = os.environ.get("KTP_TEST_BASH", "bash")

needs_bash = pytest.mark.skipif(shutil.which(BASH) is None, reason="needs bash")

COMMITTED = (
    "ktp-audit-state-ci.json",
    "ktp-distribute-drift-ci.json",
    "ktp-restart-drift-ci.txt",
    "ktp-distribute-drift-ci.txt",
    "ktp-config-key-drift-ci.json",
    "ktp-config-key-drift-ci.txt",
)

DRIFT_A = "Atlanta:\n  DRIFT: x DIVERGES\n\nhosts reached: 5/5  clean: 4  drifted: 1\n"
DRIFT_B = DRIFT_A.replace("Atlanta:", "Denver:\n  DRIFT: y is ABSENT\nAtlanta:")


def _state(cmd: str, run_id: str, state_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [BASH, STATE.as_posix(), cmd, run_id],
        capture_output=True, text=True, timeout=60,
        env=dict(os.environ, KTP_AUDIT_STATE_DIR=state_dir.as_posix()),
    )


def _pending(state_dir: Path, run_id: str) -> Path:
    return state_dir / "ktp-fleet-audit-ci-pending" / run_id


def _gate(work: Path, gate_state: Path, drift: str) -> dict[str, str]:
    work.mkdir(parents=True, exist_ok=True)
    (work / "audit-stdout.txt").write_text("", newline="\n")
    (work / "audit-report.md").write_text("", newline="\n")
    (work / "restart-drift.txt").write_text(drift, newline="\n")
    (work / "distribute-drift.txt").write_text(
        "targets reached: 24/24  paths with drift: 0  per-instance hazards: 0\n", newline="\n")
    (work / "config-key-drift.txt").write_text(
        "No key drift.\n\ninstances compared: 24/24  paths compared: 1/1  keys compared: 1  "
        "findings: 0  inconclusive: 0  nothing-to-compare: 0\n", newline="\n")
    r = subprocess.run(
        [BASH, GATE.as_posix()], cwd=work, capture_output=True, text=True, timeout=60,
        env=dict(os.environ, KTP_GATE_STATE_DIR=gate_state.as_posix()),
    )
    assert r.returncode == 0, r.stderr
    return dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)


# --- the script --------------------------------------------------------------


@needs_bash
def test_seed_copies_committed_state_and_promote_writes_it_back(tmp_path):
    (tmp_path / "ktp-audit-state-ci.json").write_text('{"repo_drift": ["a"]}', newline="\n")
    assert _state("seed", "100", tmp_path).returncode == 0
    cand = _pending(tmp_path, "100") / "ktp-audit-state-ci.json"
    assert cand.read_text() == '{"repo_drift": ["a"]}'

    cand.write_text('{"repo_drift": ["a", "b"]}', newline="\n")
    assert (tmp_path / "ktp-audit-state-ci.json").read_text() == '{"repo_drift": ["a"]}'
    r = _state("promote", "100", tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "ktp-audit-state-ci.json").read_text() == '{"repo_drift": ["a", "b"]}'


@needs_bash
def test_a_file_first_written_by_this_run_is_promoted(tmp_path):
    assert _state("seed", "101", tmp_path).returncode == 0
    (_pending(tmp_path, "101") / "ktp-restart-drift-ci.txt").write_text("x\n", newline="\n")
    assert _state("promote", "101", tmp_path).returncode == 0
    assert (tmp_path / "ktp-restart-drift-ci.txt").read_text() == "x\n"


@needs_bash
def test_promote_is_idempotent(tmp_path):
    """Re-running notify and then promote after a failure must not refuse."""
    (tmp_path / "ktp-restart-drift-ci.txt").write_text("old\n", newline="\n")
    _state("seed", "102", tmp_path)
    (_pending(tmp_path, "102") / "ktp-restart-drift-ci.txt").write_text("new\n", newline="\n")
    assert _state("promote", "102", tmp_path).returncode == 0
    second = _state("promote", "102", tmp_path)
    assert second.returncode == 0, second.stderr
    assert (tmp_path / "ktp-restart-drift-ci.txt").read_text() == "new\n"


@needs_bash
def test_a_stale_run_cannot_roll_a_newer_baseline_back(tmp_path):
    """Run 1 seeds, run 2 seeds and promotes, then run 1 is re-run to promote."""
    (tmp_path / "ktp-restart-drift-ci.txt").write_text("v0\n", newline="\n")
    (tmp_path / "ktp-audit-state-ci.json").write_text("s0", newline="\n")
    _state("seed", "1", tmp_path)
    (_pending(tmp_path, "1") / "ktp-restart-drift-ci.txt").write_text("v1\n", newline="\n")
    (_pending(tmp_path, "1") / "ktp-audit-state-ci.json").write_text("s1", newline="\n")
    _state("seed", "2", tmp_path)
    (_pending(tmp_path, "2") / "ktp-restart-drift-ci.txt").write_text("v2\n", newline="\n")
    assert _state("promote", "2", tmp_path).returncode == 0

    stale = _state("promote", "1", tmp_path)
    assert stale.returncode == 1
    assert "REFUSED" in stale.stderr
    assert (tmp_path / "ktp-restart-drift-ci.txt").read_text() == "v2\n"
    # All or nothing: the file that had not moved is not promoted either.
    assert (tmp_path / "ktp-audit-state-ci.json").read_text() == "s0"


@needs_bash
def test_promote_refuses_a_run_that_was_never_seeded(tmp_path):
    r = _state("promote", "103", tmp_path)
    assert r.returncode == 1
    assert "never seeded" in r.stderr


@needs_bash
@pytest.mark.parametrize("bad", ["", "../x", "12a"])
def test_run_id_must_be_numeric(tmp_path, bad):
    """seed empties the run's directory, so the id must not be able to escape it."""
    assert _state("seed", bad, tmp_path).returncode == 64


# --- the property, end to end with the real gate ------------------------------


@needs_bash
def test_an_unreported_change_is_reported_again_next_run(tmp_path):
    state = tmp_path / "var-lib"
    state.mkdir()
    work = tmp_path / "w"

    _state("seed", "10", state)
    assert _gate(work, _pending(state, "10"), DRIFT_A)["needs_triage"] == "false"
    assert _state("promote", "10", state).returncode == 0

    # Run 11 sees a change and its notify fails: promote never runs.
    _state("seed", "11", state)
    assert _gate(work, _pending(state, "11"), DRIFT_B)["needs_triage"] == "true"

    # Run 12 still has something to say.
    _state("seed", "12", state)
    out = _gate(work, _pending(state, "12"), DRIFT_B)
    assert out["needs_triage"] == "true"
    assert "changed since last run" in out["reason"]


@needs_bash
def test_control_writing_state_in_place_loses_the_change(tmp_path):
    """The pre-fix shape: the gate writes /var/lib directly, so run 12 is silent."""
    state = tmp_path / "var-lib"
    state.mkdir()
    work = tmp_path / "w"
    _gate(work, state, DRIFT_A)
    assert _gate(work, state, DRIFT_B)["needs_triage"] == "true"
    assert _gate(work, state, DRIFT_B)["needs_triage"] == "false"


# --- the workflow's wiring ----------------------------------------------------


def _wiring_problems(text: str) -> list[str]:
    problems = []
    script = STATE.read_text(encoding="utf-8")
    for name in COMMITTED:
        if name not in script:
            problems.append(f"{name} is not managed by fleet-audit-state.sh")
        if re.search(rf"/var/lib/{re.escape(name)}\b", text):
            problems.append(f"the workflow writes /var/lib/{name} directly")
    for var in ("STATE_FILE", "KTP_GATE_STATE_DIR"):
        for value in re.findall(rf"^\s*{var}: (.+?)\s*$", text, re.M):
            if not value.startswith("/var/lib/ktp-fleet-audit-ci-pending/${{ github.run_id }}"):
                problems.append(f"{var} points at {value}, not this run's candidate")
    if not re.search(r"^\s*KTP_GATE_STATE_DIR: ", text, re.M):
        problems.append("the gate is not pointed at the candidate directory")
    if "fleet-audit-state.sh seed" not in text:
        problems.append("collect never seeds")

    promote = re.search(r"^  promote:\n(.*?)(?=^  \S|\Z)", text, re.M | re.S)
    if not promote:
        problems.append("no promote job")
        return problems
    job = promote.group(1)
    if "fleet-audit-state.sh promote" not in job:
        problems.append("promote job does not promote")
    if not re.search(r"needs: \[collect, triage, notify\]", job):
        problems.append("promote does not wait for notify")
    for clause in (
        "always()",
        "needs.collect.result == 'success'",
        "inputs.dry_run == false",
        "needs.collect.outputs.needs_triage != 'true'",
        "needs.triage.result == 'success'",
        "needs.notify.result == 'success'",
    ):
        if clause not in job:
            problems.append(f"promote condition lacks {clause}")
    return problems


def test_the_workflow_spends_state_only_in_the_promote_job():
    assert _wiring_problems(WORKFLOW.read_text(encoding="utf-8")) == []


def test_the_main_workflow_shape_fails_the_wiring_check():
    """Control: the pre-fix wiring, reconstructed from the shipped values."""
    text = WORKFLOW.read_text(encoding="utf-8")
    pre = re.sub(r"\n  promote:\n.*\Z", "\n", text, flags=re.S)
    pre = pre.replace(
        "/var/lib/ktp-fleet-audit-ci-pending/${{ github.run_id }}/ktp-audit-state-ci.json",
        "/var/lib/ktp-audit-state-ci.json")
    problems = _wiring_problems(pre)
    assert "the workflow writes /var/lib/ktp-audit-state-ci.json directly" in problems
    assert "no promote job" in problems
