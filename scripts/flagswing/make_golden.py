"""Generate golden.json: state -> expected p_allies, computed by the PRODUCTION Python.

The flag_swing timeline stored in the prod reports does not carry the flag/alive
state behind each `p_allies_after`, so it cannot be replayed directly. Instead we
take the *shape* of three real matches (roster size, team split, distinct flag
indices) from the reports, drive a deterministic synthetic event sequence over
that shape, and record every intermediate state together with the p_allies that
`_HalfState.p_allies` -- imported from the real pipeline module, not re-typed --
produces. The JS test replays the same event sequence, so the check is a true
cross-language comparison against production code.

Standard library only (no numpy/matplotlib on this box).

Usage:
    python make_golden.py [--source FLAG_SWING_PY] [--reports GLOB] [--out golden.json]
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Co-located with the pipeline's own flag_swing.py in this repo -- resolved
# relative to this file, not hardcoded to one machine's checkout path.
DEFAULT_SOURCE = HERE.parent / "flag_swing.py"
# Match reports are a local analytics artifact, not part of this repo. Only
# needed to pick 3 realistic (roster, flag) *shapes* to drive synthetic replay
# with -- see match_shapes() -- so re-running this against a different machine
# means passing --reports to wherever that machine keeps its prod-reports.
DEFAULT_REPORTS = (
    r"G:\GIT\ktp_stats\artifacts\real-match-tier2-20260906\prod-reports\*.json"
)
MATCH_COUNT = 3
HALVES = 2
EVENTS_PER_HALF = 90


def load_flag_swing(path: Path):
    spec = importlib.util.spec_from_file_location("ktp_flag_swing", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot import flag_swing from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # @dataclass resolves annotations via sys.modules
    spec.loader.exec_module(module)
    return module


def match_shapes(pattern: str, limit: int) -> list[dict]:
    """Roster + flag shape of the first `limit` reports with a usable envelope."""
    shapes: list[dict] = []
    for path in sorted(glob.glob(pattern)):
        with open(path, encoding="utf-8") as handle:
            report = json.load(handle)
        envelope = report.get("shadow_explorations", {}).get("flag_swing", {})
        if envelope.get("status") != "available":
            continue
        teams = {int(p["player_id"]): int(p["team"])
                 for p in envelope.get("players", [])
                 if p.get("team") in (1, 2)}
        if not teams:
            continue
        # Distinct flag indices actually observed; the pipeline derives the same
        # count from flag_states, which the report does not carry.
        flag_ids = sorted({row["flag_index"] for row in envelope.get("timeline", [])
                           if row.get("kind") == "flag"
                           and row.get("flag_index") is not None})
        shapes.append({
            "match_id": report.get("match_id") or Path(path).stem,
            "map_name": report.get("match", {}).get("map_name"),
            "teams": teams,
            "flag_ids": flag_ids,
        })
        if len(shapes) == limit:
            break
    if len(shapes) < limit:
        raise SystemExit(f"only {len(shapes)} usable reports matched {pattern}")
    return shapes


def build_case(module, shape: dict, seed: int, *, null_flags: bool,
               force_no_flags: bool) -> dict:
    """Replay a synthetic half-by-half event stream through the real _HalfState."""
    rng = random.Random(seed)
    teams = shape["teams"]
    flag_ids = [] if force_no_flags else list(shape["flag_ids"])
    if null_flags:
        # The pipeline stores owners[None] when flag_index is missing: such a flag
        # counts in the numerator but never in the (distinct-index) denominator.
        flag_ids = flag_ids + [None]
    # Exactly the pipeline's own expression, incl. the `or 5` fallback.
    distinct = {f for f in flag_ids if f is not None}
    flag_count = len(distinct) or 5
    roster_size = len(teams)

    steps: list[dict] = []
    for _half in range(HALVES):
        state = module._HalfState(flag_count, roster_size, module.FlagSwingConfig())
        for pid, team in teams.items():
            state.teams[pid] = team
            state.alive[pid] = True
        steps.append({"op": "resetHalf", "p": state.p_allies()})
        for _ in range(EVENTS_PER_HALF):
            roll = rng.random()
            if flag_ids and roll < 0.30:
                flag = rng.choice(flag_ids)
                owner = rng.choice([1, 2, 0, 1, 2])  # 0 = neutralised flag
                state.owners[flag] = owner if owner in (1, 2) else 0
                steps.append({"op": "flag", "flag": flag, "owner": owner,
                              "p": state.p_allies()})
                continue
            pid = rng.choice(list(teams))
            up = roll > 0.75  # ~ 3 frags per spawn, so halves get lopsided
            state.alive[pid] = up
            steps.append({"op": "alive", "player": pid, "up": up,
                          "p": state.p_allies()})
    return {
        "match_id": shape["match_id"],
        "map_name": shape["map_name"],
        "flagCoefficient": 2.0,
        "aliveCoefficient": 1.0,
        "flagCount": flag_count,
        "rosterSize": roster_size,
        "teams": [[pid, team] for pid, team in sorted(teams.items())],
        "steps": steps,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--reports", default=DEFAULT_REPORTS)
    parser.add_argument("--out", type=Path, default=HERE / "golden.json")
    args = parser.parse_args()

    module = load_flag_swing(args.source)
    shapes = match_shapes(args.reports, MATCH_COUNT)
    cases = [
        build_case(module, shapes[0], seed=1, null_flags=False, force_no_flags=False),
        # Second case exercises the owners[None] quirk...
        build_case(module, shapes[1], seed=2, null_flags=True, force_no_flags=False),
        # ...and the third the `len(flag_ids) or 5` fallback: a match whose only
        # flag rows carry no index, so the denominator is 5 while owners[None]
        # still moves the numerator.
        build_case(module, shapes[2], seed=3, null_flags=True, force_no_flags=True),
    ]
    payload = {
        "definition": "flag_swing_v1",
        "definition_version": 1,
        "generator": "make_golden.py",
        "source": str(args.source),
        "note": "p values produced by _HalfState.p_allies from the pipeline source.",
        "cases": cases,
    }
    args.out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    total = sum(len(c["steps"]) for c in cases)
    print(f"wrote {args.out} : {len(cases)} cases, {total} steps, "
          f"{args.out.stat().st_size} bytes")


if __name__ == "__main__":
    main()
