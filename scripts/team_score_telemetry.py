#!/usr/bin/env python3
"""Strict ingestion and post-match projection for official engine team scores.

The retained observer JSONL is arrival ordered.  This module validates the
producer-v1 rows, preserves their fractional ``get_gametime()`` seconds, and
lets MySQL settle them by the authoritative ``(match, half, tick, sequence)``
key.  It deliberately has no SSH, live-tail, capture-derived, player-derived,
or KTPR-derived score path.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


OFFICIAL_SOURCE = "engine-team-score-v1"
SOURCE_VERSION = 1
SETTLEMENT_SECONDS = 30
LEDGER_LOCK = "ktp_team_score_ledger_v1"
SUPPORTED_MATCH_TYPES = frozenset(range(6))
OBSERVATION_KINDS = frozenset({"baseline", "change", "final"})
MAX_JSONL_BYTES = 1 << 30
MAX_OFFICIAL_ROWS = 100_000
MAX_RAW_ROW_BYTES = 64 * 1024
MIGRATION = Path(__file__).resolve().parents[1] / "sql" / "migrate_023_team_score_observations.sql"

_DATABASE = re.compile(r"^[A-Za-z0-9_]+$")
_REQUIRED_KEYS = frozenset({
    "tick", "match_id", "map", "match_type", "half", "event",
    "allies_score", "axis_score", "allies_team_slot", "axis_team_slot",
    "event_sequence", "source", "sample_kind",
})
_OPTIONAL_KEYS = frozenset({"plugin_sent_at"})
_METADATA_KEYS = frozenset({
    "matchId", "map", "matchType", "half", "startedAt", "endedAt",
    "eventCount", "sourceServer",
})
_PUBLIC_FORBIDDEN_KEYS = frozenset({
    "matchid", "serverid", "playerid", "steamid", "userid", "alias",
    "raweventjson", "raweventsha256", "sourcefilesha256", "sourcepathsha256",
    "sourcelinenumber", "observedat", "pluginsentat", "ingestedat",
    "eventsequence", "alliesteamid", "axisteamid", "alliesteamslot",
    "axisteamslot", "matchtype",
})
_PUBLIC_QUALITY_FLAGS = frozenset({
    "missing-half-start", "missing-half-final", "half-carryover-mismatch",
    "score-regression", "side-mapping-unknown", "conflicting-order-key",
    "sequence-gap", "sequence-tie", "source-time-regression",
    "match-end-disagreement", "late-recovery", "incomplete-stream",
})
_PUBLIC_FATAL_QUALITY_FLAGS = frozenset({
    "missing-half-start", "missing-half-final", "half-carryover-mismatch",
    "score-regression", "side-mapping-unknown", "conflicting-order-key",
    "sequence-tie", "source-time-regression", "incomplete-stream",
})
_PUBLIC_PARTIAL_QUALITY_FLAGS = frozenset({
    "sequence-gap", "match-end-disagreement", "late-recovery",
})


class TeamScoreError(RuntimeError):
    """Base error for a fail-closed official-score operation."""


class JsonlValidationError(TeamScoreError):
    def __init__(self, errors: Sequence[str]):
        self.errors = tuple(errors)
        super().__init__("invalid official team_score input:\n" + "\n".join(self.errors))


class MysqlCommandError(TeamScoreError):
    """The local MySQL/MariaDB client rejected an operation."""


@dataclass(frozen=True)
class TeamScoreObservation:
    match_id: str
    match_type: int
    half: int
    tick_seconds: Decimal
    event_sequence: int
    observed_at: str | None
    allies_score: int
    axis_score: int
    allies_team_id: int
    axis_team_id: int
    map_name: str = "dod_anzio"
    source_server: str = ""
    source: str = OFFICIAL_SOURCE
    source_version: int = SOURCE_VERSION
    observation_kind: str = "change"
    retention_class: str = "retained"
    manifest_content_sha256: bytes = b""
    raw_event_json: str = ""
    raw_event_sha256: bytes = b""
    source_file_sha256: bytes = b""
    source_path_sha256: bytes = b""
    source_line_number: int = 0

    @property
    def order_key(self) -> tuple[str, int, Decimal, int]:
        return self.match_id, self.half, self.tick_seconds, self.event_sequence


@dataclass(frozen=True)
class ParsedImport:
    observations: tuple[TeamScoreObservation, ...]
    manifests: tuple["ObserverManifest", ...]
    input_lines: int
    ignored_events: int
    ignored_legacy_team_scores: int
    files: int


@dataclass(frozen=True)
class ObserverManifest:
    match_id: str
    map_name: str
    match_type: int
    source_server: str
    observer_started_at: str
    observer_ended_at: str
    terminal_half: int
    event_count: int
    official_row_count: int
    retained_row_count: int
    lifecycle_complete: bool
    settlement_seconds: int
    events_file_sha256: bytes
    metadata_file_sha256: bytes
    events_path_sha256: bytes
    metadata_path_sha256: bytes
    manifest_content_sha256: bytes
    match_end_allies_score: int | None
    match_end_axis_score: int | None
    retention_class: str


@dataclass(frozen=True)
class ProjectionContext:
    match_id: str
    map_name: str
    match_type: int | None
    source_server: str | None
    terminal_half: int | None
    event_count: int | None
    official_row_count: int | None
    retained_row_count: int | None
    events_file_sha256: bytes | None
    metadata_file_sha256: bytes | None
    manifest_content_sha256: bytes | None
    observer_closed: bool
    settled: bool
    lifecycle_complete: bool
    database_context_valid: bool
    match_end_allies_score: int | None = None
    match_end_axis_score: int | None = None


@dataclass(frozen=True)
class MatchSnapshot:
    rows: tuple[TeamScoreObservation, ...]
    conflict_keys: frozenset[tuple[int, Decimal, int]]
    context: ProjectionContext


@dataclass(frozen=True)
class ImportResult:
    input_lines: int
    ignored_events: int
    ignored_legacy_team_scores: int
    official_rows: int
    unique_candidates: int
    inserted: int
    idempotent_duplicates: int
    conflicting_rows: int
    conflict_keys: int
    retention_classes: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "inputLines": self.input_lines,
            "ignoredEvents": self.ignored_events,
            "ignoredLegacyTeamScores": self.ignored_legacy_team_scores,
            "officialRows": self.official_rows,
            "uniqueCandidates": self.unique_candidates,
            "inserted": self.inserted,
            "idempotentDuplicates": self.idempotent_duplicates,
            "conflictingRows": self.conflicting_rows,
            "conflictKeys": self.conflict_keys,
            "retentionClasses": dict(sorted(self.retention_classes.items())),
        }


@dataclass(frozen=True)
class ProjectionResult:
    dto: dict[str, Any]
    canonical_json: bytes
    sha256: str
    release_metadata: dict[str, Any]
    private_release_metadata: dict[str, Any]


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _strict_int(value: Any, field: str, *, minimum: int = 0,
                maximum: int = 4_294_967_295) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an exact integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} must be in [{minimum}, {maximum}]")
    return value


def _strict_tick(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise ValueError("tick must be a finite JSON number")
    try:
        tick = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("tick must be a finite decimal number") from exc
    if not tick.is_finite() or tick < 0:
        raise ValueError("tick must be finite and non-negative")
    exponent = tick.as_tuple().exponent
    integer_digits = max(1, tick.adjusted() + 1)
    if exponent < -9 or integer_digits > 11:
        raise ValueError("tick exceeds DECIMAL(20,9)")
    return tick


def _required_text(value: Any, field: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{field} must be a non-empty string of at most {maximum} characters")
    if "\x00" in value:
        raise ValueError(f"{field} contains NUL")
    return value


def _observed_at(plugin_sent_at: Any) -> str | None:
    if plugin_sent_at is None:
        return None
    millis = _strict_int(
        plugin_sent_at, "plugin_sent_at", minimum=1,
        maximum=253_402_300_799_999,
    )
    instant = datetime.fromtimestamp(millis / 1000, timezone.utc)
    return instant.strftime("%Y-%m-%d %H:%M:%S.") + f"{millis % 1000:03d}"


def retention_class(match_type: int, match_id: str) -> str:
    """Mirror the scheduled 14-day scrim/12man/test retention policy."""
    return "ephemeral-14d" if match_type in (1, 2) or match_id.endswith("-TEST") else "retained"


def _parse_json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    if len(raw) > MAX_RAW_ROW_BYTES:
        raise ValueError(f"row exceeds {MAX_RAW_ROW_BYTES} bytes")
    try:
        text = raw.decode("utf-8", "strict")
        value = json.loads(
            text, parse_float=Decimal, parse_int=int,
            parse_constant=_reject_constant, object_pairs_hook=_unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{label} is not a unique-key UTF-8 JSON object: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _parse_official_row(raw: bytes, value: dict[str, Any], *, file_sha: bytes,
                        path_sha: bytes, line_number: int, map_name: str,
                        source_server: str) -> TeamScoreObservation | None:
    if value.get("event") != "team_score":
        return None
    if value.get("source") != OFFICIAL_SOURCE:
        return None
    keys = frozenset(value)
    if not _REQUIRED_KEYS <= keys or keys - (_REQUIRED_KEYS | _OPTIONAL_KEYS):
        missing = sorted(_REQUIRED_KEYS - keys)
        extra = sorted(keys - (_REQUIRED_KEYS | _OPTIONAL_KEYS))
        raise ValueError(f"producer-v1 keys differ (missing={missing}, extra={extra})")

    match_id = _required_text(value["match_id"], "match_id", maximum=64)
    event_map = _required_text(value["map"], "map", maximum=32)
    if event_map != map_name:
        raise ValueError("official row map does not match observer metadata")
    match_type = _strict_int(value["match_type"], "match_type", maximum=5)
    if match_type not in SUPPORTED_MATCH_TYPES:
        raise ValueError("unsupported match_type")
    half = _strict_int(value["half"], "half", minimum=1, maximum=65_535)
    if half not in (1, 2) and half < 101:
        raise ValueError("half must be 1, 2, or an explicit OT value >= 101")
    tick = _strict_tick(value["tick"])
    sequence = _strict_int(
        value["event_sequence"], "event_sequence", minimum=1,
        maximum=18_446_744_073_709_551_615,
    )
    allies = _strict_int(value["allies_score"], "allies_score")
    axis = _strict_int(value["axis_score"], "axis_score")
    allies_team = _strict_int(value["allies_team_slot"], "allies_team_slot", minimum=1, maximum=2)
    axis_team = _strict_int(value["axis_team_slot"], "axis_team_slot", minimum=1, maximum=2)
    if {allies_team, axis_team} != {1, 2}:
        raise ValueError("side mapping must contain stable slots 1 and 2 exactly once")
    kind = value["sample_kind"]
    if not isinstance(kind, str) or kind not in OBSERVATION_KINDS:
        raise ValueError("sample_kind must be baseline, change, or final")

    return TeamScoreObservation(
        match_id=match_id,
        map_name=event_map,
        match_type=match_type,
        half=half,
        tick_seconds=tick,
        event_sequence=sequence,
        observed_at=_observed_at(value.get("plugin_sent_at")),
        allies_score=allies,
        axis_score=axis,
        allies_team_id=allies_team,
        axis_team_id=axis_team,
        source_server=source_server,
        observation_kind=kind,
        retention_class=retention_class(match_type, match_id),
        raw_event_json=raw.decode("utf-8"),
        raw_event_sha256=hashlib.sha256(raw).digest(),
        source_file_sha256=file_sha,
        source_path_sha256=path_sha,
        source_line_number=line_number,
    )


def _parse_iso8601(value: Any, field: str) -> tuple[datetime, str]:
    text = _required_text(value, field, maximum=40)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    utc = parsed.astimezone(timezone.utc)
    millis = utc.microsecond // 1000
    sql = utc.strftime("%Y-%m-%d %H:%M:%S.") + f"{millis:03d}"
    return utc, sql


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev, value.st_ino, value.st_mode, value.st_size,
        value.st_mtime_ns, value.st_ctime_ns,
    )


def _type_allowed(metadata_type: int, event_type: int, half: int) -> bool:
    if half in (1, 2):
        return event_type == metadata_type and metadata_type in (0, 1, 2, 3)
    if half >= 101:
        return (
            (metadata_type in (0, 4) and event_type == 4)
            or (metadata_type in (3, 5) and event_type == 5)
        )
    return False


def _expected_lifecycle_halves(match_type: int, terminal_half: int) -> list[int]:
    """Return the only complete half set accepted for one observer lifecycle.

    Overtime is a continuation of the regulation lifecycle: observer metadata
    keeps the originating official/draft type while individual OT rows use the
    corresponding MatchHandler OT type.
    """
    if match_type not in (0, 1, 2, 3):
        return []
    if terminal_half == 1:
        return [1]
    if terminal_half == 2:
        return [1, 2]
    if terminal_half >= 101:
        return [1, 2, *range(101, terminal_half + 1)]
    return []


def read_event_files(paths: Iterable[Path], *, settlement_seconds: int = SETTLEMENT_SECONDS,
                     now: float | None = None,
                     source_server_roots: Mapping[str, Path] | None = None,
                     _after_read_hook: Callable[[Path, Path], None] | None = None,
                     ) -> ParsedImport:
    """Read one or more completed local/mounted ``events.jsonl`` files.

    All official-v1 validation completes before any caller can write to the
    database.  Unrelated events and legacy team-score rows are counted and
    ignored; a row claiming the official source fails the whole batch closed.
    """
    if settlement_seconds < SETTLEMENT_SECONDS:
        raise ValueError(f"settlement_seconds cannot be below {SETTLEMENT_SECONDS}")
    configured_roots: dict[str, Path] = {}
    for source_server, root in (source_server_roots or {}).items():
        source_server = _required_text(
            source_server, "allowed source server", maximum=128,
        )
        resolved_root = Path(root).expanduser().resolve(strict=True)
        if not resolved_root.is_dir():
            raise ValueError(f"configured source root is not a directory: {resolved_root}")
        configured_roots[source_server] = resolved_root
    if not configured_roots:
        raise ValueError("an explicit source-server/root allowlist is required")
    clock = time.time() if now is None else now
    observations: list[TeamScoreObservation] = []
    manifests: list[ObserverManifest] = []
    errors: list[str] = []
    input_lines = ignored = legacy = 0
    seen_matches: set[str] = set()
    for supplied in paths:
        supplied_path = Path(supplied).expanduser()
        if supplied_path.name != "events.jsonl" or supplied_path.is_symlink():
            raise JsonlValidationError([f"{supplied_path}: expected a non-symlink events.jsonl"])
        path = supplied_path.resolve(strict=True)
        if not path.is_file():
            raise JsonlValidationError([f"{path}: not a regular file"])
        metadata_path = path.parent / "metadata.json"
        if not metadata_path.is_file() or metadata_path.is_symlink():
            raise JsonlValidationError([f"{path}: adjacent non-symlink metadata.json is required"])
        events_before = path.stat()
        metadata_before = metadata_path.stat()
        if events_before.st_size > MAX_JSONL_BYTES:
            raise JsonlValidationError([f"{path}: exceeds {MAX_JSONL_BYTES} bytes"])
        body = path.read_bytes()
        metadata_body = metadata_path.read_bytes()
        if _after_read_hook is not None:
            _after_read_hook(path, metadata_path)
        events_after = path.stat()
        metadata_after = metadata_path.stat()
        if (_stat_identity(events_before) != _stat_identity(events_after)
                or _stat_identity(metadata_before) != _stat_identity(metadata_after)):
            raise JsonlValidationError([f"{path}: observer files changed while being read"])

        try:
            metadata = _parse_json_object(metadata_body, label="metadata.json")
            if frozenset(metadata) != _METADATA_KEYS:
                raise ValueError("metadata.json keys differ from the observer contract")
            match_id = _required_text(metadata["matchId"], "metadata.matchId", maximum=64)
            map_name = _required_text(metadata["map"], "metadata.map", maximum=32)
            metadata_type = _strict_int(metadata["matchType"], "metadata.matchType", maximum=5)
            metadata_half = _strict_int(
                metadata["half"], "metadata.half", minimum=1, maximum=65_535,
            )
            if metadata_half not in (1, 2) and metadata_half < 101:
                raise ValueError("metadata.half is not an authoritative half identifier")
            event_count = _strict_int(
                metadata["eventCount"], "metadata.eventCount",
                maximum=18_446_744_073_709_551_615,
            )
            source_server = _required_text(
                metadata["sourceServer"], "metadata.sourceServer", maximum=128,
            )
            if source_server not in configured_roots:
                raise ValueError("metadata.sourceServer is not explicitly allowlisted")
            if metadata["endedAt"] is None:
                raise ValueError("metadata describes an active source (endedAt is null)")
            started, started_sql = _parse_iso8601(metadata["startedAt"], "metadata.startedAt")
            ended, ended_sql = _parse_iso8601(metadata["endedAt"], "metadata.endedAt")
            if ended < started:
                raise ValueError("metadata.endedAt precedes metadata.startedAt")
            age = clock - ended.timestamp()
            if age < settlement_seconds:
                raise ValueError(
                    f"observer late-settlement window is open ({age:.3f}s < {settlement_seconds}s)"
                )
            if path.parent.name != match_id:
                raise ValueError("events.jsonl parent directory is not metadata.matchId")
            expected_path = configured_roots[source_server] / match_id / "events.jsonl"
            if path != expected_path:
                raise ValueError("events.jsonl path is not owned by metadata.sourceServer")
            if match_id in seen_matches:
                raise ValueError("match appears in more than one input path")
            seen_matches.add(match_id)
        except ValueError as exc:
            errors.append(f"{metadata_path}: {exc}")
            continue

        file_sha = hashlib.sha256(body).digest()
        metadata_sha = hashlib.sha256(metadata_body).digest()
        path_sha = hashlib.sha256(str(path).encode("utf-8")).digest()
        metadata_path_sha = hashlib.sha256(str(metadata_path).encode("utf-8")).digest()
        file_rows: list[TeamScoreObservation] = []
        lifecycle_rows: list[dict[str, Any]] = []
        file_line_count = 0
        for line_number, raw in enumerate(body.splitlines(), 1):
            if not raw.strip():
                continue
            file_line_count += 1
            input_lines += 1
            try:
                value = _parse_json_object(raw, label="JSONL record")
                if "match_id" in value and value["match_id"] != match_id:
                    raise ValueError("event match_id does not match metadata.matchId")
                if "map" in value and value["map"] not in (map_name, "unknown"):
                    raise ValueError("event map does not match metadata.map")
                if "match_type" in value:
                    event_type = _strict_int(value["match_type"], "event.match_type", maximum=5)
                    event_half = _strict_int(value.get("half"), "event.half", minimum=1, maximum=65_535)
                    if not _type_allowed(metadata_type, event_type, event_half):
                        raise ValueError("event match-type/half progression is not canonical")
                if value.get("event") == "ktp_match_end":
                    for required in ("match_id", "map", "match_type", "half"):
                        if required not in value:
                            raise ValueError(f"ktp_match_end lacks {required}")
                    lifecycle_rows.append(value)
                value = _parse_official_row(
                    raw, value, file_sha=file_sha, path_sha=path_sha,
                    line_number=line_number, map_name=map_name,
                    source_server=source_server,
                )
                if value is None:
                    if _parse_json_object(raw, label="JSONL record").get("event") == "team_score":
                        legacy += 1
                    else:
                        ignored += 1
                else:
                    if value.match_id != match_id:
                        raise ValueError("official row match_id does not match metadata")
                    if not _type_allowed(metadata_type, value.match_type, value.half):
                        raise ValueError("official row match-type/half progression is not canonical")
                    file_rows.append(value)
            except ValueError as exc:
                errors.append(f"{path}:{line_number}: {exc}")
        if file_line_count != event_count:
            errors.append(
                f"{path}: metadata.eventCount={event_count} but JSONL has {file_line_count} nonblank rows"
            )
        if len(lifecycle_rows) != 1:
            errors.append(f"{path}: expected exactly one authoritative ktp_match_end lifecycle row")
            continue
        lifecycle = lifecycle_rows[0]
        try:
            terminal_half = _strict_int(
                lifecycle["half"], "ktp_match_end.half", minimum=1, maximum=65_535,
            )
            if terminal_half not in (1, 2) and terminal_half < 101:
                raise ValueError("ktp_match_end half is invalid")
            lifecycle_type = _strict_int(lifecycle["match_type"], "ktp_match_end.match_type", maximum=5)
            if not _type_allowed(metadata_type, lifecycle_type, terminal_half):
                raise ValueError("ktp_match_end match-type progression is invalid")
            if lifecycle["match_id"] != match_id or lifecycle["map"] != map_name:
                raise ValueError("ktp_match_end context does not match metadata")
            if file_rows and max(row.half for row in file_rows) != terminal_half:
                raise ValueError("terminal lifecycle half does not equal final score half")
            end_allies = lifecycle.get("allies_score")
            end_axis = lifecycle.get("axis_score")
            if (end_allies is None) != (end_axis is None):
                raise ValueError("ktp_match_end comparison scores must be both present or absent")
            if end_allies is not None:
                end_allies = _strict_int(end_allies, "ktp_match_end.allies_score")
                end_axis = _strict_int(end_axis, "ktp_match_end.axis_score")
        except ValueError as exc:
            errors.append(f"{path}: {exc}")
            continue

        variants_by_order: dict[tuple[str, int, Decimal, int], set[bytes]] = defaultdict(set)
        for row in file_rows:
            variants_by_order[row.order_key].add(row.raw_event_sha256)
        retained_row_count = sum(
            len(variants) == 1 for variants in variants_by_order.values()
        )
        manifest_fields = {
            "matchId": match_id, "mapName": map_name, "matchType": metadata_type,
            "sourceServer": source_server, "observerStartedAt": started_sql,
            "observerEndedAt": ended_sql, "terminalHalf": terminal_half,
            "eventCount": event_count, "officialRowCount": len(file_rows),
            "retainedRowCount": retained_row_count,
            "lifecycleComplete": True, "settlementSeconds": settlement_seconds,
            "eventsFileSha256": file_sha.hex(), "metadataFileSha256": metadata_sha.hex(),
            "eventsPathSha256": path_sha.hex(), "metadataPathSha256": metadata_path_sha.hex(),
            "matchEndAlliesScore": end_allies, "matchEndAxisScore": end_axis,
        }
        manifest_sha = hashlib.sha256(_canonical_bytes(manifest_fields)).digest()
        retention = retention_class(metadata_type, match_id)
        manifest = ObserverManifest(
            match_id=match_id, map_name=map_name, match_type=metadata_type,
            source_server=source_server, observer_started_at=started_sql,
            observer_ended_at=ended_sql, terminal_half=terminal_half,
            event_count=event_count, official_row_count=len(file_rows),
            retained_row_count=retained_row_count,
            lifecycle_complete=True, settlement_seconds=settlement_seconds,
            events_file_sha256=file_sha, metadata_file_sha256=metadata_sha,
            events_path_sha256=path_sha, metadata_path_sha256=metadata_path_sha,
            manifest_content_sha256=manifest_sha,
            match_end_allies_score=end_allies, match_end_axis_score=end_axis,
            retention_class=retention,
        )
        manifests.append(manifest)
        observations.extend(replace(row, manifest_content_sha256=manifest_sha)
                            for row in file_rows)
    if errors:
        raise JsonlValidationError(errors)
    if len(observations) > MAX_OFFICIAL_ROWS:
        raise JsonlValidationError([
            f"official row count {len(observations)} exceeds {MAX_OFFICIAL_ROWS}"
        ])
    return ParsedImport(
        observations=tuple(observations), manifests=tuple(manifests), input_lines=input_lines,
        ignored_events=ignored, ignored_legacy_team_scores=legacy,
        files=len(manifests),
    )


def _sql_text(value: str) -> str:
    return f"CONVERT(0x{value.encode('utf-8').hex()} USING utf8mb4)"


def _sql_binary(value: bytes) -> str:
    return f"0x{value.hex()}"


def _sql_decimal(value: Decimal) -> str:
    return format(value, "f")


def _stage_rows(
    observations: Sequence[TeamScoreObservation],
) -> list[tuple[TeamScoreObservation, int, TeamScoreObservation, int]]:
    groups: dict[tuple[tuple[str, int, Decimal, int], bytes], list[TeamScoreObservation]] = defaultdict(list)
    for row in observations:
        groups[(row.order_key, row.raw_event_sha256)].append(row)
    by_order: dict[tuple[str, int, Decimal, int], list[tuple[TeamScoreObservation, int]]] = defaultdict(list)
    for values in groups.values():
        chosen = min(values, key=lambda row: (
            row.source_file_sha256, row.source_path_sha256, row.source_line_number
        ))
        by_order[chosen.order_key].append((chosen, len(values)))
    result = []
    for variants in by_order.values():
        incumbent = min(variants, key=lambda item: item[0].raw_event_sha256)[0]
        for chosen, count in variants:
            result.append((chosen, count, incumbent, len(variants)))
    return sorted(result, key=lambda item: (item[0].order_key, item[0].raw_event_sha256))


def build_import_sql(parsed: ParsedImport) -> str:
    """Build one lock-serialized, transactional, context-bound import."""
    observations = parsed.observations
    manifests = parsed.manifests
    if not manifests:
        return "SELECT 'KTP_TEAM_SCORE_IMPORT_RESULT',0,0,0,0,0,0,0,0,1;\n"
    staged = _stage_rows(observations)
    values: list[str] = []
    for row, count, incumbent, variant_count in staged:
        observed = "NULL" if row.observed_at is None else f"'{row.observed_at}'"
        values.append("(" + ",".join((
            _sql_text(row.match_id), str(row.match_type), str(row.half),
            _sql_text(row.map_name), _sql_text(row.source_server),
            _sql_decimal(row.tick_seconds), str(row.event_sequence), observed,
            str(row.allies_score), str(row.axis_score),
            str(row.allies_team_id), str(row.axis_team_id),
            _sql_text(row.source), str(row.source_version),
            _sql_text(row.observation_kind), _sql_text(row.retention_class),
            _sql_binary(row.manifest_content_sha256),
            _sql_text(row.raw_event_json), _sql_binary(row.raw_event_sha256),
            _sql_binary(row.source_file_sha256), _sql_binary(row.source_path_sha256),
            str(row.source_line_number), str(count),
            _sql_binary(incumbent.raw_event_sha256),
            _sql_text(incumbent.raw_event_json), str(variant_count),
        )) + ")")

    conflict_key = (
        "c.match_id=s.match_id AND c.half=s.half "
        "AND c.tick_seconds=s.tick_seconds AND c.event_sequence=s.event_sequence"
    )
    row_columns = (
        "match_id,match_type,half,map_name,source_server,tick_seconds,event_sequence,observed_at,"
        "allies_score,axis_score,allies_team_id,axis_team_id,source,source_version,"
        "observation_kind,retention_class,manifest_content_sha256,raw_event_json,raw_event_sha256,"
        "source_file_sha256,source_path_sha256,source_line_number,input_count,"
        "batch_incumbent_raw_sha256,batch_incumbent_raw_event_json,batch_variant_count"
    )
    manifest_values = []
    for item in manifests:
        end_allies = "NULL" if item.match_end_allies_score is None else str(item.match_end_allies_score)
        end_axis = "NULL" if item.match_end_axis_score is None else str(item.match_end_axis_score)
        manifest_values.append("(" + ",".join((
            _sql_text(item.match_id), _sql_text(item.map_name), str(item.match_type),
            _sql_text(item.source_server), f"'{item.observer_started_at}'",
            f"'{item.observer_ended_at}'", str(item.terminal_half),
            str(item.event_count), str(item.official_row_count), str(item.retained_row_count), "1",
            str(item.settlement_seconds), _sql_binary(item.events_file_sha256),
            _sql_binary(item.metadata_file_sha256), _sql_binary(item.events_path_sha256),
            _sql_binary(item.metadata_path_sha256), _sql_binary(item.manifest_content_sha256),
            end_allies, end_axis, _sql_text(item.retention_class),
        )) + ")")
    row_stage_sql = ""
    if values:
        row_stage_sql = f"INSERT INTO `ktp_team_score_import_stage` ({row_columns}) VALUES\n{','.join(values)};"
    return f"""
