#!/usr/bin/env python3
"""Derive bounded per-life positional impact from private match telemetry.

Raw coordinates and life timelines are private working evidence. The returned
shareable structure contains derived component totals only; callers may retain
the second return value in a separately protected location for audit.
"""

from __future__ import annotations

import bisect
import math
from collections import defaultdict
from typing import Any


PUBLIC_COMPONENTS = (
    "mid_defense_points",
    "aggression_points",
    "enemy_flag_hold_points",
    "active_flag_defense_points",
    "sequence_continuity_points",
)


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


def _time(row: dict[str, Any]) -> float:
    return _f(row.get("time", row.get("game_time")))


def _player(row: dict[str, Any]) -> int:
    return _i(row.get("player_id", row.get("player")))


def _xy(row: dict[str, Any]) -> tuple[float, float]:
    return (
        _f(row.get("pos_x", row.get("x"))),
        _f(row.get("pos_y", row.get("y"))),
    )


def _flag_xy(row: dict[str, Any]) -> tuple[float, float]:
    return (
        _f(row.get("origin_x", row.get("x"))),
        _f(row.get("origin_y", row.get("y"))),
    )


def _flag_name(row: dict[str, Any]) -> str:
    return str(row.get("flag_name", row.get("name", "")))


def _nearest_flag(
    sample: dict[str, Any], flags: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, float]:
    if not flags:
        return None, math.inf
    x, y = _xy(sample)
    flag = min(flags, key=lambda row: math.hypot(x - _flag_xy(row)[0], y - _flag_xy(row)[1]))
    fx, fy = _flag_xy(flag)
    return flag, math.hypot(x - fx, y - fy)


def _team_ids(samples: list[dict[str, Any]]) -> tuple[int, int] | None:
    values = sorted({_i(row.get("team")) for row in samples if _i(row.get("team")) > 0})
    return (values[0], values[1]) if len(values) == 2 else None


def _flag_role(
    flag_name: str, team: int, topology: dict[str, Any], team_ids: tuple[int, int]
) -> str:
    team1, team2 = team_ids
    forward = {
        topology.get("team1_first"): "own_first",
        topology.get("team1_second"): "own_second",
        topology.get("middle"): "middle",
        topology.get("team2_second"): "enemy_second",
        topology.get("team2_first"): "enemy_first",
    }
    role = forward.get(flag_name, "uncategorized")
    if team == team1:
        return role
    if team == team2:
        return {
            "own_first": "enemy_first", "own_second": "enemy_second",
            "middle": "middle", "enemy_second": "own_second",
            "enemy_first": "own_first", "uncategorized": "uncategorized",
        }[role]
    return "uncategorized"


def _owner_at(
    timeline: dict[tuple[int, str], list[tuple[float, int]]],
    half: int, flag_name: str, when: float,
) -> int | None:
    rows = timeline.get((half, flag_name), [])
    index = bisect.bisect_right(rows, (when, 10**9)) - 1
    return rows[index][1] if index >= 0 else None


def _life_index(deaths: dict[tuple[int, int], list[float]], half: int,
                player_id: int, when: float) -> int:
    return bisect.bisect_right(deaths.get((half, player_id), []), when)


def _presence_decay(elapsed: float, cfg: dict[str, Any]) -> float:
    full = _f(cfg.get("unopposed_full_value_seconds"), 30.0)
    reduced = _f(cfg.get("unopposed_reduced_value_seconds"), 90.0)
    if elapsed <= full:
        return 1.0
    if elapsed <= reduced:
        return _f(cfg.get("unopposed_reduced_multiplier"), 0.5)
    return _f(cfg.get("unopposed_floor_multiplier"), 0.25)


def _scale_components(components: dict[str, float], cap: float) -> dict[str, float]:
    total = sum(components.values())
    scale = min(1.0, cap / total) if total > 0 and cap >= 0 else 1.0
    return {key: value * scale for key, value in components.items()}


