#!/usr/bin/env python3
"""Generate a read-only JSON and Markdown analytics report for one match.

Phase A deliberately supports persisted local fixture dumps only. It starts an
isolated MySQL/MariaDB instance, imports the dump, runs SELECT-only SQL, writes
the report locally, and tears the database down. It has no HTTP client and no
production database configuration.

Usage (inside the Lane B image, with this repository mounted at /work):

    python3 scripts/match_analytics.py \
      tests/e2e_stats/fixtures/.../hlstatsx-fixture.sql.gz \
      --output-dir /work/build/match-analytics
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_SPAWN_OWNERSHIP = (
    Path(__file__).resolve().parents[1] / "config" / "analytics"
    / "spawn_ownership.toml"
)

from tests.e2e_stats.ephemeral_mysql import EphemeralMysql  # noqa: E402
from scripts.damage_conversion import (  # noqa: E402
    DamageConversionConfig,
    build_damage_conversion,
)
from scripts.fps_stat_explorations import (  # noqa: E402
    EngagementDistanceConfig,
    ObjectivePressureConfig,
    build_objective_pressure_shadow,
    build_weapon_engagement_shadow,
)
from scripts.flag_fights import (  # noqa: E402
    build_clutch_shadow,
    build_entries_shadow,
    build_flag_fight_shadow,
)
from scripts.highlight_windows import build_highlight_windows  # noqa: E402
from scripts.excursions import build_excursions  # noqa: E402
from scripts.plays import build_plays  # noqa: E402
from scripts.progression import build_progression  # noqa: E402
from scripts.roster_teams import apply_canonical_teams  # noqa: E402
from scripts.flag_swing import (  # noqa: E402
    build_flag_swing_shadow,
)
from scripts.report_team_convention import (  # noqa: E402
    report_team1_engine_side,
    translate_capouts,
    translate_map_control,
    translate_team_series,
)
from scripts.ktpr_v2 import (  # noqa: E402
    build_ktpr_v2_shadow,
)
from scripts.positional_shadow import (  # noqa: E402
    PositionalConfig,
    build_positional_shadow,
)
from scripts.spatial_layers import (  # noqa: E402
    SpatialLayersConfig,
    build_spatial_layers,
)
from scripts.objective_control import (  # noqa: E402
    build_recap_speed,
)
from scripts.life_exploration import (  # noqa: E402
    LifeExplorationConfig,
    build_life_exploration,
)
from scripts.match_timelines import (  # noqa: E402
    TimelineConfig,
    _revenge_analysis,
    build_shadow_timelines,
)


from scripts.in_game_result import load_in_game_result, unavailable as in_game_unavailable  # noqa: E402
from scripts.player_halves import build_player_halves  # noqa: E402
from scripts.kill_streaks import (  # noqa: E402
    best_by_player, best_by_player_half, build_kill_streaks)
from scripts.life_ledger import resolve_sides  # noqa: E402
from scripts.side_splits import (  # noqa: E402
    annotate_player_halves, build_duels_by_side, build_player_classes,
    build_weapon_sides, load_class_map)

REPO = Path(__file__).resolve().parents[1]
SQL_DIR = REPO / "sql" / "analytics"
SCHEMA_VERSION = 21  # 9: spatial_layers; 10: in_game_result + player_halves; 11: kill_streaks + side/class splits; 12: objective score + grenade damage/kills, per-team and per-minute rates; 13: wave 1/2 player facts (damage_applied, life shots, score attribution) + duel_stats; 14: grenade throws + flight time; 15: aim shadow (computed placement + AC on-hit precision); 16: shadow_explorations.highlight_windows (key moments ranked on flag_swing); 17: shadow_explorations.progression (cumulative per-player series per half); 18: shadow_explorations.excursions + plays (per-player top plays, match top three, dunce); 19: map_control + progression.flag_differential translated engine-side -> report-team convention (were silently backwards in half 1 of every two-half match); shadow_explorations.capouts; 20: progression gains cap_breaks (producer clock already on hlstats_Events_PlayerActions since migrate_021, just never probed for) and cap_participation (reuses credit_timeline, already computed for flag_swing/excursions -- no new query); 21: excursions use the per-map isolation distance (p80 of each map's own past-the-rear-line teammate distance) instead of a flat 1200 that was measuring the map rather than the player -- changes which runs exist, so plays change with them
# The health streams EVERY producer contract emits, schema 21 onward. All of
# these must appear exactly once per half; a missing one means that stream went
# dark, which is the defect this list exists to catch.
CAPTURE_EVENT_TYPES = (
    "life", "damage", "position", "frag", "assist", "break",
    "flag_state", "flag_position", "objective_attempt", "team_membership",
    "grenade_entity",
)

# Streams a NEWER producer may additionally emit. Permitted but not required,
# so one set of expectations covers a fleet mid-rollout.
#
# `ksc_emit_health` loops over every event type the plugin knows, so a plugin
# that gains a stream gains a health row for it. Comparing the observed set for
# exact equality against the required list therefore breaks on the first match
# played by a newer plugin -- every half reports "does not contain each exact
# health type once" while nothing is actually wrong. Schema 24 added `shot`
# (KTPAMXX #102) and would have done exactly that to every match, on both this
# check and canary_evidence's `complete_types`.
#
# Anything outside required|optional is still an error: an unknown type is a
# producer/daemon disagreement worth failing on.
CAPTURE_EVENT_TYPES_OPTIONAL = (
    "shot",
    # Expansion wave 2 (KTPAMXX 1.22.0, migration 033).
    "score",
    "duel",
    "player_state",
    # Grenade throw (migration 034, KTPAMXX 1.23.0).
    "grenade_throw",
)
TEAM_NAMES = {1: "Allies", 2: "Axis"}
GRENADE_WEAPON_TYPES = {13: "handgrenade", 14: "stickgrenade", 36: "mills_bomb"}

# Production ids are <epoch>-<SERVER> (1788919258-CHI1); the 12-man branch
# writes 1.3-<queueId>-<SERVER>; test mode writes <anything>-TEST. The server
# alias is matched generically so a new region is not stamped malformed.
MATCH_ID_RE = re.compile(
    r"(?:\d+|1\.3-\d+)-[A-Z]{2,5}\d+|[A-Za-z0-9._-]+-TEST")

INTEGER_COLUMNS = {
    "server_id", "player_id", "team", "duration_seconds", "halves_played",
    "open_halves", "is_test_match", "kills", "deaths", "assists",
    "headshots", "team_kills", "suicides", "damage_dealt", "damage_taken",
    "team_damage", "self_damage", "capture_credits", "cap_breaks", "shots",
    "hits", "position_samples", "headshot_kills", "head_hits", "chest_hits",
    "stomach_hits", "arm_hits", "leg_hits", "located_hits", "statsme_kills",
    "statsme_deaths", "statsme_damage", "half", "credited_players",
    "match_halves", "roster_players", "distinct_roster_players", "frags",
    "invalid_half_frags", "damage_events", "invalid_half_damage",
    "statsme_rows", "statsme2_rows", "statsme_hits", "unique_capture_events",
    "cached_player_totals", "cached_kills", "cached_deaths", "victim_id",
    "legacy_damage_dealt", "legacy_kills", "statsme_damage_dealt", "statsme_frags",
    "event_id", "event_unix", "killer_id", "killer_team", "victim_team",
    "match_type", "flag_index", "owner_team", "is_initial",
    "attacker_id", "attacker_team", "assister_id", "assister_team",
    "damage_capped", "hitplace", "sample_id", "origin_x", "origin_y",
    "killer_pos_x", "killer_pos_y", "killer_pos_z", "victim_pos_x",
    "victim_pos_y", "victim_pos_z", "killer_prone", "killer_scoped",
    "killer_clip", "killer_ammo", "is_last_flag_defense", "is_alive",
    "frag_context_recorded",
    "player_slot", "engine_userid", "player_class", "round_live",
    "event_epoch", "producer_activation_epoch", "activation_receipt_epoch",
    "match_start_epoch", "start_epoch", "end_epoch",
    "stored_half", "producer_half", "receipt_epoch",
    "score", "grenade_kills", "grenade_damage", "grenade_damage_taken",
    "attempt_id", "producer_sequence", "entindex", "serial", "weapon_id",
    "owner_player_id", "owner_engine_userid", "allies_in_zone", "axis_in_zone",
    "damage_applied", "damage_capped_with_applied", "hits_with_applied",
    "life_shots", "life_shots_hitscan", "lives_fired", "score_events",
    "score_points", "score_points_placed", "score_events_unresolved",
    "head_hits", "chest_hits", "stomach_hits", "arm_hits", "leg_hits",
    "grenade_throws", "grenade_bursts_matched", "grenade_cooked",
    "placement_shots", "ac_hits_with_geometry", "ac_range_avg",
}
FLOAT_COLUMNS = {
    "kd_ratio", "kda_ratio", "damage_per_minute", "damage_per_life",
    "headshot_rate", "raw_accuracy", "game_time", "first_shot_delay_avg",
    "grenade_flight_avg", "placement_avg_deg", "placement_under5_pct",
    "placement_under15_pct", "ac_err_avg_deg", "ac_target_angvel_avg_dps",
}


def sql_literal(value: str) -> str:
    """Return a MySQL string literal for a value selected by the operator."""
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


# Half expressions an analytics query may name. The first form reads the stored
# half and runs on every archive; the second prefers the producer half and needs
# the columns named by the capability.
_HALF_TOKENS = {
    "FRAG_HALF": ("frag_event_clock", "f.half",
                  "CASE WHEN BINARY f.producer_match_id = BINARY {{MATCH_ID}} "
                  "AND f.producer_half > 0 THEN f.producer_half ELSE f.half END"),
    "DAMAGE_HALF": ("damage_event_clock", "de.half",
                    "CASE WHEN BINARY de.producer_match_id = BINARY {{MATCH_ID}} "
                    "AND de.producer_half > 0 THEN de.producer_half ELSE de.half END"),
    "BREAK_HALF": ("break_producer_half",
                   "(SELECT MAX(h.half) FROM halves h WHERE h.start_time <= e.eventTime)",
                   "COALESCE(CASE WHEN BINARY e.producer_match_id = BINARY {{MATCH_ID}} "
                   "AND e.producer_half > 0 THEN e.producer_half END, "
                   "(SELECT MAX(h.half) FROM halves h WHERE h.start_time <= e.eventTime))"),
}


def read_query(name: str, match_id: str, sources: dict[str, bool] | None = None) -> str:
    path = SQL_DIR / name
    query = path.read_text(encoding="utf-8")
    for token, (capability, stored, producer) in _HALF_TOKENS.items():
        use_producer = bool((sources or {}).get(capability, False))
        query = query.replace("{{" + token + "}}", producer if use_producer else stored)
    query = query.replace("{{MATCH_ID}}", sql_literal(match_id))
    # This is a defense against an accidental mutating analytics file, not a
    # general SQL parser. The checked-in query files are also reviewed/tests.
    first = query.lstrip().lower()
    while first.startswith("--"):
        first = first.split("\n", 1)[1].lstrip()
    if not (first.startswith("select") or first.startswith("with")):
        raise ValueError(f"analytics query is not read-only: {path}")
    return query


def _value(name: str, raw: str) -> Any:
    if raw == "NULL":
        return None
    if name in INTEGER_COLUMNS:
        return int(raw)
    if name in FLOAT_COLUMNS:
        return float(raw)
    return raw


def tsv_rows(output: str) -> list[dict[str, Any]]:
    if not output.strip():
        return []
    # mysql --batch --raw emits TSV, not CSV. Quote characters are ordinary
    # field data (a malformed historical match_id contains them), so enabling
    # csv's default quote handling silently changes identifiers.
    reader = csv.DictReader(output.splitlines(), delimiter="\t", quoting=csv.QUOTE_NONE)
    return [
        {name: _value(name, raw) for name, raw in row.items()}
        for row in reader
    ]


def query_rows(db: EphemeralMysql, name: str, match_id: str,
               sources: dict[str, bool] | None = None) -> list[dict[str, Any]]:
    return tsv_rows(db.sql(read_query(name, match_id, sources)))


def load_fixture(db: EphemeralMysql, fixture: Path) -> None:
    """Stream .sql or .sql.gz into the isolated database without extracting."""
    fixture = fixture.resolve()
    if not fixture.is_file():
        raise FileNotFoundError(f"fixture not found: {fixture}")
    argv = [
        db.client, "--no-defaults", f"--socket={db.socket_path}",
        "-u", "root", db.database,
    ]
    opener = gzip.open if fixture.suffix == ".gz" else Path.open
    with opener(fixture, "rb") as source:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        assert proc.stdin is not None
        try:
            shutil.copyfileobj(source, proc.stdin, length=1024 * 1024)
        finally:
            proc.stdin.close()
        stderr = proc.stderr.read() if proc.stderr is not None else b""
        rc = proc.wait()
    if rc:
        raise RuntimeError(
            f"fixture load failed ({fixture.name}): "
            f"{stderr.decode(errors='replace')[-1500:]}"
        )


def load_spawn_ownership(path: Path, map_name: str) -> dict[int, int]:
    """(flag_index -> 1/2) AUTHORED spawn owners for one map.

    Read from each map's own BSP (`point_default_owner`), not inferred from
    play -- see config/analytics/spawn_ownership.toml and regenerate with
    scripts/map_spawn_ownership.py. A flag absent here is unresolved, not
    neutral; callers must not fill in a default.
    """
    if not path.exists():
        return {}
    with path.open("rb") as source:
        maps = tomllib.load(source).get("maps", {})
    flags = maps.get(map_name, {}).get("flags", {})
    return {int(flag_index): int(entry["owner"])
            for flag_index, entry in flags.items()
            if entry.get("owner") in (1, 2)}


def discover_match_ids(db: EphemeralMysql) -> list[str]:
    rows = tsv_rows(db.sql(
        "SELECT DISTINCT match_id FROM ktp_matches "
        "WHERE match_id IS NOT NULL ORDER BY match_id"
    ))
    return [str(row["match_id"]) for row in rows]


def source_capabilities(db: EphemeralMysql) -> dict[str, bool]:
    """Inventory source support before any local compatibility objects exist."""
    rows = tsv_rows(db.sql("""
