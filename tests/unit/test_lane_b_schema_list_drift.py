"""Drift guard for Lane B's migration apply order.

`DEFAULT_SCHEMA_FILES` in `tests/e2e_stats/artifacts.py` is the one list. The
builder writes the part of it the daemon ref under test carries to
`SCHEMA_MIGRATIONS_LIST`, and both `--schema` blocks in `lane-b-stats-e2e.yml`
expand that file. A migration named literally in the workflow is the defect
this guards against: every daemon ref cut before that migration then fails
with "no such file", which is how every `main`-based KTPHLStatsX PR went red
on migrate_028.

Deliberately in `tests/unit/` rather than `tests/e2e_stats/`: config-tests.yml
runs this directory on every PR, while `tests/e2e_stats` only runs inside a
Lane B job.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tests.e2e_stats import artifacts  # noqa: E402
from tests.source_anchors import HASH, code_text  # noqa: E402

WORKFLOW = REPO / ".github" / "workflows" / "lane-b-stats-e2e.yml"

_LITERAL = re.compile(r"/work/build/artifacts/sql/(migrate_\d+_[a-z0-9_]+\.sql)")
_EXPANSION = '"${schema_migrations[@]}"'
_READ = ("mapfile -t schema_migrations < "
         f"build/lane-b-artifacts/artifacts/{artifacts.SCHEMA_MIGRATIONS_LIST}")


def _schema_blocks(text: str) -> list[str]:
    """The argument text of each `--schema`, up to its `--seed`."""
    return [chunk.split("--seed")[0] for chunk in text.split("--schema")[1:]]


def _schema_steps(text: str) -> list[str]:
    return [step for step in re.split(r"\n      - name: ", text) if "--schema" in step]


def _literal_problems(text: str) -> list[str]:
    return [f"--schema block {i} hard-codes {found}"
            for i, block in enumerate(_schema_blocks(text))
            if (found := _LITERAL.findall(block))]


def _expansion_problems(text: str) -> list[str]:
    problems = [f"--schema block {i} does not apply {_EXPANSION}"
                for i, block in enumerate(_schema_blocks(text))
                if _EXPANSION not in block]
    for raw in _schema_steps(text):
        name = raw.splitlines()[0]
        # A `#` note mentioning either anchor is not the step doing it, and a
        # second `--schema` in the step makes "after" a claim about which one.
        step = code_text(raw, flavour=HASH, origin=f"lane-b-stats-e2e.yml:{name}")
        if _READ not in step:
            problems.append(f"step {name!r} never reads the builder's list")
        elif min(step.occurrences(_READ)) > min(step.occurrences("--schema")):
            problems.append(f"step {name!r} reads the builder's list after using it")
    return problems


def test_the_parsers_find_something():
    """A split that matches nothing turns every check below into a pass."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert len(_schema_blocks(text)) == 2
    assert len(_schema_steps(text)) == 2
    assert sum("migrate_" in rel for rel in artifacts.DEFAULT_SCHEMA_FILES) >= 11


def test_no_schema_block_names_a_migration_literally():
    problems = _literal_problems(WORKFLOW.read_text(encoding="utf-8"))
    assert not problems, (
        f"{problems}: a daemon ref without those files fails with 'no such "
        f"file'; register them in DEFAULT_SCHEMA_FILES and expand {_EXPANSION}")


def test_every_schema_block_applies_the_builder_list():
    problems = _expansion_problems(WORKFLOW.read_text(encoding="utf-8"))
    assert not problems, problems


def test_apply_order_is_strictly_increasing():
    ordinals = [int(Path(rel).name.split("_")[1])
                for rel in artifacts.DEFAULT_SCHEMA_FILES
                if Path(rel).name.startswith("migrate_")]
    assert ordinals == sorted(set(ordinals)), ordinals


def test_no_migration_is_both_applied_and_marked_never_applied():
    applied = set(artifacts.DEFAULT_SCHEMA_FILES) | set(artifacts.DEFAULT_SEED_FILES)
    assert not applied & set(artifacts.NOT_APPLIED_MIGRATIONS)


def test_guard_fails_on_a_reintroduced_literal():
    text = WORKFLOW.read_text(encoding="utf-8")
    drifted = text.replace(
        _EXPANSION,
        _EXPANSION + " \\\n                       "
        "/work/build/artifacts/sql/migrate_099_invented.sql",
        1)
    assert drifted != text
    assert _literal_problems(drifted)


def test_guard_fails_when_one_lane_stops_reading_the_list():
    text = WORKFLOW.read_text(encoding="utf-8")
    drifted = text.replace(_READ, "true", 1)
    assert drifted != text
    assert _expansion_problems(drifted)
