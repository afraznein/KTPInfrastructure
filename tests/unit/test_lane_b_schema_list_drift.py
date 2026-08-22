"""Drift guard for Lane B's migration lists.

Lane B names its schema migrations in THREE places that have to agree:

  * `DEFAULT_SCHEMA_FILES` in `tests/e2e_stats/artifacts.py` decides which
    files are extracted out of the KTPHLStatsX commit into `artifacts/sql/`.
  * `lane-b-stats-e2e.yml` names them again on the full lane's `--schema`.
  * ...and a third time on the corpus lane's `--schema`.

Update one and the lane breaks in a way nothing else catches: a name only the
workflow knows about is a "no such file" at run time, and a name only
`DEFAULT_SCHEMA_FILES` knows about is a migration that silently never runs.
`cap_break` has zero production rows, so the corpus lane is the only place
that code path is exercised at all -- a list that quietly trails leaves the
feature untested everywhere.

Deliberately in `tests/unit/` rather than `tests/e2e_stats/`: config-tests.yml
runs this directory on every PR, while `tests/e2e_stats` only runs inside a
full Lane B job.

What this CANNOT check: whether KTPHLStatsX has published a migration nobody
added here. That needs the other repo, and Lane B must not grow a run-time
network dependency on it. Adding a migration there is still a two-repo change.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "lane-b-stats-e2e.yml"
ARTIFACTS = REPO / "tests" / "e2e_stats" / "artifacts.py"

_APPLIED = re.compile(r"/work/build/artifacts/sql/(migrate_\d+_[a-z0-9_]+\.sql)")
_DEFAULTS = re.compile(r'^\s*"sql/(migrate_\d+_[a-z0-9_]+\.sql)",\s*$', re.M)


def _workflow_schema_blocks() -> list[list[str]]:
    """Migration basenames per `--schema` block, in apply order."""
    text = WORKFLOW.read_text(encoding="utf-8")
    blocks = []
    for chunk in text.split("--schema")[1:]:
        blocks.append(_APPLIED.findall(chunk.split("--seed")[0]))
    return blocks


def _default_schema_files() -> list[str]:
    """Read the tuple as text, so this stays a pure file-vs-file comparison."""
    text = ARTIFACTS.read_text(encoding="utf-8")
    body = text.split("DEFAULT_SCHEMA_FILES = (", 1)[1].split(")", 1)[0]
    return _DEFAULTS.findall(body)


def test_the_parsers_find_something():
    """A regex that silently matches nothing turns every assertion below into
    an empty-vs-empty pass. Positive control first."""
    blocks = _workflow_schema_blocks()
    assert len(blocks) == 2, f"expected 2 --schema blocks, found {len(blocks)}"
    assert all(len(b) >= 11 for b in blocks), blocks
    assert len(_default_schema_files()) >= 11


def test_no_migration_is_extracted_without_being_applied():
    defaults = _default_schema_files()
    for i, applied in enumerate(_workflow_schema_blocks()):
        missing = [m for m in defaults if m not in applied]
        assert not missing, (
            f"--schema block {i} collects but never applies {missing}; "
            "add them to lane-b-stats-e2e.yml")


def test_no_migration_is_applied_without_being_extracted():
    defaults = set(_default_schema_files())
    for i, applied in enumerate(_workflow_schema_blocks()):
        unknown = [m for m in applied if m not in defaults]
        assert not unknown, (
            f"--schema block {i} applies {unknown}, which DEFAULT_SCHEMA_FILES "
            "never extracts -- the run fails with 'no such file'")


def test_both_lanes_apply_the_same_migrations_in_the_same_order():
    full, corpus = _workflow_schema_blocks()
    assert full == corpus, (
        "the full and corpus lanes disagree; updating one list and not the "
        "other is the exact defect this file exists to catch")


def test_ordinals_are_strictly_increasing():
    for i, applied in enumerate(_workflow_schema_blocks()):
        ordinals = [int(m.split("_")[1]) for m in applied]
        assert ordinals == sorted(set(ordinals)), (
            f"--schema block {i} is out of order or repeats: {ordinals}")


@pytest.mark.parametrize("injected", ["migrate_099_invented.sql"])
def test_guard_actually_fails_on_injected_drift(injected, tmp_path, monkeypatch):
    """Break it on purpose. A drift guard that cannot be made to fail proves
    nothing about the case it was written for."""
    text = WORKFLOW.read_text(encoding="utf-8")
    # Anchor inside a --schema block, not just the last match in the file --
    # the file's last match is a --seed entry, and rewriting that drifts
    # nothing this guard looks at.
    anchor = _workflow_schema_blocks()[0][-1]
    drifted = tmp_path / "drifted.yml"
    drifted.write_text(
        text.replace(
            f"/work/build/artifacts/sql/{anchor}",
            f"/work/build/artifacts/sql/{injected}", 1),
        encoding="utf-8")
    monkeypatch.setattr(
        "tests.unit.test_lane_b_schema_list_drift.WORKFLOW", drifted)

    with pytest.raises(AssertionError):
        test_no_migration_is_applied_without_being_extracted()
    with pytest.raises(AssertionError):
        test_both_lanes_apply_the_same_migrations_in_the_same_order()


def test_guard_catches_a_list_that_trails_the_extraction_set(tmp_path, monkeypatch):
    """The original defect, encoded: KTPHLStatsX gains a migration, someone
    adds it to DEFAULT_SCHEMA_FILES, and the workflow's own lists trail."""
    text = WORKFLOW.read_text(encoding="utf-8")
    trailing = _workflow_schema_blocks()[0][-1]
    drifted = tmp_path / "trailing.yml"
    drifted.write_text(
        "\n".join(ln for ln in text.splitlines()
                  if f"/work/build/artifacts/sql/{trailing}" not in ln),
        encoding="utf-8")
    monkeypatch.setattr(
        "tests.unit.test_lane_b_schema_list_drift.WORKFLOW", drifted)

    with pytest.raises(AssertionError):
        test_no_migration_is_extracted_without_being_applied()