SELECT
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'ktp_damage_events')
    AS per_hit_damage,
  ((SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'ktp_damage_events'
      AND column_name IN ('producer_match_id', 'producer_half', 'event_epoch')) = 3)
    AS damage_event_clock,
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'ktp_flag_captures')
    AS capture_credits,
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'ktp_position_samples')
    AS positions,
  EXISTS(SELECT 1 FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'ktp_position_samples'
      AND column_name = 'is_alive')
    AS position_liveness,
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'ktp_flag_state_events')
    AS flag_ownership,
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'ktp_flag_positions')
    AS flag_positions,
  EXISTS(SELECT 1 FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'hlstats_Events_Frags'
      AND column_name = 'frag_context_recorded')
    AND EXISTS(SELECT 1 FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'hlstats_Events_Frags'
      AND column_name = 'pos_victim_x')
    AS frag_context,
  ((SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'hlstats_Events_Frags'
      AND column_name IN
        ('producer_match_id', 'producer_half', 'game_time', 'event_epoch')) = 4)
    AS frag_event_clock,
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'ktp_life_events')
    AS life_boundaries,
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'ktp_assist_events')
    AS assist_context,
  (EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'ktp_capture_manifests')
   AND EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'ktp_capture_health'))
    AS capture_health,
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE()
      AND table_name = 'ktp_objective_attempt_events')
    AS objective_attempts,
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE()
      AND table_name = 'ktp_grenade_entity_events')
    AS grenade_entities,
  ((SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND ((table_name = 'ktp_damage_events' AND column_name = 'damage_applied')
        OR (table_name = 'ktp_life_events' AND column_name = 'first_shot_delay'))) = 2)
    AS wave1_fields,
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'ktp_score_events')
    AS score_events,
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'ktp_duel_stats')
    AS duel_stats,
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'ktp_grenade_throw_events')
    AS grenade_throws,
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'ktp_shot_events')
    AS shot_events,
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'ktp_ac_weapon_fires')
    AS ac_weapon_fires,
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'hlstats_Events_Statsme')
    AS statsme,
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'hlstats_Events_Statsme2')
    AS statsme2,
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'ktp_match_stats')
    AS legacy_match_cache,
  EXISTS(SELECT 1 FROM hlstats_Actions
    WHERE game = 'dod' AND code = 'assist')
    AS assists,
  ((SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'hlstats_Events_PlayerActions'
      AND column_name IN ('producer_match_id', 'producer_half')) = 2)
    AS break_producer_half,
  ((SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'hlstats_Events_PlayerActions'
      AND column_name IN ('producer_match_id', 'producer_half',
                          'producer_game_time', 'producer_event_epoch')) = 4)
    AS break_event_clock,
  ((SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND column_name = 'half'
      AND table_name IN ('hlstats_Events_Frags', 'hlstats_Events_Teamkills',
                         'hlstats_Events_Suicides', 'hlstats_Events_Statsme')) = 4)
    AS player_halves
"""))
    if not rows:
        raise RuntimeError("could not inventory analytics source capabilities")
    return {name: bool(int(value)) for name, value in rows[0].items()}


def _half_scoped(rows: list[dict[str, Any]], key: str) -> int:
    return max((int(row.get(key) or 0) for row in rows), default=0)


def _half_sequence_errors(
    half: int, rows: list[dict[str, Any]], intake_shortfall: int,
) -> list[str]:
    """Half-wide sequence evidence that no single stream can own.

    Both counters are HALF-scoped -- the daemon stamps one per-half value into
    every event type's row, so a gap is non-zero even on a stream that emitted
    nothing. A gap is intake loss already charged to the stream whose `emitted`
    exceeds its `daemon_received`; only the unaccounted residual is match-level.
    """
    errors = []
    duplicates = _half_scoped(rows, "duplicate_or_reordered_count")
    if duplicates:
        errors.append(
            f"half {half} reports {duplicates} duplicate or reordered line(s) "
            "on the shared producer sequence")
    residual = _half_scoped(rows, "sequence_gap_count") - intake_shortfall
    if residual > 0:
        errors.append(
            f"half {half} has {residual} sequence-gap line(s) no stream's "
            "emitted/received shortfall accounts for")
    return errors


def capture_stream_status(
    capture: dict[str, Any], event_type: str,
) -> dict[str, Any]:
    """Authorization for ONE capture stream, with the reason it was withheld.

    A stream whose capture reconciles publishes even when a sibling failed --
    a frag correlation failure is not evidence about the objective stream.
    """
    entry = (capture.get("stream_authorization") or {}).get(event_type)
    if entry is None:
        # No per-stream verdict exists only when nothing was captured at all.
        return {
            "authorized": False, "status": "not_captured",
            "reason": "no capture telemetry was recorded for this match",
        }
    if entry.get("authorized"):
        return {"authorized": True, "status": "authorized", "reason": ""}
    reason = "; ".join(entry.get("errors") or [])
    return {
        "authorized": False, "status": "withheld",
        "reason": reason or "capture authorization failed",
    }


def capture_stream_authorized(capture: dict[str, Any], event_type: str) -> bool:
    return bool(capture_stream_status(capture, event_type)["authorized"])


def evaluate_capture_authorization(
    observed_halves: set[int],
    manifests: list[dict[str, Any]],
    health: list[dict[str, Any]],
    *,
    require_activation: bool = False,
) -> dict[str, Any]:
    """Validate schema-22/23 capture authorization without vacuous passes.

    Authorization is PER STREAM, across every observed half -- across-halves
    because consumers query a stream for the whole match, so a per-half verdict
    would publish a partial aggregate with nothing marking it partial.
    `match_errors` are the preconditions that bind every stream at once and
    still fail the match. Match-level `status`/`authorized` keep their meaning.
    """
    expected_types = set(CAPTURE_EVENT_TYPES)
    observed = {int(half) for half in observed_halves if int(half) > 0}
    if not manifests and not health:
        return {
            "status": "not_captured", "authorized": False,
            "observed_halves": sorted(observed), "manifest_halves": [],
            "health_halves": [], "streams": {}, "errors": [],
            "match_errors": [], "stream_authorization": {},
            "authorized_streams": [],
        }
    match_errors: list[str] = []
    stream_errors: dict[str, list[str]] = {}

    def stream_error(event_type: str, message: str) -> None:
        stream_errors.setdefault(event_type or "<empty>", []).append(message)

    manifest_halves = [int(row.get("half") or 0) for row in manifests]
    health_halves = {int(row.get("half") or 0) for row in health}
    if set(manifest_halves) != observed or len(manifest_halves) != len(observed):
        match_errors.append("manifest half set/count does not equal observed match halves")
    if health_halves != observed:
        match_errors.append("health half set does not equal observed match halves")
    for row in manifests:
        capabilities = {
            item.strip() for item in str(row.get("capabilities") or "").split(",")
            if item.strip()
        }
        if (
            # 24 added 2026-09-10 (ENGINE_STATS_EXPANSION_PLAN_20260909.md wave
            # 0): schema 24 is additive over 23 (adds "shot"; drops nothing),
            # so it authorizes the same objective_attempt/grenade_entity
            # contract 22/23 do. An exact {22, 23} set would have failed this
            # gate for every match the moment a schema-24 producer shipped --
            # the same class of bug the KTPHLStatsX daemon fix (PR #87)
            # addressed on the producer side.
            int(row.get("schema_version") or 0) not in {22, 23, 24}
            or abs(float(row.get("position_interval") or 0) - 2.0) > 0.01
            or not {"objective_attempt", "grenade_entity"}.issubset(capabilities)
        ):
            match_errors.append(f"half {row.get('half')} manifest is not schema22+/2.00 authorized")
        if require_activation:
            producer_activation = row.get("producer_activation_epoch")
            activation_receipt = row.get("activation_receipt_epoch")
            match_start = row.get("match_start_epoch")
            try:
                int(producer_activation)
            except (TypeError, ValueError):
                match_errors.append(
                    f"half {row.get('half')} manifest producer activation "
                    "epoch is missing"
                )
            try:
                receipt_epoch = int(activation_receipt)
            except (TypeError, ValueError):
                match_errors.append(
                    f"half {row.get('half')} manifest activation receipt "
                    "epoch is missing"
                )
            else:
                try:
                    start_epoch = int(match_start)
                except (TypeError, ValueError):
                    match_errors.append(
                        f"half {row.get('half')} match start epoch is missing"
                    )
                else:
                    latency = receipt_epoch - start_epoch
                    if not 0 <= latency <= 3:
                        match_errors.append(
                            f"half {row.get('half')} manifest activation "
                            "receipt latency "
                            f"{latency}s is outside inclusive 0..3s policy"
                        )
    streams: dict[str, dict[str, int]] = {}
    for half in sorted(observed):
        rows = [row for row in health if int(row.get("half") or 0) == half]
        types = [str(row.get("event_type") or "") for row in rows]
        observed_types = set(types)
        missing = expected_types - observed_types
        unknown = observed_types - expected_types - set(CAPTURE_EVENT_TYPES_OPTIONAL)
        for event_type in sorted(missing):
            # A dark stream is that stream's own failure, and its reason is
            # rendered to operators -- so it must not name its siblings.
            stream_error(
                event_type,
                f"half {half} is missing the {event_type} health type")
        if unknown:
            # Unattributable to any contracted stream: a producer/daemon
            # disagreement puts every stream's counters in doubt.
            match_errors.append(
                f"half {half} carries unknown health type(s) {sorted(unknown)}")
        for event_type in sorted(
            name for name in observed_types if types.count(name) > 1
        ):
            stream_error(event_type, f"half {half} repeats a health type")
        shortfall_by_type: dict[str, int] = {}
        for row in rows:
            event_type = str(row.get("event_type") or "")
            counters = {
                key: int(row.get(key) or 0) for key in (
                    "attempted", "enqueued", "dropped", "emitted",
                    "daemon_received", "daemon_accepted", "daemon_rejected",
                    "correlation_failure_count", "sequence_gap_count",
                    "duplicate_or_reordered_count",
                )
            }
            shortfall_by_type.setdefault(
                event_type,
                max(0, counters["emitted"] - counters["daemon_received"]))
            if (
                min(counters.values()) < 0
                or counters["attempted"] != counters["enqueued"] + counters["dropped"]
                or counters["enqueued"] != counters["emitted"]
                or counters["emitted"] != counters["daemon_received"]
                or counters["daemon_accepted"] + counters["daemon_rejected"]
                    != counters["daemon_received"]
                or any(counters[key] for key in (
                    "dropped", "daemon_rejected", "correlation_failure_count",
                ))
            ):
                stream_error(
                    event_type,
                    f"half {half} {event_type or '<empty>'} counters do not reconcile")
            stream = streams.setdefault(event_type, {
                "attempted": 0, "enqueued": 0, "emitted": 0,
                "received": 0, "accepted": 0,
            })
            for target, source in (
                ("attempted", "attempted"), ("enqueued", "enqueued"),
                ("emitted", "emitted"), ("received", "daemon_received"),
                ("accepted", "daemon_accepted"),
            ):
                stream[target] += counters[source]
        # A repeated or unknown type means the half's rows cannot be trusted to
        # account for its gaps, so credit nothing and let the residual stand.
        match_errors += _half_sequence_errors(
            half, rows,
            0 if unknown or len(types) != len(observed_types)
            else sum(shortfall_by_type.values()))
    match_ok = not match_errors and bool(observed)
    # Every contracted stream gets a verdict, plus any optional stream the
    # producer actually emitted. An unknown type is already a match error, so
    # it never reaches here as an authorized stream.
    reported = sorted(
        expected_types
        | {name for name in CAPTURE_EVENT_TYPES_OPTIONAL if name in streams}
    )
    stream_authorization = {}
    for name in reported:
        own = stream_errors.get(name, [])
        stream_authorization[name] = {
            "authorized": match_ok and not own,
            "status": "authorized" if match_ok and not own else "withheld",
            # A broken match precondition outranks the stream's own state:
            # its counters describe halves that cannot be trusted either way.
            "scope": None if match_ok and not own else
                     "match" if not match_ok else "stream",
            "errors": (match_errors + own) if not match_ok else own,
        }
    errors = match_errors + [
        error for name in sorted(stream_errors) for error in stream_errors[name]
    ]
    authorized = match_ok and not stream_errors
    return {
        "status": "authorized" if authorized else "invalid",
        "authorized": authorized,
        "observed_halves": sorted(observed),
        "manifest_halves": sorted(set(manifest_halves)),
        "health_halves": sorted(health_halves),
        "streams": streams,
        "errors": errors,
        "match_errors": match_errors,
        "stream_authorization": stream_authorization,
        "authorized_streams": sorted(
            name for name, entry in stream_authorization.items()
            if entry["authorized"]
        ),
    }


def evaluate_position_provenance(
    observed_halves: set[int],
    manifests: list[dict[str, Any]],
    health: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    *,
    require_activation: bool = False,
) -> dict[str, Any]:
    """Fail-closed aggregate evidence for schema-23 position provenance."""
    capture = evaluate_capture_authorization(
        observed_halves, manifests, health,
        require_activation=require_activation,
    )
    # Position provenance rides on the position stream, not on its siblings:
    # a frag correlation failure is not evidence about position capture.
    position_authorized = capture_stream_authorized(capture, "position")
    position_entry = (capture.get("stream_authorization") or {}).get("position") or {}
    errors = list(position_entry.get("errors") or [])
    observed = {int(half) for half in observed_halves if int(half) > 0}
    manifest_by_half: dict[int, dict[str, Any]] = {}
    revisions: set[str] = set()
    for row in manifests:
        half = int(row.get("half") or 0)
        capabilities = {
            item.strip() for item in str(row.get("capabilities") or "").split(",")
            if item.strip()
        }
        revision = str(row.get("map_revision_sha256") or "")
        if (
            # 24 added 2026-09-10, same reasoning as evaluate_capture_authorization
            # above: schema 24 carries the same position_state/map_revision
            # contract schema 23 does, so "!= 23" would reject a schema-24
            # manifest's position provenance outright.
            int(row.get("schema_version") or 0) not in {23, 24}
            or not {"position_state", "map_revision"}.issubset(capabilities)
            or str(row.get("map_revision_algorithm") or "") != "sha256"
            or re.fullmatch(r"[0-9a-f]{64}", revision) is None
        ):
            errors.append(f"half {half} manifest lacks schema-23 position provenance")
            continue
        manifest_by_half[half] = row
        revisions.add(revision)
    if set(manifest_by_half) != observed:
        errors.append("schema-23 position manifest halves do not equal observed halves")
    if len(revisions) != 1:
        errors.append("captured BSP revision is not one consistent SHA-256")

    invalid_state = revision_mismatches = invalid_half = 0
    rows_by_half: dict[int, int] = {half: 0 for half in observed}
    for row in positions:
        half = int(row.get("half") or 0)
        rows_by_half[half] = rows_by_half.get(half, 0) + 1
        if half not in observed:
            invalid_half += 1
        alive, spectator = row.get("is_alive"), row.get("is_spectator")
        if (
            alive is None or spectator is None
            or str(alive) != "1" or str(spectator) != "0"
        ):
            invalid_state += 1
        manifest_revision = str((manifest_by_half.get(half) or {}).get(
            "map_revision_sha256") or "")
        if (
            re.fullmatch(r"[0-9a-f]{64}", str(row.get("map_revision_sha256") or ""))
            is None
            or str(row.get("map_revision_sha256") or "") != manifest_revision
        ):
            revision_mismatches += 1
    missing_position_halves = sorted(half for half in observed if not rows_by_half.get(half))
    health_accepted_by_half = {
        half: sum(
            int(row.get("daemon_accepted") or 0) for row in health
            if int(row.get("half") or 0) == half
            and str(row.get("event_type") or "") == "position"
        )
        for half in observed
    }
    persistence_mismatch_halves = sorted(
        half for half in observed
        if rows_by_half.get(half, 0) != health_accepted_by_half.get(half, 0)
    )
    if not positions:
        errors.append("no position rows carry schema-23 provenance")
    if missing_position_halves:
        errors.append("position provenance is absent for one or more observed halves")
    if invalid_half:
        errors.append("position rows include invalid match halves")
    if invalid_state:
        errors.append("position rows include non-alive or spectator state")
    if revision_mismatches:
        errors.append("position row revision does not match its manifest")
    if persistence_mismatch_halves:
        errors.append("persisted position rows do not reconcile with accepted health counters")

    authorized = position_authorized and not errors and bool(observed)
    return {
        "status": "authorized" if authorized else "not_captured" if not manifests else "invalid",
        "authorized": authorized,
        "schema_version": 23,
        "observed_halves": sorted(observed),
        "rows": len(positions),
        "rows_by_half": {str(key): rows_by_half[key] for key in sorted(rows_by_half)},
        "health_accepted": sum(health_accepted_by_half.values()),
        "health_accepted_by_half": {
            str(key): health_accepted_by_half[key] for key in sorted(health_accepted_by_half)
        },
        "persistence_mismatch_halves": persistence_mismatch_halves,
        "invalid_state_rows": invalid_state,
        "revision_mismatch_rows": revision_mismatches,
        "invalid_half_rows": invalid_half,
        "map_revision_algorithm": "sha256" if len(revisions) == 1 else None,
        "captured_bsp_sha256": next(iter(revisions)) if len(revisions) == 1 else None,
        "errors": errors,
    }


def match_capture_authorization(
    db: EphemeralMysql, match_id: str, *, capture_tables_available: bool,
) -> dict[str, Any]:
    literal = sql_literal(match_id)
    observed = {
        int(row["half"]) for row in tsv_rows(db.sql(
            f"SELECT DISTINCT half FROM ktp_matches WHERE match_id={literal} "
            "AND half>0 ORDER BY half"
        ))
    }
    if not capture_tables_available:
        return evaluate_capture_authorization(observed, [], [])
    manifests = tsv_rows(db.sql(f"""
