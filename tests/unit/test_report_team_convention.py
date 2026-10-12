"""Engine-side -> report-team translation layer over flag_swing.sides_by_half."""
from __future__ import annotations

from scripts.report_team_convention import (
    engine_side_for_report_team,
    report_team1_engine_side,
    translate_capouts,
    translate_map_control,
    translate_objective_attempts,
    translate_objective_timeline,
    translate_recap_speed,
    translate_team_series,
)

ROSTER = [
    {"player_id": 1, "team": 1},
    {"player_id": 2, "team": 1},
    {"player_id": 3, "team": 2},
    {"player_id": 4, "team": 2},
]


def life(half, pid, team):
    return {"half": half, "player_id": pid, "team": team}


def test_report_team1_engine_side_resolves_the_swapped_half():
    # Report team 1 (players 1, 2) played engine Axis (2) in half 1, and
    # (as ktp_match_players always shows) engine Allies (1) in half 2.
    lives = [life(1, 1, 2), life(1, 2, 2), life(1, 3, 1), life(1, 4, 1),
             life(2, 1, 1), life(2, 2, 1), life(2, 3, 2), life(2, 4, 2)]
    result = report_team1_engine_side(lives, ROSTER)
    assert result == {1: 2, 2: 1}


def test_disagreeing_report_team1_players_drop_the_half():
    lives = [life(1, 1, 1), life(1, 2, 2)]  # both report team 1, split sides
    assert report_team1_engine_side(lives, ROSTER) == {}


def test_translate_map_control_mirrors_when_report_team1_played_engine_side_2():
    mc = {"halves": {"1": [[0.0, 0.2], [4.0, 0.8]]},
          "orientation_by_half": {"1": "team1_at_arc0"},
          "mean_control_team1": 0.5, "caveats": []}
    translate_map_control(mc, {1: 2})
    assert mc["halves"]["1"] == [[0.0, 0.8], [4.0, 0.2]]
    assert mc["orientation_by_half"]["1"] == "team2_at_arc0"
    assert mc["mean_control_team1"] == 0.5


def test_translate_map_control_keeps_engine_side_1_as_is():
    mc = {"halves": {"1": [[0.0, 0.3]]}, "orientation_by_half": {"1": "team1_at_arc0"},
          "mean_control_team1": 0.3, "caveats": []}
    translate_map_control(mc, {1: 1})
    assert mc["halves"]["1"] == [[0.0, 0.3]]
    assert mc["orientation_by_half"]["1"] == "team1_at_arc0"


def test_translate_map_control_drops_unresolved_half_with_a_caveat():
    mc = {"halves": {"1": [[0.0, 0.5]], "2": [[0.0, 0.4]]},
          "orientation_by_half": {"1": "team1_at_arc0", "2": "team1_at_arc0"},
          "mean_control_team1": 0.45, "caveats": []}
    translate_map_control(mc, {2: 1})  # half 1 unresolved
    assert "1" not in mc["halves"]
    assert "2" in mc["halves"]
    assert any("1" in c for c in mc["caveats"])


def test_translate_team_series_swaps_the_differential_when_engine_side_flips():
    rows = [{"team": 1, "half": 1, "metric": "flag_differential", "points": [[0, 2]]},
            {"team": 2, "half": 1, "metric": "flag_differential", "points": [[0, -2]]}]
    out, dropped = translate_team_series(rows, {1: 2})
    by_team = {r["team"]: r["points"] for r in out}
    assert by_team[1] == [[0, -2]]  # report team 1 gets engine team 2's series
    assert by_team[2] == [[0, 2]]
    assert dropped == []


def test_translate_team_series_drops_a_half_with_no_resolved_side():
    rows = [{"team": 1, "half": 1, "metric": "flag_differential", "points": [[0, 1]]},
            {"team": 2, "half": 1, "metric": "flag_differential", "points": [[0, -1]]}]
    out, dropped = translate_team_series(rows, {})
    assert out == []
    assert dropped == [1]


def test_translate_capouts_relabels_team_to_report_convention():
    capouts = [{"half": 1, "game_time": 30.0, "team": 2}]
    out = translate_capouts(capouts, {1: 2})
    assert out == [{"half": 1, "game_time": 30.0, "team": 1}]


