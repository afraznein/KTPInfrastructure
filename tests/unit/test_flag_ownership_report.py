from scripts.flag_ownership_report import render_report, summarize_intervals


def test_summarize_intervals_accounts_for_each_owner_until_half_end():
    states = [
        {"half": 1, "flag_index": 2, "flag_name": "mid",
         "owner_team": 1, "game_time": 0},
        {"half": 1, "flag_index": 2, "flag_name": "mid",
         "owner_team": 2, "game_time": 20},
    ]
    assert summarize_intervals(states, {1: 50}) == [{
        "half": 1,
        "flag_index": 2,
        "flag_name": "mid",
        "observed_seconds": 50.0,
        "neutral_seconds": 0.0,
        "allies_seconds": 20.0,
        "axis_seconds": 30.0,
        "allies_share": 0.4,
        "axis_share": 0.6,
    }]


def test_report_is_aggregate_and_contains_reviewable_config_draft():
    flags = [{"flag_index": 2, "flag_name": "POINT MID",
              "origin_x": 10, "origin_y": -20}]
    body = render_report("M-TEST", "dod_map", flags, [], [])
    assert "No `ktp_flag_state_events` rows" in body
    assert '[maps.dod_map.team1_flag_multipliers]' in body
    assert '"POINT MID" = 1.00  # review' in body
    assert "player_id" not in body
