#!/usr/bin/env python3
"""Render aggregate flag-control intervals and a reviewed map-config draft."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import match_analytics as analytics  # noqa: E402
from tests.e2e_stats.ephemeral_mysql import EphemeralMysql  # noqa: E402


def summarize_intervals(
    states: list[dict[str, Any]], half_ends: dict[int, float]
) -> list[dict[str, Any]]:
    """Aggregate owner durations from ordered change events; no player data."""
    timelines: dict[tuple[int, int, str], list[tuple[float, int]]] = defaultdict(list)
    for row in states:
        key = (int(row["half"]), int(row["flag_index"]), str(row["flag_name"] or ""))
        timelines[key].append((float(row["game_time"]), int(row["owner_team"])))

    result: list[dict[str, Any]] = []
    for (half, flag_index, flag_name), events in sorted(timelines.items()):
        events.sort()
        end = float(half_ends.get(half, events[-1][0]))
        durations = {0: 0.0, 1: 0.0, 2: 0.0}
        for index, (start, owner) in enumerate(events):
            stop = events[index + 1][0] if index + 1 < len(events) else end
            durations[owner] += max(0.0, stop - start)
        observed = sum(durations.values())
        result.append({
            "half": half,
            "flag_index": flag_index,
            "flag_name": flag_name,
            "observed_seconds": round(observed, 2),
            "neutral_seconds": round(durations[0], 2),
            "allies_seconds": round(durations[1], 2),
            "axis_seconds": round(durations[2], 2),
            "allies_share": round(durations[1] / observed, 4) if observed else None,
            "axis_share": round(durations[2] / observed, 4) if observed else None,
        })
    return result


def render_report(
    match_id: str,
    map_name: str,
    flags: list[dict[str, Any]],
    states: list[dict[str, Any]],
    intervals: list[dict[str, Any]],
) -> str:
    lines = [
        f"# Flag ownership — {match_id}", "",
        "Aggregate map/flag output only. No player positions or personal heatmaps are included.", "",
        "## Canonical flag catalog", "",
        "| Index | Flag | X | Y |",
        "|---:|---|---:|---:|",
    ]
    for flag in flags:
        lines.append(
            f"| {flag['flag_index']} | {flag['flag_name']} | "
            f"{flag['origin_x']} | {flag['origin_y']} |"
        )

    lines += ["", "## Control intervals", ""]
    if not states:
        lines.append("No `ktp_flag_state_events` rows exist for this match.")
    else:
        lines += [
            "| Half | Flag | Observed s | Neutral s | Allies s | Axis s | Allies % | Axis % |",
            "|---:|---|---:|---:|---:|---:|---:|---:|",
        ]
        for row in intervals:
            allies = "—" if row["allies_share"] is None else f"{100 * row['allies_share']:.1f}%"
            axis = "—" if row["axis_share"] is None else f"{100 * row['axis_share']:.1f}%"
            lines.append(
                f"| {row['half']} | {row['flag_name']} | {row['observed_seconds']:.2f} | "
                f"{row['neutral_seconds']:.2f} | {row['allies_seconds']:.2f} | "
                f"{row['axis_seconds']:.2f} | {allies} | {axis} |"
            )

    lines += ["", "## Map configuration draft", "", "```toml"]
    lines.append(f"[maps.{map_name}.team1_flag_multipliers]")
    for flag in flags:
        lines.append(f"{json.dumps(str(flag['flag_name']))} = 1.00  # review")
    lines.append("")
    lines.append(f"[maps.{map_name}.team2_flag_multipliers]")
    for flag in flags:
        lines.append(f"{json.dumps(str(flag['flag_name']))} = 1.00  # review")
    lines += ["```", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--match-id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    with EphemeralMysql.start() as db:
        analytics.load_fixture(db, args.fixture)
        match_ids = analytics.discover_match_ids(db)
        match_id = args.match_id or (match_ids[0] if len(match_ids) == 1 else None)
        if match_id is None:
            raise SystemExit("fixture has multiple matches; pass --match-id")
        match_sql = analytics.sql_literal(match_id)
        match = analytics.tsv_rows(db.sql(f"""
SELECT MAX(server_id) AS server_id, MAX(map_name) AS map_name
FROM ktp_matches WHERE match_id = {match_sql}
"""))[0]
        map_name = str(match["map_name"] or "")
        map_sql = analytics.sql_literal(map_name)
        flags = analytics.tsv_rows(db.sql(f"""
SELECT flag_index, flag_name, origin_x, origin_y
FROM ktp_flag_positions
WHERE server_id = {int(match['server_id'])} AND map_name = {map_sql}
ORDER BY flag_index
"""))
        sources = analytics.source_capabilities(db)
        states = []
        if sources.get("flag_ownership"):
            states = analytics.tsv_rows(db.sql(f"""
SELECT half, flag_index, flag_name, owner_team, game_time
FROM ktp_flag_state_events
WHERE match_id = {match_sql} AND half > 0
ORDER BY half, flag_index, game_time, id
"""))
        half_rows = analytics.tsv_rows(db.sql(f"""
SELECT half, MAX(game_time) AS end_game_time
FROM ktp_position_samples
WHERE match_id = {match_sql} AND half > 0 GROUP BY half
"""))
        half_ends = {int(row["half"]): float(row["end_game_time"])
                     for row in half_rows}

    report = render_report(
        match_id, map_name, flags, states, summarize_intervals(states, half_ends)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
