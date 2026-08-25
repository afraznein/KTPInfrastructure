#!/usr/bin/env python3
"""Private team-momentum engine with sanitized swing attribution output."""

from __future__ import annotations

import bisect
import math
from collections import Counter, defaultdict
from typing import Any
from xml.sax.saxutils import escape


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


def _stable_team(row: dict[str, Any]) -> int:
    return _i(row.get("momentum_team", row.get("team")))


def _xy(row: dict[str, Any]) -> tuple[float, float]:
    return _f(row.get("pos_x", row.get("x"))), _f(row.get("pos_y", row.get("y")))


def _flag_xy(row: dict[str, Any]) -> tuple[float, float]:
    return _f(row.get("origin_x", row.get("x"))), _f(row.get("origin_y", row.get("y")))


def _flag_name(row: dict[str, Any]) -> str:
    return str(row.get("flag_name", row.get("name", "")))


def _team_ids(samples: list[dict[str, Any]]) -> tuple[int, int] | None:
    values = sorted({_stable_team(row) for row in samples if _stable_team(row) > 0})
    return (values[0], values[1]) if len(values) == 2 else None


def _team_by_player_half(samples: list[dict[str, Any]]) -> dict[tuple[int, int], int]:
    votes: dict[tuple[int, int], Counter[int]] = defaultdict(Counter)
    for row in samples:
        votes[(_i(row.get("half")), _player(row))][_stable_team(row)] += 1
    return {key: count.most_common(1)[0][0] for key, count in votes.items()}


def _roles(topology: dict[str, Any]) -> dict[str, str]:
    return {
        str(topology.get("team1_first") or ""): "team1_first",
        str(topology.get("team1_second") or ""): "team1_second",
        str(topology.get("middle") or ""): "middle",
        str(topology.get("team2_second") or ""): "team2_second",
        str(topology.get("team2_first") or ""): "team2_first",
    }


def _progress(flag_name: str, team: int, team_ids: tuple[int, int],
              topology: dict[str, Any]) -> float:
    order = {
        str(topology.get("team1_first") or ""): 0.0,
        str(topology.get("team1_second") or ""): 0.25,
        str(topology.get("middle") or ""): 0.50,
        str(topology.get("team2_second") or ""): 0.75,
        str(topology.get("team2_first") or ""): 1.0,
    }
    value = order.get(flag_name, 0.5)
    return value if team == team_ids[0] else 1.0 - value


def _nearest(sample: dict[str, Any], flags: list[dict[str, Any]]) -> tuple[str, float]:
    x, y = _xy(sample)
    flag = min(flags, key=lambda row: math.hypot(x - _flag_xy(row)[0], y - _flag_xy(row)[1]))
    fx, fy = _flag_xy(flag)
    return _flag_name(flag), math.hypot(x - fx, y - fy)


def _flag_value(flag_name: str, topology: dict[str, Any], cfg: dict[str, Any]) -> float:
    role = _roles(topology).get(flag_name, "")
    if role == "middle":
        value = _f(cfg.get("middle_flag_value"), 1.5)
    elif role.endswith("second"):
        value = _f(cfg.get("second_flag_value"), 1.25)
    else:
        value = _f(cfg.get("first_flag_value"), 1.0)
    if flag_name in set(topology.get("double_caps", [])):
        value *= _f(cfg.get("double_cap_multiplier"), 1.25)
    return value


def _owner_at(timeline: dict[tuple[int, str], list[tuple[float, int]]],
              half: int, flag_name: str, when: float) -> int | None:
    rows = timeline.get((half, flag_name), [])
    index = bisect.bisect_right(rows, (when, 10**9)) - 1
    return rows[index][1] if index >= 0 else None


def _initial_and_capture_timeline(
    captures: list[dict[str, Any]], flag_states: list[dict[str, Any]] | None,
) -> dict[tuple[int, str], list[tuple[float, int]]]:
    staged: dict[tuple[int, str], dict[float, int]] = defaultdict(dict)
    for row in flag_states or []:
        name = str(row.get("flag_name") or "")
        if name:
            staged[(_i(row.get("half")), name)][_time(row)] = _i(row.get("owner_team"))
    # Canonical captures win if a state snapshot shares the same timestamp.
    for row in captures:
        name = str(row.get("flag_name") or "")
        if name:
            staged[(_i(row.get("half")), name)][_time(row)] = _i(row.get("team"))
    return {key: sorted(values.items()) for key, values in staged.items()}


