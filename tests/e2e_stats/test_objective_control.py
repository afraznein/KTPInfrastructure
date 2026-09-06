"""Unit tests for recap speed (definition v1) and fight clutches (v1)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.flag_fights import build_clutch_shadow
from scripts.objective_control import build_recap_speed


def state(half, flag, owner, at, initial=0):
    return {"half": half, "flag_index": flag, "owner_team": owner,
            "game_time": at, "is_initial": initial, "flag_name": f"F{flag}"}


def test_recap_pairs_loss_with_next_retake_same_flag_same_half():
    rows = [
        state(1, 0, 1, 10.0, initial=1),
        state(1, 0, 2, 40.0),   # allies lose f0
        state(1, 0, 1, 55.5),   # allies retake: 15.5s
        state(1, 1, 2, 20.0, initial=1),
        state(1, 1, 0, 70.0),   # axis lose f1 to neutral
        state(1, 1, 2, 90.0),   # axis retake: 20s
    ]
    result = build_recap_speed(rows)
    assert result["status"] == "available"
    seconds = {(r["team"], r["flag_index"]): r["seconds"]
               for r in result["recaps"]}
    assert seconds[(1, 0)] == 15.5
    assert seconds[(2, 1)] == 20.0
    teams = {t["team"]: t for t in result["teams"]}
    assert teams[1]["median_seconds"] == 15.5
    # The allies' retake of f0 is simultaneously an axis loss that stays
    # open to half end: one censored open loss.
    assert result["censored_open_losses"] == 1


def test_recap_open_loss_at_half_end_is_censored():
    rows = [
        state(1, 0, 1, 10.0, initial=1),
        state(1, 0, 2, 40.0),
    ]
    result = build_recap_speed(rows)
    assert result["recaps"] == []
    assert result["censored_open_losses"] == 1


def test_recap_virgin_owner_never_starts_a_hold():
    rows = [
        state(1, 0, -1, 5.0, initial=1),
        state(1, 0, 1, 30.0),
    ]
    result = build_recap_speed(rows)
    assert result["recaps"] == []


def test_recap_replay_and_missing_source_suppress():
    assert build_recap_speed([], temporal_valid=False)["status"] == \
        "timed_metrics_suppressed"
    assert build_recap_speed(None)["status"] == "unavailable"


def window(half, attempt, team, ended, outcome="capture"):
    return {"half": half, "attempt_id": attempt, "capturing_team": team,
            "ended_game_time": ended, "outcome": outcome, "flag_name": "F1"}


def boundary(pid, half, at, kind):
    return {"player_id": pid, "half": half, "game_time": at,
            "boundary_kind": kind}


ROSTER = [{"player_id": pid, "team": 1 if pid <= 3 else 2}
          for pid in (1, 2, 3, 4, 5, 6)]


def spawn_all(at=0.0):
    return [boundary(pid, 1, at, "start") for pid in (1, 2, 3, 4, 5, 6)]


def test_clutch_credits_lone_winner_against_two_plus():
    # Capture by team 1 at t=100; players 2 and 3 (team 1) are dead,
    # all of team 2 alive: player 1 clutched 1v3.
    boundaries = spawn_all() + [
        boundary(2, 1, 50.0, "end"), boundary(3, 1, 60.0, "end"),
    ]
    result = build_clutch_shadow(
        [window(1, 1, 1, 100.0)], boundaries, ROSTER)
    assert result["evaluated_windows"] == 1
    assert result["players"] == [{"player_id": 1, "clutches": 1}]
    assert result["clutches"][0]["against"] == 3


def test_stop_outcome_credits_the_defenders():
    # Team 2 attempted, stopped at t=100; team 1 defenders: only player 3
    # alive; two attackers alive: defender clutch.
    boundaries = spawn_all() + [
        boundary(1, 1, 40.0, "end"), boundary(2, 1, 45.0, "end"),
        boundary(6, 1, 50.0, "end"),
    ]
    result = build_clutch_shadow(
        [window(1, 1, 2, 100.0, outcome="stop")], boundaries, ROSTER)
    assert result["players"] == [{"player_id": 3, "clutches": 1}]


def test_unknown_liveness_censors_the_window():
    boundaries = [b for b in spawn_all() if b["player_id"] != 6]
    result = build_clutch_shadow(
        [window(1, 1, 1, 100.0)], boundaries, ROSTER)
    assert result["censored_windows"] == 1
    assert result["evaluated_windows"] == 0


def test_no_clutch_when_two_winners_alive_or_lone_enemy():
    boundaries = spawn_all() + [boundary(3, 1, 50.0, "end")]
    result = build_clutch_shadow(
        [window(1, 1, 1, 100.0)], boundaries, ROSTER)
    assert result["players"] == []
    # 1v1 is not a clutch.
    boundaries2 = spawn_all() + [
        boundary(2, 1, 40.0, "end"), boundary(3, 1, 41.0, "end"),
        boundary(4, 1, 42.0, "end"), boundary(5, 1, 43.0, "end"),
    ]
    result2 = build_clutch_shadow(
        [window(1, 1, 1, 100.0)], boundaries2, ROSTER)
    assert result2["players"] == []


def test_clutch_missing_sources_suppress():
    assert build_clutch_shadow(None, [], ROSTER)["status"] == "unavailable"
    assert build_clutch_shadow([], None, ROSTER)["status"] == "unavailable"
    assert build_clutch_shadow(
        [], [], ROSTER, temporal_valid=False)["status"] == \
        "timed_metrics_suppressed"
    assert build_clutch_shadow([], [], [])["status"] == "unavailable"
