#!/usr/bin/env python3
"""Bounded, deterministic match accumulation and AI-review checkpoint builder.

The scorer consumes normalized match facts. Database extraction is deliberately
separate so the same engine can run in CI, a report worker, or the KTP website.
AI output may annotate a deterministic report, but it cannot alter points,
quality gates, privacy classifications, or publication state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import tomllib
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = REPO / "config" / "analytics" / "accumulation_v3_bounded.toml"
COMPONENT_KEYS = (
    "combat_finisher_points",
    "combat_damage_share_points",
    "fallback_assist_points",
    "fallback_damage_points",
    "streak_points",
    "shutdown_points",
    "fast_chain_points",
    "capture_points",
    "conversion_points",
    "cap_break_points",
    "position_points",
    "momentum_points",
)
POSITION_COMPONENT_KEYS = (
    "mid_defense_points",
    "aggression_points",
    "enemy_flag_hold_points",
    "active_flag_defense_points",
    "sequence_continuity_points",
)
AI_FORBIDDEN_KEYS = {
    "points", "score", "total_points", "event_points", "position_points",
    "component_totals", "quality_gates", "publication_state", "publish",
    "player_position", "coordinates", "heatmap", "path", "route",
}


def load_profile(path: Path = DEFAULT_PROFILE) -> dict[str, Any]:
    with path.open("rb") as source:
        profile = tomllib.load(source)
    required = (
        "profile", "combat", "streaks", "fast_chains", "objectives",
        "cap_breaks", "position",
    )
    missing = [section for section in required if section not in profile]
    if missing:
        raise ValueError(f"v3 profile is missing sections: {', '.join(missing)}")
    return profile


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


def _rounded(value: float) -> float:
    return round(value, 2) or 0.0


def normalize_impact_index(
    points_per_minute: float, reference_ppm: float, log_scale: float,
    impact_cfg: dict[str, Any],
) -> float:
    """Normalize the complete accumulated rate; component scores are already summed."""
    center = _f(impact_cfg.get("center_index"), 100.0)
    per_sigma = _f(impact_cfg.get("points_per_robust_sigma"), 30.0)
    minimum = _f(impact_cfg.get("minimum_index"), 25.0)
    maximum = _f(impact_cfg.get("maximum_index"), 175.0)
    if reference_ppm <= 0 or log_scale <= 0:
        raise ValueError("impact normalization requires a positive center and log scale")
    return _rounded(min(maximum, max(minimum,
        center + per_sigma * math.log(max(points_per_minute, 1e-9) / reference_ppm)
        / log_scale
    )))


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_facts(facts: dict[str, Any]) -> None:
    if _i(facts.get("schema_version")) != 1:
        raise ValueError("normalized facts must use schema_version 1")
    match = facts.get("match") or {}
    if not match.get("match_id"):
        raise ValueError("normalized facts require match.match_id")
    players = facts.get("players") or []
    ids = [_i(player.get("player_id")) for player in players]
    if not ids or 0 in ids or len(ids) != len(set(ids)):
        raise ValueError("players require unique positive player_id values")
    known = set(ids)
    for frag in facts.get("frags") or []:
        if _i(frag.get("killer_id")) not in known or _i(frag.get("victim_id")) not in known:
            raise ValueError("frag references a player outside the roster")
        if not frag.get("event_id"):
            raise ValueError("every frag requires a stable event_id")
    position = facts.get("position_points") or {}
    if any(_i(player_id) not in known for player_id in position):
        raise ValueError("position_points references a player outside the roster")
    position_components = facts.get("position_components") or {}
    if any(_i(player_id) not in known for player_id in position_components):
        raise ValueError("position_components references a player outside the roster")
    for raw_player_id, components in position_components.items():
        if any(_f(components.get(key)) < 0 for key in (*POSITION_COMPONENT_KEYS, "position_points")):
            raise ValueError("position_components cannot contain negative points")
        component_sum = sum(_f(components.get(key)) for key in POSITION_COMPONENT_KEYS)
        if not math.isclose(component_sum, _f(components.get("position_points")), abs_tol=0.06):
            raise ValueError(f"position_components do not sum for player {raw_player_id}")
    momentum = facts.get("momentum_points") or {}
    if any(_i(player_id) not in known for player_id in momentum):
        raise ValueError("momentum_points references a player outside the roster")
    if any(_f(value) < 0 for value in momentum.values()):
        raise ValueError("momentum_points cannot contain negative points")


def _reliability(facts: dict[str, Any], key: str, inferred: bool = False) -> bool:
    reliability = facts.get("reliability") or {}
    return bool(reliability[key]) if key in reliability else inferred


def _new_player_result(player: dict[str, Any]) -> dict[str, Any]:
    return {
        "player_id": _i(player["player_id"]),
        "player_name_at_match": player.get("player_name_at_match") or player.get("name"),
        "team_name": player.get("team_name"),
        "kills": _i(player.get("kills")),
        "deaths": _i(player.get("deaths")),
        "assists": _i(player.get("assists")),
        "team_kills": _i(player.get("team_kills")),
        "suicides": _i(player.get("suicides")),
        "opponent_damage": _f(player.get("opponent_damage", player.get("damage_dealt"))),
        "observed_seconds": _f(player.get("observed_seconds")),
        **{key: 0.0 for key in COMPONENT_KEYS},
        **{key: 0.0 for key in POSITION_COMPONENT_KEYS},
    }


def _enemy_frag(frag: dict[str, Any]) -> bool:
    killer = _i(frag.get("killer_id"))
    victim = _i(frag.get("victim_id"))
    killer_team = _i(frag.get("killer_team"))
    victim_team = _i(frag.get("victim_team"))
    return killer > 0 and victim > 0 and killer != victim and (
        killer_team == 0 or victim_team == 0 or killer_team != victim_team
    )


def _damage_for_death(
    frag: dict[str, Any], damage_by_event: dict[str, list[dict[str, Any]]],
    damage_by_life: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    event_id = str(frag.get("event_id") or "")
    life_id = str(frag.get("victim_life_id") or "")
    rows = damage_by_event.get(event_id, [])
    if not rows and life_id:
        rows = damage_by_life.get(life_id, [])
    victim = _i(frag.get("victim_id"))
    victim_team = _i(frag.get("victim_team"))
    return [
        row for row in rows
        if _f(row.get("damage_capped")) > 0
        and _i(row.get("attacker_id")) != victim
        and (
            victim_team == 0 or _i(row.get("attacker_team")) == 0
            or _i(row.get("attacker_team")) != victim_team
        )
    ]


def _fast_chain_bonus(kills: int, cfg: dict[str, Any]) -> float:
    if kills >= 5:
        return _f(cfg.get("bonus_5_plus"))
    return _f(cfg.get(f"bonus_{kills}"))


def _outcome(capture: dict[str, Any], reliability: dict[str, bool]) -> str:
    if bool(capture.get("is_capout")) and reliability["ownership"]:
        return "capout"
    if str(capture.get("flag_role") or "") == "middle" and reliability["map_topology"]:
        return "middle"
    return "flag"


def _conversion_pool(outcome: str, cfg: dict[str, Any]) -> float:
    return _f(cfg.get(f"{outcome}_conversion_pool"))


def _break_points(event: dict[str, Any], cfg: dict[str, Any], context: bool,
                  ownership: bool) -> tuple[float, dict[str, float]]:
    parts = {
        "base": _f(cfg.get("base_points")),
        "urgency": 0.0,
        "contesters": 0.0,
        "last_flag": 0.0,
    }
    if context and event.get("time_remaining") is not None:
        urgent_seconds = max(_f(cfg.get("urgent_seconds"), 3.0), 0.001)
        remaining = max(0.0, _f(event.get("time_remaining")))
        parts["urgency"] = _f(cfg.get("urgency_points_cap")) * max(
            0.0, 1.0 - min(remaining / urgent_seconds, 1.0)
        )
    if context and event.get("contester_count") is not None:
        extras = max(0, _i(event.get("contester_count")) - 1)
        extras = min(extras, _i(cfg.get("extra_contester_count_cap")))
        parts["contesters"] = extras * _f(cfg.get("extra_contester_points"))
    if ownership and bool(event.get("prevented_capout")):
        parts["last_flag"] = _f(cfg.get("validated_last_flag_points"))
    awarded = min(sum(parts.values()), _f(cfg.get("total_points_cap"), math.inf))
    return awarded, {key: _rounded(value) for key, value in parts.items()}


def score_match(facts: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Score normalized facts and return a shareable deterministic report."""
    validate_facts(facts)
    players = {_i(p["player_id"]): _new_player_result(p) for p in facts["players"]}
    roster = {_i(p["player_id"]): p for p in facts["players"]}
    combat_cfg = profile["combat"]
    streak_cfg = profile["streaks"]
    chain_cfg = profile["fast_chains"]
    objective_cfg = profile["objectives"]
    break_cfg = profile["cap_breaks"]
    reliability = {
        "life_boundaries": _reliability(facts, "life_boundaries"),
        "damage_events": _reliability(
            facts, "damage_events", bool(facts.get("damage_events"))
        ),
        "capture_events": _reliability(
            facts, "capture_events", bool(facts.get("captures"))
        ),
        "ownership": _reliability(facts, "ownership"),
        "map_topology": _reliability(facts, "map_topology"),
        "break_context": _reliability(facts, "break_context"),
        "positions": _reliability(
            facts, "positions", bool(facts.get("position_points"))
        ),
        "flag_positions": _reliability(facts, "flag_positions"),
        "life_impact": _reliability(facts, "life_impact"),
        "life_boundaries_inferred": _reliability(facts, "life_boundaries_inferred"),
        "momentum": _reliability(facts, "momentum"),
    }
    momentum_cfg = profile.get("momentum") or {}
    momentum_enabled = bool(momentum_cfg) and reliability["momentum"]
    replace_conversion = momentum_enabled and bool(
        momentum_cfg.get("replace_conversion_points")
    )
    replace_sequence = momentum_enabled and bool(
        momentum_cfg.get("replace_sequence_continuity_points")
    )
    bounded_combat = reliability["life_boundaries"] and reliability["damage_events"]

    damage_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    damage_by_life: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in facts.get("damage_events") or []:
        if row.get("death_event_id"):
            damage_by_event[str(row["death_event_id"])].append(row)
        if row.get("victim_life_id"):
            damage_by_life[str(row["victim_life_id"])].append(row)

    frags = sorted(
        (frag for frag in facts.get("frags") or [] if _enemy_frag(frag)),
        key=lambda row: (_i(row.get("half")), _f(row.get("time")), str(row["event_id"])),
    )
    resets = sorted(
        facts.get("death_resets") or [],
        key=lambda row: (_i(row.get("half")), _f(row.get("time"))),
    )
    reset_index = 0
    streaks: dict[tuple[int, int], int] = defaultdict(int)
    life_tokens: dict[tuple[int, int], int] = defaultdict(int)
    combat_events: list[dict[str, Any]] = []
    finisher = _f(combat_cfg.get("finisher_points"))
    damage_pool = _f(combat_cfg.get("damage_contribution_pool"))

    for frag in frags:
        half = _i(frag.get("half"))
        event_time = _f(frag.get("time"))
        while reset_index < len(resets):
            reset = resets[reset_index]
            reset_key = (_i(reset.get("half")), _f(reset.get("time")))
            if reset_key > (half, event_time):
                break
            reset_player = _i(reset.get("player_id"))
            reset_half = _i(reset.get("half"))
            streaks[(reset_half, reset_player)] = 0
            life_tokens[(reset_half, reset_player)] += 1
            reset_index += 1

        killer = _i(frag["killer_id"])
        victim = _i(frag["victim_id"])
        victim_key = (half, victim)
        killer_key = (half, killer)
        victim_streak = streaks[victim_key]
        streaks[victim_key] = 0
        life_tokens[victim_key] += 1
        streaks[killer_key] += 1
        streak_index = streaks[killer_key]
        contribution: dict[int, float] = defaultdict(float)

        if bounded_combat:
            players[killer]["combat_finisher_points"] += finisher
            contribution[killer] += finisher
            damage_rows = _damage_for_death(frag, damage_by_event, damage_by_life)
            by_attacker: dict[int, float] = defaultdict(float)
            for row in damage_rows:
                attacker = _i(row.get("attacker_id"))
                if attacker in players:
                    by_attacker[attacker] += _f(row.get("damage_capped"))
            total_damage = sum(by_attacker.values())
            if total_damage <= 0:
                by_attacker = {killer: 1.0}
                total_damage = 1.0
            for attacker, damage in by_attacker.items():
                share = damage_pool * damage / total_damage
                players[attacker]["combat_damage_share_points"] += share
                contribution[attacker] += share
        else:
            fallback_kill = _f(combat_cfg.get("fallback_kill_points"))
            players[killer]["combat_finisher_points"] += fallback_kill
            contribution[killer] += fallback_kill

        streak_steps = min(
            max(0, streak_index - 1), _i(streak_cfg.get("finisher_increment_steps_cap"))
        )
        streak_bonus = finisher * _f(
            streak_cfg.get("finisher_increment_per_kill")
        ) * streak_steps
        players[killer]["streak_points"] += streak_bonus

        shutdown = min(
            max(0, victim_streak - _i(streak_cfg.get("shutdown_starts_after")))
            * _f(streak_cfg.get("shutdown_points_per_level")),
            _f(streak_cfg.get("shutdown_points_cap")),
        )
        players[killer]["shutdown_points"] += shutdown
        combat_events.append({
            "event_id": str(frag["event_id"]),
            "half": half,
            "time": event_time,
            "team": _i(frag.get("killer_team")),
            "killer_id": killer,
            "victim_id": victim,
            "streak_index": streak_index,
            "life_token": life_tokens[killer_key],
            "base_contribution": dict(contribution),
            "streak_bonus": _rounded(streak_bonus),
            "shutdown_bonus": _rounded(shutdown),
        })

    if not bounded_combat:
        for player_id, source in roster.items():
            players[player_id]["fallback_assist_points"] = (
                _i(source.get("assists")) * _f(combat_cfg.get("fallback_assist_points"))
            )
            players[player_id]["fallback_damage_points"] = (
                _f(source.get("opponent_damage", source.get("damage_dealt")))
                * _f(combat_cfg.get("fallback_damage_points"))
            )

    # Maximal personal chains: no overlapping 2k/3k awards.
    chain_events: list[dict[str, Any]] = []
    by_life: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
    for event in combat_events:
        by_life[(event["half"], event["killer_id"], event["life_token"])].append(event)
    event_chain_size: dict[str, int] = {}
    for (_, player_id, _), events in sorted(by_life.items()):
        events.sort(key=lambda row: row["time"])
        chains: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for event in events:
            if current and event["time"] - current[-1]["time"] > _f(
                chain_cfg.get("max_personal_gap_seconds"), 5.0
            ):
                chains.append(current)
                current = []
            current.append(event)
        if current:
            chains.append(current)
        for chain in chains:
            if len(chain) < _i(chain_cfg.get("minimum_kills"), 2):
                continue
            bonus = _fast_chain_bonus(len(chain), chain_cfg)
            players[player_id]["fast_chain_points"] += bonus
            chain_id = f"h{chain[0]['half']}-p{player_id}-t{chain[0]['time']:.3f}"
            for event in chain:
                event_chain_size[event["event_id"]] = len(chain)
            chain_events.append({
                "chain_id": chain_id,
                "player_id": player_id,
                "half": chain[0]["half"],
                "kills": len(chain),
                "elapsed_seconds": _rounded(chain[-1]["time"] - chain[0]["time"]),
                "bonus": _rounded(bonus),
                "event_ids": [event["event_id"] for event in chain],
            })

    objective_events: list[dict[str, Any]] = []
    captures = sorted(
        facts.get("captures") or [],
        key=lambda row: (_i(row.get("half")), _f(row.get("time")), str(row.get("event_id"))),
    ) if reliability["capture_events"] else []
    capture_context: dict[str, dict[str, Any]] = {}
    for index, capture in enumerate(captures, start=1):
        event_id = str(capture.get("event_id") or f"capture-{index}")
        credited = sorted({
            _i(player_id) for player_id in capture.get("credited_player_ids") or []
            if _i(player_id) in players
        })
        pool = _f(objective_cfg.get("capture_event_pool"))
        share = pool / len(credited) if credited else 0.0
        for player_id in credited:
            players[player_id]["capture_points"] += share
        outcome = _outcome(capture, reliability)
        capture_context[event_id] = {
            **capture,
            "event_id": event_id,
            "outcome": outcome,
            "credited_player_ids": credited,
        }
        objective_events.append({
            "event_id": event_id,
            "half": _i(capture.get("half")),
            "time": _f(capture.get("time")),
            "team": _i(capture.get("team")),
            "flag_name": capture.get("flag_name"),
            "outcome": outcome,
            "capture_pool": _rounded(pool),
            "credited_players": len(credited),
            "capture_share": _rounded(share),
        })

    # Assign each death to only its highest-value following capture. This is
    # what makes capout supersede an overlapping ordinary/mid conversion.
    outcome_rank = {"flag": 1, "middle": 2, "capout": 3}
    window = _f(objective_cfg.get("conversion_window_seconds"), 30.0)
    assigned: dict[str, str] = {}
    for event in combat_events:
        candidates = []
        for event_id, capture in capture_context.items():
            delta = _f(capture.get("time")) - event["time"]
            if (
                _i(capture.get("half")) == event["half"]
                and _i(capture.get("team")) == event["team"]
                and 0 <= delta <= window
            ):
                candidates.append((outcome_rank[capture["outcome"]], -delta, event_id))
        if candidates:
            assigned[event["event_id"]] = max(candidates)[2]

    conversion_events: list[dict[str, Any]] = []
    by_event_id = {event["event_id"]: event for event in combat_events}
    for event_id, capture in capture_context.items():
        deaths = [
            by_event_id[death_id] for death_id, target in assigned.items()
            if target == event_id
        ]
        pool = 0.0 if replace_conversion else _conversion_pool(capture["outcome"], objective_cfg)
        weights: dict[int, float] = defaultdict(float)
        for death in deaths:
            decay = max(0.0, 1.0 - ((_f(capture.get("time")) - death["time"]) / window))
            chain_size = event_chain_size.get(death["event_id"], 1)
            speed_weight = 1.0 + 0.10 * max(0, chain_size - 1)
            for player_id, contribution in death["base_contribution"].items():
                weights[_i(player_id)] += _f(contribution) * decay * speed_weight
        total_weight = sum(weights.values())
        awarded = pool if total_weight > 0 else 0.0
        allocations = {}
        if total_weight > 0:
            for player_id, weight in weights.items():
                share = pool * weight / total_weight
                players[player_id]["conversion_points"] += share
                allocations[str(player_id)] = _rounded(share)
        distinct_killers = sorted({death["killer_id"] for death in deaths})
        conversion_events.append({
            "capture_event_id": event_id,
            "outcome": capture["outcome"],
            "pool": _rounded(pool),
            "awarded": _rounded(awarded),
            "qualifying_deaths": len(deaths),
            "team_push": len(deaths) >= 3 and len(distinct_killers) >= 2,
            "participant_count": len(weights),
            "allocations": allocations,
            "replaced_by_momentum": replace_conversion,
        })

    break_events = []
    for index, event in enumerate(facts.get("cap_breaks") or [], start=1):
        player_id = _i(event.get("player_id"))
        if player_id not in players:
            continue
        awarded, parts = _break_points(
            event, break_cfg, reliability["break_context"], reliability["ownership"]
        )
        players[player_id]["cap_break_points"] += awarded
        break_events.append({
            "event_id": str(event.get("event_id") or f"break-{index}"),
            "player_id": player_id,
            "points": _rounded(awarded),
            "components": parts,
            "context_reliable": reliability["break_context"],
            "ownership_reliable": reliability["ownership"],
        })

    position_enabled = reliability["positions"] and reliability["flag_positions"]
    if position_enabled:
        component_rows = facts.get("position_components") or {}
        for raw_player_id, value in (facts.get("position_points") or {}).items():
            player_id = _i(raw_player_id)
            if player_id in players:
                players[player_id]["position_points"] = max(0.0, _f(value))
        for raw_player_id, components in component_rows.items():
            player_id = _i(raw_player_id)
            if player_id not in players:
                continue
            for key in POSITION_COMPONENT_KEYS:
                players[player_id][key] = max(0.0, _f(components.get(key)))
            if replace_sequence:
                players[player_id]["sequence_continuity_points"] = 0.0
            players[player_id]["position_points"] = sum(
                players[player_id][key] for key in POSITION_COMPONENT_KEYS
            )
    if momentum_enabled:
        for raw_player_id, value in (facts.get("momentum_points") or {}).items():
            player_id = _i(raw_player_id)
            if player_id in players:
                players[player_id]["momentum_points"] = max(0.0, _f(value))

    duration = max(0.0, _f((facts.get("match") or {}).get("duration_seconds")))
    output_players = []
    for player_id, result in players.items():
        rounded = {key: _rounded(_f(result[key])) for key in COMPONENT_KEYS}
        rounded_position = {
            key: _rounded(_f(result[key])) for key in POSITION_COMPONENT_KEYS
        }
        event_points = sum(rounded[key] for key in COMPONENT_KEYS if key != "position_points")
        total_points = event_points + rounded["position_points"]
        observed = _f(roster[player_id].get("observed_seconds"), duration)
        output_players.append({
            **{key: value for key, value in result.items() if key not in COMPONENT_KEYS},
            **rounded,
            **rounded_position,
            "event_points": _rounded(event_points),
            "total_points": _rounded(total_points),
            "points_per_minute": _rounded(total_points / (observed / 60.0)) if observed > 0 else None,
            "observed_seconds": _rounded(observed),
            "participation_percent": _rounded(100.0 * observed / duration)
            if duration > 0 else None,
        })
    impact_cfg = profile.get("impact_index") or {}
    reference_minimum_observed = max(
        _f(impact_cfg.get("minimum_observed_seconds"), 300.0),
        duration * _f(impact_cfg.get("reference_minimum_match_fraction"), 0.0),
    )
    eligible_rates = [
        _f(player["points_per_minute"]) for player in output_players
        if player["points_per_minute"] is not None
        and _f(roster[player["player_id"]].get("observed_seconds"), duration)
        >= reference_minimum_observed
    ]
    match_facts = facts.get("match") or {}
    explicit_reference = _f(match_facts.get("impact_index_reference_ppm"))
    explicit_log_scale = _f(match_facts.get("impact_index_log_scale"))
    reference_ppm = explicit_reference or (
        statistics.median(eligible_rates) if eligible_rates else 0.0
    )
    centered_logs = sorted(
        math.log(rate / reference_ppm) for rate in eligible_rates
        if rate > 0 and reference_ppm > 0
    )
    if len(centered_logs) >= 4:
        midpoint = len(centered_logs) // 2
        lower = centered_logs[:midpoint]
        upper = centered_logs[-midpoint:]
        observed_log_scale = (
            statistics.median(upper) - statistics.median(lower)
        ) / 1.349
    else:
        observed_log_scale = 0.0
    minimum_log_scale = _f(impact_cfg.get("minimum_log_scale"), 0.15)
    log_scale = max(
        explicit_log_scale or observed_log_scale
        or _f(impact_cfg.get("fallback_log_scale"), 0.35),
        minimum_log_scale,
    )
    center_index = _f(impact_cfg.get("center_index"), 100.0)
    points_per_sigma = _f(impact_cfg.get("points_per_robust_sigma"), 30.0)
    minimum_index = _f(impact_cfg.get("minimum_index"), 25.0)
    maximum_index = _f(impact_cfg.get("maximum_index"), 175.0)
    for player in output_players:
        observed = _f(roster[player["player_id"]].get("observed_seconds"), duration)
        player["impact_index"] = (
            normalize_impact_index(
                _f(player["points_per_minute"]), reference_ppm, log_scale, impact_cfg
            )
            if impact_cfg and reference_ppm > 0 and player["points_per_minute"] is not None
            and observed >= _f(impact_cfg.get("minimum_observed_seconds"), 300.0)
            else None
        )
    output_players.sort(key=lambda row: (
        -(row["impact_index"] if row["impact_index"] is not None else -1)
        if impact_cfg else -row["total_points"],
        -row["total_points"], row.get("player_name_at_match") or "",
    ))
    for rank, player in enumerate(output_players, start=1):
        player["rank"] = rank

    component_totals = {
        key: _rounded(sum(_f(player[key]) for player in output_players))
        for key in COMPONENT_KEYS
    }
    grand_total = sum(component_totals.values())
    component_shares = {
        key: _rounded(100.0 * value / grand_total) if grand_total > 0 else 0.0
        for key, value in component_totals.items()
    }
    position_component_totals = {
        key: _rounded(sum(_f(player[key]) for player in output_players))
        for key in POSITION_COMPONENT_KEYS
    }
    quality_gates = {
        "match_classification": {
            "status": "PASS" if (facts.get("match") or {}).get("match_type_consistent")
            else "WARN",
            "detail": "All halves carry one consistent match type."
            if (facts.get("match") or {}).get("match_type_consistent")
            else "One or more halves are unclassified or use inconsistent match types.",
        },
        "bounded_combat": {
            "status": "PASS" if bounded_combat else "WARN",
            "detail": "60/40 victim-life contribution pools enabled."
            if bounded_combat else "Life/damage evidence incomplete; 100/50/0.02 fallback enabled.",
        },
        "capture_pools": {
            "status": "PASS" if reliability["capture_events"] else "DISABLED",
            "detail": "Unique capture events split fixed pools."
            if reliability["capture_events"] else "Capture-event evidence unavailable.",
        },
        "mid_context": {
            "status": "PASS" if reliability["map_topology"] else "DISABLED",
            "detail": "Reviewed map topology available."
            if reliability["map_topology"] else "Middle flags are treated as ordinary flags.",
        },
        "capout_context": {
            "status": "PASS" if reliability["ownership"] else "DISABLED",
            "detail": "Ownership evidence is trusted."
            if reliability["ownership"] else "Capout and last-flag bonuses are disabled.",
        },
        "position": {
            "status": "PASS" if position_enabled else "DISABLED",
            "detail": (
                "Derived per-life impact components included; underlying movement remains private."
                if reliability["life_impact"]
                else "Derived private position points included."
            )
            if position_enabled else "Position samples or objective coordinates are unavailable.",
        },
        "life_reconstruction": {
            "status": "WARN" if reliability["life_boundaries_inferred"] else (
                "PASS" if reliability["life_impact"] else "DISABLED"
            ),
            "detail": (
                "Lives were reconstructed from deaths and the next observed position sample."
                if reliability["life_boundaries_inferred"]
                else "Explicit life boundaries were available."
                if reliability["life_impact"] else "Per-life impact was not calculated."
            ),
        },
        "break_context": {
            "status": "PASS" if reliability["break_context"] else "WARN",
            "detail": "Urgency and contester evidence included."
            if reliability["break_context"] else "Only the bounded base break value is used.",
        },
        "momentum": {
            "status": "PASS" if momentum_enabled and reliability["ownership"] else (
                "WARN" if momentum_enabled else "DISABLED"
            ),
            "detail": "Aggregate team momentum and bounded swing attribution included."
            if momentum_enabled and reliability["ownership"] else (
                "Positions, combat, and swings are included, but territory ownership is incomplete."
                if momentum_enabled else "Momentum facts unavailable or profile does not enable them."
            ),
        },
        "impact_index": {
            "status": "PASS" if explicit_reference > 0 and explicit_log_scale > 0 else (
                "WARN" if impact_cfg and reference_ppm > 0 else "DISABLED"
            ),
            "detail": "Qualified corpus center and dispersion supplied."
            if explicit_reference > 0 and explicit_log_scale > 0 else "Provisional match center/dispersion; not cross-match comparable."
            if impact_cfg and reference_ppm > 0 else "Overall rating not enabled.",
        },
    }
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "experimental_shadow",
        "publication_state": "DRAFT",
        "profile": profile["profile"]["name"],
        "profile_status": profile["profile"]["status"],
        "match": facts["match"],
        "privacy": {
            "individual_positions": "private_not_embedded",
            "shareable_position_field": "derived_position_points_only",
        },
        "quality_gates": quality_gates,
        "component_totals": component_totals,
        "component_shares_percent": component_shares,
        "position_component_totals": position_component_totals,
        "life_impact_contract": profile.get("life_impact"),
        "momentum_contract": profile.get("momentum"),
        "momentum": facts.get("momentum_summary") if momentum_enabled else None,
        "impact_index": {
            "center_index": center_index,
            "points_per_robust_sigma": points_per_sigma,
            "minimum_index": minimum_index,
            "maximum_index": maximum_index,
            "reference_points_per_minute": _rounded(reference_ppm),
            "reference_log_scale": _rounded(log_scale),
            "reference_source": "qualified_corpus"
            if explicit_reference > 0 and explicit_log_scale > 0
            else "provisional_match_robust",
            "reference_minimum_observed_seconds": _rounded(reference_minimum_observed),
        } if impact_cfg and reference_ppm > 0 else None,
        "match_total_points": _rounded(grand_total),
        "players": output_players,
        "events": {
            "fast_chains": chain_events,
            "objectives": objective_events,
            "conversions": conversion_events,
            "cap_breaks": break_events,
            "momentum_swings": (facts.get("momentum_summary") or {}).get("episodes", [])
            if momentum_enabled else [],
        },
        "descriptive_only": {
            "team_kills": sum(_i(player.get("team_kills")) for player in roster.values()),
            "suicides": sum(_i(player.get("suicides")) for player in roster.values()),
            "penalty_points": 0.0,
        },
    }