def test_translate_capouts_drops_an_unresolved_half():
    capouts = [{"half": 1, "game_time": 30.0, "team": 2}]
    assert translate_capouts(capouts, {}) == []


# --- the capture feed -----------------------------------------------------
# objective_timeline_fact.sql maps the capture's team NAME onto 1=Allies /
# 2=Axis, and match_timelines compares it against a killer's REPORT team.

def capture(half, team, flag="flag_a"):
    return {"half": half, "team": team, "team_name": "Allies" if team == 1 else "Axis",
            "flag_name": flag, "event_unix": 100}


def test_a_capture_in_the_swapped_half_is_relabeled():
    out = translate_objective_timeline([capture(1, 2), capture(1, 1)], {1: 2})
    assert [r["team"] for r in out] == [1, 2]
    assert [r["engine_side"] for r in out] == [2, 1]


def test_the_terminal_half_is_untouched():
    out = translate_objective_timeline([capture(2, 1), capture(2, 2)], {2: 1})
    assert [r["team"] for r in out] == [1, 2]


def test_an_unresolved_half_drops_its_captures():
    out = translate_objective_timeline([capture(1, 1), capture(2, 1)], {2: 1})
    assert [r["half"] for r in out] == [2]


def test_a_capture_with_no_side_is_dropped_rather_than_guessed():
    # objective_timeline_fact.sql emits NULL for any team name but the two.
    out = translate_objective_timeline([{"half": 1, "team": None}], {1: 1})
    assert out == []


# --- recap speed ----------------------------------------------------------
# build_recap_speed keys every recap on the owning engine side, and the page
# renders it as a report team.

def recap(half, team, seconds):
    return {"half": half, "flag_index": 0, "flag_name": "flag_a", "team": team,
            "lost_at": 0.0, "retaken_at": seconds, "seconds": seconds}


def test_recap_events_flip_in_the_swapped_half_only():
    rs = {"recaps": [recap(1, 1, 10.0), recap(2, 1, 20.0)],
          "teams": [{"team": 1, "recaps": 2, "median_seconds": 15.0,
                     "mean_seconds": 15.0}], "caveats": []}
    translate_recap_speed(rs, {1: 2, 2: 1})
    assert [(r["half"], r["team"], r["engine_side"]) for r in rs["recaps"]] == [
        (1, 2, 1), (2, 1, 1)]
    assert rs["team_convention"] == "report_team"


def test_per_team_totals_are_reaggregated_not_relabeled():
    # Engine side 1 took one recap in each half, and those two halves belong to
    # DIFFERENT report teams -- the engine-keyed row said "team 1: 2 recaps".
    rs = {"recaps": [recap(1, 1, 10.0), recap(2, 1, 30.0)], "teams": [], "caveats": []}
    translate_recap_speed(rs, {1: 2, 2: 1})
    assert [(t["team"], t["recaps"], t["mean_seconds"]) for t in rs["teams"]] == [
        (1, 1, 30.0), (2, 1, 10.0)]


def test_median_is_computed_over_the_translated_grouping():
    rs = {"recaps": [recap(2, 1, 10.0), recap(2, 1, 20.0), recap(2, 1, 60.0)],
          "teams": [], "caveats": []}
    translate_recap_speed(rs, {2: 1})
    assert rs["teams"] == [{"team": 1, "recaps": 3, "median_seconds": 20.0,
                            "mean_seconds": 30.0}]


def test_an_unresolved_half_drops_its_recaps_with_a_caveat():
    rs = {"recaps": [recap(1, 1, 10.0), recap(2, 2, 20.0)], "teams": [], "caveats": []}
    translate_recap_speed(rs, {2: 1})
    assert [r["half"] for r in rs["recaps"]] == [2]
    assert [t["team"] for t in rs["teams"]] == [2]
    assert any("Half(s) 1" in c for c in rs["caveats"])


