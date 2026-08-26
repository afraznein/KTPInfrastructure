#!/usr/bin/env python3
"""Collect a reproducible, read-only evidence bundle for one canary match.

The input is a local SQL dump (optionally gzip-compressed), never a live DB.
Optional game/daemon logs make unresolved-action and SQL-error checks decisive;
without them those checks are explicitly reported as unavailable.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import match_analytics as analytics  # noqa: E402
from scripts.match_timelines import TimelineConfig  # noqa: E402
from tests.e2e_stats.ephemeral_mysql import EphemeralMysql  # noqa: E402


REPO = Path(__file__).resolve().parents[1]
MATCH_TYPES = {
    0: "official", 1: "scrim", 2: "12man", 3: "draft",
    4: "official_ot", 5: "draft_ot",
}
FRAG_CONTEXT_SLO_PCT = 99.5
POSITION_INTERVAL_SECONDS = 2.0
POSITION_INTERVAL_TOLERANCE_SECONDS = 0.75
ERROR_PATTERNS = {
    "unresolved_actions": re.compile(
        r"Unresolved action\s+['\"]|unknown action|action.{0,30}not found", re.I
    ),
    "sql_errors": re.compile(
        r"SQL_ERROR|DBD::mysql|SQL syntax|execute failed|prepare failed|mysql.{0,20}error", re.I
    ),
}
HEALTH_PATTERN = re.compile(
    r"KTP_HEALTH.*sql_failed=(\d+)\s+sql_retried=(\d+)\s+unresolved_actions=(\d+)",
    re.I,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_log(path: Path) -> str:
    opener = gzip.open if path.suffix == ".gz" else Path.open
    with opener(path, "rt", encoding="utf-8", errors="replace") as source:
        return source.read()


def inspect_logs(paths: list[Path]) -> dict[str, Any]:
    if not paths:
        return {
            "status": "not_provided", "files": [],
            "unresolved_actions": {"count": None, "samples": []},
            "sql_errors": {"count": None, "samples": []},
        }
    findings = {name: [] for name in ERROR_PATTERNS}
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"log not found: {path}")
        for number, line in enumerate(_read_log(path).splitlines(), 1):
            health = HEALTH_PATTERN.search(line)
            if health:
                sql_failed, sql_retried, unresolved = map(int, health.groups())
                sample = {"file": path.name, "line": number, "text": line[:500]}
                if sql_failed or sql_retried:
                    findings["sql_errors"].append(sample)
                if unresolved:
                    findings["unresolved_actions"].append(sample)
                # Do not double-count the same health line via generic patterns.
                continue
            for name, pattern in ERROR_PATTERNS.items():
                if pattern.search(line):
                    findings[name].append({
                        "file": path.name, "line": number, "text": line[:500],
                    })
    return {
        "status": "clean" if not any(findings.values()) else "errors_found",
        "files": [path.name for path in paths],
        **{name: {"count": len(rows), "samples": rows[:20]}
           for name, rows in findings.items()},
    }


def _column_exists(db: EphemeralMysql, table: str, column: str) -> bool:
    query = (
        "SELECT COUNT(*) AS present FROM information_schema.columns "
        f"WHERE table_schema=DATABASE() AND table_name={analytics.sql_literal(table)} "
        f"AND column_name={analytics.sql_literal(column)}"
    )
    rows = analytics.tsv_rows(db.sql(query))
    return bool(int(rows[0]["present"]))


def collect_classification(db: EphemeralMysql, match_id: str) -> list[dict[str, Any]]:
    if not _column_exists(db, "ktp_matches", "match_type"):
        return []
    literal = analytics.sql_literal(match_id)
    return analytics.tsv_rows(db.sql(f"""
SELECT half, match_type, start_time, end_time
FROM ktp_matches WHERE match_id={literal} ORDER BY half
"""))


def collect_ownership(db: EphemeralMysql, match_id: str, available: bool) -> list[dict[str, Any]]:
    if not available:
        return []
    literal = analytics.sql_literal(match_id)
    return analytics.tsv_rows(db.sql(f"""
SELECT id AS event_id, half, flag_index, flag_name, owner_team, is_initial,
       game_time, event_time
FROM ktp_flag_state_events
WHERE match_id={literal} ORDER BY half, flag_index, game_time, id
"""))


def _count_row(db: EphemeralMysql, query: str) -> dict[str, Any]:
    rows = analytics.tsv_rows(db.sql(query))
    return rows[0] if rows else {}


def collect_capture_activation(
    db: EphemeralMysql, match_id: str, sources: dict[str, bool],
) -> dict[str, Any]:
    """Measure whether optional capture schemas were actually populated.

    A table or column existing only proves that a migration ran.  Denver 4 had
    every new schema object but no producer clocks, life rows, or canonical
    assist rows, so schema capability and per-match activation stay separate.
    """
    literal = analytics.sql_literal(match_id)
    frags = _count_row(db, f"""
