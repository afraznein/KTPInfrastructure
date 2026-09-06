"""Unit tests for flag swing (v1) and the KTPR v2 shadow blend (v1)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.flag_swing import FlagSwingConfig, build_flag_swing_shadow
from scripts.ktpr_v2 import KtprV2Config, build_ktpr_v2_shadow

ROSTER = [{"player_id": pid, "team": 1 if pid <= 3 else 2}
          for pid in (1, 2, 3, 4, 5, 6)]


def flag_state(half, flag, owner, at, name="F", initial=0):
    return {"half": half, "flag_index": flag, "owner_team": owner,
            "game_time": at, "flag_name": name, "event_time": f"t{at}",
            "is_initial": initial}


def frag(half, at, killer, victim):
    return {"half": half, "game_time": at,
            "killer_id": killer, "victim_id": victim}


def spawn(pid, half, at):
    return {"player_id": pid, "half": half, "game_time": at,
            "boundary_kind": "start"}


def test_allied_cap_raises_p_and_credits_cappers():
    states = [flag_state(1, 0, 1, 30.0, name="A")]
    caps = [{"half": 1, "flag_name": "A", "event_time": "t30.0",
             "player_id": 1},
            {"half": 1, "flag_name": "A", "event_time": "t30.0",
             "player_id": 2}]
    result = build_flag_swing_shadow(states, [], [], caps, ROSTER)
    assert result["status"] == "available"
    point = result["timeline"][0]
    assert point["kind"] == "flag" and point["delta"] > 0
    players = {p["player_id"]: p for p in result["players"]}
    assert players[1]["attributed_swing"] == players[2]["attributed_swing"] > 0
    assert players[3]["attributed_swing"] == 0.0


def test_axis_kill_lowers_p_allies_and_credits_killer_positively():
    result = build_flag_swing_shadow([], [frag(1, 10.0, 4, 1)], [], [], ROSTER)
    point = result["timeline"][0]
    assert point["delta"] < 0
    players = {p["player_id"]: p for p in result["players"]}
    assert players[4]["attributed_swing"] > 0  # team-signed credit


def test_duel_difficulty_halves_credit_per_man_advantage():
    # Two even kills by 1, then a third while two men up: quarter weight.
    frags = [frag(1, 10.0, 1, 4), frag(1, 20.0, 1, 5), frag(1, 30.0, 1, 6)]
    result = build_flag_swing_shadow([], frags, [], [], ROSTER)
    timeline = result["timeline"]
    assert [p["killer_man_advantage"] for p in timeline] == [0, 1, 2]
    players = {p["player_id"]: p for p in result["players"]}
    assert players[1]["weighted_frags"] == 3
    assert players[1]["attributed_swing"] > 0


def test_respawn_restores_alive_state():
    frags = [frag(1, 10.0, 4, 1)]
    boundaries = [spawn(1, 1, 15.0)]
    result = build_flag_swing_shadow([], frags, boundaries, [], ROSTER)
    # After respawn the second kill of the same victim prices again.
    result2 = build_flag_swing_shadow(
        [], frags + [frag(1, 20.0, 4, 1)], boundaries, [], ROSTER)
    assert len(result2["timeline"]) == 2
    assert len(result["timeline"]) == 1


def test_swing_suppression_paths():
    assert build_flag_swing_shadow(
        [], [], [], [], ROSTER, temporal_valid=False)["status"] == \
        "timed_metrics_suppressed"
    assert build_flag_swing_shadow(
        None, [], [], [], ROSTER)["status"] == "unavailable"
    assert build_flag_swing_shadow([], [], [], [], [])["status"] == \
        "unavailable"


def test_swing_config_validation():
    with pytest.raises(ValueError):
        FlagSwingConfig(flag_coefficient=-1.0).validate()


def box(pid, team, name, kd, dpl, k2=0, k3=0, k4=0):
    return {"player_id": pid, "team": team, "player_name_at_match": name,
            "kd_ratio": kd, "damage_per_life": dpl,
            "fast_2k": k2, "fast_3k": k3, "fast_4k_plus": k4}


def test_ktpr_blend_ranks_and_lists_components():
    players = [box(1, 1, "Alfa", 2.0, 220.0, k2=2),
               box(2, 1, "Bravo", 1.0, 110.0),
               box(3, 2, "Zulu", 0.5, 80.0)]
    fights = [{"player_id": 1, "kast_f": 0.9},
              {"player_id": 2, "kast_f": 0.6},
              {"player_id": 3, "kast_f": 0.4}]
    swing = [{"player_id": 1, "attributed_swing": 0.5},
             {"player_id": 2, "attributed_swing": 0.1},
             {"player_id": 3, "attributed_swing": -0.2}]
    result = build_ktpr_v2_shadow(players, fights, swing)
    assert result["components_used"] == ["kast_f", "multikill", "output",
                                         "swing"]
    ratings = [p["player_id"] for p in result["players"]]
    assert ratings[0] == 1 and ratings[-1] == 3
    assert result["calibration"] == "uncalibrated_baseline"


def test_ktpr_missing_component_redistributes_not_zeroes():
    players = [box(1, 1, "Alfa", 2.0, 200.0), box(2, 2, "Zulu", 1.0, 100.0)]
    result = build_ktpr_v2_shadow(players, None, None)
    assert "swing" not in result["components_used"]
    assert result["players"][0]["player_id"] == 1
    assert build_ktpr_v2_shadow([], None, None)["status"] == "unavailable"


def test_ktpr_config_validation():
    with pytest.raises(ValueError):
        KtprV2Config(swing_weight=-1.0).validate()
    with pytest.raises(ValueError):
        KtprV2Config(0.0, 0.0, 0.0, 0.0).validate()
