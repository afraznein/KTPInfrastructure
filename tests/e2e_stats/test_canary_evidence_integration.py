from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from scripts import canary_evidence
from scripts import match_analytics as analytics
from tests.e2e_stats.ephemeral_mysql import EphemeralMysql


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/e2e_stats/fixtures/analytics-phase-a-contract.sql"


def test_contract_fixture_builds_complete_canary_bundle(tmp_path):
    with EphemeralMysql.start(parent=tmp_path) as db:
        analytics.load_fixture(db, FIXTURE)
        sources = analytics.source_capabilities(db)
        report = analytics.build_report(db, "phase-a-contract-TEST", FIXTURE, sources)
        classifications = canary_evidence.collect_classification(
            db, "phase-a-contract-TEST"
        )
        ownership = canary_evidence.collect_ownership(
            db, "phase-a-contract-TEST", True
        )
        activation = canary_evidence.collect_capture_activation(
            db, "phase-a-contract-TEST", sources
        )
        flag_positions = canary_evidence.collect_flag_positions(
            db, "phase-a-contract-TEST", True
        )
        cap_breaks = canary_evidence.collect_cap_breaks(
            db, "phase-a-contract-TEST"
        )

    evidence = canary_evidence.build_evidence(
        report, classifications, ownership,
        canary_evidence.inspect_logs([]),
        {"fixture": FIXTURE.name, "fixture_sha256": "test"},
        capture_activation=activation,
        flag_positions=flag_positions,
        cap_break_rows=cap_breaks,
        expected_server_id=2,
        as_of=datetime(2026, 8, 17, tzinfo=timezone.utc),
    )
    assert evidence["status"] == "WARN"  # logs deliberately omitted
    assert evidence["match_type"]["match_type_name"] == "official"
    assert evidence["ownership"]["baseline_ok"] is True
    assert evidence["ownership"]["transition_count"] == 2
    assert evidence["capture_activation"]["frag_producer_coverage_pct"] == 100.0
    assert evidence["capture_activation"]["damage_producer_coverage_pct"] == 100.0
    assert evidence["capture_activation"]["life_active"] is True
    assert evidence["capture_activation"]["assist_reconciled"] is True
    assert evidence["objective_classification"][
        "trusted_for_capout_and_last_flag"
    ] is False
    assert evidence["cap_breaks"]["cappers_stopped"] == 2
    assert evidence["analytics_coverage"]["players"] == 12
    assert evidence["shadow_timeline_summary"]["opening_duels"] == 2
    assert evidence["retention"]["eligible_now"] is False


def test_canary_capture_trust_uses_exact_daemon_receipt_clock(tmp_path):
    with EphemeralMysql.start(parent=tmp_path) as db:
        db.sql("""
CREATE TABLE ktp_matches (
  match_id VARCHAR(64) NOT NULL, half TINYINT NOT NULL,
  start_time DATETIME NOT NULL
);
CREATE TABLE ktp_capture_manifests (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  match_id VARCHAR(64) NOT NULL, half TINYINT NOT NULL,
  map_name VARCHAR(64) NOT NULL, producer VARCHAR(64) NOT NULL,
  producer_version VARCHAR(64) NOT NULL, schema_version SMALLINT NOT NULL,
  capabilities TEXT NOT NULL, position_interval DECIMAL(5,2) NOT NULL,
  buffer_entries INT NOT NULL, life_buffer_entries INT NOT NULL,
  producer_sequence BIGINT NOT NULL, event_epoch BIGINT NOT NULL,
  created_at DATETIME NOT NULL
);
CREATE TABLE ktp_capture_health (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  match_id VARCHAR(64) NOT NULL, half TINYINT NOT NULL,
  event_type VARCHAR(32) NOT NULL,
  attempted BIGINT NOT NULL, enqueued BIGINT NOT NULL,
  dropped BIGINT NOT NULL, emitted BIGINT NOT NULL,
  daemon_received BIGINT NOT NULL, daemon_accepted BIGINT NOT NULL,
  daemon_rejected BIGINT NOT NULL, correlation_failure_count BIGINT NOT NULL,
  sequence_first BIGINT NOT NULL, sequence_last BIGINT NOT NULL,
  daemon_sequence_first BIGINT NOT NULL, daemon_sequence_last BIGINT NOT NULL,
  sequence_gap_count BIGINT NOT NULL,
  duplicate_or_reordered_count BIGINT NOT NULL,
  producer_sequence BIGINT NOT NULL, event_epoch BIGINT NOT NULL
);
INSERT INTO ktp_matches VALUES
  ('canary-clock-TEST',1,'2026-08-28 21:16:04');
INSERT INTO ktp_capture_manifests
  (match_id,half,map_name,producer,producer_version,schema_version,
   capabilities,position_interval,buffer_entries,life_buffer_entries,
   producer_sequence,event_epoch,created_at)
VALUES
  ('canary-clock-TEST',1,'dod_anzio','stats_logging','1.18.1',22,
   'objective_attempt,grenade_entity',2.00,128,64,1,
   UNIX_TIMESTAMP('2026-08-28 21:16:03'),'2026-08-28 21:16:04');
""")
        values = ",".join(
            "('canary-clock-TEST',1," + analytics.sql_literal(event_type)
            + ",0,0,0,0,0,0,0,0,1,1,1,1,0,0,1,1787951763)"
            for event_type in analytics.CAPTURE_EVENT_TYPES
        )
        db.sql("""
INSERT INTO ktp_capture_health
  (match_id,half,event_type,attempted,enqueued,dropped,emitted,
   daemon_received,daemon_accepted,daemon_rejected,
   correlation_failure_count,sequence_first,sequence_last,
   daemon_sequence_first,daemon_sequence_last,sequence_gap_count,
   duplicate_or_reordered_count,producer_sequence,event_epoch)
VALUES """ + values)

        healthy_rows = canary_evidence.collect_capture_health(
            db, "canary-clock-TEST", True
        )
        healthy = canary_evidence.capture_health_evidence(healthy_rows, {1})
        db.sql("""
UPDATE ktp_capture_manifests
SET created_at='2026-08-28 21:16:08'
WHERE match_id='canary-clock-TEST'
""")
        late_rows = canary_evidence.collect_capture_health(
            db, "canary-clock-TEST", True
        )
        late = canary_evidence.capture_health_evidence(late_rows, {1})

    assert healthy["trusted"] is True
    assert healthy["activation_details"] == [{
        "half": 1,
        "producer_activation_epoch": 1787951763,
        "activation_receipt_epoch": 1787951764,
        "match_start_epoch": 1787951764,
        "receipt_latency_seconds": 0,
    }]
    assert late["trusted"] is False
    assert any("receipt latency 4s" in error
               for error in late["authorization_errors"])
