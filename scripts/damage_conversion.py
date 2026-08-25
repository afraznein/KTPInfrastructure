#!/usr/bin/env python3
"""Pure, aggregate-only damage-to-outcome shadow exploration.

All joins use producer ``game_time`` plus an explicit half. Daemon receipt
timestamps are deliberately ignored because buffered damage and assist markers
can arrive after a later life has already begun.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import math
from typing import Any


_SOURCE_NAMES = (
    "damage", "producer_frag_clock", "assist_context", "life_boundaries",
)


@dataclass(frozen=True)
class DamageConversionConfig:
    conversion_seconds: float = 15.0
    assist_grace_seconds: float = 2.0
    death_match_tolerance_seconds: float = 1.0

    def validate(self) -> None:
        for name, value in asdict(self).items():
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.conversion_seconds <= 0:
            raise ValueError("conversion_seconds must be greater than zero")
        if self.assist_grace_seconds < 0:
            raise ValueError("assist_grace_seconds must not be negative")
        if self.death_match_tolerance_seconds < 0:
            raise ValueError("death_match_tolerance_seconds must not be negative")


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _identity(row: Mapping[str, Any], prefix: str) -> dict[str, Any]:
    return {
        "player_id": row.get(f"{prefix}_id"),
        "steam_id": row.get(f"{prefix}_steam_id"),
        "name": row.get(f"{prefix}_name"),
        "team": _int(row.get(f"{prefix}_team")),
    }


def _availability(
    source_available: bool | Mapping[str, bool],
    supplied: Mapping[str, Sequence[dict[str, Any]] | None],
) -> dict[str, bool]:
    if isinstance(source_available, Mapping):
        result = {name: True for name in _SOURCE_NAMES}
        aliases = {
            "damage_events": "damage",
            "frag_event_clock": "producer_frag_clock",
            "frags": "producer_frag_clock",
            "assists": "assist_context",
            "canonical_assist_context": "assist_context",
            "death_boundaries": "life_boundaries",
        }
        for supplied_name, is_available in source_available.items():
            name = aliases.get(str(supplied_name), str(supplied_name))
            if name in result:
                result[name] = bool(is_available)
    else:
        result = {name: bool(source_available) for name in _SOURCE_NAMES}
    for name, rows in supplied.items():
        if rows is None:
            result[name] = False
    return result


def _frag_classification(row: Mapping[str, Any]) -> str:
    killer = _int(row.get("killer_id"))
    victim = _int(row.get("victim_id"))
    if killer is None or victim is None:
        return "missing_identity"
    if killer == victim:
        return "self"
    killer_team = _int(row.get("killer_team"))
    victim_team = _int(row.get("victim_team"))
    if killer_team in {1, 2} and victim_team in {1, 2}:
        return "explicit_same_team" if killer_team == victim_team else "opponent"
    # The input is the canonical enemy-frag table. Missing roster context
    # lowers confidence but does not turn an enemy kill into a non-kill.
    return "opponent_missing_team_context"


def _normalize_frag(row: dict[str, Any]) -> dict[str, Any] | None:
    classification = _frag_classification(row)
    half = _int(row.get("half"))
    at = _float(row.get("game_time"))
    if not classification.startswith("opponent") or half is None or at is None:
        return None
    return {
        **row,
        "half": half,
        "game_time": at,
        "killer_id": int(row["killer_id"]),
        "victim_id": int(row["victim_id"]),
        "team_context_complete": classification == "opponent",
    }


def _normalize_death(row: dict[str, Any], index: int) -> dict[str, Any] | None:
    kind = str(row.get("boundary_kind") or row.get("kind") or "").casefold()
    reason = str(row.get("reason") or "").casefold()
    if kind != "end" or reason != "death":
        return None
    player_id = _int(row.get("player_id"))
    half = _int(row.get("half"))
    at = _float(row.get("game_time"))
    if player_id is None or half is None or at is None:
        return None
    return {
        "index": index,
        "player_id": player_id,
        "half": half,
        "game_time": at,
        "event_id": _int(row.get("event_id") or row.get("id")) or 0,
        "death_event_id": _int(row.get("death_event_id") or row.get("frag_event_id")),
    }


def _normalize_assist(row: dict[str, Any]) -> dict[str, Any] | None:
    assister = _int(row.get("assister_id") or row.get("player_id"))
    victim = _int(row.get("victim_id"))
    half = _int(row.get("half"))
    at = _float(row.get("game_time"))
    if assister is None or victim is None or half is None or at is None:
        return None
    return {
        "assister_id": assister,
        "victim_id": victim,
        "half": half,
        "game_time": at,
    }


def _normalize_damage(row: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    attacker = _int(row.get("attacker_id"))
    victim = _int(row.get("victim_id"))
    attacker_team = _int(row.get("attacker_team"))
    victim_team = _int(row.get("victim_team"))
    half = _int(row.get("half"))
    at = _float(row.get("game_time"))
    amount = _int(row.get("damage_capped"))
    if (
        attacker is None or victim is None or half is None or at is None
        or amount is None or amount < 0
    ):
        return None, "malformed"
    if attacker_team not in {1, 2} or victim_team not in {1, 2}:
        return None, "missing_team"
    if attacker == victim or attacker_team == victim_team:
        return None, "self_or_team"
    return {
        **row,
        "attacker_id": attacker,
        "victim_id": victim,
        "attacker_team": attacker_team,
        "victim_team": victim_team,
        "half": half,
        "game_time": at,
        "damage_capped": amount,
    }, None


def _map_frags_to_deaths(
    frags: Sequence[dict[str, Any]],
    deaths: Sequence[dict[str, Any]],
    tolerance: float,
) -> tuple[dict[int, dict[str, Any]], int, int]:
    available = set(range(len(deaths)))
    result: dict[int, dict[str, Any]] = {}
    unmatched = 0
    ambiguous = 0
    for frag in sorted(
        frags,
        key=lambda row: (
            row["half"], row["game_time"], _int(row.get("event_id")) or 0,
        ),
    ):
        explicit_id = _int(frag.get("event_id"))
        identity_candidates = [
            index for index in available
            if deaths[index]["half"] == frag["half"]
            and deaths[index]["player_id"] == frag["victim_id"]
        ]
        exact = [
            index for index in identity_candidates
            if deaths[index]["death_event_id"] is not None
            and explicit_id is not None
            and deaths[index]["death_event_id"] == explicit_id
        ]
        candidates = exact or [
            index for index in identity_candidates
            if abs(deaths[index]["game_time"] - frag["game_time"]) <= tolerance
        ]
        if not candidates:
            unmatched += 1
            continue
        if len(candidates) != 1:
            ambiguous += 1
            continue
        chosen = candidates[0]
        available.remove(chosen)
        result[chosen] = frag
    return result, unmatched, ambiguous


def _credited_assist(
    damage: Mapping[str, Any], death: Mapping[str, Any],
    assists: Sequence[dict[str, Any]], grace_seconds: float,
) -> bool:
    for assist in assists:
        if assist["half"] != damage["half"]:
            continue
        if assist["assister_id"] != damage["attacker_id"]:
            continue
        if assist["victim_id"] != damage["victim_id"]:
            continue
        if damage["game_time"] <= assist["game_time"] <= death["game_time"] + grace_seconds:
            return True
    return False


def _empty_envelope(
    config: DamageConversionConfig,
    source_coverage: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "definition": "damage_conversion_v2",
        "definition_version": 2,
        "unit": "hp_capped_damage",
        "status": "available",
        "visibility": "private_shadow_only",
        "privacy": "private_shadow_only",
        "writes": False,
        "rating_effect": False,
        "rating_impact": False,
        "raw_events_included": False,
        "confidence": {"level": "unavailable", "basis": []},
        "parameters": {
            **asdict(config), "clock": "producer_game_time", "same_half": True,
        },
        "source_coverage": source_coverage,
        "limitations": [
            "Uses HP-capped per-hit damage, not nominal raw weapon damage.",
            "Outcome links are time associations and do not prove causation.",
            "The first death-ended life boundary after a hit is a hard reset; a suicide, teamkill, or death without a canonical enemy frag remains unconverted.",
            "Canonical assist context and all timed joins use producer game_time plus explicit half; daemon receipt time is ignored.",
            "Per-hit positions are not captured; damage distance is unavailable.",
        ],
        "players": [],
        "excluded_rows": {
            "self_or_team": 0,
            "missing_team": 0,
            "malformed": 0,
            "finish_missing_team_context": 0,
        },
    }


def build_damage_conversion(
    damage_events: Sequence[dict[str, Any]] | None,
    frags: Sequence[dict[str, Any]] | None,
    assist_events: Sequence[dict[str, Any]] | None,
    config: DamageConversionConfig | None = None,
    *,
    life_boundaries: Sequence[dict[str, Any]] | None = None,
    source_available: bool | Mapping[str, bool] = True,
    temporal_valid: bool = True,
) -> dict[str, Any]:
    """Return aggregate player results without exposing per-hit/life rows."""
    config = config or DamageConversionConfig()
    config.validate()
    supplied = {
        "damage": damage_events,
        "producer_frag_clock": frags,
        "assist_context": assist_events,
        "life_boundaries": life_boundaries,
    }
    available = _availability(source_available, supplied)
    rows = {name: list(value or []) for name, value in supplied.items()}
    source_coverage = {
        name: {
            "available": available[name],
            "rows_received": len(rows[name]) if supplied[name] is not None else None,
            "rows_usable": None,
            "rows_excluded": None,
        }
        for name in _SOURCE_NAMES
    }
    envelope = _empty_envelope(config, source_coverage)
    if not all(available.values()):
        missing = [name for name in _SOURCE_NAMES if not available[name]]
        envelope["status"] = "source_not_captured"
        envelope["confidence"] = {
            "level": "unavailable",
            "basis": ["Required source not captured: " + ", ".join(missing) + "."],
        }
        return envelope
    if not temporal_valid:
        envelope["status"] = "timed_metrics_suppressed"
        envelope["confidence"] = {
            "level": "unavailable",
            "basis": ["Replay timing was invalid, so damage conversion was not inferred."],
        }
        return envelope
    if not rows["damage"]:
        envelope["status"] = "no_observed_data"
        envelope["confidence"] = {
            "level": "unavailable",
            "basis": ["The captured damage source contained no events."],
        }
        for coverage in source_coverage.values():
            coverage["rows_usable"] = 0
            coverage["rows_excluded"] = int(coverage["rows_received"] or 0)
        return envelope

    normalized_damage = []
    for row in rows["damage"]:
        normalized, reason = _normalize_damage(row)
        if normalized is not None:
            normalized_damage.append(normalized)
        elif reason is not None:
            envelope["excluded_rows"][reason] += 1
    normalized_frags = [
        normalized for row in rows["producer_frag_clock"]
        if (normalized := _normalize_frag(row)) is not None
    ]
    normalized_assists = [
        normalized for row in rows["assist_context"]
        if (normalized := _normalize_assist(row)) is not None
    ]
    normalized_deaths = [
        normalized for index, row in enumerate(rows["life_boundaries"])
        if (normalized := _normalize_death(row, index)) is not None
    ]
    normalized = {
        "damage": normalized_damage,
        "producer_frag_clock": normalized_frags,
        "assist_context": normalized_assists,
        "life_boundaries": normalized_deaths,
    }
    for name, source_rows in normalized.items():
        source_coverage[name]["rows_usable"] = len(source_rows)
        source_coverage[name]["rows_excluded"] = len(rows[name]) - len(source_rows)
    death_candidates = [
        row for row in rows["life_boundaries"]
        if str(row.get("boundary_kind") or row.get("kind") or "").casefold() == "end"
        and str(row.get("reason") or "").casefold() == "death"
    ]
    source_coverage["life_boundaries"]["death_rows_received"] = len(death_candidates)
    source_coverage["life_boundaries"]["rows_excluded"] = (
        len(death_candidates) - len(normalized_deaths)
    )
    source_coverage["life_boundaries"]["non_death_rows_ignored"] = (
        len(rows["life_boundaries"]) - len(death_candidates)
    )

    if not normalized_damage or not normalized_deaths:
        envelope["status"] = "insufficient_source_data"
        envelope["confidence"] = {
            "level": "unavailable",
            "basis": [
                "Producer-timed damage rows and at least one producer-timed death boundary are required when damage was observed."
            ],
        }
        return envelope
    canonical_frag_count = sum(
        _frag_classification(row).startswith("opponent")
        for row in rows["producer_frag_clock"]
    )
    if len(normalized_frags) != canonical_frag_count:
        envelope["status"] = "insufficient_source_data"
        envelope["confidence"] = {
            "level": "unavailable",
            "basis": ["At least one canonical enemy frag lacked producer game_time or half."],
        }
        return envelope
    if rows["assist_context"] and not normalized_assists:
        envelope["status"] = "insufficient_source_data"
        envelope["confidence"] = {
            "level": "unavailable",
            "basis": [
                "Assist context rows were supplied but none had producer game_time, half, assister, and victim."
            ],
        }
        return envelope

    frag_for_death, unmatched_frags, ambiguous_frags = _map_frags_to_deaths(
        normalized_frags, normalized_deaths, config.death_match_tolerance_seconds,
    )
    source_coverage["producer_frag_clock"]["frags_matched_to_death_boundaries"] = len(frag_for_death)
    source_coverage["producer_frag_clock"]["frags_unmatched_to_death_boundaries"] = unmatched_frags
    source_coverage["producer_frag_clock"]["frags_with_ambiguous_death_boundaries"] = ambiguous_frags
    if unmatched_frags or ambiguous_frags:
        envelope["status"] = "incomplete_death_boundary_coverage"
        envelope["confidence"] = {
            "level": "unavailable",
            "basis": [
                "A canonical enemy frag lacked exactly one matching death-ended life boundary; damage conversion was suppressed."
            ],
        }
        return envelope

    deaths_by_victim_half: dict[
        tuple[int, int], list[tuple[int, dict[str, Any]]]
    ] = defaultdict(list)
    for index, death in enumerate(normalized_deaths):
        deaths_by_victim_half[(death["half"], death["player_id"])].append((index, death))
    for death_rows in deaths_by_victim_half.values():
        death_rows.sort(key=lambda item: (item[1]["game_time"], item[1]["event_id"]))

    fields = (
        "damage_total", "damage_to_own_kill", "damage_to_credited_assist",
        "damage_to_teammate_finish", "unconverted_damage",
    )
    players: dict[int, dict[str, Any]] = {}
    for damage in normalized_damage:
        player_id = damage["attacker_id"]
        player = players.setdefault(player_id, {
            **_identity(damage, "attacker"),
            **{field: 0 for field in fields},
            "hit_events": 0,
        })
        amount = damage["damage_capped"]
        player["damage_total"] += amount
        player["hit_events"] += 1
        death_match: tuple[int, dict[str, Any]] | None = None
        for candidate in deaths_by_victim_half.get(
            (damage["half"], damage["victim_id"]), []
        ):
            delta = candidate[1]["game_time"] - damage["game_time"]
            if delta < 0:
                continue
            if delta > config.conversion_seconds:
                break
            death_match = candidate
            break
        if death_match is None:
            player["unconverted_damage"] += amount
            continue
        death_index, death = death_match
        frag = frag_for_death.get(death_index)
        if frag is None:
            # Suicide/teamkill/no canonical frag is still a hard life reset.
            player["unconverted_damage"] += amount
        elif frag["killer_id"] == damage["attacker_id"]:
            player["damage_to_own_kill"] += amount
        elif _credited_assist(
            damage, death, normalized_assists, config.assist_grace_seconds
        ):
            player["damage_to_credited_assist"] += amount
        elif (
            _int(frag.get("killer_team")) in {1, 2}
            and int(frag["killer_team"]) == damage["attacker_team"]
        ):
            player["damage_to_teammate_finish"] += amount
        else:
            if not frag["team_context_complete"]:
                envelope["excluded_rows"]["finish_missing_team_context"] += 1
            player["unconverted_damage"] += amount

    kills_by_player: dict[int, int] = defaultdict(int)
    for frag in normalized_frags:
        kills_by_player[frag["killer_id"]] += 1
    team_totals: dict[int, int] = defaultdict(int)
    for player in players.values():
        if player.get("team") in {1, 2}:
            team_totals[int(player["team"])] += int(player["damage_total"])

    output = []
    for player_id, player in players.items():
        total = int(player["damage_total"])
        linked = sum(int(player[field]) for field in (
            "damage_to_own_kill", "damage_to_credited_assist",
            "damage_to_teammate_finish",
        ))
        team_total = team_totals.get(int(player["team"]), 0)
        kills = kills_by_player.get(player_id, 0)
        player.update({
            "opponent_kills": kills,
            "damage_per_kill": round(total / kills, 2) if kills else None,
            "outcome_linked_damage": linked,
            "outcome_linked_share": round(linked / total, 4) if total else None,
            "team_damage_share": round(total / team_total, 4) if team_total else None,
        })
        output.append(player)
    envelope["players"] = sorted(
        output,
        key=lambda row: (
            int(row.get("team") or 0), -int(row["damage_total"]),
            int(row["player_id"]),
        ),
    )
    cautions = []
    if any(int(value.get("rows_excluded") or 0) for value in source_coverage.values()):
        cautions.append("Malformed or source-contract-violating rows were excluded.")
    if any(
        _frag_classification(row) == "opponent_missing_team_context"
        for row in rows["producer_frag_clock"]
    ):
        cautions.append(
            "Some canonical enemy frags lacked roster team context; teammate-finish attribution may be incomplete."
        )
    envelope["confidence"] = {
        "level": "low" if cautions else "medium",
        "basis": cautions or [
            "All required sources used producer game_time and explicit half; confidence remains capped pending human-match validation."
        ],
    }
    return envelope
