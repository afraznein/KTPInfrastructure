"""Invariants the engine lane must keep, expressed against the workflow itself.

Two of them are decisions rather than mechanics -- `full` stays off
`pull_request`, and the lane stays on a GitHub-hosted runner -- so nothing in
the harness would notice them being undone.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/lane-b-stats-e2e.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _parsed() -> dict:
    # `on` is parsed as the boolean True by YAML 1.1, which is why this reads
    # the key back rather than indexing "on".
    return yaml.safe_load(_text())


def _triggers() -> set:
    document = _parsed()
    return set(document[True] if True in document else document["on"])


def test_the_full_lane_stays_off_pull_request_and_adds_no_new_trigger():
    assert _triggers() == {"workflow_call", "workflow_dispatch", "push", "schedule"}
    assert "pull_request" not in _triggers()


def test_the_push_trigger_is_still_the_preprod_tag_only():
    document = _parsed()
    push = (document[True] if True in document else document["on"])["push"]
    assert push == {"tags": ["lane-b-preprod-*"]}


def test_the_lane_stays_github_hosted():
    # The self-hosted runner is the production data server; this lane must not
    # migrate onto it, and a string swap here would be the whole change.
    jobs = _parsed()["jobs"]
    assert jobs
    for job in jobs.values():
        assert job["runs-on"] == "ubuntu-latest"


def test_engine_ref_is_offered_on_both_entry_points_and_defaults_to_empty():
    document = _parsed()
    triggers = document[True] if True in document else document["on"]
    for entry in ("workflow_call", "workflow_dispatch"):
        engine_ref = triggers[entry]["inputs"]["engine_ref"]
        assert engine_ref["default"] == ""
        assert engine_ref["required"] is False


def test_engine_ref_has_no_matrix_fallback():
    # AMXX_REF and friends fall back to the matrix ref. If ENGINE_REF did too,
    # every scheduled run would start injecting an engine nobody asked for.
    assert "ENGINE_REF: ${{ inputs.engine_ref || '' }}" in _text()
    assert "inputs.engine_ref || matrix.target_ref" not in _text()
    # Control: the fallback this asserts the absence of is genuinely the house
    # pattern, so the assertion above is discriminating rather than trivially true.
    assert "${{ inputs.amxx_ref || matrix.target_ref }}" in _text()


def test_the_fetch_is_gated_on_the_lane_and_on_an_engine_being_asked_for():
    assert "if: ${{ env.LANE == 'full' && env.ENGINE_REF != '' }}" in _text()


def test_the_fetch_cannot_fall_through_to_the_baked_engine():
    step = _text().split("Fetch the candidate engine")[1].split("- name:")[0]
    assert "continue-on-error" not in step
    assert "|| true" not in step
    assert "set -euo pipefail" in step
    # An unset credential is refused before the fetch, so the failure names the
    # token rather than surfacing as an opaque HTTP error.
    assert "KTP_CHECKOUT_TOKEN is unset" in step


def test_the_harness_only_receives_an_engine_when_one_was_fetched():
    run_step = _text().split("Run full synthetic 6v6 match")[1]
    assert 'if [ -n "$ENGINE_REF" ]; then' in run_step
    assert "--engine-so /work/build/engine/engine_i486.so" in run_step
    assert "--engine-provenance /work/build/engine/provenance.json" in run_step


def test_the_engine_identity_is_kept_in_the_uploaded_report():
    assert "build/lane-b-artifacts/engine/provenance.json" in _text()
