#!/usr/bin/env python3
"""Build and verify a match report from Lane B's live ephemeral MySQL."""

from __future__ import annotations

import bisect
import hashlib
import json
import math
import statistics
import tomllib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scripts.accumulation_v3 import load_profile, score_match, validate_facts
from scripts.build_automated_match_report import build_bundle
from scripts.life_impact_v4 import derive_life_impact
from scripts.match_analytics import (
    evaluate_capture_authorization,
    grenade_entity_summary,
    objective_attempt_summary,
    sql_literal,
    tsv_rows,
)
from scripts.momentum_v5 import derive_momentum
from scripts.points_timeline import (
    BIN_SECONDS,
    CONSERVATION_TOLERANCE,
    privacy_violations as timeline_privacy_violations,
)


REPO = Path(__file__).resolve().parents[1]
LEGACY_PROFILE = REPO / "config/analytics/accumulation_v5_momentum.toml"
SCHEMA22_PROFILE = REPO / "config/analytics/accumulation_v6_schema22_2s.toml"
DEFAULT_PROFILE = SCHEMA22_PROFILE
DEFAULT_OBJECTIVES = REPO / "config/analytics/map_objectives.toml"
DEFAULT_SPATIAL_CATALOG = REPO / "config/analytics/spatial_maps"
PUBLIC_FORBIDDEN_KEYS = {
    "pos_x", "pos_y", "pos_z", "origin_x", "origin_y", "origin_z",
    "coordinates", "heatmap_cells", "position_samples", "steam_id",
}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _rows(db, marker: str, sql: str) -> list[dict[str, Any]]:
    return tsv_rows(db.sql(f"/* lane_b_v5_{marker} */\n{sql}"))


def _mode(values: list[int], fallback: int = 0) -> int:
    return Counter(values).most_common(1)[0][0] if values else fallback


def _flag_role(flag_name: str, team: int, topology: dict[str, Any]) -> str:
    ordered = {
        topology.get("team1_first"): "own_first",
        topology.get("team1_second"): "own_second",
        topology.get("middle"): "middle",
        topology.get("team2_second"): "enemy_second",
        topology.get("team2_first"): "enemy_first",
    }
    role = ordered.get(flag_name, "uncategorized")
    if team == 1:
        return role
    return {
        "own_first": "enemy_first", "own_second": "enemy_second",
        "middle": "middle", "enemy_second": "own_second",
        "enemy_first": "own_first",
    }.get(role, "uncategorized")


def _stable_and_side_teams(
    samples: list[dict[str, Any]], roster_team: dict[int, int],
) -> tuple[dict[tuple[int, int], int], dict[int, int]]:
    side_votes: dict[tuple[int, int], list[int]] = defaultdict(list)
    for row in samples:
        side_votes[(_i(row["half"]), _i(row["player_id"]))].append(_i(row["team"]))
    sides = {key: _mode(values) for key, values in side_votes.items()}
    stable = {}
    player_ids = set(roster_team) | {player_id for _, player_id in sides}
    for player_id in player_ids:
        stable[player_id] = sides.get((1, player_id), roster_team.get(player_id, 0))
    return sides, stable


def _associate_damage_to_deaths(
    damage_rows: list[dict[str, Any]], frags: list[dict[str, Any]],
    sides: dict[tuple[int, int], int],
) -> list[dict[str, Any]]:
    deaths: dict[tuple[int, int], list[tuple[float, str]]] = defaultdict(list)
    for frag in frags:
        deaths[(_i(frag["half"]), _i(frag["victim_id"]))].append(
            (_f(frag["time"]), str(frag["event_id"]))
        )
    for values in deaths.values():
        values.sort()
    result = []
    for row in damage_rows:
        half, attacker, victim = _i(row["half"]), _i(row["attacker_id"]), _i(row["victim_id"])
        attacker_team = sides.get((half, attacker), 0)
        victim_team = sides.get((half, victim), 0)
        if attacker == victim or not attacker_team or attacker_team == victim_team:
            continue
        candidates = deaths.get((half, victim), [])
        index = bisect.bisect_left(candidates, (_f(row["time"]) - 0.001, ""))
        death_id = candidates[index][1] if index < len(candidates) else None
        life_id = f"h{half}-p{victim}-{death_id or 'open'}"
        result.append({
            "death_event_id": death_id, "victim_life_id": life_id,
            "attacker_id": attacker, "victim_id": victim,
            "attacker_team": attacker_team, "victim_team": victim_team,
            "damage_capped": _f(row["damage_capped"]),
        })
    return result


