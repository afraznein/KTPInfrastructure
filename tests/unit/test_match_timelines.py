from __future__ import annotations

import pytest

from scripts.match_timelines import TimelineConfig, build_shadow_timelines


def frag(event_id, at, killer, victim, killer_team, victim_team, half=1):
    return {
        "event_id": event_id,
        "event_unix": at,
        "game_time": at,
        "event_time": f"t{at}",
        "half": half,
        "killer_id": killer,
        "killer_steam_id": f"S{killer}",
        "killer_name": f"P{killer}",
        "killer_team": killer_team,
        "victim_id": victim,
        "victim_steam_id": f"S{victim}",
        "victim_name": f"P{victim}",
        "victim_team": victim_team,
        "weapon": "garand",
        "headshot": 0,
    }


def death(event_id, at, player, half=1):
    return {
        "id": event_id,
        "game_time": at,
        "half": half,
        "player_id": player,
        "boundary_kind": "end",
        "reason": "death",
    }


def test_shadow_timelines_detect_multikill_trade_opening_and_conversion():
    frags = [
        frag(1, 100, 1, 7, 1, 2),
        frag(2, 104, 1, 8, 1, 2),
        frag(3, 107, 9, 1, 2, 1),
        frag(4, 109, 2, 9, 1, 2),
    ]
    objectives = [{
        "event_unix": 112,
        "event_time": "t112",
        "half": 1,
        "team": 1,
        "team_name": "Allies",
        "flag_name": "middle",
    }]
    boundaries = [
        death(101, 100, 7), death(102, 104, 8),
        death(103, 107, 1), death(104, 109, 9),
    ]

    report = build_shadow_timelines(
        frags, objectives, death_boundaries=boundaries
    )

    assert report["privacy"] == "private_shadow_only"
    assert report["writes"] is False
    assert report["rating_effect"] is False
    assert report["opening_duels"][0]["winner"]["player_id"] == 1
    sequence = report["fast_multikills"][0]
    assert sequence["classification"] == "fast_2k"
    assert sequence["objective_conversion"]["converted"] is True
    assert sequence["objective_conversion"]["seconds_after"] == 8.0
    assert [row["trader"]["player_id"] for row in report["trades"]] == [9, 2]

    analysis = report["trade_analysis"]
    assert analysis["definition_version"] == 3
    assert analysis["status"] == "available"
    assert analysis["trade_kills"] == analysis["deaths_traded"] == 2
    assert analysis["team_death_response_opportunities"] == 4
    assert analysis["team_death_response_rate"] == 0.5
    assert analysis["deprecated_aliases"] == {
        "trade_opportunities": 4,
        "trade_conversion_rate": 0.5,
    }
    # Every participant is represented, including player 7 with no successful
    # trade kill or traded death.
    player7 = next(
        row for row in analysis["players"] if row["player"]["player_id"] == 7
    )
    assert player7["trade_kills"] == 0
    assert player7["deaths_traded"] == 0
    assert player7["deaths_suffered"] == 1


def test_window_values_are_configurable_and_reported():
    config = TimelineConfig(
        multikill_seconds=3,
        trade_seconds=1,
        objective_conversion_seconds=4,
        death_match_tolerance_seconds=0.25,
    )
    report = build_shadow_timelines([
        frag(1, 100, 1, 7, 1, 2), frag(2, 104, 1, 8, 1, 2),
    ], [], config)
    assert report["config"] == {
        "multikill_seconds": 3,
        "trade_seconds": 1,
        "objective_conversion_seconds": 4,
        "death_match_tolerance_seconds": 0.25,
    }
    assert report["fast_multikills"] == []


def test_replay_suppresses_timed_inferences_but_keeps_ordered_facts():
    report = build_shadow_timelines(
        [frag(1, 100, 1, 7, 1, 2), frag(2, 102, 1, 8, 1, 2)],
        [],
        temporal_valid=False,
        death_boundaries=[],
    )
    assert report["status"] == "timed_metrics_suppressed"
    assert report["fast_multikills"] == []
    assert report["trades"] == []
    assert report["trade_analysis"]["status"] == "timed_metrics_suppressed"
    assert report["trade_analysis"]["team_death_response_rate"] is None
    assert report["revenge_analysis"]["status"] == "timed_metrics_suppressed"
    assert report["revenge_events"] == []
    assert len(report["opening_duels"]) == 1
    assert len(report["head_to_head"]) == 2