def _impact_kill_weights(frags: list[dict[str, Any]], teams: dict[tuple[int, int], int]) -> dict[str, float]:
    streak: dict[tuple[int, int], int] = defaultdict(int)
    last_kill: dict[tuple[int, int], float] = {}
    weights = {}
    for row in sorted(frags, key=lambda item: (_i(item.get("half")), _time(item), str(item.get("event_id")))):
        half, killer, victim, when = _i(row.get("half")), _i(row.get("killer_id")), _i(row.get("victim_id")), _time(row)
        streak[(half, victim)] = 0
        key = (half, killer)
        if key in last_kill and when - last_kill[key] <= 5:
            streak[key] += 1
        else:
            streak[key] = 1
        last_kill[key] = when
        weights[str(row.get("event_id"))] = 1.0 + 0.15 * min(max(0, streak[key] - 1), 3)
        row["killer_momentum_team"] = teams.get((half, killer), 0)
    return weights


def derive_momentum(
    players: list[dict[str, Any]], samples: list[dict[str, Any]],
    flags: list[dict[str, Any]], frags: list[dict[str, Any]],
    captures: list[dict[str, Any]], profile: dict[str, Any],
    topology: dict[str, Any], flag_states: list[dict[str, Any]] | None = None,
) -> tuple[dict[int, float], dict[str, Any], dict[str, Any]]:
    """Return player points, public aggregate curve/episodes, and private audit."""
    cfg = profile["momentum"]
    known_players = {_i(row["player_id"]) for row in players}
    team_ids = _team_ids(samples)
    side_values = sorted({_i(row.get("team")) for row in samples if _i(row.get("team")) > 0})
    side_ids = (side_values[0], side_values[1]) if len(side_values) == 2 else None
    if not samples or not flags or not topology or team_ids is None or side_ids is None:
        return ({player_id: 0.0 for player_id in known_players}, {
            "status": "disabled", "curve": [], "episodes": [],
            "ownership_coverage_percent": 0.0,
        }, {"reason": "positions, flags, topology, or two-team identity unavailable"})
    tick = _f(cfg.get("tick_seconds"), 5.0)
    public_step = _f(cfg.get("public_curve_seconds"), 15.0)
    teams = _team_by_player_half(samples)
    side_team_votes: dict[tuple[int, int], Counter[int]] = defaultdict(Counter)
    for row in samples:
        side_team_votes[(_i(row.get("half")), _i(row.get("team")))][_stable_team(row)] += 1
    side_to_team = {
        key: votes.most_common(1)[0][0] for key, votes in side_team_votes.items()
    }
    kill_weights = _impact_kill_weights(frags, teams)
    timeline = _initial_and_capture_timeline(captures, flag_states)
    flag_names = [_flag_name(row) for row in flags]
    flag_values = {name: _flag_value(name, topology, cfg) for name in flag_names}
    total_flag_value = sum(flag_values.values()) or 1.0

    by_bucket: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    by_player_bucket: dict[tuple[int, int, int], dict[str, Any]] = {}
    for row in samples:
        bucket = round(_time(row) / tick)
        half = _i(row.get("half"))
        by_bucket[(half, bucket)].append(row)
        by_player_bucket[(half, bucket, _player(row))] = row
    halves = sorted({_i(row.get("half")) for row in samples if _i(row.get("half")) > 0})
    max_time = {half: max(_time(row) for row in samples if _i(row.get("half")) == half) for half in halves}

    curve_private = []
    coverage_values = []
    for half in halves:
        smoothed = 0.0
        for bucket in range(0, round(max_time[half] / tick) + 1):
            when = bucket * tick
            rows = by_bucket.get((half, bucket), [])
            if not rows:
                continue
            progress = defaultdict(list)
            beyond = Counter()
            for row in rows:
                name, _ = _nearest(row, flags)
                side = _i(row.get("team"))
                team = _stable_team(row)
                value = _progress(name, side, side_ids, topology)
                progress[team].append(value)
                if value > 0.5:
                    beyond[team] += 1
            if not progress[team_ids[0]] or not progress[team_ids[1]]:
                continue
            field = (
                sum(progress[team_ids[0]]) / len(progress[team_ids[0]])
                - sum(progress[team_ids[1]]) / len(progress[team_ids[1]])
            )
            team_size = max(len(progress[team_ids[0]]), len(progress[team_ids[1]]), 1)
            objective_pressure = (beyond[team_ids[0]] - beyond[team_ids[1]]) / team_size

            territory_numerator = 0.0
            known_value = 0.0
            for name in flag_names:
                owner = _owner_at(timeline, half, name, when)
                if owner is None or owner == 0:
                    continue
                value = flag_values[name]
                known_value += value
                stable_owner = side_to_team.get((half, owner))
                if stable_owner is None:
                    continue
                territory_numerator += value * (1 if stable_owner == team_ids[0] else -1)
            territory = territory_numerator / total_flag_value
            coverage = known_value / total_flag_value
            coverage_values.append(coverage)

            combat_sum = 0.0
            manpower_sum = 0.0
            for frag in frags:
                if _i(frag.get("half")) != half:
                    continue
                age = when - _time(frag)
                if not (0 <= age <= 45):
                    continue
                killer_team = _i(frag.get("killer_momentum_team"))
                if killer_team not in team_ids:
                    continue
                sign = 1 if killer_team == team_ids[0] else -1
                weight = kill_weights.get(str(frag.get("event_id")), 1.0)
                combat_sum += sign * weight * math.pow(0.5, age / _f(cfg.get("combat_half_life_seconds"), 15.0))
                manpower_sum += sign * math.pow(0.5, age / _f(cfg.get("manpower_half_life_seconds"), 10.0))
            combat = math.tanh(combat_sum / _f(cfg.get("combat_normalizer"), 3.0))
            manpower = math.tanh(manpower_sum / team_size)
            raw = (
                _f(cfg.get("territory_weight")) * territory
                + _f(cfg.get("field_position_weight")) * field
                + _f(cfg.get("recent_combat_weight")) * combat
                + _f(cfg.get("manpower_weight")) * manpower
                + _f(cfg.get("objective_pressure_weight")) * objective_pressure
            )
            current = 100.0 * math.tanh(raw)
            alpha = _f(cfg.get("smoothing_current_weight"), 0.55)
            smoothed = alpha * current + (1 - alpha) * smoothed
            curve_private.append({
                "half": half, "time": when, "momentum": smoothed,
                "territory": territory, "field_position": field,
                "recent_combat": combat, "manpower": manpower,
                "objective_pressure": objective_pressure,
                "ownership_coverage": coverage,
            })

    by_half_curve = defaultdict(list)
    for row in curve_private:
        by_half_curve[row["half"]].append(row)

    candidates = []
    episode_window = _f(cfg.get("episode_window_seconds"), 40.0)
    for half, curve in by_half_curve.items():
        for end_index, end in enumerate(curve):
            target = end["time"] - episode_window
            start_index = min(range(end_index + 1), key=lambda index: abs(curve[index]["time"] - target))
            start = curve[start_index]
            delta = end["momentum"] - start["momentum"]
            if abs(delta) >= _f(cfg.get("minimum_swing"), 15.0):
                candidates.append({"half": half, "start": start, "end": end,
                                   "team": team_ids[0] if delta > 0 else team_ids[1],
                                   "magnitude": abs(delta), "capture_centered": False})
    before_window = _f(cfg.get("capture_before_seconds"), 20.0)
    after_window = _f(cfg.get("capture_after_seconds"), 20.0)
    for capture in captures:
        curve = by_half_curve.get(_i(capture.get("half")), [])
        if not curve:
            continue
        start = min(curve, key=lambda row: abs(row["time"] - max(0.0, _time(capture) - before_window)))
        end = min(curve, key=lambda row: abs(row["time"] - (_time(capture) + after_window)))
        capture_team = side_to_team.get((_i(capture.get("half")), _i(capture.get("team"))), 0)
        if capture_team not in team_ids:
            continue
        sign = 1 if capture_team == team_ids[0] else -1
        magnitude = (end["momentum"] - start["momentum"]) * sign
        if magnitude >= _f(cfg.get("minimum_swing"), 15.0):
            candidates.append({"half": _i(capture.get("half")), "start": start, "end": end,
                               "team": capture_team, "magnitude": magnitude,
                               "capture_centered": True})

    selected = []
    maximum = _i(cfg.get("maximum_episodes_per_half"), 12)
    for candidate in sorted(candidates, key=lambda row: (-row["magnitude"], not row["capture_centered"])):
        overlap = any(
            other["half"] == candidate["half"]
            and not (candidate["end"]["time"] <= other["start"]["time"]
                     or candidate["start"]["time"] >= other["end"]["time"])
            for other in selected
        )
        count = sum(other["half"] == candidate["half"] for other in selected)
        if not overlap and count < maximum:
            selected.append(candidate)
    selected.sort(key=lambda row: (row["half"], row["start"]["time"]))

    points = defaultdict(float)
    player_cap = _f(cfg.get("player_match_cap"), 600.0)
    public_episodes = []
    private_attribution = []
    for index, episode in enumerate(selected, start=1):
        half, team = episode["half"], episode["team"]
        start_time, end_time = episode["start"]["time"], episode["end"]["time"]
        weights = defaultdict(float)
        evidence = defaultdict(list)
        for frag in frags:
            if (_i(frag.get("half")) == half and _i(frag.get("killer_momentum_team")) == team
                    and start_time <= _time(frag) <= end_time):
                player_id = _i(frag.get("killer_id"))
                closeness = 0.5 + 0.5 * ((_time(frag) - start_time) / max(end_time - start_time, 1.0))
                weights[player_id] += _f(cfg.get("kill_attribution_weight"), 1.0) * closeness * kill_weights.get(str(frag.get("event_id")), 1.0)
                evidence[player_id].append(str(frag.get("event_id")))
        for capture in captures:
            capture_team = side_to_team.get((_i(capture.get("half")), _i(capture.get("team"))), 0)
            if (_i(capture.get("half")) == half and capture_team == team
                    and start_time <= _time(capture) <= end_time):
                for player_id in {_i(value) for value in capture.get("credited_player_ids") or []}:
                    weights[player_id] += _f(cfg.get("capture_credit_weight"), 1.5)
                    evidence[player_id].append(str(capture.get("event_id")))
        start_bucket, end_bucket = round(start_time / tick), round(end_time / tick)
        for player_id in known_players:
            if teams.get((half, player_id)) != team:
                continue
            start_sample = by_player_bucket.get((half, start_bucket, player_id))
            end_sample = by_player_bucket.get((half, end_bucket, player_id))
            if not start_sample or not end_sample:
                continue
            start_name, _ = _nearest(start_sample, flags)
            end_name, _ = _nearest(end_sample, flags)
            start_progress = _progress(start_name, _i(start_sample.get("team")), side_ids, topology)
            end_progress = _progress(end_name, _i(end_sample.get("team")), side_ids, topology)
            weights[player_id] += max(0.0, end_progress - start_progress) * _f(
                cfg.get("forward_progress_weight"), 1.0
            )
            weights[player_id] += max(0.0, end_progress - 0.5) * _f(
                cfg.get("forward_presence_weight"), 0.5
            )
        pool = min(
            _f(cfg.get("episode_pool_cap"), 150.0),
            max(0.0, episode["magnitude"] - _f(cfg.get("minimum_swing"), 15.0))
            * _f(cfg.get("points_per_momentum"), 2.0),
        )
        total_weight = sum(value for player_id, value in weights.items() if player_id in known_players)
        allocations = {}
        if total_weight > 0:
            for player_id, weight in weights.items():
                if player_id not in known_players or weight <= 0:
                    continue
                value = min(
                    pool * weight / total_weight,
                    max(0.0, player_cap - points[player_id]),
                )
                points[player_id] += value
                allocations[str(player_id)] = round(value, 2)
        event_id = f"momentum-h{half}-e{index}"
        public_episodes.append({
            "event_id": event_id, "half": half, "start_time": start_time,
            "end_time": end_time, "team": team,
            "start_momentum": round(episode["start"]["momentum"], 2),
            "end_momentum": round(episode["end"]["momentum"], 2),
            "swing": round(episode["magnitude"], 2), "pool": round(pool, 2),
            "capture_centered": episode["capture_centered"],
            "allocations": allocations,
        })
        private_attribution.append({
            "event_id": event_id, "weights": dict(weights), "evidence": dict(evidence)
        })

    sanitized_points = {player_id: round(min(points[player_id], player_cap), 2) or 0.0
                        for player_id in known_players}
    public_curve = [
        {"half": row["half"], "time": row["time"],
         "momentum": round(row["momentum"], 2)}
        for row in curve_private
        if round(row["time"] / public_step) * public_step == row["time"]
    ]
    public = {
        "status": "experimental_shadow", "team1": team_ids[0], "team2": team_ids[1],
        "scale": {"team1_max": 100, "balanced": 0, "team2_max": -100},
        "ownership_coverage_percent": round(100 * (sum(coverage_values) / len(coverage_values)), 2)
        if coverage_values else 0.0,
        "curve": public_curve, "episodes": public_episodes,
        "component_weights": {
            "territory": _f(cfg.get("territory_weight")),
            "field_position": _f(cfg.get("field_position_weight")),
            "recent_combat": _f(cfg.get("recent_combat_weight")),
            "manpower": _f(cfg.get("manpower_weight")),
            "objective_pressure": _f(cfg.get("objective_pressure_weight")),
        },
    }
    private = {
        "classification": "PRIVATE_PLAYER_POSITIONAL_ANALYTICS",
        "curve_components": curve_private,
        "attribution": private_attribution,
    }
    return sanitized_points, public, private


