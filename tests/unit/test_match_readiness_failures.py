from __future__ import annotations

from copy import deepcopy

import pytest

from scripts import match_readiness


MATCH_ID = "1700000000-TEST"


def healthy_tables() -> dict[str, list[dict[str, object]]]:
    roster = [
        {
            "match_id": MATCH_ID,
            "player_id": str(player_id),
            "team": "1" if player_id <= 6 else "2",
            "steam_id": f"BOT:test-{player_id}",
        }
        for player_id in range(1, 13)
    ]
    positions = []
    for player_id in range(1, 13):
        for index, when in enumerate(("2026-08-19 00:00:00", "2026-08-19 00:00:02")):
            positions.append({
                "id": str(player_id * 10 + index),
                "match_id": MATCH_ID,
                "player_id": str(player_id),
                "team": "1" if player_id <= 6 else "2",
                "half": "1",
                "event_time": when,
                "pos_x": str(player_id * 10),
                "pos_y": str(player_id * 20),
                "pos_z": "0",
                "is_alive": "1",
                "is_spectator": "0",
                "map_revision_sha256": "a" * 64,
            })
    return {
        "ktp_matches": [{
            "id": "1", "match_id": MATCH_ID, "map_name": "dod_anzio",
            "half": "1",
            "start_time": "2026-08-19 00:00:00",
            "end_time": "2026-08-19 00:10:00",
        }],
        "ktp_match_players": roster,
        "hlstats_Events_Frags": [{
            "id": "1", "match_id": MATCH_ID, "killerId": "1", "victimId": "7",
            "half": "1", "eventTime": "2026-08-19 00:00:01",
            "pos_x": "10", "pos_y": "20", "pos_victim_x": "70", "pos_victim_y": "140",
        }],
        "ktp_damage_events": [{
            "id": "1", "match_id": MATCH_ID, "attacker_id": "1", "victim_id": "7",
            "half": "1", "event_time": "2026-08-19 00:00:01", "damage_capped": "90",
        }],
        "ktp_position_samples": positions,
        "ktp_flag_captures": [],
        "ktp_flag_state_events": [{
            "id": "1", "match_id": MATCH_ID, "half": "1",
            "event_time": "2026-08-19 00:00:00", "flag_index": "0", "owner": "1",
        }],
        "hlstats_Actions": [
            {"id": "1", "code": "assist"},
            {"id": "2", "code": "cap_break"},
        ],
        "hlstats_Events_PlayerPlayerActions": [{
            "id": "1", "match_id": MATCH_ID, "actionId": "1",
        }],
        "hlstats_Events_PlayerActions": [{
            "id": "1", "match_id": MATCH_ID, "actionId": "2",
        }],
        "hlstats_Events_Statsme": [{"id": "1", "match_id": MATCH_ID}],
        "hlstats_Events_Statsme2": [{"id": "1", "match_id": MATCH_ID}],
        "ktp_objective_attempt_events": [
            {"id": "1", "match_id": MATCH_ID, "half": "1", "attempt_id": "10",
             "server_id": "1", "producer_sequence": "10", "event_kind": "start",
             "stop_reason": None, "flag_name": "Bridge", "map_name": "dod_anzio",
             "capturing_team": "1", "owner_before": "2", "allies_in_zone": "1",
             "axis_in_zone": "0"},
            {"id": "2", "match_id": MATCH_ID, "half": "1", "attempt_id": "10",
             "server_id": "1", "producer_sequence": "11", "event_kind": "complete",
             "stop_reason": None, "flag_name": "Bridge", "map_name": "dod_anzio",
             "capturing_team": "1", "owner_before": "2", "allies_in_zone": "1",
             "axis_in_zone": "0"},
            {"id": "3", "match_id": MATCH_ID, "half": "1", "attempt_id": "11",
             "server_id": "1", "producer_sequence": "11", "event_kind": "start",
             "stop_reason": None, "flag_name": "Church", "map_name": "dod_anzio",
             "capturing_team": "2", "owner_before": "1", "allies_in_zone": "0",
             "axis_in_zone": "1"},
            {"id": "4", "match_id": MATCH_ID, "half": "1", "attempt_id": "11",
             "server_id": "1", "producer_sequence": "12", "event_kind": "stop",
             "stop_reason": "context_reset", "flag_name": "Church",
             "map_name": "dod_anzio", "capturing_team": "2", "owner_before": "1",
             "allies_in_zone": "0", "axis_in_zone": "0"},
        ],
        "ktp_grenade_entity_events": [
            {"id": "1", "match_id": MATCH_ID, "half": "1", "entindex": "101",
             "serial": "10001", "entity_kind": "tracked", "weapon_id": "13",
             "weapon_type": "handgrenade"},
            {"id": "2", "match_id": MATCH_ID, "half": "1", "entindex": "101",
             "serial": "10001", "entity_kind": "removed", "weapon_id": "13",
             "weapon_type": "handgrenade"},
            {"id": "3", "match_id": MATCH_ID, "half": "1", "entindex": "102",
             "serial": "10002", "entity_kind": "tracked", "weapon_id": "36",
             "weapon_type": "mills_bomb"},
        ],
        "ktp_capture_manifests": [{
            "id": "1", "match_id": MATCH_ID, "half": "1", "schema_version": "23",
            "event_epoch": "1787097601",
            "created_at": "2026-08-19 00:00:00",
            "position_interval": "2.00",
            "capabilities": (
                "life,damage,position,frag,assist,break,flag_state,flag_position,"
                "objective_attempt,team_membership,grenade_entity,position_state,"
                "map_revision,sequence,health"
            ),
            "map_revision_algorithm": "sha256",
            "map_revision_sha256": "a" * 64,
        }],
        "ktp_capture_health": [
            {
                "id": str(index), "match_id": MATCH_ID, "half": "1",
                "event_type": event_type, "attempted": (
                    "4" if event_type == "objective_attempt" else
                    "24" if event_type == "position" else "3"
                ), "enqueued": (
                    "4" if event_type == "objective_attempt" else
                    "24" if event_type == "position" else "3"
                ), "dropped": "0", "emitted": (
                    "4" if event_type == "objective_attempt" else
                    "24" if event_type == "position" else "3"
                ), "daemon_received": (
                    "4" if event_type == "objective_attempt" else
                    "24" if event_type == "position" else "3"
                ), "daemon_accepted": (
                    "4" if event_type == "objective_attempt" else
                    "24" if event_type == "position" else "3"
                ),
                "daemon_rejected": "0", "correlation_failure_count": "0",
                "sequence_gap_count": "0", "duplicate_or_reordered_count": "0",
            }
            for index, event_type in enumerate((
                "life", "damage", "position", "frag", "assist", "break",
                "flag_state", "flag_position", "objective_attempt", "team_membership",
                "grenade_entity",
            ), 1)
        ],
    }


