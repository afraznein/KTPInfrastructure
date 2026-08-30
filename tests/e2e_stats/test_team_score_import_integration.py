from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts import team_score_telemetry as score
from scripts import project_team_score
from scripts.lane_b_e2e import import_lane_b_score_fixture
from tests.e2e_stats.ephemeral_mysql import EphemeralMysql, MysqlUnavailable


SOURCE_SERVER = "lane-b-score-fixture"


def event(*, half=1, tick=0.25, sequence=1, allies=0, axis=0,
          allies_team=1, axis_team=2, kind="baseline", match_id="db-match"):
    return {
        "tick": tick, "match_id": match_id, "map": "dod_anzio",
        "match_type": 0, "half": half, "plugin_sent_at": 1_787_000_000_123,
        "event": "team_score", "allies_score": allies, "axis_score": axis,
        "allies_team_slot": allies_team, "axis_team_slot": axis_team,
        "event_sequence": sequence, "source": score.OFFICIAL_SOURCE,
        "sample_kind": kind,
    }


def write_events(root: Path, values, *, match_id="db-match", match_type=0) -> Path:
    directory = root / match_id
    directory.mkdir(parents=True, exist_ok=True)
    values = list(values)
    official = [value for value in values if value.get("event") == "team_score"]
    terminal = max(value["half"] for value in official)
    last = next(value for value in reversed(official) if value["half"] == terminal)
    values.append({
        "event": "ktp_match_end", "match_id": match_id, "map": "dod_anzio",
        "match_type": last["match_type"], "half": terminal,
        "allies_score": last["allies_score"], "axis_score": last["axis_score"],
    })
    path = directory / "events.jsonl"
    path.write_text("".join(json.dumps(value, separators=(",", ":")) + "\n"
                            for value in values), encoding="utf-8")
    (directory / "metadata.json").write_text(json.dumps({
        "matchId": match_id, "map": "dod_anzio", "matchType": match_type,
        "half": 1, "startedAt": "2026-01-01T00:00:00Z",
        "endedAt": "2026-01-01T00:30:00Z", "eventCount": len(values),
        "sourceServer": SOURCE_SERVER,
    }, separators=(",", ":")), encoding="utf-8")
    return path


def prepare_match(db: EphemeralMysql, match_id: str, *, terminal_half=2,
                  match_type=0, half_ids=None) -> None:
    db.sql("""
CREATE TABLE IF NOT EXISTS ktp_matches (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  match_id VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  map_name VARCHAR(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  match_type TINYINT UNSIGNED NULL,
  half SMALLINT UNSIGNED NOT NULL,
  start_time DATETIME(3) NOT NULL,
  end_time DATETIME(3) NULL,
  KEY idx_match_id (match_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
""")
    values = []
    if half_ids is None:
        half_ids = ([1, 2] if terminal_half == 2 else
                    [1, 2, *range(101, terminal_half + 1)]
                    if terminal_half >= 101 else [1])
    for half in half_ids:
        row_type = (4 if match_type == 0 else 5) if half >= 101 else match_type
        values.append(
            f"('{match_id}','dod_anzio',{row_type},{half},"
            "'2026-01-01 00:00:00.000','2026-01-01 00:30:00.000')"
        )
    db.sql(
        "INSERT INTO ktp_matches "
        "(match_id,map_name,match_type,half,start_time,end_time) VALUES "
        + ",".join(values)
    )


def rows():
    return [
        event(),
        event(tick=120.5, sequence=2, allies=3, kind="change"),
        event(tick=1200.75, sequence=3, allies=3, kind="final"),
        event(half=2, tick=0.1, allies=0, axis=3,
              allies_team=2, axis_team=1, kind="baseline"),
        event(half=2, tick=1200.2, sequence=2, allies=2, axis=3,
              allies_team=2, axis_team=1, kind="final"),
    ]