def test_trade_is_symmetric_excludes_invalid_rows_and_uses_new_denominator_name():
    report = build_shadow_timelines([
        frag(1, 100, 1, 7, 1, 2),
        frag(2, 101, 1, 8, 1, 2),
        frag(3, 103, 9, 1, 2, 1),
        frag(4, 104, 3, 4, 1, 1),
        frag(5, 105, 5, 5, 1, 1),
    ], [])

    analysis = report["trade_analysis"]
    assert len(report["trades"]) == 1
    assert analysis["trade_kills"] == analysis["deaths_traded"] == 1
    assert analysis["team_death_response_opportunities"] == 3
    assert analysis["team_death_response_rate"] == 0.3333
    coverage = analysis["source_coverage"]["canonical_frag_source"]
    assert coverage["explicit_same_team_rows"] == 1
    assert coverage["self_rows"] == 1
    assert analysis["confidence"]["level"] == "low"


def test_trade_reply_allocates_to_most_recent_eligible_death():
    report = build_shadow_timelines([
        frag(1, 100, 1, 7, 1, 2),
        frag(2, 102, 1, 8, 1, 2),
        frag(3, 104, 9, 1, 2, 1),
    ], [])

    assert len(report["trades"]) == 1
    assert report["trades"][0]["death_event_id"] == 2
    assert report["trades"][0]["fallen_player"]["player_id"] == 8


def test_missing_team_context_retains_canonical_death_but_suppresses_exact_rate():
    report = build_shadow_timelines([
        frag(1, 100, 1, 7, None, None),
    ], [])

    analysis = report["trade_analysis"]
    assert analysis["status"] == "partial_team_context"
    assert analysis["team_death_response_opportunities"] == 1
    assert analysis["team_death_response_rate"] is None
    assert analysis["source_coverage"]["canonical_frag_source"][
        "missing_team_context_rows"
    ] == 1
    assert analysis["confidence"]["level"] == "low"


def test_revenge_expires_on_noncanonical_death_boundary():
    frags = [
        frag(1, 10, 1, 7, 1, 2),
        frag(2, 20, 7, 1, 2, 1),
        frag(3, 30, 3, 7, 1, 2),
        frag(4, 32, 7, 3, 2, 1),
    ]
    boundaries = [
        death(101, 10, 7),
        death(102, 15, 7),  # Suicide/teamkill-equivalent reset; no frag row.
        death(103, 20, 1),
        death(104, 30, 7),
        death(105, 32, 3),
    ]

    report = build_shadow_timelines(
        frags, [], death_boundaries=boundaries
    )

    assert report["revenge_analysis"]["status"] == "available"
    assert [row["revenge_event_id"] for row in report["revenge_events"]] == [4]
    assert report["revenge_events"][0]["death_event_id"] == 3


def test_revenge_requires_producer_clock_and_all_death_boundaries():
    row = frag(1, 10, 1, 7, 1, 2)
    assert build_shadow_timelines([row], [])["revenge_analysis"]["status"] == (
        "source_not_captured"
    )
    without_clock = dict(row)
    without_clock.pop("game_time")
    report = build_shadow_timelines(
        [without_clock], [], death_boundaries=[death(2, 10, 7)]
    )
    assert report["revenge_analysis"]["status"] == "insufficient_source_data"
    assert report["revenge_events"] == []


def test_shadow_output_reports_versioned_trade_and_revenge_definitions():
    report = build_shadow_timelines([], [])

    assert report["definitions"]["basic_trade"]["definition_version"] == 3
    assert report["definitions"]["basic_trade"]["parameters"]["allocation"] == (
        "most_recent_eligible_team_death"
    )
    assert report["definitions"]["revenge_response"] == {
        "definition_version": 2,
        "parameters": {
            "same_half": True,
            "expires_on_next_death": True,
            "time_limit_seconds": None,
            "clock": "producer_game_time",
            "all_death_boundaries_required": True,
        },
    }


@pytest.mark.parametrize("kwargs", [
    {"trade_seconds": 0},
    {"death_match_tolerance_seconds": float("nan")},
    {"conversion": float("inf")},
])
def test_invalid_window_is_rejected(kwargs):
    if "conversion" in kwargs:
        kwargs = {"objective_conversion_seconds": kwargs["conversion"]}
    with pytest.raises(ValueError):
        build_shadow_timelines([], [], TimelineConfig(**kwargs))


