from __future__ import annotations

from pathlib import Path

from scripts import match_analytics as analytics
from tests.e2e_stats.ephemeral_mysql import EphemeralMysql


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/e2e_stats/fixtures/analytics-phase-a-contract.sql"


def _assert_no_raw_position_payload(value):
    forbidden = {
        "pos_x", "pos_y", "pos_z", "pos_victim_x", "pos_victim_y",
        "pos_victim_z", "killer_pos_x", "killer_pos_y", "killer_pos_z",
        "victim_pos_x", "victim_pos_y", "victim_pos_z", "heatmap", "paths",
    }
    if isinstance(value, dict):
        assert forbidden.isdisjoint(value)
        for child in value.values():
            _assert_no_raw_position_payload(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_raw_position_payload(child)


def test_contract_fixture_generates_complete_private_report(tmp_path):
    """Exercise every checked-in query against an actual isolated database."""
    with EphemeralMysql.start(parent=tmp_path) as db:
        analytics.load_fixture(db, FIXTURE)
        assert analytics.discover_match_ids(db) == ["phase-a-contract-TEST"]
        producer_frags = analytics.query_rows(
            db, "frag_context_fact.sql", "phase-a-contract-TEST"
        )
        life_rows = analytics.query_rows(
            db, "life_boundary_fact.sql", "phase-a-contract-TEST"
        )
        damage_rows = analytics.query_rows(
            db, "damage_timeline_fact.sql", "phase-a-contract-TEST"
        )
        assist_rows = analytics.query_rows(
            db, "assist_timeline_fact.sql", "phase-a-contract-TEST"
        )
        report = analytics.build_report(db, "phase-a-contract-TEST", FIXTURE)

    assert len(producer_frags) == 12
    assert {(row["half"], row["victim_id"], row["game_time"])
            for row in producer_frags} == {
        (row["half"], row["player_id"], row["game_time"])
        for row in life_rows
        if row["boundary_kind"] == "end" and row["reason"] == "death"
    }
    assert {(row["half"], row["game_time"])
            for row in producer_frags if row["half"] == 2} == {
        (2, 20.0), (2, 40.0), (2, 60.0),
        (2, 80.0), (2, 100.0), (2, 120.0),
    }
    crossed_half = next(
        row for row in damage_rows
        if row["attacker_id"] == 7 and row["victim_id"] == 1
    )
    assert crossed_half["stored_half"] == 1
    assert crossed_half["producer_half"] == crossed_half["half"] == 2
    assert [(row["half"], row["game_time"])
            for row in assist_rows] == [(1, 15.0), (1, 35.0), (2, 15.0)]

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
        "damage_event_clock": True,
        "capture_credits": True,
        "positions": True,
        "statsme": True,
        "statsme2": True,
        "legacy_match_cache": True,
        "assists": True,
        "flag_ownership": True,
        "flag_positions": True,
        "frag_context": True,
        "frag_event_clock": True,
        "life_boundaries": True,
        "assist_context": True,
        "capture_health": False,
    }
    assert report["schema_version"] == 6
    assert report["shadow_timelines"]["status"] == "available"
    assert len(report["shadow_timelines"]["opening_duels"]) == 2
    assert report["shadow_timelines"]["fast_multikills"] == []
    assert report["shadow_timelines"]["trade_analysis"]["status"] == "available"
    assert report["shadow_timelines"]["revenge_events"] == []
    explorations = report["shadow_explorations"]
    assert explorations["definition_version"] == 2
    assert explorations["privacy"] == "private_shadow_only"
    assert explorations["writes"] is False
    assert explorations["rating_impact"] is False
    for metric in (
        "damage_conversion", "objective_pressure", "weapon_engagement", "life_kat"
    ):
        assert {
            "definition_version", "status", "source_coverage", "confidence",
            "visibility", "rating_effect",
        }.issubset(explorations[metric])
        assert explorations[metric]["visibility"] == "private_shadow_only"
        assert explorations[metric]["rating_effect"] is False
    assert explorations["damage_conversion"]["status"] == "available"
    assert sum(row["damage_total"]
               for row in explorations["damage_conversion"]["players"]) == 1080
    assert explorations["objective_pressure"]["status"] == "partial"
    assert explorations["objective_pressure"]["confidence"]["level"] == "low"
    assert explorations["objective_pressure"]["source_coverage"][
        "position_samples"
    ]["temporal"]["distinct_snapshot_count"] == 2
    assert explorations["objective_pressure"]["raw_paths_returned"] is False
    assert explorations["objective_pressure"]["raw_timelines_included"] is False
    assert explorations["weapon_engagement"]["status"] == "available"
    assert explorations["weapon_engagement"]["summary"][
        "mean_kill_time_separation_units"
    ] == 500.0
    assert explorations["life_kat"]["status"] == "available"
    assert explorations["life_kat"]["parameters"][
        "live_freeze_classification"
    ] == "unavailable"
    assert explorations["life_kat"]["aggregate"]["eligible_lives"] == 12
    assert explorations["life_kat"]["raw_timelines_included"] is False
    assert explorations["weapon_engagement"]["raw_timelines_included"] is False
    _assert_no_raw_position_payload(report)