def test_migration_import_idempotency_conflict_and_projection_against_mariadb(tmp_path):
    with EphemeralMysql.start(parent=tmp_path) as db:
        db.load_file(score.MIGRATION)
        db.load_file(score.MIGRATION)
        prepare_match(db, "db-match")
        mysql = score.MysqlCli(
            mysql_bin=db.client, database=db.database,
            socket=db.socket_path, user="root",
        )
        input_rows = list(reversed(rows()))
        input_rows.append(dict(input_rows[0]))
        path = write_events(tmp_path, input_rows)
        parsed = score.read_event_files(
            [path], source_server_roots={SOURCE_SERVER: path.parent.parent},
        )

        first = mysql.import_observations(parsed)
        assert (first.official_rows, first.inserted, first.idempotent_duplicates,
                first.conflict_keys) == (6, 5, 1, 0)
        assert db.count("SELECT COUNT(*) FROM ktp_team_score_observations") == 5
        assert db.scalar("SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
                         "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ktp_team_score_observations' "
                         "AND COLUMN_NAME='tick_seconds'") == "decimal(20,9) unsigned"

        second = mysql.import_observations(parsed)
        assert (second.inserted, second.idempotent_duplicates,
                second.conflict_keys) == (0, 6, 0)
        snapshot = mysql.fetch_match("db-match")
        projected = score.project_official_score(
            snapshot.rows, conflict_keys=snapshot.conflict_keys, context=snapshot.context,
        )
        assert projected.dto["objectiveScoreTimeline"]["quality"]["status"] == "complete"
        assert [half["half"] for half in projected.dto["objectiveScoreTimeline"]["halves"]] == [1, 2]

        release_dir = tmp_path / "release"
        project_args = [
            "--match-id", "db-match", "--output-dir", str(release_dir),
            "--mysql-bin", db.client, "--database", db.database,
            "--socket", str(db.socket_path), "--user", "root",
        ]
        assert project_team_score.main(project_args) == 0
        first_release_bytes = (release_dir / "objective-score-timeline.json").read_bytes()
        assert json.loads(first_release_bytes)["objectiveScoreTimeline"]["quality"]["status"] == "complete"
        # Same retained facts are an idempotent immutable release rerun.
        assert project_team_score.main(project_args) == 0
        assert (release_dir / "objective-score-timeline.json").read_bytes() == first_release_bytes

def test_same_batch_conflict_is_audited_and_no_arbitrary_incumbent_is_inserted(tmp_path):
    with EphemeralMysql.start(parent=tmp_path) as db:
        db.load_file(score.MIGRATION)
        prepare_match(db, "batch-conflict", terminal_half=1)
        mysql = score.MysqlCli(
            mysql_bin=db.client, database=db.database,
            socket=db.socket_path, user="root",
        )
        first = event(match_id="batch-conflict")
        second = dict(first, allies_score=4)
        path = write_events(tmp_path, [first, second], match_id="batch-conflict")
        result = mysql.import_observations(
            score.read_event_files(
                [path], source_server_roots={SOURCE_SERVER: path.parent.parent},
            )
        )
        assert result.inserted == 0
        assert result.conflicting_rows == 2
        assert result.conflict_keys == 1
        assert db.count("SELECT COUNT(*) FROM ktp_team_score_observations") == 0
        assert db.count("SELECT COUNT(*) FROM ktp_team_score_ingest_conflicts") == 1

        # Re-reading the identical closed file remains blocked by its durable
        # conflict audit and cannot select an arbitrary incumbent.
        again = mysql.import_observations(
            score.read_event_files(
                [path], source_server_roots={SOURCE_SERVER: path.parent.parent},
            )
        )
        assert again.inserted == 0
        assert again.conflict_keys == 1
        assert db.count("SELECT COUNT(*) FROM ktp_team_score_observations") == 0

        snapshot = mysql.fetch_match("batch-conflict")
        projected = score.project_official_score(
            snapshot.rows, conflict_keys=snapshot.conflict_keys, context=snapshot.context,
        )
        assert projected.dto["objectiveScoreTimeline"]["quality"]["status"] == "unavailable"


def test_migration_repairs_missing_index_and_rejects_incompatible_schema(tmp_path):
    with EphemeralMysql.start(parent=tmp_path) as db:
        db.load_file(score.MIGRATION)
        db.sql("ALTER TABLE ktp_team_score_observations DROP INDEX idx_team_score_retention")
        db.load_file(score.MIGRATION)
        assert db.count("""
SELECT COUNT(*) FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ktp_team_score_observations'
AND INDEX_NAME='idx_team_score_retention'
""") == 2
        db.sql("ALTER TABLE ktp_team_score_observations MODIFY map_name VARCHAR(33) NOT NULL")
        with pytest.raises(MysqlUnavailable, match="ERROR_023_team_score_observation"):
            db.load_file(score.MIGRATION)


