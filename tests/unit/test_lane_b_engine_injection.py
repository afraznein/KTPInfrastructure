"""Invariants the engine lane must keep, expressed against the workflow itself.

Two of them are decisions rather than mechanics -- `full` stays off
`pull_request`, and the lane stays on a GitHub-hosted runner -- so nothing in
the harness would notice them being undone.

Text assertions rather than a YAML parse: the Tier 1 gate is stdlib + pytest,
and PyYAML is not there.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/lane-b-stats-e2e.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _triggers() -> set[str]:
    lines = _text().splitlines()
    start = lines.index("on:") + 1
    found = set()
    for line in lines[start:]:
        if line and not line.startswith((" ", "#")):
            break
        match = re.match(r"^  (\w+):", line)
        if match:
            found.add(match.group(1))
    return found


def _input_block(name: str) -> list[str]:
    """Every rendering of one input, sliced to the next sibling key."""
    lines = _text().splitlines()
    blocks = []
    for index, line in enumerate(lines):
        if line != f"      {name}:":
            continue
        block = []
        for following in lines[index + 1:]:
            if re.match(r"^      \w+:", following):
                break
            block.append(following)
        blocks.append(block)
    return blocks


def test_the_full_lane_stays_off_pull_request_and_adds_no_new_trigger():
    assert _triggers() == {"workflow_call", "workflow_dispatch", "push", "schedule"}


def test_the_push_trigger_is_still_the_preprod_tag_only():
    assert "    tags: ['lane-b-preprod-*']" in _text()
    # Control: the parser above finds real keys, so an empty trigger set could
    # not have satisfied the assertion in the previous test.
    assert len(_triggers()) == 4


def test_the_lane_stays_github_hosted():
    # The self-hosted runner is the production data server; this lane must not
    # migrate onto it, and a string swap here would be the whole change.
    runners = re.findall(r"^\s*runs-on:\s*(.+)$", _text(), re.M)
    assert runners and set(runners) == {"ubuntu-latest"}


def test_engine_ref_is_offered_on_both_entry_points_and_defaults_to_empty():
    blocks = _input_block("engine_ref")
    assert len(blocks) == 2
    for block in blocks:
        assert "        required: false" in block
        assert "        default: ''" in block


def test_engine_ref_has_no_matrix_fallback():
    # AMXX_REF and its siblings fall back to the matrix ref. If ENGINE_REF did
    # too, every scheduled run would inject an engine nobody asked for.
    assert "ENGINE_REF: ${{ inputs.engine_ref || '' }}" in _text()
    assert "inputs.engine_ref || matrix.target_ref" not in _text()
    # Control: that fallback really is the house pattern here, so the assertion
    # above discriminates rather than passing on a spelling nobody uses.
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
