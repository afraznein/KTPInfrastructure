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

    evidence = canary_evidence.build_evidence(
        report, classifications, ownership,
        canary_evidence.inspect_logs([]),
        {"fixture": FIXTURE.name, "fixture_sha256": "test"},
        expected_server_id=2,
        as_of=datetime(2026, 8, 17, tzinfo=timezone.utc),
    )
    assert evidence["status"] == "WARN"  # logs deliberately omitted
    assert evidence["match_type"]["match_type_name"] == "official"
    assert evidence["ownership"]["baseline_ok"] is True
    assert evidence["ownership"]["transition_count"] == 2
    assert evidence["analytics_coverage"]["players"] == 12
    assert evidence["shadow_timeline_summary"]["opening_duels"] == 2
    assert evidence["retention"]["eligible_now"] is False