SELECT COUNT(*) AS rows_total,
       SUM(BINARY producer_match_id = BINARY {literal}
           AND producer_half > 0 AND game_time IS NOT NULL
           AND event_epoch IS NOT NULL) AS rows_producer_timed,
       SUM(frag_context_recorded = 1) AS rows_contextual,
       SUM(LEFT(map, 4) <> 'dod_') AS rows_invalid_map,
       SUM(is_last_flag_defense = 1) AS rows_last_flag_defense
FROM hlstats_Events_Frags
WHERE BINARY match_id = BINARY {literal}
   OR BINARY producer_match_id = BINARY {literal}
""") if sources.get("frag_event_clock") else {
        "rows_total": 0, "rows_producer_timed": None,
        "rows_contextual": None, "rows_invalid_map": None,
        "rows_last_flag_defense": None,
    }
    damage = _count_row(db, f"""
SELECT COUNT(*) AS rows_total,
       SUM(BINARY producer_match_id = BINARY {literal}
           AND producer_half > 0 AND game_time IS NOT NULL
           AND event_epoch IS NOT NULL) AS rows_producer_timed
FROM ktp_damage_events
WHERE BINARY match_id = BINARY {literal}
   OR BINARY producer_match_id = BINARY {literal}
""") if sources.get("damage_event_clock") else {
        "rows_total": 0, "rows_producer_timed": None,
    }
    life = _count_row(db, f"""
SELECT COUNT(*) AS rows_total,
       SUM(boundary_kind='start') AS starts,
       SUM(boundary_kind='end') AS ends
FROM ktp_life_events WHERE BINARY match_id = BINARY {literal}
""") if sources.get("life_boundaries") else {
        "rows_total": None, "starts": None, "ends": None,
    }
    assists = _count_row(db, f"""
SELECT COUNT(*) AS rows_total
FROM ktp_assist_events WHERE BINARY match_id = BINARY {literal}
""") if sources.get("assist_context") else {"rows_total": None}
    return {"frags": frags, "damage": damage, "life_events": life,
            "canonical_assists": assists}


def collect_position_cadence(
    db: EphemeralMysql, match_id: str, available: bool,
) -> list[dict[str, Any]]:
    if not available:
        return []
    literal = analytics.sql_literal(match_id)
    return analytics.tsv_rows(db.sql(f"""
SELECT half, ROUND(game_time, 1) AS sample_time, COUNT(*) AS player_samples
FROM ktp_position_samples
WHERE BINARY match_id=BINARY {literal}
GROUP BY half, ROUND(game_time, 1) ORDER BY half, sample_time
"""))


def position_cadence_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ticks_by_half: dict[int, list[float]] = {}
    samples_by_half: dict[int, int] = {}
    for row in rows:
        half = int(row["half"])
        ticks_by_half.setdefault(half, []).append(float(row["sample_time"]))
        samples_by_half[half] = samples_by_half.get(half, 0) + int(
            row.get("player_samples") or 0
        )
    halves = []
    for half, ticks in sorted(ticks_by_half.items()):
        deltas = [later - earlier for earlier, later in zip(ticks, ticks[1:])]
        interval = round(float(median(deltas)), 3) if deltas else None
        in_tolerance = bool(
            interval is not None
            and abs(interval - POSITION_INTERVAL_SECONDS)
            <= POSITION_INTERVAL_TOLERANCE_SECONDS
        )
        halves.append({
            "half": half, "rows_total": samples_by_half[half],
            "sample_ticks": len(ticks), "median_interval_seconds": interval,
            "in_tolerance": in_tolerance,
        })
    return {
        "available": bool(rows),
        "target_interval_seconds": POSITION_INTERVAL_SECONDS,
        "tolerance_seconds": POSITION_INTERVAL_TOLERANCE_SECONDS,
        "within_slo": bool(halves) and all(row["in_tolerance"] for row in halves),
        "halves": halves,
    }


def collect_flag_positions(
    db: EphemeralMysql, match_id: str, available: bool,
) -> list[dict[str, Any]]:
    if not available:
        return []
    literal = analytics.sql_literal(match_id)
    return analytics.tsv_rows(db.sql(f"""
SELECT DISTINCT fp.flag_index, fp.flag_name, fp.origin_x, fp.origin_y
FROM ktp_flag_positions fp
JOIN ktp_matches m
  ON m.server_id=fp.server_id AND m.map_name=fp.map_name