def test_migration_rejects_an_extra_unique_constraint(tmp_path):
    with EphemeralMysql.start(parent=tmp_path) as db:
        db.load_file(score.MIGRATION)
        db.sql("ALTER TABLE ktp_team_score_ingest_manifests "
               "ADD UNIQUE KEY unexpected_unique_source (source_server)")
        with pytest.raises(MysqlUnavailable, match="ERROR_023_team_score_manifest"):
            db.load_file(score.MIGRATION)


@pytest.mark.parametrize("mutation", ["default", "foreign-key", "check"])
def test_migration_rejects_default_foreign_key_or_check_drift(tmp_path, mutation):
    with EphemeralMysql.start(parent=tmp_path) as db:
        db.load_file(score.MIGRATION)
        if mutation == "default":
            db.sql("ALTER TABLE ktp_team_score_ingest_manifests "
                   "MODIFY ingested_at TIMESTAMP(3) NOT NULL")
        elif mutation == "foreign-key":
            db.sql("ALTER TABLE ktp_team_score_observations "
                   "DROP FOREIGN KEY fk_team_score_observation_manifest")
            db.sql("ALTER TABLE ktp_team_score_observations "
                   "ADD CONSTRAINT fk_team_score_observation_manifest "
                   "FOREIGN KEY (match_id) REFERENCES ktp_team_score_ingest_manifests(match_id) "
                   "ON UPDATE RESTRICT ON DELETE CASCADE")
        else:
            db.sql("ALTER TABLE ktp_team_score_observations "
                   "DROP CONSTRAINT chk_team_score_source_version")
            db.sql("ALTER TABLE ktp_team_score_observations "
                   "ADD CONSTRAINT chk_team_score_source_version CHECK (source_version >= 1)")
        with pytest.raises(MysqlUnavailable, match="ERROR_023_team_score"):
            db.load_file(score.MIGRATION)


def test_modified_settled_file_is_rejected_and_durably_audited(tmp_path):
    with EphemeralMysql.start(parent=tmp_path) as db:
        db.load_file(score.MIGRATION)
        prepare_match(db, "tamper-TEST", terminal_half=1)
        mysql = score.MysqlCli(
            mysql_bin=db.client, database=db.database,
            socket=db.socket_path, user="root",
        )
        path = write_events(tmp_path, [
            event(match_id="tamper-TEST"),
            event(match_id="tamper-TEST", tick=10, sequence=2, allies=1, kind="final"),
        ], match_id="tamper-TEST")
        accepted = score.read_event_files(
            [path], source_server_roots={SOURCE_SERVER: path.parent.parent},
        )
        assert mysql.import_observations(accepted).inserted == 2
        accepted_manifest = db.scalar(
            "SELECT HEX(manifest_content_sha256) FROM ktp_team_score_ingest_manifests "
            "WHERE match_id='tamper-TEST'"
        )

        path = write_events(tmp_path, [
            event(match_id="tamper-TEST"),
            event(match_id="tamper-TEST", tick=10, sequence=2, allies=2, kind="final"),
        ], match_id="tamper-TEST")
        attempted = score.read_event_files(
            [path], source_server_roots={SOURCE_SERVER: path.parent.parent},
        )
        with pytest.raises(score.MysqlCommandError, match="manifest/file identity"):
            mysql.import_observations(attempted)
        assert db.count("SELECT COUNT(*) FROM ktp_team_score_ingest_audits "
                        "WHERE match_id='tamper-TEST' AND audit_kind='manifest-mismatch'") == 1
        assert db.scalar(
            "SELECT HEX(manifest_content_sha256) FROM ktp_team_score_ingest_manifests "
            "WHERE match_id='tamper-TEST'"
        ) == accepted_manifest
        assert db.count("SELECT COUNT(*) FROM ktp_team_score_observations "
                        "WHERE match_id='tamper-TEST'") == 2
        snapshot = mysql.fetch_match("tamper-TEST")
        assert snapshot.context.database_context_valid is False


