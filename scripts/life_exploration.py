#!/usr/bin/env python3
"""Conservative, aggregate-only exploration of player life boundaries.

This module is deliberately pure: it consumes persisted rows and returns a
private-shadow report.  It does not write to a database, API, rating, or site,
and it never returns the reconstructed per-life timeline.

KAT is a continuous-respawn adaptation, not KAST.  Its denominator contains
only lives observed from a start boundary through a death boundary.  A life is
covered when it contains an opposing-player kill, a credited assist, or when
the death ending that life appears in the existing basic-trade facts.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import math
from typing import Any


_SOURCE_NAMES = ("life_boundaries", "frags", "assists", "basic_trades")
# Life membership is intentionally producer-clock only.  Receipt-time epoch
# values can move buffered damage/assist facts into a later life.
_CLOCK_FIELDS = ("game_time",)


@dataclass(frozen=True)
class LifeExplorationConfig:
    """Parameters that affect conservative death-to-frag correlation."""

    death_match_tolerance_seconds: float = 1.0
    require_complete_match_frag_coverage: bool = True

    def validate(self) -> None:
        if (
            not math.isfinite(self.death_match_tolerance_seconds)
            or self.death_match_tolerance_seconds < 0
        ):
            raise ValueError(
                "death_match_tolerance_seconds must be finite and not negative"
            )


def _empty_aggregate() -> dict[str, Any]:
    return {
        "eligible_lives": None,
        "covered_lives": None,
        "kat_coverage": None,
        "lives_with_kill": None,
        "lives_with_assist": None,
        "lives_with_traded_death": None,
        "lives_with_multiple_components": None,
    }


def _empty_boundary_coverage() -> dict[str, Any]:
    return {
        "rows_usable": None,
        "rows_excluded": None,
        "start_boundaries": None,
        "end_boundaries": None,
        "start_reason_counts": None,
        "end_reason_counts": None,
        "lives_reconstructed": None,
        "death_ended_lives": None,
        "censored_lives": None,
        "censored_by_reason": None,
        "orphan_end_boundaries": None,
        "context_live_started_lives": None,
        "death_boundaries_matched_to_frags": None,
        "death_frag_match_coverage": None,
        "canonical_victim_frags_in_boundary_population": None,
        "canonical_victim_frags_matched_to_death_boundaries": None,
        "canonical_victim_frags_unmatched": None,
        "death_frag_bijection_complete": None,
    }


def _rows(value: Sequence[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return list(value) if value is not None else []


def _availability(
    source_available: bool | Mapping[str, bool],
    source_rows: Mapping[str, Sequence[dict[str, Any]] | None],
) -> dict[str, bool]:
    if isinstance(source_available, Mapping):
        result = {name: True for name in _SOURCE_NAMES}
        aliases = {
            "boundaries": "life_boundaries",
            "death_boundaries": "life_boundaries",
            "canonical_frag_source": "frags",
            "producer_frag_clock": "frags",
            "frag_event_clock": "frags",
            "assist_context": "assists",
            "canonical_assist_context": "assists",
            "trades": "basic_trades",
        }
        for supplied_name, available in source_available.items():
            name = aliases.get(str(supplied_name), str(supplied_name))
            if name in result:
                result[name] = bool(available)
    else:
        result = {name: bool(source_available) for name in _SOURCE_NAMES}

    # ``None`` is an explicit absence, unlike an available, captured empty
    # list.  Treating the two alike would manufacture false zeroes.
    for name, rows in source_rows.items():
        if rows is None:
            result[name] = False
    return result


def _float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = row.get(name)
        if value is not None:
            return value
    return None


def _clock_value(row: Mapping[str, Any], clock: str) -> float | None:
    return _float(row.get(clock))


def _select_clock(
    boundaries: Sequence[dict[str, Any]],
    timed_facts: Sequence[dict[str, Any]],
) -> str | None:
    """Pick one coherent clock; never compare game time with epoch time."""
    if not boundaries:
        return None
    scores: dict[str, tuple[int, int]] = {
        field: (
            sum(_clock_value(row, field) is not None for row in boundaries),
            sum(_clock_value(row, field) is not None for row in timed_facts),
        )
        for field in _CLOCK_FIELDS
    }
    best = max(scores.values(), default=(0, 0))
    if best[0] == 0:
        return None
    # Boundary coverage is mandatory and therefore the first score component.
    return next(field for field in _CLOCK_FIELDS if scores[field] == best)


def _nested(row: Mapping[str, Any], prefix: str) -> Mapping[str, Any]:
    value = row.get(prefix)
    return value if isinstance(value, Mapping) else {}


def _identity(row: Mapping[str, Any], prefix: str = "player") -> dict[str, Any]:
    nested = _nested(row, prefix)
    if prefix == "player":
        player_id = _first(row, "player_id")
        steam_id = _first(row, "steam_id", "player_steam_id")
        name = _first(row, "player_name", "name")
        team = _first(row, "player_team", "team")
    else:
        player_id = _first(row, f"{prefix}_id")
        steam_id = _first(row, f"{prefix}_steam_id")
        name = _first(row, f"{prefix}_name")
        team = _first(row, f"{prefix}_team")

    player_id = player_id if player_id is not None else _first(
        nested, "player_id", "id"
    )
    steam_id = steam_id if steam_id is not None else _first(
        nested, "steam_id", "unique_id"
    )
    name = name if name is not None else _first(nested, "name", "player_name")
    team = team if team is not None else _first(nested, "team", "team_id")

    scalar = row.get(prefix)
    if player_id is None and steam_id is None and not isinstance(scalar, Mapping):
        player_id = scalar
    return {
        "player_id": player_id,
        "steam_id": steam_id,
        "name": name,
        "team": _int(team),
    }


def _identity_key(identity: Mapping[str, Any]) -> tuple[str, str] | None:
    if identity.get("player_id") is not None:
        value = identity["player_id"]
        numeric = _int(value)
        return ("player_id", str(numeric if numeric is not None else value))
    if identity.get("steam_id"):
        return ("steam_id", str(identity["steam_id"]).strip().casefold())
    return None


def _merge_identity(
    current: Mapping[str, Any], update: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        field: current.get(field) if current.get(field) is not None else update.get(field)
        for field in ("player_id", "steam_id", "name", "team")
    }


def _row_id(row: Mapping[str, Any]) -> int:
    return _int(_first(row, "event_id", "id")) or 0


def _normalize_boundary(
    row: dict[str, Any], clock: str, input_index: int
) -> dict[str, Any] | None:
    identity = _identity(row)
    key = _identity_key(identity)
    half = _int(row.get("half"))
    at = _clock_value(row, clock)
    kind = str(_first(row, "boundary_kind", "kind") or "").strip().casefold()
    reason = str(_first(row, "reason", "boundary_reason") or "").strip().casefold()
    if key is None or half is None or at is None or kind not in {"start", "end"}:
        return None
    if kind == "start" and reason not in {"spawn", "context_live"}:
        return None
    if kind == "end" and not reason:
        return None
    return {
        "key": key,
        "player": identity,
        "half": half,
        "at": at,
        "event_id": _row_id(row),
        "input_index": input_index,
        "kind": kind,
        "reason": reason,
        "death_event_id": _int(_first(row, "death_event_id", "frag_event_id")),
    }


def _normalize_frag(
    row: dict[str, Any], clock: str, input_index: int
) -> dict[str, Any] | None:
    killer = _identity(row, "killer")
    victim = _identity(row, "victim")
    killer_key = _identity_key(killer)
    victim_key = _identity_key(victim)
    half = _int(row.get("half"))
    at = _clock_value(row, clock)
    if killer_key is None or victim_key is None or half is None or at is None:
        return None
    killer_team, victim_team = killer.get("team"), victim.get("team")
    if killer_key == victim_key:
        classification = "self"
    elif (
        killer_team in {1, 2}
        and victim_team in {1, 2}
        and int(killer_team) == int(victim_team)
    ):
        classification = "explicit_same_team"
    elif killer_team not in {1, 2} or victim_team not in {1, 2}:
        classification = "opponent_missing_team_context"
    else:
        classification = "opponent"
    return {
        "killer_key": killer_key,
        "victim_key": victim_key,
        "half": half,
        "at": at,
        "event_id": _row_id(row),
        "source_index": input_index,
        "classification": classification,
        "opponent": classification.startswith("opponent"),
        "team_context_complete": classification == "opponent",
    }


def _normalize_assist(
    row: dict[str, Any], clock: str
) -> dict[str, Any] | None:
    assister = _identity(row, "assister")
    # Some persisted assist facts use player_* for the credited player.
    if _identity_key(assister) is None:
        assister = _identity(row)
    key = _identity_key(assister)
    half = _int(row.get("half"))
    at = _clock_value(row, clock)
    if key is None or at is None or half is None:
        return None
    return {"assister_key": key, "half": half, "at": at, "event_id": _row_id(row)}


def _normalize_trade(row: dict[str, Any], clock: str) -> dict[str, Any] | None:
    fallen = _identity(row, "fallen_player")
    if _identity_key(fallen) is None:
        fallen = _identity(row, "victim")
    fallen_key = _identity_key(fallen)
    death_event_id = _int(_first(row, "death_event_id", "original_death_event_id"))
    half = _int(row.get("half"))
    death_at = _float(
        row.get("death_game_time")
        if clock == "game_time"
        else _first(row, "death_event_epoch", "death_event_unix")
    )
    if death_event_id is None and (fallen_key is None or half is None or death_at is None):
        return None
    return {
        "fallen_key": fallen_key,
        "half": half,
        "death_at": death_at,
        "death_event_id": death_event_id,
    }


def _boundary_sort_key(row: Mapping[str, Any]) -> tuple[float, int, int]:
    # Input order is retained when a source has no stable event id.
    event_order = int(row["event_id"]) if row["event_id"] else int(row["input_index"])
    return (float(row["at"]), event_order, int(row["input_index"]))


def _reconstruct_lives(
    boundaries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    groups: dict[tuple[int, tuple[str, str]], list[dict[str, Any]]] = defaultdict(list)
    for row in boundaries:
        groups[(int(row["half"]), row["key"])].append(row)

    lives: list[dict[str, Any]] = []
    orphan_ends = 0
    for (_half, _player_key), rows in sorted(groups.items(), key=lambda item: repr(item[0])):
        active: dict[str, Any] | None = None
        for boundary in sorted(rows, key=_boundary_sort_key):
            if boundary["kind"] == "start":
                if active is not None:
                    active.update({
                        "end_at": boundary["at"],
                        "end_event_id": boundary["event_id"],
                        "end_reason": "consecutive_start",
                        "eligible": False,
                    })
                    lives.append(active)
                active = {
                    "key": boundary["key"],
                    "player": boundary["player"],
                    "half": boundary["half"],
                    "start_at": boundary["at"],
                    "start_event_id": boundary["event_id"],
                    "start_reason": boundary["reason"],
                }
                continue

            if active is None:
                orphan_ends += 1
                continue
            active["player"] = _merge_identity(active["player"], boundary["player"])
            active.update({
                "end_at": boundary["at"],
                "end_event_id": boundary["event_id"],
                "end_reason": boundary["reason"],
                "death_event_id": boundary["death_event_id"],
                "eligible": boundary["reason"] == "death",
            })
            lives.append(active)
            active = None

        if active is not None:
            active.update({
                "end_at": None,
                "end_event_id": 0,
                "end_reason": "open_at_half_end",
                "eligible": False,
            })
            lives.append(active)

    censored = Counter(
        life["end_reason"] for life in lives if not bool(life["eligible"])
    )
    coverage = {
        "start_boundaries": sum(row["kind"] == "start" for row in boundaries),
        "end_boundaries": sum(row["kind"] == "end" for row in boundaries),
        "start_reason_counts": dict(sorted(Counter(
            row["reason"] for row in boundaries if row["kind"] == "start"
        ).items())),
        "end_reason_counts": dict(sorted(Counter(
            row["reason"] for row in boundaries if row["kind"] == "end"
        ).items())),
        "lives_reconstructed": len(lives),
        "death_ended_lives": sum(bool(life["eligible"]) for life in lives),
        "censored_lives": sum(not bool(life["eligible"]) for life in lives),
        "censored_by_reason": dict(sorted(censored.items())),
        "orphan_end_boundaries": orphan_ends,
        "context_live_started_lives": sum(
            life["start_reason"] == "context_live" for life in lives
        ),
    }
    return lives, coverage


def _position(at: float, event_id: int) -> tuple[float, int]:
    return (float(at), int(event_id))


def _inside_life(life: Mapping[str, Any], event: Mapping[str, Any]) -> bool:
    if event.get("half") is not None and int(life["half"]) != int(event["half"]):
        return False
    event_at = float(event["at"])
    # IDs belong to different physical tables and are not a global ordering.
    # Boundary-edge facts are therefore included by clock only and called out
    # as an epoch-precision limitation in the report.
    return float(life["start_at"]) <= event_at <= float(life["end_at"])


def _match_death_frag(
    life: Mapping[str, Any],
    victim_frags: Mapping[tuple[int, tuple[str, str]], list[dict[str, Any]]],
    used_source_indexes: set[int],
    tolerance: float,
) -> dict[str, Any] | None:
    candidates = [
        frag for frag in victim_frags.get((int(life["half"]), life["key"]), [])
        if frag["opponent"]
    ]
    reference = life.get("death_event_id")
    if reference is not None:
        exact = [
            frag for frag in candidates
            if int(frag["event_id"]) == int(reference)
        ]
        if len(exact) == 1 and int(exact[0]["source_index"]) not in used_source_indexes:
            return exact[0]
        if exact:
            return None

    available = [
        frag for frag in candidates
        if int(frag["source_index"]) not in used_source_indexes
        if abs(float(frag["at"]) - float(life["end_at"])) <= tolerance
    ]
    # A tolerance is only a correlation aid, not authority to choose among
    # multiple plausible deaths. Fail closed when the mapping is ambiguous.
    if len(available) != 1:
        return None
    return available[0]


def _death_was_traded(
    life: Mapping[str, Any],
    death_frag: Mapping[str, Any] | None,
    trades: Sequence[dict[str, Any]],
    tolerance: float,
) -> bool:
    candidate_ids = {
        int(value) for value in (
            life.get("death_event_id"),
            death_frag.get("event_id") if death_frag else None,
        ) if value is not None and int(value) != 0
    }
    for trade in trades:
        trade_id = trade.get("death_event_id")
        if trade_id is not None and int(trade_id) in candidate_ids:
            if trade.get("fallen_key") is None or trade["fallen_key"] == life["key"]:
                return True
        if (
            trade.get("fallen_key") == life["key"]
            and trade.get("half") == life["half"]
            and trade.get("death_at") is not None
            and abs(float(trade["death_at"]) - float(life["end_at"])) <= tolerance
        ):
            return True
    return False


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _aggregate_lives(lives: Sequence[dict[str, Any]]) -> dict[str, Any]:
    eligible = len(lives)
    covered = sum(bool(life["covered"]) for life in lives)
    return {
        "eligible_lives": eligible,
        "covered_lives": covered,
        "kat_coverage": _rate(covered, eligible),
        "lives_with_kill": sum(bool(life["had_kill"]) for life in lives),
        "lives_with_assist": sum(bool(life["had_assist"]) for life in lives),
        "lives_with_traded_death": sum(
            bool(life["death_was_traded"]) for life in lives
        ),
        "lives_with_multiple_components": sum(
            int(life["had_kill"])
            + int(life["had_assist"])
            + int(life["death_was_traded"]) > 1
            for life in lives
        ),
    }


def _group_aggregates(
    eligible_lives: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_player: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_team: dict[int | None, list[dict[str, Any]]] = defaultdict(list)
    identities: dict[tuple[str, str], dict[str, Any]] = {}
    player_teams: dict[tuple[str, str], set[int]] = defaultdict(set)
    for life in eligible_lives:
        key = life["key"]
        by_player[key].append(life)
        identities[key] = _merge_identity(
            identities.get(key, {}), life["player"]
        )
        team = life["player"].get("team")
        normalized_team = int(team) if team is not None else None
        by_team[normalized_team].append(life)
        if normalized_team is not None:
            player_teams[key].add(normalized_team)

    players = []
    for key in sorted(by_player, key=repr):
        identity = identities[key]
        teams = sorted(player_teams[key])
        if len(teams) > 1:
            identity = {**identity, "team": None}
        players.append({
            "player": identity,
            "teams": teams,
            **_aggregate_lives(by_player[key]),
        })

    teams = [
        {"team": team, **_aggregate_lives(by_team[team])}
        for team in sorted(by_team, key=lambda value: (value is None, value or 0))
    ]
    return players, teams


def _confidence(
    status: str,
    boundary_coverage: Mapping[str, Any],
    source_coverage: Mapping[str, Mapping[str, Any]],
    selected_clock: str | None,
) -> dict[str, Any]:
    if status != "available":
        return {
            "level": "unavailable",
            "basis": [f"KAT is not emitted while status is {status}."],
        }

    cautions: list[str] = []
    if boundary_coverage.get("context_live_started_lives"):
        cautions.append(
            "At least one eligible observation may start at context_live rather than spawn."
        )
    if boundary_coverage.get("orphan_end_boundaries"):
        cautions.append("At least one end boundary had no observed start boundary.")
    if boundary_coverage.get("rows_excluded"):
        cautions.append("Malformed or clock-incompatible boundary rows were excluded.")
    eligible = int(boundary_coverage.get("death_ended_lives") or 0)
    matched = int(boundary_coverage.get("death_boundaries_matched_to_frags") or 0)
    if matched < eligible or not boundary_coverage.get("death_frag_bijection_complete"):
        cautions.append("Death-to-frag coverage was not bijective.")
    for name in ("frags", "assists", "basic_trades"):
        if source_coverage[name].get("rows_excluded"):
            cautions.append(f"Some {name} rows could not use the selected clock or identity.")
    if source_coverage["frags"].get("missing_team_context_rows"):
        cautions.append(
            "Some canonical enemy frags lacked roster team context; they remain enemy kills but lower attribution confidence."
        )
    if source_coverage["frags"].get("explicit_same_team_rows"):
        cautions.append(
            "Explicit same-team rows violated the canonical enemy-frag contract and were excluded from KAT kills."
        )

    if cautions:
        return {"level": "low", "basis": cautions}
    return {
        "level": "medium",
        "basis": [
            "All eligible lives have explicit starts and death ends, and canonical victim frags map bijectively to those deaths.",
            "Confidence is capped at medium until the boundary feed is validated with real human matches.",
        ],
    }


def build_life_exploration(
    life_boundaries: Sequence[dict[str, Any]] | None,
    frags: Sequence[dict[str, Any]] | None,
    assist_timeline: Sequence[dict[str, Any]] | None,
    basic_trades: Sequence[dict[str, Any]] | None,
    config: LifeExplorationConfig | None = None,
    *,
    source_available: bool | Mapping[str, bool] = True,
    temporal_valid: bool = True,
) -> dict[str, Any]:
    """Build aggregate KAT coverage without returning reconstructed lives.

    A mapping may be supplied for ``source_available`` to mark one source as
    unavailable (keys: life_boundaries, frags, assists, basic_trades).  Any
    missing component suppresses KAT because silently treating it as empty
    would turn unknown contribution into observed zero contribution.
    """
    config = config or LifeExplorationConfig()
    config.validate()
    supplied = {
        "life_boundaries": life_boundaries,
        "frags": frags,
        "assists": assist_timeline,
        "basic_trades": basic_trades,
    }
    available = _availability(source_available, supplied)
    materialized = {name: _rows(rows) for name, rows in supplied.items()}
    source_coverage: dict[str, dict[str, Any]] = {
        name: {
            "available": available[name],
            "rows_received": len(materialized[name]) if supplied[name] is not None else None,
            "rows_usable": None,
            "rows_excluded": None,
        }
        for name in _SOURCE_NAMES
    }
    envelope: dict[str, Any] = {
        "definition": "life_kat_coverage_v2",
        "definition_version": 2,
        "parameters": {
            **asdict(config),
            "same_half": True,
            "denominator": "death_ended_lives_only",
            "covered_if_any": ["kill", "assist", "death_was_traded"],
            "kill_definition": "opposing_player_frag_inside_life",
            "kill_assist_membership": "credited_event_inside_inclusive_life_clock_interval",
            "traded_death_membership": "existing_basic_trade_linked_to_death_end",
            "consecutive_start": "censor_prior_life",
            "disconnect_end": "censored",
            "open_at_half_end": "censored",
            "survival_component": False,
            "life_scope": "physical_lives",
            "live_freeze_classification": "unavailable",
            "clock": "producer_game_time",
            "death_frag_coverage_required": "bijective_for_boundary_population",
        },
        "status": "available",
        "selected_clock": None,
        "source_coverage": source_coverage,
        "boundary_coverage": _empty_boundary_coverage(),
        "confidence": {"level": "unavailable", "basis": []},
        "visibility": "private_shadow_only",
        "writes": False,
        "rating_effect": False,
        "raw_timelines_included": False,
        "suicide_inventory": {
            "status": "source_not_captured",
            "count": None,
            "unmatched_death_boundaries": None,
        },
        "aggregate": _empty_aggregate(),
        "players": [],
        "teams": [],
        "limitations": [
            "This is KAT, not KAST: continuous respawn makes round survival inapplicable.",
            "Only death-ended lives enter the denominator; disconnect, consecutive-start, and open lives are censored.",
            "A context_live start may be left-censored and therefore lowers confidence.",
            "Kills and assists use producer game_time plus explicit half; association does not prove causal contribution.",
            "Canonical assist context supplies producer time, so delayed daemon receipt cannot move an assist into a later life.",
            "Trade credit inherits the existing basic-trade definition and its timing, roster, distance, and line-of-sight limitations.",
            "Each canonical victim frag in the observed boundary population must map to exactly one death-ended life, and each eligible life must map back to one canonical frag.",
            "Suicide and teamkill counts are not present in the canonical enemy-frag source; unmatched death boundaries therefore suppress KAT rather than being guessed as zero contribution.",
            "Life rows do not reliably classify live versus freeze/pause state; receipt-time inference is not used.",
        ],
    }

    if not all(available.values()):
        envelope["status"] = "source_not_captured"
        missing = [name for name in _SOURCE_NAMES if not available[name]]
        envelope["confidence"] = {
            "level": "unavailable",
            "basis": [f"Required source not captured: {', '.join(missing)}."],
        }
        return envelope
    if not temporal_valid:
        envelope["status"] = "timed_metrics_suppressed"
        envelope["confidence"] = {
            "level": "unavailable",
            "basis": [
                "Replay timing was marked invalid, so life membership and KAT were not inferred."
            ],
        }
        return envelope

    clock = _select_clock(
        materialized["life_boundaries"],
        materialized["frags"] + materialized["assists"],
    )
    envelope["selected_clock"] = clock
    if clock is None:
        for coverage in source_coverage.values():
            coverage["rows_usable"] = 0
            coverage["rows_excluded"] = int(coverage["rows_received"] or 0)
        envelope["status"] = "insufficient_boundary_data"
        envelope["confidence"] = _confidence(
            envelope["status"], envelope["boundary_coverage"], source_coverage,
            clock,
        )
        return envelope

    normalized_boundaries = [
        normalized
        for index, row in enumerate(materialized["life_boundaries"])
        if (normalized := _normalize_boundary(row, clock, index)) is not None
    ]
    normalized_frags = [
        normalized for index, row in enumerate(materialized["frags"])
        if (normalized := _normalize_frag(row, clock, index)) is not None
    ]
    normalized_assists = [
        normalized for row in materialized["assists"]
        if (normalized := _normalize_assist(row, clock)) is not None
    ]
    normalized_trades = [
        normalized for row in materialized["basic_trades"]
        if (normalized := _normalize_trade(row, clock)) is not None
    ]
    normalized_by_name = {
        "life_boundaries": normalized_boundaries,
        "frags": normalized_frags,
        "assists": normalized_assists,
        "basic_trades": normalized_trades,
    }
    for name, rows in normalized_by_name.items():
        source_coverage[name]["rows_usable"] = len(rows)
        source_coverage[name]["rows_excluded"] = (
            len(materialized[name]) - len(rows)
        )
    source_coverage["frags"]["opposing_player_kill_rows"] = sum(
        bool(row["opponent"]) for row in normalized_frags
    )
    source_coverage["frags"]["missing_team_context_rows"] = sum(
        row["classification"] == "opponent_missing_team_context"
        for row in normalized_frags
    )
    source_coverage["frags"]["explicit_same_team_rows"] = sum(
        row["classification"] == "explicit_same_team"
        for row in normalized_frags
    )
    source_coverage["frags"]["self_rows"] = sum(
        row["classification"] == "self" for row in normalized_frags
    )
    source_coverage["frags"]["rows_usable"] = source_coverage["frags"][
        "opposing_player_kill_rows"
    ]
    source_coverage["frags"]["rows_excluded"] = (
        len(materialized["frags"])
        - int(source_coverage["frags"]["rows_usable"] or 0)
    )

    if not normalized_boundaries:
        envelope["status"] = "insufficient_boundary_data"
        boundary_coverage = _empty_boundary_coverage()
        boundary_coverage.update({
            "rows_usable": 0,
            "rows_excluded": len(materialized["life_boundaries"]),
        })
        envelope["boundary_coverage"] = boundary_coverage
        envelope["confidence"] = _confidence(
            envelope["status"], boundary_coverage, source_coverage, clock
        )
        return envelope

    lives, reconstructed_coverage = _reconstruct_lives(normalized_boundaries)
    boundary_coverage = _empty_boundary_coverage()
    boundary_coverage.update(reconstructed_coverage)
    boundary_coverage["rows_usable"] = len(normalized_boundaries)
    boundary_coverage["rows_excluded"] = (
        len(materialized["life_boundaries"]) - len(normalized_boundaries)
    )
    eligible_lives = [life for life in lives if bool(life["eligible"])]

    wholly_unusable_sources = [
        name for name in ("frags", "assists", "basic_trades")
        if int(source_coverage[name]["rows_received"] or 0) > 0
        and int(source_coverage[name]["rows_usable"] or 0) == 0
    ]
    if eligible_lives and wholly_unusable_sources:
        envelope["status"] = "insufficient_source_data"
        envelope["boundary_coverage"] = boundary_coverage
        envelope["confidence"] = {
            "level": "unavailable",
            "basis": [
                "Rows were supplied but none were usable from: "
                + ", ".join(wholly_unusable_sources)
                + ". KAT was suppressed rather than treating unknown contribution as zero."
            ],
        }
        return envelope

    boundary_population = {row["key"] for row in normalized_boundaries}
    relevant_opponent_frags = [
        frag for frag in normalized_frags
        if frag["opponent"]
        and (
            config.require_complete_match_frag_coverage
            or frag["victim_key"] in boundary_population
        )
    ]
    victim_frags: dict[
        tuple[int, tuple[str, str]], list[dict[str, Any]]
    ] = defaultdict(list)
    for frag in relevant_opponent_frags:
        victim_frags[(int(frag["half"]), frag["victim_key"])].append(frag)
    for rows in victim_frags.values():
        rows.sort(key=lambda row: _position(row["at"], row["event_id"]))

    used_death_frag_indexes: set[int] = set()
    death_frags_by_life_index: dict[int, dict[str, Any]] = {}
    death_matches = 0
    for life_index, life in enumerate(eligible_lives):
        death_frag = _match_death_frag(
            life,
            victim_frags,
            used_death_frag_indexes,
            config.death_match_tolerance_seconds,
        )
        if death_frag is not None:
            death_matches += 1
            used_death_frag_indexes.add(int(death_frag["source_index"]))
            death_frags_by_life_index[life_index] = death_frag

    unmatched_victim_frags = (
        len(relevant_opponent_frags) - len(used_death_frag_indexes)
    )
    bijective = (
        death_matches == len(eligible_lives)
        and unmatched_victim_frags == 0
    )
    boundary_coverage["death_boundaries_matched_to_frags"] = death_matches
    boundary_coverage["death_frag_match_coverage"] = _rate(
        death_matches, len(eligible_lives)
    )
    boundary_coverage["canonical_victim_frags_in_boundary_population"] = len(
        relevant_opponent_frags
    )
    boundary_coverage["canonical_victim_frags_matched_to_death_boundaries"] = len(
        used_death_frag_indexes
    )
    boundary_coverage["canonical_victim_frags_unmatched"] = unmatched_victim_frags
    boundary_coverage["death_frag_bijection_complete"] = bijective
    envelope["boundary_coverage"] = boundary_coverage
    envelope["suicide_inventory"]["unmatched_death_boundaries"] = (
        len(eligible_lives) - death_matches
    )

    if (eligible_lives or relevant_opponent_frags) and not bijective:
        envelope["status"] = "incomplete_death_frag_coverage"
        envelope["confidence"] = {
            "level": "unavailable",
            "basis": [
                "Canonical victim frags and death-ended lives did not form a one-to-one mapping. Unmatched deaths may be suicides/teamkills or missing facts, so KAT was suppressed."
            ],
        }
        return envelope

    for life_index, life in enumerate(eligible_lives):
        death_frag = death_frags_by_life_index.get(life_index)
        life["had_kill"] = any(
            frag["opponent"]
            and frag["killer_key"] == life["key"]
            and _inside_life(life, frag)
            for frag in normalized_frags
        )
        life["had_assist"] = any(
            assist["assister_key"] == life["key"]
            and _inside_life(life, assist)
            for assist in normalized_assists
        )
        life["death_was_traded"] = _death_was_traded(
            life,
            death_frag,
            normalized_trades,
            config.death_match_tolerance_seconds,
        )
        life["covered"] = bool(
            life["had_kill"] or life["had_assist"] or life["death_was_traded"]
        )

    if not eligible_lives:
        envelope["status"] = "no_eligible_lives"
        envelope["aggregate"] = {
            **_empty_aggregate(),
            "eligible_lives": 0,
        }
        envelope["confidence"] = _confidence(
            envelope["status"], boundary_coverage, source_coverage, clock
        )
        return envelope

    envelope["aggregate"] = _aggregate_lives(eligible_lives)
    envelope["players"], envelope["teams"] = _group_aggregates(eligible_lives)
    envelope["confidence"] = _confidence(
        envelope["status"], boundary_coverage, source_coverage, clock
    )
    return envelope