def _participation_seconds(
    samples: list[dict[str, Any]], duration_seconds: float,
) -> dict[int, float]:
    """Estimate time present from each player's per-half sample window.

    Position rows are emitted only while alive, so row count would incorrectly
    remove normal respawn time. First-to-last span per half preserves that time
    while still handling a mid-match substitution. One sample interval is added
    to include the final observed tick.
    """
    by_player_half: dict[tuple[int, int], list[float]] = defaultdict(list)
    tick_times: dict[int, set[float]] = defaultdict(set)
    for row in samples:
        half = _i(row["half"])
        when = _f(row["game_time"])
        by_player_half[(_i(row["player_id"]), half)].append(when)
        tick_times[half].add(when)
    intervals = []
    for times in tick_times.values():
        ordered = sorted(times)
        intervals.extend(
            right - left for left, right in zip(ordered, ordered[1:])
            if 0.1 <= right - left <= 30.0
        )
    sample_interval = statistics.median(intervals) if intervals else 2.0
    result: dict[int, float] = defaultdict(float)
    for (player_id, _half), times in by_player_half.items():
        result[player_id] += max(times) - min(times) + sample_interval
    return {
        player_id: round(min(seconds, duration_seconds), 2)
        for player_id, seconds in result.items()
    }


def _aggregate_team_life_timing(
    private_lives: list[dict[str, Any]], life_points: dict[int, dict[str, float]],
    stable_teams: dict[int, int], half_end_bins: dict[int, float] | None = None,
) -> list[dict[str, Any]]:
    """Collapse private per-life awards to team/time rows immediately.

    Final per-player match caps and rounding remain authoritative. Private
    life rows supply only proportional timing weights and are never returned.
    """
    by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for life in private_lives:
        by_player[_i(life.get("player_id"))].append(life)
    aggregate: dict[tuple[int, float, int], float] = defaultdict(float)
    contributors: dict[tuple[int, float, int], set[int]] = defaultdict(set)
    deferred: dict[tuple[int, int], float] = defaultdict(float)
    observed_half_end: dict[int, float] = defaultdict(lambda: BIN_SECONDS)
    for player_id, components in sorted(life_points.items()):
        team = stable_teams.get(player_id, 0)
        target = max(0.0, _f(components.get("position_points")))
        if team not in (1, 2) or target <= 0:
            continue
        weighted = []
        for life in by_player.get(player_id, []):
            awarded = life.get("awarded_components") or {}
            points = sum(
                max(0.0, _f(awarded.get(key)))
                for key in (
                    "mid_defense_points", "aggression_points",
                    "enemy_flag_hold_points", "active_flag_defense_points",
                )
            )
            if points > 0:
                weighted.append((
                    max(1, _i(life.get("half"), 1)),
                    max(0.0, _f(life.get("end_time"))), points,
                ))
        total = sum(row[2] for row in weighted)
        if total <= 0:
            deferred[(1, team)] += target
            continue
        scale = target / total
        for half, when, points in weighted:
            bin_index = 0 if when <= 0 else math.ceil(when / BIN_SECONDS) - 1
            bin_end = (bin_index + 1) * BIN_SECONDS
            key = (half, bin_end, team)
            aggregate[key] += points * scale
            contributors[key].add(player_id)
            observed_half_end[half] = max(observed_half_end[half], bin_end)
    public = []
    for (half, bin_end, team), points in sorted(aggregate.items()):
        if len(contributors[(half, bin_end, team)]) >= 3:
            public.append({
                "half": half, "bin_end": round(bin_end, 4), "team": team,
                "points": round(points, 4), "timing": "team_bin",
            })
        else:
            deferred[(half, team)] += points
    reconciliation_ends = dict(observed_half_end)
    reconciliation_ends.update(half_end_bins or {})
    for (half, team), points in sorted(deferred.items()):
        if points <= 0:
            continue
        public.append({
            "half": half,
            "bin_end": round(max(BIN_SECONDS, reconciliation_ends.get(half, BIN_SECONDS)), 4),
            "team": team, "points": round(points, 4),
            "timing": "privacy_deferred_reconciliation",
        })
    return sorted(public, key=lambda row: (
        row["half"], row["bin_end"], row["team"], row["timing"]
    ))


def _catalog_flags(map_name: str, catalog_dir: Path | None) -> list[dict[str, Any]]:
    if catalog_dir is None:
        return []
    path = catalog_dir / f"{map_name}.json"
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("map_name") != map_name:
        raise ValueError(f"spatial catalog map mismatch in {path}")
    return [
        {
            "flag_index": _i(row.get("index"), index),
            "flag_name": str(row.get("code") or row.get("name")),
            "origin_x": _f(row.get("x")),
            "origin_y": _f(row.get("y")),
        }
        for index, row in enumerate(payload.get("flags") or [])
    ]


