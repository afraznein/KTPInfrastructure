#!/usr/bin/env python3
"""Compare two sanitized v5 match-report bundles without private positions."""

from __future__ import annotations

import argparse
import html
import json
import math
import statistics
from pathlib import Path
from typing import Any


GROUPS = {
    "bounded_combat": ("combat_finisher_points", "combat_damage_share_points",
                       "fallback_assist_points", "fallback_damage_points"),
    "streak_context": ("streak_points", "shutdown_points", "fast_chain_points"),
    "objectives": ("capture_points", "conversion_points", "cap_break_points"),
    "life_position": ("position_points",),
    "momentum": ("momentum_points",),
}


def _load(folder: Path) -> dict[str, Any]:
    return {
        "report": json.loads((folder / "report.json").read_text(encoding="utf-8")),
        "facts": json.loads((folder / "facts.normalized.json").read_text(encoding="utf-8")),
        "verification": json.loads(
            (folder / "report-verification.json").read_text(encoding="utf-8")
        ),
    }


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * fraction
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _ranks(values: list[float]) -> list[float]:
    result = [0.0] * len(values)
    order = sorted(range(len(values)), key=lambda index: values[index])
    cursor = 0
    while cursor < len(order):
        end = cursor + 1
        while end < len(order) and values[order[end]] == values[order[cursor]]:
            end += 1
        rank = (cursor + 1 + end) / 2.0
        for index in order[cursor:end]:
            result[index] = rank
        cursor = end
    return result


def _spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) < 3 or len(left) != len(right):
        return None
    x, y = _ranks(left), _ranks(right)
    x_mean, y_mean = statistics.mean(x), statistics.mean(y)
    numerator = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y))
    denominator = math.sqrt(
        sum((a - x_mean) ** 2 for a in x) * sum((b - y_mean) ** 2 for b in y)
    )
    return round(numerator / denominator, 3) if denominator else None


def _summary(bundle: dict[str, Any]) -> dict[str, Any]:
    report, facts, verification = bundle["report"], bundle["facts"], bundle["verification"]
    players = report["players"]
    ratings = [float(row["impact_index"]) for row in players if row.get("impact_index") is not None]
    duration = float(report["match"]["duration_seconds"])
    reference_minimum = float(report["impact_index"]["reference_minimum_observed_seconds"])
    reference_players = [row for row in players if float(row.get("observed_seconds") or 0) >= reference_minimum]
    groups = {
        name: round(sum(float(report["component_totals"].get(key) or 0) for key in keys), 2)
        for name, keys in GROUPS.items()
    }
    group_shares = {
        name: round(100 * value / float(report["match_total_points"]), 2)
        for name, value in groups.items()
    }
    fields = {
        "kills": lambda row: float(row["kills"]),
        "assists": lambda row: float(row["assists"]),
        "opponent_damage": lambda row: float(row["opponent_damage"]),
        "streak_context": lambda row: sum(float(row[key]) for key in GROUPS["streak_context"]),
        "objectives": lambda row: sum(float(row[key]) for key in GROUPS["objectives"]),
        "life_position": lambda row: float(row["position_points"]),
        "momentum": lambda row: float(row["momentum_points"]),
    }
    rating_values = [float(row["impact_index"]) for row in reference_players]
    correlations = {
        name: _spearman(rating_values, [getter(row) for row in reference_players])
        for name, getter in fields.items()
    }
    momentum = report.get("momentum") or {}
    episodes = momentum.get("episodes") or []
    return {
        "match_id": report["match"]["match_id"],
        "map_name": report["match"]["map_name"],
        "duration_seconds": duration,
        "players": len(players),
        "reference_players": len(reference_players),
        "partial_appearances": [
            {"player_id": row["player_id"], "name": row["player_name_at_match"],
             "minutes": round(float(row.get("observed_seconds") or 0) / 60, 1),
             "participation_percent": row.get("participation_percent"),
             "rating": row.get("impact_index")}
            for row in players if float(row.get("participation_percent") or 0) < 90
        ],
        "events": {
            "enemy_frags": len(facts.get("frags") or []),
            "damage_rows": len(facts.get("damage_events") or []),
            "assists": sum(int(row.get("assists") or 0) for row in facts["players"]),
            "capture_events": len(facts.get("captures") or []),
            "capture_credits": sum(len(row.get("credited_player_ids") or []) for row in facts.get("captures") or []),
            "cap_break_credits": len(facts.get("cap_breaks") or []),
            "position_samples": int(
                (verification.get("private_derivation") or {}).get("position_samples") or 0
            ),
        },
        "match_total_points": report["match_total_points"],
        "groups": groups,
        "group_shares_percent": group_shares,
        "rating_distribution": {
            "minimum": round(min(ratings), 2), "q1": round(_percentile(ratings, 0.25), 2),
            "median": round(statistics.median(ratings), 2),
            "q3": round(_percentile(ratings, 0.75), 2), "maximum": round(max(ratings), 2),
        },
        "reference_points_per_minute": report["impact_index"]["reference_points_per_minute"],
        "reference_log_scale": report["impact_index"]["reference_log_scale"],
        "top_three_point_share_percent": round(
            100 * sum(float(row["total_points"]) for row in players[:3])
            / float(report["match_total_points"]), 2
        ),
        "correlations_reference_players": correlations,
        "momentum": {
            "ownership_coverage_percent": momentum.get("ownership_coverage_percent"),
            "episodes": len(episodes),
            "episode_pool_points": round(sum(float(row.get("pool") or 0) for row in episodes), 2),
            "largest_swing": round(max((float(row.get("swing") or 0) for row in episodes), default=0), 2),
        },
        "quality_gates": {key: value["status"] for key, value in report["quality_gates"].items()},
        "players_table": players,
    }


