"""Unit tests for fight entries (definition v1)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.flag_fights import EntryConfig, build_entries_shadow

ROSTER = [{"player_id": pid, "team": 1 if pid <= 3 else 2}
          for pid in (1, 2, 3, 4, 5, 6)]
FLAGS = [{"flag_index": 0, "origin_x": 1000.0, "origin_y": 1000.0}]


def window(half=1, attempt=1, team=1, start=100.0, end=120.0,
           flag=0, outcome="capture"):
    return {"half": half, "attempt_id": attempt, "capturing_team": team,
            "flag_index": flag, "flag_name": "F0", "outcome": outcome,
            "started_game_time": start, "ended_game_time": end,
            "membership_start": start - 10.0, "membership_end": end + 5.0}


def sample(pid, at, x, y, half=1, alive=1):
    return {"player_id": pid, "half": half, "game_time": at,
            "pos_x": x, "pos_y": y, "is_alive": alive}


def boundary(pid, at, kind, half=1):
    return {"player_id": pid, "half": half, "game_time": at,
            "boundary_kind": kind}


SPAWNS = [boundary(pid, 0.0, "start") for pid in (1, 2, 3, 4, 5, 6)]


def test_entry_is_first_alive_capturing_sample_in_radius():
    positions = [
        sample(4, 95.0, 1010, 1010),          # enemy team — not an entry
        sample(2, 96.0, 5000, 5000),          # too far
        sample(3, 97.0, 1100, 1100, alive=0),  # corpse — excluded
        sample(1, 98.0, 1200, 1200),          # first qualifying
        sample(2, 99.0, 1000, 1000),          # later
    ]
    result = build_entries_shadow(
        [window()], positions, FLAGS, SPAWNS, ROSTER)
    assert result["status"] == "available"
    assert result["windows_with_entry"] == 1
    entry = result["entries"][0]
    assert entry["player_id"] == 1
    assert entry["entry_game_time"] == 98.0
    assert entry["survived"] is True
    players = {p["player_id"]: p for p in result["players"]}
    assert players[1]["survival_rate"] == 1.0


def test_entrant_death_before_close_counts_as_not_survived():
    positions = [sample(1, 98.0, 1000, 1000)]
    boundaries = SPAWNS + [boundary(1, 110.0, "end")]
    result = build_entries_shadow(
        [window()], positions, FLAGS, boundaries, ROSTER)
    assert result["entries"][0]["survived"] is False
    players = {p["player_id"]: p for p in result["players"]}
    assert players[1]["survival_rate"] == 0.0


def test_no_qualifying_sample_counts_windowless():
    result = build_entries_shadow(
        [window()], [sample(1, 200.0, 1000, 1000)], FLAGS, SPAWNS, ROSTER)
    assert result["windows_with_entry"] == 0
    assert result["windows_without_entry"] == 1


def test_unknown_survival_is_censored_not_guessed():
    positions = [sample(1, 98.0, 1000, 1000)]
    result = build_entries_shadow(
        [window()], positions, FLAGS, [], ROSTER)
    assert result["entries"][0]["survived"] is None
    assert result["survival_censored"] == 1
    players = {p["player_id"]: p for p in result["players"]}
    assert players[1]["survival_rate"] is None


def test_missing_liveness_column_suppresses_everything():
    result = build_entries_shadow(
        [window()], [sample(1, 98.0, 1000, 1000)], FLAGS, SPAWNS, ROSTER,
        liveness_available=False)
    assert result["status"] == "unavailable"
    assert any("is_alive" in c for c in result["caveats"])


def test_replay_and_missing_sources_suppress():
    assert build_entries_shadow(
        [window()], [], FLAGS, [], ROSTER,
        temporal_valid=False)["status"] == "timed_metrics_suppressed"
    assert build_entries_shadow(
        None, [], FLAGS, [], ROSTER)["status"] == "unavailable"
    assert build_entries_shadow(
        [window()], [], FLAGS, [], [])["status"] == "unavailable"


def test_entry_config_validation():
    with pytest.raises(ValueError):
        EntryConfig(entry_radius_units=0).validate()
