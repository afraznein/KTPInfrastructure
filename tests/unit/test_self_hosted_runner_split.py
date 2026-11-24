"""Which workflow may run on which self-hosted runner on the data server.

Labels are not a security boundary on a personal-account repo, so this does not
stop a pull request naming `ktp-ops`. It stops a reviewed change from quietly
putting a root-only job back on the runner pull requests reach, or a
pull-request trigger onto a root runner's workflow.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"

OPS_WORKFLOWS = {"fleet-audit.yml", "report-regeneration.yml"}
PR_TRIGGERS = {"pull_request", "pull_request_target"}


def _triggers(text: str) -> set[str]:
    block = re.search(r"^on:\n((?:  .*\n|\n)+?)^\S", text, re.MULTILINE)
    assert block, "expected a block-form on: mapping"
    return set(re.findall(r"^  (\w+):", block.group(1), re.MULTILINE))


def _self_hosted_labels(text: str) -> list[str]:
    return re.findall(r"^\s*runs-on: \[self-hosted, ([\w-]+)\]", text, re.MULTILINE)


def _all() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(WORKFLOWS.glob("*.yml"))}


def test_the_parsers_see_the_workflows() -> None:
    wfs = _all()
    assert "pull_request" in _triggers(wfs["tier2-integration.yml"])
    assert _self_hosted_labels(wfs["tier2-integration.yml"]) == ["ktp-tier2"]
    assert _triggers(wfs["fleet-audit.yml"])


def test_ops_workflows_run_only_on_the_ops_runner() -> None:
    wfs = _all()
    for name in OPS_WORKFLOWS:
        labels = _self_hosted_labels(wfs[name])
        assert labels and set(labels) == {"ktp-ops"}, (name, labels)


def test_no_pull_request_workflow_uses_the_ops_runner() -> None:
    for name, text in _all().items():
        if _triggers(text) & PR_TRIGGERS:
            assert "ktp-ops" not in _self_hosted_labels(text), name


def test_ops_workflows_have_no_pull_request_trigger() -> None:
    wfs = _all()
    for name in OPS_WORKFLOWS:
        assert not (_triggers(wfs[name]) & PR_TRIGGERS), name


def test_only_tier2_integration_uses_the_tier2_runner() -> None:
    users = sorted(n for n, t in _all().items() if "ktp-tier2" in _self_hosted_labels(t))
    assert users == ["tier2-integration.yml"], users
