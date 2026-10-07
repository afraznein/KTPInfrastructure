"""Lane B's concurrency keys must discriminate caller, event and ref.

Why this is a test and not a comment: the key is a string in a YAML file, the
failure it causes is a run that goes PENDING and is then dropped, and a dropped
run is indistinguishable from one that was never created. Nothing else in CI
can see it. #627 documented the defect; this is what stops it coming back.

A constant key put every nightly, push, PR and dispatch into one repo-wide
group. Two dispatches were measured dying seventeen and nineteen seconds after
creation, which read as "the dispatch never ran".
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"
CALLED = WORKFLOWS / "lane-b-stats-e2e.yml"
CALLERS = ("lane-b-corpus-main.yml", "lane-c-experimental.yml")

_GROUP_RE = re.compile(r"^\s*group:\s*(?P<group>.+?)\s*$", re.MULTILINE)


def _group(path: Path) -> str | None:
    """The workflow-level concurrency group, or None when there is no block."""
    text = path.read_text(encoding="utf-8")
    block = re.search(
        r"^concurrency:\n(?P<body>(?:[ \t].*\n|\n)*)", text, re.MULTILINE
    )
    if not block:
        return None
    found = _GROUP_RE.search(block.group("body"))
    return found.group("group") if found else None


def test_the_called_workflow_exists_and_declares_a_concurrency_group() -> None:
    """The control. Without it every assertion below passes on a typo."""
    assert CALLED.is_file()
    assert _group(CALLED) is not None


def test_called_workflow_key_discriminates_event_and_ref() -> None:
    group = _group(CALLED)
    assert "github.event_name" in group
    assert "github.ref" in group
    # A constant key is the whole defect; anything that cannot vary per run is
    # the same bug under a new spelling.
    assert "${{" in group


def test_called_workflow_key_discriminates_the_caller() -> None:
    """Two callers on the same ref and event should not share a queue.

    A `workflow_call` run's record carries the CALLER's identity: run
    37636221910 reports name "Lane B Corpus (main)" against path
    lane-b-corpus-main.yml while executing this file's job. Event and ref
    already carry the fix on their own, so this one is belt and braces.
    """
    assert "github.workflow" in _group(CALLED)


def test_called_workflow_still_serialises_rather_than_cancelling() -> None:
    """A Lane B run is ~60 minutes and boots hlds; cancelling in progress would
    throw away the only evidence the scheduled lane ever produces."""
    assert "cancel-in-progress: false" in CALLED.read_text(encoding="utf-8")


def test_every_caller_that_has_a_key_keys_it_per_ref() -> None:
    present = 0
    for name in CALLERS:
        path = WORKFLOWS / name
        assert path.is_file(), name
        group = _group(path)
        if group is None:
            continue
        present += 1
        assert "github.ref" in group, name
    # lane-b-corpus-main.yml carries one; if that stops being true the
    # per-ref claim in its own comment has quietly become untrue.
    assert present >= 1


def test_callers_do_not_share_a_group_with_the_called_workflow() -> None:
    called = _group(CALLED)
    for name in CALLERS:
        assert _group(WORKFLOWS / name) != called, name
