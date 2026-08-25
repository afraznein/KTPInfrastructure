import json
from xml.etree import ElementTree

import pytest

from scripts.points_timeline import (
    build_points_timeline,
    privacy_violations,
    render_points_timeline_svg,
)


def _timeline():
    components = ("combat_finisher_points", "position_points")
    players = [
        {"player_id": 1, "combat_finisher_points": 10, "position_points": 5},
        {"player_id": 2, "combat_finisher_points": 8, "position_points": 2},
        {"player_id": 3, "combat_finisher_points": 7, "position_points": 3},
        {"player_id": 4, "combat_finisher_points": 5, "position_points": 0},
    ]
    sources = {
        (1, "combat_finisher_points"): [{"half": 1, "time": 5, "points": 10}],
        (2, "combat_finisher_points"): [{"half": 1, "time": 17, "points": 8}],
        (3, "combat_finisher_points"): [{"half": 1, "time": 10, "points": 7}],
        (4, "combat_finisher_points"): [{"half": 1, "time": 29, "points": 5}],
    }
    return build_points_timeline(
        match_id="known-alignment-TEST", components=components,
        component_totals={"combat_finisher_points": 30, "position_points": 10},
        match_total_points=40, player_rows=players,
        player_teams={1: 1, 2: 1, 3: 2, 4: 2},
        contribution_sources=sources,
        team_position_contributions=[
            {"half": 1, "time": 20, "team": 1, "points": 7},
            {"half": 1, "time": 20, "team": 2, "points": 3},
        ],
        momentum={
            "team1": 1, "team2": 2,
            "curve": [
                {"half": 1, "time": 0, "momentum": 0},
                {"half": 1, "time": 15, "momentum": 12},
                {"half": 1, "time": 30, "momentum": -4},
            ],
        },
        annotations=[{"half": 1, "time": 20, "team": 1,
                      "kind": "capture", "label": "Team 1 middle capture"}],
    )


def test_known_fixture_aligns_points_and_momentum_to_15_second_windows():
    timeline = _timeline()
    first, second = timeline["halves"][0]["bins"]
    assert first["start_time"] == 0
    assert first["teams"]["1"]["points_gained"] == 10
    assert first["teams"]["2"]["points_gained"] == 7
    assert first["momentum"] == 12
    assert first["momentum_change"] == 12
    assert second["teams"]["1"]["points_gained"] == 15
    assert second["teams"]["2"]["points_gained"] == 8
    assert second["momentum"] == -4
    assert second["momentum_change"] == -16


def test_timeline_conserves_match_and_component_totals():
    conservation = _timeline()["conservation"]
    assert conservation["difference"] == pytest.approx(0, abs=0.0001)
    assert conservation["timeline_match_total_points"] == 40
    assert all(
        row["difference"] == pytest.approx(0, abs=0.0001)
        for row in conservation["component_totals"].values()
    )


def test_timeline_is_deterministic_and_contains_no_individual_evidence():
    first = json.dumps(_timeline(), sort_keys=True, separators=(",", ":"))
    second = json.dumps(_timeline(), sort_keys=True, separators=(",", ":"))
    assert first == second
    assert privacy_violations(json.loads(first)) == []
    lowered = first.lower()
    assert not any(token in lowered for token in (
        "player_id", "player_name", "pos_x", "pos_y", "coordinates", "route",
    ))
    svg = render_points_timeline_svg(_timeline())
    ElementTree.fromstring(svg)
    assert "Accumulated points over time" in svg
    assert not any(token in svg.lower() for token in ("player_id", "pos_x", "route"))


def test_privacy_contract_rejects_forbidden_keys():
    malformed = _timeline()
    malformed["halves"][0]["bins"][0]["player_id"] = 7
    assert "points_timeline.halves[0].bins[0].player_id" in privacy_violations(
        malformed
    )


def test_closed_end_boundaries_align_point_awards_and_momentum_episode():
    timeline = build_points_timeline(
        match_id="boundary-TEST",
        components=("combat_finisher_points", "momentum_points"),
        component_totals={"combat_finisher_points": 3, "momentum_points": 2},
        match_total_points=5,
        player_rows=[{"player_id": 1, "combat_finisher_points": 3,
                      "momentum_points": 2},
                     {"player_id": 2, "combat_finisher_points": 0,
                      "momentum_points": 0}],
        player_teams={1: 1, 2: 2},
        contribution_sources={
            (1, "combat_finisher_points"): [
                {"half": 1, "time": 0, "points": 1},
                {"half": 1, "time": 15, "points": 1},
                {"half": 1, "time": 30, "points": 1},
            ],
            (1, "momentum_points"): [
                {"half": 1, "time": 30, "points": 2},
            ],
        },
        team_position_contributions=[],
        momentum={"team1": 1, "team2": 2, "curve": [
            {"half": 1, "time": 0, "momentum": 0},
            {"half": 1, "time": 15, "momentum": 10},
            {"half": 1, "time": 30, "momentum": 20},
        ]},
        annotations=[{"half": 1, "time": 30, "team": 1,
                      "kind": "momentum_swing", "label": "Team 1 momentum swing"}],
    )
    first, second = timeline["halves"][0]["bins"]
    assert first["teams"]["1"]["points_gained"] == 2
    assert first["momentum"] == 10
    assert second["teams"]["1"]["points_gained"] == 3
    assert second["momentum"] == 20


def test_schema_rejects_unknown_spelling_and_non_finite_numbers():
    malformed = _timeline()
    malformed["halves"][0]["bins"][0]["point_gain"] = 12
    assert any("point_gain" in error for error in privacy_violations(malformed))
    with pytest.raises(ValueError, match="non-finite"):
        build_points_timeline(
            match_id="nan-TEST", components=("combat_finisher_points",),
            component_totals={"combat_finisher_points": float("nan")},
            match_total_points=0,
            player_rows=[{"player_id": 1, "combat_finisher_points": 0},
                         {"player_id": 2, "combat_finisher_points": 0}],
            player_teams={1: 1, 2: 2}, contribution_sources={},
            team_position_contributions=[],
            momentum={"team1": 1, "team2": 2, "curve": []}, annotations=[],
        )
