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


# ---------------------------------------------------------------------------
# Team convention. `capturing_team` arrives in REPORT-team convention; the
# column behind it is the engine side. Half 1 is the swapped half (report
# team 1 played engine side 2), half 2 the terminal half where the two agree
# by construction -- the built-in control for every assertion here.
# ---------------------------------------------------------------------------
from scripts.flag_fights import (  # noqa: E402
    EntryConfig, build_clutch_shadow, build_entries_shadow)
from scripts.report_team_convention import (  # noqa: E402
    translate_objective_attempts)

SWAP = {1: 2, 2: 1}
# Report team 1 = players 1,2,3; report team 2 = players 4,5,6.
CONV_ROSTER = ([{"player_id": p, "team": 1} for p in (1, 2, 3)]
               + [{"player_id": p, "team": 2} for p in (4, 5, 6)])


def life(half, pid, kind, at):
    return {"half": half, "player_id": pid, "boundary_kind": kind, "game_time": at}


def conv_window(half, attempt_id, engine_capturing_team, kind="complete"):
    """One window whose capturing_team is the raw ENGINE side."""
    return [
        attempt(half, attempt_id, "start", 100.0, team=engine_capturing_team),
        attempt(half, attempt_id, kind, 120.0, team=engine_capturing_team),
    ]


def test_opening_duel_is_credited_to_the_capturing_report_team():
    # Engine side 2 took the flag in half 1. Report team 1 PLAYED engine side
    # 2 that half, so a report-team-1 killer won this fight -- but compared
    # against the raw side the answer inverts.
    rows = conv_window(1, 7, 2)
    opener = frag(1, 1, 105.0, 1, 4, killer_team=1, victim_team=2)
    raw = build_flag_fight_shadow(rows, [opener], [], [], [1, 4])
    fixed = build_flag_fight_shadow(
        translate_objective_attempts(rows, SWAP), [opener], [], [], [1, 4])
    assert raw["windows"][0]["opening"]["won_by_capturing_team"] is False
    assert fixed["windows"][0]["opening"]["won_by_capturing_team"] is True


def test_the_terminal_half_opening_does_not_move():
    rows = conv_window(2, 9, 1)
    opener = frag(2, 2, 105.0, 1, 4, killer_team=1, victim_team=2)
    raw = build_flag_fight_shadow(rows, [opener], [], [], [1, 4])
    fixed = build_flag_fight_shadow(
        translate_objective_attempts(rows, SWAP), [opener], [], [], [1, 4])
    assert raw["windows"][0]["opening"] == fixed["windows"][0]["opening"]
    assert raw["windows"][0]["opening"]["won_by_capturing_team"] is True


def test_a_clutch_resolves_to_the_side_that_actually_won_it():
    # Engine side 2 captured in half 1, so report team 1 won. Player 1 is its
    # only survivor against three living opponents. Read as engine side 2, the
    # winner resolves to report team 2 and the clutch is credited to THEM.
    rows = conv_window(1, 7, 2)
    lives = ([life(1, p, "start", 0.0) for p in (1, 2, 3, 4, 5, 6)]
             + [life(1, 2, "end", 50.0), life(1, 3, "end", 60.0)])
    raw = build_clutch_shadow(_windows(rows), lives, CONV_ROSTER)
    fixed = build_clutch_shadow(
        _windows(translate_objective_attempts(rows, SWAP)), lives, CONV_ROSTER)
    assert [c["player_id"] for c in fixed["clutches"]] == [1]
    assert [c["team"] for c in fixed["clutches"]] == [1]
    # The raw side names the other team as winner, so player 1 is not its
    # survivor and the real clutch is not recorded at all.
    assert [c["player_id"] for c in raw["clutches"]] != [1]


def test_an_entry_is_taken_from_the_capturing_team_not_the_defenders():
    # The entrant filter is `teams[pid] != capturing: continue`, so the wrong
    # space picks the DEFENDERS' first man into the flag area.
    rows = conv_window(1, 7, 2)
    flags = [{"flag_index": 1, "flag_name": "POINT_A",
              "origin_x": 0.0, "origin_y": 0.0}]
    samples = [
        {"half": 1, "player_id": 4, "game_time": 101.0, "pos_x": 10.0,
         "pos_y": 0.0, "is_alive": 1},   # report team 2, in first
        {"half": 1, "player_id": 1, "game_time": 105.0, "pos_x": 10.0,
         "pos_y": 0.0, "is_alive": 1},   # report team 1, the real capturer
    ]
    lives = [life(1, p, "start", 0.0) for p in (1, 2, 3, 4, 5, 6)]
    raw = build_entries_shadow(_windows(rows), samples, flags, lives,
                               CONV_ROSTER, EntryConfig())
    fixed = build_entries_shadow(
        _windows(translate_objective_attempts(rows, SWAP)), samples, flags,
        lives, CONV_ROSTER, EntryConfig())
    assert [e["player_id"] for e in raw["entries"]] == [4], "defender's entry"
    assert [e["player_id"] for e in fixed["entries"]] == [1]
    assert [e["team"] for e in fixed["entries"]] == [1]


def test_a_window_with_no_resolvable_side_is_skipped_not_guessed():
    # translate_objective_attempts keeps the row and nulls capturing_team;
    # every consumer here must then skip the window rather than invent a side.
    rows = translate_objective_attempts(conv_window(1, 7, 2), {})
    opener = frag(1, 1, 105.0, 1, 4, killer_team=1, victim_team=2)
    built = build_flag_fight_shadow(rows, [opener], [], [], [1, 4])
    assert built["windows"][0]["opening"]["won_by_capturing_team"] is None
    lives = [life(1, p, "start", 0.0) for p in (1, 2, 3, 4, 5, 6)]
    clutch = build_clutch_shadow(_windows(rows), lives, CONV_ROSTER)
    assert clutch["clutches"] == [] and clutch["evaluated_windows"] == 0


def _windows(attempt_rows):
    """The window list the clutch/entry builders consume, as the orchestrator
    hands it to them: flag_fights' own output, so the translation propagates
    through one call rather than being applied twice."""
    return build_flag_fight_shadow(attempt_rows, [], [], [], [1, 4])["windows"]
