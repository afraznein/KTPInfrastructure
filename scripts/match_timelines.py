#!/usr/bin/env python3
"""Pure, private shadow analytics derived from persisted match events.

These metrics are exploratory. They do not write to a database, public API,
player rating, or site. Window values are emitted with every result so a later
review can reproduce the exact interpretation.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import math
from typing import Any


@dataclass(frozen=True)
class TimelineConfig:
    multikill_seconds: float = 10.0
    trade_seconds: float = 5.0
    objective_conversion_seconds: float = 30.0
    death_match_tolerance_seconds: float = 1.0

    def validate(self) -> None:
        for name, value in asdict(self).items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be greater than zero")


def _event_key(row: dict[str, Any]) -> tuple[int, float, int]:
    return (int(row.get("half") or 0), float(row["event_unix"]),
            int(row.get("event_id") or 0))


def _identity(row: dict[str, Any], prefix: str) -> dict[str, Any]:
    return {
        "player_id": row.get(f"{prefix}_id"),
        "steam_id": row.get(f"{prefix}_steam_id"),
        "name": row.get(f"{prefix}_name"),
        "team": row.get(f"{prefix}_team"),
    }


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _frag_classification(row: Mapping[str, Any]) -> str:
    """Classify a row from the canonical enemy-frag table.

    ``hlstats_Events_Frags`` already excludes suicides and teamkills.  Missing
    roster team context therefore does not turn a canonical enemy kill into a
    non-kill.  An explicit same-team row is treated as a source-contract
    violation and excluded rather than being silently accepted.
    """
    killer = _int(row.get("killer_id"))
    victim = _int(row.get("victim_id"))
    if killer is None or victim is None:
        return "missing_identity"
    if killer == victim:
        return "self"
    killer_team = _int(row.get("killer_team"))
    victim_team = _int(row.get("victim_team"))
    teams_known = killer_team in {1, 2} and victim_team in {1, 2}
    if teams_known and killer_team == victim_team:
        return "explicit_same_team"
    if not teams_known:
        return "opponent_missing_team_context"
    return "opponent"


def _is_opponent_frag(row: Mapping[str, Any]) -> bool:
    return _frag_classification(row).startswith("opponent")


def _has_complete_team_context(row: Mapping[str, Any]) -> bool:
    return _frag_classification(row) == "opponent"


def _multikills(
    frags: list[dict[str, Any]], config: TimelineConfig
) -> list[dict[str, Any]]:
    by_player_half: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for frag in frags:
        by_player_half[(int(frag["half"]), int(frag["killer_id"]))].append(frag)

    result: list[dict[str, Any]] = []
    for (_half, _killer), kills in sorted(by_player_half.items()):
        kills.sort(key=_event_key)
        cluster: list[dict[str, Any]] = []
        for kill in kills:
            if cluster and float(kill["event_unix"]) - float(cluster[0]["event_unix"]) > config.multikill_seconds:
                if len(cluster) >= 2:
                    result.append(_multikill_row(cluster))
                cluster = []
            cluster.append(kill)
        if len(cluster) >= 2:
            result.append(_multikill_row(cluster))
    return sorted(result, key=lambda row: (row["half"], row["started_unix"], row["killer"]["player_id"]))


def _multikill_row(kills: list[dict[str, Any]]) -> dict[str, Any]:
    first, last = kills[0], kills[-1]
    count = len(kills)
    return {
        "classification": f"fast_{count}k",
        "half": int(first["half"]),
        "killer": _identity(first, "killer"),
        "kill_count": count,
        "started_at": first.get("event_time"),
        "ended_at": last.get("event_time"),
        "started_unix": float(first["event_unix"]),
        "ended_unix": float(last["event_unix"]),
        "elapsed_seconds": round(float(last["event_unix"]) - float(first["event_unix"]), 3),
        "victims": [_identity(row, "victim") for row in kills],
        "event_ids": [int(row.get("event_id") or 0) for row in kills],
    }


def _attach_objective_conversion(
    multikills: list[dict[str, Any]], objectives: list[dict[str, Any]],
    config: TimelineConfig,
) -> None:
    objectives = sorted(objectives, key=_event_key)
    for sequence in multikills:
        conversion = None
        killer_team = sequence["killer"].get("team")
        for event in objectives:
            delta = float(event["event_unix"]) - sequence["ended_unix"]
            if int(event["half"]) != sequence["half"] or delta < 0:
                continue
            if delta > config.objective_conversion_seconds:
                break
            if killer_team is not None and int(event.get("team") or 0) == int(killer_team):
                conversion = {
                    "converted": True,
                    "seconds_after": round(delta, 3),
                    "event_time": event.get("event_time"),
                    "team": event.get("team"),
                    "team_name": event.get("team_name"),
                    "flag_name": event.get("flag_name"),
                }
                break
        sequence["objective_conversion"] = conversion or {"converted": False}


def _trades(frags: list[dict[str, Any]], config: TimelineConfig) -> list[dict[str, Any]]:
    """Allocate each reply to the most recent eligible prior team death."""
    ordered = sorted(frags, key=_event_key)
    used_death_indexes: set[int] = set()
    result: list[dict[str, Any]] = []
    for reply_index, reply in enumerate(ordered):
        if not _has_complete_team_context(reply):
            continue
        reply_at = float(reply["event_unix"])
        for death_index in range(reply_index - 1, -1, -1):
            death = ordered[death_index]
            if death_index in used_death_indexes:
                continue
            if int(death["half"]) != int(reply["half"]):
                if int(death["half"]) < int(reply["half"]):
                    break
                continue
            delta = reply_at - float(death["event_unix"])
            if delta < 0:
                continue
            if delta > config.trade_seconds:
                break
            if not _has_complete_team_context(death):
                continue
            if (int(reply["victim_id"]) == int(death["killer_id"])
                    and int(reply["killer_team"]) == int(death["victim_team"])):
                used_death_indexes.add(death_index)
                result.append({
                    "half": int(death["half"]),
                    "death_event_id": int(death.get("event_id") or 0),
                    "trade_event_id": int(reply.get("event_id") or 0),
                    "seconds_after": round(delta, 3),
                    "fallen_player": _identity(death, "victim"),
                    "original_killer": _identity(death, "killer"),
                    "trader": _identity(reply, "killer"),
                    "event_time": reply.get("event_time"),
                })
                break
    return result


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _trade_analysis(
    frags: list[dict[str, Any]], trades: list[dict[str, Any]],
    *, temporal_valid: bool, source_available: bool,
) -> dict[str, Any]:
    """Summarize the two credited sides of each one-to-one basic trade.

    An opposing-team frag is the only opportunity denominator supported by
    the current timeline.  Individual opportunity attribution would require
    alive, position, and line-of-sight state that these rows do not contain.
    """
    classifications = [_frag_classification(row) for row in frags]
    canonical_rows = sum(value.startswith("opponent") for value in classifications)
    missing_team_rows = classifications.count("opponent_missing_team_context")
    invalid_rows = len(frags) - canonical_rows
    status = (
        "source_not_captured" if not source_available else
        "timed_metrics_suppressed" if not temporal_valid else
        "no_observed_data" if canonical_rows == 0 else
        "partial_team_context" if missing_team_rows else
        "available"
    )
    envelope: dict[str, Any] = {
        "definition_version": 3,
        "unit": "events_and_team_death_response_rate",
        "status": status,
        "visibility": "private_shadow_only",
        "writes": False,
        "rating_effect": False,
        "raw_events_included": False,
        "source_coverage": {
            "canonical_frag_source": {
                "available": source_available,
                "rows_received": len(frags) if source_available else None,
                "opponent_frag_rows": canonical_rows if source_available else None,
                "missing_team_context_rows": missing_team_rows if source_available else None,
                "explicit_same_team_rows": classifications.count("explicit_same_team") if source_available else None,
                "self_rows": classifications.count("self") if source_available else None,
                "missing_identity_rows": classifications.count("missing_identity") if source_available else None,
            },
            "team_context": {
                "complete_opponent_frag_rows": canonical_rows - missing_team_rows if source_available else None,
                "incomplete_opponent_frag_rows": missing_team_rows if source_available else None,
            },
        },
        "confidence": {"level": "unavailable", "basis": []},
        "trade_kills": None,
        "deaths_traded": None,
        "team_death_response_opportunities": None,
        "team_death_response_rate": None,
        "deprecated_aliases": {
            "trade_opportunities": None,
            "trade_conversion_rate": None,
        },
        "teams": [],
        "players": [],
    }
    if status in {"source_not_captured", "timed_metrics_suppressed", "no_observed_data"}:
        envelope["confidence"] = {
            "level": "unavailable",
            "basis": [f"Trade response is not emitted while status is {status}."],
        }
        return envelope

    opportunities_by_team: dict[int, int] = defaultdict(int)
    deaths_by_player: dict[int, int] = defaultdict(int)
    player_counts: dict[int, dict[str, Any]] = {}
    for frag in frags:
        if _is_opponent_frag(frag):
            for prefix in ("killer", "victim"):
                identity = _identity(frag, prefix)
                player_id = _int(identity.get("player_id"))
                if player_id is not None:
                    player_counts.setdefault(player_id, {
                        "player": identity,
                        "trade_kills": 0,
                        "deaths_traded": 0,
                        "deaths_suffered": 0,
                    })
            victim_id = int(frag["victim_id"])
            deaths_by_player[victim_id] += 1
            if victim_id in player_counts:
                player_counts[victim_id]["deaths_suffered"] += 1
            if _has_complete_team_context(frag):
                opportunities_by_team[int(frag["victim_team"])] += 1

    team_counts: dict[int, dict[str, int]] = defaultdict(
        lambda: {"trade_kills": 0, "deaths_traded": 0}
    )
    for trade in trades:
        trader = trade["trader"]
        fallen = trade["fallen_player"]
        trader_id = int(trader["player_id"])
        fallen_id = int(fallen["player_id"])
        trader_team = int(trader["team"])
        fallen_team = int(fallen["team"])

        player_counts.setdefault(trader_id, {
            "player": trader,
            "trade_kills": 0,
            "deaths_traded": 0,
            "deaths_suffered": deaths_by_player[trader_id],
        })["trade_kills"] += 1
        player_counts.setdefault(fallen_id, {
            "player": fallen,
            "trade_kills": 0,
            "deaths_traded": 0,
            "deaths_suffered": deaths_by_player[fallen_id],
        })["deaths_traded"] += 1
        team_counts[trader_team]["trade_kills"] += 1
        team_counts[fallen_team]["deaths_traded"] += 1

    teams = []
    for team in sorted(set(opportunities_by_team) | set(team_counts)):
        trade_kills = team_counts[team]["trade_kills"]
        deaths_traded = team_counts[team]["deaths_traded"]
        opportunities = opportunities_by_team[team]
        teams.append({
            "team": team,
            "trade_kills": trade_kills,
            "deaths_traded": deaths_traded,
            "team_death_response_opportunities": opportunities,
            "team_death_response_rate": _rate(trade_kills, opportunities),
            "deprecated_aliases": {
                "trade_opportunities": opportunities,
                "trade_conversion_rate": _rate(trade_kills, opportunities),
            },
        })

    known_opportunities = sum(opportunities_by_team.values())
    all_opportunities = canonical_rows
    exact_rate = _rate(len(trades), all_opportunities) if not missing_team_rows else None
    envelope.update({
        "trade_kills": len(trades),
        "deaths_traded": len(trades),
        "team_death_response_opportunities": all_opportunities,
        "team_death_response_rate": exact_rate,
        "known_team_context_opportunities": known_opportunities,
        "known_team_context_response_rate": _rate(len(trades), known_opportunities),
        "deprecated_aliases": {
            "trade_opportunities": all_opportunities,
            "trade_conversion_rate": exact_rate,
        },
        "teams": teams,
        "players": [player_counts[player] for player in sorted(player_counts)],
    })
    if missing_team_rows or invalid_rows:
        basis = []
        if missing_team_rows:
            basis.append(
                "Canonical enemy frags with missing roster team context were retained in the denominator, but team-sensitive trade attribution and the exact rate were suppressed."
            )
        if invalid_rows:
            basis.append("Source-contract violations were excluded from competitive trade facts.")
        envelope["confidence"] = {"level": "low", "basis": basis}
    else:
        envelope["confidence"] = {
            "level": "medium",
            "basis": [
                "All canonical enemy frags had complete team context; confidence remains capped pending human-match validation."
            ],
        }
    return envelope


def _normalize_death_boundaries(
    rows: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    normalized: list[dict[str, Any]] = []
    excluded = 0
    for index, row in enumerate(rows):
        if str(row.get("boundary_kind") or row.get("kind") or "").casefold() != "end":
            continue
        if str(row.get("reason") or "").casefold() != "death":
            continue
        player_id = _int(row.get("player_id"))
        half = _int(row.get("half"))
        game_time = _finite_float(row.get("game_time"))
        if player_id is None or half is None or game_time is None:
            excluded += 1
            continue
        normalized.append({
            "index": index,
            "player_id": player_id,
            "half": half,
            "game_time": game_time,
            "event_id": _int(row.get("event_id") or row.get("id")) or 0,
            "death_event_id": _int(
                row.get("death_event_id") or row.get("frag_event_id")
            ),
        })
    return normalized, excluded


def _revenge_analysis(
    frags: list[dict[str, Any]],
    death_boundaries: Sequence[dict[str, Any]] | None,
    config: TimelineConfig,
    *,
    temporal_valid: bool,
    frag_source_available: bool,
    producer_clock_available: bool,
    boundary_source_available: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Use all producer-timed deaths to reset continuous-respawn revenge."""
    boundaries = list(death_boundaries or [])
    source_coverage: dict[str, Any] = {
        "canonical_frag_source": {
            "available": frag_source_available,
            "rows_received": len(frags) if frag_source_available else None,
            "producer_clock_available": producer_clock_available,
            "rows_with_usable_producer_clock": None,
            "opponent_frags_matched_to_deaths": None,
            "opponent_frags_unmatched_to_deaths": None,
            "opponent_frags_with_ambiguous_deaths": None,
        },
        "all_death_boundaries": {
            "available": boundary_source_available,
            "rows_received": len(boundaries) if boundary_source_available else None,
            "death_rows_usable": None,
            "death_rows_excluded": None,
        },
    }
    analysis: dict[str, Any] = {
        "definition_version": 2,
        "unit": "revenge_events",
        "status": "available",
        "visibility": "private_shadow_only",
        "writes": False,
        "rating_effect": False,
        "raw_events_included": False,
        "source_coverage": source_coverage,
        "confidence": {"level": "unavailable", "basis": []},
        "revenge_events": None,
    }
    missing = []
    if not frag_source_available:
        missing.append("canonical_frag_source")
    if not producer_clock_available:
        missing.append("producer_frag_clock")
    if not boundary_source_available:
        missing.append("all_death_boundaries")
    if missing:
        analysis["status"] = "source_not_captured"
        analysis["confidence"] = {
            "level": "unavailable",
            "basis": ["Required source not captured: " + ", ".join(missing) + "."],
        }
        return analysis, []
    if not temporal_valid:
        analysis["status"] = "timed_metrics_suppressed"
        analysis["confidence"] = {
            "level": "unavailable",
            "basis": ["Replay timing was invalid, so revenge was not inferred."],
        }
        return analysis, []

    opponent_frags = [row for row in frags if _is_opponent_frag(row)]
    timed_frags = [
        row for row in opponent_frags
        if _int(row.get("half")) is not None
        and _finite_float(row.get("game_time")) is not None
    ]
    normalized_boundaries, excluded_boundaries = _normalize_death_boundaries(boundaries)
    source_coverage["canonical_frag_source"]["rows_with_usable_producer_clock"] = len(timed_frags)
    source_coverage["all_death_boundaries"]["death_rows_usable"] = len(normalized_boundaries)
    source_coverage["all_death_boundaries"]["death_rows_excluded"] = excluded_boundaries

    if not opponent_frags and not normalized_boundaries:
        analysis["status"] = "no_observed_data"
        analysis["confidence"] = {
            "level": "unavailable",
            "basis": ["No canonical enemy frags or death boundaries were observed."],
        }
        return analysis, []
    if len(timed_frags) != len(opponent_frags):
        analysis["status"] = "insufficient_source_data"
        analysis["confidence"] = {
            "level": "unavailable",
            "basis": ["At least one canonical enemy frag lacked producer game_time or half."],
        }
        return analysis, []

    # Match each canonical enemy frag to exactly one all-death boundary.  A
    # boundary without a canonical frag is still valuable: it is the suicide/
    # teamkill-equivalent reset that the frag table cannot provide.
    available_boundary_indexes = set(range(len(normalized_boundaries)))
    frag_for_boundary: dict[int, dict[str, Any]] = {}
    unmatched_frags = 0
    ambiguous_frags = 0
    for frag in sorted(
        timed_frags,
        key=lambda row: (int(row["half"]), float(row["game_time"]), int(row.get("event_id") or 0)),
    ):
        identity_candidates = [
            index for index in available_boundary_indexes
            if normalized_boundaries[index]["half"] == int(frag["half"])
            and normalized_boundaries[index]["player_id"] == int(frag["victim_id"])
        ]
        frag_event_id = _int(frag.get("event_id"))
        exact = [
            index for index in identity_candidates
            if normalized_boundaries[index]["death_event_id"] is not None
            and frag_event_id is not None
            and normalized_boundaries[index]["death_event_id"] == frag_event_id
        ]
        candidates = exact or [
            index for index in identity_candidates
            if abs(
                normalized_boundaries[index]["game_time"]
                - float(frag["game_time"])
            ) <= config.death_match_tolerance_seconds
        ]
        if not candidates:
            unmatched_frags += 1
            continue
        if len(candidates) != 1:
            ambiguous_frags += 1
            continue
        chosen = candidates[0]
        available_boundary_indexes.remove(chosen)
        frag_for_boundary[chosen] = frag

    source_coverage["canonical_frag_source"]["opponent_frags_matched_to_deaths"] = len(frag_for_boundary)
    source_coverage["canonical_frag_source"]["opponent_frags_unmatched_to_deaths"] = unmatched_frags
    source_coverage["canonical_frag_source"]["opponent_frags_with_ambiguous_deaths"] = ambiguous_frags
    if unmatched_frags or ambiguous_frags:
        analysis["status"] = "incomplete_death_boundary_coverage"
        analysis["confidence"] = {
            "level": "unavailable",
            "basis": [
                "At least one canonical enemy frag lacked exactly one matching all-death boundary; revenge was suppressed rather than missing or inventing a reset."
            ],
        }
        return analysis, []

    frag_entries = [
        (int(row["half"]), float(row["game_time"]), 0, index, "frag", row)
        for index, row in enumerate(timed_frags)
    ]
    boundary_entries = [
        (row["half"], row["game_time"], 1, index, "death", row)
        for index, row in enumerate(normalized_boundaries)
    ]
    pending: dict[tuple[int, int], dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    for half, game_time, _order, index, kind, row in sorted(
        frag_entries + boundary_entries,
        key=lambda item: item[:4],
    ):
        if kind == "frag":
            killer = int(row["killer_id"])
            victim = int(row["victim_id"])
            prior = pending.get((half, killer))
            if prior is not None and int(prior["killer_id"]) == victim:
                events.append({
                    "half": half,
                    "death_event_id": int(prior.get("event_id") or 0),
                    "revenge_event_id": int(row.get("event_id") or 0),
                    "seconds_after": round(game_time - float(prior["game_time"]), 3),
                    "avenger": _identity(row, "killer"),
                    "target": _identity(row, "victim"),
                    "death_event_time": prior.get("event_time"),
                    "event_time": row.get("event_time"),
                })
                del pending[(half, killer)]
            continue

        player = int(row["player_id"])
        pending.pop((half, player), None)
        causing_frag = frag_for_boundary.get(index)
        if causing_frag is not None:
            pending[(half, player)] = causing_frag

    analysis["revenge_events"] = len(events)
    analysis["confidence"] = {
        "level": "medium" if not excluded_boundaries else "low",
        "basis": [
            "Every producer-timed canonical enemy frag matched one all-death boundary; unmatched death boundaries were retained as reset-only deaths."
        ] + (["Malformed all-death boundary rows were excluded."] if excluded_boundaries else []),
    }
    return analysis, events


def _opening_duels(frags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    first_by_half: dict[int, dict[str, Any]] = {}
    for frag in sorted(frags, key=_event_key):
        first_by_half.setdefault(int(frag["half"]), frag)
    return [{
        "half": half,
        "event_id": int(row.get("event_id") or 0),
        "event_time": row.get("event_time"),
        "winner": _identity(row, "killer"),
        "loser": _identity(row, "victim"),
        "weapon": row.get("weapon"),
        "headshot": bool(row.get("headshot")),
    } for half, row in sorted(first_by_half.items())]


def _head_to_head(frags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    names: dict[int, dict[str, Any]] = {}
    pairs: dict[tuple[int, int], dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for frag in frags:
        killer, victim = int(frag["killer_id"]), int(frag["victim_id"])
        names[killer] = _identity(frag, "killer")
        names[victim] = _identity(frag, "victim")
        pairs[tuple(sorted((killer, victim)))][killer] += 1
    rows = []
    for (a, b), kills in sorted(pairs.items()):
        rows.append({
            "player_a": names[a], "player_b": names[b],
            "a_kills": kills[a], "b_kills": kills[b],
            "a_differential": kills[a] - kills[b],
        })
    return rows


def _source_flags(
    source_available: bool | Mapping[str, bool],
    death_boundaries: Sequence[dict[str, Any]] | None,
) -> dict[str, bool]:
    names = ("frags", "frag_event_clock", "life_boundaries")
    if isinstance(source_available, Mapping):
        result = {name: True for name in names}
        aliases = {
            "producer_frag_clock": "frag_event_clock",
            "death_boundaries": "life_boundaries",
            "all_death_boundaries": "life_boundaries",
        }
        for supplied_name, available in source_available.items():
            name = aliases.get(str(supplied_name), str(supplied_name))
            if name in result:
                result[name] = bool(available)
    else:
        result = {name: bool(source_available) for name in names}
    if death_boundaries is None:
        result["life_boundaries"] = False
    return result


def build_shadow_timelines(
    frags: list[dict[str, Any]], objectives: list[dict[str, Any]],
    config: TimelineConfig | None = None, *, temporal_valid: bool = True,
    death_boundaries: Sequence[dict[str, Any]] | None = None,
    source_available: bool | Mapping[str, bool] = True,
) -> dict[str, Any]:
    config = config or TimelineConfig()
    config.validate()
    sources = _source_flags(source_available, death_boundaries)
    ordered = sorted(frags, key=_event_key)
    competitive = [row for row in ordered if _is_opponent_frag(row)]
    timed_valid = temporal_valid and sources["frags"]
    multikills = _multikills(competitive, config) if timed_valid else []
    if timed_valid:
        _attach_objective_conversion(multikills, objectives, config)
    trades = _trades(competitive, config) if timed_valid else []
    revenge_analysis, revenge_events = _revenge_analysis(
        ordered,
        death_boundaries,
        config,
        temporal_valid=temporal_valid,
        frag_source_available=sources["frags"],
        producer_clock_available=sources["frag_event_clock"],
        boundary_source_available=sources["life_boundaries"],
    )
    return {
        "status": (
            "source_not_captured" if not sources["frags"] else
            "available" if temporal_valid else "timed_metrics_suppressed"
        ),
        "privacy": "private_shadow_only",
        "visibility": "private_shadow_only",
        "writes": False,
        "rating_impact": False,
        "rating_effect": False,
        "config": asdict(config),
        "definitions": {
            "basic_trade": {
                "definition_version": 3,
                "parameters": {
                    "trade_seconds": config.trade_seconds,
                    "same_half": True,
                    "one_to_one_credit": True,
                    "allocation": "most_recent_eligible_team_death",
                    "canonical_enemy_frag_source": True,
                },
                "opportunity_denominator": (
                    "canonical enemy-frag deaths suffered by the team"
                ),
            },
            "revenge_response": {
                "definition_version": 2,
                "parameters": {
                    "same_half": True,
                    "expires_on_next_death": True,
                    "time_limit_seconds": None,
                    "clock": "producer_game_time",
                    "all_death_boundaries_required": True,
                },
            },
        },
        "limitations": [
            "Basic trades use roster team and time only; distance, alive state, and line of sight are not inferred.",
            "Team-death response opportunities are canonical enemy-frag deaths, not proof that any specific teammate was alive, nearby, or had line of sight.",
            "One trade reply credits the most recent eligible prior death so trade kills and deaths traded remain symmetric.",
            "Roster team is match-level, so a mid-match team change cannot be resolved per half from this feed.",
            "Revenge is a continuous-respawn response to the killer from the player's immediately preceding opponent-caused death, and every producer-timed death boundary expires it.",
            "Objective conversion means the next same-team flag capture, not a score or capout.",
        ],
        "fast_multikills": multikills,
        "trades": trades,
        "trade_analysis": _trade_analysis(
            ordered,
            trades,
            temporal_valid=temporal_valid,
            source_available=sources["frags"],
        ),
        "revenge_analysis": revenge_analysis,
        "revenge_events": revenge_events,
        "opening_duels": _opening_duels(competitive),
        "head_to_head": _head_to_head(competitive),
    }