def test_mismatched_producer_context_is_reported_and_fails_closed(tmp_path):
    with EphemeralMysql.start(parent=tmp_path) as db:
        analytics.load_fixture(db, FIXTURE)
        db.sql("""
INSERT INTO hlstats_Events_Frags
  (eventTime,match_id,killerId,victimId,weapon,headshot,half,
   pos_x,pos_y,pos_z,pos_victim_x,pos_victim_y,pos_victim_z,
   frag_context_recorded,producer_match_id,producer_half,game_time,event_epoch)
VALUES
  ('2026-08-16 20:09:00','phase-a-contract-TEST',90,91,'decoy',0,1,
   0,0,0,300,400,0,1,'different-TEST',NULL,540,
   UNIX_TIMESTAMP('2026-08-16 20:09:00'));
INSERT INTO ktp_damage_events
  (match_id,half,attacker_id,victim_id,weapon,damage_capped,hitplace,
   game_time,event_time,producer_match_id,producer_half,event_epoch)
VALUES
  ('phase-a-contract-TEST',1,1,7,'decoy',5,2,540,
   '2026-08-16 20:09:00','different-TEST',NULL,
   UNIX_TIMESTAMP('2026-08-16 20:09:00'));
INSERT INTO hlstats_Events_PlayerPlayerActions
  (eventTime,match_id,playerId,victimId,actionId)
VALUES
  ('2026-08-16 20:09:05','phase-a-contract-TEST',4,10,1);
""")
        selected_frags = analytics.query_rows(
            db, "frag_context_fact.sql", "phase-a-contract-TEST"
        )
        selected_damage = analytics.query_rows(
            db, "damage_timeline_fact.sql", "phase-a-contract-TEST"
        )
        report = analytics.build_report(db, "phase-a-contract-TEST", FIXTURE)

    assert len(selected_frags) == 13
    assert len(selected_damage) == 15
    assert sum(row["half"] is None for row in selected_frags) == 1
    assert sum(row["half"] is None for row in selected_damage) == 1
    # Stock-event exploration never groups the NULL producer half. Timed
    # revenge sees the invalid row and suppresses inference.
    assert report["shadow_timelines"]["status"] == "available"
    revenge = report["shadow_timelines"]["revenge_analysis"]
    assert revenge["status"] == "insufficient_source_data"
    assert revenge["source_coverage"]["canonical_frag_source"][
        "rows_received"
    ] == 13
    assert revenge["source_coverage"]["canonical_frag_source"][
        "rows_with_usable_producer_clock"
    ] == 12

    explorations = report["shadow_explorations"]
    damage = explorations["damage_conversion"]
    assert damage["status"] == "insufficient_source_data"
    assert damage["source_coverage"]["damage"]["rows_received"] == 15
    # Two fixture rows are intentionally team/self damage; the third excluded
    # row is the producer-context mismatch inserted above.
    assert damage["source_coverage"]["damage"]["rows_usable"] == 12
    assert damage["source_coverage"]["damage"]["rows_excluded"] == 3
    assert damage["excluded_rows"]["malformed"] == 1
    assert damage["excluded_rows"]["self_or_team"] == 2
    assert damage["source_coverage"]["producer_frag_clock"][
        "rows_excluded"
    ] == 1
    assert damage["source_coverage"]["assist_context"]["rows_received"] == 3

    kat = explorations["life_kat"]
    assert kat["status"] == "available"
    assert kat["confidence"]["level"] == "low"
    assert kat["source_coverage"]["frags"]["rows_received"] == 13
    assert kat["source_coverage"]["frags"]["rows_excluded"] == 1
    assert kat["source_coverage"]["assists"]["rows_received"] == 3
    assert kat["boundary_coverage"]["death_frag_bijection_complete"] is True

    weapon = explorations["weapon_engagement"]
    assert weapon["status"] == "partial"
    assert weapon["confidence"]["level"] == "low"
    assert weapon["source_coverage"]["frags"][
        "producer_context_invalid_rows"
    ] == 1
    assert weapon["summary"]["kills_observed"] == 12
    _assert_no_raw_position_payload(report)


def test_replay_report_suppresses_time_normalized_metrics(tmp_path):
    with EphemeralMysql.start(parent=tmp_path) as db:
        analytics.load_fixture(db, FIXTURE)
        report = analytics.build_report(
            db, "phase-a-contract-TEST", FIXTURE, source_mode="replay"
        )

    assert report["quality"]["status"] == "WARN"
    assert report["temporal_metrics_valid"] is False
    assert report["shadow_timelines"]["status"] == "timed_metrics_suppressed"
    assert len(report["shadow_timelines"]["opening_duels"]) == 2
    assert all(player["damage_per_minute"] is None for player in report["players"])
    assert report["shadow_explorations"]["damage_conversion"][
        "status"
    ] == "timed_metrics_suppressed"
    assert report["shadow_explorations"]["objective_pressure"][
        "status"
    ] == "timed_metrics_suppressed"
    assert report["shadow_explorations"]["weapon_engagement"][
        "status"
    ] == "available"
    assert report["shadow_explorations"]["life_kat"][
        "status"
    ] == "timed_metrics_suppressed"
    assert any(check["code"] == "replay_timing_compressed"
               for check in report["quality"]["checks"])