WHERE BINARY m.match_id = BINARY {literal}
ORDER BY fp.flag_index
"""))


CAPTURE_EVENT_TYPES = {
    "life", "damage", "position", "frag", "assist", "break",
    "flag_state", "flag_position", "objective_attempt", "grenade_entity",
}


def collect_capture_health(
    db: EphemeralMysql, match_id: str, available: bool,
) -> dict[str, list[dict[str, Any]]]:
    if not available:
        return {"manifests": [], "health": []}
    literal = analytics.sql_literal(match_id)
    manifests = analytics.tsv_rows(db.sql(f"""
SELECT half, map_name, producer, producer_version, schema_version,
       capabilities, position_interval, buffer_entries, life_buffer_entries,
       producer_sequence, event_epoch
FROM ktp_capture_manifests WHERE BINARY match_id=BINARY {literal}
ORDER BY half, producer
"""))
    health = analytics.tsv_rows(db.sql(f"""
SELECT half, event_type, attempted, enqueued, dropped, emitted,
       daemon_received, daemon_accepted, daemon_rejected,
       correlation_failure_count, sequence_first, sequence_last,
       daemon_sequence_first, daemon_sequence_last, sequence_gap_count,
       duplicate_or_reordered_count, producer_sequence, event_epoch
FROM ktp_capture_health WHERE BINARY match_id=BINARY {literal}
ORDER BY half, event_type
"""))
    return {"manifests": manifests, "health": health}


def capture_health_evidence(
    rows: dict[str, list[dict[str, Any]]], expected_halves: set[int],
) -> dict[str, Any]:
    manifests, health = rows.get("manifests", []), rows.get("health", [])
    manifest_halves = {int(row["half"]) for row in manifests}
    health_by_half: dict[int, set[str]] = {}
    for row in health:
        health_by_half.setdefault(int(row["half"]), set()).add(str(row["event_type"]))
    complete_types = bool(expected_halves) and all(
        health_by_half.get(half, set()) == CAPTURE_EVENT_TYPES
        for half in expected_halves
    )
    drops = sum(int(row.get("dropped") or 0) for row in health)
    gaps = max((int(row.get("sequence_gap_count") or 0) for row in health), default=0)
    duplicates = max(
        (int(row.get("duplicate_or_reordered_count") or 0) for row in health),
        default=0,
    )
    mismatches = [row for row in health if int(row.get("emitted") or 0)
                  != int(row.get("daemon_received") or 0)]
    attempted_mismatches = [
        row for row in health
        if int(row.get("attempted") or 0)
        != int(row.get("enqueued") or 0) + int(row.get("dropped") or 0)
    ]
    enqueue_mismatches = [
        row for row in health
        if int(row.get("enqueued") or 0) != int(row.get("emitted") or 0)
    ]
    acceptance_mismatches = [
        row for row in health
        if int(row.get("emitted") or 0) != int(row.get("daemon_accepted") or 0)
    ]
    rejected = sum(int(row.get("daemon_rejected") or 0) for row in health)
    correlation_failures = sum(
        int(row.get("correlation_failure_count") or 0) for row in health
    )
    manifest_complete = bool(expected_halves) and manifest_halves == expected_halves
    manifest_authorized = manifest_complete and all(
        int(row.get("schema_version") or 0) == 22
        and abs(float(row.get("position_interval") or 0) - 2.0) <= 0.01
        and {"objective_attempt", "grenade_entity"}.issubset({
            item.strip() for item in str(row.get("capabilities") or "").split(",")
            if item.strip()
        })
        for row in manifests
    )
    available = bool(manifests or health)
    trusted = bool(
        available and manifest_authorized and complete_types and drops == 0
        and gaps == 0 and duplicates == 0 and not mismatches
        and not attempted_mismatches and not enqueue_mismatches
        and not acceptance_mismatches and rejected == 0 and correlation_failures == 0
    )
    return {
        "available": available,
        "trusted": trusted,
        "manifest_complete": manifest_complete,
        "manifest_authorized": manifest_authorized,
        "health_types_complete": complete_types,
        "producer_drops": drops,
        "sequence_gaps": gaps,
        "duplicates_or_reordered": duplicates,
        "emitted_received_mismatches": len(mismatches),
        "attempted_enqueue_drop_mismatches": len(attempted_mismatches),
        "enqueued_emitted_mismatches": len(enqueue_mismatches),
        "emitted_accepted_mismatches": len(acceptance_mismatches),
        "daemon_rejected": rejected,
        "correlation_failures": correlation_failures,
        "manifest_versions": sorted({
            f"{row.get('producer')}@{row.get('producer_version')}/schema-{row.get('schema_version')}"
            for row in manifests
        }),
        "rows": health,
    }


def collect_cap_breaks(db: EphemeralMysql, match_id: str) -> list[dict[str, Any]]:
    literal = analytics.sql_literal(match_id)
    detail_columns = (
        "eventTime", "playerId", "pos_x", "pos_y", "pos_z",
        "break_victim_id", "break_incident_id", "flag_index", "flag_name",
    )
    detailed = all(
        _column_exists(db, "hlstats_Events_PlayerActions", column)
        for column in detail_columns
    )
    select = (
        "pa.eventTime AS event_time, pa.playerId AS player_id, "
        "pa.pos_x, pa.pos_y, pa.pos_z, pa.break_victim_id, "
        "pa.break_incident_id, pa.flag_index, pa.flag_name" if detailed else
        "NULL AS event_time, NULL AS player_id, NULL AS pos_x, "
        "NULL AS pos_y, NULL AS pos_z, NULL AS break_victim_id, "
        "NULL AS break_incident_id, NULL AS flag_index, NULL AS flag_name"
    )
    return analytics.tsv_rows(db.sql(f"""