def validate(monkeypatch: pytest.MonkeyPatch, tmp_path, tables):
    fixture = tmp_path / "injected.sql"
    fixture.write_text("-- failure-injection fixture\n", encoding="utf-8")
    monkeypatch.setattr(match_readiness, "load_tables", lambda _path: tables)
    return match_readiness.validate_fixture(fixture)


def finding(report, code):
    return next(item for item in report["checks"] if item["code"] == code)


def test_control_fixture_passes(monkeypatch, tmp_path):
    assert validate(monkeypatch, tmp_path, healthy_tables())["status"] == "PASS"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda tables: tables["ktp_matches"][0].update(end_time=None), "closed_match"),
        (lambda tables: tables["ktp_position_samples"].clear(), "positions_present"),
        (lambda tables: tables["hlstats_Events_Frags"][0].update(half="0"), "valid_half_tags"),
        (
            lambda tables: tables["hlstats_Events_Frags"].append(
                {**tables["hlstats_Events_Frags"][0], "id": "2"}
            ),
            "duplicate_frags",
        ),
    ],
)
def test_hard_source_failures_block_promotion(monkeypatch, tmp_path, mutation, code):
    tables = healthy_tables()
    mutation(tables)
    report = validate(monkeypatch, tmp_path, tables)
    assert report["status"] == "FAIL"
    assert finding(report, code)["level"] == "FAIL"


def test_coordinate_loss_below_75_percent_fails(monkeypatch, tmp_path):
    tables = healthy_tables()
    tables["hlstats_Events_Frags"][0]["pos_x"] = None
    report = validate(monkeypatch, tmp_path, tables)
    assert finding(report, "frag_coordinate_coverage")["level"] == "FAIL"


