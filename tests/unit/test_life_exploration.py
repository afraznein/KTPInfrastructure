from __future__ import annotations

import pytest

from scripts.life_exploration import (
    LifeExplorationConfig,
    build_life_exploration,
)


def boundary(
    event_id: int,
    at: float,
    player: int,
    kind: str,
    reason: str,
    *,
    half: int = 1,
    team: int = 1,
    death_event_id: int | None = None,
    clock: str = "game_time",
) -> dict:
    row = {
        "id": event_id,
        clock: at,
        "player_id": player,
        "steam_id": f"S{player}",
        "player_name": f"P{player}",
        "team": team,
        "half": half,
        "boundary_kind": kind,
        "reason": reason,
    }
    if death_event_id is not None:
        row["death_event_id"] = death_event_id
    return row


def frag(
    event_id: int,
    at: float,
    killer: int,
    victim: int,
    *,
    half: int = 1,
    killer_team: int = 2,
    victim_team: int = 1,
    clock: str = "game_time",
) -> dict:
    return {
        "event_id": event_id,
        clock: at,
        "half": half,
        "killer_id": killer,
        "killer_steam_id": f"S{killer}",
        "killer_name": f"P{killer}",
        "killer_team": killer_team,
        "victim_id": victim,
        "victim_steam_id": f"S{victim}",
        "victim_name": f"P{victim}",
        "victim_team": victim_team,
    }


def assist(
    event_id: int,
    at: float,
    player: int,
    *,
    half: int = 1,
    clock: str = "game_time",
) -> dict:
    return {
        "event_id": event_id,
        clock: at,
        "half": half,
        "assister_id": player,
        "assister_steam_id": f"S{player}",
        "assister_name": f"P{player}",
        "assister_team": 1,
    }


def death_life(
    player: int,
    start_at: float,
    death_at: float,
    start_id: int,
    end_id: int,
    death_frag_id: int,
    *,
    half: int = 1,
    reason: str = "spawn",
    clock: str = "game_time",
) -> list[dict]:
    return [
        boundary(
            start_id, start_at, player, "start", reason,
            half=half, clock=clock,
        ),
        boundary(
            end_id, death_at, player, "end", "death",
            half=half, death_event_id=death_frag_id, clock=clock,
        ),
    ]


def test_kat_aggregates_union_of_kill_assist_and_traded_death_lives():
    boundaries = []
    boundaries += death_life(1, 0, 10, 1, 3, 101)
    boundaries += death_life(1, 20, 30, 4, 6, 103)
    boundaries += death_life(1, 40, 50, 7, 9, 104)
    boundaries += death_life(1, 60, 70, 10, 12, 105)
    frags = [
        frag(100, 5, 1, 7, killer_team=1, victim_team=2),
        frag(101, 10, 7, 1),
        frag(103, 30, 8, 1),
        frag(104, 50, 9, 1),
        frag(105, 70, 10, 1),
    ]
    trades = [{
        "half": 1,
        "death_event_id": 104,
        "fallen_player": {
            "player_id": 1, "steam_id": "S1", "name": "P1", "team": 1,
        },
    }]

    report = build_life_exploration(
        boundaries, frags, [assist(102, 25, 1)], trades,
        LifeExplorationConfig(require_complete_match_frag_coverage=False),
    )

    assert report["definition"] == "life_kat_coverage_v2"
    assert report["definition_version"] == 2
    assert report["parameters"]["denominator"] == "death_ended_lives_only"
    assert report["parameters"]["survival_component"] is False
    assert report["parameters"]["life_scope"] == "physical_lives"
    assert report["parameters"]["live_freeze_classification"] == "unavailable"
    assert report["status"] == "available"
    assert report["visibility"] == "private_shadow_only"
    assert report["writes"] is False
    assert report["rating_effect"] is False
    assert report["raw_timelines_included"] is False
    assert report["aggregate"] == {
        "eligible_lives": 4,
        "covered_lives": 3,
        "kat_coverage": 0.75,
        "lives_with_kill": 1,
        "lives_with_assist": 1,
        "lives_with_traded_death": 1,
        "lives_with_multiple_components": 0,
    }
    assert report["players"] == [{
        "player": {
            "player_id": 1, "steam_id": "S1", "name": "P1", "team": 1,
        },
        "teams": [1],
        **report["aggregate"],
    }]
    assert report["teams"] == [{"team": 1, **report["aggregate"]}]
    assert report["confidence"]["level"] == "medium"


