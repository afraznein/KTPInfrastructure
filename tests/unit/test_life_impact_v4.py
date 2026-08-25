from pathlib import Path

import pytest

from scripts.accumulation_v3 import load_profile, render_markdown, score_match
from scripts.compare_accumulation_models import compare_models, render_markdown as render_comparison
from scripts.life_impact_v4 import PUBLIC_COMPONENTS, derive_life_impact


REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "config" / "analytics" / "accumulation_v4_life_impact.toml")
TOPOLOGY = {
    "team1_first": "a_first",
    "team1_second": "a_second",
    "middle": "mid",
    "team2_second": "x_second",
    "team2_first": "x_first",
}
FLAGS = [
    {"flag_name": "a_first", "origin_x": 0, "origin_y": 0},
    {"flag_name": "a_second", "origin_x": 1000, "origin_y": 0},
    {"flag_name": "mid", "origin_x": 2000, "origin_y": 0},
    {"flag_name": "x_second", "origin_x": 3000, "origin_y": 0},
    {"flag_name": "x_first", "origin_x": 4000, "origin_y": 0},
]
PLAYERS = [
    {"player_id": 1, "player_name_at_match": "Aggressor"},
    {"player_id": 2, "player_name_at_match": "Defender"},
]


def sample(player, team, when, x):
    return {"player_id": player, "team": team, "half": 1,
            "pos_x": x, "pos_y": 0, "pos_z": 0, "game_time": when}


def test_same_life_defense_push_and_caps_reward_outcomes_without_negative_points():
    samples = [
        sample(1, 1, 15, 2000), sample(2, 2, 15, 2050),
        sample(1, 1, 25, 3000), sample(2, 2, 25, 3050),
        sample(1, 1, 40, 3000), sample(2, 2, 40, 3050),
    ]
    frags = [
        {"event_id": "def-mid", "half": 1, "time": 15,
         "killer_id": 1, "victim_id": 2},
        {"event_id": "def-forward", "half": 1, "time": 40,
         "killer_id": 1, "victim_id": 2},
    ]
    captures = [
        {"event_id": "own-mid", "half": 1, "time": 10, "team": 1,
         "flag_name": "mid", "credited_player_ids": [1]},
        {"event_id": "mid-again", "half": 1, "time": 20, "team": 1,
         "flag_name": "mid", "credited_player_ids": [1]},
        {"event_id": "take-x-second", "half": 1, "time": 35, "team": 1,
         "flag_name": "x_second", "credited_player_ids": [1]},
    ]
    uncapped_profile = {
        **PROFILE,
        "life_impact": {**PROFILE["life_impact"], "points_cap_per_life": 1000.0},
    }
    points, private = derive_life_impact(
        PLAYERS, samples, FLAGS, frags, captures, uncapped_profile, TOPOLOGY
    )
    attacker = points[1]
    assert attacker["mid_defense_points"] > 60  # pressure presence plus defensive kill
    assert attacker["aggression_points"] > 40  # crossing award plus forward pressure
    assert attacker["enemy_flag_hold_points"] > 60
    assert attacker["active_flag_defense_points"] == 70
    assert attacker["sequence_continuity_points"] == 120  # bounded continuity
    assert attacker["position_points"] == pytest.approx(
        sum(attacker[key] for key in PUBLIC_COMPONENTS), abs=0.02
    )
    assert all(value >= 0 for value in attacker.values())
    assert private and "evidence" in private[0]


def test_unopposed_forward_presence_is_positive_but_worth_less_than_active_pressure():
    quiet = [sample(1, 1, 10, 3000), sample(2, 2, 10, 0)]
    contested = [sample(1, 1, 10, 3000), sample(2, 2, 10, 3050)]
    quiet_points, _ = derive_life_impact(
        PLAYERS, quiet, FLAGS, [], [], PROFILE, TOPOLOGY
    )
    contested_points, _ = derive_life_impact(
        PLAYERS, contested, FLAGS, [], [], PROFILE, TOPOLOGY
    )
    assert quiet_points[1]["aggression_points"] > 0
    assert contested_points[1]["aggression_points"] > quiet_points[1]["aggression_points"]
    assert quiet_points[1]["enemy_flag_hold_points"] == 0
    assert contested_points[1]["enemy_flag_hold_points"] > 0


