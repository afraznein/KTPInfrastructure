#!/usr/bin/env python3
"""Compare legacy, damped/no-penalty, and bounded v3 accumulation models."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from scripts.accumulation_v3 import load_profile, score_match


def _f(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _i(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _aggregate_capture_credits(facts: dict[str, Any]) -> dict[int, int]:
    credits: dict[int, int] = defaultdict(int)
    for capture in facts.get("captures") or []:
        for player_id in set(capture.get("credited_player_ids") or []):
            credits[_i(player_id)] += 1
    return credits


def _aggregate_breaks(facts: dict[str, Any]) -> dict[int, int]:
    breaks: dict[int, int] = defaultdict(int)
    for event in facts.get("cap_breaks") or []:
        breaks[_i(event.get("player_id"))] += 1
    return breaks


def _aggregate_model(
    facts: dict[str, Any], name: str, damage_rate: float, penalties: bool,
) -> dict[str, Any]:
    capture_credits = _aggregate_capture_credits(facts)
    breaks = _aggregate_breaks(facts)
    position = {_i(key): _f(value) for key, value in (facts.get("position_points") or {}).items()}
    players = []
    totals = defaultdict(float)
    for source in facts.get("players") or []:
        player_id = _i(source.get("player_id"))
        components = {
            "kill_points": 100.0 * _i(source.get("kills")),
            "assist_points": 50.0 * _i(source.get("assists")),
            "damage_points": damage_rate * _f(
                source.get("opponent_damage", source.get("damage_dealt"))
            ),
            "capture_points": 100.0 * capture_credits[player_id],
            "break_points": 100.0 * breaks[player_id],
            "penalty_points": (
                -100.0 * _i(source.get("team_kills"))
                - 50.0 * _i(source.get("suicides"))
            ) if penalties else 0.0,
            "position_points": position[player_id],
        }
        for key, value in components.items():
            totals[key] += value
        total = sum(components.values())
        players.append({
            "player_id": player_id,
            "player_name_at_match": source.get("player_name_at_match") or source.get("name"),
            **{key: round(value, 2) or 0.0 for key, value in components.items()},
            "total_points": round(total, 2),
        })
    players.sort(key=lambda row: (-row["total_points"], row["player_name_at_match"] or ""))
    for rank, player in enumerate(players, start=1):
        player["rank"] = rank
    grand_total = sum(totals.values())
    return {
        "name": name,
        "players": players,
        "component_totals": {key: round(value, 2) or 0.0 for key, value in totals.items()},
        "match_total_points": round(grand_total, 2),
    }


def compare_models(facts: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    legacy = _aggregate_model(facts, "legacy_v2", 0.10, True)
    damped = _aggregate_model(facts, "damped_no_penalty", 0.02, False)
    bounded_report = score_match(facts, profile)
    profile_name = str(profile.get("profile", {}).get("name") or "bounded_v3")
    bounded_name = {
        "accumulation_v4_life_impact": "bounded_v4_life_impact",
        "accumulation_v5_momentum": "bounded_v5_momentum",
    }.get(profile_name, "bounded_v3")
    bounded = {
        "name": bounded_name,
        "players": [
            {
                "player_id": row["player_id"],
                "player_name_at_match": row["player_name_at_match"],
                "rank": row["rank"],
                "total_points": row["total_points"],
            }
            for row in bounded_report["players"]
        ],
        "component_totals": bounded_report["component_totals"],
        "match_total_points": bounded_report["match_total_points"],
        "quality_gates": bounded_report["quality_gates"],
    }
    rank_lookup = {
        model["name"]: {row["player_id"]: row["rank"] for row in model["players"]}
        for model in (legacy, damped, bounded)
    }
    comparisons = []
    names = {
        _i(row["player_id"]): row.get("player_name_at_match") or row.get("name")
        for row in facts.get("players") or []
    }
    for player_id, player_name in names.items():
        comparisons.append({
            "player_id": player_id,
            "player_name_at_match": player_name,
            "legacy_rank": rank_lookup["legacy_v2"][player_id],
            "damped_rank": rank_lookup["damped_no_penalty"][player_id],
            "bounded_rank": rank_lookup[bounded_name][player_id],
            "bounded_vs_legacy": rank_lookup["legacy_v2"][player_id]
            - rank_lookup[bounded_name][player_id],
        })
    comparisons.sort(key=lambda row: row["bounded_rank"])
    return {
        "schema_version": 1,
        "match_id": facts["match"]["match_id"],
        "bounded_model": bounded_name,
        "comparison_scope": (
            "All aggregate baselines use the current facts.position_points term so "
            "the comparison isolates event-formula changes; they are not historical reruns."
        ),
        "models": [legacy, damped, bounded],
        "rank_comparison": comparisons,
        "interpretation": {
            "legacy_v2": "Former event weights and penalties, combined with the current positional term.",
            "damped_no_penalty": "No penalties and 0.02 damage, combined with the current positional term.",
            "bounded_v3": "Fixed death/objective pools plus contextual positive bonuses.",
            "bounded_v4_life_impact": "Bounded v3 events plus private-derived per-life territorial impact.",
            "bounded_v5_momentum": "Bounded life impact plus team-momentum swings and a normalized Impact Index.",
        },
    }


def render_markdown(comparison: dict[str, Any]) -> str:
    by_name = {model["name"]: model for model in comparison["models"]}
    bounded_name = comparison.get("bounded_model", "bounded_v3")
    bounded_label = {
        "bounded_v4_life_impact": "Bounded v4 life-impact",
        "bounded_v5_momentum": "Bounded v5 momentum",
    }.get(bounded_name, "Bounded v3")
    lines = [
        f"# Accumulation model comparison — {comparison['match_id']}", "",
        comparison.get("comparison_scope", ""), "",
        f"| Player | Legacy rank | Damped/no-penalty rank | {bounded_label} rank | Change vs legacy |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in comparison["rank_comparison"]:
        change = row["bounded_vs_legacy"]
        rendered = f"+{change}" if change > 0 else str(change)
        lines.append(
            f"| {row['player_name_at_match']} | {row['legacy_rank']} | "
            f"{row['damped_rank']} | {row['bounded_rank']} | {rendered} |"
        )
    lines += ["", "## Match totals", "", "| Model | Total points | Purpose |", "|---|---:|---|"]
    for name in ("legacy_v2", "damped_no_penalty", bounded_name):
        lines.append(
            f"| {name} | {by_name[name]['match_total_points']:.2f} | "
            f"{comparison['interpretation'][name]} |"
        )
    lines += [
        "", "A rank change is diagnostic, not proof that one model is correct. Review "
        "the bounded event ledger and component shares before changing weights.", "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    facts = json.loads(args.facts.read_text(encoding="utf-8"))
    profile = load_profile(args.profile) if args.profile else load_profile()
    comparison = compare_models(facts, profile)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    match_id = comparison["match_id"]
    json_path = args.output_dir / f"{match_id}.comparison.json"
    md_path = args.output_dir / f"{match_id}.comparison.md"
    json_path.write_text(
        json.dumps(comparison, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    md_path.write_text(render_markdown(comparison), encoding="utf-8")
    print(f"comparison: {json_path}")
    print(f"markdown: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