def compare(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    left, right = _summary(baseline), _summary(candidate)
    left_by_id = {row["player_id"]: row for row in left["players_table"]}
    right_by_id = {row["player_id"]: row for row in right["players_table"]}
    common = []
    for player_id in sorted(left_by_id.keys() & right_by_id.keys()):
        old, new = left_by_id[player_id], right_by_id[player_id]
        common.append({
            "player_id": player_id, "name": new["player_name_at_match"],
            "baseline_rank": old["rank"], "candidate_rank": new["rank"],
            "baseline_rating": old["impact_index"], "candidate_rating": new["impact_index"],
            "rating_change": round(float(new["impact_index"]) - float(old["impact_index"]), 2),
            "baseline_ppm": old["points_per_minute"], "candidate_ppm": new["points_per_minute"],
        })
    event_delta = {
        key: {
            "absolute": right["events"][key] - left["events"][key],
            "percent": round(100 * (right["events"][key] / left["events"][key] - 1), 2)
            if left["events"][key] else None,
        }
        for key in left["events"]
    }
    group_share_delta = {
        key: round(right["group_shares_percent"][key] - left["group_shares_percent"][key], 2)
        for key in GROUPS
    }
    return {
        "schema_version": 1,
        "privacy": "sanitized_reports_only_no_raw_player_positions",
        "baseline": left, "candidate": right,
        "event_delta": event_delta,
        "group_share_delta_percentage_points": group_share_delta,
        "common_players": common,
        "adjustments_applied": [
            "derive cap-break half from the match time window for production-schema compatibility",
            "derive per-player participation by per-half first/last position sample",
            "exclude appearances under 50% of match duration from the provisional reference distribution",
            "bound the display rating to 50-150 and floor narrow-match log dispersion at 0.30",
            "require a complete two-team ownership partition in every half before capout/last-flag scoring",
            "warn, rather than claim full momentum coverage, when territory ownership is incomplete",
            "surface NULL or inconsistent match classification as a quality warning",
        ],
    }


def _markdown(data: dict[str, Any]) -> str:
    a, b = data["baseline"], data["candidate"]
    lines = [
        f"# Denver 4 v5 deep comparison — {a['match_id']} vs {b['match_id']}", "",
        "Both bundles were regenerated with the same scoring profile and code. Raw individual positions are not embedded.", "",
        "## Match-level comparison", "",
        "| Metric | Earlier match | New match | Change |", "|---|---:|---:|---:|",
    ]
    labels = {
        "enemy_frags": "Enemy frags", "damage_rows": "Opponent-damage contribution rows", "assists": "Assists",
        "capture_events": "Unique captures", "capture_credits": "Capture credits",
        "cap_break_credits": "Cap-break credits", "position_samples": "Position samples",
    }
    for key, label in labels.items():
        delta = data["event_delta"][key]
        pct = "—" if delta["percent"] is None else f"{delta['percent']:+.1f}%"
        lines.append(f"| {label} | {a['events'][key]} | {b['events'][key]} | {pct} |")
    lines += [
        f"| Rostered appearances | {a['players']} | {b['players']} | {b['players']-a['players']:+d} |",
        f"| Raw accumulated points | {a['match_total_points']:.2f} | {b['match_total_points']:.2f} | {(b['match_total_points']/a['match_total_points']-1)*100:+.1f}% |",
        "", "## Component balance", "",
        "| Group | Earlier share | New share | Delta |", "|---|---:|---:|---:|",
    ]
    for key in GROUPS:
        lines.append(
            f"| {key.replace('_', ' ').title()} | {a['group_shares_percent'][key]:.2f}% | "
            f"{b['group_shares_percent'][key]:.2f}% | "
            f"{data['group_share_delta_percentage_points'][key]:+.2f} pp |"
        )
    lines += [
        "", "The component mix is stable across the two matches; no raw scoring weight was changed from this two-match sample.",
        "", "## Rating behavior", "",
        "| Distribution | Earlier | New |", "|---|---:|---:|",
    ]
    for key in ("minimum", "q1", "median", "q3", "maximum"):
        lines.append(f"| {key.title()} | {a['rating_distribution'][key]:.2f} | {b['rating_distribution'][key]:.2f} |")
    lines += [
        f"| Reference raw points/min | {a['reference_points_per_minute']:.2f} | {b['reference_points_per_minute']:.2f} |",
        f"| Robust log scale | {a['reference_log_scale']:.2f} | {b['reference_log_scale']:.2f} |",
        f"| Top-three share of raw points | {a['top_three_point_share_percent']:.2f}% | {b['top_three_point_share_percent']:.2f}% |",
        "", "The rating is match-relative shadow output. Raw points/minute is the safer cross-match comparison until a qualified corpus reference replaces the per-match median.",
        "", "## What drove the rating", "",
        "Spearman rank correlation uses only appearances eligible for the provisional reference distribution.", "",
        "| Evidence | Earlier | New |", "|---|---:|---:|",
    ]
    for key in ("kills", "assists", "opponent_damage", "streak_context", "objectives", "life_position", "momentum"):
        old = a["correlations_reference_players"][key]
        new = b["correlations_reference_players"][key]
        lines.append(f"| {key.replace('_', ' ').title()} | {old:.3f} | {new:.3f} |")
    lines += [
        "", "The first match was strongly kill/streak-led. The second remained combat-led but assists, damage contribution, and life-position evidence aligned more strongly with the final ordering. Objective correlation stayed near zero because fixed capture/break pools are sparse and distributed across otherwise different performances; their total share rose without dominating the table.",
        "", "## New match scoreboard", "",
        "| Rank | Player | Rating | Minutes | Raw | Pts/min | K/D/A | Position | Momentum |", "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in b["players_table"]:
        lines.append(
            f"| {row['rank']} | {row['player_name_at_match']} | {row['impact_index']:.2f} | "
            f"{row['observed_seconds']/60:.1f} | {row['total_points']:.2f} | "
            f"{row['points_per_minute']:.2f} | {row['kills']}/{row['deaths']}/{row['assists']} | "
            f"{row['position_points']:.2f} | {row['momentum_points']:.2f} |"
        )
    if b["partial_appearances"]:
        lines += ["", "### Partial appearances", ""]
        for row in b["partial_appearances"]:
            lines.append(
                f"- {row['name']}: {row['minutes']:.1f} minutes "
                f"({row['participation_percent']:.1f}% participation), rating {row['rating']:.2f}."
            )
        lines += [
            "", "Denver replaced one player during the first half. The outgoing appearance remains visible but does not set the match reference; the incoming player's rate-based rank remains visible with minutes attached. Neither receives a penalty.",
        ]
    lines += ["", "## Repeat-player comparison", "",
              "| Player | Earlier rank/rating | New rank/rating | Rating delta | Raw pts/min change |",
              "|---|---:|---:|---:|---:|"]
    for row in data["common_players"]:
        lines.append(
            f"| {row['name']} | {row['baseline_rank']} / {row['baseline_rating']:.2f} | "
            f"{row['candidate_rank']} / {row['candidate_rating']:.2f} | {row['rating_change']:+.2f} | "
            f"{row['candidate_ppm']-row['baseline_ppm']:+.2f} |"
        )
    lines += ["", "## Momentum and evidence", "",
              "| Metric | Earlier | New |", "|---|---:|---:|",
              f"| Ownership coverage | {a['momentum']['ownership_coverage_percent']:.2f}% | {b['momentum']['ownership_coverage_percent']:.2f}% |",
              f"| Swing episodes | {a['momentum']['episodes']} | {b['momentum']['episodes']} |",
              f"| Bounded episode pools | {a['momentum']['episode_pool_points']:.2f} | {b['momentum']['episode_pool_points']:.2f} |",
              f"| Largest swing | {a['momentum']['largest_swing']:.2f} | {b['momentum']['largest_swing']:.2f} |",
              "", "Momentum remains useful for field position, combat, manpower, and swing attribution, but Thunder2 territory ownership is sparse. The gate is therefore WARN, and capout/last-flag bonuses remain disabled.",
              "", "## Adjustments made", ""]
    lines.extend(f"- {item}." for item in data["adjustments_applied"])
    lines += ["", "## Remaining blockers", "",
              "- Both live `.12man` halves are still `match_type = NULL`; fix/validate classification before retention automation.",
              "- Static Thunder2 flag coordinates came from the curated competitive-map catalog because Denver 4 has no live `ktp_flag_positions` rows.",
              "- Life boundaries remain reconstructed; validate canonical life events after their producer is deployed.",
              "- Do not calibrate cross-match rating weights from two human matches; accumulate a larger qualified corpus first.", ""]
    return "\n".join(lines)


def _html(data: dict[str, Any], markdown: str) -> str:
    b = data["candidate"]
    rows = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in (
            row["rank"], row["player_name_at_match"], f"{row['impact_index']:.2f}",
            f"{row['observed_seconds']/60:.1f}", f"{row['total_points']:.2f}",
            f"{row['points_per_minute']:.2f}", f"{row['kills']}/{row['deaths']}/{row['assists']}",
            f"{row['position_points']:.2f}", f"{row['momentum_points']:.2f}",
        )) + "</tr>" for row in b["players_table"]
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Denver v5 comparison</title><style>body{{font:15px/1.45 system-ui;background:#101418;color:#eef4f7;margin:auto;max-width:1200px;padding:28px}}a{{color:#e8b44d}}table{{border-collapse:collapse;width:100%;background:#192127}}th,td{{padding:8px;border-bottom:1px solid #31404a;text-align:left}}pre{{white-space:pre-wrap;background:#192127;padding:18px;border-radius:8px}}</style></head><body><h1>Denver 4 v5 match comparison</h1><p><a href="1.3-6574-DEN4/report.html">Earlier report</a> · <a href="1.3-6606-DEN4/report.html">New report</a> · <a href="DEEP_COMPARISON.md">Markdown analysis</a></p><h2>New match scoreboard</h2><table><thead><tr><th>#</th><th>Player</th><th>Rating</th><th>Minutes</th><th>Raw</th><th>Pts/min</th><th>K/D/A</th><th>Position</th><th>Momentum</th></tr></thead><tbody>{rows}</tbody></table><h2>Full analysis</h2><pre>{html.escape(markdown)}</pre></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    data = compare(_load(args.baseline), _load(args.candidate))
    markdown = _markdown(data)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "deep-comparison.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (args.output_dir / "DEEP_COMPARISON.md").write_text(markdown, encoding="utf-8")
    (args.output_dir / "index.html").write_text(_html(data, markdown), encoding="utf-8")
    (args.output_dir / "README.md").write_text(
        "# Denver 4 comparison bundle\n\n"
        "- [Open the comparison UI](index.html)\n"
        "- [Read the deep comparison](DEEP_COMPARISON.md)\n"
        f"- [Earlier match report]({data['baseline']['match_id']}/report.html)\n"
        f"- [New match report]({data['candidate']['match_id']}/report.html)\n"
        "- [Machine-readable comparison](deep-comparison.json)\n\n"
        "All public files exclude raw individual coordinates and movement paths.\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