def render_momentum_svg(momentum: dict[str, Any], match_id: str) -> str:
    """Render the sanitized team-level curve; never accepts player samples."""
    curve = momentum.get("curve") or []
    width, height = 1200, 620
    left, right, top, bottom = 75, 30, 65, 70
    plot_w, plot_h = width - left - right, height - top - bottom
    halves = sorted({_i(row.get("half")) for row in curve})
    half_width = plot_w / max(len(halves), 1)
    paths, labels = [], []
    for half_index, half in enumerate(halves):
        rows = [row for row in curve if _i(row.get("half")) == half]
        max_time = max((_time(row) for row in rows), default=1.0) or 1.0
        points = []
        for row in rows:
            x = left + half_index * half_width + (_time(row) / max_time) * half_width
            y = top + (100.0 - _f(row.get("momentum"))) / 200.0 * plot_h
            points.append(f"{x:.1f},{y:.1f}")
        if points:
            paths.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="#f8fafc" stroke-width="3"/>')
        labels.append(f'<text x="{left + (half_index + .5) * half_width:.1f}" y="{height - 26}" class="axis" text-anchor="middle">Half {half}</text>')
    episode_marks = []
    for episode in sorted(momentum.get("episodes") or [], key=lambda row: -_f(row.get("swing")))[:8]:
        if _i(episode.get("half")) not in halves:
            continue
        half_index = halves.index(_i(episode.get("half")))
        half_rows = [row for row in curve if _i(row.get("half")) == _i(episode.get("half"))]
        max_time = max((_time(row) for row in half_rows), default=1.0) or 1.0
        when = (_f(episode.get("start_time")) + _f(episode.get("end_time"))) / 2.0
        x = left + half_index * half_width + (when / max_time) * half_width
        y = top + (100.0 - _f(episode.get("end_momentum"))) / 200.0 * plot_h
        episode_marks.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#fbbf24"><title>{escape(str(episode.get("event_id")))}: {float(episode.get("swing", 0)):.1f}</title></circle>')
    divider = "" if len(halves) < 2 else f'<line x1="{left + half_width:.1f}" y1="{top}" x2="{left + half_width:.1f}" y2="{top + plot_h}" stroke="#94a3b8" stroke-dasharray="7 7"/>'
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>.title{{font:700 24px system-ui;fill:#f8fafc}}.axis{{font:14px system-ui;fill:#cbd5e1}}.small{{font:12px system-ui;fill:#94a3b8}}</style>
<rect width="100%" height="100%" fill="#0f172a"/><rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h/2}" fill="#1d4ed8" opacity=".24"/><rect x="{left}" y="{top + plot_h/2}" width="{plot_w}" height="{plot_h/2}" fill="#b91c1c" opacity=".24"/>
<text x="{left}" y="35" class="title">Team momentum — {escape(match_id)}</text><text x="{left}" y="54" class="small">Positive: team 1 · Negative: team 2 · Gold markers: largest attributed swings</text>
<line x1="{left}" y1="{top + plot_h/2}" x2="{left + plot_w}" y2="{top + plot_h/2}" stroke="#e2e8f0"/><text x="20" y="{top + 7}" class="axis">+100</text><text x="38" y="{top + plot_h/2 + 5}" class="axis">0</text><text x="23" y="{top + plot_h + 5}" class="axis">−100</text>
{divider}{''.join(paths)}{''.join(episode_marks)}{''.join(labels)}
</svg>'''
