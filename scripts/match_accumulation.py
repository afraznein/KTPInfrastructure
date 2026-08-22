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
DEFAULT_PROFILE = REPO / "config" / "analytics" / "accumulation_v2_target10.toml"
DEFAULT_OBJECTIVES = REPO / "config" / "analytics" / "map_objectives.toml"
PRIVATE_KEYS = {
    "heatmap", "heatmap_cells", "cell_x", "cell_y", "pos_x", "pos_y", "pos_z",
    "nearest_flag", "nearest_flag_index", "nearest_flag_distance",
    "flag_breakdown", "position_samples", "sample_count", "observed_seconds",
    "within_radius_samples", "raw_position_points", "awarded_position_points",
    "raw_points", "active_contest_samples", "scenario_points",
    "last_flag_defense_kills", "ownership_state_counts", "owner_team",
    "flag_state_events",
}


def load_position_profile(path: Path) -> dict[str, Any]:
    with path.open("rb") as source:
        profile = tomllib.load(source)
    for section in ("profile", "position"):
        if section not in profile:
            raise ValueError(f"accumulation profile is missing [{section}]")
    return profile


def load_profile(path: Path) -> dict[str, Any]:
    """Load a legacy aggregate profile used by this v0-v2 report CLI."""
    profile = load_position_profile(path)
    if "events" not in profile:
        raise ValueError("legacy accumulation report profile is missing [events]")
    return profile


def load_map_objectives(path: Path, map_name: str) -> dict[str, Any]:
    with path.open("rb") as source:
        maps = tomllib.load(source).get("maps", {})
    return maps.get(map_name, {})


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


def load_last_flag_defense_kills(
    db: EphemeralMysql, match_id: str
) -> dict[int, int]:
    match = analytics.sql_literal(match_id)
    rows = _query(db, f"""
SELECT killerId AS player_id, COUNT(*) AS last_flag_defense_kills
FROM hlstats_Events_Frags
WHERE match_id = {match} AND is_last_flag_defense = 1
GROUP BY killerId
""")
    return {int(row["player_id"]): int(row["last_flag_defense_kills"])
            for row in rows}


def load_flag_state_facts(
    db: EphemeralMysql, match_id: str, available: bool
) -> list[dict[str, Any]]:
    if not available:
        return []
    match = analytics.sql_literal(match_id)
    return _query(db, f"""
SELECT id, half, flag_index, flag_name, owner_team, is_initial,
       game_time, event_time
FROM ktp_flag_state_events
WHERE match_id = {match} AND half > 0
ORDER BY half, flag_index, game_time, id
""")


def _flag_role(flag_name: str, team: int, topology: dict[str, Any]) -> str:
    if not topology:
        return "uncategorized"
    team1 = {
        topology.get("team1_first"): "own_first",
        topology.get("team1_second"): "own_second",
        topology.get("middle"): "middle",
        topology.get("team2_second"): "enemy_second",
        topology.get("team2_first"): "enemy_first",
    }
    if team == 1:
        return team1.get(flag_name, "uncategorized")
    inverse = {
        "own_first": "enemy_first", "own_second": "enemy_second",
        "middle": "middle", "enemy_second": "own_second",
        "enemy_first": "own_first",
    }
    return inverse.get(team1.get(flag_name, "uncategorized"), "uncategorized")


def _flag_multiplier(
    flag_name: str,
    team: int,
    topology: dict[str, Any],
    scenario: dict[str, Any],
) -> float:
    """Return a reviewed map/team/flag value, with role weights as fallback."""
    explicit = topology.get(f"team{team}_flag_multipliers", {})
    if flag_name in explicit:
        return float(explicit[flag_name])
    role = _flag_role(flag_name, team, topology)
    return float(scenario.get(f"{role}_multiplier", 1.0))


def _owner_at(
    timeline: list[tuple[float, int]], game_time: float
) -> int | None:
    owner = None
    for changed_at, candidate_owner in timeline:
        if changed_at > game_time:
            break
        owner = candidate_owner
    return owner


def _unopposed_presence_multiplier(elapsed_seconds: float, cfg: dict[str, Any]) -> float:
    """Dampen only a consecutive unopposed run; contested presence stays whole."""
    if "unopposed_full_value_seconds" not in cfg:
        return 1.0
    full = float(cfg["unopposed_full_value_seconds"])
    reduced_until = float(cfg.get("unopposed_reduced_value_seconds", full))
    if elapsed_seconds <= full:
        return 1.0
    if elapsed_seconds <= reduced_until:
        return float(cfg.get("unopposed_reduced_multiplier", 0.5))
    return float(cfg.get("unopposed_floor_multiplier", 0.25))


