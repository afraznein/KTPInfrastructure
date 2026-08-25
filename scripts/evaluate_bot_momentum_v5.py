#!/usr/bin/env python3
"""Evaluate v5 momentum on SQL bot fixtures without starting MySQL."""

from __future__ import annotations

import argparse
import json
import statistics
import tomllib
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from scripts.accumulation_v3 import load_profile
from scripts.match_readiness import iter_rows
from scripts.momentum_v5 import derive_momentum, render_momentum_svg


TABLES = {"ktp_matches", "ktp_match_players", "ktp_position_samples",
          "ktp_flag_positions", "ktp_flag_state_events", "ktp_flag_captures",
          "hlstats_Events_Frags"}


def _dt(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def evaluate(path: Path, profile: dict, topology: dict) -> dict:
    tables: dict[str, list[dict]] = defaultdict(list)
    for table, row in iter_rows(path, TABLES):
        tables[table].append(row)
    match_id = next(row["match_id"] for row in tables["ktp_matches"] if row.get("match_id"))
    matches = [row for row in tables["ktp_matches"] if row["match_id"] == match_id]
    starts = {int(row["half"]): _dt(row["start_time"]) for row in matches}
    samples = [{"player_id": int(row["player_id"]), "team": int(row["team"]),
                "half": int(row["half"]), "pos_x": float(row["pos_x"]),
                "pos_y": float(row["pos_y"]), "game_time": float(row["game_time"])}
               for row in tables["ktp_position_samples"] if row["match_id"] == match_id]
    votes: dict[tuple[int, int], Counter] = defaultdict(Counter)
    for row in samples:
        votes[(row["half"], row["player_id"])][row["team"]] += 1
    teams = {key: value.most_common(1)[0][0] for key, value in votes.items()}
    names = {}
    for row in tables["ktp_match_players"]:
        if row["match_id"] == match_id:
            names[int(row["player_id"])] = row.get("player_name") or str(row["player_id"])
    players = [{"player_id": player_id, "player_name_at_match": name}
               for player_id, name in sorted(names.items())]
    flags = [{"flag_name": row["flag_name"], "origin_x": float(row["origin_x"]),
              "origin_y": float(row["origin_y"])}
             for row in tables["ktp_flag_positions"] if row["map_name"] == "dod_anzio"]
    frags = []
    for row in tables["hlstats_Events_Frags"]:
        if row["match_id"] != match_id:
            continue
        half, killer, victim = int(row["half"]), int(row["killerId"]), int(row["victimId"])
        frags.append({"event_id": f"frag-{row['id']}", "half": half,
                      "time": (_dt(row["eventTime"]) - starts[half]).total_seconds(),
                      "killer_id": killer, "victim_id": victim,
                      "killer_team": teams.get((half, killer), 0),
                      "victim_team": teams.get((half, victim), 0)})
    grouped: dict[tuple, set[int]] = defaultdict(set)
    for row in tables["ktp_flag_captures"]:
        if row["match_id"] == match_id:
            grouped[(int(row["half"]), row["event_time"], row["team"], row["flag_name"])].add(int(row["player_id"]))
    captures = []
    for index, ((half, event_time, team_name, flag_name), credited) in enumerate(sorted(grouped.items()), 1):
        captures.append({"event_id": f"capture-{index}", "half": half,
                         "time": (_dt(event_time) - starts[half]).total_seconds(),
                         "team": 1 if str(team_name).lower().startswith("all") else 2,
                         "flag_name": flag_name, "credited_player_ids": sorted(credited)})
    states = [{"half": int(row["half"]), "game_time": float(row["game_time"]),
               "flag_name": row["flag_name"], "owner_team": int(row["owner_team"])}
              for row in tables["ktp_flag_state_events"] if row["match_id"] == match_id]
    points, public, _ = derive_momentum(
        players, samples, flags, frags, captures, profile, topology, states
    )
    values = [row["momentum"] for row in public["curve"]]
    return {"fixture": str(path), "match_id": match_id, "players": len(players),
            "samples": len(samples), "frags": len(frags), "captures": len(captures),
            "ownership_coverage_percent": public["ownership_coverage_percent"],
            "curve_min": min(values, default=0), "curve_max": max(values, default=0),
            "episodes": len(public["episodes"]),
            "swing_pool_points": round(sum(row["pool"] for row in public["episodes"]), 2),
            "players_with_points": sum(value > 0 for value in points.values()),
            "maximum_player_points": max(points.values(), default=0), "momentum": public}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixtures", type=Path, nargs="+")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--objectives", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    profile = load_profile(args.profile)
    with args.objectives.open("rb") as source:
        topology = tomllib.load(source)["maps"]["dod_anzio"]
    results = [evaluate(path, profile, topology) for path in args.fixtures]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    safe = [{key: value for key, value in row.items() if key != "momentum"} for row in results]
    (args.output_dir / "results.json").write_text(json.dumps(safe, indent=2) + "\n", encoding="utf-8")
    lines = ["# V5 momentum — five Anzio bot matches", "",
             "Synthetic fixtures validate behavior and bounds, not human calibration.", "",
             "| Match | Frags | Captures | Positions | Ownership | Curve range | Episodes | Pool | Players | Max player |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in results:
        lines.append(f"| `{row['match_id']}` | {row['frags']} | {row['captures']} | {row['samples']} | "
                     f"{row['ownership_coverage_percent']:.1f}% | {row['curve_min']:.1f} to {row['curve_max']:.1f} | "
                     f"{row['episodes']} | {row['swing_pool_points']:.1f} | {row['players_with_points']} | "
                     f"{row['maximum_player_points']:.1f} |")
    pools = [row["swing_pool_points"] for row in results]
    lines += ["", f"Median swing pool: **{statistics.median(pools):.1f}** points; range "
              f"**{min(pools):.1f}–{max(pools):.1f}**.", ""]
    (args.output_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    for index, row in enumerate(results, 1):
        (args.output_dir / f"match-{index:02d}-momentum.svg").write_text(
            render_momentum_svg(row["momentum"], row["match_id"]), encoding="utf-8"
        )
    print(args.output_dir / "REPORT.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
