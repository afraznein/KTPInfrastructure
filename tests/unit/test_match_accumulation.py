import pytest

from scripts.match_accumulation import (
    DEFAULT_PROFILE,
    accumulate_player,
    assert_shareable_safe,
    derive_private_positions,
    load_profile,
    validate_output_separation,
)


PROFILE = {
    "profile": {"name": "test"},
    "events": {
        "kill": 100.0, "assist": 50.0, "damage": 0.1,
        "capture_credit": 100.0, "cap_break": 100.0,
        "team_kill": -100.0, "suicide": -50.0,
    },
    "position": {
        "sample_seconds": 5.0, "objective_radius_units": 100.0,
        "points_per_second_at_flag": 1.0, "grid_size_units": 50,
        "max_points_per_half": 6.0,
    },
}


def player(**overrides):
    row = {
        "player_id": 7, "steam_id": "STEAM_1:0:7",
        "player_name_at_match": "Private", "team": 1, "team_name": "Allies",
        "halves_played": 1, "kills": 2, "assists": 1, "damage_dealt": 250,
        "capture_credits": 1, "cap_breaks": 1, "team_kills": 0, "suicides": 0,
    }
    row.update(overrides)
    return row


def test_default_shadow_profile_targets_ten_percent_corpus_settings():
    profile = load_profile(DEFAULT_PROFILE)
    assert profile["profile"] == {
        "name": "accumulation_v2_target10",
        "status": "provisional_shadow_default",
    }
    assert profile["position"]["points_per_second_at_flag"] == 0.50
    assert profile["position"]["max_points_per_half"] == 150.0
    assert profile["scenarios"]["last_flag_defense_kill_points"] == 30.0
    assert profile["scenarios"]["last_flag_defense_max_per_half"] == 60.0


def test_private_heatmap_drives_capped_shareable_points():
    samples = [
        {"player_id": 7, "team": 1, "half": 1, "pos_x": 0, "pos_y": 0,
         "pos_z": 0, "game_time": 5},
        {"player_id": 7, "team": 1, "half": 1, "pos_x": 50, "pos_y": 0,
         "pos_z": 0, "game_time": 10},
    ]
    flags = [{"flag_index": 1, "flag_name": "mid", "origin_x": 0, "origin_y": 0}]
    points, private = derive_private_positions([player()], samples, flags, PROFILE)
    # Raw is 5 + 2.5, but the per-half presence cap is 6.
    assert points[7]["position_points"] == 6.0
    assert points[7]["base_position_points"] == 6.0
    assert private[0]["awarded_position_points"] == 6.0
    assert private[0]["heatmap_cells"]
    assert private[0]["flag_breakdown"][0]["nearest_flag"] == "mid"


def test_scenarios_reward_enemy_pressure_active_contest_and_last_flag_kill():
    profile = {
        **PROFILE,
        "position": {**PROFILE["position"], "max_points_per_half": 100.0},
        "scenarios": {
            "own_first_multiplier": 0.5,
            "enemy_first_multiplier": 2.0,
            "active_contest_radius_units": 100.0,
            "active_contest_multiplier": 2.0,
            "last_flag_defense_kill_points": 15.0,
            "last_flag_defense_max_per_half": 45.0,
        },
    }
    opponent = player(
        player_id=8, steam_id="STEAM_1:0:8", player_name_at_match="Opponent",
        team=2, team_name="Axis",
    )
    samples = [
        {"player_id": 7, "team": 1, "half": 1, "pos_x": 0, "pos_y": 0,
         "pos_z": 0, "game_time": 5},
        {"player_id": 8, "team": 2, "half": 1, "pos_x": 10, "pos_y": 0,
         "pos_z": 0, "game_time": 5},
    ]
    flags = [{"flag_index": 4, "flag_name": "axis_first",
              "origin_x": 0, "origin_y": 0}]
    topology = {"team1_first": "allies_first", "team2_first": "axis_first"}
    points, _ = derive_private_positions(
        [player(), opponent], samples, flags, profile, topology, {7: 1}
    )
    assert points[7] == {
        "base_position_points": 5.0,
        "enemy_pressure_points": 5.0,
        "contested_points": 10.0,
        "double_cap_points": 0.0,
        "ownership_adjustment_points": 0.0,
        "last_flag_defense_points": 15.0,
        "position_points": 35.0,
    }
    # The same active fight near Axis's own first is useful but worth less.
    assert points[8]["position_points"] == 4.5


