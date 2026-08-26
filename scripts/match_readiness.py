#!/usr/bin/env python3
"""Validate one match in a local SQL fixture and write an aggregate-only gate.

This command does not start MySQL, contact a shared service, or publish data.
It parses a ``.sql`` or ``.sql.gz`` fixture directly, applies deterministic
source-quality checks, and writes JSON plus Markdown suitable for CI artifacts.

Exit codes: 0 = PASS/WARN, 1 = FAIL, 2 = invalid invocation/source.
Use ``--strict`` when WARN should also return 1.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.match_analytics import (  # noqa: E402
    evaluate_capture_authorization,
)

SCHEMA_VERSION = 1
MATCH_ID_RE = re.compile(r"(?:\d+-KTP\d+|[A-Za-z0-9._-]+-TEST)$")
INSERT_RE = re.compile(r"^INSERT INTO `([^`]+)` \((.*?)\) VALUES \((.*)\);$")
TEAM_NAMES = {1: "Allies", 2: "Axis"}
REQUIRED_EVENT_TABLES = (
    "hlstats_Events_Frags",
    "ktp_damage_events",
    "ktp_position_samples",
)
WANTED_TABLES = {
    "hlstats_Actions",
    "hlstats_Events_Frags",
    "hlstats_Events_PlayerActions",
    "hlstats_Events_PlayerPlayerActions",
    "hlstats_Events_Statsme",
    "hlstats_Events_Statsme2",
    "ktp_damage_events",
    "ktp_flag_captures",
    "ktp_flag_state_events",
    "ktp_capture_health",
    "ktp_capture_manifests",
    "ktp_grenade_entity_events",
    "ktp_match_players",
    "ktp_matches",
    "ktp_objective_attempt_events",
    "ktp_position_samples",
}
FORBIDDEN_PUBLIC_KEYS = {
    "player_name", "steam_id", "player_id", "killer_id", "victim_id",
    "attacker_id", "assister_id", "pos_x", "pos_y", "pos_z",
    "pos_victim_x", "pos_victim_y", "pos_victim_z",
}
FORBIDDEN_PUBLIC_KEY_TOKENS = {
    re.sub(r"[^a-z0-9]", "", key.lower()) for key in FORBIDDEN_PUBLIC_KEYS
}


def _open_text(path: Path):
    return gzip.open(path, "rt", encoding="utf-8", errors="replace") \
        if path.suffix == ".gz" else path.open("r", encoding="utf-8", errors="replace")


def parse_value(value: str) -> str | None:
    value = value.strip()
    return None if value.upper() == "NULL" else value


def iter_rows(path: Path, wanted: set[str] | None = None) -> Iterator[tuple[str, dict[str, str | None]]]:
    """Yield single-row INSERT records from a Lane B mysqldump fixture."""
    with _open_text(path) as handle:
        for line_number, line in enumerate(handle, start=1):
            match = INSERT_RE.match(line.rstrip("\r\n"))
            if not match:
                continue
            table, columns_text, tuple_text = match.groups()
            if wanted is not None and table not in wanted:
                continue
            columns = [column.strip().strip("`") for column in columns_text.split(",")]
            values = next(csv.reader(
                [tuple_text], delimiter=",", quotechar="'", escapechar="\\"
            ))
            if len(columns) != len(values):
                raise ValueError(
                    f"{path.name}:{line_number}: {table} has {len(columns)} columns "
                    f"but {len(values)} values"
                )
            yield table, {
                column: parse_value(value) for column, value in zip(columns, values)
            }


def load_tables(path: Path) -> dict[str, list[dict[str, str | None]]]:
    tables: dict[str, list[dict[str, str | None]]] = defaultdict(list)
    for table, row in iter_rows(path, WANTED_TABLES):
        tables[table].append(row)
    return dict(tables)


def discover_match_ids(tables: dict[str, list[dict[str, Any]]]) -> list[str]:
    return sorted({
        str(row["match_id"])
        for rows in tables.values()
        for row in rows
        if row.get("match_id")
    })


def integer(value: Any, default: int = 0) -> int:
    return default if value in (None, "") else int(value)


def floating(value: Any, default: float = 0.0) -> float:
    return default if value in (None, "") else float(value)


def timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")


def rows_for(tables: dict[str, list[dict[str, Any]]], table: str, match_id: str) -> list[dict[str, Any]]:
    return [row for row in tables.get(table, []) if row.get("match_id") == match_id]


def finding(level: str, code: str, message: str, **evidence: Any) -> dict[str, Any]:
    return {"level": level, "code": code, "message": message, "evidence": evidence}


def duplicate_count(rows: Iterable[dict[str, Any]], ignored=("id", "created_at")) -> int:
    seen: set[tuple] = set()
    duplicates = 0
    for row in rows:
        signature = tuple(sorted((key, value) for key, value in row.items() if key not in ignored))
        if signature in seen:
            duplicates += 1
        else:
            seen.add(signature)
    return duplicates


def coordinate_coverage(frags: list[dict[str, Any]]) -> tuple[int, float]:
    coordinate_rows = sum(
        all(row.get(key) is not None for key in (
            "pos_x", "pos_y", "pos_victim_x", "pos_victim_y"
        ))
        for row in frags
    )
    return coordinate_rows, (100.0 * coordinate_rows / len(frags) if frags else 0.0)


def position_interval_summary(
    rows: list[dict[str, Any]], roster_players: int = 0,
) -> dict[str, Any]:
    by_player: dict[int, list[datetime]] = defaultdict(list)
    by_tick: dict[tuple[int, datetime], int] = defaultdict(int)
    by_half_ticks: dict[int, set[datetime]] = defaultdict(set)
    for row in rows:
        when = timestamp(row.get("event_time"))
        if when is not None:
            by_player[integer(row.get("player_id"))].append(when)
            half = integer(row.get("half"))
            by_tick[(half, when)] += 1
            by_half_ticks[half].add(when)
    gaps: list[float] = []
    for times in by_player.values():
        times.sort()
        gaps.extend((right - left).total_seconds() for left, right in zip(times, times[1:]) if right > left)
    populations = sorted(by_tick.values())
    active_seconds = sum(
        max((max(ticks) - min(ticks)).total_seconds(), 0.0)
        for ticks in by_half_ticks.values() if ticks
    )
    rows_per_minute = (
        len(rows) * 60.0 / active_seconds if active_seconds > 0 else None
    )
    population_coverage = (
        100.0 * sum(populations) / (len(populations) * roster_players)
        if populations and roster_players > 0 else None
    )
    evidence = {
        "players_with_timing": len(by_player),
        "sample_ticks": len(populations),
        "players_per_tick_min": min(populations) if populations else None,
        "players_per_tick_median": (
            round(statistics.median(populations), 2) if populations else None
        ),
        "players_per_tick_max": max(populations) if populations else None,
        "population_coverage_percent": (
            round(population_coverage, 2) if population_coverage is not None else None
        ),
        "rows_per_minute": round(rows_per_minute, 2) if rows_per_minute else None,
        "projected_60m_rows": round(rows_per_minute * 60) if rows_per_minute else None,
        # This is deliberately a transparent cardinality proxy, not a measured
        # table-size promise or a promotion threshold. Live calibration owns it.
        "storage_proxy_bytes_per_row": 128,
        "projected_60m_storage_bytes_proxy": (
            round(rows_per_minute * 60 * 128) if rows_per_minute else None
        ),
    }
    if not gaps:
        return {**evidence, "gap_count": 0, "median_seconds": None,
                "p95_seconds": None, "p95_jitter_seconds": None,
                "in_band_percent": None}
    gaps.sort()
    p95_index = min(len(gaps) - 1, math.ceil(0.95 * len(gaps)) - 1)
    jitter = sorted(abs(gap - 2.0) for gap in gaps)
    in_band = sum(1.0 <= gap <= 3.5 for gap in gaps)
    return {
        **evidence,
        "gap_count": len(gaps),
        "median_seconds": round(statistics.median(gaps), 3),
        "p95_seconds": round(gaps[p95_index], 3),
        "p95_jitter_seconds": round(jitter[p95_index], 3),
        "in_band_percent": round(100.0 * in_band / len(gaps), 2),
    }


def damage_alignment(damage: list[dict[str, Any]], positions: list[dict[str, Any]], max_seconds=3.0) -> tuple[int, int]:
    by_player: dict[int, list[datetime]] = defaultdict(list)
    for row in positions:
        when = timestamp(row.get("event_time"))
        if when is not None:
            by_player[integer(row.get("player_id"))].append(when)
    for times in by_player.values():
        times.sort()
    aligned = 0
    for row in damage:
        when = timestamp(row.get("event_time"))
        if when is None:
            continue
        candidates = by_player.get(integer(row.get("attacker_id")), [])
        if candidates and min(abs((sample - when).total_seconds()) for sample in candidates) <= max_seconds:
            aligned += 1
    return aligned, len(damage)


def public_payload_is_safe(value: Any, path="report") -> list[str]:
    violations: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized_key in FORBIDDEN_PUBLIC_KEY_TOKENS:
                violations.append(f"{path}.{key}")
            violations.extend(public_payload_is_safe(nested, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            violations.extend(public_payload_is_safe(nested, f"{path}[{index}]"))
    return violations


OBJECTIVE_STOP_REASONS = {"capture_stopped", "context_reset"}
GRENADE_WEAPON_TYPES = {13: "handgrenade", 14: "stickgrenade", 36: "mills_bomb"}


def objective_rows_valid(
    rows: list[dict[str, Any]], observed_halves: set[int],
) -> tuple[bool, list[str]]:
    """Validate factual objective rows, including keyed sequence ordering."""
    errors: list[str] = []
    keyed: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        kind = str(row.get("event_kind") or "")
        reason = row.get("stop_reason")
        half = integer(row.get("half"))
        attempt = integer(row.get("attempt_id"))
        sequence = integer(row.get("producer_sequence"))
        capturing_team = integer(row.get("capturing_team"), -1)
        owner_before = integer(row.get("owner_before"), -1)
        allies = integer(row.get("allies_in_zone"), -1)
        axis = integer(row.get("axis_in_zone"), -1)
        if half not in observed_halves:
            errors.append("objective row half is outside the observed match half set")
        if kind not in {"start", "complete", "stop"}:
            errors.append("objective event kind is invalid")
        if attempt <= 0 or sequence <= 0:
            errors.append("objective attempt/producer sequence is not positive")
        if not str(row.get("flag_name") or "").strip():
            errors.append("objective flag name is empty")
        if not str(row.get("map_name") or "").strip():
            errors.append("objective map name is empty")
        if capturing_team not in {1, 2} or owner_before not in {0, 1, 2}:
            errors.append("objective team/owner value is invalid")
        if allies < 0 or axis < 0:
            errors.append("objective occupancy count is negative")
        if kind == "start":
            active = allies if capturing_team == 1 else axis
            if active <= 0:
                errors.append("objective start has no capture-team occupancy")
            if attempt != sequence:
                errors.append("objective start attempt_id differs from producer_sequence")
        elif kind in {"complete", "stop"} and attempt >= sequence:
            errors.append("objective terminal attempt_id is not earlier than producer_sequence")
        if (kind == "stop") != (str(reason or "") in OBJECTIVE_STOP_REASONS):
            errors.append("objective stop reason is invalid for event kind")
        keyed[(integer(row.get("server_id")), half, attempt)].append(row)
    for attempt_rows in keyed.values():
        starts = [row for row in attempt_rows if row.get("event_kind") == "start"]
        terminals = [
            row for row in attempt_rows
            if row.get("event_kind") in {"complete", "stop"}
        ]
        if len(starts) > 1 or len(terminals) > 1:
            errors.append("objective attempt has duplicate start or terminal rows")
        if starts and terminals and integer(terminals[0].get("producer_sequence")) <= integer(
            starts[0].get("producer_sequence")
        ):
            errors.append("objective terminal sequence is not later than start")
    return not errors, errors


def grenade_rows_valid(
    rows: list[dict[str, Any]], observed_halves: set[int],
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    for row in rows:
        weapon_id = integer(row.get("weapon_id"))
        if integer(row.get("half")) not in observed_halves:
            errors.append("grenade row half is outside the observed match half set")
        if row.get("entity_kind") not in {"tracked", "removed"}:
            errors.append("grenade entity kind is invalid")
        if GRENADE_WEAPON_TYPES.get(weapon_id) != row.get("weapon_type"):
            errors.append("grenade weapon ID/type mapping is invalid")
    return not errors, errors


def validate_fixture(path: Path, match_id: str | None = None) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    tables = load_tables(path)
    match_ids = discover_match_ids(tables)
    if match_id is None:
        if len(match_ids) != 1:
            raise ValueError(f"fixture contains {len(match_ids)} match IDs; pass --match-id")
        match_id = match_ids[0]
    if match_id not in match_ids:
        raise ValueError(f"match ID {match_id!r} is absent; available: {', '.join(match_ids)}")

    matches = rows_for(tables, "ktp_matches", match_id)
    roster = rows_for(tables, "ktp_match_players", match_id)
    frags = rows_for(tables, "hlstats_Events_Frags", match_id)
    damage = rows_for(tables, "ktp_damage_events", match_id)
    positions = rows_for(tables, "ktp_position_samples", match_id)
    captures = rows_for(tables, "ktp_flag_captures", match_id)
    ownership = rows_for(tables, "ktp_flag_state_events", match_id)
    player_actions = rows_for(tables, "hlstats_Events_PlayerActions", match_id)
    player_player_actions = rows_for(tables, "hlstats_Events_PlayerPlayerActions", match_id)
    statsme = rows_for(tables, "hlstats_Events_Statsme", match_id)
    statsme2 = rows_for(tables, "hlstats_Events_Statsme2", match_id)
    objective_attempts = rows_for(tables, "ktp_objective_attempt_events", match_id)
    grenade_entities = rows_for(tables, "ktp_grenade_entity_events", match_id)
    manifests = rows_for(tables, "ktp_capture_manifests", match_id)
    health = rows_for(tables, "ktp_capture_health", match_id)
    observed_halves = {
        integer(row.get("half")) for row in matches if integer(row.get("half")) > 0
    }
    action_codes = {integer(row.get("id")): row.get("code") for row in tables.get("hlstats_Actions", [])}
    assists = [row for row in player_player_actions if action_codes.get(integer(row.get("actionId"))) == "assist"]
    cap_breaks = [row for row in player_actions if action_codes.get(integer(row.get("actionId"))) == "cap_break"]

    coordinate_rows, coordinate_percent = coordinate_coverage(frags)
    unique_captures = len({
        (row.get("half"), row.get("flag_name"), row.get("event_time")) for row in captures
    })
    position_timing = position_interval_summary(
        positions, len({integer(row.get("player_id")) for row in roster})
    )
    damage_aligned, damage_total = damage_alignment(damage, positions)
    damage_alignment_percent = 100.0 * damage_aligned / damage_total if damage_total else 0.0
    team_counts = Counter(integer(row.get("team")) for row in roster)
    bot_count = sum(str(row.get("steam_id") or "").startswith("BOT:") for row in roster)
    event_players = {
        integer(row.get(key))
        for row, keys in (
            *((row, ("killerId", "victimId")) for row in frags),
            *((row, ("attacker_id", "victim_id")) for row in damage),
            *((row, ("player_id",)) for row in positions),
        )
        for key in keys
        if row.get(key) not in (None, "", "0", 0)
    }
    roster_players = {integer(row.get("player_id")) for row in roster}
    orphan_players = event_players - roster_players if roster else set()
    invalid_half_rows = sum(integer(row.get("half")) <= 0 for row in frags + damage + positions + captures)
    attempts: dict[tuple[int, int], set[str]] = defaultdict(set)
    for row in objective_attempts:
        attempts[(integer(row.get("half")), integer(row.get("attempt_id")))].add(
            str(row.get("event_kind") or "")
        )
    grenade_lifecycles: dict[tuple[int, int, int], set[str]] = defaultdict(set)
    for row in grenade_entities:
        grenade_lifecycles[(
            integer(row.get("half")), integer(row.get("entindex")),
            integer(row.get("serial")),
        )].add(str(row.get("entity_kind") or ""))

    inventory = {
        "match_rows": len(matches),
        "roster_players": len(roster_players),
        "team_counts": {TEAM_NAMES.get(team, str(team)): count for team, count in sorted(team_counts.items())},
        "event_players": len(event_players),
        "frags": len(frags),
        "coordinate_frags": coordinate_rows,
        "coordinate_coverage_percent": round(coordinate_percent, 2),
        "damage_events": len(damage),
        "damage_sample_aligned": damage_aligned,
        "damage_alignment_percent": round(damage_alignment_percent, 2),
        "position_samples": len(positions),
        "position_timing": position_timing,
        "capture_credits": len(captures),
        "unique_capture_events": unique_captures,
        "flag_state_events": len(ownership),
        "assists": len(assists),
        "cap_breaks": len(cap_breaks),
        "statsme_rows": len(statsme),
        "statsme2_rows": len(statsme2),
        "objective_attempts": len(attempts),
        "objective_starts": sum("start" in kinds for kinds in attempts.values()),
        "objective_completes": sum("complete" in kinds for kinds in attempts.values()),
        "objective_stops": sum("stop" in kinds for kinds in attempts.values()),
        "objective_orphan_terminals": sum(
            "start" not in kinds and bool(kinds & {"complete", "stop"})
            for kinds in attempts.values()
        ),
        "grenade_entities": len(grenade_lifecycles),
        "grenade_tracked": sum("tracked" in kinds for kinds in grenade_lifecycles.values()),
        "grenade_removed": sum("removed" in kinds for kinds in grenade_lifecycles.values()),
        "grenade_incomplete": sum(kinds == {"tracked"} for kinds in grenade_lifecycles.values()),
        "capture_manifests": len(manifests),
        "capture_health_rows": len(health),
    }
    checks: list[dict[str, Any]] = []
    checks.append(finding(
        "PASS" if MATCH_ID_RE.fullmatch(match_id) else "FAIL", "match_id_shape",
        "Match identifier has an accepted production or test shape." if MATCH_ID_RE.fullmatch(match_id)
        else "Match identifier is malformed.",
    ))
    checks.append(finding(
        "PASS" if len(matches) == 1 else "FAIL", "single_match_record",
        "Exactly one ktp_matches row exists." if len(matches) == 1
        else "Expected exactly one ktp_matches row.", rows=len(matches),
    ))
    closed = len(matches) == 1 and bool(matches[0].get("end_time"))
    checks.append(finding(
        "PASS" if closed else "FAIL", "closed_match",
        "The match has an end boundary." if closed else "The match is missing its end boundary.",
    ))

    if roster:
        expected_test = match_id.endswith("-TEST")
        roster_ok = len(roster_players) == len(roster) and (not expected_test or team_counts == Counter({1: 6, 2: 6}))
        checks.append(finding(
            "PASS" if roster_ok else "FAIL", "roster_integrity",
            "Roster identifiers are unique and the test roster is 6v6." if roster_ok
            else "Roster identifiers are duplicated or the test roster is not 6v6.",
            players=len(roster_players), teams=inventory["team_counts"],
        ))
        checks.append(finding(
            "PASS" if not orphan_players else "FAIL", "event_roster_consistency",
            "All event participants belong to the match roster." if not orphan_players
            else "Some event participants are absent from the match roster.",
            orphan_player_count=len(orphan_players),
        ))
    else:
        checks.append(finding(
            "WARN", "roster_source_missing",
            "This fixture predates ktp_match_players; event-player cardinality is retained as coverage.",
            event_players=len(event_players),
        ))

    bot_safe = match_id.endswith("-TEST") or bot_count == 0
    checks.append(finding(
        "PASS" if bot_safe else "FAIL", "bot_containment",
        "Bot identities are confined to test data." if bot_safe
        else "A bot identity appears in a non-test match.", bot_players=bot_count,
    ))
    checks.append(finding(
        "PASS" if invalid_half_rows == 0 else "FAIL", "valid_half_tags",
        "All match events use positive half tags." if invalid_half_rows == 0
        else "Some match events have half <= 0.", invalid_rows=invalid_half_rows,
    ))

    for table, rows in (("frags", frags), ("damage", damage), ("positions", positions)):
        checks.append(finding(
            "PASS" if rows else "FAIL", f"{table}_present",
            f"{table.capitalize()} rows are present." if rows else f"No {table} rows were captured.",
            rows=len(rows),
        ))

    coordinate_level = "PASS" if coordinate_percent >= 90.0 else "WARN" if coordinate_percent >= 75.0 else "FAIL"
    checks.append(finding(
        coordinate_level, "frag_coordinate_coverage",
        "At least 90% of frags contain both spatial endpoints." if coordinate_level == "PASS"
        else "Frag coordinate coverage is incomplete; spatial products will exclude rows.",
        coordinate_rows=coordinate_rows, total_rows=len(frags), percent=round(coordinate_percent, 2),
    ))
    alignment_level = "PASS" if damage_alignment_percent >= 90.0 else "WARN" if damage_alignment_percent >= 75.0 else "FAIL"
    checks.append(finding(
        alignment_level, "damage_position_alignment",
        "At least 90% of damage can be aligned to a <=3-second attacker sample." if alignment_level == "PASS"
        else "Sample-aligned damage coverage is incomplete.",
        aligned=damage_aligned, total=damage_total, percent=round(damage_alignment_percent, 2),
    ))
    median_gap = position_timing["median_seconds"]
    timing_in_band = median_gap is not None and 1.0 <= median_gap <= 3.5
    cadence_manifest_halves = [integer(row.get("half")) for row in manifests]
    cadence_authorized = (
        bool(observed_halves)
        and set(cadence_manifest_halves) == observed_halves
        and len(cadence_manifest_halves) == len(observed_halves)
        and all(
            integer(row.get("schema_version")) == 22
            and abs(floating(row.get("position_interval")) - 2.0) <= 0.01
            for row in manifests
        )
    )
    timing_ok = timing_in_band and cadence_authorized
    checks.append(finding(
        "PASS" if timing_ok else "WARN", "position_sampling_interval",
        "Median sampling interval is in band and every observed half has an exact schema22/2.00 manifest."
        if timing_ok else
        "Observed cadence is in band but lacks exact schema22/2.00 manifest authorization."
        if timing_in_band else
        "Sampling cadence is unavailable or outside the expected 1-3.5 second band.",
        timing_in_band=timing_in_band,
        schema22_cadence_authorized=cadence_authorized,
        observed_halves=sorted(observed_halves),
        manifest_halves=sorted(cadence_manifest_halves),
        **position_timing,
    ))

    telemetry_present = bool(objective_attempts or grenade_entities or manifests or health)
    capture_authorization = evaluate_capture_authorization(
        observed_halves, manifests, health
    )
    objective_shape_ok, objective_errors = objective_rows_valid(
        objective_attempts, observed_halves
    )
    objective_expected = integer(
        capture_authorization.get("streams", {}).get("objective_attempt", {}).get("accepted")
    )
    objective_reconciled = len(objective_attempts) == objective_expected
    objective_ok = (
        capture_authorization["authorized"]
        and objective_reconciled and objective_shape_ok
    )
    checks.append(finding(
        "PASS" if objective_ok else "FAIL" if telemetry_present else "WARN",
        "objective_attempt_lifecycle",
        "Authorized objective facts reconcile, including a valid zero-row stream."
        if objective_ok else "Objective attempt telemetry was not captured in this archive."
        if not telemetry_present else "Objective attempt rows or health reconciliation are invalid.",
        attempts=len(attempts), starts=inventory["objective_starts"],
        completes=inventory["objective_completes"], stops=inventory["objective_stops"],
        orphan_terminals=inventory["objective_orphan_terminals"],
        rows=len(objective_attempts), health_accepted=objective_expected,
        validation_errors=objective_errors,
    ))
    grenade_shape_ok, grenade_errors = grenade_rows_valid(
        grenade_entities, observed_halves
    )
    grenade_expected = integer(
        capture_authorization.get("streams", {}).get("grenade_entity", {}).get("accepted")
    )
    grenade_reconciled = len(grenade_entities) == grenade_expected
    grenade_ok = (
        capture_authorization["authorized"]
        and grenade_reconciled and grenade_shape_ok
    )
    checks.append(finding(
        "PASS" if grenade_ok else "FAIL" if telemetry_present else "WARN",
        "grenade_entity_lifecycle",
        "Authorized grenade entity facts reconcile, including a valid zero-row stream."
        if grenade_ok else "Grenade entity telemetry was not captured in this archive."
        if not telemetry_present else "Grenade entity rows or health reconciliation are invalid.",
        entities=len(grenade_lifecycles), tracked=inventory["grenade_tracked"],
        removed=inventory["grenade_removed"], incomplete=inventory["grenade_incomplete"],
        rows=len(grenade_entities), health_accepted=grenade_expected,
        validation_errors=grenade_errors,
    ))
    checks.append(finding(
        "PASS" if capture_authorization["authorized"] else
        "FAIL" if telemetry_present else "WARN",
        "schema22_capture_authorization",
        "Schema 22, the 2-second cadence, all ten health types, and zero drops reconcile."
        if capture_authorization["authorized"] else
        "Schema-22 capture authorization is unavailable in this archive."
        if not telemetry_present else "Schema-22 manifest, half set, or health counters do not reconcile.",
        manifests=len(manifests), health_rows=len(health),
        observed_halves=capture_authorization["observed_halves"],
        manifest_halves=capture_authorization["manifest_halves"],
        health_halves=capture_authorization["health_halves"],
        authorization_status=capture_authorization["status"],
        authorization_errors=capture_authorization["errors"],
    ))

    duplicate_specs = (
        # Damage timestamps have one-second precision, so two identical hits in
        # the same second are suspicious but not proof of duplicate ingestion.
        ("frags", frags, "FAIL"), ("damage", damage, "WARN"),
        ("captures", captures, "FAIL"), ("positions", positions, "WARN"),
    )
    for label, rows, duplicate_level in duplicate_specs:
        duplicates = duplicate_count(rows)
        checks.append(finding(
            "PASS" if duplicates == 0 else duplicate_level, f"duplicate_{label}",
            f"No exact duplicate {label} rows were found." if duplicates == 0
            else f"Exact duplicate {label} rows were found.", duplicates=duplicates,
        ))

    checks.append(finding(
        "PASS" if assists else "WARN", "assist_coverage",
        "Assist rows are present." if assists else "No assist rows are present; distinguish zero from unavailable.",
        rows=len(assists),
    ))
    checks.append(finding(
        "PASS" if statsme else "WARN", "statsme_coverage",
        "Weapon totals are present." if statsme else "StatsMe weapon totals are unavailable.", rows=len(statsme),
    ))
    checks.append(finding(
        "PASS" if statsme2 else "WARN", "statsme2_coverage",
        "Hit-location totals are present." if statsme2 else "StatsMe2 hit-location totals are unavailable.", rows=len(statsme2),
    ))
    checks.append(finding(
        "PASS" if len(captures) >= unique_captures else "FAIL", "capture_grouping",
        "Capture credits group into plausible unique capture events." if len(captures) >= unique_captures
        else "Unique capture events exceed capture-credit rows.",
        credits=len(captures), unique_events=unique_captures,
    ))
    checks.append(finding(
        "PASS" if ownership else "WARN", "flag_ownership_coverage",
        "Flag ownership events are present." if ownership
        else "Flag ownership events are unavailable; capout reconstruction may be incomplete.", rows=len(ownership),
    ))

    severity = {"PASS": 0, "WARN": 1, "FAIL": 2}
    status = max((item["level"] for item in checks), key=severity.get, default="FAIL")
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "fixture": path.name,
        "match_id": match_id,
        "status": status,
        "privacy": "aggregate_only",
        "inventory": inventory,
        "checks": checks,
    }
    violations = public_payload_is_safe(report)
    if violations:
        raise AssertionError(f"public readiness payload contains private fields: {violations}")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    inventory = report["inventory"]
    out = [
        "# Match readiness report", "",
        f"- Result: **{report['status']}**",
        f"- Match: `{report['match_id']}`",
        f"- Fixture: `{report['fixture']}`",
        "- Privacy: aggregate-only; no player identities, individual coordinates, or routes", "",
        "## Source inventory", "",
        "| Source | Rows/coverage |", "|---|---:|",
        f"| Roster | {inventory['roster_players']} |",
        f"| Event participants | {inventory['event_players']} |",
        f"| Frags | {inventory['frags']} |",
        f"| Frags with both endpoints | {inventory['coordinate_frags']} ({inventory['coordinate_coverage_percent']}%) |",
        f"| Damage events | {inventory['damage_events']} |",
        f"| Damage aligned to <=3s sample | {inventory['damage_sample_aligned']} ({inventory['damage_alignment_percent']}%) |",
        f"| Position samples | {inventory['position_samples']} |",
        f"| Assists | {inventory['assists']} |",
        f"| Cap breaks | {inventory['cap_breaks']} |",
        f"| Capture credits / unique events | {inventory['capture_credits']} / {inventory['unique_capture_events']} |",
        f"| Flag ownership events | {inventory['flag_state_events']} |",
        f"| StatsMe / StatsMe2 | {inventory['statsme_rows']} / {inventory['statsme2_rows']} |", "",
        f"| Objective attempts (start / complete / stop / orphan) | {inventory['objective_attempts']} "
        f"({inventory['objective_starts']} / {inventory['objective_completes']} / "
        f"{inventory['objective_stops']} / {inventory['objective_orphan_terminals']}) |",
        f"| Grenade entities (tracked / removed / incomplete) | {inventory['grenade_entities']} "
        f"({inventory['grenade_tracked']} / {inventory['grenade_removed']} / "
        f"{inventory['grenade_incomplete']}) |",
        f"| Schema-22 manifest / health rows | {inventory['capture_manifests']} / "
        f"{inventory['capture_health_rows']} |", "",
        "## Checks", "",
        "| Result | Code | Explanation | Evidence |", "|---|---|---|---|",
    ]
    for item in report["checks"]:
        evidence = ", ".join(f"{key}={value}" for key, value in item["evidence"].items()) or "-"
        out.append(f"| {item['level']} | `{item['code']}` | {item['message']} | {evidence} |")
    out += ["", "A `FAIL` blocks promotion. A `WARN` records a known coverage limitation and is non-blocking unless `--strict` is used.", ""]
    return "\n".join(out)


def write_report(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "match-readiness.json"
    markdown_path = output_dir / "MATCH_READINESS.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="local .sql or .sql.gz fixture")
    parser.add_argument("--match-id", help="required when the fixture contains multiple matches")
    parser.add_argument("--output-dir", type=Path, default=Path("build/match-readiness"))
    parser.add_argument("--strict", action="store_true", help="treat WARN as a failing exit status")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = validate_fixture(args.fixture, args.match_id)
        json_path, markdown_path = write_report(report, args.output_dir)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"match-readiness: {exc}", file=sys.stderr)
        return 2
    print(f"Match readiness: {report['status']}")
    print(f"  Markdown: {markdown_path}")
    print(f"  JSON: {json_path}")
    return int(report["status"] == "FAIL" or (args.strict and report["status"] == "WARN"))


if __name__ == "__main__":
    raise SystemExit(main())
