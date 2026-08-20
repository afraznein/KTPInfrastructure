from copy import deepcopy

import pytest

from scripts.fps_stat_explorations import (
    EngagementDistanceConfig,
    ObjectivePressureConfig,
    build_objective_pressure_shadow,
    build_weapon_engagement_shadow,
)


RAW_LOCATION_KEYS = {
    "pos_x", "pos_y", "pos_z",
    "pos_victim_x", "pos_victim_y", "pos_victim_z",
    "killer_pos_x", "killer_pos_y", "killer_pos_z",
    "victim_pos_x", "victim_pos_y", "victim_pos_z",
    "game_time", "event_time", "heatmap", "path", "paths",
}


def assert_no_raw_locations(value):
    if isinstance(value, dict):
        assert not RAW_LOCATION_KEYS.intersection(value)
        for child in value.values():
            assert_no_raw_locations(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_raw_locations(child)


def position(player_id, team, game_time, x, y, name=None):
    return {
        "player_id": player_id,
        "player_name_at_match": name,
        "team": team,
        "half": 1,
        "pos_x": x,
        "pos_y": y,
        "pos_z": 64,
        "game_time": game_time,
        "event_time": "2026-08-19 20:00:00",
    }


def test_objective_pressure_aggregates_enemy_neutral_and_sampled_contest():
    positions = [
        position(1, 1, 5, 900, 0, "Rifle"),
        position(2, 2, 5, 920, 0, "Support"),
        position(1, 1, 10, 50, 0, "Rifle"),
    ]
    flags = [
        {"flag_index": 0, "flag_name": "allied", "origin_x": 0, "origin_y": 0},
        {"flag_index": 1, "flag_name": "axis", "origin_x": 1000, "origin_y": 0},
    ]
    ownership = [
        {"half": 1, "flag_index": 0, "owner_team": 1,
         "game_time": 0, "is_initial": 1},
        {"half": 1, "flag_index": 1, "owner_team": 2,
         "game_time": 0, "is_initial": 1},
        {"half": 1, "flag_index": 0, "owner_team": 0,
         "game_time": 8, "is_initial": 0},
    ]
    original = deepcopy((positions, flags, ownership))

    report = build_objective_pressure_shadow(positions, flags, ownership)

    assert (positions, flags, ownership) == original
    assert report["metric"] == "sampled_objective_pressure"
    assert report["status"] == "partial"
    assert report["visibility"] == "private_shadow_only"
    assert report["rating_effect"] is False
    assert report["raw_paths_returned"] is False
    assert report["raw_timelines_included"] is False
    assert report["parameters"]["distance_dimension"] == "2d_xy"
    assert report["source_coverage"]["flag_ownership"] == {
        "present": True,
        "rows_received": 3,
        "valid_rows": 3,
        "invalid_rows": 0,
        "rows_for_unknown_flags": 0,
        "expected_initial_baselines": 2,
        "observed_initial_baselines": 2,
        "initial_baseline_fraction": 1.0,
        "near_sample_resolution_fraction": 1.0,
    }
    assert report["confidence"]["level"] == "low"
    assert report["unit"] == "nominal_sampled_player_seconds"
    temporal = report["source_coverage"]["position_samples"]["temporal"]
    assert temporal["distinct_snapshot_count"] == 2
    assert temporal["snapshot_minimum_met"] is False
    assert temporal["players_meeting_minimum_samples"] == 0
    assert report["summary"]["enemy_owned_pressure_seconds"] == 5.0
    assert report["summary"]["neutral_proximity_seconds"] == 5.0
    assert report["summary"]["friendly_owned_proximity_seconds"] == 5.0
    assert report["summary"]["sampled_contest_seconds"] == 10.0

    rifle = next(row for row in report["players"] if row["player_id"] == 1)
    assert rifle["teams_observed"] == [1]
    assert rifle["near_objective_seconds"] == 10.0
    assert rifle["enemy_owned_pressure_seconds"] == 5.0
    assert rifle["neutral_proximity_seconds"] == 5.0
    assert rifle["sampled_contest_seconds"] == 5.0
    assert rifle["mean_nearest_objective_distance_units"] == 75.0
    assert_no_raw_locations(report)


def test_objective_pressure_requires_sustained_temporal_coverage_for_medium_confidence():
    report = build_objective_pressure_shadow(
        [
            position(1, 1, 0, 20, 0, "Rifle"),
            position(1, 1, 5, 25, 0, "Rifle"),
            position(1, 1, 10, 30, 0, "Rifle"),
        ],
        [{"flag_index": 0, "origin_x": 0, "origin_y": 0}],
        [{
            "half": 1, "flag_index": 0, "owner_team": 2,
            "game_time": 0, "is_initial": 1,
        }],
        ObjectivePressureConfig(expected_live_seconds=15),
    )

    assert report["status"] == "available"
    assert report["confidence"]["level"] == "medium"
    temporal = report["source_coverage"]["position_samples"]["temporal"]
    assert temporal["distinct_snapshot_count"] == 3
    assert temporal["maximum_observed_gap_seconds"] == 5.0
    assert temporal["expected_coverage_fraction"] == 1.0
    assert temporal["players_meeting_minimum_fraction"] == 1.0
    assert report["players"][0]["sample_coverage"][
        "player_sample_minimum_met"
    ] is True


def test_objective_pressure_preserves_unknown_ownership_instead_of_guessing():
    report = build_objective_pressure_shadow(
        [position(1, 1, 5, 20, 0)],
        [{"flag_index": 0, "origin_x": 0, "origin_y": 0}],
        [],
    )

    assert report["status"] == "partial"
    assert report["confidence"]["level"] == "low"
    assert report["summary"]["unknown_ownership_proximity_seconds"] == 5.0
    assert report["summary"]["enemy_owned_pressure_seconds"] == 0.0
    assert report["summary"]["ownership_context_coverage"] == 0.0
    assert report["source_coverage"]["flag_ownership"][
        "initial_baseline_fraction"
    ] == 0.0


def test_objective_pressure_requires_valid_parameters_and_source_geometry():
    with pytest.raises(ValueError, match="objective_radius_units"):
        build_objective_pressure_shadow(
            [], [], [], ObjectivePressureConfig(objective_radius_units=0)
        )
    with pytest.raises(ValueError, match="maximum_sample_gap_seconds"):
        build_objective_pressure_shadow(
            [], [], [],
            ObjectivePressureConfig(maximum_sample_gap_seconds=4),
        )

    report = build_objective_pressure_shadow(
        [position(1, 1, 5, 20, 0)], [], []
    )
    assert report["status"] == "unavailable"
    assert report["players"] == []
    assert report["source_coverage"]["position_samples"]["valid_rows"] == 1


def frag(
    killer_id,
    victim_id,
    weapon,
    victim_position,
    *,
    killer_team=1,
    victim_team=2,
    marker=1,
    include_victim_z=True,
    headshot=0,
    scoped=0,
    prone=0,
):
    row = {
        "killer_id": killer_id,
        "killer_name": f"Player {killer_id}",
        "killer_team": killer_team,
        "victim_id": victim_id,
        "victim_team": victim_team,
        "weapon": weapon,
        "killer_pos_x": 0,
        "killer_pos_y": 0,
        "killer_pos_z": 0,
        "victim_pos_x": victim_position[0],
        "victim_pos_y": victim_position[1],
        "headshot": headshot,
        "killer_scoped": scoped,
        "killer_prone": prone,
        "frag_context_recorded": marker,
        "event_time": "2026-08-19 20:00:00",
    }
    if include_victim_z:
        row["victim_pos_z"] = victim_position[2]
    return row


def test_weapon_profiles_measure_3d_distance_and_keep_missing_context_visible():
    rows = [
        frag(1, 10, "garand", (300, 0, 0), headshot=1),
        frag(1, 11, "garand", (600, 800, 0), scoped=1, prone=1),
        frag(2, 12, "mp40", (512, 0, 0)),
        frag(1, 13, "garand", (200, 0, 0), include_victim_z=False),
        frag(1, 14, "garand", (100, 0, 0), marker=0),
        frag(3, 3, "spade", (20, 0, 0)),
        frag(4, 15, "bar", (400, 0, 0), killer_team=1, victim_team=1),
    ]
    original = deepcopy(rows)
    report = build_weapon_engagement_shadow(
        rows, EngagementDistanceConfig(minimum_profile_kills=2)
    )

    assert rows == original
    assert report["metric"] == "weapon_kill_time_player_separation"
    assert report["status"] == "partial"
    assert report["visibility"] == "private_shadow_only"
    assert report["rating_effect"] is False
    assert report["raw_paths_returned"] is False
    assert report["raw_timelines_included"] is False
    assert report["parameters"]["distance_dimension"] == "3d_euclidean_kill_endpoints"
    assert report["source_coverage"]["frags"]["rows_received"] == 7
    assert report["source_coverage"]["frags"]["qualified_weapon_kills"] == 5
    assert report["source_coverage"]["frags"]["excluded_self_kills"] == 1
    assert report["source_coverage"]["frags"]["excluded_same_team_kills"] == 1
    assert report["source_coverage"]["frag_context"]["separation_eligible_kills"] == 3
    assert report["source_coverage"]["frag_context"]["coordinate_missing_rows"] == 1
    assert report["source_coverage"]["frag_context"]["marker_false_rows"] == 1
    assert report["summary"]["mean_kill_time_separation_units"] == 604.0
    assert report["summary"]["median_kill_time_separation_units"] == 512.0

    garand = next(row for row in report["weapon_profiles"] if row["weapon"] == "garand")
    assert garand["kills_observed"] == 4
    assert garand["separation_eligible_kills"] == 2
    assert garand["mean_kill_time_separation_units"] == 650.0
    assert garand["median_kill_time_separation_units"] == 650.0
    assert garand["separation_bands"]["close"] == {"kills": 1, "share": 0.5}
    assert garand["separation_bands"]["medium"] == {"kills": 1, "share": 0.5}
    assert garand["scoped_kills"] == 1
    assert garand["prone_kills"] == 1
    assert garand["profile_confidence"] == "low"

    mp40 = next(row for row in report["weapon_profiles"] if row["weapon"] == "mp40")
    assert mp40["separation_bands"]["close"]["kills"] == 0
    assert mp40["separation_bands"]["medium"]["kills"] == 1
    assert_no_raw_locations(report)


def test_weapon_profile_accepts_canonical_coordinate_names():
    report = build_weapon_engagement_shadow([{
        "killerId": 1,
        "victimId": 2,
        "killer_team": "Allies",
        "victim_team": "Axis",
        "weapon": "spring",
        "pos_x": 0,
        "pos_y": 0,
        "pos_z": 0,
        "pos_victim_x": 0,
        "pos_victim_y": 0,
        "pos_victim_z": 300,
        "frag_context_recorded": 1,
    }], EngagementDistanceConfig(minimum_profile_kills=1))

    assert report["status"] == "available"
    assert report["summary"]["mean_kill_time_separation_units"] == 300.0
    assert report["confidence"]["level"] == "medium"


def test_weapon_profile_accepts_unmarked_coordinates_but_lowers_confidence():
    row = frag(1, 2, "garand", (300, 0, 0))
    del row["frag_context_recorded"]

    report = build_weapon_engagement_shadow(
        [row], EngagementDistanceConfig(minimum_profile_kills=1)
    )

    assert report["status"] == "partial"
    assert report["summary"]["separation_eligible_kills"] == 1
    assert report["confidence"]["level"] == "low"
    assert report["source_coverage"]["frag_context"]["rows_without_marker"] == 1


def test_weapon_profile_rejects_explicitly_invalid_producer_context():
    row = frag(1, 2, "garand", (300, 0, 0))
    row.update({
        "half": None,
        "producer_match_id": "different-TEST",
        "producer_half": 1,
        "game_time": 20.0,
        "event_epoch": 1787154601,
    })

    report = build_weapon_engagement_shadow(
        [row], EngagementDistanceConfig(minimum_profile_kills=1)
    )

    assert report["status"] == "unavailable"
    assert report["weapon_profiles"] == []
    assert report["source_coverage"]["frags"]["rows_received"] == 1
    assert report["source_coverage"]["frags"]["invalid_rows"] == 1
    assert report["source_coverage"]["frags"][
        "producer_context_invalid_rows"
    ] == 1


def test_weapon_profile_empty_and_invalid_config_are_explicit():
    report = build_weapon_engagement_shadow([])
    assert report["status"] == "unavailable"
    assert report["confidence"]["level"] == "unavailable"
    assert report["weapon_profiles"] == []
    assert report["player_weapon_profiles"] == []

    with pytest.raises(ValueError, match="final distance band"):
        build_weapon_engagement_shadow(
            [], EngagementDistanceConfig(distance_bands=(("close", 512.0),))
        )
