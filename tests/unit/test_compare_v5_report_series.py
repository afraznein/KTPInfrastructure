from copy import deepcopy

import pytest

import scripts.compare_v5_report_series as series
from scripts.compare_v5_report_series import _spread, compare_series


def test_spread_is_deterministic_and_handles_zero():
    assert _spread([0, 0])["coefficient_of_variation_percent"] == 0
    assert _spread([10, 20])["mean"] == 15
    assert _spread([10, 20])["coefficient_of_variation_percent"] == 33.33


def test_series_requires_at_least_two_reports():
    with pytest.raises(ValueError, match="at least two"):
        compare_series([])


def test_series_aggregates_runs_and_tracks_same_player_by_name(monkeypatch):
    base = {
        "match_id": "test-1", "map_name": "dod_anzio", "players": 1,
        "duration_seconds": 360, "events": {
            "enemy_frags": 10, "damage_rows": 20, "assists": 2,
            "capture_events": 1, "capture_credits": 1,
            "cap_break_credits": 1, "position_samples": 100,
        },
        "groups": {key: 10 for key in series.GROUPS},
        "group_shares_percent": {key: 20 for key in series.GROUPS},
        "match_total_points": 50, "rating_distribution": {
            "minimum": 100, "q1": 100, "median": 100, "q3": 100, "maximum": 100,
        },
        "top_three_point_share_percent": 100, "momentum": {},
        "quality_gates": {"facts": "PASS"},
        "players_table": [{
            "player_id": 1, "player_name_at_match": "KTP Bot 1", "rank": 1,
            "impact_index": 100, "points_per_minute": 10, "kills": 10,
            "assists": 2, "opponent_damage": 500, "capture_points": 10,
            "conversion_points": 0, "cap_break_points": 0,
            "position_points": 10, "momentum_points": 2,
        }],
    }
    second = deepcopy(base)
    second["match_id"] = "test-2"
    second["players_table"][0]["player_id"] = 99
    summaries = iter([base, second])
    monkeypatch.setattr(series, "_summary", lambda _bundle: next(summaries))
    bundles = [
        {"report": {"profile": "v5"}, "verification": {
            "status": "PASS", "private_derivation": {"position_samples": 100}}},
        {"report": {"profile": "v5"}, "verification": {
            "status": "PASS", "private_derivation": {"position_samples": 100}}},
    ]

    result = compare_series(bundles)

    assert result["all_reports_pass"] is True
    assert result["no_blocking_quality_gates"] is True
    assert result["consistent_map"] is True
    assert result["stable_players"][0]["appearances"] == 2
    assert result["stable_players"][0]["name"] == "KTP Bot 1"
    assert result["duplicate_match_ids"] == []
    assert len(result["lessons_learned"]) == 4
