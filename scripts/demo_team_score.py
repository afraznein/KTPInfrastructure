"""Winner labels from HLTV demos, as a second producer of the team-score ledger.

The engine's own scoreboard TeamScore is what fit_flag_swing.py and the MMR
ladder demand as the authoritative half outcome. dod-tools decodes it straight
out of a demo's TeamScore user messages and resets at match-live, so a demo
yields the label with no dependency on the HUD observer or on the daemon.

Facts this module is built on, all measured 2026-09-17 against real S10 demos
and ktpleague.gg's admin-entered scores (8 of 8 official matches matched
exactly on totals, per-half exact where the site shows halves):

- The engine resets TeamScore at match-live but NOT at the half swap, so a
  half-2 demo reports the running match total. Half scores are derived by
  differencing per stable roster slot, never per side.
- The ledger convention is cumulative too: team_score_telemetry.py's
  half-carryover-mismatch check requires half 2's opening to equal half 1's
  final. So rows here carry the demo's raw cumulative values, one baseline and
  one final per half, and the carryover holds by construction.
- Roster slot 1 is whoever was Allies in half 1; slot 2 the Axis roster. That
  is the ledger's stable-slot contract (allies_team_id / axis_team_id in {1,2}).
- Official matches carry casters/admins as spectators; they are not a roster.

Provenance is kept honest: rows go in under their own ``source`` and
``producer`` strings and never under the HUD's, and the per-match ingest
manifest the ledger's foreign key requires is written with the demo files as
its evidence. A match already owned by a different producer is left alone.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Sequence

from scripts.report_scope import MATCH_TYPE_BY_DEMO_LABEL  # noqa: E402 - sibling module
from scripts.team_score_telemetry import (  # noqa: E402 - sibling module
    LEDGER_LOCK, TeamScoreObservation, _sql_binary, _sql_decimal, _sql_text,
    retention_class,
)

SOURCE = "hltv-demo-team-score-v1"
SOURCE_VERSION = 1
PRODUCER = "hltv-demo"  # ktp_team_score_*.producer, VARCHAR(32) ascii
TOOL = "dod-tools"
TOOL_VERSION = "0.10.0"  # pinned in build/dod-tools/

# 12man_1.3-6744-ATL1_h1-2609070000-dod_armory_b6.dem  /  ktp_1789326428-NY1_h2-2609131529-dod_thunder2_part2.dem
DEMO_NAME = re.compile(
    r"^(?P<type>[a-z0-9]+)_(?P<match>(?:\d+|1\.3-\d+)-[A-Z]{2,5}\d+)_h(?P<half>\d+)"
    r"-(?P<stamp>\d{10})-(?P<map>.+?)(?:_part(?P<part>\d+))?\.dem$"
)
SIDES = ("allies", "axis")


class DemoLabelError(ValueError):
    pass


@dataclass(frozen=True)
class DemoName:
    type: str
    match_id: str
    half: int
    stamp: str
    map_name: str
    part: int | None

    @property
    def match_type(self) -> int:
        try:
            return MATCH_TYPE_BY_DEMO_LABEL[self.type]
        except KeyError:
            raise DemoLabelError(f"unknown demo type {self.type!r}") from None

    @property
    def server(self) -> str:
        return self.match_id.rsplit("-", 1)[-1]

    @property
    def started_at(self) -> str:
        return datetime.strptime("20" + self.stamp, "%Y%m%d%H%M").strftime("%Y-%m-%d %H:%M:%S.000")


def parse_demo_name(name: str) -> DemoName:
    m = DEMO_NAME.match(name)
    if not m:
        raise DemoLabelError(f"unrecognised demo name: {name}")
    return DemoName(m["type"].lower(), m["match"], int(m["half"]), m["stamp"], m["map"],
                    int(m["part"]) if m["part"] else None)


def account(steam_id: str) -> str:
    """'STEAM_0:1:16151757' -> '16151757'. Demo and report disagree on the auth bit
    for about half a roster (knowledge/KTPInfrastructure.md); the account number is
    what both agree on."""
    return steam_id.strip().split(":")[-1]


@dataclass(frozen=True)
class HalfDemo:
    """One demo file, decoded: cumulative scores by side and rosters by side."""
    name: DemoName
    file_name: str
    allies_score: int
    axis_score: int
    allies_roster: tuple[str, ...]
    axis_roster: tuple[str, ...]
    spectators: tuple[str, ...]
    file_sha256: bytes
    path_sha256: bytes


def run_dod_tools(cli: Path, demo: Path) -> dict[str, Any]:
    out = subprocess.run([str(cli), "--output-format", "json", str(demo)],
                         capture_output=True, check=True).stdout
    reports = json.loads(out.decode("utf-8", "replace"))
    if not isinstance(reports, list) or len(reports) != 1:
        raise DemoLabelError(f"dod-tools returned {len(reports) if isinstance(reports, list) else 'non-list'} reports for {demo.name}")
    return reports[0]


def half_from_report(report: dict[str, Any], file_name: str, *, file_sha256: bytes,
                     archive_path: str) -> HalfDemo:
    """Turn one dod-tools JSON report into a HalfDemo. No I/O; unit-testable."""
    name = parse_demo_name(file_name)
    teams = report.get("teams") or {}
    for side in SIDES:
        if not isinstance(teams.get(side), int) or teams[side] < 0:
            raise DemoLabelError(f"{file_name}: missing or invalid {side} score")
    rosters: dict[str, list[str]] = {"allies": [], "axis": []}
    spectators: list[str] = []
    for p in report.get("players") or []:
        side = p.get("team")
        if side in rosters:
            rosters[side].append(account(p["id"]))
        else:
            spectators.append(str(p.get("name", "")))
    if not rosters["allies"] or not rosters["axis"]:
        raise DemoLabelError(f"{file_name}: a side has no players")
    return HalfDemo(
        name=name, file_name=file_name,
        allies_score=teams["allies"], axis_score=teams["axis"],
        allies_roster=tuple(sorted(rosters["allies"])), axis_roster=tuple(sorted(rosters["axis"])),
        spectators=tuple(spectators),
        file_sha256=file_sha256, path_sha256=hashlib.sha256(archive_path.encode()).digest(),
    )


@dataclass(frozen=True)
class HalfLabel:
    demo: HalfDemo
    allies_slot: int          # stable roster slot on Allies this half (1 or 2)
    axis_slot: int
    cumulative: dict[int, int]  # slot -> cumulative score at end of this half
    half_score: dict[int, int]  # slot -> this half only
    winner_slot: int | None     # slot that won the half, None on a draw

    @property
    def winner_team(self) -> int | None:
        """fit_flag_swing convention: 1 when the Allies side won the half, 2 Axis."""
        if self.winner_slot is None:
            return None
        return 1 if self.winner_slot == self.allies_slot else 2


@dataclass(frozen=True)
class MatchLabel:
    match_id: str
    match_type: int
    map_name: str
    server: str
    halves: tuple[HalfLabel, ...]
    rosters: dict[int, tuple[str, ...]]  # slot -> accounts
    totals: dict[int, int]               # slot -> final cumulative
    side_swap_seen: bool

    @property
    def winner_slot(self) -> int | None:
        a, b = self.totals[1], self.totals[2]
        return 1 if a > b else 2 if b > a else None


def label_match(halves: Sequence[HalfDemo]) -> MatchLabel:
    """Attach winners to stable roster slots across the side swap."""
    if not halves:
        raise DemoLabelError("no halves")
    halves = sorted(halves, key=lambda h: (h.name.half, h.name.part or 0))
    first = halves[0]
    ids = {h.name.match_id for h in halves}
    if len(ids) != 1:
        raise DemoLabelError(f"halves from different matches: {sorted(ids)}")
    if first.name.half != 1:
        raise DemoLabelError(f"{first.name.match_id}: half 1 missing, cannot fix roster slots")
    # `_partN` files are HLTV rotation splits; the last part carries the final score.
    by_half: dict[int, HalfDemo] = {}
    for h in halves:
        by_half[h.name.half] = h
    ordered = [by_half[k] for k in sorted(by_half)]

    slot1 = set(ordered[0].allies_roster)
    prev = {1: 0, 2: 0}
    out: list[HalfLabel] = []
    swap_ok = True
    for h in ordered:
        on_allies = set(h.allies_roster)
        # majority vote survives a sub or a late joiner
        slot1_is_allies = len(on_allies & slot1) >= len(on_allies) / 2
        allies_slot, axis_slot = (1, 2) if slot1_is_allies else (2, 1)
        if h.name.half == 2 and slot1_is_allies:
            swap_ok = False
        cum = {allies_slot: h.allies_score, axis_slot: h.axis_score}
        for slot in (1, 2):
            if cum[slot] < prev[slot]:
                raise DemoLabelError(
                    f"{h.name.match_id} h{h.name.half}: slot {slot} regressed {prev[slot]} -> {cum[slot]}; "
                    "cumulative convention violated (a mid-match restart?)")
        half = {slot: cum[slot] - prev[slot] for slot in (1, 2)}
        winner = 1 if half[1] > half[2] else 2 if half[2] > half[1] else None
        out.append(HalfLabel(h, allies_slot, axis_slot, cum, half, winner))
        prev = cum
    return MatchLabel(
        match_id=first.name.match_id, match_type=first.name.match_type, map_name=first.name.map_name,
        server=first.name.server, halves=tuple(out),
        rosters={1: tuple(sorted(slot1)), 2: tuple(ordered[0].axis_roster)},
        totals=prev, side_swap_seen=swap_ok,
    )


def group_by_match(halves: Iterable[HalfDemo]) -> dict[str, list[HalfDemo]]:
    groups: dict[str, list[HalfDemo]] = {}
    for h in halves:
        groups.setdefault(h.name.match_id, []).append(h)
    return groups


# --------------------------------------------------------------------------- rows

@dataclass(frozen=True)
class DemoManifest:
    """One row for ktp_team_score_ingest_manifests, which the observations FK requires.

    The table was shaped for the HUD observer, so the evidence columns are reused
    with the demo files as the evidence: events_* = half-1 demo, metadata_* =
    last-half demo. Documented here and in every row's raw_event_json so a reader
    of the table is never guessing.
    """
    match_id: str
    map_name: str
    match_type: int
    source_server: str
    observer_started_at: str
    observer_ended_at: str
    terminal_half: int
    event_count: int
    events_file_sha256: bytes
    metadata_file_sha256: bytes
    events_path_sha256: bytes
    metadata_path_sha256: bytes
    manifest_content_sha256: bytes
    match_end_allies_score: int
    match_end_axis_score: int
    retention_class: str


def build_rows(label: MatchLabel, *, manifest_sha256: bytes) -> tuple[list[TeamScoreObservation], DemoManifest]:
    rows: list[TeamScoreObservation] = []
    prev_cum: dict[int, int] | None = None
    for hl in label.halves:
        d = hl.demo
        if prev_cum is None:
            b_allies, b_axis = 0, 0
        else:
            b_allies, b_axis = prev_cum[hl.allies_slot], prev_cum[hl.axis_slot]
        common = {
            "event": "team_score", "source": SOURCE, "source_version": SOURCE_VERSION, "producer": PRODUCER,
            "tool": f"{TOOL} {TOOL_VERSION}", "demo": d.file_name,
            "matchId": label.match_id, "map": label.map_name, "matchType": label.match_type, "half": d.name.half,
            "allies_team_slot": hl.allies_slot, "axis_team_slot": hl.axis_slot,
            "convention": "scores are cumulative since match-live, as the engine reports them; "
                          "half scores = difference per stable slot",
            "tick_seconds": "not derived from the demo; baseline=0, final=end of half",
        }
        for kind, seq, a, x in (("baseline", 1, b_allies, b_axis), ("final", 2, d.allies_score, d.axis_score)):
            raw = dict(common, sample_kind=kind, allies_score=a, axis_score=x)
            if kind == "final":
                raw["derived_half_score"] = {"slot1": hl.half_score[1], "slot2": hl.half_score[2]}
                raw["winner_team"] = hl.winner_team
                raw["winner_slot"] = hl.winner_slot
            raw_json = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            rows.append(TeamScoreObservation(
                match_id=label.match_id, match_type=label.match_type, half=d.name.half,
                tick_seconds=Decimal(0), event_sequence=seq, observed_at=d.name.started_at,
                allies_score=a, axis_score=x, allies_team_id=hl.allies_slot, axis_team_id=hl.axis_slot,
                map_name=label.map_name, source_server=label.server,
                source=SOURCE, source_version=SOURCE_VERSION, observation_kind=kind,
                retention_class=retention_class(label.match_type, label.match_id),
                manifest_content_sha256=manifest_sha256,
                raw_event_json=raw_json, raw_event_sha256=hashlib.sha256(raw_json.encode()).digest(),
                source_file_sha256=d.file_sha256, source_path_sha256=d.path_sha256,
                source_line_number=0,
            ))
        prev_cum = hl.cumulative
    first, last = label.halves[0], label.halves[-1]
    manifest = DemoManifest(
        match_id=label.match_id, map_name=label.map_name, match_type=label.match_type,
        source_server=label.server,
        observer_started_at=first.demo.name.started_at, observer_ended_at=last.demo.name.started_at,
        terminal_half=last.demo.name.half, event_count=len(rows),
        events_file_sha256=first.demo.file_sha256, metadata_file_sha256=last.demo.file_sha256,
        events_path_sha256=first.demo.path_sha256, metadata_path_sha256=last.demo.path_sha256,
        manifest_content_sha256=manifest_sha256,
        match_end_allies_score=last.demo.allies_score, match_end_axis_score=last.demo.axis_score,
        retention_class=retention_class(label.match_type, label.match_id),
    )
    return rows, manifest


def build_import_sql(rows: Sequence[TeamScoreObservation], manifests: Sequence[DemoManifest]) -> str:
    """One lock-serialized transaction, idempotent, that never touches another producer's match.

    Mirrors team_score_telemetry.build_import_sql's shape: typed temporary
    staging tables, then INSERT ... SELECT. A match whose manifest belongs to a
    different producer is excluded from both inserts; re-running is a no-op on
    the ledger's unique keys.
    """
    if not manifests:
        return ("SELECT 'KTP_DEMO_TEAM_SCORE_RESULT' AS result,"
                "0 AS manifests,0 AS observations,0 AS skipped_other_producer;" + chr(10))
    prod = _sql_text(PRODUCER)
    mvals = []
    for m in manifests:
        mvals.append("(" + ",".join((
            _sql_text(m.match_id), _sql_text(m.map_name), str(m.match_type), _sql_text(m.source_server),
            prod, f"'{m.observer_started_at}'", f"'{m.observer_ended_at}'",
            str(m.terminal_half), str(m.event_count), str(m.event_count), str(m.event_count), "1", "0",
            _sql_binary(m.events_file_sha256), _sql_binary(m.metadata_file_sha256),
            _sql_binary(m.events_path_sha256), _sql_binary(m.metadata_path_sha256),
            _sql_binary(m.manifest_content_sha256),
            str(m.match_end_allies_score), str(m.match_end_axis_score), _sql_text(m.retention_class),
        )) + ")")
    rvals = []
    for r in rows:
        rvals.append("(" + ",".join((
            _sql_text(r.match_id), str(r.match_type), str(r.half), _sql_text(r.map_name),
            _sql_text(r.source_server), _sql_decimal(r.tick_seconds), str(r.event_sequence),
            "NULL" if r.observed_at is None else f"'{r.observed_at}'",
            str(r.allies_score), str(r.axis_score), str(r.allies_team_id), str(r.axis_team_id),
            _sql_text(r.source), str(r.source_version), prod,
            _sql_text(r.observation_kind), _sql_text(r.retention_class),
            _sql_binary(r.manifest_content_sha256), _sql_text(r.raw_event_json), _sql_binary(r.raw_event_sha256),
            _sql_binary(r.source_file_sha256), _sql_binary(r.source_path_sha256),
            str(r.source_line_number),
        )) + ")")
    mcols = ("match_id,map_name,match_type,source_server,producer,observer_started_at,observer_ended_at,"
             "terminal_half,event_count,official_row_count,retained_row_count,lifecycle_complete,settlement_seconds,"
             "events_file_sha256,metadata_file_sha256,events_path_sha256,metadata_path_sha256,manifest_content_sha256,"
             "match_end_allies_score,match_end_axis_score,retention_class")
    rcols = ("match_id,match_type,half,map_name,source_server,tick_seconds,event_sequence,observed_at,"
             "allies_score,axis_score,allies_team_id,axis_team_id,source,source_version,producer,"
             "observation_kind,retention_class,manifest_content_sha256,raw_event_json,raw_event_sha256,"
             "source_file_sha256,source_path_sha256,source_line_number")
    return f"""