def test_slow_position_cadence_warns_without_rewriting_data(monkeypatch, tmp_path):
    tables = healthy_tables()
    for row in tables["ktp_position_samples"]:
        if row["event_time"] == "2026-08-19 00:00:02":
            row["event_time"] = "2026-08-19 00:00:20"
    report = validate(monkeypatch, tmp_path, tables)
    result = finding(report, "position_sampling_interval")
    assert report["status"] == "WARN"
    assert result["level"] == "WARN"
    assert result["evidence"]["median_seconds"] == 20.0


def test_legacy_in_band_cadence_without_schema22_manifest_remains_warn(monkeypatch, tmp_path):
    tables = healthy_tables()
    for row in tables["ktp_position_samples"]:
        if row["event_time"] == "2026-08-19 00:00:02":
            row["event_time"] = "2026-08-19 00:00:01"
    tables["ktp_objective_attempt_events"] = []
    tables["ktp_grenade_entity_events"] = []
    tables["ktp_capture_manifests"] = []
    tables["ktp_capture_health"] = []
    result = finding(validate(monkeypatch, tmp_path, tables), "position_sampling_interval")
    assert result["level"] == "WARN"
    assert result["evidence"]["median_seconds"] == 1.0
    assert result["evidence"]["timing_in_band"] is True
    assert result["evidence"]["schema22_cadence_authorized"] is False


def test_authorized_schema22_two_second_cadence_passes(monkeypatch, tmp_path):
    result = finding(
        validate(monkeypatch, tmp_path, healthy_tables()),
        "position_sampling_interval",
    )
    assert result["level"] == "PASS"
    assert result["evidence"]["median_seconds"] == 2.0
    assert result["evidence"]["schema22_cadence_authorized"] is True


def test_schema23_position_state_and_revision_pass(monkeypatch, tmp_path):
    result = finding(
        validate(monkeypatch, tmp_path, healthy_tables()),
        "schema23_position_provenance",
    )
    assert result["level"] == "PASS"
    assert result["evidence"]["captured_bsp_sha256"] == "a" * 64


@pytest.mark.parametrize("field", ("is_alive", "is_spectator", "map_revision_sha256"))
def test_schema23_position_state_and_revision_fail_closed(
        monkeypatch, tmp_path, field):
    tables = healthy_tables()
    tables["ktp_position_samples"][0][field] = None
    result = finding(
        validate(monkeypatch, tmp_path, tables),
        "schema23_position_provenance",
    )
    assert result["level"] == "FAIL"


def test_grenade_rocket_or_mortar_entity_is_rejected(monkeypatch, tmp_path):
    tables = healthy_tables()
    tables["ktp_grenade_entity_events"][0].update(
        weapon_id="29", weapon_type="bazooka"
    )
    report = validate(monkeypatch, tmp_path, tables)
    assert report["status"] == "FAIL"
    assert finding(report, "grenade_entity_lifecycle")["level"] == "FAIL"


def test_schema22_requires_exact_health_types_and_two_second_manifest(monkeypatch, tmp_path):
    tables = healthy_tables()
    tables["ktp_capture_manifests"][0]["position_interval"] = "5.00"
    tables["ktp_capture_health"].pop()
    report = validate(monkeypatch, tmp_path, tables)
    assert report["status"] == "FAIL"
    assert finding(report, "position_sampling_interval")["level"] == "WARN"
    assert finding(report, "schema22_capture_authorization")["level"] == "FAIL"


def test_schema22_readiness_uses_manifest_receipt_not_producer_epoch(
        monkeypatch, tmp_path):
    tables = healthy_tables()
    tables["ktp_capture_manifests"][0]["event_epoch"] = "1787097599"

    report = validate(monkeypatch, tmp_path, tables)

    assert finding(report, "schema22_capture_authorization")["level"] == "PASS"


@pytest.mark.parametrize("created_at", ("2026-08-19 00:00:04", None))
def test_schema22_readiness_rejects_late_or_missing_manifest_receipt(
        monkeypatch, tmp_path, created_at):
    tables = healthy_tables()
    tables["ktp_capture_manifests"][0]["created_at"] = created_at

    report = validate(monkeypatch, tmp_path, tables)

    result = finding(report, "schema22_capture_authorization")
    assert result["level"] == "FAIL"
    assert any("activation receipt" in error
               for error in result["evidence"]["authorization_errors"])