SELECT cm.half, cm.schema_version, cm.capabilities, cm.position_interval,
       cm.event_epoch AS producer_activation_epoch,
       UNIX_TIMESTAMP(cm.created_at) AS activation_receipt_epoch,
       UNIX_TIMESTAMP(m.start_time) AS match_start_epoch
FROM ktp_capture_manifests cm
LEFT JOIN ktp_matches m
  ON BINARY m.match_id=BINARY cm.match_id AND m.half=cm.half
WHERE BINARY cm.match_id=BINARY {literal}
ORDER BY cm.half, cm.id
"""))
    health = tsv_rows(db.sql(f"""
SELECT half, event_type, attempted, enqueued, dropped, emitted,
       daemon_received, daemon_accepted, daemon_rejected,
       correlation_failure_count, sequence_gap_count,
       duplicate_or_reordered_count
FROM ktp_capture_health WHERE BINARY match_id=BINARY {literal}
ORDER BY half, event_type
"""))
    return evaluate_capture_authorization(
        observed, manifests, health, require_activation=True
    )


def install_legacy_compatibility(db: EphemeralMysql) -> None:
    """Install empty optional tables only in the caller's ephemeral database."""
    compatibility = REPO / "sql" / "compatibility" / "legacy_optional_sources.sql"
    db.sql(compatibility.read_text(encoding="utf-8"))


def check(level: str, code: str, message: str, **evidence: Any) -> dict[str, Any]:
    return {"level": level, "code": code, "message": message, "evidence": evidence}


# Statsme may carry more frags than the match if a match_id was reused; outside
# this band its damage describes more than this match and cannot be published.
LEGACY_DAMAGE_COVERAGE_TOLERANCE = 0.15