def _ot_rows(match_id):
    return [
        event(match_id=match_id),
        event(match_id=match_id, tick=10, sequence=2, allies=1, kind="final"),
        event(match_id=match_id, half=2, allies=0, axis=1,
              allies_team=2, axis_team=1),
        event(match_id=match_id, half=2, tick=10, sequence=2, allies=0, axis=1,
              allies_team=2, axis_team=1, kind="final"),
        dict(event(match_id=match_id, half=101, allies=1, axis=0), match_type=4),
        dict(event(match_id=match_id, half=101, tick=10, sequence=2,
                   allies=2, axis=0, kind="final"), match_type=4),
        dict(event(match_id=match_id, half=102, allies=0, axis=2,
                   allies_team=2, axis_team=1), match_type=4),
        dict(event(match_id=match_id, half=102, tick=10, sequence=2,
                   allies=0, axis=2, allies_team=2, axis_team=1,
                   kind="final"), match_type=4),
    ]


def test_importer_requires_exact_regulation_and_ot_half_set(tmp_path):
    with EphemeralMysql.start(parent=tmp_path) as db:
        db.load_file(score.MIGRATION)
        mysql = score.MysqlCli(
            mysql_bin=db.client, database=db.database,
            socket=db.socket_path, user="root",
        )
        prepare_match(db, "ot-valid", terminal_half=102, match_type=0)
        valid_path = write_events(tmp_path, _ot_rows("ot-valid"), match_id="ot-valid")
        valid = score.read_event_files(
            [valid_path], source_server_roots={SOURCE_SERVER: valid_path.parent.parent},
        )
        assert mysql.import_observations(valid).inserted == 8

        prepare_match(db, "ot-gap", terminal_half=102, match_type=0,
                      half_ids=[1, 2, 102])
        gap_path = write_events(tmp_path, _ot_rows("ot-gap"), match_id="ot-gap")
        gap = score.read_event_files(
            [gap_path], source_server_roots={SOURCE_SERVER: gap_path.parent.parent},
        )
        with pytest.raises(score.MysqlCommandError, match="ktp_matches context"):
            mysql.import_observations(gap)


@pytest.mark.parametrize("half_ids", [[2], [1, 3], [1, 100]])
def test_importer_rejects_missing_or_unexpected_database_halves(tmp_path, half_ids):
    with EphemeralMysql.start(parent=tmp_path) as db:
        db.load_file(score.MIGRATION)
        match_id = "bad-halves-" + "-".join(map(str, half_ids))
        terminal = 2 if half_ids == [2] else 1
        prepare_match(db, match_id, terminal_half=terminal, match_type=0,
                      half_ids=half_ids)
        path = write_events(tmp_path, [
            event(match_id=match_id),
            event(match_id=match_id, tick=10, sequence=2, kind="final"),
        ], match_id=match_id)
        parsed = score.read_event_files(
            [path], source_server_roots={SOURCE_SERVER: path.parent.parent},
        )
        mysql = score.MysqlCli(
            mysql_bin=db.client, database=db.database,
            socket=db.socket_path, user="root",
        )
        with pytest.raises(score.MysqlCommandError, match="ktp_matches context"):
            mysql.import_observations(parsed)


def test_actual_lane_b_fixture_import_projection_path_is_available(tmp_path):
    with EphemeralMysql.start(parent=tmp_path) as db:
        db.load_file(score.MIGRATION)
        prepare_match(db, "lane-b-score-TEST", terminal_half=1)
        template = (
            Path(__file__).parent / "fixtures" / "team_score"
            / "lane-b-observer-template.json"
        )
        result = import_lane_b_score_fixture(
            db, match_id="lane-b-score-TEST", template_path=template,
            output_root=tmp_path / "retained-observer",
        )
        timeline = result.dto["objectiveScoreTimeline"]
        assert timeline["quality"] == {"status": "complete", "flags": []}
        assert [point["observationKind"] for point in timeline["halves"][0]["points"]] == [
            "baseline", "change", "final",
        ]
        assert timeline["halves"][0]["points"][-1]["team1Score"] == 1
