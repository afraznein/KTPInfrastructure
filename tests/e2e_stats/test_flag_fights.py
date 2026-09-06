"""Unit tests for the flag-fight shadow exploration (definition v1)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.flag_fights import FlagFightConfig, build_flag_fight_shadow


def attempt(half, attempt_id, kind, game_time, *, flag="POINT_A", flag_index=1,
            team=2, stop_reason=None):
    return {
        "half": half, "attempt_id": attempt_id, "event_kind": kind,
        "flag_index": flag_index, "flag_name": flag, "capturing_team": team,
        "stop_reason": stop_reason, "game_time": game_time,
    }


def frag(event_id, half, game_time, killer, victim, *, killer_team=2,
         victim_team=1, weapon="k98"):
    return {
        "event_id": event_id, "half": half, "game_time": game_time,
        "event_unix": 1000.0 + game_time,
        "killer_id": killer, "killer_name": f"p{killer}",
        "killer_team": killer_team,
        "victim_id": victim, "victim_name": f"p{victim}",
        "victim_team": victim_team, "weapon": weapon,
    }


def assist(half, game_time, assister, victim):
    return {"half": half, "game_time": game_time,
            "assister_id": assister, "victim_id": victim}


ONE_WINDOW = [
    attempt(1, 7, "start", 100.0),
    attempt(1, 7, "complete", 120.0),
]


def test_window_is_built_from_start_and_terminal_rows():
    result = build_flag_fight_shadow(ONE_WINDOW, [], [], [], [1, 2])
    assert result["status"] == "available"
    assert result["summary"]["fight_windows"] == 1
    assert result["summary"]["captures"] == 1
    window = result["windows"][0]
    assert window["outcome"] == "capture"
    assert window["duration_seconds"] == 20.0
    assert window["membership_start"] == 90.0
    assert window["membership_end"] == 125.0


def test_attempt_without_terminal_row_is_counted_not_windowed():
    result = build_flag_fight_shadow(
        [attempt(1, 7, "start", 100.0)], [], [], [], [1])
    assert result["status"] == "no_fight_windows"
    assert result["summary"]["attempts_without_closed_window"] == 1


def test_opening_kill_is_first_frag_in_padded_window():
    frags = [
        frag(11, 1, 95.0, killer=1, victim=5),   # inside pre-padding
        frag(12, 1, 105.0, killer=5, victim=1, killer_team=1, victim_team=2),
        frag(13, 1, 300.0, killer=1, victim=6),  # outside
    ]
    result = build_flag_fight_shadow(ONE_WINDOW, frags, [], [], [1, 5])
    window = result["windows"][0]
    assert window["opening"]["event_id"] == 11
    assert window["opening"]["killer"]["player_id"] == 1
    assert window["opening"]["won_by_capturing_team"] is True
    assert window["frag_event_ids"] == [11, 12]
    players = {p["player_id"]: p for p in result["players"]}
    assert players[1]["openings_won"] == 1
    assert players[5]["openings_lost"] == 1
    assert players[1]["kills"] == 1 and players[1]["deaths"] == 1


def test_kast_f_counts_kill_assist_survival_and_traded_death():
    frags = [
        frag(21, 1, 101.0, killer=1, victim=2, killer_team=2, victim_team=1),
        frag(22, 1, 103.0, killer=3, victim=1, killer_team=1, victim_team=2),
    ]
    trades = [{"death_event_id": 21}]  # player 2's death was traded (by 3)
    assists = [assist(1, 102.0, assister=4, victim=2)]
    result = build_flag_fight_shadow(
        ONE_WINDOW, frags, assists, trades, [1, 2, 3, 4, 5])
    players = {p["player_id"]: p for p in result["players"]}
    assert players[1]["kast_f"] == 1.0   # killed (also died untraded)
    assert players[2]["kast_f"] == 1.0   # died but traded
    assert players[3]["kast_f"] == 1.0   # killed
    assert players[4]["kast_f"] == 1.0   # assisted
    assert players[5]["kast_f"] == 1.0   # survived
    assert players[2]["deaths_traded"] == 1
    # An untraded death with no other contribution is uncovered.
    frags2 = [frag(31, 1, 101.0, killer=1, victim=2)]
    result2 = build_flag_fight_shadow(ONE_WINDOW, frags2, [], [], [2])
    assert {p["player_id"]: p for p in result2["players"]}[2]["kast_f"] == 0.0


def test_missing_assist_source_suppresses_kast_only():
    frags = [frag(41, 1, 101.0, killer=1, victim=2)]
    result = build_flag_fight_shadow(
        ONE_WINDOW, frags, None, [], [1, 2],
        source_available={"objective_attempts": True, "frags": True,
                          "assists": False, "basic_trades": True})
    assert result["status"] == "available"
    players = {p["player_id"]: p for p in result["players"]}
    assert players[1]["kast_f"] is None
    assert players[1]["kills"] == 1
    assert any("KAST-F suppressed" in c for c in result["caveats"])


def test_missing_required_source_suppresses_everything():
    result = build_flag_fight_shadow(
        ONE_WINDOW, None, [], [], [1],
        source_available={"objective_attempts": True, "frags": False,
                          "assists": True, "basic_trades": True})
    assert result["status"] == "unavailable"
    assert result["windows"] == []


def test_replay_mode_suppresses_timed_windows():
    result = build_flag_fight_shadow(
        ONE_WINDOW, [], [], [], [1], temporal_valid=False)
    assert result["status"] == "timed_metrics_suppressed"
    assert result["windows"] == []


def test_frags_without_producer_clock_are_excluded_and_counted():
    bad = {"event_id": 51, "half": None, "game_time": None,
           "killer_id": 1, "victim_id": 2}
    result = build_flag_fight_shadow(ONE_WINDOW, [bad], [], [], [1, 2])
    assert result["summary"]["frags_excluded_missing_clock"] == 1
    assert result["windows"][0]["frag_event_ids"] == []


def test_stop_outcome_records_reasons():
    rows = [
        attempt(2, 3, "start", 50.0),
        attempt(2, 3, "stop", 60.0, stop_reason="zone_emptied"),
    ]
    result = build_flag_fight_shadow(rows, [], [], [], [1])
    window = result["windows"][0]
    assert window["outcome"] == "stop"
    assert window["stop_reasons"] == ["zone_emptied"]
    assert result["summary"]["stops"] == 1


def test_padding_config_is_validated():
    with pytest.raises(ValueError):
        FlagFightConfig(pre_window_seconds=-1.0).validate()