def derive_life_impact(
    players: list[dict[str, Any]],
    samples: list[dict[str, Any]],
    flags: list[dict[str, Any]],
    frags: list[dict[str, Any]],
    captures: list[dict[str, Any]],
    profile: dict[str, Any],
    topology: dict[str, Any],
    death_resets: list[dict[str, Any]] | None = None,
    flag_states: list[dict[str, Any]] | None = None,
) -> tuple[dict[int, dict[str, float]], list[dict[str, Any]]]:
    """Return sanitized player totals plus private per-life audit records."""
    cfg = profile["life_impact"]
    interval = _f(cfg.get("sample_seconds"), 5.0)
    objective_radius = _f(cfg.get("objective_radius_units"), 512.0)
    territory_radius = _f(cfg.get("territory_radius_units"), 1024.0)
    threat_radius = _f(cfg.get("enemy_threat_radius_units"), 768.0)
    align = _f(cfg.get("sample_alignment_seconds"), 3.0)
    known_players = {_i(row["player_id"]) for row in players}
    team_ids = _team_ids(samples)
    empty = {key: 0.0 for key in PUBLIC_COMPONENTS}
    if not topology or team_ids is None or not flags or not samples:
        return ({player_id: {**empty, "position_points": 0.0}
                 for player_id in known_players}, [])

    samples = sorted(samples, key=lambda row: (_i(row.get("half")), _time(row), _player(row)))
    deaths: dict[tuple[int, int], list[float]] = defaultdict(list)
    for frag in frags:
        deaths[(_i(frag.get("half")), _i(frag.get("victim_id")))].append(_time(frag))
    for reset in death_resets or []:
        deaths[(_i(reset.get("half")), _i(reset.get("player_id")))].append(_time(reset))
    for key in deaths:
        deaths[key] = sorted(set(deaths[key]))

    owner_timeline: dict[tuple[int, str], list[tuple[float, int]]] = defaultdict(list)
    # A capture-only timeline cannot describe flags that have not changed hands
    # yet. Prefer the explicit initial/change stream when it is available, then
    # retain captures as a compatibility source for older fixtures.
    for state in flag_states or []:
        name = str(state.get("flag_name") or "")
        if name:
            owner_timeline[(_i(state.get("half")), name)].append(
                (_time(state), _i(state.get("owner_team")))
            )
    if not flag_states:
        for capture in captures:
            name = str(capture.get("flag_name") or "")
            if name:
                owner_timeline[(_i(capture.get("half")), name)].append(
                    (_time(capture), _i(capture.get("team")))
                )
    for rows in owner_timeline.values():
        rows.sort()

    by_bucket: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    by_player_half: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    life_samples: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        half, player_id = _i(sample.get("half")), _player(sample)
        if player_id not in known_players:
            continue
        bucket = round(_time(sample) / interval)
        by_bucket[(half, bucket)].append(sample)
        by_player_half[(half, player_id)].append(sample)
        life = _life_index(deaths, half, player_id, _time(sample))
        life_samples[(half, player_id, life)].append(sample)

    # Make kill-to-position alignment deterministic and bounded by the telemetry cadence.
    player_times = {
        key: [_time(row) for row in rows] for key, rows in by_player_half.items()
    }

    def nearest_player_sample(half: int, player_id: int, when: float) -> dict[str, Any] | None:
        rows = by_player_half.get((half, player_id), [])
        times = player_times.get((half, player_id), [])
        if not rows:
            return None
        index = bisect.bisect_left(times, when)
        candidates = [i for i in (index - 1, index) if 0 <= i < len(rows)]
        best = min(candidates, key=lambda i: abs(times[i] - when))
        return rows[best] if abs(times[best] - when) <= align else None

    life_kills: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
    for frag in frags:
        half, killer, when = _i(frag.get("half")), _i(frag.get("killer_id")), _time(frag)
        if killer in known_players:
            life = _life_index(deaths, half, killer, when)
            life_kills[(half, killer, life)].append(frag)

    private_lives: list[dict[str, Any]] = []
    totals: dict[int, dict[str, float]] = {player_id: dict(empty) for player_id in known_players}
    for life_key, rows in sorted(life_samples.items()):
        half, player_id, life_index = life_key
        rows.sort(key=_time)
        team = _i(rows[0].get("team"))
        components = dict(empty)
        evidence = {
            "defense_times": [], "cross_mid_time": None, "enemy_flag_time": None,
            "mid_capture_time": None, "enemy_capture_time": None,
        }
        unopposed: dict[str, float] = defaultdict(float)

        for sample in rows:
            flag, distance = _nearest_flag(sample, flags)
            if flag is None:
                continue
            name = _flag_name(flag)
            role = _flag_role(name, team, topology, team_ids)
            when = _time(sample)
            half_bucket = (half, round(when / interval))
            fx, fy = _flag_xy(flag)
            threats = []
            for other in by_bucket[half_bucket]:
                if _i(other.get("team")) == team:
                    continue
                ox, oy = _xy(other)
                enemy_distance = math.hypot(ox - fx, oy - fy)
                if enemy_distance <= threat_radius:
                    threats.append(max(0.0, 1.0 - enemy_distance / threat_radius))
            active = bool(threats)
            threat_weight = min(1.5, sum(threats)) if active else 0.0
            owner = _owner_at(owner_timeline, half, name, when)

            if role == "middle" and owner == team and active and distance <= objective_radius:
                proximity = max(0.0, 1.0 - distance / objective_radius)
                components["mid_defense_points"] += (
                    interval * _f(cfg.get("mid_defense_points_per_second"))
                    * proximity * max(0.5, threat_weight)
                )

            if role in {"enemy_second", "enemy_first"} and distance <= territory_radius:
                proximity = max(0.0, 1.0 - distance / territory_radius)
                pressure = (_f(cfg.get("active_pressure_multiplier"), 1.5) if active
                            else _f(cfg.get("unopposed_aggression_multiplier"), 0.2))
                components["aggression_points"] += (
                    interval * _f(cfg.get("aggression_points_per_second"))
                    * proximity * pressure
                )
                if evidence["cross_mid_time"] is None:
                    evidence["cross_mid_time"] = when
                    components["aggression_points"] += _f(cfg.get("cross_mid_points"))

            if role in {"enemy_second", "enemy_first"} and distance <= objective_radius:
                if active:
                    unopposed[name] = 0.0
                    hold_multiplier = _f(cfg.get("active_pressure_multiplier"), 1.5)
                else:
                    unopposed[name] += interval
                    hold_multiplier = (
                        _f(cfg.get("unopposed_hold_multiplier"), 0.25)
                        * _presence_decay(unopposed[name], cfg)
                    )
                # Holding an enemy-side flag is evidenced either by current
                # friendly ownership or by defenders contesting the pressure.
                if owner == team or active:
                    proximity = max(0.0, 1.0 - distance / objective_radius)
                    components["enemy_flag_hold_points"] += (
                        interval * _f(cfg.get("enemy_flag_hold_points_per_second"))
                        * proximity * hold_multiplier
                    )
                    if evidence["enemy_flag_time"] is None:
                        evidence["enemy_flag_time"] = when
                        components["enemy_flag_hold_points"] += _f(
                            cfg.get("reach_enemy_flag_points")
                        )

        for frag in life_kills.get(life_key, []):
            when = _time(frag)
            sample = nearest_player_sample(half, player_id, when)
            if sample is None:
                continue
            flag, distance = _nearest_flag(sample, flags)
            if flag is None or distance > objective_radius:
                continue
            name = _flag_name(flag)
            role = _flag_role(name, team, topology, team_ids)
            owner = _owner_at(owner_timeline, half, name, when)
            bucket = by_bucket[(half, round(when / interval))]
            fx, fy = _flag_xy(flag)
            threatened = any(
                _i(other.get("team")) != team
                and math.hypot(_xy(other)[0] - fx, _xy(other)[1] - fy) <= threat_radius
                for other in bucket
            )
            if owner != team or not threatened:
                continue
            evidence["defense_times"].append(when)
            if role == "middle":
                components["mid_defense_points"] += _f(
                    cfg.get("mid_defense_kill_points")
                )
            else:
                components["active_flag_defense_points"] += _f(
                    cfg.get("active_flag_defense_kill_points")
                )

        start, end = _time(rows[0]), _time(rows[-1]) + interval
        kills = life_kills.get(life_key, [])
        kill_times = [_time(row) for row in kills]
        credited_captures = []
        for capture in captures:
            when = _time(capture)
            if _i(capture.get("half")) != half or _i(capture.get("team")) != team:
                continue
            if not (start <= when <= end):
                continue
            credited = player_id in {_i(value) for value in capture.get("credited_player_ids") or []}
            contributed = any(0 <= when - kill_time <= 30.0 for kill_time in kill_times)
            if not (credited or contributed):
                continue
            credited_captures.append(capture)
            role = _flag_role(str(capture.get("flag_name") or ""), team, topology, team_ids)
            if role == "middle" and evidence["mid_capture_time"] is None:
                evidence["mid_capture_time"] = when
            if role in {"enemy_second", "enemy_first"} and evidence["enemy_capture_time"] is None:
                evidence["enemy_capture_time"] = when

        sequence = 0.0
        defense_time = min(evidence["defense_times"], default=None)
        mid_capture = evidence["mid_capture_time"]
        crossed = evidence["cross_mid_time"]
        enemy_capture = evidence["enemy_capture_time"]
        if defense_time is not None and mid_capture is not None and defense_time <= mid_capture:
            sequence += _f(cfg.get("defense_to_mid_capture_points"))
        elif defense_time is not None and crossed is not None and defense_time <= crossed:
            sequence += _f(cfg.get("defense_to_forward_push_points"))
        if mid_capture is not None and crossed is not None and mid_capture <= crossed:
            sequence += _f(cfg.get("mid_capture_to_forward_push_points"))
        if crossed is not None and enemy_capture is not None and crossed <= enemy_capture:
            sequence += _f(cfg.get("forward_push_to_enemy_capture_points"))
        components["sequence_continuity_points"] = min(
            sequence, _f(cfg.get("sequence_points_cap_per_life"), 60.0)
        )

        awarded = _scale_components(components, _f(cfg.get("points_cap_per_life"), 200.0))
        for key, value in awarded.items():
            totals[player_id][key] += value
        private_lives.append({
            "half": half, "player_id": player_id, "life_index": life_index,
            "start_time": start, "end_time": end, "sample_count": len(rows),
            "kill_event_ids": [str(row.get("event_id")) for row in kills],
            "capture_event_ids": [str(row.get("event_id")) for row in credited_captures],
            "evidence": evidence,
            "raw_components": {key: round(value, 4) for key, value in components.items()},
            "awarded_components": {key: round(value, 4) for key, value in awarded.items()},
        })

    match_cap = _f(cfg.get("points_cap_per_match"), 1200.0)
    public: dict[int, dict[str, float]] = {}
    for player_id, components in totals.items():
        awarded = _scale_components(components, match_cap)
        public[player_id] = {
            **{key: round(value, 2) or 0.0 for key, value in awarded.items()},
            "position_points": round(sum(awarded.values()), 2) or 0.0,
        }
    return public, private_lives