def test_an_unavailable_block_still_declares_its_convention():
    # build_recap_speed returns an envelope with no recaps when the flag-state
    # stream is absent; a consumer must not read that as engine side.
    rs = {"status": "unavailable", "recaps": [], "teams": [], "caveats": []}
    translate_recap_speed(rs, {})
    assert rs["teams"] == [] and rs["team_convention"] == "report_team"
    assert rs["caveats"] == [], "nothing was dropped, so nothing is claimed"


# Report team 1 played engine Axis (2) in half 1 and Allies (1) in half 2 --
# the guaranteed swap, and the only condition the two conventions disagree in.
SWAP = {1: 2, 2: 1}


def attempt(half, attempt_id, capturing_team, kind="start"):
    return {"half": half, "attempt_id": attempt_id, "event_kind": kind,
            "flag_index": 3, "flag_name": "mid",
            "capturing_team": capturing_team, "game_time": 100.0}


def test_a_capture_in_the_swapped_half_is_credited_to_the_right_team():
    rows = translate_objective_attempts([attempt(1, 1, 2), attempt(1, 2, 1)], SWAP)
    assert [r["capturing_team"] for r in rows] == [1, 2]
    assert [r["engine_side"] for r in rows] == [2, 1], "the side is kept beside it"


def test_the_terminal_half_does_not_move():
    # Half 2's conventions agree by construction: this is the built-in control
    # for every change on this layer.
    rows = translate_objective_attempts([attempt(2, 5, 1), attempt(2, 6, 2)], SWAP)
    assert [r["capturing_team"] for r in rows] == [1, 2]


def test_an_unresolvable_half_keeps_the_row_with_no_team():
    # A window is assembled from a START plus its TERMINAL rows. Dropping one
    # of a pair would read as an incomplete window rather than an
    # untranslatable one, and every flag_fights consumer already skips a
    # window whose capturing_team is not 1 or 2.
    rows = translate_objective_attempts(
        [attempt(1, 1, 2), attempt(1, 1, 2, kind="complete")], {})
    assert len(rows) == 2
    assert [r["capturing_team"] for r in rows] == [None, None]
    assert all("engine_side" not in r for r in rows)


def test_a_capturing_team_that_is_not_a_side_is_not_invented():
    rows = translate_objective_attempts([attempt(1, 1, 0), attempt(1, 2, None)], SWAP)
    assert [r["capturing_team"] for r in rows] == [None, None]


def test_attempt_rows_are_copied_not_mutated():
    feed = [attempt(1, 1, 2)]
    translate_objective_attempts(feed, SWAP)
    assert feed[0]["capturing_team"] == 2


def test_everything_else_on_the_row_survives_translation():
    rows = translate_objective_attempts(
        [attempt(1, 7, 2, kind="complete") | {"stop_reason": None,
                                              "peak_progress": 0.9}], SWAP)
    assert rows[0]["attempt_id"] == 7 and rows[0]["event_kind"] == "complete"
    assert rows[0]["flag_name"] == "mid" and rows[0]["peak_progress"] == 0.9


def test_engine_side_for_report_team_is_the_inverse_of_the_translators():
    # positional_shadow's depth is engine-side geometry, so it needs the
    # mapping run the other way.
    assert engine_side_for_report_team(1, 1, SWAP) == 2
    assert engine_side_for_report_team(2, 1, SWAP) == 1
    assert engine_side_for_report_team(1, 2, SWAP) == 1
    assert engine_side_for_report_team(2, 2, SWAP) == 2


def test_engine_side_round_trips_through_the_capture_translator():
    # The two directions must agree, or one of them is a second resolver.
    for half in (1, 2):
        for engine in (1, 2):
            report = translate_objective_attempts(
                [attempt(half, 1, engine)], SWAP)[0]["capturing_team"]
            assert engine_side_for_report_team(report, half, SWAP) == engine


def test_engine_side_refuses_an_unresolvable_half_or_team():
    assert engine_side_for_report_team(1, 3, SWAP) is None, "no side for half 3"
    assert engine_side_for_report_team(0, 1, SWAP) is None
    assert engine_side_for_report_team(None, 1, SWAP) is None
    assert engine_side_for_report_team(1, None, SWAP) is None