def test_consecutive_start_disconnect_and_open_half_end_are_censored():
    boundaries = [
        boundary(1, 0, 1, "start", "spawn"),
        boundary(3, 5, 1, "start", "spawn"),
        boundary(5, 10, 1, "end", "disconnect"),
        boundary(6, 20, 1, "start", "spawn"),
        boundary(10, 0, 1, "start", "spawn", half=2),
        boundary(
            12, 10, 1, "end", "death", half=2, death_event_id=201,
        ),
    ]
    report = build_life_exploration(
        boundaries,
        [
            frag(2, 2, 1, 7, killer_team=1, victim_team=2),
            frag(201, 10, 7, 1, half=2),
        ],
        [],
        [],
        LifeExplorationConfig(require_complete_match_frag_coverage=False),
    )

    # The kill occurred in a censored life and cannot cover the one eligible
    # death-ended life in the other half.
    assert report["aggregate"]["eligible_lives"] == 1
    assert report["aggregate"]["covered_lives"] == 0
    assert report["aggregate"]["kat_coverage"] == 0.0
    assert report["boundary_coverage"]["lives_reconstructed"] == 4
    assert report["boundary_coverage"]["death_ended_lives"] == 1
    assert report["boundary_coverage"]["censored_lives"] == 3
    assert report["boundary_coverage"]["censored_by_reason"] == {
        "consecutive_start": 1,
        "disconnect": 1,
        "open_at_half_end": 1,
    }


def test_context_live_to_death_is_eligible_but_explicitly_lowers_confidence():
    report = build_life_exploration(
        death_life(1, 3, 10, 1, 3, 20, reason="context_live"),
        [frag(20, 10, 7, 1)],
        [assist(2, 7, 1)],
        [],
    )

    assert report["aggregate"]["eligible_lives"] == 1
    assert report["aggregate"]["kat_coverage"] == 1.0
    assert report["boundary_coverage"]["context_live_started_lives"] == 1
    assert report["confidence"]["level"] == "low"
    assert any("context_live" in reason for reason in report["confidence"]["basis"])


def test_nullable_round_live_is_not_used_to_infer_freeze_or_pause_state():
    boundaries = death_life(1, 0, 10, 1, 3, 20)
    boundaries[0]["round_live"] = None
    boundaries[1]["round_live"] = 0
    report = build_life_exploration(
        boundaries, [frag(20, 10, 7, 1)], [], []
    )

    assert report["aggregate"]["eligible_lives"] == 1
    assert report["parameters"]["life_scope"] == "physical_lives"
    assert report["parameters"]["live_freeze_classification"] == "unavailable"
    assert any(
        "live versus freeze/pause" in limitation
        for limitation in report["limitations"]
    )


def test_source_unavailable_and_replay_suppression_never_emit_false_zeroes():
    boundaries = death_life(1, 0, 10, 1, 3, 20)
    events = [frag(20, 10, 7, 1)]

    unavailable = build_life_exploration(
        boundaries, events, [], [], source_available=False
    )
    assert unavailable["status"] == "source_not_captured"
    assert unavailable["aggregate"]["eligible_lives"] is None
    assert unavailable["aggregate"]["kat_coverage"] is None
    assert unavailable["boundary_coverage"]["death_ended_lives"] is None
    assert unavailable["players"] == []

    replay = build_life_exploration(
        boundaries, events, [], [], temporal_valid=False
    )
    assert replay["status"] == "timed_metrics_suppressed"
    assert replay["aggregate"]["eligible_lives"] is None
    assert replay["aggregate"]["kat_coverage"] is None
    assert replay["players"] == []


def test_one_missing_component_suppresses_instead_of_treating_unknown_as_empty():
    report = build_life_exploration(
        death_life(1, 0, 10, 1, 3, 20),
        [frag(20, 10, 7, 1)],
        [],
        [],
        source_available={"basic_trades": False},
    )

    assert report["status"] == "source_not_captured"
    assert report["source_coverage"]["basic_trades"]["available"] is False
    assert report["source_coverage"]["frags"]["available"] is True
    assert report["aggregate"]["covered_lives"] is None
    assert report["aggregate"]["kat_coverage"] is None

    assist_missing = build_life_exploration(
        death_life(1, 0, 10, 1, 3, 20),
        [frag(20, 10, 7, 1)],
        [],
        [],
        source_available={"assist_context": False},
    )
    assert assist_missing["status"] == "source_not_captured"
    assert assist_missing["source_coverage"]["assists"]["available"] is False


def test_none_is_an_unavailable_source_while_captured_empty_is_not():
    rows = death_life(1, 0, 10, 1, 3, 20)
    missing = build_life_exploration(rows, None, [], [])
    assert missing["status"] == "source_not_captured"
    assert missing["source_coverage"]["frags"]["rows_received"] is None

    captured_empty = build_life_exploration(rows, [], [], [])
    assert captured_empty["status"] == "incomplete_death_frag_coverage"
    assert captured_empty["aggregate"]["eligible_lives"] is None
    assert captured_empty["aggregate"]["kat_coverage"] is None
    assert captured_empty["suicide_inventory"] == {
        "status": "source_not_captured",
        "count": None,
        "unmatched_death_boundaries": 1,
    }