# --- the half-time leaver, end to end ------------------------------------
# The feed hands this module killer_team/victim_team straight off
# ktp_match_players, so a player who leaves at the break carries the opponent's
# label and BOTH sides of his frags read as the same team. Nothing here is
# mislabeled -- the rows are discarded as explicit team kills, which
# _frag_classification's own comment calls a source-contract violation because
# hlstats_Events_Frags already excludes teamkills.
#
# Report team 1 = {1, 2} and plays engine side 2 in half 1; player 4 is report
# team 1 and leaves at the break, so the roster files him on team 2.

LEAVER_FEED_AS_THE_ROSTER_GIVES_IT = [
    frag(1, 100, 4, 7, 2, 2),   # the leaver's own kill, both sides read team 2
    frag(2, 103, 7, 4, 2, 2),   # and the answer to it
    frag(3, 106, 1, 8, 1, 2),
]

LEAVER_LIFE_FEED = (
    [{"half": 1, "player_id": p, "team": 2} for p in (1, 2, 4)]
    + [{"half": 1, "player_id": p, "team": 1} for p in (7, 8)]
    + [{"half": 2, "player_id": p, "team": 1} for p in (1, 2)]
    + [{"half": 2, "player_id": p, "team": 2} for p in (7, 8)]
)

LEAVER_ROSTER = [{"player_id": p, "team": 2} for p in (1, 2, 4)] \
    + [{"player_id": p, "team": 1} for p in (7, 8)]


def test_the_leavers_frags_are_dropped_from_the_competitive_set_untouched():
    report = build_shadow_timelines(
        LEAVER_FEED_AS_THE_ROSTER_GIVES_IT, [], TimelineConfig())
    assert report["trades"] == [], "the trade is invisible while both sides read team 2"
    assert report["fast_multikills"] == []
    coverage = report["trade_analysis"]["source_coverage"]["canonical_frag_source"]
    assert coverage["explicit_same_team_rows"] == 2
    assert coverage["opponent_frag_rows"] == 1, "only the unaffected frag survives"


def test_restamping_from_the_corrected_roster_recovers_them():
    from scripts.report_team_convention import report_team1_engine_side
    from scripts.roster_teams import apply_canonical_teams, restamp_frag_teams

    players = apply_canonical_teams(LEAVER_ROSTER, LEAVER_LIFE_FEED)
    assert {p["player_id"]: p["team"] for p in players}[4] == 1, "fixture precondition"
    # And the swap this case needs is really in the fixture: report team 1
    # played engine side 2 in half 1 and side 1 in half 2.
    assert report_team1_engine_side(LEAVER_LIFE_FEED, players) == {1: 2, 2: 1}

    report = build_shadow_timelines(
        restamp_frag_teams(LEAVER_FEED_AS_THE_ROSTER_GIVES_IT, players),
        [], TimelineConfig())
    assert [row["trader"]["player_id"] for row in report["trades"]] == [7]
    assert report["trades"][0]["original_killer"] == {
        "player_id": 4, "steam_id": "S4", "name": "P4", "team": 1,
    }, "the leaver is filed on his own team, not his opponents'"
    coverage = report["trade_analysis"]["source_coverage"]["canonical_frag_source"]
    assert coverage["explicit_same_team_rows"] == 0
    assert coverage["opponent_frag_rows"] == 3


def test_an_objective_conversion_is_credited_to_the_killer_not_his_opponent():
    from scripts.report_team_convention import (
        report_team1_engine_side,
        translate_objective_timeline,
    )
    from scripts.roster_teams import apply_canonical_teams, restamp_frag_teams

    players = apply_canonical_teams(LEAVER_ROSTER, LEAVER_LIFE_FEED)
    team1_engine_side = report_team1_engine_side(LEAVER_LIFE_FEED, players)
    # Two kills by report team 1, then a capture BY report team 1 -- which in
    # half 1 is engine Axis (2), the side the capture feed names.
    frags = [frag(1, 100, 1, 7, 2, 1), frag(2, 103, 1, 8, 2, 1)]
    captures = [{"event_unix": 110, "event_time": "t110", "half": 1,
                 "team": 2, "team_name": "Axis", "flag_name": "middle"}]

    raw = build_shadow_timelines(
        restamp_frag_teams(frags, players), captures, TimelineConfig())
    assert raw["fast_multikills"][0]["objective_conversion"]["converted"] is False, \
        "engine side 2 against report team 1 never matches"

    fixed = build_shadow_timelines(
        restamp_frag_teams(frags, players),
        translate_objective_timeline(captures, team1_engine_side),
        TimelineConfig())
    conversion = fixed["fast_multikills"][0]["objective_conversion"]
    assert conversion["converted"] is True
    assert conversion["seconds_after"] == 7.0