def _ownership_is_reliable(
    flag_states: list[dict[str, Any]], flags: list[dict[str, Any]],
    observed_halves: set[int],
) -> bool:
    """Require a complete baseline and a two-team partition in every half."""
    expected = {str(row["flag_name"]) for row in flags}
    if not expected or not observed_halves:
        return False
    for half in observed_halves:
        rows = sorted(
            (row for row in flag_states if _i(row.get("half")) == half),
            key=lambda row: (_f(row.get("game_time")), _i(row.get("id"))),
        )
        initial = {
            str(row["flag_name"]): _i(row["owner_team"])
            for row in rows if _i(row.get("is_initial"))
        }
        if expected - set(initial) or any(owner not in (0, 1, 2) for owner in initial.values()):
            return False
        state: dict[str, int] = {}
        partition_seen = False
        for row in rows:
            name = str(row["flag_name"])
            if name in expected:
                state[name] = _i(row["owner_team"])
            owners = [state.get(name) for name in expected]
            if all(owner in (1, 2) for owner in owners) and {1, 2} <= set(owners):
                partition_seen = True
        if not partition_seen:
            return False
    return True


def build_facts(
    db, match_id: str, *, profile_path: Path = DEFAULT_PROFILE,
    objectives_path: Path = DEFAULT_OBJECTIVES,
    spatial_catalog_dir: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Extract one match and return shareable facts plus private audit metadata."""
    match = sql_literal(match_id)
    match_rows = _rows(db, "match", f"""
SELECT match_id, MAX(server_id) AS server_id, MAX(map_name) AS map_name,
       COUNT(*) AS halves_played,
       GROUP_CONCAT(DISTINCT half ORDER BY half) AS observed_halves,
       SUM(CASE WHEN end_time IS NULL THEN 1 ELSE 0 END) AS open_halves,
       MAX(match_type) AS match_type,
       COUNT(DISTINCT match_type) AS distinct_match_types,
       SUM(CASE WHEN match_type IS NULL THEN 1 ELSE 0 END) AS unclassified_halves,
       SUM(CASE WHEN end_time IS NULL THEN 0 ELSE
           GREATEST(TIMESTAMPDIFF(SECOND, start_time, end_time), 0) END)
           AS duration_seconds
FROM ktp_matches WHERE match_id={match} GROUP BY match_id
""")
    if len(match_rows) != 1:
        raise ValueError(f"expected one completed match summary for {match_id}")
    match_row = match_rows[0]
    if _i(match_row.get("open_halves")):
        raise ValueError(f"match {match_id} still has an open half")
    map_name = str(match_row["map_name"])
    server_id = _i(match_row["server_id"])
    duration = _f(match_row["duration_seconds"])

    with objectives_path.open("rb") as source:
        topology = tomllib.load(source).get("maps", {}).get(map_name, {})
    profile = load_profile(profile_path)
    manifest_rows = _rows(db, "capture_manifests", f"""
SELECT cm.half, cm.schema_version, cm.capabilities, cm.position_interval,
       cm.event_epoch AS producer_activation_epoch,
       UNIX_TIMESTAMP(cm.created_at) AS activation_receipt_epoch,
       UNIX_TIMESTAMP(m.start_time) AS match_start_epoch
FROM ktp_capture_manifests cm
LEFT JOIN ktp_matches m
  ON BINARY m.match_id=BINARY cm.match_id AND m.half=cm.half
WHERE BINARY cm.match_id=BINARY {match}
ORDER BY cm.half, cm.id
""")
    health_rows = _rows(db, "capture_health", f"""
SELECT half, event_type, attempted, enqueued, dropped, emitted,
       daemon_received, daemon_accepted, daemon_rejected,
       correlation_failure_count, sequence_gap_count,
       duplicate_or_reordered_count
FROM ktp_capture_health
WHERE BINARY match_id=BINARY {match}
ORDER BY half, event_type
""")
    observed_halves = {
        _i(value) for value in str(match_row.get("observed_halves") or "").split(",")
        if _i(value) > 0
    }
    capture_authorization = evaluate_capture_authorization(
        observed_halves, manifest_rows, health_rows,
        require_activation=True,
    )
    profile_contract = profile.get("profile") or {}
    requires_schema22 = (
        _i(profile_contract.get("requires_capture_schema")) == 22
        or abs(_f(profile_contract.get("requires_position_interval")) - 2.0) <= 0.01
    )
    if requires_schema22 and not capture_authorization["authorized"]:
        errors = "; ".join(capture_authorization.get("errors") or [])
        raise ValueError(
            "schema22/2s scoring profile requires an authorized capture for every "
            f"observed half ({capture_authorization['status']}: {errors or 'not captured'})"
        )
    minimum_observed = _f(
        (profile.get("impact_index") or {}).get("minimum_observed_seconds"), 300.0
    )
    if duration < minimum_observed:
        raise ValueError(
            f"match duration {duration:.0f}s is below the v5 rating minimum "
            f"of {minimum_observed:.0f}s"
        )

    roster_rows = _rows(db, "roster", f"""
SELECT player_id, player_name, team
FROM ktp_match_players WHERE match_id={match} ORDER BY player_id
""")
    if not roster_rows:
        raise ValueError(f"match {match_id} has no roster")
    roster_team = {_i(row["player_id"]): _i(row.get("team")) for row in roster_rows}
    invalid_roster_teams = sorted(
        player_id for player_id, team in roster_team.items() if team not in (1, 2)
    )
    if invalid_roster_teams:
        raise ValueError(f"roster has invalid team values for players {invalid_roster_teams}")

    state_rows = _rows(db, "flag_states", f"""
SELECT s.id, s.half, s.flag_index, s.flag_name, s.owner_team, s.is_initial,
       s.game_time
FROM ktp_flag_state_events s
WHERE s.match_id={match} AND s.half>0
ORDER BY s.half, game_time, s.id
""")
    flag_states = [{**row, "half": _i(row["half"]), "flag_index": _i(row["flag_index"]),
                    "owner_team": _i(row["owner_team"]), "is_initial": _i(row["is_initial"]),
                    "game_time": _f(row["game_time"])} for row in state_rows]
    half_clock_baselines: dict[int, float] = {}
    for row in flag_states:
        if row["is_initial"]:
            half = row["half"]
            half_clock_baselines[half] = min(
                half_clock_baselines.get(half, math.inf), row["game_time"]
            )
    for row in flag_states:
        row["game_time"] = max(
            0.0, row["game_time"] - half_clock_baselines.get(row["half"], 0.0)
        )

    samples = _rows(db, "positions", f"""
SELECT p.player_id, p.team, p.half, p.pos_x, p.pos_y, p.pos_z,
       p.game_time
FROM ktp_position_samples p
WHERE p.match_id={match} AND p.half>0
ORDER BY p.half, game_time, p.id
""")
    samples = [{**row, "player_id": _i(row["player_id"]), "team": _i(row["team"]),
                "half": _i(row["half"]), "pos_x": _f(row["pos_x"]),
                "pos_y": _f(row["pos_y"]), "pos_z": _f(row["pos_z"]),
                "game_time": _f(row["game_time"])} for row in samples]
    if samples:
        fallback_baselines = {
            half: min(row["game_time"] for row in samples if row["half"] == half)
            for half in {row["half"] for row in samples}
        }
        for row in samples:
            baseline = half_clock_baselines.get(
                row["half"], fallback_baselines[row["half"]]
            )
            row["game_time"] = max(0.0, row["game_time"] - baseline)

    objective_attempt_rows = _rows(db, "objective_attempts", f"""
SELECT server_id, half, attempt_id, event_kind, stop_reason
FROM ktp_objective_attempt_events
WHERE match_id={match} AND half>0
ORDER BY half, event_epoch, producer_sequence
""") if capture_authorization["authorized"] else []
    grenade_entity_rows = _rows(db, "grenade_entities", f"""
SELECT server_id, half, entindex, serial, entity_kind, weapon_id, weapon_type
FROM ktp_grenade_entity_events
WHERE match_id={match} AND half>0
ORDER BY half, event_epoch, producer_sequence
""") if capture_authorization["authorized"] else []
    telemetry_lifecycles = {
        "privacy": "aggregate_only_no_entity_or_position_detail",
        "objective_attempts": objective_attempt_summary(objective_attempt_rows),
        "grenade_entities": grenade_entity_summary(grenade_entity_rows),
    }
    sides, stable_teams = _stable_and_side_teams(samples, roster_team)
    side_stable_votes: dict[tuple[int, int], list[int]] = defaultdict(list)
    for (half, player_id), side in sides.items():
        stable = stable_teams.get(player_id, 0)
        if side in (1, 2) and stable in (1, 2):
            side_stable_votes[(half, side)].append(stable)
    side_to_stable = {
        key: _mode(values) for key, values in side_stable_votes.items()
    }
    for row in samples:
        row["momentum_team"] = stable_teams.get(row["player_id"], row["team"])

    frag_rows = _rows(db, "frags", f"""
SELECT f.id, f.half, f.killerId AS killer_id, f.victimId AS victim_id,
       GREATEST(TIMESTAMPDIFF(MICROSECOND, m.start_time, f.eventTime)/1000000.0, 0)
           AS game_time
FROM hlstats_Events_Frags f
JOIN ktp_matches m ON m.match_id=f.match_id AND m.half=f.half
WHERE f.match_id={match} AND f.half>0
ORDER BY f.half, f.eventTime, f.id
""")
    frags = []
    for row in frag_rows:
        half, killer, victim = _i(row["half"]), _i(row["killer_id"]), _i(row["victim_id"])
        frags.append({
            "event_id": f"frag-{row['id']}", "half": half,
            "time": _f(row["game_time"]), "killer_id": killer, "victim_id": victim,
            "killer_team": sides.get((half, killer), roster_team.get(killer, 0)),
            "victim_team": sides.get((half, victim), roster_team.get(victim, 0)),
            "killer_momentum_team": stable_teams.get(killer, roster_team.get(killer, 0)),
            "victim_momentum_team": stable_teams.get(victim, roster_team.get(victim, 0)),
            "victim_life_id": f"h{half}-p{victim}-frag-{row['id']}",
        })

    raw_damage = _rows(db, "damage", f"""
SELECT d.id, d.half, d.attacker_id, d.victim_id, d.damage_capped,
       GREATEST(TIMESTAMPDIFF(MICROSECOND, m.start_time, d.event_time)/1000000.0, 0)
           AS game_time
FROM ktp_damage_events d
JOIN ktp_matches m ON m.match_id=d.match_id AND m.half=d.half
WHERE d.match_id={match} AND d.half>0 AND d.damage_capped>0
ORDER BY d.half, d.event_time, d.id
""")
    raw_damage = [{**row, "half": _i(row["half"]),
                   "attacker_id": _i(row["attacker_id"]),
                   "victim_id": _i(row["victim_id"]),
                   "damage_capped": _f(row["damage_capped"]),
                   "time": _f(row["game_time"])} for row in raw_damage]
    damage_events = _associate_damage_to_deaths(raw_damage, frags, sides)

    assist_rows = _rows(db, "assists", f"""
SELECT e.playerId AS player_id, COUNT(*) AS assists
FROM hlstats_Events_PlayerPlayerActions e
JOIN hlstats_Actions a ON a.id=e.actionId
WHERE e.match_id={match} AND a.game='dod' AND a.code='assist'
GROUP BY e.playerId
""")
    assists = {_i(row["player_id"]): _i(row["assists"]) for row in assist_rows}

    teamkill_rows = _rows(db, "teamkill_resets", f"""
SELECT t.id, t.half, t.killerId AS killer_id, t.victimId AS player_id,
       GREATEST(TIMESTAMPDIFF(MICROSECOND, m.start_time, t.eventTime)/1000000.0, 0)
           AS game_time
FROM hlstats_Events_Teamkills t
JOIN ktp_matches m ON m.match_id=t.match_id AND m.half=t.half
WHERE t.match_id={match} AND t.half>0
""")
    suicide_rows = _rows(db, "suicide_resets", f"""
SELECT s.id, s.half, s.playerId AS player_id,
       GREATEST(TIMESTAMPDIFF(MICROSECOND, m.start_time, s.eventTime)/1000000.0, 0)
           AS game_time
FROM hlstats_Events_Suicides s
JOIN ktp_matches m ON m.match_id=s.match_id AND m.half=s.half
WHERE s.match_id={match} AND s.half>0
""")
    death_resets = [
        {"half": _i(row["half"]), "time": _f(row["game_time"]),
         "player_id": _i(row["player_id"]), "kind": kind}
        for rows, kind in ((teamkill_rows, "teamkill_victim"), (suicide_rows, "suicide"))
        for row in rows
    ]
    team_kills = Counter(_i(row["killer_id"]) for row in teamkill_rows)

    capture_rows = _rows(db, "captures", f"""
SELECT c.id, c.half, c.player_id, c.team AS capture_team, c.flag_name,
       GREATEST(TIMESTAMPDIFF(MICROSECOND, m.start_time, c.event_time)/1000000.0, 0)
           AS game_time
FROM ktp_flag_captures c
JOIN ktp_matches m ON m.match_id=c.match_id AND m.half=c.half
WHERE c.match_id={match} AND c.half>0
ORDER BY c.half, c.event_time, c.id
""")
    grouped_captures: dict[tuple[int, float, int, str], set[int]] = defaultdict(set)
    for row in capture_rows:
        capture_team = str(row.get("capture_team") or "").lower()
        if capture_team.startswith("all"):
            team = 1
        elif capture_team.startswith("axis"):
            team = 2
        else:
            raise ValueError(f"capture {row.get('id')} has unknown team {capture_team!r}")
        if not row.get("flag_name"):
            raise ValueError(f"capture {row.get('id')} has no flag name")
        grouped_captures[(_i(row["half"]), _f(row["game_time"]), team,
                          str(row["flag_name"]))].add(_i(row["player_id"]))
    captures = []
    for index, ((half, when, team, flag_name), credited) in enumerate(
        sorted(grouped_captures.items()), 1
    ):
        captures.append({
            "event_id": f"capture-{index}", "half": half, "time": when,
            "team": team, "flag_name": flag_name,
            "momentum_team": side_to_stable.get((half, team), team),
            "flag_role": _flag_role(flag_name, team, topology),
            "credited_player_ids": sorted(credited), "is_capout": False,
        })

    break_rows = _rows(db, "breaks", f"""
SELECT e.id, m.half, e.playerId AS player_id, e.contester_count,
       e.time_remaining, e.is_capout,
       GREATEST(TIMESTAMPDIFF(MICROSECOND, m.start_time, e.eventTime)/1000000.0, 0)
           AS game_time
FROM hlstats_Events_PlayerActions e
JOIN hlstats_Actions a ON a.id=e.actionId
JOIN ktp_matches m ON m.match_id=e.match_id
 AND e.eventTime BETWEEN m.start_time AND m.end_time
WHERE e.match_id={match} AND m.half>0 AND a.game='dod' AND a.code='cap_break'
ORDER BY m.half, e.eventTime, e.id
""")
    cap_breaks = [{
        "event_id": f"break-{row['id']}", "half": _i(row["half"]),
        "time": _f(row["game_time"]), "player_id": _i(row["player_id"]),
        "contester_count": None if row.get("contester_count") is None else _i(row["contester_count"]),
        "time_remaining": None if row.get("time_remaining") is None else _f(row["time_remaining"]),
        "prevented_capout": bool(_i(row.get("is_capout"))),
    } for row in break_rows]

    flags = _rows(db, "flags", f"""
SELECT flag_index, flag_name, origin_x, origin_y
FROM ktp_flag_positions WHERE server_id={server_id} AND map_name={sql_literal(map_name)}
ORDER BY flag_index
""")
    flags = [{"flag_index": _i(row["flag_index"]), "flag_name": row["flag_name"],
              "origin_x": _f(row["origin_x"]), "origin_y": _f(row["origin_y"])}
             for row in flags]
    flag_position_source = "live_database"
    if not flags:
        flags = _catalog_flags(map_name, spatial_catalog_dir)
        flag_position_source = "curated_competitive_map_catalog" if flags else "unavailable"
    state_timeline: dict[tuple[int, str], list[tuple[float, int]]] = defaultdict(list)
    for row in flag_states:
        state_timeline[(row["half"], str(row["flag_name"]))].append(
            (row["game_time"], row["owner_team"])
        )
    for values in state_timeline.values():
        values.sort()
    for capture in captures:
        owners = []
        for flag in flags:
            values = state_timeline.get((capture["half"], str(flag["flag_name"])), [])
            index = bisect.bisect_right(values, (capture["time"] + 1.0, 10**9)) - 1
            owners.append(values[index][1] if index >= 0 else None)
        capture["is_capout"] = bool(owners) and all(
            owner == capture["team"] for owner in owners
        )

    opponent_damage = defaultdict(float)
    for row in damage_events:
        opponent_damage[_i(row["attacker_id"])] += _f(row["damage_capped"])
    kills = Counter(_i(row["killer_id"]) for row in frags
                    if _i(row["killer_team"]) != _i(row["victim_team"]))
    deaths = Counter(_i(row["victim_id"]) for row in frags
                     if _i(row["killer_team"]) != _i(row["victim_team"]))
    participation = _participation_seconds(samples, duration)
    players = [{
        "player_id": _i(row["player_id"]),
        "player_name_at_match": str(row["player_name"]),
        "team": stable_teams.get(_i(row["player_id"]), _i(row.get("team"))),
        "team_name": f"Team {stable_teams.get(_i(row['player_id']), _i(row.get('team')))}",
        "kills": kills[_i(row["player_id"])], "deaths": deaths[_i(row["player_id"])],
        "assists": assists.get(_i(row["player_id"]), 0),
        "opponent_damage": round(opponent_damage[_i(row["player_id"])], 2),
        "team_kills": team_kills[_i(row["player_id"])],
        "suicides": sum(_i(reset["player_id"]) == _i(row["player_id"])
                        and reset["kind"] == "suicide" for reset in death_resets),
        "observed_seconds": participation.get(_i(row["player_id"]), duration),
    } for row in roster_rows]

    life_points, private_lives = derive_life_impact(
        players, samples, flags, frags, captures, profile, topology, death_resets,
        flag_states=flag_states,
    )
    for components in life_points.values():
        components["sequence_continuity_points"] = 0.0
        components["position_points"] = round(sum(
            _f(components[key]) for key in (
                "mid_defense_points", "aggression_points", "enemy_flag_hold_points",
                "active_flag_defense_points", "sequence_continuity_points",
            )
        ), 2)
    half_end_bins = {
        half: max(BIN_SECONDS, math.ceil(max(
            row["game_time"] for row in samples if row["half"] == half
        ) / BIN_SECONDS) * BIN_SECONDS)
        for half in {row["half"] for row in samples}
    }
    team_position_contributions = _aggregate_team_life_timing(
        private_lives, life_points, stable_teams, half_end_bins
    )
    momentum_points, momentum_summary, private_momentum = derive_momentum(
        players, samples, flags, frags, captures, profile, topology, flag_states
    )

    position_halves = {row["half"] for row in samples}
    ownership_reliable = _ownership_is_reliable(flag_states, flags, position_halves)
    if not ownership_reliable:
        for row in cap_breaks:
            row["prevented_capout"] = False
    break_context = bool(cap_breaks) and all(
        row["contester_count"] is not None and row["time_remaining"] is not None
        for row in cap_breaks
    )
    facts = {
        "schema_version": 1,
        "match": {"match_id": match_id, "map_name": map_name,
                  "duration_seconds": duration, "server_id": server_id,
                  "match_type": None if match_row.get("match_type") is None
                  else _i(match_row["match_type"]),
                  "match_type_consistent": _i(match_row.get("distinct_match_types")) == 1
                  and _i(match_row.get("unclassified_halves")) == 0,
                  "unclassified_halves": _i(match_row.get("unclassified_halves")),
                  "is_test_match": match_id.endswith("-TEST"),
                  "source_mode": getattr(db, "source_mode", "lane_b_ephemeral_mysql"),
                  "flag_position_source": flag_position_source,
                  "scoring_iteration": (
                      "v6_schema22_2s" if requires_schema22 else "v5_team_momentum"
                  ),
                  "capture_authorization": capture_authorization},
        "players": players, "frags": frags, "damage_events": damage_events,
        "death_resets": death_resets, "captures": captures, "cap_breaks": cap_breaks,
        "position_points": {str(pid): row["position_points"]
                            for pid, row in sorted(life_points.items())},
        "position_components": {str(pid): row for pid, row in sorted(life_points.items())},
        "team_position_contributions": team_position_contributions,
        "momentum_points": {str(pid): value for pid, value in sorted(momentum_points.items())},
        "momentum_summary": momentum_summary,
        "telemetry_lifecycles": telemetry_lifecycles,
        "reliability": {
            "life_boundaries": bool(frags), "damage_events": bool(raw_damage),
            "capture_events": bool(captures), "ownership": ownership_reliable,
            "map_topology": bool(topology), "break_context": break_context,
            "positions": bool(samples), "flag_positions": bool(flags),
            "life_impact": bool(samples and flags and topology),
            "life_boundaries_inferred": bool(frags),
            "momentum": momentum_summary.get("status") != "disabled",
        },
    }
    private_meta = {
        "classification": "PRIVATE_PLAYER_POSITIONAL_ANALYTICS",
        "retained": False, "position_samples": len(samples),
        "reconstructed_lives": len(private_lives),
        "momentum_private_ticks": len(private_momentum.get("curve_components") or []),
        "grenade_entity_position_rows": len(grenade_entity_rows),
    }
    validate_facts(facts)
    return facts, private_meta


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _privacy_violations(value: Any, path: str = "report") -> list[str]:
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in PUBLIC_FORBIDDEN_KEYS:
                found.append(f"{path}.{key}")
            found.extend(_privacy_violations(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_privacy_violations(child, f"{path}[{index}]"))
    return found


def verify_bundle(
    facts: dict[str, Any], report: dict[str, Any], manifest: dict[str, Any],
    output_dir: Path, *, expected_players: int, profile: dict[str, Any],
) -> dict[str, Any]:
    errors = []
    component_sums_valid = True
    if len(report.get("players") or []) != expected_players:
        errors.append(f"report has {len(report.get('players') or [])} players, expected {expected_players}")
    for player in report.get("players") or []:
        if not math.isclose(_f(player.get("total_points")),
                            _f(player.get("event_points")) + _f(player.get("position_points")),
                            abs_tol=0.03):
            component_sums_valid = False
            errors.append(f"player {player.get('player_id')} component sum mismatch")
        if player.get("impact_index") is None:
            errors.append(f"player {player.get('player_id')} has no overall rating")
    if not math.isclose(sum(_f(row.get("total_points")) for row in report.get("players") or []),
                        _f(report.get("match_total_points")), abs_tol=0.10):
        component_sums_valid = False
        errors.append("match total does not equal player totals")
    momentum_pools_valid = True
    for episode in ((report.get("momentum") or {}).get("episodes") or []):
        if sum(_f(value) for value in (episode.get("allocations") or {}).values()) \
                > _f(episode.get("pool")) + 0.10:
            momentum_pools_valid = False
            errors.append(f"{episode.get('event_id')} allocations exceed its fixed pool")
    privacy = _privacy_violations(report)
    facts_privacy = _privacy_violations(facts, "facts")
    privacy.extend(facts_privacy)
    if privacy:
        errors.append("public report contains private keys: " + ", ".join(privacy[:10]))
    timeline = report.get("points_timeline") or {}
    timeline_privacy = timeline_privacy_violations(timeline)
    if timeline_privacy:
        errors.append("points timeline contains private keys: " + ", ".join(timeline_privacy[:10]))
    conservation = timeline.get("conservation") or {}
    timeline_conservation_valid = bool(timeline) and math.isclose(
        _f(conservation.get("timeline_match_total_points")),
        _f(report.get("match_total_points")), abs_tol=CONSERVATION_TOLERANCE,
    )
    for component, expected in (report.get("component_totals") or {}).items():
        observed = ((conservation.get("component_totals") or {}).get(component) or {}).get("timeline")
        if not math.isclose(_f(observed), _f(expected), abs_tol=CONSERVATION_TOLERANCE):
            timeline_conservation_valid = False
            errors.append(f"points timeline component mismatch: {component}")
    if not timeline_conservation_valid:
        errors.append("points timeline does not conserve the report total")
    manifest_hashes_valid = True
    for item in manifest.get("files") or []:
        path = output_dir / item["path"]
        if not path.is_file() or _sha256(path) != item["sha256"]:
            manifest_hashes_valid = False
            errors.append(f"manifest hash mismatch: {item['path']}")
    required_files = {
        "report.json", "report.md", "report.html", "comparison.json", "comparison.md",
        "ai-request.json", "momentum.svg",
        "points-timeline.json", "points-timeline.svg",
    }
    manifest_files = {item.get("path") for item in manifest.get("files") or []}
    missing_files = sorted(required_files - manifest_files)
    if missing_files:
        errors.append("required report files missing: " + ", ".join(missing_files))
    if (report.get("quality_gates") or {}).get("momentum", {}).get("status") == "DISABLED":
        errors.append("momentum quality gate is disabled")
    if (report.get("quality_gates") or {}).get("position", {}).get("status") != "PASS":
        errors.append("position quality gate did not pass")
    facts_hash = hashlib.sha256(
        (json.dumps(facts, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    ).hexdigest()
    if facts_hash != manifest.get("facts_sha256"):
        errors.append("normalized facts hash does not match the manifest")
    profile_hash = hashlib.sha256(
        (json.dumps(profile, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    ).hexdigest()
    if profile_hash != manifest.get("profile_sha256"):
        errors.append("scoring profile hash does not match the manifest")
    first = score_match(facts, profile)
    second = score_match(facts, profile)
    def semantic(value):
        return json.dumps({k: v for k, v in value.items() if k != "generated_at"},
                          sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False)
    deterministic = hashlib.sha256(semantic(first).encode()).hexdigest() == \
        hashlib.sha256(semantic(second).encode()).hexdigest()
    if not deterministic:
        errors.append("identical facts/profile did not reproduce the semantic report")
    return {
        "schema_version": 1, "status": "PASS" if not errors else "FAIL",
        "checks": {
            "normalized_facts_contract": "PASS",
            "player_count": "PASS" if len(report.get("players") or []) == expected_players else "FAIL",
            "component_sums": "PASS" if component_sums_valid else "FAIL",
            "overall_rating": "PASS" if not any("overall rating" in item for item in errors) else "FAIL",
            "momentum_pool_bounds": "PASS" if momentum_pools_valid else "FAIL",
            "public_privacy": "PASS" if not privacy else "FAIL",
            "points_timeline_privacy": "PASS" if not timeline_privacy else "FAIL",
            "points_timeline_conservation": "PASS" if timeline_conservation_valid else "FAIL",
            "manifest_hashes": "PASS" if manifest_hashes_valid else "FAIL",
            "required_files": "PASS" if not missing_files else "FAIL",
            "position_and_momentum": "PASS" if not any(
                "quality gate" in item for item in errors
            ) else "FAIL",
            "facts_hash": "PASS" if facts_hash == manifest.get("facts_sha256") else "FAIL",
            "profile_hash": "PASS" if profile_hash == manifest.get("profile_sha256") else "FAIL",
            "semantic_determinism": "PASS" if deterministic else "FAIL",
        },
        "errors": errors,
    }


def generate_lane_b_report(
    db, match_id: str, output_dir: Path, *, expected_players: int = 12,
    profile_path: Path = DEFAULT_PROFILE, objectives_path: Path = DEFAULT_OBJECTIVES,
    spatial_catalog_dir: Path | None = None,
) -> dict[str, Any]:
    facts, private_meta = build_facts(
        db, match_id, profile_path=profile_path, objectives_path=objectives_path,
        spatial_catalog_dir=spatial_catalog_dir,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    facts_path = output_dir / "facts.normalized.json"
    facts_path.write_text(
        json.dumps(facts, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    profile = load_profile(profile_path)
    manifest = build_bundle(facts, profile, output_dir)
    report = json.loads((output_dir / "report.json").read_text(encoding="utf-8"))
    verification = verify_bundle(
        facts, report, manifest, output_dir, expected_players=expected_players,
        profile=profile,
    )
    verification["private_derivation"] = private_meta
    (output_dir / "report-verification.json").write_text(
        json.dumps(verification, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    if verification["status"] != "PASS":
        raise ValueError("Lane B report verification failed: " + "; ".join(verification["errors"]))
    return {"facts": facts, "report": report, "manifest": manifest,
            "verification": verification}


def summary_for_lane(result: dict[str, Any], bundle_path: str = "match-report") -> dict[str, Any]:
    report = result["report"]
    return {
        "status": result["verification"]["status"], "profile": report["profile"],
        "bundle_path": bundle_path,
        "normalization": report.get("impact_index"),
        "momentum_points": report["component_totals"].get("momentum_points", 0),
        "players": [{"rank": row["rank"], "name": row["player_name_at_match"],
                     "overall_rating": row["impact_index"],
                     "raw_points": row["total_points"],
                     "momentum_points": row["momentum_points"]}
                    for row in report["players"]],
    }