SELECT GET_LOCK('{LEDGER_LOCK}',30) INTO @ktp_team_score_lock;
START TRANSACTION;
CREATE TEMPORARY TABLE `ktp_team_score_manifest_stage` (
  `match_id` VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL PRIMARY KEY,
  `map_name` VARCHAR(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `match_type` TINYINT UNSIGNED NOT NULL,
  `source_server` VARCHAR(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `observer_started_at` DATETIME(3) NOT NULL,
  `observer_ended_at` DATETIME(3) NOT NULL,
  `terminal_half` SMALLINT UNSIGNED NOT NULL,
  `event_count` BIGINT UNSIGNED NOT NULL,
  `official_row_count` INT UNSIGNED NOT NULL,
  `retained_row_count` INT UNSIGNED NOT NULL,
  `lifecycle_complete` TINYINT UNSIGNED NOT NULL,
  `settlement_seconds` SMALLINT UNSIGNED NOT NULL,
  `events_file_sha256` BINARY(32) NOT NULL,
  `metadata_file_sha256` BINARY(32) NOT NULL,
  `events_path_sha256` BINARY(32) NOT NULL,
  `metadata_path_sha256` BINARY(32) NOT NULL,
  `manifest_content_sha256` BINARY(32) NOT NULL,
  `match_end_allies_score` INT UNSIGNED NULL,
  `match_end_axis_score` INT UNSIGNED NULL,
  `retention_class` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL
) ENGINE=InnoDB;
INSERT INTO `ktp_team_score_manifest_stage` VALUES
{','.join(manifest_values)};
CREATE TEMPORARY TABLE `ktp_team_score_import_stage` (
  `match_id` VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `match_type` TINYINT UNSIGNED NOT NULL,
  `half` SMALLINT UNSIGNED NOT NULL,
  `map_name` VARCHAR(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `source_server` VARCHAR(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `tick_seconds` DECIMAL(20,9) UNSIGNED NOT NULL,
  `event_sequence` BIGINT UNSIGNED NOT NULL,
  `observed_at` DATETIME(3) NULL,
  `allies_score` INT UNSIGNED NOT NULL,
  `axis_score` INT UNSIGNED NOT NULL,
  `allies_team_id` TINYINT UNSIGNED NOT NULL,
  `axis_team_id` TINYINT UNSIGNED NOT NULL,
  `source` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `source_version` SMALLINT UNSIGNED NOT NULL,
  `observation_kind` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `retention_class` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `manifest_content_sha256` BINARY(32) NOT NULL,
  `raw_event_json` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `raw_event_sha256` BINARY(32) NOT NULL,
  `source_file_sha256` BINARY(32) NOT NULL,
  `source_path_sha256` BINARY(32) NOT NULL,
  `source_line_number` BIGINT UNSIGNED NOT NULL,
  `input_count` INT UNSIGNED NOT NULL,
  `batch_incumbent_raw_sha256` BINARY(32) NOT NULL,
  `batch_incumbent_raw_event_json` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `batch_variant_count` INT UNSIGNED NOT NULL,
  PRIMARY KEY (`match_id`,`half`,`tick_seconds`,`event_sequence`,`raw_event_sha256`)
) ENGINE=InnoDB;
{row_stage_sql}

SET @ktp_team_score_manifest_mismatch := (
  SELECT COUNT(*) FROM `ktp_team_score_manifest_stage` s
  LEFT JOIN `ktp_team_score_ingest_manifests` m ON m.match_id=s.match_id
  WHERE (m.match_id IS NOT NULL AND (
      m.manifest_content_sha256<>s.manifest_content_sha256
      OR m.events_path_sha256<>s.events_path_sha256
      OR m.metadata_path_sha256<>s.metadata_path_sha256))
    OR EXISTS (SELECT 1 FROM `ktp_team_score_ingest_manifests` p
               WHERE p.match_id<>s.match_id AND
                 (p.events_path_sha256=s.events_path_sha256
                  OR p.metadata_path_sha256=s.metadata_path_sha256))
);
SET @ktp_team_score_context_mismatch := (
  SELECT COUNT(*) FROM `ktp_team_score_manifest_stage` s
  WHERE NOT EXISTS (
    SELECT 1 FROM ktp_matches km
    WHERE BINARY km.match_id=BINARY s.match_id
    GROUP BY km.match_id
    HAVING COUNT(DISTINCT BINARY km.map_name)=1
       AND MIN(BINARY km.map_name)=BINARY s.map_name
       AND SUM(km.end_time IS NULL)=0
       AND MAX(km.half)=s.terminal_half
       AND COUNT(DISTINCT km.half)=CASE
         WHEN s.terminal_half=1 THEN 1
         WHEN s.terminal_half=2 THEN 2
         WHEN s.terminal_half>=101 THEN s.terminal_half-98
         ELSE 0 END
       AND SUM(km.half=1)>0
       AND (s.terminal_half=1 OR SUM(km.half=2)>0)
       AND SUM(km.half NOT IN (1,2) AND
               NOT(km.half BETWEEN 101 AND s.terminal_half))=0
       AND SUM(
         CASE
           WHEN km.half IN (1,2) THEN NOT(km.match_type=s.match_type AND s.match_type IN (0,1,2,3))
           WHEN km.half>=101 THEN NOT(
             (s.match_type IN (0,4) AND km.match_type=4)
             OR (s.match_type IN (3,5) AND km.match_type=5))
           ELSE 1
         END
       )=0
  )
);

-- Preserve evidence of a later settled-file mutation or path reuse before
-- rejecting the attempt. This ledger intentionally has no parent FK, so the
-- accepted manifest and observations remain immutable while the audit itself
-- survives both rejection and any future retention choreography.
INSERT IGNORE INTO `ktp_team_score_ingest_audits`
 (match_id,audit_kind,accepted_match_id,accepted_manifest_sha256,
  attempted_manifest_sha256,attempted_events_file_sha256,
  attempted_metadata_file_sha256,attempted_events_path_sha256,
  attempted_metadata_path_sha256,map_name,source_server,match_type,
  terminal_half,event_count,official_row_count)
SELECT s.match_id,
 CASE WHEN m.match_id IS NOT NULL THEN 'manifest-mismatch' ELSE 'path-reuse' END,
 COALESCE(m.match_id,p.match_id),
 COALESCE(m.manifest_content_sha256,p.manifest_content_sha256),
 s.manifest_content_sha256,s.events_file_sha256,s.metadata_file_sha256,
 s.events_path_sha256,s.metadata_path_sha256,s.map_name,s.source_server,
 s.match_type,s.terminal_half,s.event_count,s.official_row_count
FROM `ktp_team_score_manifest_stage` s
LEFT JOIN `ktp_team_score_ingest_manifests` m ON m.match_id=s.match_id
 AND (m.manifest_content_sha256<>s.manifest_content_sha256
      OR m.events_path_sha256<>s.events_path_sha256
      OR m.metadata_path_sha256<>s.metadata_path_sha256)
LEFT JOIN `ktp_team_score_ingest_manifests` p ON p.match_id<>s.match_id
 AND (p.events_path_sha256=s.events_path_sha256
      OR p.metadata_path_sha256=s.metadata_path_sha256)
WHERE @ktp_team_score_lock=1 AND (m.match_id IS NOT NULL OR p.match_id IS NOT NULL);
SET @ktp_team_score_blocked := (
  @ktp_team_score_lock<>1 OR @ktp_team_score_manifest_mismatch<>0
  OR @ktp_team_score_context_mismatch<>0
);

INSERT INTO `ktp_team_score_ingest_manifests`
 (match_id,map_name,match_type,source_server,observer_started_at,observer_ended_at,
  terminal_half,event_count,official_row_count,retained_row_count,lifecycle_complete,settlement_seconds,
  events_file_sha256,metadata_file_sha256,events_path_sha256,metadata_path_sha256,
  manifest_content_sha256,match_end_allies_score,match_end_axis_score,retention_class)
SELECT s.match_id,s.map_name,s.match_type,s.source_server,s.observer_started_at,s.observer_ended_at,
 s.terminal_half,s.event_count,s.official_row_count,s.retained_row_count,s.lifecycle_complete,s.settlement_seconds,
 s.events_file_sha256,s.metadata_file_sha256,s.events_path_sha256,s.metadata_path_sha256,
 s.manifest_content_sha256,s.match_end_allies_score,s.match_end_axis_score,s.retention_class
FROM `ktp_team_score_manifest_stage` s
WHERE @ktp_team_score_blocked=0 AND NOT EXISTS (
 SELECT 1 FROM `ktp_team_score_ingest_manifests` m WHERE m.match_id=s.match_id
);

-- Conflicting variants delivered together are quarantined deterministically.
INSERT IGNORE INTO `ktp_team_score_ingest_conflicts`
  (match_id,half,tick_seconds,event_sequence,
   manifest_content_sha256,
   incumbent_raw_sha256,rejected_raw_sha256,
   incumbent_raw_event_json,rejected_raw_event_json,
   source_file_sha256,source_path_sha256,source_line_number,conflict_kind)
SELECT s.match_id,s.half,s.tick_seconds,s.event_sequence,
       s.manifest_content_sha256,
       s.batch_incumbent_raw_sha256,s.raw_event_sha256,
       s.batch_incumbent_raw_event_json,s.raw_event_json,
       s.source_file_sha256,s.source_path_sha256,s.source_line_number,'batch'
FROM `ktp_team_score_import_stage` s
WHERE @ktp_team_score_blocked=0
  AND s.batch_variant_count>1
  AND s.raw_event_sha256<>s.batch_incumbent_raw_sha256;

-- A later different row never overwrites the append-only incumbent.
INSERT IGNORE INTO `ktp_team_score_ingest_conflicts`
  (match_id,half,tick_seconds,event_sequence,
   manifest_content_sha256,
   incumbent_raw_sha256,rejected_raw_sha256,
   incumbent_raw_event_json,rejected_raw_event_json,
   source_file_sha256,source_path_sha256,source_line_number,conflict_kind)
SELECT o.match_id,o.half,o.tick_seconds,o.event_sequence,
       s.manifest_content_sha256,
       o.raw_event_sha256,s.raw_event_sha256,
       o.raw_event_json,s.raw_event_json,
       s.source_file_sha256,s.source_path_sha256,s.source_line_number,'existing'
FROM `ktp_team_score_observations` o
JOIN `ktp_team_score_import_stage` s
  ON o.match_id=s.match_id AND o.half=s.half
 AND o.tick_seconds=s.tick_seconds AND o.event_sequence=s.event_sequence
WHERE @ktp_team_score_blocked=0
  AND o.raw_event_sha256<>s.raw_event_sha256;

SET @ktp_team_score_conflicting_rows := (
  SELECT COALESCE(SUM(s.input_count),0)
  FROM `ktp_team_score_import_stage` s
  WHERE EXISTS (
    SELECT 1 FROM `ktp_team_score_ingest_conflicts` c WHERE {conflict_key}
  )
);
SET @ktp_team_score_conflict_keys := (
  SELECT COUNT(*) FROM (
    SELECT s.match_id,s.half,s.tick_seconds,s.event_sequence
    FROM `ktp_team_score_import_stage` s
    WHERE EXISTS (
      SELECT 1 FROM `ktp_team_score_ingest_conflicts` c WHERE {conflict_key}
    )
    GROUP BY s.match_id,s.half,s.tick_seconds,s.event_sequence
  ) touched_conflicts
);
SET @ktp_team_score_duplicates := (
  SELECT COALESCE(SUM(
    CASE WHEN EXISTS (
      SELECT 1 FROM `ktp_team_score_observations` o
      WHERE o.match_id=s.match_id AND o.half=s.half
        AND o.tick_seconds=s.tick_seconds AND o.event_sequence=s.event_sequence
        AND o.raw_event_sha256=s.raw_event_sha256
    ) THEN s.input_count ELSE GREATEST(s.input_count-1,0) END
  ),0)
  FROM `ktp_team_score_import_stage` s
  WHERE NOT EXISTS (
    SELECT 1 FROM `ktp_team_score_ingest_conflicts` c WHERE {conflict_key}
  )
);

INSERT INTO `ktp_team_score_observations`
  (match_id,map_name,match_type,half,tick_seconds,event_sequence,observed_at,
   allies_score,axis_score,allies_team_id,axis_team_id,source,source_version,
   source_server,observation_kind,retention_class,manifest_content_sha256,
   raw_event_json,raw_event_sha256,
   source_file_sha256,source_path_sha256,source_line_number)
SELECT s.match_id,s.map_name,s.match_type,s.half,s.tick_seconds,s.event_sequence,s.observed_at,
       s.allies_score,s.axis_score,s.allies_team_id,s.axis_team_id,s.source,s.source_version,
       s.source_server,s.observation_kind,s.retention_class,s.manifest_content_sha256,
       s.raw_event_json,s.raw_event_sha256,
       s.source_file_sha256,s.source_path_sha256,s.source_line_number
FROM `ktp_team_score_import_stage` s
WHERE NOT EXISTS (
  SELECT 1 FROM `ktp_team_score_observations` o
  WHERE o.match_id=s.match_id AND o.half=s.half
    AND o.tick_seconds=s.tick_seconds AND o.event_sequence=s.event_sequence
)
AND NOT EXISTS (
  SELECT 1 FROM `ktp_team_score_ingest_conflicts` c WHERE {conflict_key}
)
AND @ktp_team_score_blocked=0;
SET @ktp_team_score_inserted := ROW_COUNT();
SET @ktp_team_score_official_rows := (
  SELECT COALESCE(SUM(input_count),0) FROM `ktp_team_score_import_stage`
);
SET @ktp_team_score_unique_candidates := (
  SELECT COUNT(*) FROM `ktp_team_score_import_stage`
);
COMMIT;
SELECT 'KTP_TEAM_SCORE_IMPORT_RESULT',
       @ktp_team_score_official_rows,@ktp_team_score_unique_candidates,
       @ktp_team_score_inserted,@ktp_team_score_duplicates,
       @ktp_team_score_conflicting_rows,@ktp_team_score_conflict_keys,
       @ktp_team_score_manifest_mismatch,@ktp_team_score_context_mismatch,
       @ktp_team_score_lock;
SELECT IF(@ktp_team_score_lock=1,
          RELEASE_LOCK('{LEDGER_LOCK}'),0);
""".strip() + "\n"


class MysqlCli:
    """Small local-client adapter; credentials remain in MySQL option files."""

    def __init__(self, *, mysql_bin: str = "mysql", database: str = "hlstatsx_lan",
                 defaults_extra_file: Path | None = None, socket: Path | None = None,
                 host: str | None = None, port: int | None = None,
                 user: str | None = None):
        if not _DATABASE.fullmatch(database):
            raise ValueError("database must contain only letters, digits, and underscore")
        if socket is not None and (host is not None or port is not None):
            raise ValueError("socket and TCP host/port are mutually exclusive")
        self.mysql_bin = mysql_bin
        self.database = database
        self.defaults_extra_file = Path(defaults_extra_file) if defaults_extra_file else None
        self.socket = Path(socket) if socket else None
        self.host = host
        self.port = port
        self.user = user

    def _argv(self) -> list[str]:
        argv = [self.mysql_bin]
        if self.defaults_extra_file:
            argv.append(f"--defaults-extra-file={self.defaults_extra_file}")
        else:
            argv.append("--no-defaults")
        argv += ["--batch", "--raw", "--skip-column-names", "--connect-timeout=5"]
        if self.socket:
            argv += ["--protocol=SOCKET", f"--socket={self.socket}"]
        else:
            if self.host:
                argv.append(f"--host={self.host}")
            if self.port is not None:
                argv.append(f"--port={self.port}")
        if self.user:
            argv += ["-u", self.user]
        argv.append(self.database)
        return argv

    def execute(self, sql: str) -> str:
        proc = subprocess.run(
            self._argv(), input=sql, text=True, encoding="utf-8",
            capture_output=True, check=False,
        )
        if proc.returncode:
            raise MysqlCommandError(
                f"MySQL client failed (rc={proc.returncode}): {proc.stderr.strip()[-2000:]}"
            )
        return proc.stdout

    def apply_migration(self, path: Path = MIGRATION) -> None:
        migration = Path(path)
        if not migration.is_file():
            raise FileNotFoundError(migration)
        self.execute(migration.read_text(encoding="utf-8"))

    def import_observations(self, parsed: ParsedImport) -> ImportResult:
        rows = parsed.observations
        if not parsed.manifests:
            fields = [0, 0, 0, 0, 0, 0]
        else:
            output = self.execute(build_import_sql(parsed))
            result_line = next(
                (line for line in output.splitlines()
                 if line.startswith("KTP_TEAM_SCORE_IMPORT_RESULT\t")),
                None,
            )
            if result_line is None:
                raise MysqlCommandError("import result marker missing from MySQL output")
            try:
                fields = [int(value) for value in result_line.split("\t")[1:]]
            except ValueError as exc:
                raise MysqlCommandError(f"invalid import result: {result_line}") from exc
            if len(fields) != 9:
                raise MysqlCommandError(f"invalid import result width: {result_line}")
            if fields.pop() != 1:
                raise MysqlCommandError("could not acquire shared team-score ledger lock")
            context_mismatch = fields.pop()
            manifest_mismatch = fields.pop()
            if manifest_mismatch:
                raise MysqlCommandError("observer manifest/file identity conflicts with retained evidence")
            if context_mismatch:
                raise MysqlCommandError("observer manifest does not match closed ktp_matches context")
        classes = Counter(row.retention_class for row in rows)
        return ImportResult(
            input_lines=parsed.input_lines,
            ignored_events=parsed.ignored_events,
            ignored_legacy_team_scores=parsed.ignored_legacy_team_scores,
            official_rows=fields[0], unique_candidates=fields[1],
            inserted=fields[2], idempotent_duplicates=fields[3],
            conflicting_rows=fields[4], conflict_keys=fields[5],
            retention_classes=dict(classes),
        )

    def fetch_match(self, match_id: str) -> MatchSnapshot:
        """Fetch rows, conflicts, finality, and analytics context atomically.

        One mysql client process is one connection. The named ledger lock and
        consistent transaction cover every SELECT, so retention/import cannot
        interleave and make conflict or finality evidence disappear mid-read.
        """
        match_id = _required_text(match_id, "match_id", maximum=64)
        match = _sql_text(match_id)
        output = self.execute(f"""
SELECT GET_LOCK('{LEDGER_LOCK}',30) INTO @ktp_team_score_lock;
SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;
START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;
SELECT 'KTP_SCORE_LOCK',@ktp_team_score_lock;
SELECT 'KTP_SCORE_MANIFEST',HEX(match_id),HEX(map_name),match_type,
       HEX(source_server),terminal_half,event_count,official_row_count,
       retained_row_count,lifecycle_complete,settlement_seconds,HEX(events_file_sha256),
       HEX(metadata_file_sha256),HEX(manifest_content_sha256),
       COALESCE(CAST(match_end_allies_score AS CHAR),'NULL'),
       COALESCE(CAST(match_end_axis_score AS CHAR),'NULL')
FROM ktp_team_score_ingest_manifests
WHERE match_id={match} AND @ktp_team_score_lock=1;
SELECT 'KTP_SCORE_ROW',HEX(match_id),HEX(map_name),match_type,half,
       CAST(tick_seconds AS CHAR),event_sequence,allies_score,axis_score,
       allies_team_id,axis_team_id,HEX(source_server),source,source_version,
       observation_kind,retention_class,HEX(manifest_content_sha256)
FROM ktp_team_score_observations
WHERE match_id={match} AND @ktp_team_score_lock=1
ORDER BY half,tick_seconds,event_sequence;
SELECT 'KTP_SCORE_CONFLICT',half,CAST(tick_seconds AS CHAR),event_sequence
FROM ktp_team_score_ingest_conflicts
WHERE match_id={match} AND @ktp_team_score_lock=1
GROUP BY half,tick_seconds,event_sequence
ORDER BY half,tick_seconds,event_sequence;
SELECT 'KTP_SCORE_AUDIT',COUNT(*) FROM ktp_team_score_ingest_audits
WHERE match_id={match} AND @ktp_team_score_lock=1;
SELECT 'KTP_SCORE_CONTEXT',HEX(match_id),HEX(map_name),half,
       COALESCE(CAST(match_type AS CHAR),'NULL'),(end_time IS NOT NULL)
FROM ktp_matches WHERE BINARY match_id=BINARY {match} AND @ktp_team_score_lock=1
ORDER BY half;
COMMIT;
SELECT 'KTP_SCORE_RELEASE',IF(@ktp_team_score_lock=1,
       RELEASE_LOCK('{LEDGER_LOCK}'),0);
""")
        lines = [line.split("\t") for line in output.splitlines() if line]
        lock_rows = [fields for fields in lines if fields[0] == "KTP_SCORE_LOCK"]
        release_rows = [fields for fields in lines if fields[0] == "KTP_SCORE_RELEASE"]
        if lock_rows != [["KTP_SCORE_LOCK", "1"]] or release_rows != [["KTP_SCORE_RELEASE", "1"]]:
            raise MysqlCommandError("shared team-score ledger snapshot lock failed")
        rows: list[TeamScoreObservation] = []
        for fields in (item for item in lines if item[0] == "KTP_SCORE_ROW"):
            if len(fields) != 17:
                raise MysqlCommandError("unexpected team-score query width")
            rows.append(TeamScoreObservation(
                match_id=bytes.fromhex(fields[1]).decode("utf-8"),
                map_name=bytes.fromhex(fields[2]).decode("utf-8"),
                match_type=int(fields[3]), half=int(fields[4]),
                tick_seconds=Decimal(fields[5]), event_sequence=int(fields[6]),
                observed_at=None, allies_score=int(fields[7]), axis_score=int(fields[8]),
                allies_team_id=int(fields[9]), axis_team_id=int(fields[10]),
                source_server=bytes.fromhex(fields[11]).decode("utf-8"),
                source=fields[12], source_version=int(fields[13]),
                observation_kind=fields[14], retention_class=fields[15],
                manifest_content_sha256=bytes.fromhex(fields[16]),
            ))
        conflicts = frozenset(
            (int(fields[1]), Decimal(fields[2]), int(fields[3]))
            for fields in lines if fields[0] == "KTP_SCORE_CONFLICT"
        )
        audit_rows = [fields for fields in lines if fields[0] == "KTP_SCORE_AUDIT"]
        if len(audit_rows) != 1 or len(audit_rows[0]) != 2:
            raise MysqlCommandError("unexpected team-score manifest audit query")
        manifest_audit_count = int(audit_rows[0][1])
        manifest_rows = [fields for fields in lines if fields[0] == "KTP_SCORE_MANIFEST"]
        context_rows = [fields for fields in lines if fields[0] == "KTP_SCORE_CONTEXT"]
        if len(manifest_rows) > 1:
            raise MysqlCommandError("multiple finality manifests for one match")
        analytics_map = None
        analytics_types: list[tuple[int, int | None]] = []
        closed = bool(context_rows)
        for fields in context_rows:
            if len(fields) != 6:
                raise MysqlCommandError("unexpected ktp_matches context query width")
            current_map = bytes.fromhex(fields[2]).decode("utf-8")
            analytics_map = current_map if analytics_map is None else analytics_map
            if current_map != analytics_map or fields[5] != "1":
                closed = False
            analytics_types.append((int(fields[3]), None if fields[4] == "NULL" else int(fields[4])))

        if manifest_rows:
            fields = manifest_rows[0]
            if len(fields) != 16:
                raise MysqlCommandError("unexpected finality manifest query width")
            manifest_match = bytes.fromhex(fields[1]).decode("utf-8")
            manifest_map = bytes.fromhex(fields[2]).decode("utf-8")
            manifest_type = int(fields[3])
            source_server = bytes.fromhex(fields[4]).decode("utf-8")
            terminal_half = int(fields[5])
            official_count = int(fields[7])
            retained_count = int(fields[8])
            analytics_halves = [half for half, _ in analytics_types]
            expected_halves = _expected_lifecycle_halves(manifest_type, terminal_half)
            progression_valid = (
                analytics_halves == expected_halves
                and len(analytics_halves) == len(set(analytics_halves))
            )
            for half, match_type in analytics_types:
                progression_valid = progression_valid and match_type is not None and _type_allowed(
                    manifest_type, match_type, half
                )
            database_valid = (
                manifest_match == match_id and analytics_map == manifest_map and closed
                and progression_valid and retained_count == len(rows)
                and manifest_audit_count == 0
                and all(row.manifest_content_sha256 == bytes.fromhex(fields[13]) for row in rows)
            )
            context = ProjectionContext(
                match_id=manifest_match, map_name=manifest_map,
                match_type=manifest_type, source_server=source_server,
                terminal_half=terminal_half, event_count=int(fields[6]),
                official_row_count=official_count,
                retained_row_count=retained_count,
                events_file_sha256=bytes.fromhex(fields[11]),
                metadata_file_sha256=bytes.fromhex(fields[12]),
                manifest_content_sha256=bytes.fromhex(fields[13]),
                observer_closed=True, settled=int(fields[10]) >= SETTLEMENT_SECONDS,
                lifecycle_complete=fields[9] == "1",
                database_context_valid=database_valid,
                match_end_allies_score=None if fields[14] == "NULL" else int(fields[14]),
                match_end_axis_score=None if fields[15] == "NULL" else int(fields[15]),
            )
        else:
            context = ProjectionContext(
                match_id=match_id, map_name=analytics_map or "unknown",
                match_type=None, source_server=None, terminal_half=None,
                event_count=None, official_row_count=None, retained_row_count=None,
                events_file_sha256=None, metadata_file_sha256=None,
                manifest_content_sha256=None, observer_closed=False,
                settled=False, lifecycle_complete=False,
                database_context_valid=closed,
            )
        return MatchSnapshot(tuple(rows), conflicts, context)


def _public_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("public time is not finite")
    return number


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def privacy_violations(value: Any, path: str = "objectiveScoreTimeline") -> list[str]:
    violations: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            token = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if token in _PUBLIC_FORBIDDEN_KEYS or token.startswith("player") or token.startswith("steam"):
                violations.append(f"{path}.{key}")
            violations.extend(privacy_violations(nested, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            violations.extend(privacy_violations(nested, f"{path}[{index}]"))
    return violations


def validate_public_projection(value: Any) -> dict[str, Any]:
    """Validate an already-sanitized DTO before attaching/publishing it."""
    violations = privacy_violations(value)
    if violations:
        raise ValueError(f"objective-score artifact contains private keys: {violations}")
    if not isinstance(value, dict) or set(value) != {"objectiveScoreTimeline"}:
        raise ValueError("objective-score artifact must contain exactly objectiveScoreTimeline")
    timeline = value["objectiveScoreTimeline"]
    required = {
        "source", "sourceVersion", "scoringScope", "carryOver",
        "teams", "halves", "quality",
    }
    if not isinstance(timeline, dict) or set(timeline) != required:
        raise ValueError("objectiveScoreTimeline has an unexpected public schema")
    if (timeline["source"] != OFFICIAL_SOURCE
            or timeline["sourceVersion"] != SOURCE_VERSION
            or timeline["scoringScope"] != "official-in-game-team-score"
            or timeline["carryOver"] != "cumulative-across-halves"):
        raise ValueError("objectiveScoreTimeline provenance is not official v1")
    if timeline["teams"] != [
        {"id": "team-1", "label": "Team 1"},
        {"id": "team-2", "label": "Team 2"},
    ]:
        raise ValueError("objectiveScoreTimeline must use neutral match-local teams")
    quality = timeline["quality"]
    if not isinstance(quality, dict) or set(quality) != {"status", "flags"}:
        raise ValueError("objectiveScoreTimeline quality schema is invalid")
    if quality["status"] not in {"complete", "partial", "unavailable"}:
        raise ValueError("objectiveScoreTimeline quality status is invalid")
    flags = quality["flags"]
    if (not isinstance(flags, list) or any(not isinstance(flag, str) for flag in flags)
            or flags != sorted(set(flags)) or not set(flags) <= _PUBLIC_QUALITY_FLAGS):
        raise ValueError("objectiveScoreTimeline quality flags are invalid")
    if quality["status"] == "complete" and flags:
        raise ValueError("complete objectiveScoreTimeline cannot carry quality flags")
    if quality["status"] != "complete" and not flags:
        raise ValueError("non-complete objectiveScoreTimeline needs a quality flag")
    if quality["status"] == "partial" and not set(flags) <= _PUBLIC_PARTIAL_QUALITY_FLAGS:
        raise ValueError("partial objectiveScoreTimeline contains a fatal quality flag")
    if quality["status"] == "unavailable" and not set(flags) & _PUBLIC_FATAL_QUALITY_FLAGS:
        raise ValueError("unavailable objectiveScoreTimeline needs a fatal quality flag")

    halves = timeline["halves"]
    if not isinstance(halves, list):
        raise ValueError("objectiveScoreTimeline halves must be a list")
    if quality["status"] == "unavailable":
        if halves:
            raise ValueError("unavailable objectiveScoreTimeline must expose no points")
    elif not halves:
        raise ValueError("available objectiveScoreTimeline needs at least one half")
    half_ids: list[int] = []
    previous_final: tuple[int, int] | None = None
    for half in halves:
        if not isinstance(half, dict) or set(half) != {"half", "points"}:
            raise ValueError("objectiveScoreTimeline half schema is invalid")
        half_id = _strict_int(half["half"], "public half", minimum=1, maximum=65_535)
        if half_id not in (1, 2) and half_id < 101:
            raise ValueError("public half identifier is invalid")
        half_ids.append(half_id)
        points = half["points"]
        if not isinstance(points, list) or not points:
            raise ValueError("available objectiveScoreTimeline half needs points")
        times: list[float] = []
        previous_scores: tuple[int, int] | None = None
        for point in points:
            if not isinstance(point, dict) or set(point) != {
                "halfTimeSeconds", "team1Score", "team2Score", "observationKind",
            }:
                raise ValueError("objectiveScoreTimeline point schema is invalid")
            seconds = point["halfTimeSeconds"]
            if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
                    or not math.isfinite(seconds) or seconds < 0):
                raise ValueError("halfTimeSeconds must be finite and non-negative")
            times.append(float(seconds))
            scores = (
                _strict_int(point["team1Score"], "team1Score"),
                _strict_int(point["team2Score"], "team2Score"),
            )
            if previous_scores is not None and any(
                current < previous
                for current, previous in zip(scores, previous_scores)
            ):
                raise ValueError("public score timeline cannot regress")
            previous_scores = scores
            if point["observationKind"] not in OBSERVATION_KINDS:
                raise ValueError("public observationKind is invalid")
        if times != sorted(times) or times[0] != 0:
            raise ValueError("public half times must be ordered from zero")
        if points[0]["observationKind"] != "baseline" or points[-1]["observationKind"] != "final":
            raise ValueError("public half must retain baseline and final boundaries")
        if any(point["observationKind"] == "baseline" for point in points[1:]):
            raise ValueError("public half can contain only one opening baseline")
        if any(point["observationKind"] == "final" for point in points[:-1]):
            raise ValueError("public half can contain only one closing final")
        opening = (points[0]["team1Score"], points[0]["team2Score"])
        if previous_final is not None and opening != previous_final:
            raise ValueError("public half score does not carry over")
        previous_final = (points[-1]["team1Score"], points[-1]["team2Score"])
    if half_ids != sorted(set(half_ids)):
        raise ValueError("public halves must be unique and ordered")
    return timeline


def _quality_status(flags: set[str], *, unavailable: bool) -> str:
    if unavailable:
        return "unavailable"
    if flags:
        return "partial"
    return "complete"


def _build_projection(halves: list[dict[str, Any]], flags: set[str], *, unavailable: bool,
                      context: ProjectionContext | None = None) -> ProjectionResult:
    timeline = {
        "source": OFFICIAL_SOURCE,
        "sourceVersion": SOURCE_VERSION,
        "scoringScope": "official-in-game-team-score",
        "carryOver": "cumulative-across-halves",
        "teams": [
            {"id": "team-1", "label": "Team 1"},
            {"id": "team-2", "label": "Team 2"},
        ],
        "halves": [] if unavailable else halves,
        "quality": {
            "status": _quality_status(flags, unavailable=unavailable),
            "flags": sorted(flags),
        },
    }
    dto = {"objectiveScoreTimeline": timeline}
    try:
        validate_public_projection(dto)
    except ValueError as exc:
        raise AssertionError(f"invalid public official-score DTO: {exc}") from exc
    body = _canonical_bytes(dto)
    digest = hashlib.sha256(body).hexdigest()
    release = {
        "schemaVersion": 1,
        "releaseId": f"objective-score-v1-{digest}",
        "contentSha256": digest,
        "contentBytes": len(body),
        "publicationState": "draft",
        "immutable": True,
    }
    private_release: dict[str, Any] = {
        "schemaVersion": 1,
        "objectiveScoreSha256": digest,
        "selectedMatchId": context.match_id if context else None,
        "analyticsFactsSha256": None,
        "context": None,
    }
    if context is not None:
        private_release["context"] = {
            "mapName": context.map_name,
            "matchType": context.match_type,
            "sourceServer": context.source_server,
            "terminalHalf": context.terminal_half,
            "eventCount": context.event_count,
            "officialRowCount": context.official_row_count,
            "retainedRowCount": context.retained_row_count,
            "eventsFileSha256": (
                context.events_file_sha256.hex() if context.events_file_sha256 else None
            ),
            "metadataFileSha256": (
                context.metadata_file_sha256.hex() if context.metadata_file_sha256 else None
            ),
            "ingestManifestSha256": (
                context.manifest_content_sha256.hex()
                if context.manifest_content_sha256 else None
            ),
            "observerClosed": context.observer_closed,
            "settled": context.settled,
            "lifecycleComplete": context.lifecycle_complete,
            "databaseContextValid": context.database_context_valid,
        }
    return ProjectionResult(
        dto=dto, canonical_json=body, sha256=digest,
        release_metadata=release, private_release_metadata=private_release,
    )


def unavailable_projection(*flags: str) -> ProjectionResult:
    selected = set(flags) or {"incomplete-stream"}
    return _build_projection([], selected, unavailable=True)


def projection_result_from_release(
    public_dto: Any, private_release_metadata: Any,
) -> ProjectionResult:
    """Rehydrate a projector release without trusting either JSON document.

    This is intentionally the only supported file boundary for downstream
    report tooling. A bare sanitized DTO has no private match/map binding and
    therefore cannot be joined safely to analytics facts.
    """
    validate_public_projection(public_dto)
    if not isinstance(private_release_metadata, dict) or set(private_release_metadata) != {
        "schemaVersion", "objectiveScoreSha256", "selectedMatchId",
        "analyticsFactsSha256", "context",
    }:
        raise ValueError("objective-score private release schema is invalid")
    if private_release_metadata.get("schemaVersion") != 1:
        raise ValueError("objective-score private release version is invalid")
    selected = private_release_metadata.get("selectedMatchId")
    if not isinstance(selected, str) or not selected or len(selected) > 64:
        raise ValueError("objective-score private release has no selected match")
    context = private_release_metadata.get("context")
    if not isinstance(context, dict) or not isinstance(context.get("mapName"), str):
        raise ValueError("objective-score private release has no map context")
    facts_digest = private_release_metadata.get("analyticsFactsSha256")
    if facts_digest is not None and not (
        isinstance(facts_digest, str) and re.fullmatch(r"[0-9a-f]{64}", facts_digest)
    ):
        raise ValueError("objective-score private release facts digest is invalid")
    body = _canonical_bytes(public_dto)
    digest = hashlib.sha256(body).hexdigest()
    if private_release_metadata.get("objectiveScoreSha256") != digest:
        raise ValueError("objective-score private release digest disagrees with public bytes")
    return ProjectionResult(
        dto=public_dto,
        canonical_json=body,
        sha256=digest,
        release_metadata={
            "schemaVersion": 1,
            "releaseId": f"objective-score-v1-{digest}",
            "contentSha256": digest,
            "contentBytes": len(body),
            "publicationState": "draft",
            "immutable": True,
        },
        private_release_metadata=dict(private_release_metadata),
    )


def bound_unavailable_projection(match_id: str, map_name: str,
                                 *flags: str) -> ProjectionResult:
    context = ProjectionContext(
        match_id=_required_text(match_id, "match_id", maximum=64),
        map_name=_required_text(map_name, "map_name", maximum=32),
        match_type=None, source_server=None, terminal_half=None,
        event_count=None, official_row_count=None, events_file_sha256=None,
        retained_row_count=None,
        metadata_file_sha256=None, manifest_content_sha256=None,
        observer_closed=False, settled=False, lifecycle_complete=False,
        database_context_valid=True,
    )
    return _build_projection(
        [], set(flags) or {"incomplete-stream"}, unavailable=True, context=context,
    )


def validate_private_projection_binding(
    result: ProjectionResult, *, analytics_match_id: str, analytics_map_name: str,
    analytics_facts_sha256: str,
) -> dict[str, Any]:
    """Validate the private join, then return only the public score DTO."""
    binding = result.private_release_metadata
    if not isinstance(binding, dict) or binding.get("schemaVersion") != 1:
        raise ValueError("objective-score private binding is missing")
    if binding.get("selectedMatchId") != analytics_match_id:
        raise ValueError("objective-score private binding selects a foreign match")
    if (not re.fullmatch(r"[0-9a-f]{64}", analytics_facts_sha256)
            or binding.get("analyticsFactsSha256") != analytics_facts_sha256):
        raise ValueError("objective-score private binding selects foreign analytics facts")
    context = binding.get("context")
    if not isinstance(context, dict) or context.get("mapName") != analytics_map_name:
        raise ValueError("objective-score private binding context disagrees with analytics")
    if binding.get("objectiveScoreSha256") != hashlib.sha256(
        _canonical_bytes(result.dto)
    ).hexdigest():
        raise ValueError("objective-score private binding digest disagrees with public bytes")
    validate_public_projection(result.dto)
    return result.dto


def bind_projection_to_analytics(
    result: ProjectionResult, *, analytics_match_id: str,
    analytics_map_name: str, analytics_facts_sha256: str,
) -> ProjectionResult:
    """Bind a private score release to the exact analytics input at join time.

    The score projection already owns its match/map/objective digest.  This
    function verifies those immutable fields before adding the private facts
    digest; no binding field is ever copied into the public DTO.
    """
    if not re.fullmatch(r"[0-9a-f]{64}", analytics_facts_sha256):
        raise ValueError("analytics facts digest must be lowercase SHA-256")
    binding = result.private_release_metadata
    if not isinstance(binding, dict) or binding.get("schemaVersion") != 1:
        raise ValueError("objective-score private binding is missing")
    if binding.get("selectedMatchId") != analytics_match_id:
        raise ValueError("objective-score private binding selects a foreign match")
    context = binding.get("context")
    if not isinstance(context, dict) or context.get("mapName") != analytics_map_name:
        raise ValueError("objective-score private binding context disagrees with analytics")
    if binding.get("objectiveScoreSha256") != hashlib.sha256(
        _canonical_bytes(result.dto)
    ).hexdigest():
        raise ValueError("objective-score private binding digest disagrees with public bytes")
    existing_facts_digest = binding.get("analyticsFactsSha256")
    if existing_facts_digest not in (None, analytics_facts_sha256):
        raise ValueError("objective-score private binding selects foreign analytics facts")
    bound = dict(binding)
    bound["analyticsFactsSha256"] = analytics_facts_sha256
    return replace(result, private_release_metadata=bound)


def project_official_score(
    rows: Sequence[TeamScoreObservation], *,
    conflict_keys: Iterable[tuple[int, Decimal, int]] = (),
    context: ProjectionContext | None = None,
    match_end: dict[str, Any] | None = None,
    late_recovery: bool = False,
) -> ProjectionResult:
    """Validate retained rows and build a strict team-only public projection.

    ``match_end`` is optional quality evidence only.  Its side-oriented values
    are compared to the final authoritative team_score row and never replace it.
    """
    flags: set[str] = set()
    fatal = False
    if late_recovery:
        flags.add("late-recovery")
    conflicts = set(conflict_keys)
    if conflicts:
        flags.add("conflicting-order-key")
        fatal = True
    if context is None or not (
        context.observer_closed and context.settled
        and context.lifecycle_complete and context.database_context_valid
        and context.terminal_half is not None
        and context.event_count is not None
        and context.official_row_count is not None
        and context.retained_row_count is not None
        and context.event_count >= context.official_row_count + 1
        and context.official_row_count >= context.retained_row_count
        and isinstance(context.events_file_sha256, bytes)
        and len(context.events_file_sha256) == 32
        and isinstance(context.metadata_file_sha256, bytes)
        and len(context.metadata_file_sha256) == 32
        and isinstance(context.manifest_content_sha256, bytes)
        and len(context.manifest_content_sha256) == 32
    ):
        flags.add("incomplete-stream")
        fatal = True
    if not rows:
        flags.add("incomplete-stream")
        return _build_projection([], flags, unavailable=True, context=context)

    # Validate every order-key component before sorting.  This API is also used
    # directly by post-match tooling, so malformed in-memory rows (for example
    # Decimal("NaN"), bool side slots, or an unsupported half) must become an
    # explicit unavailable result instead of escaping as a Python sort error.
    validated: list[TeamScoreObservation] = []
    for row in rows:
        row_valid = True
        try:
            if not isinstance(row.match_id, str) or not row.match_id or len(row.match_id) > 64:
                raise ValueError("match_id must be a non-empty string of at most 64 characters")
            _required_text(row.map_name, "map_name", maximum=32)
            _required_text(row.source_server, "source_server", maximum=128)
            _strict_int(row.match_type, "match_type", maximum=5)
            half = _strict_int(row.half, "half", minimum=1, maximum=65_535)
            if half not in (1, 2) and half < 101:
                raise ValueError("half must be 1, 2, or an overtime identifier >= 101")
            _strict_tick(row.tick_seconds)
            _strict_int(row.event_sequence, "event_sequence", minimum=1,
                        maximum=18_446_744_073_709_551_615)
            _strict_int(row.allies_score, "allies_score")
            _strict_int(row.axis_score, "axis_score")
            _strict_int(row.source_version, "source_version", minimum=1, maximum=1)
        except (TypeError, ValueError, InvalidOperation):
            flags.add("incomplete-stream")
            fatal = True
            row_valid = False
        try:
            allies_team = _strict_int(row.allies_team_id, "allies_team_id", minimum=1, maximum=2)
            axis_team = _strict_int(row.axis_team_id, "axis_team_id", minimum=1, maximum=2)
            if {allies_team, axis_team} != {1, 2}:
                raise ValueError("side mapping must contain both stable team slots")
        except (TypeError, ValueError):
            flags.add("side-mapping-unknown")
            fatal = True
            row_valid = False
        if row.source != OFFICIAL_SOURCE or row.source_version != SOURCE_VERSION:
            flags.add("incomplete-stream")
            fatal = True
            row_valid = False
        if row.observation_kind not in OBSERVATION_KINDS:
            flags.add("incomplete-stream")
            fatal = True
            row_valid = False
        if context is not None and (
            row.match_id != context.match_id or row.map_name != context.map_name
            or row.source_server != context.source_server
            or row.manifest_content_sha256 != context.manifest_content_sha256
            or context.match_type is None
            or not _type_allowed(context.match_type, row.match_type, row.half)
        ):
            flags.add("incomplete-stream")
            fatal = True
            row_valid = False
        if row_valid:
            validated.append(row)

    if not validated:
        flags.add("incomplete-stream")
        return _build_projection([], flags, unavailable=True, context=context)

    match_ids = {row.match_id for row in validated}
    if len(match_ids) != 1:
        flags.add("incomplete-stream")
        fatal = True
    ordered = sorted(validated, key=lambda row: (
        row.half, row.tick_seconds, row.event_sequence
    ))
    seen_order: dict[tuple[int, Decimal, int], TeamScoreObservation] = {}
    grouped: dict[int, list[TeamScoreObservation]] = defaultdict(list)
    for row in ordered:
        order_key = (row.half, row.tick_seconds, row.event_sequence)
        previous = seen_order.get(order_key)
        if previous is not None:
            if previous != row:
                flags.add("conflicting-order-key")
                fatal = True
            # An exact in-memory duplicate is idempotent just like the retained
            # database row.  Do not turn it into a sequence tie downstream.
            continue
        seen_order[order_key] = row
        grouped[row.half].append(row)

    if context is not None and context.retained_row_count != len(seen_order):
        flags.add("incomplete-stream")
        fatal = True

    half_ids = sorted(grouped)
    if context is not None and half_ids and max(half_ids) != context.terminal_half:
        flags.add("incomplete-stream")
        fatal = True
    if context is not None and half_ids:
        terminal = context.terminal_half
        expected_halves = (
            _expected_lifecycle_halves(context.match_type, terminal)
            if context.match_type is not None and terminal is not None else []
        )
        if half_ids != expected_halves:
            flags.add("incomplete-stream")
            fatal = True
    for previous, current in zip(half_ids, half_ids[1:]):
        allowed = (
            (previous == 1 and current == 2)
            or (previous == 2 and current == 101)
            or (previous >= 101 and current == previous + 1)
        )
        if not allowed:
            flags.add("incomplete-stream")
            fatal = True

    public_halves: list[dict[str, Any]] = []
    previous_final: dict[int, int] | None = None
    final_row: TeamScoreObservation | None = None
    final_scores: dict[int, int] | None = None
    for half in half_ids:
        half_rows = grouped[half]
        sequences = [row.event_sequence for row in half_rows]
        if len(sequences) != len(set(sequences)):
            flags.add("sequence-tie")
            fatal = True
        sequence_order = sorted(half_rows, key=lambda row: row.event_sequence)
        if any(current.tick_seconds < previous.tick_seconds
               for previous, current in zip(sequence_order, sequence_order[1:])):
            flags.add("source-time-regression")
            fatal = True
        if sequences and (min(sequences) != 1 or sorted(sequences) != list(range(1, max(sequences) + 1))):
            flags.add("sequence-gap")
        baselines = [row for row in half_rows if row.observation_kind == "baseline"]
        finals = [row for row in half_rows if row.observation_kind == "final"]
        if len(baselines) != 1 or half_rows[0].observation_kind != "baseline":
            flags.add("missing-half-start")
            fatal = True
        if not finals or half_rows[-1].observation_kind != "final":
            flags.add("missing-half-final")
            fatal = True
        if any(row.observation_kind != "final" for row in half_rows[half_rows.index(finals[0]) + 1:]) if finals else False:
            flags.add("missing-half-final")
            fatal = True
        # The producer can emit a final at half_end and another consecutive
        # final from changelevel/plugin_end. Retain all raw rows internally,
        # but publish exactly the last final as the authoritative close.
        mapping = {(row.allies_team_id, row.axis_team_id) for row in half_rows}
        if len(mapping) != 1:
            flags.add("side-mapping-unknown")
            fatal = True

        # Audit monotonicity across every retained observation before final
        # suffix normalization. A changed plugin_end final is legitimate only
        # when it advances (or repeats) stable-team scores; normalization must
        # never hide a descending raw final such as 5 -> 4.
        raw_stable_last: dict[int, int] | None = None
        for row in half_rows:
            raw_stable = {
                row.allies_team_id: row.allies_score,
                row.axis_team_id: row.axis_score,
            }
            if set(raw_stable) != {1, 2}:
                continue
            if raw_stable_last and any(
                raw_stable[team] < raw_stable_last[team] for team in (1, 2)
            ):
                flags.add("score-regression")
                fatal = True
            raw_stable_last = raw_stable

        normalized_rows = (
            half_rows[:half_rows.index(finals[0])] + [half_rows[-1]]
            if finals else half_rows
        )

        baseline_tick = half_rows[0].tick_seconds
        points: list[dict[str, Any]] = []
        stable_last: dict[int, int] | None = None
        opening: dict[int, int] | None = None
        for row in normalized_rows:
            stable = {
                row.allies_team_id: row.allies_score,
                row.axis_team_id: row.axis_score,
            }
            if set(stable) != {1, 2}:
                # The mapping defect is already a fatal quality flag.  Do not
                # index the malformed mapping while completing the audit.
                continue
            if opening is None:
                opening = dict(stable)
            stable_last = stable
            points.append({
                "halfTimeSeconds": _public_number(row.tick_seconds - baseline_tick),
                "team1Score": stable[1],
                "team2Score": stable[2],
                "observationKind": row.observation_kind,
            })
        if previous_final is not None and opening != previous_final:
            flags.add("half-carryover-mismatch")
            fatal = True
        if stable_last and previous_final and any(
            stable_last[team] < previous_final[team] for team in (1, 2)
        ):
            flags.add("score-regression")
            fatal = True
        previous_final = dict(stable_last or {})
        final_row = half_rows[-1]
        final_scores = stable_last
        public_halves.append({"half": half, "points": points})

    if match_end is None and context is not None and (
        context.match_end_allies_score is not None
        or context.match_end_axis_score is not None
    ):
        match_end = {
            "allies_score": context.match_end_allies_score,
            "axis_score": context.match_end_axis_score,
        }
    if match_end is not None:
        try:
            allies = _strict_int(match_end["allies_score"], "match_end.allies_score")
            axis = _strict_int(match_end["axis_score"], "match_end.axis_score")
        except (KeyError, ValueError):
            flags.add("match-end-disagreement")
        else:
            if final_row is None or final_scores is None:
                flags.add("match-end-disagreement")
            else:
                compared = {
                    final_row.allies_team_id: allies,
                    final_row.axis_team_id: axis,
                }
                if compared != final_scores:
                    flags.add("match-end-disagreement")

    return _build_projection(public_halves, flags, unavailable=fatal, context=context)
