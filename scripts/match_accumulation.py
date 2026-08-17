#!/usr/bin/env python3
"""Generate shadow accumulation points with private positional working data.

The shareable JSON/Markdown contains only derived positional points. Individual
heatmap cells, objective-distance observations, and flag-level movement data
are written to a separate explicitly private directory and never embedded in
the shareable payload.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tomllib
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import match_analytics as analytics  # noqa: E402
from tests.e2e_stats.ephemeral_mysql import EphemeralMysql  # noqa: E402


REPO = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = REPO / "config" / "analytics" / "accumulation_v0.toml"
PRIVATE_KEYS = {
    "heatmap", "heatmap_cells", "cell_x", "cell_y", "pos_x", "pos_y", "pos_z",
    "nearest_flag", "nearest_flag_index", "nearest_flag_distance",
    "flag_breakdown", "position_samples", "sample_count", "observed_seconds",
    "within_radius_samples", "raw_position_points", "awarded_position_points",
    "raw_points",
}


def load_profile(path: Path) -> dict[str, Any]:
    with path.open("rb") as source:
        profile = tomllib.load(source)
    for section in ("profile", "events", "position"):
        if section not in profile:
            raise ValueError(f"accumulation profile is missing [{section}]")
    return profile


def _query(db: EphemeralMysql, sql: str) -> list[dict[str, Any]]:
    return analytics.tsv_rows(db.sql(sql))


def load_position_facts(
    db: EphemeralMysql, match_id: str, server_id: int, map_name: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    match = analytics.sql_literal(match_id)
    map_value = analytics.sql_literal(map_name)
    samples = _query(db, f"""
SELECT id, player_id, team, half, pos_x, pos_y, pos_z, game_time, event_time
FROM ktp_position_samples
WHERE match_id = {match} AND half > 0
ORDER BY half, game_time, id
""")
    flags = _query(db, f"""