def build_ai_checkpoint(report: dict[str, Any]) -> dict[str, Any]:
    """Create a sanitized, hash-bound request for optional AI annotations."""
    deterministic = {
        "profile": report["profile"],
        "match": report["match"],
        "quality_gates": report["quality_gates"],
        "component_totals": report["component_totals"],
        "players": [
            {
                "player_id": player["player_id"],
                "player_name_at_match": player["player_name_at_match"],
                "rank": player["rank"],
                "overall_rating": player.get("impact_index"),
                "total_points": player["total_points"],
                "position_points": player["position_points"],
                "momentum_points": player["momentum_points"],
                "kills": player["kills"],
                "assists": player["assists"],
            }
            for player in report["players"]
        ],
        "events": report["events"],
    }
    return {
        "schema_version": 1,
        "checkpoint": "post_deterministic_scoring",
        "input_sha256": _canonical_hash(deterministic),
        "privacy": "shareable_aggregate_and_event_ledger_only",
        "deterministic_report": deterministic,
        "requested_tasks": [
            "identify explainable match storylines supported by event IDs",
            "flag possible data anomalies without changing quality gates",
            "suggest calibration questions without proposing an official rating",
            "write a concise draft summary for human review",
        ],
        "prohibited_tasks": [
            "change or invent points",
            "override a reliability gate",
            "infer or expose individual movement",
            "publish the report",
            "write to a production database",
        ],
        "response_contract": {
            "input_sha256": "must exactly match this request",
            "summary": "string",
            "storylines": [{"title": "string", "evidence_event_ids": ["string"]}],
            "anomalies": [{"severity": "info|warn|block", "detail": "string", "evidence_event_ids": ["string"]}],
            "calibration_questions": ["string"],
            "publication_recommendation": "review|hold",
        },
    }