def resolve_legacy_damage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the legacy damage source for one match, or refuse to pick.

    `ktp_match_stats` half=0 is a derived sum of the two half rows, so a fault in
    either lands in it with nothing to flag it -- and one did: half=1 damage is
    booked twice on every match from 2026-03-11 to 2026-03-18, per player at
    exactly 2.000x, while kills stay correct. Statsme is the reference, but only
    where its own frag count says its rows cover this match and no other.

    Returns per-player damage (None where it cannot be known) plus the verdict,
    which is reported as a quality check rather than applied silently.
    """
    cache_damage = sum(r.get("legacy_damage_dealt") or 0 for r in rows)
    cache_kills = sum(r.get("legacy_kills") or 0 for r in rows)
    statsme_rows = [r for r in rows if r.get("statsme_damage_dealt") is not None]
    statsme_damage = sum(r["statsme_damage_dealt"] for r in statsme_rows)
    statsme_frags = sum(r.get("statsme_frags") or 0 for r in statsme_rows)

    def verdict(source: str, damage: dict[int, int | None]) -> dict[str, Any]:
        return {
            "source": source,
            "damage": damage,
            "cache_damage": cache_damage,
            "statsme_damage": statsme_damage if statsme_rows else None,
            "cache_kills": cache_kills,
            "statsme_frags": statsme_frags if statsme_rows else None,
        }

    by_cache = {r["player_id"]: r.get("legacy_damage_dealt") for r in rows}
    if not statsme_rows:
        return verdict("cache", by_cache)
    if cache_damage == statsme_damage:
        return verdict("agree", by_cache)

    lo = (1.0 - LEGACY_DAMAGE_COVERAGE_TOLERANCE) * cache_kills
    hi = (1.0 + LEGACY_DAMAGE_COVERAGE_TOLERANCE) * cache_kills
    if cache_kills <= 0 or not lo <= statsme_frags <= hi:
        # The two sources disagree and nothing says which is describing this
        # match. Absent is the only honest answer -- a number here would be a
        # claim about real players that no source supports.
        return verdict("unresolved", {r["player_id"]: None for r in rows})

    return verdict(
        "statsme",
        {r["player_id"]: r.get("statsme_damage_dealt") for r in rows},
    )


def evaluate_quality(
    match_id: str,
    match: dict[str, Any] | None,
    players: list[dict[str, Any]],
    inventory: dict[str, Any],
    sources: dict[str, bool] | None = None,
    source_mode: str = "database",
    legacy_damage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return transparent checks; never repair a source mismatch here."""
    checks: list[dict[str, Any]] = []
    sources = sources or {
        "per_hit_damage": True, "capture_credits": True, "positions": True,
        "flag_ownership": True,
        "statsme": True, "statsme2": True, "legacy_match_cache": True,
        "assists": True,
    }
    shaped = bool(MATCH_ID_RE.fullmatch(match_id))
    checks.append(check(
        "PASS" if shaped else "FAIL",
        "match_id_shape",
        "Match identifier has a recognized production or test shape."
        if shaped
        else "Match identifier is malformed; preserve it for source-data investigation.",
        match_id=match_id,
    ))
    if source_mode == "replay":
        checks.append(check(
            "WARN", "replay_timing_compressed",
            "Replay preserves event facts but not original match duration; "
            "per-minute metrics are unavailable.",
        ))
    if match is None:
        checks.append(check("FAIL", "missing_match", "No ktp_matches row exists."))
    else:
        checks.append(check(
            "PASS" if match["open_halves"] == 0 else "FAIL",
            "closed_match",
            "All recorded halves are closed." if match["open_halves"] == 0
            else "At least one recorded half has no end boundary.",
            open_halves=match["open_halves"],
        ))

    roster = inventory.get("roster_players", 0)
    distinct = inventory.get("distinct_roster_players", 0)
    checks.append(check(
        "PASS" if roster > 0 and roster == distinct == len(players) else "FAIL",
        "roster_integrity",
        "Roster keys and canonical player rows reconcile."
        if roster > 0 and roster == distinct == len(players)
        else "Roster is empty, duplicated, or does not match the player fact.",
        roster_rows=roster, distinct_players=distinct, fact_rows=len(players),
    ))

    if match_id.endswith("-TEST"):
        checks.append(check(
            "PASS" if roster == 12 else "WARN",
            "test_roster_size",
            "Synthetic match has the current 6v6 roster."
            if roster == 12 else "Synthetic fixture is not the current 12-player shape.",
            roster_players=roster, expected=12,
        ))

    invalid = inventory.get("invalid_half_frags", 0) + inventory.get("invalid_half_damage", 0)
    checks.append(check(
        "PASS" if invalid == 0 else "FAIL",
        "valid_half_tags",
        "Frag and damage events use live half tags."
        if invalid == 0 else "Some frag or damage events have half <= 0.",
        invalid_rows=invalid,
    ))

    cached_rows = inventory.get("cached_player_totals", 0)
    fact_kills = sum(p["kills"] for p in players)
    fact_deaths = sum(p["deaths"] for p in players)
    if cached_rows == 0:
        checks.append(check(
            "WARN", "aggregate_cache_missing",
            "ktp_match_stats half=0 has no rows; raw event facts remain usable.",
        ))
    else:
        matches = (fact_kills == inventory["cached_kills"]
                   and fact_deaths == inventory["cached_deaths"])
        checks.append(check(
            "PASS" if matches else "FAIL", "aggregate_reconciliation",
            "Raw frag totals reconcile with ktp_match_stats half=0."
            if matches else "Raw frag totals disagree with ktp_match_stats half=0.",
            fact_kills=fact_kills, cached_kills=inventory["cached_kills"],
            fact_deaths=fact_deaths, cached_deaths=inventory["cached_deaths"],
        ))

    dealt = sum(p.get("damage_dealt") or 0 for p in players)
    taken = sum(p.get("damage_taken") or 0 for p in players)
    if not sources["per_hit_damage"]:
        checks.append(check(
            "WARN", "damage_source_not_captured",
            "This archive predates per-hit damage; legacy aggregate damage is shown.",
        ))
        v = legacy_damage or {"source": "cache"}
        source = v.get("source")
        checks.append(check(
            "PASS" if source == "agree" else "WARN",
            "legacy_damage_source",
            {
                "agree": "ktp_match_stats and Statsme agree on legacy damage.",
                "cache": "No Statsme rows; legacy damage rests on ktp_match_stats alone.",
                "statsme": "ktp_match_stats disagrees with Statsme; Statsme is published "
                           "because its frag count corroborates its coverage.",
                "unresolved": "The two legacy damage sources disagree and neither is "
                              "corroborated; damage is absent, not zero.",
            }.get(source, "Legacy damage source is unknown."),
            **{k: val for k, val in v.items() if k != "damage"},
        ))
    elif inventory.get("damage_events", 0) == 0:
        checks.append(check("WARN", "damage_missing", "No per-hit damage rows exist."))
    else:
        checks.append(check(
            "PASS" if dealt == taken else "FAIL", "damage_balance",
            "Opponent damage dealt equals opponent damage taken."
            if dealt == taken else "Opponent damage dealt and taken do not balance.",
            damage_dealt=dealt, damage_taken=taken,
        ))

    checks.append(check(
        "PASS" if sources["assists"] else "WARN", "assist_source_coverage",
        "Assist event support is present." if sources["assists"]
        else "This archive predates the assist action; zero does not mean no assists occurred.",
    ))

    statsme_rows = inventory.get("statsme_rows", 0)
    statsme2_rows = inventory.get("statsme2_rows", 0)
    checks.append(check(
        "PASS" if statsme_rows > 0 else "WARN", "statsme_coverage",
        "Weapon shots and hits are present." if statsme_rows > 0
        else "No StatsMe weapon rows exist; accuracy is unavailable.",
        rows=statsme_rows,
    ))
    checks.append(check(
        "PASS" if statsme2_rows > 0 else "WARN", "hitbox_coverage",
        "Weapon hit-location rows are present." if statsme2_rows > 0
        else "No StatsMe2 hit-location rows exist.",
        rows=statsme2_rows,
    ))
    if statsme_rows and statsme2_rows:
        located = inventory["located_hits"]
        hits = inventory["statsme_hits"]
        checks.append(check(
            "PASS" if located <= hits else "WARN", "hitbox_reconciliation",
            "Located hits do not exceed StatsMe hits."
            if located <= hits else "Located hits exceed StatsMe hits; inspect flush semantics.",
            located_hits=located, statsme_hits=hits,
        ))

    credits = inventory.get("capture_credits", 0)
    events = inventory.get("unique_capture_events", 0)
    checks.append(check(
        "WARN" if not sources["capture_credits"] else
        ("PASS" if credits >= events else "FAIL"), "capture_grouping",
        "This archive predates dedicated capture credits; zero is unavailable."
        if not sources["capture_credits"] else
        "Capture credits group into plausible unique capture events."
        if credits >= events else "Unique capture count exceeds player credits.",
        capture_credits=credits, unique_capture_events=events,
    ))

    positions = inventory.get("position_samples", 0)
    checks.append(check(
        "PASS" if sources["positions"] and positions > 0 else "WARN",
        "aggregate_position_coverage",
        "This archive predates aggregate position samples."
        if not sources["positions"] else
        "Aggregate positional coverage is present and remains internal."
        if positions > 0 else "No position samples exist.",
        aggregate_samples=positions,
    ))

    bot_rows = sum(str(p.get("steam_id", "")).startswith("BOT:") for p in players)
    bots_allowed = match_id.endswith("-TEST") or bot_rows == 0
    checks.append(check(
        "PASS" if bots_allowed else "FAIL", "bot_containment",
        "Bot identities occur only in test data." if bots_allowed
        else "Bot identities were found in a non-test match.",
        bot_players=bot_rows,
    ))

    rank = {"PASS": 0, "WARN": 1, "FAIL": 2}
    status = max((c["level"] for c in checks), key=rank.get, default="FAIL")
    return {"status": status, "checks": checks}


WAVE_PLAYER_KEYS = (
    "damage_applied", "damage_capped_with_applied", "hits_with_applied",
    "life_shots", "life_shots_hitscan", "lives_fired", "first_shot_delay_avg",
    "score_events", "score_points", "score_points_placed", "score_events_unresolved",
    "grenade_throws", "grenade_bursts_matched", "grenade_flight_avg", "grenade_cooked",
)


def attach_wave_facts(
    players: list[dict[str, Any]],
    wave_rows: list[dict[str, Any]] | None,
    score_rows: list[dict[str, Any]] | None,
    throw_rows: list[dict[str, Any]] | None = None,
) -> None:
    """Add expansion wave 1/2 per-player facts to the box-score rows in place.

    Every key is present on every player so the DTO shape is stable. A missing
    source (table or column absent, stream not authorized) or a producer older
    than the wave leaves None -- never 0, which is a real value for all of
    these. Score rows are absent for a player who scored nothing, and that IS
    a zero, so score keys default to 0 only when the score source was queried.
    """
    by_id = {int(r["player_id"]): r for r in (wave_rows or [])}
    score_by_id = {int(r["player_id"]): r for r in (score_rows or [])}
    throw_by_id = {int(r["player_id"]): r for r in (throw_rows or [])}
    for player in players:
        pid = int(player["player_id"])
        wave = by_id.get(pid, {})
        score = score_by_id.get(pid)
        throw = throw_by_id.get(pid)
        for key in WAVE_PLAYER_KEYS:
            if key.startswith("score_"):
                if score_rows is None:
                    player[key] = None
                else:
                    player[key] = (score or {}).get(key, 0)
            elif key.startswith("grenade_"):
                # Same rule as score: a player with no throw row threw nothing
                # (0), but only when the throw source was queried at all.
                if throw_rows is None:
                    player[key] = None
                elif key == "grenade_flight_avg":
                    player[key] = (throw or {}).get(key)
                else:
                    player[key] = (throw or {}).get(key, 0)
            else:
                player[key] = wave.get(key)


AIM_PLAYER_KEYS = (
    "placement_shots", "placement_avg_deg", "placement_under5_pct", "placement_under15_pct",
    "ac_hits_with_geometry", "ac_err_avg_deg", "ac_range_avg", "ac_target_angvel_avg_dps",
)


def attach_aim_facts(
    players: list[dict[str, Any]],
    placement_rows: list[dict[str, Any]] | None,
    precision_rows: list[dict[str, Any]] | None,
) -> None:
    """Aim shadow facts on the box-score rows, in place. Shadow only: no rating
    impact, no publication -- infra-aim-telemetry's field map, computed.

    None everywhere a source is absent OR the player has no row: a player with
    no shots was not measured, which is not a placement of zero degrees.
    """
    placement = {int(r["player_id"]): r for r in (placement_rows or [])}
    precision = {int(r["player_id"]): r for r in (precision_rows or [])}
    for player in players:
        pid = int(player["player_id"])
        for key in AIM_PLAYER_KEYS:
            source = precision if key.startswith("ac_") else placement
            player[key] = source.get(pid, {}).get(key)


