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
        for index, when in enumerate(("2026-08-19 00:00:00", "2026-08-19 00:00:05")):
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
            })
    return {
        "ktp_matches": [{
            "id": "1", "match_id": MATCH_ID, "map_name": "dod_anzio",
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
        if row["event_time"] == "2026-08-19 00:00:05":
            row["event_time"] = "2026-08-19 00:00:20"
    report = validate(monkeypatch, tmp_path, tables)
    result = finding(report, "position_sampling_interval")
    assert report["status"] == "WARN"
    assert result["level"] == "WARN"
    assert result["evidence"]["median_seconds"] == 20.0


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