def derive_private_positions(
    players: list[dict[str, Any]],
    samples: list[dict[str, Any]],
    flags: list[dict[str, Any]],
    profile: dict[str, Any],
    topology: dict[str, Any] | None = None,
    last_flag_kills: dict[int, int] | None = None,
    flag_states: list[dict[str, Any]] | None = None,
) -> tuple[dict[int, dict[str, float]], list[dict[str, Any]]]:
    """Return player positional points and private heatmap working records."""
    cfg = profile["position"]
    interval = float(cfg["sample_seconds"])
    radius = float(cfg["objective_radius_units"])
    rate = float(cfg["points_per_second_at_flag"])
    grid = int(cfg["grid_size_units"])
    cap_per_half = float(cfg["max_points_per_half"])
    scenario = profile.get("scenarios", {})
    topology = topology or {}
    last_flag_kills = last_flag_kills or {}
    flag_states = flag_states or []
    contest_radius = float(scenario.get("active_contest_radius_units", 0))
    double_caps = set(topology.get("double_caps", []))
    high_contest = set(topology.get("high_contest", []))
    by_player: dict[int, dict[str, Any]] = {}
    ownership_timeline: dict[tuple[int, int], list[tuple[float, int]]] = defaultdict(list)
    for flag_state in flag_states:
        ownership_timeline[
            (int(flag_state["half"]), int(flag_state["flag_index"]))
        ].append((float(flag_state["game_time"]), int(flag_state["owner_team"])))
    for timeline in ownership_timeline.values():
        timeline.sort()
    player_context = {int(p["player_id"]): p for p in players}
    sample_buckets: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        bucket = (int(sample["half"]), round(float(sample["game_time"]) / interval))
        sample_buckets[bucket].append(sample)
    unopposed_runs: dict[tuple[int, int, int], float] = defaultdict(float)
    last_near_flag: dict[tuple[int, int], tuple[int, int, int]] = {}

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
            "base_position_points": 0.0,
            "enemy_pressure_points": 0.0,
            "contested_points": 0.0,
            "double_cap_points": 0.0,
            "ownership_adjustment_points": 0.0,
            "last_flag_defense_points": 0.0,
            "ownership_state_counts": defaultdict(int),
            "heatmap": defaultdict(lambda: {"samples": 0, "seconds": 0.0}),
            "flag_breakdown": defaultdict(lambda: {
                "samples": 0, "within_radius_samples": 0,
                "active_contest_samples": 0, "observed_seconds": 0.0,
                "raw_points": 0.0, "scenario_points": 0.0,
            }),
        })
        state["sample_count"] += 1
        state["observed_seconds"] += interval
        cell = state["heatmap"][(x // grid, y // grid)]
        cell["samples"] += 1
        cell["seconds"] += interval
        player_half = (player_id, int(sample["half"]))
        if nearest is not None and nearest_distance is not None:
            flag_state = state["flag_breakdown"][(
                int(nearest["flag_index"]), str(nearest["flag_name"])
            )]
            flag_state["samples"] += 1
            flag_state["observed_seconds"] += interval
            if nearest_distance <= radius:
                bucket = (int(sample["half"]),
                          round(float(sample["game_time"]) / interval))
                actively_contested = False
                if contest_radius > 0:
                    for other in sample_buckets[bucket]:
                        if int(other["team"]) == int(sample["team"]):
                            continue
                        if math.hypot(
                            x - int(other["pos_x"]), y - int(other["pos_y"])
                        ) <= contest_radius:
                            actively_contested = True
                            break

                run_key = (player_id, int(sample["half"]), int(nearest["flag_index"]))
                previous_key = last_near_flag.get(player_half)
                if previous_key is not None and previous_key != run_key:
                    unopposed_runs.pop(previous_key, None)
                last_near_flag[player_half] = run_key
                if actively_contested:
                    unopposed_runs[run_key] = 0.0
                    presence_multiplier = 1.0
                else:
                    unopposed_runs[run_key] += interval
                    presence_multiplier = _unopposed_presence_multiplier(
                        unopposed_runs[run_key], cfg
                    )
                proximity = 1.0 - (nearest_distance / radius)
                raw_points = interval * rate * proximity * presence_multiplier
                flag_name = str(nearest["flag_name"])
                role = _flag_role(flag_name, int(sample["team"]), topology)
                territory_multiplier = _flag_multiplier(
                    flag_name, int(sample["team"]), topology, scenario
                )
                base_points = raw_points * min(territory_multiplier, 1.0)
                territory_bonus = raw_points * max(territory_multiplier - 1.0, 0.0)
                state["base_position_points"] += base_points
                if role in ("enemy_first", "enemy_second"):
                    state["enemy_pressure_points"] += territory_bonus
                else:
                    state["contested_points"] += territory_bonus
                running = base_points + territory_bonus

                if flag_name in double_caps:
                    bonus = running * (
                        float(scenario.get("double_cap_multiplier", 1.0)) - 1.0
                    )
                    state["double_cap_points"] += bonus
                    running += bonus
                if flag_name in high_contest:
                    bonus = running * (
                        float(scenario.get("high_contest_area_multiplier", 1.0)) - 1.0
                    )
                    state["contested_points"] += bonus
                    running += bonus

                sample_game_time = float(sample["game_time"])
                timeline = ownership_timeline.get(
                    (int(sample["half"]), int(nearest["flag_index"])), []
                )
                owner_team = _owner_at(timeline, sample_game_time)

                ownership_state = "unknown"
                ownership_multiplier = 1.0
                if owner_team == 0:
                    ownership_state = "neutral"
                    ownership_multiplier = float(
                        scenario.get("neutral_flag_multiplier", 1.0)
                    )
                elif owner_team == int(sample["team"]):
                    ownership_state = (
                        "defending_under_pressure" if actively_contested else "holding"
                    )
                    key = (
                        "defending_under_pressure_multiplier" if actively_contested
                        else "holding_multiplier"
                    )
                    ownership_multiplier = float(scenario.get(key, 1.0))

                    # Last-flag status is safe only when every configured flag
                    # has a known owner at this sample. An incomplete baseline
                    # must not accidentally look like a one-flag defense.
                    owners = [
                        _owner_at(
                            ownership_timeline.get(
                                (int(sample["half"]), int(flag["flag_index"])), []
                            ),
                            sample_game_time,
                        )
                        for flag in flags
                    ]
                    if (owners and all(value is not None for value in owners)
                            and owners.count(int(sample["team"])) == 1):
                        ownership_state = (
                            "last_flag_defending_under_pressure"
                            if actively_contested else "last_flag_holding"
                        )
                        ownership_multiplier *= float(
                            scenario.get("last_flag_holding_multiplier", 1.0)
                        )
                elif owner_team is not None:
                    ownership_state = (
                        "attacking_under_pressure" if actively_contested else "attacking"
                    )
                    key = (
                        "attacking_under_pressure_multiplier" if actively_contested
                        else "attacking_multiplier"
                    )
                    ownership_multiplier = float(scenario.get(key, 1.0))

                ownership_bonus = running * (ownership_multiplier - 1.0)
                state["ownership_adjustment_points"] += ownership_bonus
                state["ownership_state_counts"][ownership_state] += 1
                running += ownership_bonus

                if actively_contested:
                    bonus = running * (
                        float(scenario.get("active_contest_multiplier", 1.0)) - 1.0
                    )
                    state["contested_points"] += bonus
                    running += bonus
                    flag_state["active_contest_samples"] += 1
                flag_state["within_radius_samples"] += 1
                flag_state["raw_points"] += raw_points
                flag_state["scenario_points"] += running
                state["raw_position_points"] += running
            else:
                previous_key = last_near_flag.pop(player_half, None)
                if previous_key is not None:
                    unopposed_runs.pop(previous_key, None)

    point_fields = (
        "base_position_points", "enemy_pressure_points", "contested_points",
        "double_cap_points", "ownership_adjustment_points",
        "last_flag_defense_points",
    )
    points_by_player: dict[int, dict[str, float]] = {}
    private_players: list[dict[str, Any]] = []
    for player_id in sorted(player_context):
        player = player_context[player_id]
        state = by_player.setdefault(player_id, {
            "player_id": player_id, "steam_id": player.get("steam_id"),
            "player_name_at_match": player.get("player_name_at_match"),
            "team": player.get("team"), "sample_count": 0,
            "observed_seconds": 0.0, "raw_position_points": 0.0,
            **{field: 0.0 for field in point_fields},
            "heatmap": {}, "flag_breakdown": {}, "ownership_state_counts": {},
        })
        defense_kills = last_flag_kills.get(player_id, 0)
        defense_points = defense_kills * float(
            scenario.get("last_flag_defense_kill_points", 0.0)
        )
        defense_cap = float(
            scenario.get("last_flag_defense_max_per_half", float("inf"))
        ) * max(1, int(player_context[player_id].get("halves_played") or 1))
        defense_points = min(defense_points, defense_cap)
        state["last_flag_defense_points"] += defense_points
        state["raw_position_points"] += defense_points
        halves = max(1, int(player_context[player_id].get("halves_played") or 1))
        awarded = min(state["raw_position_points"], cap_per_half * halves)
        scale = awarded / state["raw_position_points"] if state["raw_position_points"] else 0.0
        awarded_components = {
            field: round(state[field] * scale, 2) or 0.0 for field in point_fields
        }
        points_by_player[player_id] = {
            **awarded_components, "position_points": round(awarded, 2) or 0.0,
        }
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
            "last_flag_defense_kills": defense_kills,
            "awarded_position_points": round(awarded, 2),
            "awarded_components": awarded_components,
            "heatmap_cells": heatmap,
            "flag_breakdown": flag_breakdown,
        })
    return points_by_player, private_players