def public_players(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove individual positional coverage from shareable player records."""
    public = []
    for player in players:
        row = {key: value for key, value in player.items()
               if key != "position_samples"}
        row["team_name"] = TEAM_NAMES.get(row.get("team"), "Unknown")
        public.append(row)
    return public


def with_team_names(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    named = []
    for source in rows:
        row = dict(source)
        row["team_name"] = TEAM_NAMES.get(row.get("team"), "Unknown")
        named.append(row)
    return named


def objective_attempt_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise factual attempt rows without inventing a missing boundary."""
    attempts: dict[tuple[int, int, int], set[str]] = {}
    for row in rows:
        key = (int(row["server_id"]), int(row["half"]), int(row["attempt_id"]))
        attempts.setdefault(key, set()).add(str(row["event_kind"]))
    values = list(attempts.values())
    return {
        "status": "available",
        "events": len(rows),
        "attempts": len(values),
        "starts": sum("start" in kinds for kinds in values),
        "completes": sum("complete" in kinds for kinds in values),
        "stops": sum("stop" in kinds for kinds in values),
        "orphan_terminals": sum(
            "start" not in kinds and bool(kinds & {"complete", "stop"})
            for kinds in values
        ),
        "open_attempts": sum(
            "start" in kinds and not bool(kinds & {"complete", "stop"})
            for kinds in values
        ),
        "stop_reasons": {
            reason: sum(
                row.get("event_kind") == "stop" and row.get("stop_reason") == reason
                for row in rows
            )
            for reason in ("capture_stopped", "context_reset")
        },
    }


def grenade_entity_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise entity observations; removal is not a detonation claim."""
    entities: dict[tuple[int, int, int, int], set[str]] = {}
    for row in rows:
        key = (
            int(row["server_id"]), int(row["half"]),
            int(row["entindex"]), int(row["serial"]),
        )
        entities.setdefault(key, set()).add(str(row["entity_kind"]))
    values = list(entities.values())
    return {
        "status": "available",
        "semantics": "entity_tracked_removed_only",
        "events": len(rows),
        "entities": len(values),
        "tracked": sum("tracked" in kinds for kinds in values),
        "removed": sum("removed" in kinds for kinds in values),
        "complete_lifecycles": sum(kinds == {"tracked", "removed"} for kinds in values),
        "incomplete_tracked": sum(kinds == {"tracked"} for kinds in values),
        "left_censored_removed": sum(kinds == {"removed"} for kinds in values),
        "allowed_weapon_ids_only": all(
            GRENADE_WEAPON_TYPES.get(int(row.get("weapon_id") or 0))
            == row.get("weapon_type") for row in rows
        ),
    }


def lifecycle_block(
    capture: dict[str, Any],
    event_type: str,
    summarise: Any,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """A stream's lifecycle summary, or a withheld marker that says why.

    A withheld stream must stay visible with its reason; the silent absence is
    the defect per-stream authorization exists to fix.
    """
    state = capture_stream_status(capture, event_type)
    if state["authorized"]:
        return summarise(rows)
    return {
        "status": state["status"],
        "stream": event_type,
        "withheld_reason": state["reason"],
    }


def build_duel_matrix(
    frag_timeline: list[dict[str, Any]],
    players: list[dict[str, Any]],
) -> dict[str, Any]:
    """Player-vs-player kill grid from the stock frag timeline.

    Descriptive only. Rows are ordered by team then name so the rendered
    grid groups teammates; enemy and team kills are both counted (the cell
    carries whether the pairing crosses teams) so the grid reconciles with
    the box score's kills column exactly.
    """
    order = sorted(
        players,
        key=lambda p: (p.get("team") or 0, str(p.get("player_name_at_match"))),
    )
    ids = [int(p["player_id"]) for p in order]
    names = {int(p["player_id"]): p.get("player_name_at_match") for p in order}
    teams = {int(p["player_id"]): p.get("team") for p in order}
    counts: dict[tuple[int, int], int] = {}
    unmatched = 0
    for frag in frag_timeline:
        killer = frag.get("killer_id")
        victim = frag.get("victim_id")
        if killer is None or victim is None or int(killer) not in names \
                or int(victim) not in names:
            unmatched += 1
            continue
        counts[(int(killer), int(victim))] = counts.get(
            (int(killer), int(victim)), 0) + 1
    cells = [
        {
            "killer_id": killer, "killer_name": names[killer],
            "victim_id": victim, "victim_name": names[victim],
            "kills": kills,
            "cross_team": teams[killer] != teams[victim],
        }
        for (killer, victim), kills in sorted(counts.items())
    ]
    return {
        "definition": "duel_matrix_v1",
        "player_order": ids,
        "cells": cells,
        "frags_outside_roster": unmatched,
    }


def duel_matrix_markdown(matrix: dict[str, Any],
                         players: list[dict[str, Any]]) -> str:
    """Killer-by-victim grid; rows kill columns."""
    order = matrix.get("player_order") or []
    if not order or not matrix.get("cells"):
        return "_No rows._\n"
    names = {int(p["player_id"]): str(p.get("player_name_at_match"))
             for p in players}
    lookup = {(cell["killer_id"], cell["victim_id"]): cell["kills"]
              for cell in matrix["cells"]}
    header = "| Killer \\ Victim | " + " | ".join(
        names.get(pid, str(pid)) for pid in order) + " |"
    divider = "|---" * (len(order) + 1) + "|"
    lines = [header, divider]
    for killer in order:
        row = [names.get(killer, str(killer))]
        for victim in order:
            kills = lookup.get((killer, victim), 0)
            row.append(str(kills) if kills else "·")
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines) + "\n"


def team_summary(players: list[dict[str, Any]],
                 match: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    additive = (
        "kills", "deaths", "assists", "damage_dealt", "damage_taken",
        "team_damage", "self_damage", "capture_credits", "cap_breaks",
        "shots", "hits", "grenade_kills", "grenade_damage",
        "grenade_damage_taken", "score",
    )
    teams: dict[int, dict[str, Any]] = {}
    for player in players:
        team = player.get("team")
        if team not in TEAM_NAMES:
            continue
        row = teams.setdefault(team, {
            "team": team, "team_name": TEAM_NAMES[team], "players": 0,
            **{field: 0 for field in additive},
        })
        row["players"] += 1
        for field in additive:
            row[field] += player.get(field, 0) or 0
    duration = float((match or {}).get("duration_seconds") or 0)
    for row in teams.values():
        has_taken = all(p.get("damage_taken") is not None
                        for p in players if p.get("team") == row["team"])
        if not has_taken:
            row["damage_taken"] = None
            row["grenade_damage_taken"] = None
        row["damage_differential"] = (
            row["damage_dealt"] - row["damage_taken"] if has_taken else None
        )
        row["raw_accuracy"] = (
            round(row["hits"] / row["shots"], 3) if row["shots"] else None
        )
        row["kills_per_minute"] = (
            round(row["kills"] * 60.0 / duration, 3) if duration else None
        )
        row["points_per_minute"] = (
            round(row["score"] * 60.0 / duration, 3) if duration else None
        )
    return [teams[key] for key in sorted(teams)]


def md(value: Any) -> str:
    if value is None:
        return "—"
    return str(value).replace("|", "\\|").replace("\n", " ")


def markdown_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    if not rows:
        return "_No rows._\n"
    lines = [
        "| " + " | ".join(label for _, label in columns) + " |",
        "|" + "|".join("---" for _ in columns) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(md(row.get(key)) for key, _ in columns) + " |")
    return "\n".join(lines) + "\n"


def lifecycle_line(block: dict[str, Any], counts: str) -> str:
    """Counts when the stream published; otherwise the reason it was withheld.

    Keyed on the marker `lifecycle_block` writes, not on a summariser's status
    string, so a new summariser state cannot silently render as withheld.
    """
    reason = block.get("withheld_reason")
    if reason is None:
        return counts
    if block.get("status") == "not_captured":
        return f"**Not captured** — {md(reason)}"
    return f"**Withheld** — this stream's capture did not authorize: {md(reason)}"


def wave_markdown(report: dict[str, Any]) -> list[str]:
    """Wave 1/2 box-score columns, or one line saying why they are absent."""
    players = report.get("players") or []
    have_wave1 = any(p.get("damage_applied") is not None or p.get("life_shots") is not None
                     for p in players)
    have_score = any(p.get("score_points") is not None for p in players)
    have_throws = any(p.get("grenade_throws") is not None for p in players)
    if not have_wave1 and not have_score and not have_throws:
        return ["Not available: no half of this match came from a 1.21.0+ producer "
                "(migration 032 fields are NULL, never zero, for older builds)."]
    duel_stats = report.get("duel_stats")
    return [
        markdown_table(players, [
            ("player_name_at_match", "Player"), ("team_name", "Team"),
            ("damage_dealt", "Damage"), ("damage_applied", "Applied"),
            ("life_shots", "Shots/lives"), ("life_shots_hitscan", "Hitscan"),
            ("first_shot_delay_avg", "1st shot (s)"),
            ("score_points", "Score pts"), ("score_points_placed", "Placed"),
            ("score_events_unresolved", "Unplaced ev."),
            ("grenade_throws", "Nades"), ("grenade_flight_avg", "Flight (s)"),
            ("grenade_cooked", "Cooked"),
        ]),
        "Applied = health actually removed (overkill and armour excluded); shots are "
        "per-life weapon_fire counts, independent of hit registration; 1st shot is "
        "spawn to first shot, not reaction time. Score points are the engine's own "
        "awards; placed = attributed to a resolved flag. Nades = throws (AmmoX edge); "
        "flight = throw to burst (the tracked lifecycle row); cooked = flight under 3.5 s.",
        (f"Duel stats (dodx vstats): {len(duel_stats)} attacker/victim pairs with "
         f"shots, hits, damage and hit groups in the JSON report."
         if duel_stats is not None else
         "Duel stats: not available (needs a 1.22.0 producer and migration 033)."),
    ]


def aim_markdown(report: dict[str, Any]) -> list[str]:
    players = report.get("players") or []
    if not any(p.get("placement_shots") is not None or p.get("ac_hits_with_geometry") is not None
               for p in players):
        return ["Not available: needs the shot stream (schema-24 producer) with live "
                "position samples, and/or the anti-cheat ledger (production only)."]
    return [
        markdown_table(players, [
            ("player_name_at_match", "Player"), ("team_name", "Team"),
            ("placement_shots", "Shots"), ("placement_avg_deg", "Placement avg (deg)"),
            ("placement_under5_pct", "<5 deg %"), ("placement_under15_pct", "<15 deg %"),
            ("ac_hits_with_geometry", "Hits w/ geom"), ("ac_err_avg_deg", "On-hit err (deg)"),
            ("ac_range_avg", "Range"), ("ac_target_angvel_avg_dps", "Target deg/s"),
        ]),
        "Placement is computed: angle from the view vector to the nearest-in-time "
        "(+/-1 s, 2 s cadence) alive enemy sample, minimum over enemies -- a "
        "distribution, never a per-shot verdict. On-hit error is the AC ledger's "
        "err_udeg, present only for shots that hit a hitbox. Shadow only; no rating "
        "impact.",
    ]


def render_markdown(report: dict[str, Any]) -> str:
    match = report.get("match") or {}
    quality = report["quality"]
    timelines = report.get("shadow_timelines", {})
    explorations = report.get("shadow_explorations", {})
    damage_shadow = explorations.get("damage_conversion", {})
    objective_shadow = explorations.get("objective_pressure", {})
    engagement_shadow = explorations.get("weapon_engagement", {})
    life_shadow = explorations.get("life_kat", {})
    fight_shadow = explorations.get("flag_fights", {})
    clutch_shadow = explorations.get("fight_clutches", {})
    entries_shadow = explorations.get("fight_entries", {})
    recap_shadow = explorations.get("recap_speed", {})
    swing_shadow = explorations.get("flag_swing", {})
    ktpr_shadow = explorations.get("ktpr_v2", {})
    lifecycles = report.get("telemetry_lifecycles", {})
    objective_attempts = lifecycles.get("objective_attempts", {})
    grenade_entities = lifecycles.get("grenade_entities", {})
    trade_analysis = timelines.get("trade_analysis", {})
    revenge_analysis = timelines.get("revenge_analysis", {})
    out = [
        f"# Match analytics — {report['match_id']}", "",
        f"Quality: **{quality['status']}**", "",
        f"Source mode: `{report.get('source_mode', 'database')}`  ",
        f"Temporal metrics valid: "
        f"{'yes' if report.get('temporal_metrics_valid', True) else 'no'}  ",
        f"Map: `{md(match.get('map_name'))}`  ",
        f"Halves: {md(match.get('halves_played'))}  ",
        f"Live duration: {md(match.get('duration_seconds'))} seconds  ",
        "", "## Source coverage", "",
        "| Source | Captured |", "|---|---|",
    ]
    for source, captured in report.get("source_coverage", {}).items():
        out.append(f"| `{source}` | {'yes' if captured else 'no'} |")
    out += [
        "", "Uncaptured sources are reported as unavailable, not as observed zeroes. "
        "For legacy archives, Damage comes from `ktp_match_stats` or Statsme, whichever the "
        "`legacy_damage_source` check names; damage taken and +/- remain unavailable.",
        "", "## Team summary", "",
        markdown_table(report["teams"], [
            ("team_name", "Team"), ("kills", "K"), ("deaths", "D"),
            ("assists", "Assists"), ("damage_dealt", "Damage"),
            ("damage_taken", "Taken"), ("damage_differential", "+/-"),
            ("capture_credits", "Caps"), ("cap_breaks", "Breaks"),
            ("raw_accuracy", "Raw acc."),
        ]),
        "", "## Box score", "",
        markdown_table(report["players"], [
            ("player_name_at_match", "Player"), ("team_name", "Team"),
            ("kills", "K"), ("deaths", "D"), ("assists", "Assists"),
            ("kd_ratio", "K/D"), ("damage_dealt", "Damage"),
            ("damage_taken", "Taken"), ("damage_differential", "+/-"),
            ("headshots", "HS"), ("capture_credits", "Caps"),
            ("cap_breaks", "Breaks"), ("raw_accuracy", "Raw acc."),
            ("damage_per_minute", "Dmg/min"),
            ("damage_per_life", "Dmg/life"),
            ("grenade_kills", "Nade K"),
            ("grenade_damage", "Nade dmg"),
            ("fast_2k", "2k"), ("fast_3k", "3k"), ("fast_4k_plus", "4k+"),
            ("best_streak", "Streak"),
        ]),
        "Raw accuracy is descriptive by weapon and is not suitable for player "
        "ranking; Garand chamber-clearing shots are not distinguishable from misses.",
        "", "## Duel matrix", "",
        duel_matrix_markdown(report.get("duel_matrix", {}), report["players"]),
        "Rows kill columns; team kills are included so the grid reconciles "
        "with the box score exactly.",
        "", "## Producer waves 1-2", "",
        *wave_markdown(report),
        "", "## Aim (shadow)", "",
        *aim_markdown(report),
        "", "## Assists", "",
        markdown_table(report["assists"], [
            ("player_name_at_match", "Assister"), ("team_name", "Team"),
            ("victim_name_at_match", "Assisted against"),
            ("assists", "Assists"),
        ]),
        "Assist weapon is not reported because the assist event does not carry "
        "one; nearby damage is not treated as a safe substitute.",
        "", "## Private shadow timelines", "",
        f"Status: `{timelines.get('status', 'not_collected')}`  ",
        "Exploratory only: no database writes, public API output, or rating impact.",
        "",
        markdown_table(timelines.get("opening_duels", []), [
            ("half", "Half"), ("event_time", "Opening time"),
            ("weapon", "Weapon"), ("headshot", "Headshot"),
        ]),
        f"Fast multikills: {len(timelines.get('fast_multikills', []))}  ",
        f"Basic trades: {len(timelines.get('trades', []))}  ",
        f"Deaths traded: {md(trade_analysis.get('deaths_traded'))}  ",
        f"Team-death response denominator: "
        f"{md(trade_analysis.get('team_death_response_opportunities'))}  ",
        f"Basic trade team-death response rate: "
        f"{md(trade_analysis.get('team_death_response_rate'))}  ",
        f"Revenge status: `{revenge_analysis.get('status', 'not_collected')}`  ",
        f"Revenge responses: {md(revenge_analysis.get('revenge_events'))}  ",
        f"Head-to-head pairs: {len(timelines.get('head_to_head', []))}",
        "The trade denominator is every opposing-team death suffered, not proof "
        "that a specific teammate was alive, nearby, or had line of sight.",
        "", "## Private FPS explorations", "",
        "Aggregate exploratory output only. No database/site writes and no rating effect.",
        "", "### Damage conversion", "",
        f"Status: `{damage_shadow.get('status', 'not_collected')}`  ",
        f"Definition: `{damage_shadow.get('definition', 'unavailable')}`", "",
        markdown_table(damage_shadow.get("players", []), [
            ("name", "Player"), ("team", "Team"),
            ("damage_total", "Damage"),
            ("damage_to_own_kill", "Own kill"),
            ("damage_to_credited_assist", "Assist"),
            ("damage_to_teammate_finish", "Team finish"),
            ("unconverted_damage", "Unconverted"),
            ("outcome_linked_share", "Linked share"),
            ("team_damage_share", "Team share"),
        ]),
        "Damage links are time associations, not causal claims.",
        "", "### Sampled objective pressure", "",
        f"Status: `{objective_shadow.get('status', 'not_collected')}`  ",
        f"Confidence: `{objective_shadow.get('confidence', {}).get('level', 'unavailable')}`",
        "",
        markdown_table(objective_shadow.get("players", []), [
            ("player_name_at_match", "Player"),
            ("eligible_samples", "Samples"),
            ("near_objective_seconds", "Near sec."),
            ("enemy_owned_pressure_seconds", "Enemy sec."),
            ("friendly_owned_proximity_seconds", "Friendly sec."),
            ("neutral_proximity_seconds", "Neutral sec."),
            ("sampled_contest_seconds", "Contest sec."),
        ]),
        "Seconds are sample-count estimates for alive players, not exact capture-volume time.",
        "", "### Weapon kill-time player separation", "",
        f"Status: `{engagement_shadow.get('status', 'not_collected')}`  ",
        f"Confidence: `{engagement_shadow.get('confidence', {}).get('level', 'unavailable')}`",
        "",
        markdown_table(engagement_shadow.get("weapon_profiles", []), [
            ("weapon", "Weapon"), ("kills_observed", "Kills"),
            ("separation_eligible_kills", "Endpoint rows"),
            ("mean_kill_time_separation_units", "Mean units"),
            ("median_kill_time_separation_units", "Median units"),
            ("headshot_rate", "HS rate"),
            ("scoped_kill_rate", "Scoped rate"),
            ("prone_kill_rate", "Prone rate"),
            ("profile_confidence", "Confidence"),
        ]),
        "Separation uses killer and victim positions at the kill event. It does "
        "not establish firing origin, line of sight, or general weapon effectiveness; "
        "delayed grenade/projectile kills need particular caution.",
        "", "### DoD-native KAT coverage", "",
        f"Status: `{life_shadow.get('status', 'not_collected')}`  ",
        f"Confidence: `{life_shadow.get('confidence', {}).get('level', 'unavailable')}`  ",
        f"Eligible death-ended lives: "
        f"{md(life_shadow.get('aggregate', {}).get('eligible_lives'))}  ",
        f"Covered lives: {md(life_shadow.get('aggregate', {}).get('covered_lives'))}  ",
        f"KAT coverage: {md(life_shadow.get('aggregate', {}).get('kat_coverage'))}",
        "KAT means kill, assist, or death traded in a completed physical life. "
        "Disconnect, open, and ambiguous lives are censored; no round-survival "
        "term is invented for continuous-respawn DoD.",
        "", "### Flag fights", "",
        f"Status: `{fight_shadow.get('status', 'not_collected')}`  ",
        f"Fight windows: {md(fight_shadow.get('summary', {}).get('fight_windows'))}  ",
        f"Captures / stops: {md(fight_shadow.get('summary', {}).get('captures'))} / "
        f"{md(fight_shadow.get('summary', {}).get('stops'))}  ",
        f"Openings observed: {md(fight_shadow.get('summary', {}).get('openings_observed'))}",
        "",
        markdown_table(fight_shadow.get("players", []), [
            ("player_id", "Player id"), ("fights", "Fights"),
            ("kills", "K"), ("deaths", "D"), ("assists", "A-fights"),
            ("openings_won", "Open +"), ("openings_lost", "Open -"),
            ("deaths_traded", "Traded"), ("kast_f", "KAST-F"),
        ]),
        "A fight is one objective-attempt window (producer clock, padded). "
        "KAST-F counts fights with a kill, assist, survival, or traded death; "
        "overlapping windows may count one event in each.",
        "", "### Fight clutches", "",
        f"Status: `{clutch_shadow.get('status', 'not_collected')}`  ",
        f"Evaluated / censored windows: "
        f"{md(clutch_shadow.get('evaluated_windows'))} / "
        f"{md(clutch_shadow.get('censored_windows'))}",
        "",
        markdown_table(clutch_shadow.get("clutches", []), [
            ("half", "Half"), ("flag_name", "Flag"), ("player_id", "Player id"),
            ("against", "1 v"), ("kind", "Converted"),
        ]),
        "A clutch is the winning side's lone survivor at window close against "
        "two or more living enemies; windows with unknown liveness are "
        "censored, never guessed.",
        "", "### Fight entries", "",
        f"Status: `{entries_shadow.get('status', 'not_collected')}`  ",
        f"Windows with / without entry: "
        f"{md(entries_shadow.get('windows_with_entry'))} / "
        f"{md(entries_shadow.get('windows_without_entry'))}",
        "",
        markdown_table(entries_shadow.get("players", []), [
            ("player_id", "Player id"), ("entries", "Entries"),
            ("survived", "Survived"), ("survival_rate", "Survival"),
        ]),
        "An entry is the first alive capturing-team position sample inside "
        "the entry radius during the padded window — sample-rate precision. "
        "Point time lives in the objective-pressure section: near-objective "
        "seconds split by owner (enemy-owned = attack, friendly = defense).",
        "", "### Recap speed", "",
        f"Status: `{recap_shadow.get('status', 'not_collected')}`  ",
        f"Censored open losses: {md(recap_shadow.get('censored_open_losses'))}",
        "",
        markdown_table(recap_shadow.get("teams", []), [
            ("team", "Team"), ("recaps", "Recaps"),
            ("median_seconds", "Median s"), ("mean_seconds", "Mean s"),
        ]),
        "", "### Cap participation", "",
        markdown_table(report.get("cap_participation", []), [
            ("player_name_at_match", "Player"), ("team_name", "Team"),
            ("caps_participated", "Caps in"), ("team_caps", "Team caps"),
            ("cap_participation", "Share"),
        ]),
        "Credited participation only; on-point presence without credit needs "
        "zone-occupancy telemetry and is not approximated.",
        "", "### Flag swing (uncalibrated)", "",
        f"Status: `{swing_shadow.get('status', 'not_collected')}`  ",
        f"Calibration: `{swing_shadow.get('calibration', 'unavailable')}`  ",
        f"Timeline points: {len(swing_shadow.get('timeline', []))}",
        "",
        markdown_table(swing_shadow.get("players", []), [
            ("player_id", "Player id"), ("team", "Team"),
            ("attributed_swing", "Swing"),
            ("weighted_frags", "Weighted frags"),
        ]),
        "Swing prices each flag change and frag as the change in a baseline "
        "P(win half); coefficients are uncalibrated priors, so magnitudes "
        "compare within this match only.",
        "", "### KTPR v2 shadow blend (uncalibrated)", "",
        f"Status: `{ktpr_shadow.get('status', 'not_collected')}`  ",
        f"Components: {md(', '.join(ktpr_shadow.get('components_used', [])))}",
        "",
        markdown_table(ktpr_shadow.get("players", []), [
            ("player_name_at_match", "Player"), ("team", "Team"),
            ("rating", "Rating"),
        ]),
        "Per-match z-score blend with prior weights; no ranking consequences "
        "until the comparison review against historical KTPR signs off.",
        "", "## Weapon facts", "",
        markdown_table(report["weapons"], [
            ("player_name_at_match", "Player"), ("weapon", "Weapon"),
            ("kills", "K"), ("damage_dealt", "Damage"), ("shots", "Shots"),
            ("hits", "Hits"), ("raw_accuracy", "Raw acc."),
            ("head_hits", "Head"), ("chest_hits", "Chest"),
            ("stomach_hits", "Stomach"), ("arm_hits", "Arms"),
            ("leg_hits", "Legs"),
        ]),
        "", "## Capture credits", "",
        markdown_table(report["capture_credits"], [
            ("player_name_at_match", "Player"), ("team_name", "Team"),
            ("flag_name", "Flag"), ("capture_credits", "Credits"),
        ]),
        "", "## Unique capture events", "",
        markdown_table(report["capture_events"], [
            ("event_time", "Time"), ("half", "Half"), ("team_name", "Team"),
            ("flag_name", "Flag"), ("credited_players", "Credited players"),
        ]),
        "", "## Objective-attempt lifecycle", "",
        f"Status: `{objective_attempts.get('status', 'not_captured')}`  ",
        lifecycle_line(
            objective_attempts,
            f"Attempts: {md(objective_attempts.get('attempts'))}; "
            f"starts: {md(objective_attempts.get('starts'))}; "
            f"completes: {md(objective_attempts.get('completes'))}; "
            f"stops: {md(objective_attempts.get('stops'))}; "
            f"orphan terminals: {md(objective_attempts.get('orphan_terminals'))}; "
            f"open attempts: {md(objective_attempts.get('open_attempts'))}.",
        ),
        "Missing starts and terminals remain explicitly censored; the report does not invent them.",
        "", "## Grenade-entity lifecycle", "",
        f"Status: `{grenade_entities.get('status', 'not_captured')}`  ",
        lifecycle_line(
            grenade_entities,
            f"Entities: {md(grenade_entities.get('entities'))}; "
            f"tracked: {md(grenade_entities.get('tracked'))}; "
            f"removed: {md(grenade_entities.get('removed'))}; "
            f"complete: {md(grenade_entities.get('complete_lifecycles'))}; "
            f"incomplete tracked: {md(grenade_entities.get('incomplete_tracked'))}; "
            f"left-censored removed: {md(grenade_entities.get('left_censored_removed'))}.",
        ),
        "Removal is only an entity-lifecycle observation. No damage outcome is inferred.",
        "", "## Data quality", "",
        "| Result | Check | Detail |", "|---|---|---|",
    ]
    for item in quality["checks"]:
        out.append(f"| {item['level']} | `{item['code']}` | {md(item['message'])} |")
    out += [
        "", "## Positional privacy", "",
        "Raw coordinates, paths, heatmaps, timestamps, and ordered positional "
        "timelines are excluded. Private per-player objective and kill-endpoint "
        "aggregates may be reviewed, but are not public or rating inputs.",
        "",
    ]
    return "\n".join(out)


def build_report(
    db: EphemeralMysql,
    match_id: str,
    fixture: Path,
    sources: dict[str, bool] | None = None,
    source_mode: str = "database",
    timeline_config: TimelineConfig | None = None,
    damage_config: DamageConversionConfig | None = None,
    objective_config: ObjectivePressureConfig | None = None,
    engagement_config: EngagementDistanceConfig | None = None,
    life_config: LifeExplorationConfig | None = None,
    positional_config: PositionalConfig | None = None,
    spatial_config: SpatialLayersConfig | None = None,
    observer_root: Path | None = None,
) -> dict[str, Any]:
    sources = sources or source_capabilities(db)
    capture_authorization = match_capture_authorization(
        db, match_id,
        capture_tables_available=bool(sources.get("capture_health", False)),
    )
    sources = dict(sources)
    sources["objective_attempts"] = bool(
        sources.get("objective_attempts")
        and capture_stream_authorized(capture_authorization, "objective_attempt")
    )
    sources["grenade_entities"] = bool(
        sources.get("grenade_entities")
        and capture_stream_authorized(capture_authorization, "grenade_entity")
    )
    match_rows = query_rows(db, "match_fact.sql", match_id)
    players = query_rows(db, "player_match_fact.sql", match_id)
    weapons = query_rows(db, "weapon_fact.sql", match_id)
    assists = (query_rows(db, "assist_fact.sql", match_id)
               if sources is None or sources.get("assists", True) else [])
    credits = (query_rows(db, "capture_credit_fact.sql", match_id)
               if sources is None or sources.get("capture_credits", True) else [])
    events = (query_rows(db, "capture_event_fact.sql", match_id)
              if sources is None or sources.get("capture_credits", True) else [])
    frag_timeline = query_rows(db, "frag_timeline_fact.sql", match_id)
    objective_timeline = (query_rows(db, "objective_timeline_fact.sql", match_id)
                          if sources is None or sources.get("capture_credits", True)
                          else [])
    damage_timeline = (
        query_rows(db, "damage_timeline_fact.sql", match_id)
        if (
            sources.get("per_hit_damage", False)
            and sources.get("damage_event_clock", False)
        ) else None
    )
    assist_timeline = (query_rows(db, "assist_timeline_fact.sql", match_id)
                       if sources.get("assist_context", False) else None)
    cap_break_timeline = (query_rows(db, "cap_break_fact.sql", match_id)
                          if sources.get("break_event_clock", False) else None)
    frag_context = (
        query_rows(db, "frag_context_fact.sql", match_id)
        if (
            sources.get("frag_context", False)
            and sources.get("frag_event_clock", False)
        ) else None
    )
    # Archives predating migration 025 lack is_alive; select via the legacy
    # query there so the canonical one can name the column.
    position_timeline = (
        query_rows(
            db,
            ("position_sample_fact.sql"
             if sources.get("position_liveness", False)
             else "position_sample_fact_legacy.sql"),
            match_id,
        )
        if sources.get("positions", False) else [])
    flag_positions = (query_rows(db, "flag_position_fact.sql", match_id)
                      if sources.get("flag_positions", False) else [])
    flag_states = (query_rows(db, "flag_state_timeline_fact.sql", match_id)
                   if sources.get("flag_ownership", False) else [])
    life_boundaries = (query_rows(db, "life_boundary_fact.sql", match_id)
                       if sources.get("life_boundaries", False) else None)
    # The roster's team is the side held in the LAST half a player appeared
    # in, so anyone who leaves at the break is filed on the opponent (sides
    # swap). Correct it from the per-half life feed before anything rolls
    # players up by team.
    players = apply_canonical_teams(players, life_boundaries)
    objective_attempts = (
        query_rows(db, "objective_attempt_timeline_fact.sql", match_id)
        if sources.get("objective_attempts", False) else []
    )
    grenade_entities = (
        query_rows(db, "grenade_entity_timeline_fact.sql", match_id)
        if sources.get("grenade_entities", False) else []
    )
    # Expansion waves 1/2. Column presence says the schema can carry them; the
    # per-stream manifest verdict says a producer actually declared them.
    wave_players = (query_rows(db, "wave_player_fact.sql", match_id)
                    if sources.get("wave1_fields", False) else None)
    score_players = (
        query_rows(db, "score_player_fact.sql", match_id)
        if sources.get("score_events", False)
        and capture_stream_authorized(capture_authorization, "score") else None)
    duel_stats = (
        query_rows(db, "duel_stats_fact.sql", match_id)
        if sources.get("duel_stats", False)
        and capture_stream_authorized(capture_authorization, "duel") else None)
    grenade_throws = (
        query_rows(db, "grenade_throw_fact.sql", match_id)
        if sources.get("grenade_throws", False)
        and capture_stream_authorized(capture_authorization, "grenade_throw") else None)
    attach_wave_facts(players, wave_players, score_players, grenade_throws)
    # Aim shadow (infra-aim-telemetry field map). Placement needs the shot
    # stream and live position samples; precision reads the AC ledger directly
    # and is absent on any database that is not production.
    placement = (
        query_rows(db, "shot_placement_fact.sql", match_id)
        if sources.get("shot_events", False)
        and sources.get("positions", False)
        and sources.get("position_liveness", False)
        and capture_stream_authorized(capture_authorization, "shot") else None)
    precision = (query_rows(db, "ac_precision_fact.sql", match_id)
                 if sources.get("ac_weapon_fires", False) else None)
    attach_aim_facts(players, placement, precision)
    enriched_frag_available = bool(
        sources.get("frag_context", False)
        and sources.get("frag_event_clock", False)
        and frag_context is not None
    )
    inventory_rows = query_rows(db, "quality_inventory.sql", match_id)
    inventory = inventory_rows[0] if inventory_rows else {}
    match = match_rows[0] if match_rows else None
    legacy_damage = None
    if not sources["per_hit_damage"]:
        legacy_damage = resolve_legacy_damage(
            query_rows(db, "legacy_player_cache.sql", match_id)
        )
        cached = legacy_damage["damage"]
        duration = (match or {}).get("duration_seconds", 0) or 0
        for player in players:
            damage = cached.get(player["player_id"])
            player["damage_dealt"] = damage
            player["damage_taken"] = None
            player["damage_differential"] = None
            player["grenade_damage"] = None
            player["grenade_damage_taken"] = None
            player["damage_per_minute"] = (
                round(damage * 60.0 / duration, 2)
                if damage is not None and duration else None
            )
            deaths = player.get("deaths") or 0
            player["damage_per_life"] = (
                round(damage / deaths, 2)
                if damage is not None and deaths else None
            )
    if source_mode == "replay":
        for player in players:
            player["damage_per_minute"] = None
    quality = evaluate_quality(
        match_id, match, players, inventory, sources, source_mode,
        legacy_damage=legacy_damage,
    )
    players_public = public_players(players)
    resolved_objective_config = objective_config or ObjectivePressureConfig()
    expected_live_seconds = float((match or {}).get("duration_seconds") or 0)
    if (
        resolved_objective_config.expected_live_seconds is None
        and expected_live_seconds > 0
    ):
        resolved_objective_config = replace(
            resolved_objective_config,
            expected_live_seconds=expected_live_seconds,
        )
    objective_pressure = build_objective_pressure_shadow(
        position_timeline, flag_positions, flag_states,
        resolved_objective_config,
    )
    resolved_timeline_config = timeline_config or TimelineConfig()
    # Stock frag rows have an immediate, coherent eventTime and remain the
    # compatibility source for opening, multikill, and trade exploration.
    # Producer-context rows deliberately include malformed/legacy rows so the
    # timed analyzers can report their coverage. Feeding a NULL producer half
    # into generic grouping would either crash or silently invent half zero.
    shadow_timelines = build_shadow_timelines(
        frag_timeline, objective_timeline, resolved_timeline_config,
        temporal_valid=source_mode != "replay",
        source_available={
            "frags": True,
            "frag_event_clock": False,
            "life_boundaries": False,
        },
    )
    revenge_analysis, revenge_events = _revenge_analysis(
        frag_context or [],
        life_boundaries,
        resolved_timeline_config,
        temporal_valid=source_mode != "replay",
        frag_source_available=enriched_frag_available,
        producer_clock_available=sources.get("frag_event_clock", False),
        boundary_source_available=sources.get("life_boundaries", False),
    )
    shadow_timelines["revenge_analysis"] = revenge_analysis
    shadow_timelines["revenge_events"] = revenge_events
    # Surface fast-multikill counts on the box score. The sequences themselves
    # stay in shadow_timelines; the per-player tally is descriptive.
    multikill_counts: dict[int, dict[str, int]] = {}
    for sequence in shadow_timelines.get("fast_multikills", []):
        killer_id = int((sequence.get("killer") or {}).get("player_id") or 0)
        tally = multikill_counts.setdefault(
            killer_id, {"fast_2k": 0, "fast_3k": 0, "fast_4k_plus": 0})
        count = int(sequence.get("kill_count") or 0)
        if count == 2:
            tally["fast_2k"] += 1
        elif count == 3:
            tally["fast_3k"] += 1
        elif count >= 4:
            tally["fast_4k_plus"] += 1
    for player in players_public:
        tally = multikill_counts.get(int(player["player_id"]),
                                     {"fast_2k": 0, "fast_3k": 0, "fast_4k_plus": 0})
        player["fast_2k"] = tally["fast_2k"]
        player["fast_3k"] = tally["fast_3k"]
        player["fast_4k_plus"] = tally["fast_4k_plus"]
    life_kat = build_life_exploration(
        life_boundaries,
        frag_context,
        assist_timeline,
        shadow_timelines.get("trades", []),
        life_config,
        source_available={
            "life_boundaries": sources.get("life_boundaries", False),
            "frags": enriched_frag_available,
            "assists": sources.get("assist_context", False),
            "basic_trades": True,
        },
        temporal_valid=source_mode != "replay",
    )
    flag_fights = build_flag_fight_shadow(
        objective_attempts,
        frag_context,
        assist_timeline,
        shadow_timelines.get("trades", []),
        [p["player_id"] for p in players_public],
        source_available={
            "objective_attempts": bool(
                sources.get("objective_attempts", False)),
            "frags": enriched_frag_available,
            "assists": sources.get("assist_context", False),
            "basic_trades": True,
        },
        temporal_valid=source_mode != "replay",
    )
    fight_clutches = build_clutch_shadow(
        flag_fights.get("windows"),
        life_boundaries,
        players_public,
        source_available=bool(sources.get("life_boundaries", False)),
        temporal_valid=source_mode != "replay",
    )
    fight_entries = build_entries_shadow(
        flag_fights.get("windows"),
        position_timeline,
        flag_positions,
        life_boundaries,
        players_public,
        liveness_available=bool(sources.get("position_liveness", False)),
        source_available=bool(
            sources.get("positions", False)
            and sources.get("flag_positions", False)
            and sources.get("life_boundaries", False)),
        temporal_valid=source_mode != "replay",
    )
    recap_speed = build_recap_speed(
        flag_states if sources.get("flag_ownership", False) else None,
        source_available=bool(sources.get("flag_ownership", False)),
        temporal_valid=source_mode != "replay",
    )
    cap_participation = (
        query_rows(db, "cap_participation_fact.sql", match_id)
        if sources.get("capture_credits", True) else [])
    spawn_ownership = (load_spawn_ownership(
        DEFAULT_SPAWN_OWNERSHIP, str(match.get("map_name") or ""))
        if match else None)
    # Per-credit rows with a wall clock: the aggregated capture_events feed
    # names no player, which left every cap uncredited in flag_swing.
    credit_timeline = (
        query_rows(db, "capture_credit_timeline_fact.sql", match_id)
        if sources.get("capture_credits", True) else [])
    # DoD swaps Allies/Axis at halftime; report team 1 is the roster's
    # terminal-half slot, guaranteed opposite this in half 1 of every
    # two-half match. flag_swing/positional_shadow/progression compute in
    # raw engine side -- this is the one resolver everything below
    # translates through (scripts/report_team_convention.py).
    team1_engine_side = report_team1_engine_side(life_boundaries, players_public)
    flag_swing = build_flag_swing_shadow(
        flag_states if sources.get("flag_ownership", False) else None,
        frag_context,
        life_boundaries,
        credit_timeline,
        players_public,
        None,
        source_available=bool(
            sources.get("flag_ownership", False)
            and enriched_frag_available
            and sources.get("life_boundaries", False)),
        temporal_valid=source_mode != "replay",
        spawn_ownership=spawn_ownership,
    )
    capouts = translate_capouts(flag_swing.get("capouts") or [], team1_engine_side)
    ktpr_v2 = build_ktpr_v2_shadow(
        players_public,
        flag_fights.get("players"),
        flag_swing.get("players"),
    )
    highlight_windows = build_highlight_windows(
        flag_swing.get("timeline"),
        players_public,
        source_status=flag_swing.get("status"),
    )
    excursions = build_excursions(
        position_timeline, flag_positions, life_boundaries, flag_states,
        capture_credits=credit_timeline,
        map_name=(match or {}).get("map_name"),
        source_available=bool(
            sources.get("positions", False)
            and sources.get("life_boundaries", False)
            and source_mode != "replay"),
    )
    plays = build_plays(
        flag_swing.get("timeline"),
        players_public,
        life_boundaries,
        excursions.get("rows"),
        touches=excursions.get("touches"),
        source_status=flag_swing.get("status"),
    )
    progression = build_progression(
        frag_context,
        damage_timeline,
        flag_swing.get("timeline"),
        players_public,
        cap_break_rows=cap_break_timeline,
        # Reuse credit_timeline (already computed above for flag_swing/
        # excursions' cap credit): same producer-clocked per-credit rows,
        # no second query.
        cap_participation_rows=credit_timeline,
        spawn_ownership=spawn_ownership,
        frags_available=enriched_frag_available,
        damage_available=bool(
            sources.get("per_hit_damage", False)
            and sources.get("damage_event_clock", False)),
        flags_available=flag_swing.get("status") == "available",
        cap_breaks_available=sources.get("break_event_clock", False),
        cap_participation_available=bool(sources.get("capture_credits", True)),
        temporal_valid=source_mode != "replay",
    )
    if progression.get("teams"):
        translated_teams, undecided_halves = translate_team_series(
            progression["teams"], team1_engine_side)
        progression["teams"] = translated_teams
        if undecided_halves:
            progression["caveats"].append(
                "Half(s) " + ", ".join(str(h) for h in undecided_halves)
                + " could not be resolved to a report team and are omitted "
                  "from flag_differential rather than mislabeled.")
    if source_mode == "replay":
        objective_pressure["status"] = "timed_metrics_suppressed"
        objective_pressure["players"] = []
        objective_pressure["summary"] = {}
        objective_pressure["confidence"]["level"] = "unavailable"
        objective_pressure["caveats"].insert(
            0,
            "Replay timing is compressed; sampled objective time is unavailable.",
        )
    positional_shadow = build_positional_shadow(
        position_timeline if sources.get("positions", False) else None,
        flag_positions if sources.get("flag_positions", False) else None,
        frag_context,
        players_public,
        positional_config or PositionalConfig(),
        source_available=bool(
            sources.get("positions", False) and sources.get("flag_positions", False)),
        temporal_valid=source_mode != "replay",
    )
    translate_map_control(positional_shadow["map_control"], team1_engine_side)
    spatial_layers = build_spatial_layers(
        position_timeline if sources.get("positions", False) else None,
        flag_positions if sources.get("flag_positions", False) else None,
        frag_context,
        players_public,
        spatial_config or SpatialLayersConfig(),
        source_available=bool(sources.get("positions", False)),
        temporal_valid=source_mode != "replay",
    )
    player_halves = build_player_halves(
        query_rows(db, "player_half_fact.sql", match_id, sources)
        if sources.get("player_halves", False) else None,
        players_public,
        per_hit_damage=bool(sources.get("per_hit_damage", False)),
        temporal_valid=source_mode != "replay",
    )
    ledger_available = bool(enriched_frag_available and sources.get("life_boundaries", False))
    kill_streaks = build_kill_streaks(
        frag_context, life_boundaries, players_public,
        match_id=match_id, source_available=ledger_available,
    )
    sides = resolve_sides(life_boundaries) if sources.get("life_boundaries", False) else {}
    annotate_player_halves(player_halves, sides, best_by_player_half(kill_streaks))
    match_best = best_by_player(kill_streaks)
    for player in players_public:
        player["best_streak"] = match_best.get(int(player["player_id"]))
    duel_matrix = build_duel_matrix(frag_timeline, players_public)
    weapon_sides = build_weapon_sides(
        query_rows(db, "weapon_half_fact.sql", match_id, sources)
        if sources.get("player_halves", False) else None,
        weapons, sides,
        per_hit_damage=bool(sources.get("per_hit_damage", False)),
    )
    duels_by_side = build_duels_by_side(frag_timeline, players_public, sides, duel_matrix)
    player_classes = build_player_classes(
        frag_context, life_boundaries, players_public, sides, load_class_map(),
        match_id=match_id, source_available=ledger_available,
    )
    closed_halves = [
        (int(row["half"]), None if row["match_type"] in (None, "NULL") else int(row["match_type"]))
        for row in tsv_rows(db.sql(
            "SELECT half, match_type FROM ktp_matches "
            f"WHERE match_id={sql_literal(match_id)} AND half > 0 "
            "AND end_time IS NOT NULL ORDER BY half"))
    ]
    in_game_result = (
        load_in_game_result(observer_root, match_id,
                            map_name=(match or {}).get("map_name"),
                            closed_halves=closed_halves)
        if source_mode != "replay" else in_game_unavailable("replay-source")
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_fixture": fixture.name,
        "source_mode": source_mode,
        "temporal_metrics_valid": source_mode != "replay",
        "source_coverage": sources,
        "capture_authorization": capture_authorization,
        "match_id": match_id,
        "match": match,
        "quality": quality,
        "source_inventory": inventory,
        "teams": team_summary(players_public, match),
        "players": players_public,
        "player_halves": player_halves,
        "kill_streaks": kill_streaks,
        "weapon_sides": weapon_sides,
        "duels_by_side": duels_by_side,
        "player_classes": player_classes,
        "in_game_result": in_game_result,
        "duel_matrix": duel_matrix,
        # Wave 2 (migration 033): None until a 1.22.0 producer's half lands.
        "duel_stats": duel_stats,
        "assists": with_team_names(assists),
        "weapons": with_team_names(weapons),
        "capture_credits": with_team_names(credits),
        "cap_participation": with_team_names(cap_participation),
        "capture_events": events,
        "telemetry_lifecycles": {
            "privacy": "aggregate_public_private_timeline",
            "objective_attempts": lifecycle_block(
                capture_authorization, "objective_attempt",
                objective_attempt_summary, objective_attempts,
            ),
            "grenade_entities": lifecycle_block(
                capture_authorization, "grenade_entity",
                grenade_entity_summary, grenade_entities,
            ),
            "private_facts": {
                "objective_attempt_timeline": objective_attempts,
                "grenade_entity_timeline": grenade_entities,
            },
        },
        "shadow_timelines": shadow_timelines,
        "shadow_explorations": {
            "definition_version": 2,
            "privacy": "private_shadow_only",
            "writes": False,
            "rating_impact": False,
            "damage_conversion": build_damage_conversion(
                damage_timeline or [], frag_context or [], assist_timeline or [],
                damage_config,
                source_available={
                    "damage": (
                        sources.get("per_hit_damage", False)
                        and sources.get("damage_event_clock", False)
                    ),
                    "producer_frag_clock": enriched_frag_available,
                    "assist_context": sources.get("assist_context", False),
                    "life_boundaries": sources.get("life_boundaries", False),
                },
                life_boundaries=life_boundaries,
                temporal_valid=source_mode != "replay",
            ),
            "objective_pressure": objective_pressure,
            "flag_fights": flag_fights,
            "fight_clutches": fight_clutches,
            "fight_entries": fight_entries,
            "recap_speed": recap_speed,
            "flag_swing": flag_swing,
            "capouts": capouts,
            "ktpr_v2": ktpr_v2,
            "highlight_windows": highlight_windows,
            "excursions": excursions,
            "plays": plays,
            "progression": progression,
            "weapon_engagement": build_weapon_engagement_shadow(
                frag_context if frag_context is not None else frag_timeline,
                engagement_config,
            ),
            "life_kat": life_kat,
            "map_control": positional_shadow["map_control"],
            "depth_profiles": positional_shadow["depth_profiles"],
            "overextension": positional_shadow["overextension"],
        },
        "spatial_layers": spatial_layers,
        "positional": {
            "privacy": "aggregate_only",
            "aggregate_sample_count": inventory.get("position_samples", 0),
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="local .sql or .sql.gz fixture")
    parser.add_argument("--match-id", help="required only when a dump has multiple matches")
    parser.add_argument("--output-dir", type=Path, default=REPO / "build" / "match-analytics")
    parser.add_argument("--keep-db", action="store_true", help="keep isolated DB for debugging")
    parser.add_argument("--source-mode", choices=("database", "replay"),
                        default="database",
                        help="replay suppresses invalid time-normalized metrics")
    parser.add_argument("--multikill-seconds", type=float, default=10.0)
    parser.add_argument("--trade-seconds", type=float, default=5.0)
    parser.add_argument("--objective-conversion-seconds", type=float, default=30.0)
    parser.add_argument("--damage-conversion-seconds", type=float, default=15.0)
    parser.add_argument("--assist-grace-seconds", type=float, default=2.0)
    parser.add_argument("--position-sample-seconds", type=float, default=2.0)
    parser.add_argument("--objective-radius-units", type=float, default=512.0)
    parser.add_argument("--contest-radius-units", type=float, default=768.0)
    parser.add_argument("--simultaneous-tolerance-seconds", type=float, default=1.0)
    parser.add_argument("--minimum-objective-snapshots", type=int, default=3)
    parser.add_argument("--minimum-objective-player-samples", type=int, default=3)
    parser.add_argument("--maximum-objective-sample-gap-seconds", type=float,
                        default=15.0)
    parser.add_argument("--minimum-objective-coverage-fraction", type=float,
                        default=0.5)
    parser.add_argument("--minimum-profile-kills", type=int, default=10)
    parser.add_argument("--maximum-kill-distance-units", type=float, default=20000.0)
    parser.add_argument("--life-death-match-tolerance-seconds", type=float,
                        default=1.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    with EphemeralMysql.start(keep=args.keep_db) as db:
        load_fixture(db, args.fixture)
        sources = source_capabilities(db)
        if not all((sources["per_hit_damage"], sources["capture_credits"],
                    sources["positions"])):
            install_legacy_compatibility(db)
        match_ids = discover_match_ids(db)
        if args.match_id:
            if args.match_id not in match_ids:
                raise SystemExit(f"match {args.match_id!r} not in fixture: {match_ids}")
            match_id = args.match_id
        elif len(match_ids) == 1:
            match_id = match_ids[0]
        else:
            raise SystemExit(
                f"fixture contains {len(match_ids)} matches; pass --match-id. "
                f"Available: {match_ids}"
            )
        report = build_report(
            db, match_id, args.fixture, sources, args.source_mode,
            TimelineConfig(
                multikill_seconds=args.multikill_seconds,
                trade_seconds=args.trade_seconds,
                objective_conversion_seconds=args.objective_conversion_seconds,
            ),
            DamageConversionConfig(
                conversion_seconds=args.damage_conversion_seconds,
                assist_grace_seconds=args.assist_grace_seconds,
            ),
            ObjectivePressureConfig(
                sample_seconds=args.position_sample_seconds,
                objective_radius_units=args.objective_radius_units,
                contest_radius_units=args.contest_radius_units,
                simultaneous_tolerance_seconds=args.simultaneous_tolerance_seconds,
                minimum_distinct_snapshots=args.minimum_objective_snapshots,
                minimum_player_samples=args.minimum_objective_player_samples,
                maximum_sample_gap_seconds=(
                    args.maximum_objective_sample_gap_seconds
                ),
                minimum_expected_coverage_fraction=(
                    args.minimum_objective_coverage_fraction
                ),
            ),
            EngagementDistanceConfig(
                maximum_distance_units=args.maximum_kill_distance_units,
                minimum_profile_kills=args.minimum_profile_kills,
            ),
            LifeExplorationConfig(
                death_match_tolerance_seconds=(
                    args.life_death_match_tolerance_seconds
                ),
            ),
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / f"{match_id}.json"
    md_path = args.output_dir / f"{match_id}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"{report['quality']['status']}: {match_id}")
    print(json_path)
    print(md_path)
    return 0 if report["quality"]["status"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