def validate_ai_response(request: dict[str, Any], response: dict[str, Any]) -> None:
    required = {
        "input_sha256", "summary", "storylines", "anomalies",
        "calibration_questions", "publication_recommendation",
    }
    if set(response) != required:
        raise ValueError("AI response fields do not match the versioned contract")
    if response.get("input_sha256") != request.get("input_sha256"):
        raise ValueError("AI response does not match the deterministic input hash")
    if response.get("publication_recommendation") not in {"review", "hold"}:
        raise ValueError("AI publication recommendation must be review or hold")
    if not isinstance(response.get("summary"), str):
        raise ValueError("AI summary must be a string")
    if not isinstance(response.get("calibration_questions"), list) or not all(
        isinstance(item, str) for item in response["calibration_questions"]
    ):
        raise ValueError("AI calibration_questions must be strings")

    event_ids: set[str] = set()
    events = request.get("deterministic_report", {}).get("events", {})
    for chain in events.get("fast_chains") or []:
        event_ids.add(str(chain.get("chain_id")))
        event_ids.update(str(value) for value in chain.get("event_ids") or [])
    for event in events.get("objectives") or []:
        event_ids.add(str(event.get("event_id")))
    for event in events.get("conversions") or []:
        event_ids.add(str(event.get("capture_event_id")))
    for event in events.get("cap_breaks") or []:
        event_ids.add(str(event.get("event_id")))
    for event in events.get("momentum_swings") or []:
        event_ids.add(str(event.get("event_id")))

    if not isinstance(response.get("storylines"), list):
        raise ValueError("AI storylines must be a list")
    for storyline in response["storylines"]:
        if not isinstance(storyline, dict) or set(storyline) != {
            "title", "evidence_event_ids"
        }:
            raise ValueError("AI storyline fields do not match the contract")
        if not isinstance(storyline["title"], str):
            raise ValueError("AI storyline title must be a string")
        if any(str(value) not in event_ids for value in storyline["evidence_event_ids"]):
            raise ValueError("AI storyline cites an unknown event ID")

    if not isinstance(response.get("anomalies"), list):
        raise ValueError("AI anomalies must be a list")
    for anomaly in response["anomalies"]:
        if not isinstance(anomaly, dict) or set(anomaly) != {
            "severity", "detail", "evidence_event_ids"
        }:
            raise ValueError("AI anomaly fields do not match the contract")
        if anomaly["severity"] not in {"info", "warn", "block"}:
            raise ValueError("AI anomaly severity is invalid")
        if not isinstance(anomaly["detail"], str):
            raise ValueError("AI anomaly detail must be a string")
        if any(str(value) not in event_ids for value in anomaly["evidence_event_ids"]):
            raise ValueError("AI anomaly cites an unknown event ID")

    def walk(value: Any, path: str = "root") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in AI_FORBIDDEN_KEYS:
                    raise ValueError(f"AI response contains prohibited key {path}.{key}")
                walk(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")

    walk(response)


def render_markdown(report: dict[str, Any]) -> str:
    is_v5 = report.get("profile") == "accumulation_v5_momentum"
    lines = [
        f"# Bounded accumulation shadow — {report['match']['match_id']}", "",
        f"Profile: `{report['profile']}` · State: **{report['publication_state']}** · "
        "Experimental, not KTPR", "",
        "No penalties are applied. Teamkills, suicides, and deaths are descriptive only.", "",
        ("The overall rating is normalized only after every component below—including "
         "momentum—is added to the complete raw accumulated score." if is_v5 else ""), "",
        "| Rank | Player | Overall rating | Minutes | Raw accumulated | Combat | Streak/context | Objectives | Life position | Momentum |"
        if is_v5 else "| Rank | Player | Combat | Streak/context | Objectives | Position | Total | Pts/min |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|"
        if is_v5 else "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for player in report["players"]:
        combat = player["combat_finisher_points"] + player["combat_damage_share_points"] + player["fallback_assist_points"] + player["fallback_damage_points"]
        context = player["streak_points"] + player["shutdown_points"] + player["fast_chain_points"]
        objective = player["capture_points"] + player["conversion_points"] + player["cap_break_points"]
        ppm = "—" if player["points_per_minute"] is None else f"{player['points_per_minute']:.2f}"
        if is_v5:
            impact = "—" if player["impact_index"] is None else f"{player['impact_index']:.1f}"
            lines.append(
                f"| {player['rank']} | {player['player_name_at_match']} | **{impact}** | "
                f"{player['observed_seconds'] / 60:.1f} | {player['total_points']:.2f} | "
                f"{combat:.2f} | {context:.2f} | "
                f"{objective:.2f} | {player['position_points']:.2f} | "
                f"{player['momentum_points']:.2f} |"
            )
        else:
            lines.append(
                f"| {player['rank']} | {player['player_name_at_match']} | {combat:.2f} | "
                f"{context:.2f} | {objective:.2f} | {player['position_points']:.2f} | "
                f"{player['total_points']:.2f} | {ppm} |"
            )
    lines += ["", "## Reliability gates", "", "| Component | Status | Detail |", "|---|---|---|"]
    for name, gate in report["quality_gates"].items():
        lines.append(f"| {name} | {gate['status']} | {gate['detail']} |")
    lines += [
        "", "## Component totals", "", "| Component | Points | Share |",
        "|---|---:|---:|",
    ]
    for key, value in report["component_totals"].items():
        lines.append(f"| {key} | {value:.2f} | {report['component_shares_percent'][key]:.2f}% |")
    life_cfg = report.get("life_impact_contract")
    if life_cfg:
        position_totals = report["position_component_totals"]
        lines += [
            "", "## Per-life positional impact", "",
            "Only the following derived totals are shareable. Coordinates, routes, sample "
            "histories, and individual life timelines remain private.", "",
            "| Component | Match points | Meaning |",
            "|---|---:|---|",
            f"| Mid defense | {position_totals['mid_defense_points']:.2f} | "
            "Presence and kills while defending owned mid under nearby enemy pressure. |",
            f"| Aggression | {position_totals['aggression_points']:.2f} | "
            "Crossing beyond mid and sustaining forward pressure. |",
            f"| Enemy-flag hold | {position_totals['enemy_flag_hold_points']:.2f} | "
            "Consequential presence at flags beyond mid, with opposition or friendly ownership. |",
            f"| Active flag defense | {position_totals['active_flag_defense_points']:.2f} | "
            "Kills near a currently owned, actively threatened non-mid flag. |",
            f"| Sequence continuity | {position_totals['sequence_continuity_points']:.2f} | "
            + ("Replaced by the v5 momentum pool to avoid duplicate push rewards. |"
               if is_v5 else "Same-life defense, capture, forward-push, and enemy-capture transitions. |"),
            "", "### Player positional components", "",
            "| Rank | Player | Mid defense | Aggression | Enemy-flag hold | Active flag defense | Sequence | Position total |",
            "|---:|---|---:|---:|---:|---:|---:|---:|",
        ]
        for player in report["players"]:
            lines.append(
                f"| {player['rank']} | {player['player_name_at_match']} | "
                f"{player['mid_defense_points']:.2f} | {player['aggression_points']:.2f} | "
                f"{player['enemy_flag_hold_points']:.2f} | "
                f"{player['active_flag_defense_points']:.2f} | "
                f"{player['sequence_continuity_points']:.2f} | "
                f"{player['position_points']:.2f} |"
            )
        lines += [
            "", "### Exact positional calculation", "",
            f"Samples use a {life_cfg['sample_seconds']:.0f}-second cadence. Mid defense is "
            f"`{life_cfg['mid_defense_points_per_second']:.2f} × seconds × proximity × threat`; "
            f"aggression beyond mid is `{life_cfg['aggression_points_per_second']:.2f} × seconds × "
            "proximity × pressure`; and enemy-flag holding is "
            f"`{life_cfg['enemy_flag_hold_points_per_second']:.2f} × seconds × proximity × pressure`.", "",
            f"Active enemy pressure applies `{life_cfg['active_pressure_multiplier']:.2f}×`. "
            f"Unopposed aggression uses `{life_cfg['unopposed_aggression_multiplier']:.2f}×`; "
            f"unopposed enemy-flag holding uses `{life_cfg['unopposed_hold_multiplier']:.2f}×` "
            "and decays further with time. This preserves a small positive value without "
            "letting passive presence dominate.", "",
            f"A first crossing beyond mid adds {life_cfg['cross_mid_points']:.0f} points; first "
            f"arrival at an enemy-side flag adds {life_cfg['reach_enemy_flag_points']:.0f}. "
            f"A qualifying mid-defense kill adds {life_cfg['mid_defense_kill_points']:.0f}; "
            f"another actively defended flag kill adds {life_cfg['active_flag_defense_kill_points']:.0f}.", "",
            "The v4 continuity baseline rewarded verified same-life state changes, not the kills again: "
            f"defense→mid capture {life_cfg['defense_to_mid_capture_points']:.0f}, "
            f"defense→forward push {life_cfg['defense_to_forward_push_points']:.0f}, "
            f"mid capture→forward push {life_cfg['mid_capture_to_forward_push_points']:.0f}, and "
            f"forward push→enemy capture {life_cfg['forward_push_to_enemy_capture_points']:.0f}. "
            f"Continuity is capped at {life_cfg['sequence_points_cap_per_life']:.0f} per life, "
            f"all positional impact at {life_cfg['points_cap_per_life']:.0f} per life, and "
            f"{life_cfg['points_cap_per_match']:.0f} per player per match.", "",
            "No positional component can be negative. An immediate death normally earns zero "
            "positional impact rather than a penalty.", "",
            "### Evidence limitations", "",
            "Per-life reconstruction is explicitly labeled when spawn/life rows are absent. "
            "Ownership-dependent defense is scored only after a canonical capture establishes "
            "the owner of that flag; an unreliable initial snapshot is never filled in by "
            "assumption. A zero component can therefore mean that the required evidence was "
            "unavailable, not that the underlying behavior never occurred.", "",
        ]
        if is_v5:
            momentum = report.get("momentum") or {}
            impact_index = report.get("impact_index") or {}
            lines += [
                "", "## Team momentum over time", "",
                "[Open the full-size momentum graph](momentum.svg)", "",
                f"Positive favors team `{momentum.get('team1', 'team 1')}`; negative favors "
                f"team `{momentum.get('team2', 'team 2')}`. Known flag ownership covered "
                f"{momentum.get('ownership_coverage_percent', 0):.1f}% of the weighted timeline.", "",
                "Every five seconds, the private engine combines territory (35%), aggregate field "
                "position (25%), recent impactful kills (20%), temporary manpower (10%), and "
                "pressure beyond mid (10%), then smooths it onto a −100 to +100 scale. The public "
                "curve is team aggregate only; it contains no player routes or coordinates.", "",
                "A qualifying swing uses `min(150, max(0, swing − 15) × 2)`. Recent kills, capture "
                "credit, and private forward progress divide that fixed, non-negative pool. V5 "
                "replaces conversion and sequence-continuity awards with this one pool so a push "
                "is not counted repeatedly.", "",
                "| Swing | Half/time | Team | Momentum | Pool | Top allocations |",
                "|---|---|---:|---:|---:|---|",
            ]
            names = {str(row["player_id"]): row["player_name_at_match"] for row in report["players"]}
            for episode in sorted(momentum.get("episodes") or [], key=lambda row: -_f(row.get("swing")))[:10]:
                allocations = sorted((episode.get("allocations") or {}).items(), key=lambda item: -_f(item[1]))[:4]
                allocation_text = ", ".join(
                    f"{names.get(player_id, player_id)} {_f(value):.1f}"
                    for player_id, value in allocations
                ) or "none"
                lines.append(
                    f"| {episode['event_id']} | H{episode['half']} "
                    f"{episode['start_time']:.0f}–{episode['end_time']:.0f}s | "
                    f"{episode['team']} | {episode['start_momentum']:.1f} → "
                    f"{episode['end_momentum']:.1f} | {episode['pool']:.1f} | "
                    f"{allocation_text} |"
                )
            lines += [
                "", "## Overall accumulated-score normalization", "",
                f"The provisional qualified-player match median "
                f"({impact_index.get('reference_points_per_minute', 0):.2f} raw points/minute) "
                f"is displayed as {impact_index.get('center_index', 100):.0f}. Formula: "
                f"`100 + {impact_index.get('points_per_robust_sigma', 30):.0f} × "
                f"ln(player raw points/minute ÷ reference) ÷ {impact_index.get('reference_log_scale', 1):.2f}`. "
                f"The display is bounded to {impact_index.get('minimum_index', 25):.0f}–"
                f"{impact_index.get('maximum_index', 175):.0f}. Raw deterministic points remain in "
                "the audit column. Until a real-match corpus reference is approved, values are not "
                "comparable across matches.", "",
            ]
        top = report["players"][0]
        bounded = report["quality_gates"]["bounded_combat"]["status"] == "PASS"
        lines += [f"## Worked scoring example: {top['player_name_at_match']}", ""]
        if bounded:
            lines += [
                f"- Finisher points: {top['combat_finisher_points']:.2f}",
                f"- Victim-life damage-share points: {top['combat_damage_share_points']:.2f}",
            ]
        else:
            lines += [
                f"- Kills: {top['kills']} × 100 = {top['combat_finisher_points']:.2f}",
                f"- Assists: {top['assists']} × 50 = {top['fallback_assist_points']:.2f}",
                f"- Opponent damage: {top['opponent_damage']:.0f} × 0.02 = "
                f"{top['fallback_damage_points']:.2f}",
            ]
        lines += [
            f"- Progressive streak: {top['streak_points']:.2f}",
            f"- Shutdowns: {top['shutdown_points']:.2f}",
            f"- Fast chains: {top['fast_chain_points']:.2f}",
            f"- Captures: {top['capture_points']:.2f}",
            f"- Capture conversions: {top['conversion_points']:.2f}",
            f"- Cap breaks: {top['cap_break_points']:.2f}",
            f"- Mid defense: {top['mid_defense_points']:.2f}",
            f"- Aggression: {top['aggression_points']:.2f}",
            f"- Enemy-flag hold: {top['enemy_flag_hold_points']:.2f}",
            f"- Active flag defense: {top['active_flag_defense_points']:.2f}",
            f"- Sequence continuity: {top['sequence_continuity_points']:.2f}",
            f"- Momentum swing attribution: {top['momentum_points']:.2f}",
            f"- **Total: {top['total_points']:.2f}**", "",
            "The combat, streak, chain, and capture awards remain separate. The five "
            "life-impact lines describe only what changed territorially or defensively "
            "while that player remained alive.", "",
        ]
    lines += [
        "", "AI annotations, when present, are advisory and hash-bound to this deterministic "
        "report. They cannot alter points, gates, privacy, or publication state.", "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", type=Path, required=True)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ai-checkpoint-dir", type=Path)
    args = parser.parse_args(argv)
    facts = json.loads(args.facts.read_text(encoding="utf-8"))
    profile = load_profile(args.profile)
    report = score_match(facts, profile)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    match_id = report["match"]["match_id"]
    json_path = args.output_dir / f"{match_id}.bounded.json"
    markdown_path = args.output_dir / f"{match_id}.bounded.md"
    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    if args.ai_checkpoint_dir:
        args.ai_checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = build_ai_checkpoint(report)
        checkpoint_path = args.ai_checkpoint_dir / f"{match_id}.ai-request.json"
        checkpoint_path.write_text(
            json.dumps(checkpoint, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"ai checkpoint: {checkpoint_path}")
    print(f"report: {json_path}")
    print(f"markdown: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