def accumulate_player(
    player: dict[str, Any], position: float | dict[str, float], profile: dict[str, Any]
) -> dict[str, Any]:
    weights = profile["events"]
    position_components = (
        position if isinstance(position, dict)
        else {"position_points": float(position)}
    )
    components = {
        "kill_points": player.get("kills", 0) * float(weights["kill"]),
        "assist_points": player.get("assists", 0) * float(weights["assist"]),
        "damage_points": player.get("damage_dealt", 0) * float(weights["damage"]),
        "capture_points": player.get("capture_credits", 0) * float(weights["capture_credit"]),
        "break_points": player.get("cap_breaks", 0) * float(weights["cap_break"]),
        "team_kill_points": player.get("team_kills", 0) * float(weights["team_kill"]),
        "suicide_points": player.get("suicides", 0) * float(weights["suicide"]),
        **position_components,
    }
    event_keys = (
        "kill_points", "assist_points", "damage_points", "capture_points",
        "break_points", "team_kill_points", "suicide_points",
    )
    event_total = sum(components[key] for key in event_keys)
    position_total = components.get("position_points", 0.0)
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
        "event_points": round(event_total, 2),
        "total_points": round(event_total + position_total, 2),
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
        "| Player | Team | Events | Base pos. | Enemy pressure | Contested | Double-cap | Ownership | Last-flag D | Position | Total |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for player in report["players"]:
        lines.append(
            f"| {player['player_name_at_match']} | {player['team_name']} | "
            f"{player['event_points']:.2f} | "
            f"{player.get('base_position_points', player['position_points']):.2f} | "
            f"{player.get('enemy_pressure_points', 0.0):.2f} | "
            f"{player.get('contested_points', 0.0):.2f} | "
            f"{player.get('double_cap_points', 0.0):.2f} | "
            f"{player.get('ownership_adjustment_points', 0.0):.2f} | "
            f"{player.get('last_flag_defense_points', 0.0):.2f} | "
            f"{player['position_points']:.2f} | "
            f"{player['total_points']:.2f} |"
        )
    lines += [
        "", "## Interpretation", "",
        "This is an accumulation ledger, not a rating. Position points combine "
        "objective proximity with explicitly captured scenario evidence. Proximity "
        "alone does not prove holding or line of sight; ownership classification is "
        "used only when a captured flag-state timeline is available. The positional "
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
    parser.add_argument("--map-objectives", type=Path, default=DEFAULT_OBJECTIVES)
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
        topology = load_map_objectives(
            args.map_objectives, str(match.get("map_name") or "")
        )
        last_flag_kills = load_last_flag_defense_kills(db, match_id)
        flag_states = load_flag_state_facts(
            db, match_id, sources.get("flag_ownership", False)
        )
        points, private_players = derive_private_positions(
            base["players"], samples, flags, profile, topology, last_flag_kills,
            flag_states
        )

    empty_position = {
        "base_position_points": 0.0, "enemy_pressure_points": 0.0,
        "contested_points": 0.0, "double_cap_points": 0.0,
        "ownership_adjustment_points": 0.0,
        "last_flag_defense_points": 0.0, "position_points": 0.0,
    }
    players = [accumulate_player(
                   p, points.get(int(p["player_id"]), empty_position), profile)
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
        "map_topology": topology,
        "flags": flags,
        "flag_state_events": flag_states,
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