def test_no_death_ended_lives_has_no_rate_not_a_zero_rate():
    report = build_life_exploration(
        [boundary(1, 0, 1, "start", "spawn")], [], [], []
    )

    assert report["status"] == "no_eligible_lives"
    assert report["aggregate"]["eligible_lives"] == 0
    assert report["aggregate"]["covered_lives"] is None
    assert report["aggregate"]["kat_coverage"] is None
    assert report["boundary_coverage"]["censored_by_reason"] == {
        "open_at_half_end": 1,
    }


def test_orphan_and_malformed_boundaries_are_reported_not_inferred():
    rows = [
        boundary(1, 1, 1, "end", "death", death_event_id=10),
        {"id": 2, "game_time": 2, "player_id": 1, "half": 1,
         "boundary_kind": "start", "reason": "unknown_start"},
        *death_life(1, 3, 10, 3, 5, 11),
    ]
    report = build_life_exploration(rows, [frag(11, 10, 7, 1)], [], [])

    assert report["boundary_coverage"]["orphan_end_boundaries"] == 1
    assert report["boundary_coverage"]["rows_excluded"] == 1
    assert report["boundary_coverage"]["death_ended_lives"] == 1
    assert report["confidence"]["level"] == "low"


def test_receipt_epoch_only_rows_are_rejected_for_life_membership():
    boundaries = death_life(
        1, 1000, 1010, 1, 3, 20, clock="event_epoch"
    )
    report = build_life_exploration(
        boundaries,
        [
            frag(
                10, 1005, 1, 7, half=2, killer_team=1,
                victim_team=2, clock="event_epoch",
            ),
            frag(20, 1010, 7, 1, clock="event_epoch"),
        ],
        [],
        [],
    )

    assert report["selected_clock"] is None
    assert report["status"] == "insufficient_boundary_data"
    assert report["aggregate"]["eligible_lives"] is None


def test_dual_clock_facts_choose_producer_game_time_not_delayed_receipt_epoch():
    boundaries = death_life(1, 0, 10, 1, 3, 20)
    boundaries[0]["event_epoch"] = 1000
    boundaries[1]["event_epoch"] = 1010
    frags = [
        frag(10, 4, 1, 7, killer_team=1, victim_team=2),
        frag(20, 10, 8, 1),
    ]
    frags[0]["event_unix"] = 2004
    frags[1]["event_unix"] = 2010
    assists = [{
        "event_id": 11,
        "game_time": 6,
        "event_unix": 3006,
        "half": 1,
        "assister_id": 1,
        "assister_team": 1,
    }]

    report = build_life_exploration(
        boundaries, frags, assists, [],
        LifeExplorationConfig(require_complete_match_frag_coverage=False),
    )

    assert report["selected_clock"] == "game_time"
    assert report["source_coverage"]["assists"]["rows_usable"] == 1
    assert report["aggregate"]["eligible_lives"] == 1
    assert report["aggregate"]["lives_with_kill"] == 1
    assert report["aggregate"]["lives_with_assist"] == 1
    assert report["aggregate"]["covered_lives"] == 1


def test_delayed_assist_receipt_does_not_move_credit_into_next_life():
    boundaries = []
    boundaries += death_life(1, 0, 10, 1, 2, 20)
    boundaries += death_life(1, 20, 30, 3, 4, 21)
    delayed = assist(10, 5, 1)
    delayed["event_unix"] = 25  # Receipt appears inside life two.
    report = build_life_exploration(
        boundaries,
        [frag(20, 10, 7, 1), frag(21, 30, 8, 1)],
        [delayed],
        [],
    )

    assert report["selected_clock"] == "game_time"
    assert report["status"] == "available"
    assert report["aggregate"]["lives_with_assist"] == 1
    assert report["aggregate"]["covered_lives"] == 1


def test_trade_fallback_can_use_fallen_player_half_and_death_time():
    report = build_life_exploration(
        death_life(1, 0, 10, 1, 3, 20),
        [frag(20, 10, 7, 1)],
        [],
        [{
            "half": 1,
            "fallen_player": {"player_id": 1},
            "death_game_time": 10.5,
        }],
        LifeExplorationConfig(death_match_tolerance_seconds=0.5),
    )

    assert report["aggregate"]["lives_with_traded_death"] == 1
    assert report["aggregate"]["kat_coverage"] == 1.0


