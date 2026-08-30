from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from scripts import match_report_bundle as bundle
from scripts import team_score_telemetry as score


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


def score_result(value, *, match_id="example-TEST", map_name="dod_anzio",
                 facts_digest=None):
    body = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return score.projection_result_from_release(value, {
        "schemaVersion": 1,
        "objectiveScoreSha256": hashlib.sha256(body).hexdigest(),
        "selectedMatchId": match_id,
        "analyticsFactsSha256": facts_digest,
        "context": {"mapName": map_name},
    })


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
    assert report["objectiveScoreTimeline"]["quality"]["status"] == "unavailable"
    assert report["objectiveScoreTimeline"]["halves"] == []


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


def test_bundle_attaches_sanitized_lane_b_official_score_fixture():
    fixture = Path(__file__).parents[1] / "fixtures" / "team_score" / "lane-b-objective-score.json"
    objective_score = json.loads(fixture.read_text(encoding="utf-8"))
    report = bundle.build_bundle(
        analytics(), readiness(), objective_score_result=score_result(objective_score)
    )
    projected = report["objectiveScoreTimeline"]
    assert projected["quality"]["status"] == "complete"
    assert projected["halves"][-1]["points"][-1]["team2Score"] == 2
    rendered = bundle.render_markdown(report)
    assert "## Official objective score" in rendered
    assert "Stable match-local labels" in rendered


def test_bundle_rejects_bare_or_foreign_score_artifacts():
    fixture = Path(__file__).parents[1] / "fixtures" / "team_score" / "lane-b-objective-score.json"
    objective_score = json.loads(fixture.read_text(encoding="utf-8"))
    with pytest.raises(TypeError, match="bound ProjectionResult"):
        bundle.build_bundle(
            analytics(), readiness(), objective_score_result=objective_score,
        )
    with pytest.raises(ValueError, match="foreign match"):
        bundle.build_bundle(
            analytics(), readiness(),
            objective_score_result=score_result(objective_score, match_id="foreign-TEST"),
        )
    with pytest.raises(ValueError, match="context disagrees"):
        bundle.build_bundle(
            analytics(), readiness(),
            objective_score_result=score_result(objective_score, map_name="dod_caen"),
        )
    with pytest.raises(ValueError, match="foreign analytics facts"):
        bundle.build_bundle(
            analytics(), readiness(),
            objective_score_result=score_result(objective_score, facts_digest="aa" * 32),
        )


def test_score_release_loader_rejects_missing_or_mismatched_private_binding():
    fixture = Path(__file__).parents[1] / "fixtures" / "team_score" / "lane-b-objective-score.json"
    objective_score = json.loads(fixture.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="private release schema"):
        score.projection_result_from_release(objective_score, {})
    with pytest.raises(ValueError, match="digest disagrees"):
        score.projection_result_from_release(objective_score, {
            "schemaVersion": 1,
            "objectiveScoreSha256": "00" * 32,
            "selectedMatchId": "example-TEST",
            "analyticsFactsSha256": None,
            "context": {"mapName": "dod_anzio"},
        })


def test_cli_requires_paired_private_release_and_strips_binding(tmp_path):
    fixture = Path(__file__).parents[1] / "fixtures" / "team_score" / "lane-b-objective-score.json"
    objective_score = json.loads(fixture.read_text(encoding="utf-8"))
    result = score_result(objective_score)
    analytics_path = tmp_path / "analytics.json"
    readiness_path = tmp_path / "readiness.json"
    public_path = tmp_path / "score.json"
    private_path = tmp_path / "score-private.json"
    analytics_path.write_text(json.dumps(analytics()), encoding="utf-8")
    readiness_path.write_text(json.dumps(readiness()), encoding="utf-8")
    public_path.write_text(json.dumps(result.dto), encoding="utf-8")
    private_path.write_text(json.dumps(result.private_release_metadata), encoding="utf-8")
    with pytest.raises(ValueError, match="required together"):
        bundle.main([
            "--analytics-json", str(analytics_path),
            "--readiness-json", str(readiness_path),
            "--objective-score-json", str(public_path),
            "--output-dir", str(tmp_path / "missing-private"),
        ])
    output = tmp_path / "bound"
    assert bundle.main([
        "--analytics-json", str(analytics_path),
        "--readiness-json", str(readiness_path),
        "--objective-score-json", str(public_path),
        "--objective-score-private-release", str(private_path),
        "--output-dir", str(output),
    ]) == 0
    report = json.loads((output / "match-report.json").read_text(encoding="utf-8"))
    serialized = json.dumps(report)
    assert "selectedMatchId" not in serialized
    assert "analyticsFactsSha256" not in serialized
    assert report["objectiveScoreTimeline"]["quality"]["status"] == "complete"
