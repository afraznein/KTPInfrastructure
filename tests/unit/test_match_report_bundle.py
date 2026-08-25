from __future__ import annotations

import json

import pytest

from scripts import match_report_bundle as bundle


def analytics(match_id="example-TEST"):
    return {
        "schema_version": 3,
        "match_id": match_id,
        "match": {
            "match_id": match_id, "map_name": "dod_anzio",
            "halves_played": 1, "duration_seconds": 600,
            "is_test_match": int(match_id.endswith("-TEST")),
        },
        "quality": {"status": "PASS"},
        "teams": [{
            "team_name": "Allies", "players": 1, "kills": 5,
            "deaths": 4, "assists": 2, "damage_dealt": 600,
            "damage_taken": 500, "damage_differential": 100,
            "capture_credits": 1, "cap_breaks": 0, "shots": 30,
            "hits": 10, "raw_accuracy": 0.333,
        }],
        "players": [{
            "player_id": 123, "steam_id": "BOT:private",
            "player_name_at_match": "Example", "team_name": "Allies",
            "kills": 5, "deaths": 4, "assists": 2, "headshots": 1,
            "damage_dealt": 600, "damage_taken": 500,
            "damage_differential": 100, "damage_per_minute": 60.0,
            "damage_per_life": 150.0, "capture_credits": 1,
            "cap_breaks": 0, "shots": 30, "hits": 10,
            "headshot_rate": 0.2, "raw_accuracy": 0.333,
            "duration_seconds": 600,
        }],
    }


def readiness(match_id="example-TEST"):
    return {
        "schema_version": 1, "match_id": match_id, "status": "WARN",
        "checks": [{
            "level": "WARN", "code": "flag_ownership_coverage",
            "message": "Ownership unavailable.", "evidence": {"rows": 0},
        }],
    }


def accumulation(match_id="example-TEST"):
    return {
        "schema_version": 1, "match_id": match_id,
        "players": [{
            "player_id": 123, "steam_id": "BOT:private",
            "player_name_at_match": "Example", "team_name": "Allies",
            "position_points": 42.5, "total_points": 300.0,
        }],
    }


def atlas(match_id="example-TEST"):
    return {
        "schema_version": 1, "target_match_id": match_id,
        "map": "dod_anzio", "contact_sheet": "99.png",
        "summary": {
            "matches": 5, "target_coordinate_frags": 48,
            "target_raw_frags": 50, "trade_kills": 12,
            "fast_multikill_frags": 9, "isolated_deaths": 3,
            "capture_events": 10, "cap_breaks": 2,
            "reconstructed_capouts": 0,
        },
        "images": [{"file": "01.png", "category": "Core", "title": "Occupancy"}],
    }


def test_bundle_joins_sources_but_removes_database_identity():
    report = bundle.build_bundle(
        analytics(), readiness(), accumulation(), atlas(),
        atlas_link_prefix="../atlas",
    )
    assert report["status"] == "WARN"
    assert report["players"][0]["name"] == "Example"
    assert report["players"][0]["damage_per_life"] == 150.0
    assert report["players"][0]["position_points"] == 42.5
    assert report["players"][0]["confidence"]["position_points"]["level"] == "shadow_only"
    assert report["spatial"]["confidence"]["level"] == "synthetic"
    assert report["spatial"]["contact_sheet"] == "../atlas/99.png"
    assert bundle.privacy_violations(report) == []
    serialized = json.dumps(report).lower()
    assert "steam_id" not in serialized
    assert "player_id" not in serialized
    assert "bot:private" not in serialized


def test_bundle_rejects_cross_match_artifacts():
    with pytest.raises(ValueError, match="readiness match IDs differ"):
        bundle.build_bundle(analytics(), readiness("wrong-TEST"))
    with pytest.raises(ValueError, match="atlas target match IDs differ"):
        bundle.build_bundle(analytics(), readiness(), atlas=atlas("wrong-TEST"))
    missing_target = atlas()
    del missing_target["target_match_id"]
    with pytest.raises(ValueError, match="atlas metadata has no target_match_id"):
        bundle.build_bundle(analytics(), readiness(), atlas=missing_target)
    wrong_map = atlas()
    wrong_map["map"] = "dod_harrington"
    with pytest.raises(ValueError, match="analytics and atlas maps differ"):
        bundle.build_bundle(analytics(), readiness(), atlas=wrong_map)


def test_markdown_is_a_complete_review_template():
    report = bundle.build_bundle(
        analytics(), readiness(), accumulation(), atlas(),
        atlas_link_prefix="spatial",
    )
    rendered = bundle.render_markdown(report)
    assert "## Data quality" in rendered
    assert "## Team summary" in rendered
    assert "## Player box score" in rendered
    assert "Dmg/life" in rendered
    assert "### Player rate confidence" in rendered
    assert "synthetic | synthetic | synthetic | synthetic | shadow_only" in rendered
    assert "## Match patterns and spatial report" in rendered
    assert "spatial/99.png" in rendered
    assert "Steam IDs" in rendered
    assert "BOT:private" not in rendered


def test_privacy_guard_catches_nested_coordinates_and_ids():
    assert bundle.privacy_violations({
        "players": [{"playerId": 1}], "spatial": {"pos_victim_x": 10}
    }) == ["report.players[0].playerId", "report.spatial.pos_victim_x"]