def test_kill_assist_and_trade_on_one_life_count_as_one_covered_life():
    report = build_life_exploration(
        death_life(1, 0, 10, 1, 5, 20),
        [
            frag(2, 3, 1, 7, killer_team=1, victim_team=2),
            frag(20, 10, 8, 1),
        ],
        [assist(3, 5, 1)],
        [{"death_event_id": 20, "fallen_player": {"player_id": 1}}],
        LifeExplorationConfig(require_complete_match_frag_coverage=False),
    )

    assert report["aggregate"] == {
        "eligible_lives": 1,
        "covered_lives": 1,
        "kat_coverage": 1.0,
        "lives_with_kill": 1,
        "lives_with_assist": 1,
        "lives_with_traded_death": 1,
        "lives_with_multiple_components": 1,
    }


def test_self_and_explicit_same_team_are_excluded_but_missing_team_enemy_frag_counts():
    report = build_life_exploration(
        death_life(1, 0, 10, 1, 6, 20),
        [
            frag(2, 2, 1, 1, killer_team=1, victim_team=1),
            frag(3, 3, 1, 2, killer_team=1, victim_team=1),
            frag(4, 4, 1, 7, killer_team=0, victim_team=2),
            frag(20, 10, 8, 1),
        ],
        [],
        [],
        LifeExplorationConfig(require_complete_match_frag_coverage=False),
    )

    assert report["aggregate"]["lives_with_kill"] == 1
    assert report["aggregate"]["covered_lives"] == 1
    assert report["aggregate"]["kat_coverage"] == 1.0
    assert report["source_coverage"]["frags"]["self_rows"] == 1
    assert report["source_coverage"]["frags"]["explicit_same_team_rows"] == 1
    assert report["source_coverage"]["frags"]["missing_team_context_rows"] == 1
    assert report["confidence"]["level"] == "low"


def test_supplied_but_wholly_unusable_fact_source_is_not_a_false_zero():
    report = build_life_exploration(
        death_life(1, 0, 10, 1, 3, 20),
        [{"event_id": 20, "killer_id": 7, "victim_id": 1}],
        [],
        [],
    )

    assert report["status"] == "insufficient_source_data"
    assert report["source_coverage"]["frags"]["rows_received"] == 1
    assert report["source_coverage"]["frags"]["rows_usable"] == 0
    assert report["aggregate"]["eligible_lives"] is None
    assert report["aggregate"]["kat_coverage"] is None


def test_unmatched_canonical_victim_frag_suppresses_reverse_coverage():
    report = build_life_exploration(
        death_life(1, 0, 10, 1, 3, 20),
        [
            frag(20, 10, 7, 1),
            frag(21, 12, 8, 1),
        ],
        [],
        [],
    )

    assert report["status"] == "incomplete_death_frag_coverage"
    assert report["boundary_coverage"]["death_boundaries_matched_to_frags"] == 1
    assert report["boundary_coverage"]["canonical_victim_frags_unmatched"] == 1
    assert report["boundary_coverage"]["death_frag_bijection_complete"] is False
    assert report["aggregate"]["kat_coverage"] is None


def test_completely_missing_player_life_pair_cannot_shrink_kat_denominator():
    report = build_life_exploration(
        death_life(1, 0, 10, 1, 3, 20),
        [
            frag(20, 10, 7, 1),
            # Player 2 has a canonical death but no life start/end rows at all.
            frag(21, 12, 8, 2),
        ],
        [],
        [],
    )

    assert report["status"] == "incomplete_death_frag_coverage"
    assert report["boundary_coverage"]["canonical_victim_frags_unmatched"] == 1
    assert report["boundary_coverage"]["death_frag_bijection_complete"] is False
    assert report["aggregate"]["eligible_lives"] is None
    assert report["aggregate"]["kat_coverage"] is None


def test_output_contains_aggregate_identity_but_no_raw_life_or_event_timeline():
    report = build_life_exploration(
        death_life(1, 0, 10, 1, 3, 20),
        [frag(20, 10, 7, 1)],
        [],
        [],
    )

    def keys(value):
        if isinstance(value, dict):
            for key, nested in value.items():
                yield key
                yield from keys(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from keys(nested)

    all_keys = set(keys(report))
    assert "event_id" not in all_keys
    assert "start_at" not in all_keys
    assert "end_at" not in all_keys
    assert "lives" not in all_keys


@pytest.mark.parametrize("value", [-0.001, -1, float("inf"), float("nan")])
def test_negative_death_match_tolerance_is_rejected(value):
    with pytest.raises(ValueError, match="death_match_tolerance_seconds"):
        build_life_exploration(
            [], [], [], [],
            LifeExplorationConfig(death_match_tolerance_seconds=value),
        )
