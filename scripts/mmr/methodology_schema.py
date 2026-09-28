"""The `rating_methodology` aggregate's import contract: its kind, and the
guard that runs before the operator's import writes it.

Split out of `methodology.py` rather than living beside the document it
describes. That module builds the document by reading the ratings' own
constants out of the code that uses them, so it imports `ladder`, and `ladder`
imports the OpenSkill solver. The solver belongs to CI, where the ladder runs;
the data server deliberately has none, which is the entire reason the import
command is a dumb file-insert. With the guards next to the builder, importing
one pulled the other in and the operator's command died on a box that was
never meant to hold a solver.

Stdlib only, and it has to stay that way: `test_import_mmr_needs_no_solver`
derives what the command imports and imports it with `openskill` blocked, so
a dependency added here fails that test rather than a production run.
"""
from __future__ import annotations

import json

AGGREGATE_KIND = "rating_methodology"
METHOD_VERSION = "rating_methodology_v1"

FORBIDDEN_KEYS = ("players", "player_id", "steam_id", "steam_id64", "alias")


def validate_for_import(payload):
    """Problems that should stop this payload being written. [] means fine."""
    if not isinstance(payload, dict):
        return ["payload is not an object"]
    problems = []
    if payload.get("kind") != AGGREGATE_KIND:
        problems.append(f"kind is {payload.get('kind')!r}, expected {AGGREGATE_KIND!r}")
    for section in ("ktpr_v2", "mmr", "momentum"):
        if not isinstance(payload.get(section), dict):
            problems.append(f"missing section {section!r}")
    if not isinstance((payload.get("momentum") or {}).get("maps"), dict):
        problems.append("momentum.maps missing")
    body = json.dumps(payload)
    leaked = [k for k in FORBIDDEN_KEYS if f'"{k}"' in body]
    if leaked:
        problems.append(f"payload carries player-shaped keys {leaked}; this document is about nobody")
    return problems
