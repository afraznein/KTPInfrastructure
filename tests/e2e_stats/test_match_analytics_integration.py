from __future__ import annotations

from pathlib import Path

from scripts import match_analytics as analytics
from tests.e2e_stats.ephemeral_mysql import EphemeralMysql


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/e2e_stats/fixtures/analytics-phase-a-contract.sql"


def test_contract_fixture_generates_complete_private_report(tmp_path):
    """Exercise every checked-in query against an actual isolated database."""
    with EphemeralMysql.start(parent=tmp_path) as db:
        analytics.load_fixture(db, FIXTURE)
        assert analytics.discover_match_ids(db) == ["phase-a-contract-TEST"]
        report = analytics.build_report(db, "phase-a-contract-TEST", FIXTURE)

    assert report["quality"]["status"] == "PASS"
    assert [team["team_name"] for team in report["teams"]] == ["Allies", "Axis"]
    assert len(report["players"]) == 12
    assert sum(row["assists"] for row in report["assists"]) == 3
    assert len(report["weapons"]) == 12
    assert len(report["capture_events"]) == 2
    assert report["positional"] == {
        "privacy": "aggregate_only",
        "aggregate_sample_count": 12,
    }
    assert all("position_samples" not in player for player in report["players"])
    assert sum(player["kills"] for player in report["players"]) == 12
    assert sum(player["damage_dealt"] for player in report["players"]) == 1080
    assert sum(player["damage_taken"] for player in report["players"]) == 1080
    assert report["source_coverage"] == {
        "per_hit_damage": True,
        "capture_credits": True,
        "positions": True,
        "statsme": True,
        "statsme2": True,
        "legacy_match_cache": True,
        "assists": True,
        "flag_ownership": False,
    }
    for player in report["players"]:
        if player["deaths"]:
            assert player["damage_per_life"] == round(
                player["damage_dealt"] / player["deaths"], 2
            )
        else:
            assert player["damage_per_life"] is None
    assert report["schema_version"] == 3


def test_replay_report_suppresses_time_normalized_metrics(tmp_path):
    with EphemeralMysql.start(parent=tmp_path) as db:
        analytics.load_fixture(db, FIXTURE)
        report = analytics.build_report(
            db, "phase-a-contract-TEST", FIXTURE, source_mode="replay"
        )

    assert report["quality"]["status"] == "WARN"
    assert report["temporal_metrics_valid"] is False
    assert all(player["damage_per_minute"] is None for player in report["players"])
    assert any(check["code"] == "replay_timing_compressed"
               for check in report["quality"]["checks"])
