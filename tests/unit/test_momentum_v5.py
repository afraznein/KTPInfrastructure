import json
import math
from pathlib import Path

import pytest

from scripts.accumulation_v3 import (
    build_ai_checkpoint, load_profile, render_markdown, score_match,
    normalize_impact_index, validate_ai_response,
)
from scripts.build_automated_match_report import build_bundle
from scripts.momentum_v5 import derive_momentum, render_momentum_svg


REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "config/analytics/accumulation_v5_momentum.toml")
TOPOLOGY = {
    "team1_first": "a1", "team1_second": "a2", "middle": "mid",
    "team2_second": "b2", "team2_first": "b1", "double_caps": ["a2", "b2"],
}
FLAGS = [
    {"flag_name": name, "origin_x": x, "origin_y": 0}
    for name, x in (("a1", 0), ("a2", 1000), ("mid", 2000), ("b2", 3000), ("b1", 4000))
]


def momentum_case():
    players = [{"player_id": value, "player_name_at_match": f"P{value}"} for value in range(1, 5)]
    samples = []
    for when in range(0, 121, 5):
        # Team 1 advances decisively after 40 seconds while team 2 is pushed back.
        samples.extend([
            {"player_id": 1, "team": 1, "half": 1, "game_time": when,
             "pos_x": 500 if when < 40 else 3300, "pos_y": 0},
            {"player_id": 2, "team": 1, "half": 1, "game_time": when,
             "pos_x": 1000 if when < 40 else 3000, "pos_y": 0},
            {"player_id": 3, "team": 2, "half": 1, "game_time": when,
             "pos_x": 3500 if when < 40 else 3900, "pos_y": 0},
            {"player_id": 4, "team": 2, "half": 1, "game_time": when,
             "pos_x": 3000 if when < 40 else 4000, "pos_y": 0},
        ])
    frags = [
        {"event_id": f"f{index}", "half": 1, "time": 40 + index * 3,
         "killer_id": 1 if index < 2 else 2, "victim_id": 3 + index % 2,
         "killer_team": 1, "victim_team": 2}
        for index in range(4)
    ]
    captures = [{"event_id": "c1", "half": 1, "time": 50, "team": 1,
                 "flag_name": "mid", "credited_player_ids": [1, 2]}]
    states = [
        {"half": 1, "game_time": 0, "flag_name": name,
         "owner_team": 1 if name in ("a1", "a2") else 2 if name in ("b1", "b2") else 0}
        for name in ("a1", "a2", "mid", "b2", "b1")
    ]
    points, public, private = derive_momentum(
        players, samples, FLAGS, frags, captures, PROFILE, TOPOLOGY, states
    )
    return players, frags, captures, points, public, private


def test_team_momentum_is_bounded_attributed_and_publicly_sanitized():
    _, _, _, points, public, private = momentum_case()
    assert public["curve"] and all(-100 <= row["momentum"] <= 100 for row in public["curve"])
    assert max(row["momentum"] for row in public["curve"]) > 20
    assert public["episodes"]
    assert all(value >= 0 for value in points.values())
    assert sum(points.values()) == pytest.approx(
        sum(sum(row["allocations"].values()) for row in public["episodes"]), abs=.1
    )
    public_body = json.dumps(public).lower()
    assert not any(token in public_body for token in ("pos_x", "pos_y", "route", "path"))
    assert private["classification"] == "PRIVATE_PLAYER_POSITIONAL_ANALYTICS"


