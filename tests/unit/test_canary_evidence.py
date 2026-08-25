from __future__ import annotations

from datetime import datetime, timezone

from scripts import canary_evidence


def test_log_inspection_distinguishes_missing_clean_and_errors(tmp_path):
    assert canary_evidence.inspect_logs([])["status"] == "not_provided"
    clean = tmp_path / "clean.log"
    clean.write_text(
        "ordinary match output\nKTP_HEALTH sql_failed=0 sql_retried=0 unresolved_actions=0\n",
        encoding="utf-8",
    )
    assert canary_evidence.inspect_logs([clean])["status"] == "clean"
    bad = tmp_path / "bad.log"
    bad.write_text("DBD::mysql execute failed\nunknown action assist\n", encoding="utf-8")
    report = canary_evidence.inspect_logs([bad])
    assert report["status"] == "errors_found"
    assert report["sql_errors"]["count"] == 1
    assert report["unresolved_actions"]["count"] == 1

    health = tmp_path / "health.log"
    health.write_text(
        "KTP_HEALTH sql_failed=2 sql_retried=1 unresolved_actions=3\n",
        encoding="utf-8",
    )
    report = canary_evidence.inspect_logs([health])
    assert report["sql_errors"]["count"] == 1
    assert report["unresolved_actions"]["count"] == 1


def test_match_type_consistency_fails_closed():
    assert not canary_evidence.classification_evidence([])["consistent"]
    mixed = canary_evidence.classification_evidence([
        {"half": 1, "match_type": 1}, {"half": 2, "match_type": 2},
    ])
    assert mixed["match_type"] is None
    assert mixed["consistent"] is False


def test_ownership_requires_one_zero_time_baseline_per_flag_and_half():
    valid = canary_evidence.ownership_evidence([
        {"half": 1, "flag_index": 0, "is_initial": 1, "game_time": "0.00", "owner_team": 0},
        {"half": 1, "flag_index": 0, "is_initial": 0, "game_time": "5.00", "owner_team": 1},
    ])
    assert valid["baseline_ok"] is True
    assert valid["transition_count"] == 1
    invalid = canary_evidence.ownership_evidence([
        {"half": 1, "flag_index": 0, "is_initial": 0, "game_time": "5.00", "owner_team": 9},
    ])
    assert invalid["baseline_ok"] is False
    assert invalid["invalid_owner_count"] == 1


