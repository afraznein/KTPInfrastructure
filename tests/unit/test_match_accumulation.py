import pytest

from scripts.match_accumulation import (
    accumulate_player,
    assert_shareable_safe,
    derive_private_positions,
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
    assert points == {7: 6.0}
    assert private[0]["awarded_position_points"] == 6.0
    assert private[0]["heatmap_cells"]
    assert private[0]["flag_breakdown"][0]["nearest_flag"] == "mid"


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
])
def test_privacy_guard_rejects_personal_position_details(key):
    with pytest.raises(ValueError, match="private positional key leaked"):
        assert_shareable_safe({"players": [{key: "secret"}]})