def test_v5_replaces_duplicate_pools_and_normalizes_index(tmp_path):
    players, frags, captures, points, public, _ = momentum_case()
    facts_players = []
    for player in players:
        pid = player["player_id"]
        facts_players.append({**player, "team_name": "A" if pid < 3 else "B",
                              "kills": sum(row["killer_id"] == pid for row in frags),
                              "deaths": sum(row["victim_id"] == pid for row in frags),
                              "assists": 0, "opponent_damage": 0,
                              "team_kills": 0, "suicides": 0, "observed_seconds": 600})
    facts = {
        "schema_version": 1, "match": {"match_id": "v5-TEST", "map_name": "dod_anzio", "duration_seconds": 600},
        "players": facts_players, "frags": frags, "damage_events": [], "death_resets": [],
        "captures": captures, "cap_breaks": [],
        "position_points": {str(pid): 50 for pid in range(1, 5)},
        "position_components": {str(pid): {"mid_defense_points": 10, "aggression_points": 10,
            "enemy_flag_hold_points": 10, "active_flag_defense_points": 20,
            "sequence_continuity_points": 10, "position_points": 60} for pid in range(1, 5)},
        "momentum_points": {str(pid): value for pid, value in points.items()},
        "momentum_summary": public,
        "reliability": {"life_boundaries": False, "damage_events": False, "capture_events": True,
            "ownership": True, "map_topology": True, "break_context": False,
            "positions": True, "flag_positions": True, "life_impact": True, "momentum": True},
    }
    report = score_match(facts, PROFILE)
    assert report["component_totals"]["conversion_points"] == 0
    assert report["position_component_totals"]["sequence_continuity_points"] == 0
    assert all(row["total_points"] == pytest.approx(
        row["event_points"] + row["position_points"], abs=.02
    ) for row in report["players"])
    assert report["component_totals"]["momentum_points"] == pytest.approx(
        sum(points.values()), abs=.1
    )
    indices = sorted(row["impact_index"] for row in report["players"])
    assert indices[1] <= 100 <= indices[2]
    rendered = render_markdown(report)
    assert "Team momentum over time" in rendered and "Overall accumulated-score normalization" in rendered
    request = build_ai_checkpoint(report)
    validate_ai_response(request, {"input_sha256": request["input_sha256"],
        "summary": "A swing changed the aggregate match state.",
        "storylines": [{"title": "Swing", "evidence_event_ids": [public["episodes"][0]["event_id"]]}],
        "anomalies": [], "calibration_questions": [],
        "publication_recommendation": "review"})
    manifest = build_bundle(facts, PROFILE, tmp_path)
    assert (tmp_path / "momentum.svg").exists()
    assert "momentum.svg" in {row["path"] for row in manifest["files"]}


def test_svg_contains_only_aggregate_curve():
    _, _, _, _, public, _ = momentum_case()
    svg = render_momentum_svg(public, "safe-match")
    assert "<svg" in svg and "Team momentum" in svg
    assert not any(token in svg.lower() for token in ("pos_x", "pos_y", "player_id"))


def test_stable_team_identity_survives_halftime_side_switch():
    players = [{"player_id": value, "player_name_at_match": f"P{value}"} for value in range(1, 5)]
    samples = []
    for when in range(0, 81, 5):
        advanced = when >= 30
        samples.extend([
            # Stable team 1 is now raw Axis/side 2 and advances toward x=0.
            {"player_id": 1, "team": 2, "momentum_team": 1, "half": 2,
             "game_time": when, "pos_x": 3500 if not advanced else 700, "pos_y": 0},
            {"player_id": 2, "team": 2, "momentum_team": 1, "half": 2,
             "game_time": when, "pos_x": 3600 if not advanced else 1000, "pos_y": 0},
            {"player_id": 3, "team": 1, "momentum_team": 2, "half": 2,
             "game_time": when, "pos_x": 500 if not advanced else 100, "pos_y": 0},
            {"player_id": 4, "team": 1, "momentum_team": 2, "half": 2,
             "game_time": when, "pos_x": 400 if not advanced else 0, "pos_y": 0},
        ])
    _, public, _ = derive_momentum(players, samples, FLAGS, [], [], PROFILE, TOPOLOGY, [])
    assert public["team1"] == 1
    assert public["curve"][-1]["momentum"] > 0


def test_overall_rating_targets_50_100_150_and_is_bounded():
    cfg = PROFILE["impact_index"]
    reference, scale = 100.0, 0.30
    assert normalize_impact_index(reference, reference, scale, cfg) == 100
    exceptional = reference * math.exp(scale * 50 / 30)
    weak = reference * math.exp(-scale * 50 / 30)
    assert normalize_impact_index(exceptional, reference, scale, cfg) == 150
    assert normalize_impact_index(weak, reference, scale, cfg) == 50
    assert normalize_impact_index(0, reference, scale, cfg) == 50