SELECT GET_LOCK('{LEDGER_LOCK}',30) INTO @ktp_demo_ts_lock;
START TRANSACTION;
CREATE TEMPORARY TABLE `ktp_demo_ts_manifest_stage` (
  `match_id` VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL PRIMARY KEY,
  `map_name` VARCHAR(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `match_type` TINYINT UNSIGNED NOT NULL,
  `source_server` VARCHAR(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `producer` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
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
INSERT INTO `ktp_demo_ts_manifest_stage` VALUES
{",".join(mvals)};
CREATE TEMPORARY TABLE `ktp_demo_ts_row_stage` (
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
  `producer` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `observation_kind` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `retention_class` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `manifest_content_sha256` BINARY(32) NOT NULL,
  `raw_event_json` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  `raw_event_sha256` BINARY(32) NOT NULL,
  `source_file_sha256` BINARY(32) NOT NULL,
  `source_path_sha256` BINARY(32) NOT NULL,
  `source_line_number` BIGINT UNSIGNED NOT NULL
) ENGINE=InnoDB;
INSERT INTO `ktp_demo_ts_row_stage` VALUES
{",".join(rvals)};
-- A match whose manifest belongs to another producer is skipped in both inserts.
CREATE TEMPORARY TABLE `ktp_demo_ts_skip` AS
  SELECT m.match_id FROM `ktp_team_score_ingest_manifests` m
  JOIN `ktp_demo_ts_manifest_stage` s ON s.match_id=m.match_id
  WHERE m.producer<>{prod};
INSERT INTO `ktp_team_score_ingest_manifests` ({mcols})
  SELECT {mcols} FROM `ktp_demo_ts_manifest_stage`
  WHERE match_id NOT IN (SELECT match_id FROM `ktp_demo_ts_skip`)
  -- qualified: unqualified here resolves against both the target and the
  -- SELECT's table, and MySQL rejects that as ambiguous (1052).
  ON DUPLICATE KEY UPDATE `ktp_team_score_ingest_manifests`.`match_id` = `ktp_team_score_ingest_manifests`.`match_id`;
INSERT INTO `ktp_team_score_observations` ({rcols})
  SELECT {rcols} FROM `ktp_demo_ts_row_stage`
  WHERE match_id NOT IN (SELECT match_id FROM `ktp_demo_ts_skip`)
  ON DUPLICATE KEY UPDATE id=id;
-- A second copy of the staged ids: MySQL cannot reference one TEMPORARY table
-- twice in a single statement, and the result row counts against it twice (1137).
CREATE TEMPORARY TABLE `ktp_demo_ts_manifest_ids` ENGINE=InnoDB AS
  SELECT match_id FROM `ktp_demo_ts_manifest_stage`;
SELECT 'KTP_DEMO_TEAM_SCORE_RESULT' AS result,
  (SELECT COUNT(*) FROM `ktp_team_score_ingest_manifests` m JOIN `ktp_demo_ts_manifest_stage` s ON s.match_id=m.match_id WHERE m.producer={prod}) AS manifests,
  (SELECT COUNT(*) FROM `ktp_team_score_observations` o JOIN `ktp_demo_ts_manifest_ids` s ON s.match_id=o.match_id WHERE o.producer={prod}) AS observations,
  (SELECT COUNT(*) FROM `ktp_demo_ts_skip`) AS skipped_other_producer,
  @ktp_demo_ts_lock AS lock_acquired;
COMMIT;
DROP TEMPORARY TABLE `ktp_demo_ts_manifest_ids`;
DROP TEMPORARY TABLE `ktp_demo_ts_skip`;
DROP TEMPORARY TABLE `ktp_demo_ts_row_stage`;
DROP TEMPORARY TABLE `ktp_demo_ts_manifest_stage`;
DO RELEASE_LOCK('{LEDGER_LOCK}');
"""


def labels_from_reports(reports: Iterable[tuple[str, dict[str, Any], bytes, str]]) -> list[MatchLabel]:
    """(file_name, dod-tools json, file sha256, archive path) -> labels, grouped per match."""
    halves = [half_from_report(rep, name, file_sha256=sha, archive_path=path) for name, rep, sha, path in reports]
    return [label_match(group) for _, group in sorted(group_by_match(halves).items())]


def sql_for_labels(labels: Sequence[MatchLabel]) -> tuple[str, list[TeamScoreObservation], list[DemoManifest]]:
    canon = json.dumps([
        {"match": l.match_id, "totals": l.totals, "halves": [(h.demo.file_name, h.cumulative) for h in l.halves]}
        for l in labels
    ], sort_keys=True, separators=(",", ":")).encode()
    manifest_sha = hashlib.sha256(canon).digest()
    rows: list[TeamScoreObservation] = []
    manifests: list[DemoManifest] = []
    for label in labels:
        r, m = build_rows(label, manifest_sha256=manifest_sha)
        rows.extend(r)
        manifests.append(m)
    return build_import_sql(rows, manifests), rows, manifests