def test_schema22_authorizes_reconciled_zero_objective_and_grenade_streams(monkeypatch, tmp_path):
    tables = healthy_tables()
    tables["ktp_objective_attempt_events"] = []
    tables["ktp_grenade_entity_events"] = []
    for row in tables["ktp_capture_health"]:
        if row["event_type"] in {"objective_attempt", "grenade_entity"}:
            for field in (
                "attempted", "enqueued", "emitted", "daemon_received",
                "daemon_accepted",
            ):
                row[field] = "0"
    report = validate(monkeypatch, tmp_path, tables)
    assert finding(report, "schema22_capture_authorization")["level"] == "PASS"
    assert finding(report, "objective_attempt_lifecycle")["level"] == "PASS"
    assert finding(report, "grenade_entity_lifecycle")["level"] == "PASS"


def test_schema22_requires_exact_observed_half_sets(monkeypatch, tmp_path):
    tables = healthy_tables()
    tables["ktp_capture_manifests"][0]["half"] = "2"
    report = validate(monkeypatch, tmp_path, tables)
    assert finding(report, "schema22_capture_authorization")["level"] == "FAIL"


@pytest.mark.parametrize(
    ("kind", "reason", "attempt_id", "producer_sequence"),
    (
        ("complete", None, "20", "20"),
        ("complete", None, "21", "20"),
        ("stop", "capture_stopped", "22", "22"),
        ("stop", "context_reset", "23", "22"),
    ),
)
def test_orphan_terminal_requires_attempt_id_before_terminal_sequence(
    monkeypatch, tmp_path, kind, reason, attempt_id, producer_sequence,
):
    tables = healthy_tables()
    tables["ktp_objective_attempt_events"].append({
        "id": "5", "match_id": MATCH_ID, "half": "1", "server_id": "1",
        "attempt_id": attempt_id, "producer_sequence": producer_sequence,
        "event_kind": kind, "stop_reason": reason, "flag_name": "Orphan",
        "map_name": "dod_anzio", "capturing_team": "1", "owner_before": "2",
        "allies_in_zone": "0", "axis_in_zone": "0",
    })
    health = next(
        row for row in tables["ktp_capture_health"]
        if row["event_type"] == "objective_attempt"
    )
    for field in (
        "attempted", "enqueued", "emitted", "daemon_received", "daemon_accepted",
    ):
        health[field] = "5"
    report = validate(monkeypatch, tmp_path, tables)
    assert finding(report, "schema22_capture_authorization")["level"] == "PASS"
    objective = finding(report, "objective_attempt_lifecycle")
    assert objective["level"] == "FAIL"
    assert any(
        "terminal attempt_id is not earlier" in error
        for error in objective["evidence"]["validation_errors"]
    )


@pytest.mark.parametrize(
    ("event_type", "field", "value"),
    (
        ("objective_attempt", "attempted", "5"),
        ("grenade_entity", "enqueued", "2"),
    ),
)
def test_schema22_rejects_attempt_enqueue_equation_mismatches(
    monkeypatch, tmp_path, event_type, field, value,
):
    tables = healthy_tables()
    row = next(
        row for row in tables["ktp_capture_health"]
        if row["event_type"] == event_type
    )
    row[field] = value
    report = validate(monkeypatch, tmp_path, tables)
    assert finding(report, "schema22_capture_authorization")["level"] == "FAIL"


@pytest.mark.parametrize(
    ("table", "code"),
    [
        ("hlstats_Events_PlayerPlayerActions", "assist_coverage"),
        ("hlstats_Events_Statsme", "statsme_coverage"),
        ("hlstats_Events_Statsme2", "statsme2_coverage"),
        ("ktp_flag_state_events", "flag_ownership_coverage"),
    ],
)
def test_optional_source_loss_is_explicitly_warned(monkeypatch, tmp_path, table, code):
    tables = healthy_tables()
    tables[table] = []
    report = validate(monkeypatch, tmp_path, tables)
    assert report["status"] == "WARN"
    assert finding(report, code)["level"] == "WARN"


def test_bot_identity_in_production_match_fails_containment(monkeypatch, tmp_path):
    tables = deepcopy(healthy_tables())
    for rows in tables.values():
        for row in rows:
            if row.get("match_id") == MATCH_ID:
                row["match_id"] = "1700000000-KTP1"
    report = validate(monkeypatch, tmp_path, tables)
    assert report["status"] == "FAIL"
    assert finding(report, "bot_containment")["level"] == "FAIL"
