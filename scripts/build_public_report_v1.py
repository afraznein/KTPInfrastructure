#!/usr/bin/env python3
"""Build and atomically publish the fail-closed public-report-v1 bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import threading
import time
import unicodedata
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


PUBLIC_REPORT_SCHEMA = "public-report-v1"
PUBLIC_TIMELINE_SCHEMA = "public-timeline-v1"
MOMENTUM_EPISODE_SCHEMA = "momentumEpisode-v1"
CONTRACT_VERSION = "1.2.0"
ANALYTICS_BOX_SCHEMA = 3
PRIVATE_SCORING_SCHEMA = 1
TEAM_KEYS = ("team_a", "team_b")
SIDES = frozenset({"allies", "axis", "unknown"})
PUBLIC_STATUSES = frozenset({"PASS", "WARN", "FAIL", "UNAVAILABLE"})
AVAILABILITY = frozenset({"available", "low_sample", "unavailable"})
CONFIDENCE = frozenset({"exact", "synthetic", "descriptive", "low_sample", "unavailable"})
METRIC_REASON_CODES = frozenset({
    "none", "not_supplied", "low_sample", "synthetic_fixture",
    "undefined_zero_denominator",
})
COVERAGE_REASON_CODES = frozenset({
    "complete", "partial_input", "no_bins", "no_episodes",
    "missing_totals", "missing_momentum", "partial_evidence",
    "insufficient_evidence", "missing_halves", "irregular_interval",
})
CONSERVATION_REASON_CODES = frozenset({
    "equations_hold", "missing_totals", "equation_mismatch",
})
MOMENTUM_REASON_CODES = frozenset({
    "capture", "cap_break", "capout", "three_kill_chain", "multi_kill_chain",
    "opening_duel", "trade_kill", "objective_hold", "flag_defense",
    "combat_swing", "territory_pressure", "mixed", "insufficient_evidence",
})
MOMENTUM_CONFIDENCE_REASONS = frozenset({
    "complete_evidence", "partial_evidence", "insufficient_evidence",
})
MAX_HALVES = 10
MAX_DURATION_SECONDS = 21_600.0
MAX_BIN_SECONDS = 300.0
MAX_EVENT_TIME_SECONDS = 21_600.0
MAX_STAT_VALUE = 1_000_000
MAX_TEAM_POINTS = 1_000_000_000.0
MAX_MOMENTUM = 1_000_000.0
MIN_STALE_LOCK_SECONDS = 300.0
DEFAULT_STALE_LOCK_SECONDS = 900.0
DEFAULT_LOCK_WAIT_SECONDS = 30.0
MAX_LOCK_WAIT_SECONDS = 3_600.0

BOX_METRICS = (
    "kills", "deaths", "plus_minus", "assists", "headshots", "team_kills",
    "suicides", "damage_dealt", "damage_taken", "damage_differential",
    "capture_credits", "cap_breaks", "shots", "hits", "raw_accuracy",
)
ADDITIVE_METRICS = (
    "kills", "deaths", "assists", "headshots", "team_kills", "suicides",
    "damage_dealt", "damage_taken", "capture_credits", "cap_breaks", "shots",
    "hits",
)
INTEGER_METRICS = frozenset(ADDITIVE_METRICS)

FORBIDDEN_NORMALIZED_KEYS = frozenset({
    "databaseid", "dbid", "playerid", "steamid", "actorid", "killerid",
    "victimid", "attackerid", "assisterid", "eventid", "auditplayerkey",
    "elo", "bradleyterry", "impactindex", "impactrating", "overallrating",
    "accumulatedrating", "totalpoints", "rawpoints", "normalizedpoints",
    "playerpoints", "pointsperminute", "rank", "allocation", "allocations",
    "ledger", "ledgers", "components", "componenttotals", "scoringprofile",
    "scoringprofilehash", "profilehash", "sourceprofilehash", "provenance",
    "coordinates", "coordinate", "position", "positions", "positionsamples",
    "route", "routes", "cell", "cells", "sparsecells", "spatialfields",
    "sparsespatialfields",
    "flagid", "flagname", "posx", "posy", "posz", "posvictimx",
    "posvictimy", "posvictimz", "pointgaindifferential",
})
FORBIDDEN_EMBEDDED_KEY_TOKENS = frozenset({
    "databaseid", "playerid", "steamid", "actorid", "killerid",
    "victimid", "attackerid", "assisterid", "eventid", "internalplayerid",
    "auditplayerkey", "auditidentity", "hmac", "sourceschema",
    "elorating", "bradleyterry", "impactrating", "overallrating",
    "accumulatedrating", "positionsample", "posx", "posy", "posz",
})
ALLOWED_AGGREGATE_POINT_KEYS = frozenset({
    "pointsgained", "cumulativepoints", "teampoints",
})
ALLOWED_PRIVACY_DECLARATION_KEYS = frozenset({
    "playeridentity",
})
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"STEAM_[0-5]:[01]:\d+", re.IGNORECASE),
    re.compile(r"\[U:1:\d+\]", re.IGNORECASE),
    re.compile(r"(?<!\d)7656119\d{10}(?!\d)"),
    re.compile(r"\d{12,}"),
    re.compile(r"(?:https?|ftp)://|www\.", re.IGNORECASE),
    re.compile(r"(?:^|\s)[A-Za-z]:[\\/]"),
    re.compile(r"\\\\[^\\\s]+[\\/]"),
    re.compile(r"(?:^|\s)/(?:home|users|var|tmp|etc|opt)/", re.IGNORECASE),
    re.compile(r"\b(?:database|db|player|actor|killer|victim|assister)[ _-]?id\b", re.IGNORECASE),
    re.compile(r"\b(?:provenance|worktree|source[ _-](?:file|schema|path))\b", re.IGNORECASE),
    re.compile(
        r"(?<![A-Za-z0-9])(?:hmac|audit[ _-]?(?:player[ _-]?key|identity))"
        r"(?![A-Za-z0-9])",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?<![A-Za-z0-9])(?:elo|rating|bradley[ _-]?terry|"
        r"(?:impact|overall|accumulated)[ _-]?rating)(?![A-Za-z0-9])",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?<![A-Za-z0-9])(?:pos[xyz]|positions?|position[ _-]?samples?|"
        r"coordinates?|routes?|cells?|spatial(?:[ _-]?(?:field|data|detail)s?)?)"
        r"(?![A-Za-z0-9])",
        re.IGNORECASE,
    ),
)
NORMALIZED_SENSITIVE_TOKENS = frozenset({
    "steamid", "playerid", "actorid", "killerid", "victimid", "assisterid",
    "attackerid", "databaseid", "dbid", "eventid", "provenance", "worktree",
    "sourceschema", "sourcefile", "sourcepath", "privatepath",
    "auditplayerkey", "auditidentity", "hmacidentity", "hmacauditidentity",
    "elorating", "bradleyterry", "impactrating", "overallrating",
    "accumulatedrating", "positionsample", "positiondata", "posx", "posy",
    "posz", "spatialfield",
})
HMAC_SENSITIVE_SUFFIX = (
    r"(?:identity|id|playerkey|(?:private)?key|digest|signature|[0-9a-f]{8,})"
)
SENSITIVE_CONCATENATED_VALUE_PATTERNS = (
    ("hmac", re.compile(rf"hmac(?:audit)?{HMAC_SENSITIVE_SUFFIX}")),
    ("elo", re.compile(
        r"elo(?:rating|score|value|data|id|key|(?:player)?rank(?:ed|ing|s)?|\d)"
    )),
    ("rating", re.compile(r"rating(?:score|value|data|id|key|\d)")),
    ("position", re.compile(r"positions?(?:samples?|data|value|id|key|\d)")),
    ("coordinate", re.compile(r"coordinates?(?:samples?|data|value|id|key|\d)")),
    ("route", re.compile(r"routes?(?:samples?|data|value|id|key|\d)")),
    ("cell", re.compile(r"cells?(?:samples?|data|value|id|key|\d)")),
)
PUBLIC_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
CLIP_TOKEN = re.compile(r"^clip_[a-f0-9]{32}$")


class PublicContractError(ValueError):
    """Input or output failed a public contract."""


def _normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def sensitive_key_reason(value: Any) -> str | None:
    """Return the restricted normalized key token, including embedded variants."""
    normalized = _normalized_key(value)
    if normalized in FORBIDDEN_NORMALIZED_KEYS:
        return normalized
    for token in FORBIDDEN_EMBEDDED_KEY_TOKENS:
        if token in normalized:
            return token
    return None


def sensitive_string_reason(value: str) -> str | None:
    normalized = _normalized_key(value)
    for token in NORMALIZED_SENSITIVE_TOKENS:
        if token in normalized:
            return token
    # Concatenated protected terms require evidence of private identity/data,
    # such as numeric payloads or explicit key/data/value/sample vocabulary.
    # This rejects direct-prefix obfuscations without treating incidental
    # substrings in ordinary words as restricted terms.
    for reason, pattern in SENSITIVE_CONCATENATED_VALUE_PATTERNS:
        if pattern.search(normalized):
            return reason
    for pattern in SENSITIVE_VALUE_PATTERNS:
        if pattern.search(value):
            return pattern.pattern
    return None


def safe_display_name(value: Any, *, label: str) -> str:
    """Validate display text; consumers must still render it as escaped text."""
    name = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not name or len(name) > 64:
        raise PublicContractError(f"{label} display name must contain 1-64 characters")
    if any(unicodedata.category(char).startswith("C") for char in name):
        raise PublicContractError(f"{label} display name contains control characters")
    if sensitive_string_reason(name):
        raise PublicContractError(f"{label} display name resembles restricted identity/data")
    return name


def privacy_violations(value: Any, path: str = "public") -> list[str]:
    """Return forbidden key, value, and non-finite-number paths."""
    violations: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            token = _normalized_key(key)
            player_path = ".players[" in path or path.endswith(".players")
            allowed_privacy_declaration = (
                path == "public.privacy" and token in ALLOWED_PRIVACY_DECLARATION_KEYS
            )
            if (
                (sensitive_key_reason(key) and not allowed_privacy_declaration)
                or (token.endswith("points") and token not in ALLOWED_AGGREGATE_POINT_KEYS)
                or (player_path and "point" in token)
            ):
                violations.append(f"{path}.{key}")
            violations.extend(privacy_violations(nested, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            violations.extend(privacy_violations(nested, f"{path}[{index}]"))
    elif isinstance(value, str):
        if sensitive_string_reason(value):
            violations.append(path)
    elif isinstance(value, float) and not math.isfinite(value):
        violations.append(path)
    return violations


def assert_public(value: Any) -> None:
    violations = privacy_violations(value)
    if violations:
        raise PublicContractError(
            "public privacy contract rejected: " + ", ".join(violations)
        )


def _schema_version(document: Mapping[str, Any], expected: int, label: str) -> None:
    if document.get("schema_version") != expected:
        raise PublicContractError(
            f"{label} schema_version must be {expected}, got {document.get('schema_version')!r}"
        )


def _closed_status(value: Any) -> str:
    candidate = str(value or "UNAVAILABLE").upper()
    return candidate if candidate in PUBLIC_STATUSES else "UNAVAILABLE"


def _token(value: Any, *, label: str) -> str:
    candidate = str(value or "")
    if not PUBLIC_TOKEN.fullmatch(candidate) or sensitive_string_reason(candidate):
        raise PublicContractError(f"{label} must be a safe public token")
    return candidate


def _finite_number(
    value: Any, *, integer: bool = False, minimum: float | None = None,
    maximum: float | None = None, label: str = "numeric fact",
) -> int | float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise PublicContractError(f"boolean is not a {label}")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise PublicContractError(f"invalid {label}: {value!r}") from exc
    if not math.isfinite(numeric):
        raise PublicContractError(f"{label} must be finite")
    if minimum is not None and numeric < minimum:
        raise PublicContractError(f"{label} must be >= {minimum}")
    if maximum is not None and numeric > maximum:
        raise PublicContractError(f"{label} must be <= {maximum}")
    if integer:
        if not numeric.is_integer():
            raise PublicContractError(f"{label} must be an integer: {value!r}")
        return int(numeric)
    return numeric


def _metric_status(
    source: Mapping[str, Any], metric: str, value: int | float | None,
    *, synthetic: bool, derived: bool = False,
) -> dict[str, str]:
    if value is None:
        reason = (
            "undefined_zero_denominator"
            if metric == "raw_accuracy" and source.get("shots") == 0
            else "not_supplied"
        )
        return {
            "availability": "unavailable",
            "confidence": "unavailable",
            "reason_code": reason,
        }
    explicit = (source.get("confidence") or {}).get(metric)
    requested = explicit.get("level") if isinstance(explicit, Mapping) else None
    if requested not in CONFIDENCE:
        requested = None
    if requested == "unavailable":
        raise PublicContractError(f"{metric} has a value but confidence is unavailable")
    confidence = str(requested or ("synthetic" if synthetic else (
        "descriptive" if metric == "raw_accuracy" else "exact"
    )))
    availability = "low_sample" if confidence == "low_sample" else "available"
    reason = (
        "low_sample" if availability == "low_sample"
        else "synthetic_fixture" if synthetic
        else "none"
    )
    return {
        "availability": availability,
        "confidence": confidence,
        "reason_code": reason,
    }


def _derive_player_metrics(source: Mapping[str, Any], *, synthetic: bool) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for metric in ADDITIVE_METRICS:
        row[metric] = _finite_number(
            source.get(metric), integer=True, minimum=0, maximum=MAX_STAT_VALUE,
            label=metric,
        )

    if row["kills"] is not None and row["deaths"] is not None:
        calculated_plus_minus = row["kills"] - row["deaths"]
        supplied = _finite_number(
            source.get("plus_minus"), minimum=-MAX_STAT_VALUE,
            maximum=MAX_STAT_VALUE, label="plus_minus",
        )
        if supplied is not None and supplied != calculated_plus_minus:
            raise PublicContractError("player plus_minus disagrees with kills - deaths")
        row["plus_minus"] = calculated_plus_minus
    else:
        row["plus_minus"] = None

    if row["damage_dealt"] is not None and row["damage_taken"] is not None:
        calculated_damage = row["damage_dealt"] - row["damage_taken"]
        supplied = _finite_number(
            source.get("damage_differential"), minimum=-MAX_STAT_VALUE,
            maximum=MAX_STAT_VALUE, label="damage_differential",
        )
        if supplied is not None and supplied != calculated_damage:
            raise PublicContractError("player damage_differential disagrees with damage facts")
        row["damage_differential"] = calculated_damage
    else:
        row["damage_differential"] = None

    if row["shots"] is not None and row["shots"] > 0 and row["hits"] is not None:
        calculated_accuracy = row["hits"] / row["shots"]
        supplied = _finite_number(
            source.get("raw_accuracy"), minimum=0, maximum=1,
            label="raw_accuracy",
        )
        if supplied is not None and not math.isclose(supplied, calculated_accuracy, abs_tol=1e-8):
            raise PublicContractError("player raw_accuracy disagrees with hits / shots")
        row["raw_accuracy"] = calculated_accuracy
    else:
        if source.get("raw_accuracy") not in (None, ""):
            raise PublicContractError("raw_accuracy requires non-zero shots and available hits")
        row["raw_accuracy"] = None

    row["metric_status"] = {
        metric: _metric_status(source, metric, row[metric], synthetic=synthetic)
        for metric in BOX_METRICS
    }
    return row


def _public_team_definitions(match: Mapping[str, Any], halves: int | None) -> dict[str, dict[str, Any]]:
    definitions: dict[str, dict[str, Any]] = {}
    for source in match.get("public_teams", []):
        key = str(source.get("team_key") or "")
        if key not in TEAM_KEYS or key in definitions:
            raise PublicContractError("public_teams must declare team_a and team_b exactly once")
        side_by_half = []
        seen_halves = set()
        for mapping in source.get("side_by_half", []):
            half_value = _finite_number(
                mapping.get("half"), integer=True, minimum=1,
                maximum=MAX_HALVES, label="side_by_half half",
            )
            if half_value is None:
                raise PublicContractError("side_by_half half is required")
            half = int(half_value)
            side = str(mapping.get("side") or "unknown").lower()
            if half < 1 or half in seen_halves or side not in SIDES:
                raise PublicContractError("invalid or duplicate side_by_half mapping")
            seen_halves.add(half)
            side_by_half.append({"half": half, "side": side})
        side_by_half.sort(key=lambda item: item["half"])
        if halves is not None and seen_halves != set(range(1, halves + 1)):
            raise PublicContractError("every played half needs an explicit team side mapping")
        definitions[key] = {
            "team_key": key,
            "display_name": safe_display_name(source.get("display_name"), label=key),
            "side_by_half": side_by_half,
        }
    if set(definitions) != set(TEAM_KEYS):
        raise PublicContractError("match.public_teams must declare team_a and team_b")
    if halves is not None:
        for half in range(1, halves + 1):
            sides = [
                next(row["side"] for row in definitions[key]["side_by_half"] if row["half"] == half)
                for key in TEAM_KEYS
            ]
            known = [side for side in sides if side != "unknown"]
            if len(known) != len(set(known)):
                raise PublicContractError("teams cannot share the same known side in one half")
    return definitions


def _aggregate_team_metrics(
    team_key: str, members: Sequence[Mapping[str, Any]], source: Mapping[str, Any],
    *, synthetic: bool,
) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for metric in ADDITIVE_METRICS:
        values = [member.get(metric) for member in members]
        calculated = None if not values or any(value is None for value in values) else sum(values)
        supplied = _finite_number(
            source.get(metric), integer=True, minimum=0, maximum=MAX_STAT_VALUE,
            label=f"{team_key} {metric}",
        )
        if supplied is not None and calculated is not None and supplied != calculated:
            raise PublicContractError(f"{team_key} {metric} disagrees with additive player total")
        if supplied is not None and calculated is None:
            raise PublicContractError(
                f"{team_key} {metric} cannot be authoritative while a player value is unavailable"
            )
        row[metric] = calculated

    row["plus_minus"] = (
        row["kills"] - row["deaths"]
        if row["kills"] is not None and row["deaths"] is not None else None
    )
    supplied_plus_minus = _finite_number(
        source.get("plus_minus"), minimum=-MAX_STAT_VALUE,
        maximum=MAX_STAT_VALUE, label=f"{team_key} plus_minus",
    )
    if supplied_plus_minus is not None and supplied_plus_minus != row["plus_minus"]:
        raise PublicContractError(f"{team_key} plus_minus disagrees with kills - deaths")
    row["damage_differential"] = (
        row["damage_dealt"] - row["damage_taken"]
        if row["damage_dealt"] is not None and row["damage_taken"] is not None else None
    )
    supplied_damage = _finite_number(
        source.get("damage_differential"), minimum=-MAX_STAT_VALUE,
        maximum=MAX_STAT_VALUE, label=f"{team_key} damage_differential",
    )
    if supplied_damage is not None and supplied_damage != row["damage_differential"]:
        raise PublicContractError(f"{team_key} damage_differential disagrees with damage facts")
    row["raw_accuracy"] = (
        row["hits"] / row["shots"]
        if row["shots"] is not None and row["shots"] > 0 and row["hits"] is not None else None
    )
    supplied_accuracy = _finite_number(
        source.get("raw_accuracy"), minimum=0, maximum=1,
        label=f"{team_key} raw_accuracy",
    )
    if supplied_accuracy is not None and (
        row["raw_accuracy"] is None
        or not math.isclose(supplied_accuracy, row["raw_accuracy"], abs_tol=1e-8)
    ):
        raise PublicContractError(f"{team_key} raw_accuracy disagrees with hits / shots")
    supplied_players = _finite_number(
        source.get("players"), integer=True, minimum=0, maximum=128,
        label=f"{team_key} players",
    )
    if supplied_players is not None and supplied_players != len(members):
        raise PublicContractError(f"{team_key} player count disagrees with player rows")
    row["players"] = len(members)
    row["metric_status"] = {
        metric: _metric_status(source, metric, row[metric], synthetic=synthetic, derived=True)
        for metric in BOX_METRICS
    }
    return row


def build_public_report(
    analytics: Mapping[str, Any], readiness: Mapping[str, Any] | None = None,
    private_scoring: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    _schema_version(analytics, ANALYTICS_BOX_SCHEMA, "analytics box score")
    match_id = _token(analytics.get("match_id"), label="analytics match_id")
    if readiness is not None:
        _schema_version(readiness, 1, "readiness report")
        if str(readiness.get("match_id") or "") != match_id:
            raise PublicContractError("readiness and analytics match IDs differ")
    if private_scoring is not None:
        _schema_version(private_scoring, PRIVATE_SCORING_SCHEMA, "private scoring report")
        scoring_match = str(
            private_scoring.get("match_id")
            or (private_scoring.get("match") or {}).get("match_id") or ""
        )
        if scoring_match != match_id:
            raise PublicContractError("private scoring and analytics match IDs differ")

    match = analytics.get("match") or {}
    halves = _finite_number(
        match.get("halves_played"), integer=True, minimum=1, maximum=MAX_HALVES,
        label="halves_played",
    )
    if halves is None:
        raise PublicContractError("halves_played is required")
    teams = _public_team_definitions(match, halves)
    synthetic = bool(match.get("is_test_match")) or match_id.endswith("-TEST")

    players = []
    for source in analytics.get("players", []):
        team_key = str(source.get("public_team_key") or "")
        if team_key not in TEAM_KEYS:
            raise PublicContractError("every player requires public_team_key team_a or team_b")
        row = {
            "name": safe_display_name(source.get("player_name_at_match"), label="player"),
            "team_key": team_key,
        }
        row.update(_derive_player_metrics(source, synthetic=synthetic))
        players.append(row)
    players.sort(key=lambda row: (
        row["team_key"], row["name"].casefold(),
        json.dumps(row, sort_keys=True, separators=(",", ":")),
    ))

    team_sources: dict[str, Mapping[str, Any]] = {}
    for source in analytics.get("teams", []):
        key = str(source.get("public_team_key") or "")
        if key not in TEAM_KEYS or key in team_sources:
            raise PublicContractError("analytics teams must declare team_a and team_b exactly once")
        team_sources[key] = source
    if set(team_sources) != set(TEAM_KEYS):
        raise PublicContractError("analytics teams must declare team_a and team_b")

    public_teams = []
    for key in TEAM_KEYS:
        members = [row for row in players if row["team_key"] == key]
        row = dict(teams[key])
        row.update(_aggregate_team_metrics(
            key, members, team_sources[key], synthetic=synthetic
        ))
        public_teams.append(row)

    quality = analytics.get("quality") or {}
    report = {
        "schema_version": PUBLIC_REPORT_SCHEMA,
        "contract_version": CONTRACT_VERSION,
        "match": {
            "match_id": match_id,
            "map_name": _token(match.get("map_name"), label="map_name"),
            "halves_played": halves,
            "duration_seconds": _finite_number(
                match.get("duration_seconds"), minimum=0,
                maximum=MAX_DURATION_SECONDS, label="duration_seconds",
            ),
            "synthetic": synthetic,
        },
        "status": _closed_status((readiness or {}).get("status") or quality.get("status")),
        "quality": {
            "analytics_status": _closed_status(quality.get("status")),
            "readiness_status": _closed_status((readiness or {}).get("status")),
        },
        "privacy": {
            "classification": "public_descriptive",
            "player_identity": "display_name_only",
            "ratings_and_accumulated_scoring": "not_exported",
            "individual_positions": "not_exported",
        },
        "teams": public_teams,
        "players": players,
    }
    validate_public_report_semantics(report)
    assert_public(report)
    return report


def _coverage(status: str, reason_code: str) -> dict[str, str]:
    if status not in {"available", "partial", "unavailable"}:
        raise PublicContractError("invalid coverage status")
    if reason_code not in COVERAGE_REASON_CODES:
        raise PublicContractError("invalid coverage reason_code")
    return {"status": status, "reason_code": reason_code}


def _team_timeline_values(source: Mapping[str, Any]) -> dict[str, float | None]:
    return {
        "points_gained": _finite_number(
            source.get("timed_points_gained"), minimum=0, maximum=MAX_TEAM_POINTS,
            label="timed_points_gained",
        ),
        "cumulative_points": _finite_number(
            source.get("cumulative_timed_points"), minimum=0,
            maximum=MAX_TEAM_POINTS, label="cumulative_timed_points",
        ),
    }


def _advance_cumulative_recurrence(
    expected: float | None, gained: float | None, cumulative: float | None,
) -> float | None:
    """Validate one public cumulative pair and retain only a continuous chain."""
    if expected is None:
        if cumulative is not None:
            raise PublicContractError(
                "timeline cumulative_points cannot resume after an unavailable recurrence"
            )
        return None
    if gained is None:
        if cumulative is not None:
            raise PublicContractError(
                "timeline cumulative_points cannot resume after an unavailable gain"
            )
        return None
    next_expected = expected + gained
    if cumulative is None:
        return None
    if not math.isclose(cumulative, next_expected, abs_tol=1e-8):
        raise PublicContractError("timeline cumulative_points recurrence failed")
    return next_expected


def _advance_momentum_recurrence(
    prior: float | None, momentum: float | None, change: float | None,
) -> float | None:
    """Validate one public momentum pair and retain only a continuous chain."""
    if prior is None:
        if momentum is not None or change is not None:
            raise PublicContractError(
                "timeline momentum cannot resume after an unavailable recurrence"
            )
        return None
    if momentum is None or change is None:
        return None
    if not math.isclose(change, momentum - prior, abs_tol=1e-8):
        raise PublicContractError("timeline momentum_change recurrence failed")
    return momentum


def build_public_timeline(source: Mapping[str, Any]) -> dict[str, Any]:
    _schema_version(source, 1, "private timeline")
    match_id = _token(source.get("match_id"), label="timeline match_id")
    halves_played = _finite_number(
        source.get("halves_played"), integer=True, minimum=1,
        maximum=MAX_HALVES, label="timeline halves_played",
    )
    if halves_played is None:
        raise PublicContractError("timeline halves_played is required")
    bin_seconds = _finite_number(
        source.get("bin_seconds"), minimum=1, maximum=MAX_BIN_SECONDS,
        label="bin_seconds",
    )
    if bin_seconds is None:
        raise PublicContractError("timeline bin_seconds is required")
    if tuple(source.get("teams") or ()) != TEAM_KEYS:
        raise PublicContractError("timeline teams must be ['team_a', 'team_b']")
    sign = source.get("momentum_sign") or {}
    if {sign.get("positive_team"), sign.get("negative_team")} != set(TEAM_KEYS):
        raise PublicContractError("momentum_sign must declare team_a and team_b")

    halves = []
    bin_count = 0
    top_complete = True
    numbered_halves = []
    for source_half in source.get("halves", []):
        half_value = _finite_number(
            source_half.get("half"), integer=True, minimum=1,
            maximum=halves_played, label="timeline half",
        )
        if half_value is None:
            raise PublicContractError("timeline half is required")
        numbered_halves.append((int(half_value), source_half))
    numbered_halves.sort(key=lambda item: item[0])
    seen_halves = set()
    for half_number, source_half in numbered_halves:
        if half_number in seen_halves:
            raise PublicContractError("timeline halves must be unique played-half integers")
        seen_halves.add(half_number)
        bins = []
        source_bins = sorted(
            source_half.get("bins", []),
            key=lambda row: (
                float("inf") if row.get("start_time") is None else float(row.get("start_time")),
                float("inf") if row.get("end_time") is None else float(row.get("end_time")),
            ),
        )
        previous_end: float | None = None
        expected_cumulative: dict[str, float | None] = {key: 0.0 for key in TEAM_KEYS}
        prior_momentum: float | None = 0.0
        for bin_index, source_bin in enumerate(source_bins):
            bin_count += 1
            source_teams = source_bin.get("teams") or {}
            if set(source_teams) != set(TEAM_KEYS):
                raise PublicContractError("every timeline bin must have team_a and team_b")
            start_time = _finite_number(
                source_bin.get("start_time"), minimum=0,
                maximum=MAX_EVENT_TIME_SECONDS, label="timeline start_time",
            )
            end_time = _finite_number(
                source_bin.get("end_time"), minimum=0,
                maximum=MAX_EVENT_TIME_SECONDS, label="timeline end_time",
            )
            if start_time is not None and end_time is not None and end_time < start_time:
                raise PublicContractError("timeline bin end_time precedes start_time")
            team_values = {
                key: _team_timeline_values(source_teams[key]) for key in TEAM_KEYS
            }
            momentum = _finite_number(
                source_bin.get("momentum"), minimum=-MAX_MOMENTUM,
                maximum=MAX_MOMENTUM, label="momentum",
            )
            momentum_change = _finite_number(
                source_bin.get("momentum_change"), minimum=-MAX_MOMENTUM,
                maximum=MAX_MOMENTUM, label="momentum_change",
            )
            totals_complete = all(
                value is not None for row in team_values.values() for value in row.values()
            )
            momentum_complete = momentum is not None and momentum_change is not None
            time_complete = start_time is not None and end_time is not None
            interval_regular = False
            if time_complete:
                width = float(end_time) - float(start_time)
                last_bin = bin_index == len(source_bins) - 1
                interval_regular = (
                    (bin_index > 0 or math.isclose(float(start_time), 0, abs_tol=1e-8))
                    and (previous_end is None or math.isclose(float(start_time), previous_end, abs_tol=1e-8))
                    and width > 0
                    and (
                        math.isclose(width, float(bin_seconds), abs_tol=1e-8)
                        or (last_bin and width <= float(bin_seconds))
                    )
                )
            for key in TEAM_KEYS:
                gained = team_values[key]["points_gained"]
                cumulative = team_values[key]["cumulative_points"]
                expected_cumulative[key] = _advance_cumulative_recurrence(
                    expected_cumulative[key],
                    None if gained is None else float(gained),
                    None if cumulative is None else float(cumulative),
                )
            prior_momentum = _advance_momentum_recurrence(
                prior_momentum,
                None if momentum is None else float(momentum),
                None if momentum_change is None else float(momentum_change),
            )
            requested_coverage = source_bin.get("coverage") or {}
            if totals_complete and momentum_complete and time_complete and interval_regular:
                if requested_coverage and requested_coverage != {
                    "status": "available", "reason_code": "complete",
                }:
                    raise PublicContractError("complete timeline bin has contradictory source coverage")
                coverage = _coverage("available", "complete")
            else:
                reason = (
                    "missing_totals" if not totals_complete
                    else "missing_momentum" if not momentum_complete
                    else "partial_input" if not time_complete
                    else "irregular_interval"
                )
                if reason == "irregular_interval" and requested_coverage != {
                    "status": "partial", "reason_code": "irregular_interval",
                }:
                    raise PublicContractError(
                        "irregular timeline interval requires explicit partial/irregular_interval coverage"
                    )
                coverage = _coverage("partial", reason)
                top_complete = False
            bins.append({
                "start_time": start_time,
                "end_time": end_time,
                "teams": team_values,
                "momentum": momentum,
                "momentum_change": momentum_change,
                "coverage": coverage,
            })
            if end_time is not None:
                previous_end = float(end_time)

        untimed = source_half.get("untimed_reconciliation_by_team") or {}
        reconciled = source_half.get("reconciled_total_by_team") or {}
        summaries = []
        annotations = []
        for key in TEAM_KEYS:
            gains = [row["teams"][key]["points_gained"] for row in bins]
            cumulative_values = [
                row["teams"][key]["cumulative_points"] for row in bins
            ]
            timed_sum = None if not gains or any(value is None for value in gains) else sum(gains)
            timed_total = (
                cumulative_values[-1]
                if cumulative_values and not any(value is None for value in cumulative_values)
                else None
            )
            delta = _finite_number(
                untimed.get(key), minimum=-MAX_TEAM_POINTS,
                maximum=MAX_TEAM_POINTS, label="untimed_reconciliation_delta",
            )
            reconciled_total = _finite_number(
                reconciled.get(key), minimum=0, maximum=MAX_TEAM_POINTS,
                label="reconciled_total",
            )
            if None in (timed_sum, timed_total, delta, reconciled_total):
                status = "unavailable"
                reason = "missing_totals"
                timed_difference = None
                reconciled_difference = None
                top_complete = False
            else:
                timed_difference = float(timed_total) - float(timed_sum)
                reconciled_difference = float(reconciled_total) - (
                    float(timed_total) + float(delta)
                )
                if math.isclose(timed_difference, 0, abs_tol=1e-8) and math.isclose(
                    reconciled_difference, 0, abs_tol=1e-8
                ):
                    status = "pass"
                    reason = "equations_hold"
                else:
                    status = "fail"
                    reason = "equation_mismatch"
                    top_complete = False
            summaries.append({
                "team_key": key,
                "timed_gain_sum": timed_sum,
                "timed_total": timed_total,
                "untimed_reconciliation_delta": delta,
                "reconciled_total": reconciled_total,
                "timed_difference": timed_difference,
                "reconciled_difference": reconciled_difference,
                "status": status,
                "reason_code": reason,
            })
            if delta not in (None, 0, 0.0):
                annotations.append({
                    "team_key": key,
                    "kind": "untimed_reconciliation",
                })
        irregular_half = any(
            row["coverage"]["reason_code"] == "irregular_interval" for row in bins
        )
        half_coverage = (
            _coverage("unavailable", "no_bins") if not bins
            else _coverage("available", "complete") if all(
                row["status"] == "pass" for row in summaries
            ) and all(row["coverage"]["status"] == "available" for row in bins)
            else _coverage("partial", "irregular_interval" if irregular_half else "partial_input")
        )
        halves.append({
            "half": half_number,
            "bins": bins,
            "half_end_annotations": annotations,
            "conservation": {
                "equations": [
                    "timed_total = sum(points_gained)",
                    "reconciled_total = timed_total + untimed_reconciliation_delta",
                ],
                "teams": summaries,
            },
            "coverage": half_coverage,
        })

    missing_halves = seen_halves != set(range(1, halves_played + 1))
    if missing_halves:
        top_complete = False
    top_coverage = (
        _coverage("unavailable", "no_bins") if bin_count == 0
        else _coverage("available", "complete") if top_complete
        else _coverage("partial", "missing_halves" if missing_halves else (
            "irregular_interval" if any(
                half["coverage"]["reason_code"] == "irregular_interval" for half in halves
            ) else "partial_input"
        ))
    )
    result = {
        "schema_version": PUBLIC_TIMELINE_SCHEMA,
        "contract_version": CONTRACT_VERSION,
        "match_id": match_id,
        "halves_played": halves_played,
        "bin_seconds": bin_seconds,
        "team_keys": list(TEAM_KEYS),
        "momentum_sign": {
            "positive_team": str(sign.get("positive_team")),
            "negative_team": str(sign.get("negative_team")),
        },
        "privacy": {
            "scope": "team_only",
            "player_scoring": "not_exported",
            "team_points": "precomputed_aggregate_only",
            "individual_timing": "not_exported",
            "spatial_detail": "not_exported",
        },
        "quality": {
            "calculation": "producer_precomputed",
            "browser_calculation_allowed": False,
            "conservation_checked": True,
        },
        "coverage": top_coverage,
        "halves": halves,
    }
    validate_public_timeline_semantics(result)
    assert_public(result)
    return result


def sanitize_momentum_episodes(
    episodes: Iterable[Mapping[str, Any]], *, match_id: str, halves_played: int,
) -> dict[str, Any]:
    match_id = _token(match_id, label="momentum match_id")
    halves_played = int(_finite_number(
        halves_played, integer=True, minimum=1, maximum=MAX_HALVES,
        label="momentum halves_played",
    ))
    prepared = []
    for source in episodes:
        team_key = str(source.get("team_key") or source.get("team") or "")
        if team_key not in TEAM_KEYS:
            raise PublicContractError("momentum episode team_key must be team_a or team_b")
        half = int(_finite_number(
            source.get("half"), integer=True, minimum=1,
            maximum=halves_played, label="momentum half",
        ))
        start = _finite_number(
            source.get("start_time"), minimum=0, maximum=MAX_EVENT_TIME_SECONDS,
            label="momentum start_time",
        )
        end = _finite_number(
            source.get("end_time"), minimum=0, maximum=MAX_EVENT_TIME_SECONDS,
            label="momentum end_time",
        )
        if start is None or end is None or end < start:
            raise PublicContractError("momentum episode requires end_time >= start_time")
        end_momentum = _finite_number(
            source.get("end_momentum"), minimum=-MAX_MOMENTUM,
            maximum=MAX_MOMENTUM, label="end_momentum",
        )
        start_momentum = _finite_number(
            source.get("start_momentum"), minimum=-MAX_MOMENTUM,
            maximum=MAX_MOMENTUM, label="start_momentum",
        )
        if start_momentum is None or end_momentum is None:
            raise PublicContractError("momentum episode endpoints are required")
        calculated_swing = end_momentum - start_momentum
        supplied_swing = _finite_number(
            source.get("swing"), minimum=-MAX_MOMENTUM,
            maximum=MAX_MOMENTUM, label="momentum swing",
        )
        if supplied_swing is not None and not math.isclose(
            supplied_swing, calculated_swing, abs_tol=1e-8
        ):
            raise PublicContractError("momentum swing must equal end_momentum - start_momentum")
        contribution = source.get("contribution") or {}
        supplied_contribution = _finite_number(
            contribution.get("value"), minimum=-MAX_MOMENTUM,
            maximum=MAX_MOMENTUM, label="momentum contribution",
        )
        if supplied_contribution is not None and not math.isclose(
            supplied_contribution, calculated_swing, abs_tol=1e-8
        ):
            raise PublicContractError("momentum contribution must equal the episode swing")
        reasons = sorted(set(str(reason) for reason in source.get("reason_codes", [])))
        unknown = sorted(set(reasons) - MOMENTUM_REASON_CODES)
        if unknown:
            raise PublicContractError(f"unknown momentum reason code(s): {unknown}")
        if not reasons:
            reasons = ["insufficient_evidence"]
        confidence = source.get("confidence") or {}
        confidence_level = str(confidence.get("level") or "unavailable")
        confidence_reason = str(confidence.get("reason_code") or "insufficient_evidence")
        if confidence_level not in {"high", "medium", "low", "unavailable"}:
            raise PublicContractError("invalid momentum confidence level")
        if confidence_reason not in MOMENTUM_CONFIDENCE_REASONS:
            raise PublicContractError("invalid momentum confidence reason_code")
        coverage = source.get("coverage") or {}
        coverage_status = str(coverage.get("status") or "unavailable")
        coverage_reason = str(coverage.get("reason_code") or "insufficient_evidence")
        if coverage_status not in {"available", "partial", "unavailable"}:
            raise PublicContractError("invalid momentum coverage status")
        if coverage_reason not in COVERAGE_REASON_CODES:
            raise PublicContractError("invalid momentum coverage reason_code")
        clip_ref = source.get("clip_ref")
        if clip_ref is not None:
            clip_ref = str(clip_ref)
            if not CLIP_TOKEN.fullmatch(clip_ref) or sensitive_string_reason(clip_ref):
                raise PublicContractError("clip_ref must be an opaque server-issued clip token")
        direction = "positive" if calculated_swing > 0 else "negative" if calculated_swing < 0 else "neutral"
        item = {
            "half": half,
            "start_time": start,
            "end_time": end,
            "team_key": team_key,
            "direction": direction,
            "start_momentum": start_momentum,
            "end_momentum": end_momentum,
            "swing": calculated_swing,
            "reason_codes": reasons,
            "contribution": {
                "kind": "momentum_swing",
                "value": calculated_swing,
                "unit": "momentum_index",
            },
            "confidence": {
                "level": confidence_level,
                "reason_code": confidence_reason,
            },
            "coverage": {
                "status": coverage_status,
                "reason_code": coverage_reason,
            },
            "clip_ref": str(clip_ref) if clip_ref is not None else None,
        }
        prepared.append(item)

    prepared.sort(key=lambda item: (
        item["half"], item["start_time"], item["end_time"], item["team_key"],
        item["reason_codes"], item["swing"], item["clip_ref"] or "",
    ))
    seen_ids = set()
    public = []
    for item in prepared:
        canonical = json.dumps(item, sort_keys=True, separators=(",", ":"))
        episode_id = "episode_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        if episode_id in seen_ids:
            raise PublicContractError("duplicate canonical momentum episode")
        seen_ids.add(episode_id)
        public.append({"episode_id": episode_id, **item})

    if not public:
        top_coverage = _coverage("unavailable", "no_episodes")
    elif all(row["coverage"]["status"] == "available" for row in public):
        top_coverage = _coverage("available", "complete")
    else:
        top_coverage = _coverage("partial", "partial_evidence")
    result = {
        "schema_version": MOMENTUM_EPISODE_SCHEMA,
        "contract_version": CONTRACT_VERSION,
        "match_id": match_id,
        "halves_played": halves_played,
        "team_keys": list(TEAM_KEYS),
        "producer": "analytics_only",
        "browser_inference_allowed": False,
        "coverage": top_coverage,
        "episodes": public,
    }
    validate_momentum_semantics(result)
    assert_public(result)
    return result


def _validate_metric_pair(value: Any, status: Mapping[str, Any], path: str) -> None:
    availability = status.get("availability")
    confidence = status.get("confidence")
    reason = status.get("reason_code")
    if availability not in AVAILABILITY or confidence not in CONFIDENCE or reason not in METRIC_REASON_CODES:
        raise PublicContractError(f"{path} has invalid metric status codes")
    if availability == "unavailable":
        if value is not None or confidence != "unavailable" or reason not in {"not_supplied", "undefined_zero_denominator"}:
            raise PublicContractError(f"{path} unavailable metric contradiction")
    elif value is None or confidence == "unavailable" or reason == "not_supplied":
        raise PublicContractError(f"{path} available metric contradiction")
    if availability == "low_sample" and (confidence != "low_sample" or reason != "low_sample"):
        raise PublicContractError(f"{path} low_sample metric contradiction")
    if availability == "available":
        expected_reason = "synthetic_fixture" if confidence == "synthetic" else "none"
        if reason != expected_reason or confidence == "low_sample":
            raise PublicContractError(f"{path} available metric reason contradiction")


def _validate_coverage_contract(coverage: Mapping[str, Any], path: str) -> None:
    status = coverage.get("status")
    reason = coverage.get("reason_code")
    allowed = {
        "available": {"complete"},
        "partial": {
            "partial_input", "missing_totals", "missing_momentum",
            "partial_evidence", "missing_halves", "irregular_interval",
        },
        "unavailable": {"no_bins", "no_episodes", "insufficient_evidence"},
    }
    if status not in allowed or reason not in allowed[status]:
        raise PublicContractError(f"{path} coverage status/reason contradiction")


def validate_public_report_semantics(report: Mapping[str, Any]) -> None:
    if report.get("schema_version") != PUBLIC_REPORT_SCHEMA:
        raise PublicContractError("wrong public report schema")
    if report.get("contract_version") != CONTRACT_VERSION:
        raise PublicContractError("wrong public report contract_version")
    match = report.get("match") or {}
    _token(match.get("match_id"), label="public match_id")
    _token(match.get("map_name"), label="public map_name")
    halves_played = _finite_number(
        match.get("halves_played"), integer=True, minimum=1,
        maximum=MAX_HALVES, label="public halves_played",
    )
    _finite_number(
        match.get("duration_seconds"), minimum=0, maximum=MAX_DURATION_SECONDS,
        label="public duration_seconds",
    )
    teams = report.get("teams") or []
    if [row.get("team_key") for row in teams] != list(TEAM_KEYS):
        raise PublicContractError("public report teams must be team_a then team_b")
    declared = set(TEAM_KEYS)
    for row in teams:
        safe_display_name(row.get("display_name"), label=str(row.get("team_key")))
        side_rows = row.get("side_by_half") or []
        half_numbers = [item.get("half") for item in side_rows]
        expected_halves = halves_played
        if expected_halves is not None and half_numbers != list(range(1, expected_halves + 1)):
            raise PublicContractError("team side_by_half does not cover every half in order")
    for half in range(1, int(halves_played) + 1):
        sides = [
            next(item["side"] for item in row["side_by_half"] if item["half"] == half)
            for row in teams
        ]
        known = [side for side in sides if side != "unknown"]
        if len(known) != len(set(known)):
            raise PublicContractError("teams cannot share the same known side in one half")
    for collection in (teams, report.get("players") or []):
        for index, row in enumerate(collection):
            if row.get("team_key") not in declared:
                raise PublicContractError("row references undeclared team_key")
            if collection is not teams:
                safe_display_name(row.get("name"), label="player")
            statuses = row.get("metric_status") or {}
            if set(statuses) != set(BOX_METRICS):
                raise PublicContractError("metric_status must cover every box metric")
            for metric in BOX_METRICS:
                if row.get(metric) is not None:
                    if metric in ADDITIVE_METRICS:
                        _finite_number(
                            row[metric], integer=True, minimum=0,
                            maximum=MAX_STAT_VALUE, label=metric,
                        )
                    elif metric == "raw_accuracy":
                        _finite_number(
                            row[metric], minimum=0, maximum=1, label=metric,
                        )
                    else:
                        _finite_number(
                            row[metric], minimum=-MAX_STAT_VALUE,
                            maximum=MAX_STAT_VALUE, label=metric,
                        )
                _validate_metric_pair(row.get(metric), statuses[metric], f"row[{index}].{metric}")
            expected_plus_minus = (
                row["kills"] - row["deaths"]
                if row.get("kills") is not None and row.get("deaths") is not None else None
            )
            if row.get("plus_minus") != expected_plus_minus:
                raise PublicContractError("row plus_minus disagrees with kills - deaths")
            expected_damage = (
                row["damage_dealt"] - row["damage_taken"]
                if row.get("damage_dealt") is not None and row.get("damage_taken") is not None else None
            )
            if row.get("damage_differential") != expected_damage:
                raise PublicContractError("row damage_differential disagrees with damage facts")
            expected_accuracy = (
                row["hits"] / row["shots"]
                if row.get("shots") not in (None, 0) and row.get("hits") is not None else None
            )
            if row.get("raw_accuracy") != expected_accuracy:
                raise PublicContractError("row raw_accuracy disagrees with hits / shots")
    players = report.get("players") or []
    for team in teams:
        members = [row for row in players if row.get("team_key") == team["team_key"]]
        if team.get("players") != len(members):
            raise PublicContractError("team player count disagrees with player rows")
        for metric in ADDITIVE_METRICS:
            values = [row.get(metric) for row in members]
            calculated = None if not values or any(value is None for value in values) else sum(values)
            if team.get(metric) != calculated:
                raise PublicContractError(f"team {metric} disagrees with player rows")
        plus_minus = (
            team["kills"] - team["deaths"]
            if team.get("kills") is not None and team.get("deaths") is not None else None
        )
        if team.get("plus_minus") != plus_minus:
            raise PublicContractError("team plus_minus disagrees with kills - deaths")


def validate_public_timeline_semantics(timeline: Mapping[str, Any]) -> None:
    if timeline.get("schema_version") != PUBLIC_TIMELINE_SCHEMA:
        raise PublicContractError("wrong public timeline schema")
    if timeline.get("contract_version") != CONTRACT_VERSION:
        raise PublicContractError("wrong public timeline contract_version")
    halves_played = int(_finite_number(
        timeline.get("halves_played"), integer=True, minimum=1,
        maximum=MAX_HALVES, label="timeline halves_played",
    ))
    bin_seconds = float(_finite_number(
        timeline.get("bin_seconds"), minimum=1, maximum=MAX_BIN_SECONDS,
        label="timeline bin_seconds",
    ))
    if tuple(timeline.get("team_keys") or ()) != TEAM_KEYS:
        raise PublicContractError("timeline team_keys mismatch")
    sign = timeline.get("momentum_sign") or {}
    if {sign.get("positive_team"), sign.get("negative_team")} != set(TEAM_KEYS):
        raise PublicContractError("timeline momentum_sign mismatch")
    _validate_coverage_contract(timeline.get("coverage") or {}, "timeline")
    total_bins = 0
    half_numbers = [half.get("half") for half in timeline.get("halves") or []]
    if half_numbers != sorted(set(half_numbers)) or any(
        not isinstance(half, int) or isinstance(half, bool) or half < 1 or half > halves_played
        for half in half_numbers
    ):
        raise PublicContractError("timeline half list is not canonical or references an unplayed half")
    for half in timeline.get("halves") or []:
        bins = half.get("bins") or []
        total_bins += len(bins)
        _validate_coverage_contract(half.get("coverage") or {}, "timeline half")
        previous_end = None
        expected_cumulative: dict[str, float | None] = {key: 0.0 for key in TEAM_KEYS}
        prior_momentum: float | None = 0.0
        for bin_index, item in enumerate(half.get("bins") or []):
            if set(item.get("teams") or {}) != set(TEAM_KEYS):
                raise PublicContractError("timeline bin team keys mismatch")
            coverage = item.get("coverage") or {}
            _validate_coverage_contract(coverage, "timeline bin")
            values = [
                value for row in item["teams"].values() for value in row.values()
            ] + [
                item.get("momentum"), item.get("momentum_change"),
                item.get("start_time"), item.get("end_time"),
            ]
            if coverage.get("status") == "available" and any(value is None for value in values):
                raise PublicContractError("available timeline bin contains null")
            if item.get("start_time") is not None and item.get("end_time") is not None:
                start = float(_finite_number(
                    item["start_time"], minimum=0, maximum=MAX_EVENT_TIME_SECONDS,
                    label="timeline start_time",
                ))
                end = float(_finite_number(
                    item["end_time"], minimum=0, maximum=MAX_EVENT_TIME_SECONDS,
                    label="timeline end_time",
                ))
                if item["end_time"] < item["start_time"]:
                    raise PublicContractError("timeline bin end precedes start")
                if previous_end is not None and item["start_time"] < previous_end:
                    raise PublicContractError("timeline bins overlap or are not ordered")
                last_bin = bin_index == len(bins) - 1
                regular = (
                    (bin_index > 0 or math.isclose(start, 0, abs_tol=1e-8))
                    and (previous_end is None or math.isclose(start, previous_end, abs_tol=1e-8))
                    and end > start
                    and (
                        math.isclose(end - start, bin_seconds, abs_tol=1e-8)
                        or (last_bin and end - start <= bin_seconds)
                    )
                )
                if not regular and coverage != {
                    "status": "partial", "reason_code": "irregular_interval",
                }:
                    raise PublicContractError("timeline interval is irregular without partial coverage")
                if regular and coverage.get("reason_code") == "irregular_interval":
                    raise PublicContractError("timeline interval claims irregular coverage but is regular")
                previous_end = end
            for key in TEAM_KEYS:
                gained = item["teams"][key].get("points_gained")
                cumulative = item["teams"][key].get("cumulative_points")
                if gained is not None:
                    gained = float(_finite_number(
                        gained, minimum=0, maximum=MAX_TEAM_POINTS,
                        label="points_gained",
                    ))
                if cumulative is not None:
                    cumulative = float(_finite_number(
                        cumulative, minimum=0, maximum=MAX_TEAM_POINTS,
                        label="cumulative_points",
                    ))
                expected_cumulative[key] = _advance_cumulative_recurrence(
                    expected_cumulative[key], gained, cumulative,
                )
            momentum = item.get("momentum")
            change = item.get("momentum_change")
            if momentum is not None:
                momentum = float(_finite_number(
                    momentum, minimum=-MAX_MOMENTUM, maximum=MAX_MOMENTUM,
                    label="momentum",
                ))
            if change is not None:
                change = float(_finite_number(
                    change, minimum=-MAX_MOMENTUM, maximum=MAX_MOMENTUM,
                    label="momentum_change",
                ))
            prior_momentum = _advance_momentum_recurrence(
                prior_momentum, momentum, change,
            )
        annotations = half.get("half_end_annotations") or []
        for annotation in annotations:
            if annotation.get("team_key") not in TEAM_KEYS:
                raise PublicContractError("annotation references undeclared team_key")
        conservation_rows = (half.get("conservation") or {}).get("teams", [])
        if [row.get("team_key") for row in conservation_rows] != list(TEAM_KEYS):
            raise PublicContractError("conservation teams must be team_a then team_b")
        for row in conservation_rows:
            if row.get("team_key") not in TEAM_KEYS:
                raise PublicContractError("conservation references undeclared team_key")
            for field in ("timed_gain_sum", "timed_total", "reconciled_total"):
                if row.get(field) is not None:
                    _finite_number(
                        row[field], minimum=0, maximum=MAX_TEAM_POINTS,
                        label=f"conservation {field}",
                    )
            for field in (
                "untimed_reconciliation_delta", "timed_difference",
                "reconciled_difference",
            ):
                if row.get(field) is not None:
                    _finite_number(
                        row[field], minimum=-MAX_TEAM_POINTS,
                        maximum=MAX_TEAM_POINTS, label=f"conservation {field}",
                    )
            required = (
                row.get("timed_gain_sum"), row.get("timed_total"),
                row.get("untimed_reconciliation_delta"), row.get("reconciled_total"),
            )
            if not any(value is None for value in required):
                expected_timed_difference = float(row["timed_total"]) - float(
                    row["timed_gain_sum"]
                )
                expected_reconciled_difference = float(row["reconciled_total"]) - (
                    float(row["timed_total"])
                    + float(row["untimed_reconciliation_delta"])
                )
                if not math.isclose(
                    float(row.get("timed_difference")),
                    expected_timed_difference, abs_tol=1e-8,
                ) or not math.isclose(
                    float(row.get("reconciled_difference")),
                    expected_reconciled_difference, abs_tol=1e-8,
                ):
                    raise PublicContractError(
                        "conservation difference fields disagree with equations"
                    )
            if row.get("status") == "pass":
                if any(value is None for value in required):
                    raise PublicContractError("pass conservation has missing totals")
                if not math.isclose(float(row["timed_difference"]), 0, abs_tol=1e-8) or not math.isclose(
                    float(row["reconciled_difference"]), 0, abs_tol=1e-8
                ):
                    raise PublicContractError("pass conservation equations do not hold")
            if row.get("status") == "unavailable" and not any(value is None for value in required):
                raise PublicContractError("unavailable conservation has complete totals")
            if row.get("status") == "unavailable" and (
                row.get("timed_difference") is not None
                or row.get("reconciled_difference") is not None
            ):
                raise PublicContractError("unavailable conservation has numeric differences")
            expected_reason = {
                "pass": "equations_hold", "fail": "equation_mismatch",
                "unavailable": "missing_totals",
            }.get(row.get("status"))
            if row.get("reason_code") != expected_reason:
                raise PublicContractError("conservation status/reason contradiction")
            gains = [item["teams"][row["team_key"]]["points_gained"] for item in bins]
            calculated_sum = None if not gains or any(value is None for value in gains) else sum(gains)
            cumulative_values = [
                item["teams"][row["team_key"]]["cumulative_points"] for item in bins
            ]
            final_total = (
                cumulative_values[-1]
                if cumulative_values and not any(value is None for value in cumulative_values)
                else None
            )
            if row.get("timed_gain_sum") != calculated_sum or row.get("timed_total") != final_total:
                raise PublicContractError("conservation totals disagree with bins")
        expected_annotations = [
            {"team_key": row["team_key"], "kind": "untimed_reconciliation"}
            for row in conservation_rows
            if row.get("untimed_reconciliation_delta") not in (None, 0, 0.0)
        ]
        if annotations != expected_annotations:
            raise PublicContractError("half-end reconciliation annotations disagree with conservation")
        expected_half_coverage = (
            {"status": "unavailable", "reason_code": "no_bins"} if not bins
            else {"status": "available", "reason_code": "complete"}
            if all(item["coverage"]["status"] == "available" for item in bins)
            and all(row["status"] == "pass" for row in conservation_rows)
            else {"status": "partial", "reason_code": (
                "irregular_interval" if any(
                    item["coverage"]["reason_code"] == "irregular_interval" for item in bins
                ) else "partial_input"
            )}
        )
        if half.get("coverage") != expected_half_coverage:
            raise PublicContractError("timeline half coverage contradicts contents")
    missing_halves = set(half_numbers) != set(range(1, halves_played + 1))
    expected_top_coverage = (
        {"status": "unavailable", "reason_code": "no_bins"} if total_bins == 0
        else {"status": "available", "reason_code": "complete"}
        if not missing_halves and all(
            half["coverage"]["status"] == "available" for half in timeline.get("halves") or []
        )
        else {"status": "partial", "reason_code": (
            "missing_halves" if missing_halves else "irregular_interval" if any(
                half["coverage"]["reason_code"] == "irregular_interval"
                for half in timeline.get("halves") or []
            ) else "partial_input"
        )}
    )
    if timeline.get("coverage") != expected_top_coverage:
        raise PublicContractError("timeline top coverage contradicts halves")


def validate_momentum_semantics(document: Mapping[str, Any]) -> None:
    if document.get("schema_version") != MOMENTUM_EPISODE_SCHEMA:
        raise PublicContractError("wrong momentum episode schema")
    if document.get("contract_version") != CONTRACT_VERSION:
        raise PublicContractError("wrong momentum contract_version")
    halves_played = int(_finite_number(
        document.get("halves_played"), integer=True, minimum=1,
        maximum=MAX_HALVES, label="momentum halves_played",
    ))
    if tuple(document.get("team_keys") or ()) != TEAM_KEYS:
        raise PublicContractError("momentum team_keys mismatch")
    episodes = document.get("episodes") or []
    coverage = document.get("coverage") or {}
    _validate_coverage_contract(coverage, "momentum")
    if not episodes and coverage != {"status": "unavailable", "reason_code": "no_episodes"}:
        raise PublicContractError("empty momentum document must be unavailable/no_episodes")
    if episodes:
        expected_coverage = (
            {"status": "available", "reason_code": "complete"}
            if all(row.get("coverage", {}).get("status") == "available" for row in episodes)
            else {"status": "partial", "reason_code": "partial_evidence"}
        )
        if coverage != expected_coverage:
            raise PublicContractError("momentum top-level coverage contradicts episodes")
    previous = None
    ids = set()
    for row in episodes:
        _validate_coverage_contract(row.get("coverage") or {}, "momentum episode")
        if row.get("team_key") not in TEAM_KEYS:
            raise PublicContractError("momentum episode references undeclared team_key")
        _finite_number(
            row.get("half"), integer=True, minimum=1, maximum=halves_played,
            label="momentum half",
        )
        _finite_number(
            row.get("start_time"), minimum=0, maximum=MAX_EVENT_TIME_SECONDS,
            label="momentum start_time",
        )
        _finite_number(
            row.get("end_time"), minimum=0, maximum=MAX_EVENT_TIME_SECONDS,
            label="momentum end_time",
        )
        for key in ("start_momentum", "end_momentum", "swing"):
            _finite_number(
                row.get(key), minimum=-MAX_MOMENTUM, maximum=MAX_MOMENTUM,
                label=key,
            )
        if row["end_time"] < row["start_time"]:
            raise PublicContractError("momentum episode end precedes start")
        if not math.isclose(row["swing"], row["end_momentum"] - row["start_momentum"], abs_tol=1e-8):
            raise PublicContractError("momentum episode swing contradiction")
        if row.get("direction") != (
            "positive" if row["swing"] > 0 else "negative" if row["swing"] < 0 else "neutral"
        ):
            raise PublicContractError("momentum episode direction contradiction")
        if not row.get("reason_codes") or set(row["reason_codes"]) - MOMENTUM_REASON_CODES:
            raise PublicContractError("momentum episode has invalid reason_codes")
        if row.get("reason_codes") != sorted(set(row["reason_codes"])):
            raise PublicContractError("momentum reason_codes are not canonical")
        contribution = row.get("contribution") or {}
        if contribution.get("kind") != "momentum_swing" or contribution.get("unit") != "momentum_index" or not math.isclose(
            contribution.get("value"), row["swing"], abs_tol=1e-8
        ):
            raise PublicContractError("momentum contribution contradiction")
        confidence = row.get("confidence") or {}
        expected_confidence_reason = (
            "complete_evidence" if confidence.get("level") == "high"
            else "insufficient_evidence" if confidence.get("level") == "unavailable"
            else "partial_evidence"
        )
        if confidence.get("reason_code") != expected_confidence_reason:
            raise PublicContractError("momentum confidence status/reason contradiction")
        expected_episode_coverage_reason = {
            "available": "complete", "partial": "partial_evidence",
            "unavailable": "insufficient_evidence",
        }.get(row.get("coverage", {}).get("status"))
        if row.get("coverage", {}).get("reason_code") != expected_episode_coverage_reason:
            raise PublicContractError("momentum episode coverage contradiction")
        clip_ref = row.get("clip_ref")
        if clip_ref is not None and (
            not CLIP_TOKEN.fullmatch(str(clip_ref))
            or sensitive_string_reason(str(clip_ref))
        ):
            raise PublicContractError("momentum clip_ref is not an opaque token")
        canonical_order = (
            row["half"], row["start_time"], row["end_time"], row["team_key"],
            row["reason_codes"], row["swing"], row["clip_ref"] or "",
        )
        if previous is not None and canonical_order < previous:
            raise PublicContractError("momentum episodes are not canonically sorted")
        previous = canonical_order
        if row["episode_id"] in ids:
            raise PublicContractError("duplicate momentum episode ID")
        ids.add(row["episode_id"])
        item_without_id = {key: value for key, value in row.items() if key != "episode_id"}
        canonical = json.dumps(item_without_id, sort_keys=True, separators=(",", ":"))
        expected_id = "episode_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        if row["episode_id"] != expected_id:
            raise PublicContractError("momentum episode ID is not canonical")


def validate_bundle_consistency(
    report: Mapping[str, Any], timeline: Mapping[str, Any], episodes: Mapping[str, Any]
) -> None:
    match_id = report["match"]["match_id"]
    if timeline.get("match_id") != match_id or episodes.get("match_id") != match_id:
        raise PublicContractError("public documents have different match IDs")
    contract_versions = {
        report.get("contract_version"), timeline.get("contract_version"),
        episodes.get("contract_version"),
    }
    if contract_versions != {CONTRACT_VERSION}:
        raise PublicContractError("public documents have different contract versions")
    report_keys = tuple(row["team_key"] for row in report["teams"])
    if report_keys != TEAM_KEYS or tuple(timeline["team_keys"]) != TEAM_KEYS or tuple(episodes["team_keys"]) != TEAM_KEYS:
        raise PublicContractError("public documents have different team contracts")
    halves_played = report["match"].get("halves_played")
    if timeline.get("halves_played") != halves_played or episodes.get("halves_played") != halves_played:
        raise PublicContractError("public documents have different halves_played")
    timeline_halves = {half["half"] for half in timeline.get("halves") or []}
    if any(row["half"] not in timeline_halves for row in episodes.get("episodes") or []):
        raise PublicContractError("momentum episode references a half absent from the timeline")
    report_side_halves = {
        team["team_key"]: {row["half"] for row in team["side_by_half"]}
        for team in report["teams"]
    }
    for half in timeline_halves:
        if any(half not in report_side_halves[key] for key in TEAM_KEYS):
            raise PublicContractError("timeline half lacks report side mapping")
    half_ends: dict[int, float] = {}
    for half in timeline.get("halves") or []:
        bins = half.get("bins") or []
        if bins and bins[-1].get("end_time") is not None:
            half_ends[half["half"]] = float(bins[-1]["end_time"])
    for row in episodes.get("episodes") or []:
        end_time = half_ends.get(row["half"])
        if end_time is None or float(row["end_time"]) > end_time:
            raise PublicContractError("momentum episode falls outside its timeline half")
    if timeline.get("coverage") == {"status": "available", "reason_code": "complete"}:
        duration = report["match"].get("duration_seconds")
        if duration is None or len(half_ends) != halves_played or not math.isclose(
            sum(half_ends.values()), float(duration), abs_tol=1e-8
        ):
            raise PublicContractError(
                "complete timeline duration disagrees with the public report"
            )


def _read(path: Path | None) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8-sig")) if path else None


def _schema_directory() -> Path:
    script_root = Path(__file__).resolve().parents[1]
    candidates = (
        script_root / "development_candidate" / "public-report-v1" / "schemas",
        script_root / "schemas",
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise PublicContractError("cannot locate public schema directory")


def validate_json_schemas(documents: Mapping[str, Mapping[str, Any]], schema_dir: Path) -> None:
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise PublicContractError("publishing requires jsonschema>=4.18") from exc
    schema_names = {
        "public-report.json": "public-report-v1.schema.json",
        "public-timeline.json": "public-timeline-v1.schema.json",
        "momentum-episodes.json": "momentumEpisode-v1.schema.json",
    }
    for name, document in documents.items():
        schema = _read(schema_dir / schema_names[name])
        assert schema is not None
        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
        if errors:
            raise PublicContractError(f"{name} schema rejected: {errors[0].message}")


def _complete_bundle_directory(directory: Path, expected_names: set[str]) -> bool:
    """Recognize a previously published bundle without trusting its directory name."""
    if directory.is_symlink() or not directory.is_dir():
        return False
    try:
        children = list(directory.iterdir())
        if {child.name for child in children} != expected_names:
            return False
        for child in children:
            if child.is_symlink() or not child.is_file():
                return False
            value = json.loads(child.read_text(encoding="utf-8"))
            if not isinstance(value, Mapping):
                return False
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return True


def _remove_publish_artifact(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink(missing_ok=True)
    else:
        shutil.rmtree(path)


def _recover_interrupted_publish(output_dir: Path, expected_names: set[str]) -> None:
    """Restore the last installed bundle and remove transaction residue.

    The caller owns the adjacent publish lock, so every matching temporary,
    backup, or lock-quarantine path is necessarily orphaned by an earlier
    publisher. Directory renames keep both the recovery and normal install
    portable across Windows and POSIX filesystems.
    """
    prefixes = {
        "temporary": f".{output_dir.name}.tmp-",
        "backup": f".{output_dir.name}.old-",
        "quarantine": f".{output_dir.name}.stale-lock-",
    }
    residues: dict[str, list[Path]] = {key: [] for key in prefixes}
    for child in output_dir.parent.iterdir():
        for kind, prefix in prefixes.items():
            if child.name.startswith(prefix):
                residues[kind].append(child)
                break

    all_residue = [path for paths in residues.values() for path in paths]
    if output_dir.exists():
        if all_residue and not _complete_bundle_directory(output_dir, expected_names):
            raise PublicContractError(
                "refusing interrupted-publish recovery because the installed bundle is incomplete"
            )
    else:
        valid_backups = [
            path for path in residues["backup"]
            if _complete_bundle_directory(path, expected_names)
        ]
        if len(valid_backups) > 1:
            raise PublicContractError(
                "refusing ambiguous interrupted-publish recovery with multiple valid backups"
            )
        if valid_backups:
            restored = valid_backups[0]
            restored.rename(output_dir)
            all_residue.remove(restored)

    for path in all_residue:
        if path.exists() or path.is_symlink():
            _remove_publish_artifact(path)


@contextmanager
def _exclusive_publish_lock(
    output_dir: Path, *, stale_after_seconds: float = DEFAULT_STALE_LOCK_SECONDS,
    wait_timeout_seconds: float = DEFAULT_LOCK_WAIT_SECONDS,
):
    """Hold an adjacent portable lock, waiting and reclaiming only stale owners."""
    if (
        not math.isfinite(stale_after_seconds)
        or stale_after_seconds < MIN_STALE_LOCK_SECONDS
    ):
        raise PublicContractError(
            f"stale lock threshold must be finite and at least {MIN_STALE_LOCK_SECONDS:g} seconds"
        )
    if (
        not math.isfinite(wait_timeout_seconds)
        or wait_timeout_seconds < 0
        or wait_timeout_seconds > MAX_LOCK_WAIT_SECONDS
    ):
        raise PublicContractError(
            f"lock wait timeout must be between 0 and {MAX_LOCK_WAIT_SECONDS:g} seconds"
        )
    lock_dir = output_dir.parent / f".{output_dir.name}.publish.lock"
    owner_token = uuid.uuid4().hex
    deadline = time.monotonic() + wait_timeout_seconds
    while True:
        try:
            lock_dir.mkdir()
            break
        except FileExistsError as exc:
            try:
                age = max(0.0, time.time() - lock_dir.stat().st_mtime)
            except FileNotFoundError:
                continue
            if age < stale_after_seconds:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PublicContractError(
                        "timed out waiting for another publisher"
                    ) from exc
                time.sleep(min(0.05, remaining))
                continue
        # Rename is the ownership claim for stale-lock cleanup. A competing
        # reclaimer or renewed owner wins atomically and this publisher retries.
        quarantine = output_dir.parent / (
            f".{output_dir.name}.stale-lock-{uuid.uuid4().hex}"
        )
        try:
            lock_dir.rename(quarantine)
        except (FileNotFoundError, FileExistsError, PermissionError, OSError) as rename_exc:
            if time.monotonic() >= deadline:
                raise PublicContractError(
                    "publisher lock changed during stale-lock reclaim"
                ) from rename_exc
            continue
        try:
            shutil.rmtree(quarantine)
        except Exception:
            if quarantine.exists():
                shutil.rmtree(quarantine, ignore_errors=True)
            raise
    metadata = {
        "owner_token": owner_token,
        "pid": os.getpid(),
        "created_unix": time.time(),
        "contract_version": CONTRACT_VERSION,
    }
    owner_file = lock_dir / "owner.json"
    heartbeat_stop = threading.Event()
    heartbeat_interval = min(30.0, stale_after_seconds / 3.0)

    def heartbeat() -> None:
        while not heartbeat_stop.wait(heartbeat_interval):
            try:
                os.utime(lock_dir, None)
            except OSError:
                return

    heartbeat_thread: threading.Thread | None = None
    try:
        owner_file.write_text(json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8")
        os.utime(lock_dir, None)
        heartbeat_thread = threading.Thread(
            target=heartbeat, name=f"public-report-lock-{owner_token[:8]}", daemon=True
        )
        heartbeat_thread.start()
        yield lock_dir
    finally:
        heartbeat_stop.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=1.0)
        try:
            current = json.loads(owner_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            current = {}
        if current.get("owner_token") == owner_token and lock_dir.exists():
            shutil.rmtree(lock_dir)


def publish_bundle_atomic(
    output_dir: Path, documents: Mapping[str, Mapping[str, Any]], *, replace: bool,
    stale_lock_seconds: float = DEFAULT_STALE_LOCK_SECONDS,
    lock_wait_seconds: float = DEFAULT_LOCK_WAIT_SECONDS,
    lock_hold_hook: Callable[[], None] | None = None,
) -> None:
    output_dir = output_dir.resolve()
    if output_dir.parent == output_dir or not output_dir.name:
        raise PublicContractError("refusing to publish into a filesystem root")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_publish_lock(
        output_dir, stale_after_seconds=stale_lock_seconds,
        wait_timeout_seconds=lock_wait_seconds,
    ) as lock_dir:
        _recover_interrupted_publish(output_dir, set(documents))
        if lock_hold_hook is not None:
            lock_hold_hook()
            os.utime(lock_dir, None)
        if output_dir.exists() and not replace:
            raise FileExistsError(f"output already exists; use --replace: {output_dir}")
        if output_dir.exists():
            existing = {path.name for path in output_dir.iterdir()}
            if existing != set(documents):
                raise PublicContractError(
                    "refusing to replace a directory that is not one complete public-report-v1 bundle"
                )
        temporary: Path | None = Path(
            tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp-", dir=output_dir.parent)
        )
        backup: Path | None = None
        try:
            for name, document in documents.items():
                (temporary / name).write_text(
                    json.dumps(document, indent=2) + "\n", encoding="utf-8"
                )
            os.utime(lock_dir, None)
            if output_dir.exists():
                backup = output_dir.with_name(
                    f".{output_dir.name}.old-{uuid.uuid4().hex}"
                )
                output_dir.rename(backup)
            temporary.rename(output_dir)
            temporary = None
            if backup is not None:
                shutil.rmtree(backup)
                backup = None
        except Exception:
            if backup is not None and backup.exists() and not output_dir.exists():
                backup.rename(output_dir)
                backup = None
            raise
        finally:
            if temporary is not None and temporary.exists():
                shutil.rmtree(temporary)
            if backup is not None and backup.exists() and output_dir.exists():
                shutil.rmtree(backup)


def build_bundle_documents(
    analytics: Mapping[str, Any], readiness: Mapping[str, Any] | None,
    private_scoring: Mapping[str, Any] | None,
    private_timeline: Mapping[str, Any], momentum_source: Mapping[str, Any],
    *, schema_dir: Path | None = None,
) -> dict[str, dict[str, Any]]:
    report = build_public_report(analytics, readiness, private_scoring)
    timeline = build_public_timeline(private_timeline)
    _schema_version(momentum_source, 1, "private momentum episodes")
    episode_match = str(momentum_source.get("match_id") or "")
    episode_halves = _finite_number(
        momentum_source.get("halves_played"), integer=True, minimum=1,
        maximum=MAX_HALVES, label="private momentum halves_played",
    )
    if episode_halves is None:
        raise PublicContractError("private momentum halves_played is required")
    episodes = sanitize_momentum_episodes(
        momentum_source.get("episodes", []), match_id=episode_match,
        halves_played=int(episode_halves),
    )
    validate_bundle_consistency(report, timeline, episodes)
    documents = {
        "public-report.json": report,
        "public-timeline.json": timeline,
        "momentum-episodes.json": episodes,
    }
    for document in documents.values():
        assert_public(document)
    validate_json_schemas(documents, schema_dir or _schema_directory())
    return documents


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analytics", type=Path, required=True)
    parser.add_argument("--readiness", type=Path)
    parser.add_argument("--private-scoring", type=Path)
    parser.add_argument("--private-timeline", type=Path, required=True)
    parser.add_argument("--momentum-episodes", type=Path, required=True)
    parser.add_argument("--schema-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument(
        "--stale-lock-seconds", type=float, default=DEFAULT_STALE_LOCK_SECONDS,
        help="reclaim a publish lock only after this many seconds (minimum 300)",
    )
    parser.add_argument(
        "--lock-wait-seconds", type=float, default=DEFAULT_LOCK_WAIT_SECONDS,
        help="bounded wait for a concurrent publisher (0-3600 seconds)",
    )
    args = parser.parse_args()
    analytics = _read(args.analytics)
    timeline = _read(args.private_timeline)
    momentum = _read(args.momentum_episodes)
    assert analytics is not None and timeline is not None and momentum is not None
    documents = build_bundle_documents(
        analytics, _read(args.readiness), _read(args.private_scoring),
        timeline, momentum, schema_dir=args.schema_dir,
    )
    publish_bundle_atomic(
        args.output_dir, documents, replace=args.replace,
        stale_lock_seconds=args.stale_lock_seconds,
        lock_wait_seconds=args.lock_wait_seconds,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