def test_reviewed_per_team_flag_multiplier_overrides_generic_role_weight():
    profile = {
        **PROFILE,
        "position": {**PROFILE["position"], "max_points_per_half": 100.0},
        "scenarios": {"middle_multiplier": 9.0},
    }
    opponent = player(
        player_id=8, steam_id="STEAM_1:0:8", player_name_at_match="Opponent",
        team=2, team_name="Axis",
    )
    samples = [
        {"player_id": 7, "team": 1, "half": 1, "pos_x": 0, "pos_y": 0,
         "pos_z": 0, "game_time": 5},
        {"player_id": 8, "team": 2, "half": 1, "pos_x": 0, "pos_y": 0,
         "pos_z": 0, "game_time": 10},
    ]
    flags = [{"flag_index": 3, "flag_name": "middle",
              "origin_x": 0, "origin_y": 0}]
    topology = {
        "middle": "middle",
        "team1_flag_multipliers": {"middle": 1.4},
        "team2_flag_multipliers": {"middle": 1.1},
    }
    points, _ = derive_private_positions(
        [player(), opponent], samples, flags, profile, topology
    )
    assert points[7]["position_points"] == 7.0
    assert points[8]["position_points"] == 5.5


def test_ownership_timeline_classifies_hold_then_attack_and_adjusts_points():
    profile = {
        **PROFILE,
        "position": {**PROFILE["position"], "max_points_per_half": 100.0},
        "scenarios": {
            "holding_multiplier": 1.0,
            "attacking_multiplier": 2.0,
        },
    }
    samples = [
        {"player_id": 7, "team": 1, "half": 1, "pos_x": 0, "pos_y": 0,
         "pos_z": 0, "game_time": 5},
        {"player_id": 7, "team": 1, "half": 1, "pos_x": 0, "pos_y": 0,
         "pos_z": 0, "game_time": 10},
    ]
    flags = [{"flag_index": 3, "flag_name": "middle",
              "origin_x": 0, "origin_y": 0}]
    states = [
        {"half": 1, "flag_index": 3, "game_time": 0, "owner_team": 1},
        {"half": 1, "flag_index": 3, "game_time": 8, "owner_team": 2},
    ]
    points, private = derive_private_positions(
        [player()], samples, flags, profile, flag_states=states
    )
    assert points[7]["base_position_points"] == 10.0
    assert points[7]["ownership_adjustment_points"] == 5.0
    assert points[7]["position_points"] == 15.0
    assert private[0]["ownership_state_counts"] == {
        "last_flag_holding": 1, "attacking": 1
    }


def test_complete_timeline_adds_small_passive_last_flag_hold_premium():
    profile = {
        **PROFILE,
        "position": {**PROFILE["position"], "max_points_per_half": 100.0},
        "scenarios": {
            "holding_multiplier": 1.0,
            "last_flag_holding_multiplier": 1.1,
        },
    }
    samples = [
        {"player_id": 7, "team": 1, "half": 1, "pos_x": 0, "pos_y": 0,
         "pos_z": 0, "game_time": 5},
    ]
    flags = [
        {"flag_index": 0, "flag_name": "last", "origin_x": 0, "origin_y": 0},
        {"flag_index": 1, "flag_name": "enemy", "origin_x": 1000, "origin_y": 0},
    ]
    states = [
        {"half": 1, "flag_index": 0, "game_time": 0, "owner_team": 1},
        {"half": 1, "flag_index": 1, "game_time": 0, "owner_team": 2},
    ]
    points, private = derive_private_positions(
        [player()], samples, flags, profile, flag_states=states
    )
    assert points[7]["base_position_points"] == 5.0
    assert points[7]["ownership_adjustment_points"] == 0.5
    assert points[7]["position_points"] == 5.5
    assert private[0]["ownership_state_counts"] == {"last_flag_holding": 1}


def test_last_flag_defense_has_its_own_subcap():
    profile = {
        **PROFILE,
        "position": {**PROFILE["position"], "max_points_per_half": 100.0},
        "scenarios": {
            "last_flag_defense_kill_points": 15.0,
            "last_flag_defense_max_per_half": 45.0,
        },
    }
    points, _ = derive_private_positions(
        [player()], [], [], profile, {}, {7: 10}
    )
    assert points[7]["last_flag_defense_points"] == 45.0
    assert points[7]["position_points"] == 45.0


def test_shareable_accumulation_contains_points_not_heatmap():
    result = accumulate_player(player(), 6.0, PROFILE)
    assert result["event_points"] == 475.0
    assert result["total_points"] == 481.0
    assert_shareable_safe({"players": [result]})


def test_private_directory_cannot_be_nested_under_shareable(tmp_path):
    with pytest.raises(ValueError, match="separate and non-nested"):
        validate_output_separation(tmp_path / "out", tmp_path / "out" / "private")
    validate_output_separation(tmp_path / "shareable", tmp_path / "private")


@pytest.mark.parametrize("key", [
    "heatmap_cells", "pos_x", "nearest_flag", "flag_breakdown", "position_samples",
    "sample_count", "observed_seconds", "within_radius_samples", "raw_position_points",
    "active_contest_samples", "scenario_points", "last_flag_defense_kills",
    "ownership_state_counts", "owner_team", "flag_state_events",
])
def test_privacy_guard_rejects_personal_position_details(key):
    with pytest.raises(ValueError, match="private positional key leaked"):
        assert_shareable_safe({"players": [{key: "secret"}]})