def test_defense_requires_owned_flag_and_nearby_enemy_evidence():
    captures = [{"event_id": "mid-owned", "half": 1, "time": 1, "team": 1,
                 "flag_name": "mid", "credited_player_ids": [1]}]
    frag = [{"event_id": "kill", "half": 1, "time": 10,
             "killer_id": 1, "victim_id": 2}]
    threatened = [sample(1, 1, 10, 2000), sample(2, 2, 10, 2050)]
    distant = [sample(1, 1, 10, 2000), sample(2, 2, 10, 4000)]
    owned, _ = derive_life_impact(
        PLAYERS, threatened, FLAGS, frag, captures, PROFILE, TOPOLOGY
    )
    no_threat, _ = derive_life_impact(
        PLAYERS, distant, FLAGS, frag, captures, PROFILE, TOPOLOGY
    )
    unknown_owner, _ = derive_life_impact(
        PLAYERS, threatened, FLAGS, frag, [], PROFILE, TOPOLOGY
    )
    assert owned[1]["mid_defense_points"] >= 60
    assert no_threat[1]["mid_defense_points"] == 0
    assert unknown_owner[1]["mid_defense_points"] == 0


def test_life_and_match_caps_bound_exceptional_presence():
    profile = {**PROFILE, "life_impact": {
        **PROFILE["life_impact"], "points_cap_per_life": 50.0,
        "points_cap_per_match": 75.0,
    }}
    samples = []
    for when in range(5, 105, 5):
        samples += [sample(1, 1, when, 3000), sample(2, 2, when, 3050)]
    points, _ = derive_life_impact(
        PLAYERS, samples, FLAGS, [], [], profile, TOPOLOGY
    )
    assert points[1]["position_points"] <= 50.01  # one life hits the tighter cap


def test_immediate_death_has_zero_impact_not_a_penalty():
    samples = [sample(2, 2, 5, 0)]
    frags = [{"event_id": "instant", "half": 1, "time": 1,
              "killer_id": 2, "victim_id": 1}]
    points, _ = derive_life_impact(
        PLAYERS, samples, FLAGS, frags, [], PROFILE, TOPOLOGY
    )
    assert points[1] == {**{key: 0.0 for key in PUBLIC_COMPONENTS}, "position_points": 0.0}


def test_v4_components_are_sanitized_and_explained_with_the_worked_example():
    components = {
        "mid_defense_points": 10.0, "aggression_points": 20.0,
        "enemy_flag_hold_points": 5.0, "active_flag_defense_points": 0.0,
        "sequence_continuity_points": 15.0, "position_points": 50.0,
    }
    facts = {
        "schema_version": 1,
        "match": {"match_id": "v4-example", "map_name": "dod_anzio",
                  "duration_seconds": 60},
        "players": [
            {"player_id": 1, "player_name_at_match": "Aggressor", "kills": 1,
             "deaths": 0, "assists": 1, "opponent_damage": 100,
             "team_kills": 0, "suicides": 0, "observed_seconds": 60},
            {"player_id": 2, "player_name_at_match": "Defender", "kills": 0,
             "deaths": 1, "assists": 0, "opponent_damage": 0,
             "team_kills": 0, "suicides": 0, "observed_seconds": 60},
        ],
        "frags": [{"event_id": "e1", "half": 1, "time": 10,
                   "killer_id": 1, "victim_id": 2, "killer_team": 1,
                   "victim_team": 2}],
        "captures": [], "cap_breaks": [], "death_resets": [],
        "position_points": {"1": 50.0, "2": 0.0},
        "position_components": {
            "1": components,
            "2": {**{key: 0.0 for key in PUBLIC_COMPONENTS}, "position_points": 0.0},
        },
        "reliability": {
            "life_boundaries": False, "damage_events": True,
            "capture_events": True, "ownership": False, "map_topology": True,
            "break_context": False, "positions": True, "flag_positions": True,
            "life_impact": True, "life_boundaries_inferred": True,
        },
    }
    report = score_match(facts, PROFILE)
    markdown = render_markdown(report)
    assert report["position_component_totals"]["aggression_points"] == 20
    assert "## Per-life positional impact" in markdown
    assert "### Exact positional calculation" in markdown
    assert "## Worked scoring example: Aggressor" in markdown
    assert "Coordinates, routes" in markdown
    assert "pos_x" not in markdown and "life_index" not in markdown
    comparison = compare_models(facts, PROFILE)
    assert comparison["bounded_model"] == "bounded_v4_life_impact"
    assert "Bounded v4 life-impact rank" in render_comparison(comparison)
