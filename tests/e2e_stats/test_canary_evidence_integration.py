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