SELECT {select}
FROM hlstats_Events_PlayerActions pa
JOIN hlstats_Actions a ON a.id=pa.actionId
WHERE BINARY pa.match_id = BINARY {literal}
  AND a.game='dod' AND a.code='cap_break'
"""))


def classification_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [row.get("match_type") for row in rows]
    distinct = sorted({value for value in values if value is not None})
    consistent = bool(rows) and len(distinct) == 1 and len(values) == len([v for v in values if v is not None])
    value = distinct[0] if consistent else None
    return {
        "available": bool(rows), "consistent": consistent,
        "match_type": value, "match_type_name": MATCH_TYPES.get(value),
        "halves": rows,
    }


def ownership_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((int(row["half"]), int(row["flag_index"])), []).append(row)
    baselines = []
    for (half, flag_index), events in sorted(groups.items()):
        initial = [event for event in events if int(event["is_initial"]) == 1]
        baselines.append({
            "half": half, "flag_index": flag_index,
            "initial_rows": len(initial),
            "starts_at_zero": len(initial) == 1 and float(initial[0]["game_time"]) == 0,
        })
    invalid = [row for row in rows if int(row["owner_team"]) not in (0, 1, 2)]
    baseline_ok = bool(groups) and all(
        item["initial_rows"] == 1 and item["starts_at_zero"] for item in baselines
    )
    return {
        "available": bool(rows), "event_count": len(rows),
        "transition_count": sum(int(row["is_initial"]) == 0 for row in rows),
        "baseline_ok": baseline_ok, "invalid_owner_count": len(invalid),
        "baselines": baselines,
    }


def capture_activation_evidence(
    rows: dict[str, Any], *, generic_assists: int,
) -> dict[str, Any]:
    def coverage(section: str) -> float | None:
        values = rows[section]
        total, timed = values.get("rows_total"), values.get("rows_producer_timed")
        return round(100.0 * int(timed) / int(total), 3) if total and timed is not None else None

    frag_pct = coverage("frags")
    damage_pct = coverage("damage")
    frag_total = int(rows["frags"].get("rows_total") or 0)
    frag_contextual = int(rows["frags"].get("rows_contextual") or 0)
    frag_context_pct = (
        round(100.0 * frag_contextual / frag_total, 3) if frag_total else None
    )
    canonical = rows["canonical_assists"].get("rows_total")
    return {
        **rows,
        "frag_producer_coverage_pct": frag_pct,
        "frag_context_coverage_pct": frag_context_pct,
        "damage_producer_coverage_pct": damage_pct,
        "life_active": (
            rows["life_events"].get("rows_total") is not None
            and int(rows["life_events"]["rows_total"]) > 0
        ),
        "assist_reconciled": (
            canonical is not None and int(canonical) == int(generic_assists)
        ),
        "generic_assists": generic_assists,
    }


def objective_trust_evidence(
    ownership: dict[str, Any], ownership_rows: list[dict[str, Any]],
    flag_positions: list[dict[str, Any]],
) -> dict[str, Any]:
    observed = {
        (int(row["flag_index"]), str(row["flag_name"])) for row in ownership_rows
    }
    positioned = {
        (int(row["flag_index"]), str(row["flag_name"])) for row in flag_positions
    }
    halves = sorted({int(row["half"]) for row in ownership_rows})
    complete_partition_by_half: dict[int, bool] = {}
    for half in halves:
        state: dict[int, int] = {}
        exercised = False
        events = sorted(
            (row for row in ownership_rows if int(row["half"]) == half),
            key=lambda row: (
                float(row["game_time"]), int(row.get("event_id") or 0)
            ),
        )
        for row in events:
            state[int(row["flag_index"])] = int(row["owner_team"])
            owners = list(state.values())
            if (
                len(state) == len(observed)
                and owners and all(owner in (1, 2) for owner in owners)
                and 1 in owners and 2 in owners
            ):
                exercised = True
        complete_partition_by_half[half] = exercised
    static_complete = bool(observed) and observed.issubset(positioned)
    competitive_partition_observed = bool(halves) and all(
        complete_partition_by_half[half] for half in halves
    )
    trusted = bool(
        ownership["baseline_ok"] and ownership["invalid_owner_count"] == 0
        and static_complete and competitive_partition_observed
    )
    return {
        "trusted_for_capout_and_last_flag": trusted,
        "observed_flags": len(observed), "positioned_flags": len(positioned),
        "static_positions_complete": static_complete,
        "competitive_partition_observed": competitive_partition_observed,
        "complete_partition_by_half": complete_partition_by_half,
        "reason": (
            "Ownership baselines and static map topology support derived objective classifications."
            if trusted else
            "Suppress capout and last-flag-defense analytics; map topology is not proven by this fixture."
        ),
    }


def cap_break_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    exact = bool(rows) and all(row.get("break_incident_id") is not None for row in rows)
    detailed = bool(rows) and all(row.get("event_time") is not None for row in rows)
    incidents = None
    if exact:
        incidents = len({row["break_incident_id"] for row in rows})
    elif detailed:
        incidents = len({(
            row.get("event_time"), row.get("player_id"), row.get("pos_x"),
            row.get("pos_y"), row.get("pos_z"),
        ) for row in rows})
    return {
        "cappers_stopped": len(rows),
        "incident_lower_bound": incidents,
        "incident_identity_available": exact,
        "victim_identity_coverage": (
            sum(row.get("break_victim_id") is not None for row in rows) / len(rows)
            if rows else None
        ),
        "schema_gap": (
            None if exact else
            "Rows lack victim/flag/incident IDs; identical multi-capper credits can only be grouped as a lower bound."
            if rows else None
        ),
    }


def statsme_reconciliation(
    players: list[dict[str, Any]], weapons: list[dict[str, Any]],
) -> dict[str, Any]:
    enemy_frags = sum(int(row.get("kills") or 0) for row in players)
    teamkills = sum(int(row.get("team_kills") or 0) for row in players)
    suicides = sum(int(row.get("suicides") or 0) for row in players)
    statsme_kills = sum(int(row.get("statsme_kills") or 0) for row in weapons)
    statsme_deaths = sum(int(row.get("statsme_deaths") or 0) for row in weapons)
    physical_deaths = enemy_frags + teamkills + suicides
    statsme_kill_domain = enemy_frags + teamkills
    return {
        "canonical_enemy_frags": enemy_frags,
        "canonical_teamkills": teamkills,
        "canonical_suicides": suicides,
        "canonical_physical_deaths": physical_deaths,
        "statsme_kills": statsme_kills,
        "statsme_deaths": statsme_deaths,
        "statsme_expected_kill_domain": statsme_kill_domain,
        "statsme_kills_reconciled": statsme_kills == statsme_kill_domain,
        "statsme_death_delta": statsme_deaths - physical_deaths,
        "canonical_rule": (
            "Use frag/teamkill/suicide ledgers for K/D and physical deaths; "
            "StatsMe remains auxiliary weapon accuracy/hitbox telemetry."
        ),
    }


def retention_evidence(
    match_id: str, classification: dict[str, Any], *, days: int,
    as_of: datetime,
) -> dict[str, Any]:
    halves = classification.get("halves", [])
    ended = [row.get("end_time") or row.get("start_time") for row in halves]
    last = max((value for value in ended if value), default=None)
    age_days = None
    if last:
        parsed = datetime.fromisoformat(str(last)).replace(tzinfo=timezone.utc)
        age_days = (as_of - parsed).total_seconds() / 86400
    match_type = classification.get("match_type")
    purge_class = bool(match_id.endswith("-TEST") or match_type in (1, 2))
    eligible = bool(purge_class and age_days is not None and age_days >= days)
    return {
        "policy_days": days, "purge_class": purge_class,
        "age_days": round(age_days, 3) if age_days is not None else None,
        "eligible_now": eligible,
        "reason": (
            "expired temporary analytics" if eligible else
            "temporary analytics inside retention window" if purge_class else
            "retained match class"
        ),
    }


def build_evidence(
    analytics_report: dict[str, Any], classifications: list[dict[str, Any]],
    ownership_rows: list[dict[str, Any]], logs: dict[str, Any],
    provenance: dict[str, Any], *, capture_activation: dict[str, Any] | None = None,
    flag_positions: list[dict[str, Any]] | None = None,
    cap_break_rows: list[dict[str, Any]] | None = None,
    capture_health_rows: dict[str, list[dict[str, Any]]] | None = None,
    position_cadence_rows: list[dict[str, Any]] | None = None,
    expected_server_id: int | None = None,
    retention_days: int = 14, as_of: datetime | None = None,
) -> dict[str, Any]:
    classification = classification_evidence(classifications)
    ownership = ownership_evidence(ownership_rows)
    generic_assists = sum(row["assists"] for row in analytics_report["assists"])
    activation = capture_activation_evidence(
        capture_activation or {
            "frags": {"rows_total": 0, "rows_producer_timed": None},
            "damage": {"rows_total": 0, "rows_producer_timed": None},
            "life_events": {"rows_total": None},
            "canonical_assists": {"rows_total": None},
        }, generic_assists=generic_assists,
    )
    objective_trust = objective_trust_evidence(
        ownership, ownership_rows, flag_positions or [],
    )
    cap_breaks = cap_break_evidence(cap_break_rows or [])
    statsme = statsme_reconciliation(
        analytics_report["players"], analytics_report["weapons"]
    )
    retention = retention_evidence(
        analytics_report["match_id"], classification, days=retention_days,
        as_of=as_of or datetime.now(timezone.utc),
    )
    sources = analytics_report["source_coverage"]
    expected_halves = {int(row["half"]) for row in classifications}
    capture_health = capture_health_evidence(
        capture_health_rows or {"manifests": [], "health": []}, expected_halves,
    )
    position_cadence = position_cadence_evidence(position_cadence_rows or [])
    checks = []

    def add(level: str, code: str, detail: str) -> None:
        checks.append({"level": level, "code": code, "detail": detail})

    add(analytics_report["quality"]["status"], "analytics_quality",
        "Shared match analytics quality gate.")
    add("PASS" if classification["consistent"] else "FAIL", "match_type_consistency",
        "Every half has one consistent persisted match type.")
    add("PASS" if ownership["baseline_ok"] else "FAIL", "ownership_baselines",
        "Every observed half/flag starts with exactly one game_time=0 baseline.")
    add("PASS" if ownership["invalid_owner_count"] == 0 else "FAIL", "ownership_values",
        "Ownership values are restricted to neutral, Allies, or Axis.")
    for source, label in (("frag", "Frag"), ("damage", "Damage")):
        percent = activation[f"{source}_producer_coverage_pct"]
        add(
            "PASS" if percent == 100.0 else
            "FAIL" if percent is None or percent == 0.0 else "WARN",
            f"{source}_producer_clock",
            f"{label} producer-clock coverage: {percent if percent is not None else 'unavailable'}%.",
        )
    context_pct = activation["frag_context_coverage_pct"]
    add(
        "PASS" if context_pct is not None and context_pct >= FRAG_CONTEXT_SLO_PCT
        else "FAIL",
        "frag_context_slo",
        f"Frag-context coverage: {context_pct if context_pct is not None else 'unavailable'}%; "
        f"required >= {FRAG_CONTEXT_SLO_PCT}%.",
    )
    invalid_maps = activation["frags"].get("rows_invalid_map")
    add(
        "WARN" if invalid_maps is None else
        "PASS" if int(invalid_maps) == 0 else "FAIL",
        "canonical_map_names",
        f"Frag rows with non-dod_ map names: {invalid_maps if invalid_maps is not None else 'unavailable'}.",
    )
    add(
        "PASS" if position_cadence["within_slo"] else
        "WARN" if not position_cadence["available"] else "FAIL",
        "position_cadence_slo",
        f"Position cadence target {POSITION_INTERVAL_SECONDS}s +/- "
        f"{POSITION_INTERVAL_TOLERANCE_SECONDS}s; halves: "
        f"{position_cadence['halves'] if position_cadence['available'] else 'unavailable'}.",
    )
    add("PASS" if activation["life_active"] else "FAIL", "life_capture_active",
        f"Physical life rows: {activation['life_events'].get('rows_total')}.")
    assist_level = (
        "PASS" if activation["assist_reconciled"] and generic_assists > 0 else
        "WARN" if activation["assist_reconciled"] else "FAIL"
    )
    add(assist_level, "canonical_assist_reconciliation",
        f"Generic assists: {generic_assists}; canonical timed assists: "
        f"{activation['canonical_assists'].get('rows_total')}.")
    add(
        "PASS" if capture_health["trusted"] else
        "WARN" if not capture_health["available"] else "FAIL",
        "capture_health_reconciliation",
        "Producer counters, daemon receipts, and global sequences reconcile."
        if capture_health["trusted"] else
        "Capture-health telemetry is unavailable (legacy producer)."
        if not capture_health["available"] else
        f"drops={capture_health['producer_drops']} gaps={capture_health['sequence_gaps']} "
        f"receipt_mismatches={capture_health['emitted_received_mismatches']} "
        f"rejected={capture_health['daemon_rejected']} "
        f"correlation_failures={capture_health['correlation_failures']}.",
    )
    add("PASS" if objective_trust["trusted_for_capout_and_last_flag"] else "WARN",
        "objective_classification_trust", objective_trust["reason"])
    add("PASS" if statsme["statsme_kills_reconciled"] else "WARN",
        "statsme_kill_domain",
        f"StatsMe kills: {statsme['statsme_kills']}; enemy frags + teamkills: "
        f"{statsme['statsme_expected_kill_domain']}. StatsMe deaths are auxiliary, "
        f"with delta {statsme['statsme_death_delta']} versus physical ledgers.")
    required = ("per_hit_damage", "capture_credits", "positions", "flag_ownership",
                "statsme", "statsme2", "assists")
    missing = [name for name in required if not sources.get(name)]
    add("PASS" if not missing else "FAIL", "required_sources",
        "All current canary sources are present." if not missing else f"Missing: {', '.join(missing)}")
    if expected_server_id is not None:
        actual = (analytics_report.get("match") or {}).get("server_id")
        add("PASS" if actual == expected_server_id else "FAIL", "expected_server",
            f"Expected server {expected_server_id}; observed {actual}.")
    if logs["status"] == "not_provided":
        add("WARN", "operational_logs", "No game/daemon logs supplied; error checks are unavailable.")
    else:
        clean = logs["status"] == "clean"
        add("PASS" if clean else "FAIL", "operational_logs",
            "No unresolved-action or SQL errors found." if clean else "Operational errors found; inspect samples.")

    status = "FAIL" if any(row["level"] == "FAIL" for row in checks) else (
        "WARN" if any(row["level"] == "WARN" for row in checks) else "PASS"
    )
    timelines = analytics_report["shadow_timelines"]
    return {
        "schema_version": 2, "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status, "match_id": analytics_report["match_id"],
        "provenance": provenance, "checks": checks,
        "match_type": classification, "ownership": ownership,
        "capture_activation": activation,
        "capture_health": capture_health,
        "position_cadence": position_cadence,
        "objective_classification": objective_trust,
        "cap_breaks": cap_breaks,
        "statsme_reconciliation": statsme,
        "source_coverage": sources,
        "analytics_coverage": {
            "players": len(analytics_report["players"]),
            "assists": sum(row["assists"] for row in analytics_report["assists"]),
            "damage_events": analytics_report["source_inventory"].get("damage_events"),
            "capture_events": len(analytics_report["capture_events"]),
            "position_samples": analytics_report["positional"]["aggregate_sample_count"],
            "weapon_rows": len(analytics_report["weapons"]),
        },
        "shadow_timeline_summary": {
            "status": timelines["status"], "config": timelines["config"],
            "fast_multikills": len(timelines["fast_multikills"]),
            "trades": len(timelines["trades"]),
            "opening_duels": len(timelines["opening_duels"]),
            "head_to_head_pairs": len(timelines["head_to_head"]),
        },
        "operational_logs": logs, "retention": retention,
        "analytics_report": analytics_report,
    }


def render_markdown(evidence: dict[str, Any]) -> str:
    lines = [
        f"# Canary evidence — {evidence['match_id']}", "",
        f"Gate: **{evidence['status']}**", "",
        "## Checks", "", "| Result | Check | Detail |", "|---|---|---|",
    ]
    for check in evidence["checks"]:
        lines.append(f"| {check['level']} | `{check['code']}` | {check['detail']} |")
    classification, ownership = evidence["match_type"], evidence["ownership"]
    lines += [
        "", "## Classification and retention", "",
        f"Persisted type: `{classification.get('match_type_name')}`; "
        f"consistent: `{classification['consistent']}`.  ",
        f"Retention: {evidence['retention']['reason']}; "
        f"eligible now: `{evidence['retention']['eligible_now']}`.",
        "", "## Ownership", "",
        f"Events: {ownership['event_count']}; transitions: {ownership['transition_count']}; "
        f"baselines valid: `{ownership['baseline_ok']}`.",
        "", "## Capture activation", "",
        f"Frag producer clocks: `{evidence['capture_activation']['frag_producer_coverage_pct']}%`; "
        f"damage producer clocks: `{evidence['capture_activation']['damage_producer_coverage_pct']}%`.  ",
        f"Life rows: `{evidence['capture_activation']['life_events'].get('rows_total')}`; "
        f"canonical assists: `{evidence['capture_activation']['canonical_assists'].get('rows_total')}`.",
        f"Capture-health trusted: `{evidence['capture_health']['trusted']}`; "
        f"drops: `{evidence['capture_health']['producer_drops']}`; "
        f"sequence gaps: `{evidence['capture_health']['sequence_gaps']}`.",
        f"Position cadence within SLO: `{evidence['position_cadence']['within_slo']}`; "
        f"halves: `{evidence['position_cadence']['halves']}`.",
        "", "## Objective classification", "",
        f"Trusted for capout/last-flag: "
        f"`{evidence['objective_classification']['trusted_for_capout_and_last_flag']}`.  ",
        evidence["objective_classification"]["reason"],
        f"Cap-break credits: `{evidence['cap_breaks']['cappers_stopped']}`; "
        f"incident lower bound: `{evidence['cap_breaks']['incident_lower_bound']}`.",
        "", "## Counter reconciliation", "",
        f"StatsMe kills: `{evidence['statsme_reconciliation']['statsme_kills']}`; "
        f"enemy frags + teamkills: "
        f"`{evidence['statsme_reconciliation']['statsme_expected_kill_domain']}`.  ",
        f"StatsMe deaths versus physical-ledger deaths delta: "
        f"`{evidence['statsme_reconciliation']['statsme_death_delta']}`.  ",
        evidence["statsme_reconciliation"]["canonical_rule"],
        "", "## Shadow timelines", "",
        "Private/read-only exploratory output; no rating or public API writes.", "",
        "```json", json.dumps(evidence["shadow_timeline_summary"], indent=2), "```", "",
        "## Provenance", "", "```json", json.dumps(evidence["provenance"], indent=2), "```", "",
    ]
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--output-dir", type=Path, default=REPO / "build" / "canary-evidence")
    parser.add_argument("--game-log", type=Path, action="append", default=[])
    parser.add_argument("--daemon-log", type=Path, action="append", default=[])
    parser.add_argument("--expected-server-id", type=int)
    parser.add_argument("--retention-days", type=int, default=14)
    parser.add_argument("--source-mode", choices=("database", "replay"), default="database")
    parser.add_argument("--multikill-seconds", type=float, default=10.0)
    parser.add_argument("--trade-seconds", type=float, default=5.0)
    parser.add_argument("--objective-conversion-seconds", type=float, default=30.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    fixture = args.fixture.resolve()
    with EphemeralMysql.start() as db:
        analytics.load_fixture(db, fixture)
        sources = analytics.source_capabilities(db)
        if not all((sources["per_hit_damage"], sources["capture_credits"], sources["positions"])):
            analytics.install_legacy_compatibility(db)
        if args.match_id not in analytics.discover_match_ids(db):
            raise SystemExit(f"match {args.match_id!r} not found in fixture")
        report = analytics.build_report(
            db, args.match_id, fixture, sources, args.source_mode,
            TimelineConfig(args.multikill_seconds, args.trade_seconds,
                           args.objective_conversion_seconds),
        )
        classifications = collect_classification(db, args.match_id)
        ownership = collect_ownership(db, args.match_id, sources.get("flag_ownership", False))
        activation = collect_capture_activation(db, args.match_id, sources)
        flag_positions = collect_flag_positions(
            db, args.match_id, sources.get("flag_positions", False)
        )
        cap_break_rows = collect_cap_breaks(db, args.match_id)
        capture_health_rows = collect_capture_health(
            db, args.match_id, sources.get("capture_health", False)
        )
        position_cadence_rows = collect_position_cadence(
            db, args.match_id, sources.get("positions", False)
        )

    evidence = build_evidence(
        report, classifications, ownership,
        inspect_logs(args.game_log + args.daemon_log),
        {
            "fixture": fixture.name, "fixture_bytes": fixture.stat().st_size,
            "fixture_sha256": _sha256(fixture), "source_mode": args.source_mode,
            "analytics_schema_version": analytics.SCHEMA_VERSION,
        },
        capture_activation=activation, flag_positions=flag_positions,
        cap_break_rows=cap_break_rows, capture_health_rows=capture_health_rows,
        position_cadence_rows=position_cadence_rows,
        expected_server_id=args.expected_server_id,
        retention_days=args.retention_days,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.match_id}-canary-evidence"
    json_path, md_path = args.output_dir / f"{stem}.json", args.output_dir / f"{stem}.md"
    json_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(evidence), encoding="utf-8")
    print(f"{evidence['status']}: {args.match_id}")
    print(json_path)
    print(md_path)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