SELECT flag_index, flag_name, origin_x, origin_y
FROM ktp_flag_positions
WHERE server_id = {int(server_id)} AND map_name = {map_value}
ORDER BY flag_index
""")
    return samples, flags


def derive_private_positions(
    players: list[dict[str, Any]],
    samples: list[dict[str, Any]],
    flags: list[dict[str, Any]],
    profile: dict[str, Any],
) -> tuple[dict[int, float], list[dict[str, Any]]]:
    """Return player positional points and private heatmap working records."""
    cfg = profile["position"]
    interval = float(cfg["sample_seconds"])
    radius = float(cfg["objective_radius_units"])
    rate = float(cfg["points_per_second_at_flag"])
    grid = int(cfg["grid_size_units"])
    cap_per_half = float(cfg["max_points_per_half"])
    by_player: dict[int, dict[str, Any]] = {}
    player_context = {int(p["player_id"]): p for p in players}

    for sample in samples:
        player_id = int(sample["player_id"])
        player = player_context.get(player_id)
        if player is None:
            continue
        x, y = int(sample["pos_x"]), int(sample["pos_y"])
        nearest = None
        nearest_distance = None
        for flag in flags:
            distance = math.hypot(x - int(flag["origin_x"]), y - int(flag["origin_y"]))
            if nearest_distance is None or distance < nearest_distance:
                nearest, nearest_distance = flag, distance
        state = by_player.setdefault(player_id, {
            "player_id": player_id,
            "steam_id": player.get("steam_id"),
            "player_name_at_match": player.get("player_name_at_match"),
            "team": player.get("team"),
            "sample_count": 0,
            "observed_seconds": 0.0,
            "raw_position_points": 0.0,
            "heatmap": defaultdict(lambda: {"samples": 0, "seconds": 0.0}),
            "flag_breakdown": defaultdict(lambda: {
                "samples": 0, "within_radius_samples": 0,
                "observed_seconds": 0.0, "raw_points": 0.0,
            }),
        })
        state["sample_count"] += 1
        state["observed_seconds"] += interval
        cell = state["heatmap"][(x // grid, y // grid)]
        cell["samples"] += 1
        cell["seconds"] += interval
        if nearest is not None and nearest_distance is not None:
            flag_state = state["flag_breakdown"][(
                int(nearest["flag_index"]), str(nearest["flag_name"])
            )]
            flag_state["samples"] += 1
            flag_state["observed_seconds"] += interval
            if nearest_distance <= radius:
                proximity = 1.0 - (nearest_distance / radius)
                points = interval * rate * proximity
                flag_state["within_radius_samples"] += 1
                flag_state["raw_points"] += points
                state["raw_position_points"] += points

    points_by_player: dict[int, float] = {}
    private_players: list[dict[str, Any]] = []
    for player_id, state in sorted(by_player.items()):
        halves = max(1, int(player_context[player_id].get("halves_played") or 1))
        awarded = min(state["raw_position_points"], cap_per_half * halves)
        points_by_player[player_id] = round(awarded, 2)
        heatmap = [
            {"cell_x": cell_x, "cell_y": cell_y, **values}
            for (cell_x, cell_y), values in sorted(state["heatmap"].items())
        ]
        flag_breakdown = [
            {
                "nearest_flag_index": index,
                "nearest_flag": name,
                **{key: round(value, 3) if isinstance(value, float) else value
                   for key, value in values.items()},
            }
            for (index, name), values in sorted(state["flag_breakdown"].items())
        ]
        private_players.append({
            key: round(value, 3) if isinstance(value, float) else value
            for key, value in state.items()
            if key not in ("heatmap", "flag_breakdown")
        } | {
            "awarded_position_points": round(awarded, 2),
            "heatmap_cells": heatmap,
            "flag_breakdown": flag_breakdown,
        })
    return points_by_player, private_players


def accumulate_player(
    player: dict[str, Any], position_points: float, profile: dict[str, Any]
) -> dict[str, Any]:
    weights = profile["events"]
    components = {
        "kill_points": player.get("kills", 0) * float(weights["kill"]),
        "assist_points": player.get("assists", 0) * float(weights["assist"]),
        "damage_points": player.get("damage_dealt", 0) * float(weights["damage"]),
        "capture_points": player.get("capture_credits", 0) * float(weights["capture_credit"]),
        "break_points": player.get("cap_breaks", 0) * float(weights["cap_break"]),
        "team_kill_points": player.get("team_kills", 0) * float(weights["team_kill"]),
        "suicide_points": player.get("suicides", 0) * float(weights["suicide"]),
        "position_points": position_points,
    }
    rounded = {key: round(value, 2) or 0.0 for key, value in components.items()}
    return {
        "player_id": player["player_id"],
        "steam_id": player.get("steam_id"),
        "player_name_at_match": player.get("player_name_at_match"),
        "team": player.get("team"),
        "team_name": player.get("team_name"),
        **rounded,
        "penalty_points": round(
            components["team_kill_points"] + components["suicide_points"], 2
        ) or 0.0,
        "event_points": round(sum(value for key, value in components.items()
                                  if key != "position_points"), 2),
        "total_points": round(sum(components.values()), 2),
    }


def assert_shareable_safe(payload: Any, path: str = "root") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in PRIVATE_KEYS:
                raise ValueError(f"private positional key leaked at {path}.{key}")
            assert_shareable_safe(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            assert_shareable_safe(value, f"{path}[{index}]")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Accumulation shadow — {report['match_id']}", "",
        f"Profile: `{report['profile']}` (**experimental; not KTPR**)", "",
        "Individual positional heatmaps, cells, flag histories, distances, and raw "
        "coordinates are excluded. `Position` is the capped point result calculated "
        "from private working data.", "",
        "| Player | Team | Kill | Assist | Damage | Caps | Breaks | Penalty | Position | Total |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for player in report["players"]:
        lines.append(
            f"| {player['player_name_at_match']} | {player['team_name']} | "
            f"{player['kill_points']:.2f} | {player['assist_points']:.2f} | "
            f"{player['damage_points']:.2f} | {player['capture_points']:.2f} | "
            f"{player['break_points']:.2f} | {player['penalty_points']:.2f} | "
            f"{player['position_points']:.2f} | "
            f"{player['total_points']:.2f} |"
        )
    lines += [
        "", "## Interpretation", "",
        "This is an accumulation ledger, not a rating. Position points use objective "
        "proximity as an initial measurable proxy; they do not claim the player was "
        "holding, defending, contesting, or visible to an opponent. The positional "
        "term is capped per half so passive presence cannot dominate event production.", "",
    ]
    return "\n".join(lines)


def write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as target:
        target.write(body)


def validate_output_separation(shareable: Path, private: Path) -> None:
    shareable = shareable.resolve()
    private = private.resolve()
    if (shareable == private or shareable.is_relative_to(private)
            or private.is_relative_to(shareable)):
        raise ValueError(
            "shareable and private output directories must be separate and non-nested"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--match-id")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--private-output-dir", type=Path, required=True,
                        help="separate local-only directory for player heatmap working data")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        validate_output_separation(args.output_dir, args.private_output_dir)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    profile = load_profile(args.profile)
    with EphemeralMysql.start() as db:
        analytics.load_fixture(db, args.fixture)
        sources = analytics.source_capabilities(db)
        if not all((sources["per_hit_damage"], sources["capture_credits"], sources["positions"])):
            analytics.install_legacy_compatibility(db)
        match_ids = analytics.discover_match_ids(db)
        match_id = args.match_id or (match_ids[0] if len(match_ids) == 1 else None)
        if match_id is None:
            raise SystemExit("fixture has multiple matches; pass --match-id")
        base = analytics.build_report(db, match_id, args.fixture, sources)
        match = base.get("match") or {}
        samples, flags = load_position_facts(
            db, match_id, int(match.get("server_id") or 0), str(match.get("map_name") or "")
        )
        points, private_players = derive_private_positions(
            base["players"], samples, flags, profile
        )

    players = [accumulate_player(p, points.get(int(p["player_id"]), 0.0), profile)
               for p in base["players"]]
    players.sort(key=lambda row: (-row["total_points"], row["player_name_at_match"] or ""))
    shareable = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "experimental_shadow",
        "profile": profile["profile"]["name"],
        "match_id": match_id,
        "map_name": match.get("map_name"),
        "privacy": {
            "individual_position_data": "private_not_exported",
            "shareable_position_field": "position_points_only",
        },
        "players": players,
    }
    assert_shareable_safe(shareable)
    private = {
        "schema_version": 1,
        "generated_at": shareable["generated_at"],
        "classification": "PRIVATE_PLAYER_POSITIONAL_ANALYTICS",
        "redistribution": "prohibited",
        "match_id": match_id,
        "profile": profile,
        "flags": flags,
        "players": private_players,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / f"{match_id}.json").write_text(
        json.dumps(shareable, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (args.output_dir / f"{match_id}.md").write_text(
        render_markdown(shareable), encoding="utf-8")
    private_path = args.private_output_dir / f"{match_id}.private.json"
    write_private_json(private_path, private)
    print(f"shareable: {args.output_dir / f'{match_id}.json'}")
    print(f"private:   {private_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