def test_retention_reports_test_match_eligibility_without_mutation():
    classification = canary_evidence.classification_evidence([
        {"half": 1, "match_type": 0, "start_time": "2026-07-01 00:00:00",
         "end_time": "2026-07-01 01:00:00"},
    ])
    result = canary_evidence.retention_evidence(
        "lane-b-TEST", classification, days=14,
        as_of=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    assert result["purge_class"] is True
    assert result["eligible_now"] is True


def test_draft_is_retained():
    classification = canary_evidence.classification_evidence([
        {"half": 1, "match_type": 3, "start_time": "2020-01-01 00:00:00",
         "end_time": "2020-01-01 01:00:00"},
    ])
    result = canary_evidence.retention_evidence(
        "old-draft", classification, days=14,
        as_of=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    assert result["purge_class"] is False
    assert result["eligible_now"] is False


def test_capture_activation_distinguishes_schema_from_live_data():
    result = canary_evidence.capture_activation_evidence({
        "frags": {"rows_total": 549, "rows_producer_timed": 0},
        "damage": {"rows_total": 946, "rows_producer_timed": 0},
        "life_events": {"rows_total": "0", "starts": None, "ends": None},
        "canonical_assists": {"rows_total": "0"},
    }, generic_assists=86)
    assert result["frag_producer_coverage_pct"] == 0.0
    assert result["damage_producer_coverage_pct"] == 0.0
    assert result["life_active"] is False
    assert result["assist_reconciled"] is False


def test_objective_classification_fails_closed_without_proven_topology():
    rows = [
        {"half": 1, "flag_index": 0, "flag_name": "CENTER",
         "is_initial": 1, "game_time": "0.00", "owner_team": 0},
        {"half": 1, "flag_index": 0, "flag_name": "CENTER",
         "is_initial": 0, "game_time": "10.00", "owner_team": 1},
    ]
    result = canary_evidence.objective_trust_evidence(
        canary_evidence.ownership_evidence(rows), rows, []
    )
    assert result["trusted_for_capout_and_last_flag"] is False
    assert result["static_positions_complete"] is False
    assert "Suppress capout" in result["reason"]


def test_objective_classification_requires_complete_partition_each_half():
    rows = []
    positions = []
    for half in (1, 2):
        for index, name, owner in ((0, "ALLIED_HOME", 1), (1, "AXIS_HOME", 2)):
            rows.append({
                "half": half, "flag_index": index, "flag_name": name,
                "is_initial": 1, "game_time": "0.00", "owner_team": owner,
            })
            positions.append({"flag_index": index, "flag_name": name})
    result = canary_evidence.objective_trust_evidence(
        canary_evidence.ownership_evidence(rows), rows, positions
    )
    assert result["trusted_for_capout_and_last_flag"] is True


def test_neutral_map_start_can_become_trusted_after_full_partition():
    rows = []
    positions = []
    for index, name in ((0, "LEFT"), (1, "RIGHT")):
        rows.append({
            "half": 1, "flag_index": index, "flag_name": name,
            "is_initial": 1, "game_time": "0.00", "owner_team": 0,
        })
        positions.append({"flag_index": index, "flag_name": name})
    rows.extend([
        {"half": 1, "flag_index": 0, "flag_name": "LEFT",
         "is_initial": 0, "game_time": "10.00", "owner_team": 1},
        {"half": 1, "flag_index": 1, "flag_name": "RIGHT",
         "is_initial": 0, "game_time": "20.00", "owner_team": 2},
    ])
    result = canary_evidence.objective_trust_evidence(
        canary_evidence.ownership_evidence(rows), rows, positions
    )
    assert result["trusted_for_capout_and_last_flag"] is True
    assert result["complete_partition_by_half"] == {1: True}


def test_cap_breaks_report_credits_and_incident_lower_bound_separately():
    rows = [
        {"event_time": "2026-08-21 21:20:50", "player_id": 115,
         "pos_x": 1, "pos_y": 2, "pos_z": 3},
        {"event_time": "2026-08-21 21:20:50", "player_id": 115,
         "pos_x": 1, "pos_y": 2, "pos_z": 3},
        {"event_time": "2026-08-21 21:40:27", "player_id": 273,
         "pos_x": 4, "pos_y": 5, "pos_z": 6},
    ]
    result = canary_evidence.cap_break_evidence(rows)
    assert result["cappers_stopped"] == 3
    assert result["incident_lower_bound"] == 2
    assert result["incident_identity_available"] is False


def test_cap_breaks_use_exact_incident_and_victim_identity_when_available():
    rows = [
        {"event_time": "2026-08-21 21:20:50", "player_id": 115,
         "pos_x": 1, "pos_y": 2, "pos_z": 3, "break_victim_id": 200,
         "break_incident_id": 44},
        {"event_time": "2026-08-21 21:20:50", "player_id": 116,
         "pos_x": 1, "pos_y": 2, "pos_z": 3, "break_victim_id": 201,
         "break_incident_id": 45},
    ]
    result = canary_evidence.cap_break_evidence(rows)
    assert result["incident_identity_available"] is True
    assert result["incident_lower_bound"] == 2
    assert result["victim_identity_coverage"] == 1.0


def test_statsme_is_reconciled_but_not_used_as_canonical_death_source():
    result = canary_evidence.statsme_reconciliation(
        [{"kills": 549, "team_kills": 7, "suicides": 2}],
        [{"statsme_kills": 556, "statsme_deaths": 544}],
    )
    assert result["statsme_kills_reconciled"] is True
    assert result["canonical_physical_deaths"] == 558
    assert result["statsme_death_delta"] == -14
    assert "frag/teamkill/suicide ledgers" in result["canonical_rule"]


def test_capture_health_requires_manifest_all_types_and_exact_receipts():
    rows = {
        "manifests": [{
            "half": 1, "producer": "stats_logging", "producer_version": "1.17.0",
            "schema_version": 21,
        }],
        "health": [
            {
                "half": 1, "event_type": event_type, "dropped": 0,
                "emitted": 3, "daemon_received": 3, "daemon_accepted": 3,
                "daemon_rejected": 0, "correlation_failure_count": 0,
                "sequence_gap_count": 0,
                "duplicate_or_reordered_count": 0,
            }
            for event_type in canary_evidence.CAPTURE_EVENT_TYPES
        ],
    }
    result = canary_evidence.capture_health_evidence(rows, {1})
    assert result["trusted"] is True
    assert result["manifest_versions"] == ["stats_logging@1.17.0/schema-21"]


def test_capture_health_fails_on_drop_gap_or_receipt_mismatch():
    health = [
        {
            "half": 1, "event_type": event_type, "dropped": 0,
            "emitted": 2, "daemon_received": 2, "daemon_accepted": 2,
            "daemon_rejected": 0, "correlation_failure_count": 0,
            "sequence_gap_count": 0,
            "duplicate_or_reordered_count": 0,
        }
        for event_type in canary_evidence.CAPTURE_EVENT_TYPES
    ]
    health[0]["dropped"] = 1
    health[1]["sequence_gap_count"] = 2
    health[2]["daemon_received"] = 1
    health[2]["daemon_accepted"] = 1
    result = canary_evidence.capture_health_evidence(
        {"manifests": [{"half": 1}], "health": health}, {1}
    )
    assert result["trusted"] is False
    assert result["producer_drops"] == 1
    assert result["sequence_gaps"] == 2
    assert result["emitted_received_mismatches"] == 1


def test_position_cadence_accepts_five_second_samples_with_tolerance():
    result = canary_evidence.position_cadence_evidence([
        {"half": 1, "sample_time": value, "player_samples": 10}
        for value in (5.0, 10.0, 15.0, 20.0)
    ] + [
        {"half": 2, "sample_time": value, "player_samples": 8}
        for value in (5.1, 10.2, 15.2)
    ])
    assert result["within_slo"] is True
    assert result["halves"][0]["median_interval_seconds"] == 5.0


def test_position_cadence_rejects_sparse_or_missing_samples():
    sparse = canary_evidence.position_cadence_evidence([
        {"half": 1, "sample_time": value, "player_samples": 5}
        for value in (5.0, 20.0, 35.0)
    ])
    assert sparse["within_slo"] is False
    assert canary_evidence.position_cadence_evidence([])["available"] is False
