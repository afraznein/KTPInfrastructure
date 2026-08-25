#!/usr/bin/env python3
"""Compare a series of sanitized v5 match-report bundles.

The input directories must contain report.json, facts.normalized.json, and
report-verification.json. Raw player positions are neither read nor emitted.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.compare_v5_match_reports import GROUPS, _load, _spearman, _summary
except ModuleNotFoundError:  # Direct execution from scripts/.
    from compare_v5_match_reports import GROUPS, _load, _spearman, _summary


def _mean(values: Iterable[float]) -> float:
    rows = list(values)
    return statistics.mean(rows) if rows else 0.0


def _spread(values: Iterable[float]) -> dict[str, float]:
    rows = [float(value) for value in values]
    mean = _mean(rows)
    return {
        "minimum": round(min(rows), 2) if rows else 0.0,
        "mean": round(mean, 2),
        "maximum": round(max(rows), 2) if rows else 0.0,
        "standard_deviation": round(statistics.pstdev(rows), 2) if rows else 0.0,
        "coefficient_of_variation_percent": round(100 * statistics.pstdev(rows) / mean, 2)
        if rows and mean else 0.0,
    }


def _verification_status(bundle: dict[str, Any]) -> str:
    verification = bundle["verification"]
    return str(verification.get("status") or verification.get("result") or "UNKNOWN").upper()


def compare_series(bundles: list[dict[str, Any]]) -> dict[str, Any]:
    if len(bundles) < 2:
        raise ValueError("at least two report bundles are required")
    summaries = [_summary(bundle) for bundle in bundles]
    reports = [bundle["report"] for bundle in bundles]
    maps = sorted({row["map_name"] for row in summaries})
    profiles = sorted({str(report.get("profile")) for report in reports})

    component_spread = {
        group: {
            "points": _spread(row["groups"][group] for row in summaries),
            "share_percent": _spread(row["group_shares_percent"][group] for row in summaries),
        }
        for group in GROUPS
    }
    event_fields = tuple(summaries[0]["events"])
    event_spread = {field: _spread(row["events"][field] for row in summaries) for field in event_fields}

    appearances: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run_number, summary in enumerate(summaries, 1):
        for player in summary["players_table"]:
            appearances[str(player["player_name_at_match"])].append({
                "run": run_number,
                "name": player["player_name_at_match"],
                "rank": int(player["rank"]),
                "rating": float(player["impact_index"]),
                "points_per_minute": float(player["points_per_minute"]),
            })
    player_stability = []
    for player_name, rows in appearances.items():
        if len(rows) != len(summaries):
            continue
        player_stability.append({
            "name": player_name,
            "appearances": len(rows),
            "mean_rank": round(_mean(row["rank"] for row in rows), 2),
            "rank_range": max(row["rank"] for row in rows) - min(row["rank"] for row in rows),
            "mean_rating": round(_mean(row["rating"] for row in rows), 2),
            "rating_standard_deviation": round(statistics.pstdev(row["rating"] for row in rows), 2),
            "mean_points_per_minute": round(_mean(row["points_per_minute"] for row in rows), 2),
        })
    player_stability.sort(key=lambda row: (-row["mean_rating"], row["name"]))

    run_rows = []
    for number, (summary, bundle) in enumerate(zip(summaries, bundles), 1):
        verification = bundle["verification"]
        run_rows.append({
            "run": number,
            "match_id": summary["match_id"],
            "map_name": summary["map_name"],
            "verification": _verification_status(bundle),
            "players": summary["players"],
            "duration_seconds": summary["duration_seconds"],
            "events": summary["events"],
            "match_total_points": summary["match_total_points"],
            "group_shares_percent": summary["group_shares_percent"],
            "rating_distribution": summary["rating_distribution"],
            "top_three_point_share_percent": summary["top_three_point_share_percent"],
            "momentum": summary["momentum"],
            "quality_gates": summary["quality_gates"],
            "private_position_samples": int(
                (verification.get("private_derivation") or {}).get("position_samples") or 0
            ),
        })

    all_players = [player for summary in summaries for player in summary["players_table"]]
    correlations = {}
    rating_values = [float(row["impact_index"]) for row in all_players]
    for name, getter in {
        "kills": lambda row: float(row["kills"]),
        "assists": lambda row: float(row["assists"]),
        "opponent_damage": lambda row: float(row["opponent_damage"]),
        "objectives": lambda row: sum(float(row[key]) for key in GROUPS["objectives"]),
        "life_position": lambda row: float(row["position_points"]),
        "momentum": lambda row: float(row["momentum_points"]),
    }.items():
        correlations[name] = _spearman(rating_values, [getter(row) for row in all_players])

    verification_statuses = [row["verification"] for row in run_rows]
    quality_statuses = [status for summary in summaries for status in summary["quality_gates"].values()]
    quality_counts = {
        status: quality_statuses.count(status) for status in sorted(set(quality_statuses))
    }
    duplicate_match_ids = sorted({
        row["match_id"] for row in run_rows
        if sum(other["match_id"] == row["match_id"] for other in run_rows) > 1
    })
    component_share_max_cv = max(
        values["share_percent"]["coefficient_of_variation_percent"]
        for values in component_spread.values()
    )
    event_max = max(
        event_spread.items(),
        key=lambda item: item[1]["coefficient_of_variation_percent"],
    )
    lessons = [
        {
            "finding": "The sanitized report generator is repeatable across the series.",
            "evidence": f"{verification_statuses.count('PASS')}/{len(run_rows)} report bundles verified PASS.",
            "action": "Keep report verification as a required post-match gate.",
        },
        {
            "finding": "The scoring component mix is stable enough for regression use."
            if component_share_max_cv <= 15 else "At least one scoring component is unstable across runs.",
            "evidence": f"Largest component-share CV was {component_share_max_cv:.2f}%.",
            "action": "Use five-run component-share bands as drift checks; do not tune weights from bots alone.",
        },
        {
            "finding": "Sparse objective/context events vary more than combat volume.",
            "evidence": f"Largest event-count CV was {event_max[1]['coefficient_of_variation_percent']:.2f}% ({event_max[0]}).",
            "action": "Require presence and valid attribution, but calibrate sparse-event weights on real matches.",
        },
        {
            "finding": "The normalized rating center stayed anchored near 100.",
            "evidence": (
                f"Run medians ranged from {min(row['rating_distribution']['median'] for row in run_rows):.2f} "
                f"to {max(row['rating_distribution']['median'] for row in run_rows):.2f}."
            ),
            "action": "Continue showing normalized ratings while retaining raw points and component evidence for audits.",
        },
    ]
    if duplicate_match_ids:
        lessons.append({
            "finding": "Parallel ephemeral jobs can generate the same test match ID.",
            "evidence": "Duplicate ID(s): " + ", ".join(duplicate_match_ids) + ".",
            "action": "Key combined artifacts by workflow run index as well as match ID; keep databases isolated.",
        })
    return {
        "schema_version": 1,
        "privacy": "sanitized_reports_only_no_raw_player_positions",
        "run_count": len(summaries),
        "maps": maps,
        "profiles": profiles,
        "consistent_map": len(maps) == 1,
        "consistent_profile": len(profiles) == 1,
        "all_reports_pass": all(status == "PASS" for status in verification_statuses),
        "no_blocking_quality_gates": not any(status in {"FAIL", "BLOCK"} for status in quality_statuses),
        "quality_gate_counts": quality_counts,
        "duplicate_match_ids": duplicate_match_ids,
        "runs": run_rows,
        "event_spread": event_spread,
        "component_spread": component_spread,
        "match_total_points": _spread(row["match_total_points"] for row in summaries),
        "rating_distribution": {
            field: _spread(row["rating_distribution"][field] for row in summaries)
            for field in ("minimum", "q1", "median", "q3", "maximum")
        },
        "top_three_point_share_percent": _spread(
            row["top_three_point_share_percent"] for row in summaries
        ),
        "pooled_rating_correlations": correlations,
        "stable_players": player_stability,
        "lessons_learned": lessons,
    }


def _fmt(value: Any) -> str:
    return "—" if value is None else str(value)


def render_markdown(data: dict[str, Any]) -> str:
    lines = [
        f"# Lane B v5 report-series comparison — {data['run_count']} matches", "",
        "This comparison uses sanitized report bundles only. It does not read or expose raw player coordinates.", "",
        "## Regression result", "",
        f"- Report verification: **{'PASS' if data['all_reports_pass'] else 'FAIL'}**",
        f"- Blocking quality gates: **{'none' if data['no_blocking_quality_gates'] else 'present'}** "
        f"({', '.join(f'{key}={value}' for key, value in data['quality_gate_counts'].items())})",
        f"- Same map: **{'yes' if data['consistent_map'] else 'no'}** ({', '.join(data['maps'])})",
        f"- Same scoring profile: **{'yes' if data['consistent_profile'] else 'no'}**", "",
        "## Run comparison", "",
        "| Run | Match | Verify | Players | Frags | Assists | Captures | Breaks | Position samples | Raw points | Rating median |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in data["runs"]:
        events = row["events"]
        lines.append(
            f"| {row['run']} | {row['match_id']} | {row['verification']} | {row['players']} | "
            f"{events['enemy_frags']} | {events['assists']} | {events['capture_events']} | "
            f"{events['cap_break_credits']} | {row['private_position_samples']} | "
            f"{row['match_total_points']:.2f} | {row['rating_distribution']['median']:.2f} |"
        )
    lines += ["", "## Variability", "",
              "Coefficient of variation (CV) compares run-to-run spread with the mean.", "",
              "| Measure | Min | Mean | Max | CV |", "|---|---:|---:|---:|---:|"]
    measures = {
        "Enemy frags": data["event_spread"]["enemy_frags"],
        "Assists": data["event_spread"]["assists"],
        "Captures": data["event_spread"]["capture_events"],
        "Cap breaks": data["event_spread"]["cap_break_credits"],
        "Position samples": data["event_spread"]["position_samples"],
        "Raw accumulated points": data["match_total_points"],
        "Top-three point share": data["top_three_point_share_percent"],
    }
    for label, spread in measures.items():
        lines.append(
            f"| {label} | {spread['minimum']:.2f} | {spread['mean']:.2f} | "
            f"{spread['maximum']:.2f} | {spread['coefficient_of_variation_percent']:.2f}% |"
        )
    lines += ["", "## Component balance", "",
              "| Component | Mean share | Min | Max | CV |", "|---|---:|---:|---:|---:|"]
    for group, values in data["component_spread"].items():
        spread = values["share_percent"]
        lines.append(
            f"| {group.replace('_', ' ').title()} | {spread['mean']:.2f}% | "
            f"{spread['minimum']:.2f}% | {spread['maximum']:.2f}% | "
            f"{spread['coefficient_of_variation_percent']:.2f}% |"
        )
    lines += ["", "## Pooled relationship with the final rating", "",
              "Spearman correlations pool all sanitized player rows across the series.", "",
              "| Evidence | Correlation |", "|---|---:|"]
    for key, value in data["pooled_rating_correlations"].items():
        lines.append(f"| {key.replace('_', ' ').title()} | {_fmt(value)} |")
    if data["stable_players"]:
        lines += ["", "## Same-bot stability", "",
                  "| Player | Mean rank | Rank range | Mean rating | Rating SD | Mean points/min |",
                  "|---|---:|---:|---:|---:|---:|"]
        for row in data["stable_players"]:
            lines.append(
                f"| {row['name']} | {row['mean_rank']:.2f} | {row['rank_range']} | "
                f"{row['mean_rating']:.2f} | {row['rating_standard_deviation']:.2f} | "
                f"{row['mean_points_per_minute']:.2f} |"
            )
    lines += ["", "## Lessons learned", ""]
    for index, lesson in enumerate(data["lessons_learned"], 1):
        lines += [
            f"{index}. **{lesson['finding']}** {lesson['evidence']}",
            f"   Action: {lesson['action']}", "",
        ]
    return "\n".join(lines) + "\n"


def render_index(data: dict[str, Any], markdown: str) -> str:
    links = "".join(
        f'<li><a href="run-{row["run"]}/match-report/report.html">Run {row["run"]}: '
        f'{html.escape(str(row["match_id"]))}</a></li>' for row in data["runs"]
    )
    escaped = html.escape(markdown)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lane B v5 five-match comparison</title>
<style>body{{font:16px/1.5 system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#172033}}
a{{color:#0759b6}}pre{{white-space:pre-wrap;background:#f5f7fa;padding:1rem;border-radius:.5rem}}</style>
</head><body><h1>Lane B v5 five-match comparison</h1><ul>{links}</ul><pre>{escaped}</pre></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    data = compare_series([_load(path) for path in args.reports])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    markdown = render_markdown(data)
    (args.output_dir / "series-comparison.json").write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output_dir / "SERIES_COMPARISON.md").write_text(markdown, encoding="utf-8")
    (args.output_dir / "index.html").write_text(render_index(data, markdown), encoding="utf-8")
    return 0 if data["all_reports_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
