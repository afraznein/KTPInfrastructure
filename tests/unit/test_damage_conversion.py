from __future__ import annotations

import pytest

from scripts.damage_conversion import (
    DamageConversionConfig,
    build_damage_conversion,
)


def damage(
    event_id, at, attacker, victim, attacker_team=1, victim_team=2,
    amount=20, half=1, receipt_offset=100,
):
    return {
        "event_id": event_id,
        "game_time": at,
        "event_unix": at + receipt_offset,
        "half": half,
        "attacker_id": attacker,
        "attacker_steam_id": f"S{attacker}",
        "attacker_name": f"P{attacker}",
        "attacker_team": attacker_team,
        "victim_id": victim,
        "victim_steam_id": f"S{victim}",
        "victim_name": f"P{victim}",
        "victim_team": victim_team,
        "damage_capped": amount,
    }


def frag(event_id, at, killer, victim, killer_team=1, victim_team=2, half=1):
    return {
        "event_id": event_id,
        "game_time": at,
        "event_unix": at + 1000,
        "half": half,
        "killer_id": killer,
        "killer_team": killer_team,
        "victim_id": victim,
        "victim_team": victim_team,
    }


def assist(at, assister, victim, half=1, receipt_at=9999):
    return {
        "game_time": at,
        "event_unix": receipt_at,
        "half": half,
        "assister_id": assister,
        "victim_id": victim,
    }


def death(event_id, at, player, half=1, frag_event_id=None):
    row = {
        "id": event_id,
        "game_time": at,
        "half": half,
        "player_id": player,
        "boundary_kind": "end",
        "reason": "death",
    }
    if frag_event_id is not None:
        row["death_event_id"] = frag_event_id
    return row


def test_damage_uses_producer_clocks_and_partitions_first_life_outcome():
    report = build_damage_conversion(
        [
            damage(1, 10, 1, 7, amount=40),
            damage(2, 20, 1, 8, amount=30),
            damage(3, 30, 1, 9, amount=20),
            damage(4, 40, 1, 10, amount=10),
            damage(5, 10, 2, 11, amount=100),
        ],
        [
            frag(10, 12, 1, 7),
            frag(11, 22, 2, 8),
            frag(12, 32, 2, 9),
            frag(13, 12, 2, 11),
        ],
        [assist(22, 1, 8, receipt_at=50000)],
        life_boundaries=[
            death(100, 12, 7, frag_event_id=10),
            death(101, 22, 8, frag_event_id=11),
            death(102, 32, 9, frag_event_id=12),
            death(103, 12, 11, frag_event_id=13),
        ],
    )

    assert report["definition"] == "damage_conversion_v2"
    assert report["definition_version"] == 2
    assert report["unit"] == "hp_capped_damage"
    assert report["visibility"] == "private_shadow_only"
    assert report["writes"] is False
    assert report["rating_effect"] is False
    assert report["raw_events_included"] is False
    assert report["parameters"]["clock"] == "producer_game_time"
    player = next(row for row in report["players"] if row["player_id"] == 1)
    assert player["damage_total"] == 100
    assert player["damage_to_own_kill"] == 40
    assert player["damage_to_credited_assist"] == 30
    assert player["damage_to_teammate_finish"] == 20
    assert player["unconverted_damage"] == 10
    assert player["outcome_linked_share"] == 0.9
    assert player["team_damage_share"] == 0.5
    assert "event_id" not in player


def test_first_death_boundary_hard_resets_before_later_enemy_frag():
    report = build_damage_conversion(
        [damage(1, 10, 1, 7, amount=50)],
        [frag(10, 14, 1, 7)],
        [],
        life_boundaries=[
            death(100, 12, 7),  # Suicide/teamkill/no canonical frag.
            death(101, 14, 7, frag_event_id=10),
        ],
    )

    player = report["players"][0]
    assert player["damage_to_own_kill"] == 0
    assert player["unconverted_damage"] == 50


def test_canonical_frag_without_death_boundary_suppresses_false_attribution():
    report = build_damage_conversion(
        [damage(1, 10, 1, 7)],
        [frag(10, 12, 1, 7)],
        [],
        life_boundaries=[death(100, 20, 9)],
    )

    assert report["status"] == "incomplete_death_boundary_coverage"
    assert report["players"] == []
    assert report["confidence"]["level"] == "unavailable"


def test_only_canonical_opponent_kills_enter_damage_per_kill():
    report = build_damage_conversion(
        [damage(1, 10, 1, 7, amount=40)],
        [
            frag(10, 12, 1, 7),
            frag(11, 13, 1, 8, killer_team=1, victim_team=1),
        ],
        [],
        life_boundaries=[death(100, 12, 7, frag_event_id=10)],
    )

    player = report["players"][0]
    assert player["opponent_kills"] == 1
    assert player["damage_per_kill"] == 40.0
    assert report["source_coverage"]["producer_frag_clock"]["rows_excluded"] == 1


def test_team_self_missing_team_and_malformed_damage_are_excluded():
    report = build_damage_conversion(
        [
            damage(1, 10, 1, 1, 1, 1),
            damage(2, 11, 1, 2, 1, 1),
            damage(3, 12, 1, 7, None, 2),
            {"attacker_id": 1},
        ],
        [],
        [],
        life_boundaries=[death(100, 20, 7)],
    )
    assert report["players"] == []
    assert report["excluded_rows"]["self_or_team"] == 2
    assert report["excluded_rows"]["missing_team"] == 1
    assert report["excluded_rows"]["malformed"] == 1
    assert report["status"] == "insufficient_source_data"


def test_required_source_mapping_and_replay_do_not_emit_false_zero_players():
    row = damage(1, 10, 1, 7)
    boundaries = [death(100, 12, 7)]
    unavailable = build_damage_conversion(
        [row], [], [], life_boundaries=boundaries,
        source_available={"assist_context": False},
    )
    assert unavailable["status"] == "source_not_captured"
    assert unavailable["players"] == []
    replay = build_damage_conversion(
        [row], [], [], life_boundaries=boundaries, temporal_valid=False
    )
    assert replay["status"] == "timed_metrics_suppressed"
    assert replay["players"] == []


def test_none_is_unavailable_but_captured_empty_assists_are_valid():
    row = damage(1, 10, 1, 7)
    boundaries = [death(100, 12, 7)]
    missing = build_damage_conversion(
        [row], [], None, life_boundaries=boundaries
    )
    assert missing["status"] == "source_not_captured"
    captured_empty = build_damage_conversion(
        [row], [], [], life_boundaries=boundaries
    )
    assert captured_empty["status"] == "available"
    assert captured_empty["players"][0]["unconverted_damage"] == 20


@pytest.mark.parametrize("kwargs", [
    {"conversion_seconds": 0},
    {"assist_grace_seconds": -1},
    {"death_match_tolerance_seconds": -1},
    {"conversion_seconds": float("nan")},
    {"assist_grace_seconds": float("inf")},
])
def test_invalid_config_is_rejected(kwargs):
    with pytest.raises(ValueError):
        build_damage_conversion(
            [], [], [], DamageConversionConfig(**kwargs), life_boundaries=[]
        )
