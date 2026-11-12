"""The stage manifest must agree with the runner's disk, except where it is not the record.

The suite pins versions from the manifest so that it asserts `loaded == staged`
rather than `loaded == literal`. A manifest nothing checks against disk is the
same rot one layer along: `stage-runner.py --show` printed the comparison, but
nothing consumed it, and its md5 column was read by nothing.

Two classes are deliberately different on disk and stay quiet here: plugins the
Tier-2 workflow rebuilds every run, and stack files `sync-runner-stack.py`
mirrors from the fleet. Classification is `scripts/runner_manifest.py`, shared
with `stage-runner.py --check`. Anything else that differs fails -- including an
artifact the classifier cannot place, because "could not tell" is not "fine".

Needs no hlds: it reads files. Skips off-runner, where there is no manifest.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from . import _stage_manifest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import runner_manifest  # noqa: E402


def _tree() -> str:
    return (os.environ.get("KTP_HLDS_SERVERFILES")
            or os.environ.get("KTP_TIER2_TREE", "/opt/ktp-tier2-runner/serverfiles"))


def test_manifest_agrees_with_disk_outside_the_deliberate_classes():
    manifest = _stage_manifest._load()
    if not manifest:
        pytest.skip(f"no stage manifest ({_stage_manifest.source()}) -- not on the runner")
    tree = _tree()
    if not os.path.isdir(tree):
        pytest.skip(f"serverfiles tree {tree} not present")

    recorded = {name: {"md5": _stage_manifest.staged_md5(name)} for name in manifest}
    rows = runner_manifest.classify_local(tree, recorded)
    bad = [r for r in rows if r[1] in runner_manifest.UNEXPLAINED]
    assert not bad, (
        "stage manifest disagrees with the runner's disk, and neither deliberate "
        "class (workflow-rebuilt, fleet mirror) explains it:\n"
        + "\n".join(f"  {n}: {kind}  manifest={m}  disk={d}" for n, kind, m, d in bad)
        + "\nRestage with scripts/stage-runner.py, or find what wrote the file."
    )
