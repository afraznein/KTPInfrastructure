"""Fit the flag-swing baseline on halves labeled by the team-score ledger.

The driver for scripts/fit_flag_swing.py: winner labels come from
ktp_team_score_observations (engine TeamScore, any producer), match inputs
come through the same analytics queries the report uses, and the result is a
FlagSwingConfig JSON plus a per-half calibration table.

Runs on the data server as the reports user:

    python3 -m scripts.fit_team_score_labels --out build/flag_swing_fit.json

Labels are engine sides per half (1 Allies, 2 Axis), the frame flag owners
and life-boundary sides share; see fit_flag_swing.extract_half_samples.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from scripts.fit_flag_swing import (_sigmoid, extract_half_samples, fit_by_map,
                                    fit_logistic)
from scripts.report_scope import OFFICIAL_MATCH_TYPES

REPO = Path(__file__).resolve().parents[1]

LEDGER_FINALS_SQL = """
SELECT match_id, map_name, match_type, half, allies_team_id, axis_team_id,
       allies_score, axis_score, CAST(tick_seconds AS CHAR) AS tick_seconds,
       event_sequence
FROM ktp_team_score_observations
WHERE observation_kind = 'final' AND match_type IN ({types})
ORDER BY match_id, half, tick_seconds, event_sequence
"""


def half_winners(finals: list[dict[str, Any]]) -> dict[str, dict[int, int]]:
    """match_id -> half -> winning ENGINE side, from cumulative closes.

    A half's close is its last final row; points in a half are its close
    minus the previous close, per roster slot (in_game_result's rule).
    Draws and matches with a gap in their half sequence yield no label.
    """
    closes: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for row in finals:  # ordered by tick, so the last one per half wins
        closes[str(row["match_id"])][int(row["half"])] = row
    winners: dict[str, dict[int, int]] = {}
    for match_id, by_half in closes.items():
        halves = sorted(by_half)
        if halves != list(range(1, len(halves) + 1)):
            continue
        carried = {1: 0, 2: 0}
        for half in halves:
            row = by_half[half]
            allies_slot, axis_slot = int(row["allies_team_id"]), int(row["axis_team_id"])
            if {allies_slot, axis_slot} != {1, 2}:
                break
            close = {allies_slot: int(row["allies_score"]), axis_slot: int(row["axis_score"])}
            allies_points = close[allies_slot] - carried[allies_slot]
            axis_points = close[axis_slot] - carried[axis_slot]
            carried = close
            if allies_points != axis_points:
                winners.setdefault(match_id, {})[half] = 1 if allies_points > axis_points else 2
    return winners


def load_inputs(ma, db, match_id: str, sources: dict[str, bool]) -> dict[str, Any] | None:
    """The four inputs flag_swing consumes, via the report's own queries."""
    if not (sources.get("flag_ownership") and sources.get("life_boundaries")
            and sources.get("frag_context") and sources.get("frag_event_clock")):
        return None
    return {
        "flag_states": ma.query_rows(db, "flag_state_timeline_fact.sql", match_id, sources),
        "frags": ma.query_rows(db, "frag_context_fact.sql", match_id, sources),
        "life_boundaries": ma.query_rows(db, "life_boundary_fact.sql", match_id, sources),
        "roster": ma.query_rows(db, "player_match_fact.sql", match_id, sources),
    }


def fit_labeled_halves(
    winners: dict[str, dict[int, int]],
    inputs_for: Callable[[str], dict[str, Any] | None],
    spawn_owners_for: Callable[[str], dict[int, int]],
    map_names: dict[str, str],
) -> dict[str, Any]:
    samples: list[tuple[float, float, int]] = []
    table: list[dict[str, Any]] = []
    # Kept per map AND per half: the league plays one map a week, so the map
    # is the natural unit of a fit, and shrinkage weighs halves not samples.
    halves_by_map: dict[str, list[list[tuple[float, float, int]]]] = defaultdict(list)
    for match_id in sorted(winners):
        inputs = inputs_for(match_id)
        if inputs is None or not inputs["flag_states"] or not inputs["roster"]:
            table.append({"match_id": match_id, "status": "no-inputs"})
            continue
        initial = spawn_owners_for(map_names.get(match_id, ""))
        for half, side in sorted(winners[match_id].items()):
            half_samples = extract_half_samples(
                inputs["flag_states"], inputs["frags"], inputs["life_boundaries"],
                inputs["roster"], half, side, initial_owners=initial)
            samples += half_samples
            if half_samples:
                halves_by_map[map_names.get(match_id, "")].append(half_samples)
            table.append({"match_id": match_id, "half": half, "winner_side": side,
                          "samples": len(half_samples),
                          "final_flag_term": round(half_samples[-1][0], 3) if half_samples else None,
                          "final_alive_term": round(half_samples[-1][1], 3) if half_samples else None})
    fitted = fit_logistic(samples, halves=sum(1 for r in table if r.get("samples")))
    # Calibration check: does the fitted model's read at the last event of
    # each half point at the side that actually won it?
    agree = 0
    for row in table:
        if not row.get("samples"):
            continue
        p = _sigmoid(fitted.flag_coefficient * row["final_flag_term"]
                     + fitted.alive_coefficient * row["final_alive_term"])
        row["fitted_p_allies_at_end"] = round(p, 3)
        row["end_agrees_with_label"] = (p > 0.5) == (row["winner_side"] == 1)
        agree += row["end_agrees_with_label"]
    labeled = sum(1 for r in table if r.get("samples"))
    per_map: list[dict[str, Any]] = []
    if halves_by_map:
        _pooled, map_fits = fit_by_map(dict(halves_by_map))
        per_map = [asdict(m) for m in map_fits]
    return {
        "config": json.loads(fitted.as_config_json()),
        "fit": asdict(fitted),
        # Paste into flag_swing.MAP_COEFFICIENTS. Shrunk toward the pooled fit,
        # so a map that has not earned its distance stays at the league value.
        "map_coefficients": {m["map_name"]: [round(m["flag_coefficient"], 4),
                                             round(m["alive_coefficient"], 4)]
                             for m in per_map},
        "per_map": per_map,
        "halves_labeled": labeled,
        "halves_end_state_agrees": agree,
        "halves": table,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path, default=REPO)
    ap.add_argument("--match-types", default=",".join(map(str, OFFICIAL_MATCH_TYPES)),
                    help="ktp_team_score_observations.match_type values to label from")
    ap.add_argument("--out", type=Path, default=None, help="write the fit JSON here")
    args = ap.parse_args(argv)
    from scripts.report_service import LocalMysql, load_match_analytics  # Linux-only (pwd)
    ma = load_match_analytics(args.repo)
    db = LocalMysql()
    types = ", ".join(str(int(t)) for t in args.match_types.split(","))
    finals = ma.tsv_rows(db.sql(LEDGER_FINALS_SQL.format(types=types)))
    winners = half_winners(finals)
    map_names = {str(r["match_id"]): str(r["map_name"]) for r in finals}
    sources = ma.source_capabilities(db)
    result = fit_labeled_halves(
        winners, lambda mid: load_inputs(ma, db, mid, sources),
        lambda map_name: ma.load_spawn_ownership(ma.DEFAULT_SPAWN_OWNERSHIP, map_name),
        map_names)
    for row in result["halves"]:
        print(json.dumps(row))
    print(f"labeled halves: {result['halves_labeled']}; end state agrees: "
          f"{result['halves_end_state_agrees']}; samples: {result['fit']['samples']}; "
          f"log_loss: {result['fit']['log_loss']:.4f}")
    print(json.dumps(result["config"], indent=2))
    if args.out:
        args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
