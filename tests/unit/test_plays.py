"""Plays: per-player best moments, the match's top three, and the dunce."""
from __future__ import annotations

from scripts import analytics_report_dto as dto
from scripts.plays import PlaysConfig, build_plays

ROSTER = [
    {"player_id": 1, "player_name_at_match": "alpha", "team": 1},
    {"player_id": 2, "player_name_at_match": "bravo", "team": 1},
    {"player_id": 3, "player_name_at_match": "charlie", "team": 2},
    {"player_id": 4, "player_name_at_match": "delta", "team": 2},
]
# Sides per half from life boundaries: same as roster in half 1.
LIVES = [{"half": 1, "player_id": p["player_id"], "team": p["team"], "game_time": 0.0, "boundary_kind": "start"}
         for p in ROSTER]


def frag(t, killer, victim, delta, half=1):
    return {"half": half, "game_time": t, "kind": "frag", "killer_id": killer, "victim_id": victim,
            "killer_man_advantage": 0, "p_allies_after": 0.5, "delta": delta}


def flag(t, delta, credited, denied=False, half=1):
    return {"half": half, "game_time": t, "kind": "flag", "flag_index": 4, "owner": 1,
            "credited": credited, "allies_flags": 3, "axis_flags": 2, "capout_denied": denied,
            "p_allies_after": 0.5, "delta": delta}


def test_unavailable_paths():
    assert build_plays([], ROSTER, LIVES)["status"] == "unavailable"
    assert build_plays([frag(10, 1, 3, 0.1)], ROSTER, LIVES, source_status="unavailable")["status"] == "unavailable"


def test_kills_cluster_into_a_play_signed_from_the_players_side():
    # alpha (Allies) gets a 3k in 8 s; charlie (Axis) kills bravo later.
    tl = [frag(100, 1, 3, 0.04), frag(104, 1, 4, 0.05), frag(108, 1, 3, 0.03), frag(300, 3, 2, -0.04)]
    out = build_plays(tl, ROSTER, LIVES)
    top = out["match_top"][0]
    assert top["player_id"] == 1 and top["kills"] == 3 and "3k" in top["tags"]
    assert abs(top["value"] - 0.12) < 1e-9 and top["start"] == 100 and top["end"] == 108
    charlie = next(r for r in out["per_player"] if r["player_id"] == 3)
    assert charlie["plays"][0]["value"] > 0  # an Axis kill is positive for charlie
    bravo = next(r for r in out["per_player"] if r["player_id"] == 2)
    assert bravo["plays"] == []  # a death is not a best play


def test_cap_credit_is_split_and_denial_tagged():
    tl = [flag(200, 0.2, [1, 2], denied=True)]
    out = build_plays(tl, ROSTER, LIVES)
    plays = {p["player_id"]: p for p in out["match_top"]}
    assert set(plays) == {1, 2}
    assert abs(plays[1]["value"] - 0.1) < 1e-9 and plays[1]["capout_denials"] == 1
    assert "cap-out denial" in plays[1]["tags"]


def test_excursion_merges_events_and_charges_exposure():
    tl = [frag(150, 1, 3, 0.02), frag(158, 4, 1, -0.03)]
    exc = [{"half": 1, "player_id": 1, "start": 120.0, "end": 156.0, "duration": 36.0,
            "min_teammate_distance": 1500, "closest_flag": "axis_hq", "closest_flag_distance": 120}]
    out = build_plays(tl, ROSTER, LIVES, exc, config=PlaysConfig(dunce_floor=-0.01))
    alpha = next(r for r in out["per_player"] if r["player_id"] == 1)
    # value = +0.02 (kill) - 0.03 (death) - 0.04 * 36/60 (exposure) = -0.034 -> the match's worst
    assert alpha["plays"] == []
    assert out["plays_total"] == 3  # alpha's excursion (kill + death merged), charlie's death, delta's kill
    exposure_play = out["dunce"]
    assert exposure_play["player_id"] == 1 and exposure_play["excursion"]
    assert exposure_play["kills"] == 1 and exposure_play["deaths"] == 1
    assert abs(exposure_play["exposure"] + 0.024) < 1e-9
    assert exposure_play["start"] == 120.0 and exposure_play["end"] == 158.0


def _all(out):
    seen = {}
    for p in out["match_top"]:
        seen[(p["player_id"], p["start"])] = p
    for row in out["per_player"]:
        for p in row["plays"]:
            seen[(p["player_id"], p["start"])] = p
    if out["dunce"]:
        p = out["dunce"]; seen[(p["player_id"], p["start"])] = p
    return list(seen.values())


def test_dunce_is_the_wasted_run_not_the_plain_death():
    # bravo dies in a fight (-0.04); alpha walks alone for 60 s, does nothing, dies (-0.04 - 0.04).
    tl = [frag(100, 3, 2, -0.04), frag(400, 4, 1, -0.04)]
    exc = [{"half": 1, "player_id": 1, "start": 338.0, "end": 398.0, "duration": 60.0,
            "min_teammate_distance": 2000, "closest_flag": "axis_hq", "closest_flag_distance": 1500}]
    out = build_plays(tl, ROSTER, LIVES, exc)
    d = out["dunce"]
    assert d["player_id"] == 1 and d["excursion"] and d["deaths"] == 1 and d["kills"] == 0
    assert abs(d["value"] + 0.08) < 1e-9
    assert "loiter" in d["tags"] and "died for nothing" in d["tags"]
    assert "60 s alone behind the lines" in d["summary"]


def test_dunce_needs_a_real_cost_unless_it_is_a_wasted_run():
    out = build_plays([frag(100, 3, 2, -0.02)], ROSTER, LIVES, config=PlaysConfig(dunce_floor=-0.05))
    assert out["dunce"] is None  # an ordinary death is not a dunce
    exc = [{"half": 1, "player_id": 1, "start": 300.0, "end": 315.0, "duration": 15.0,
            "min_teammate_distance": 1400, "closest_flag": "axis_hq", "closest_flag_distance": 1100}]
    out = build_plays([frag(100, 3, 2, -0.02)], ROSTER, LIVES, exc, config=PlaysConfig(dunce_floor=-0.05))
    assert out["dunce"]["player_id"] == 1 and out["dunce"]["tags"] == ["loiter"]  # -0.01, but a wasted run


def test_sneak_versus_run_through_and_attempt_tags():
    cap_tl = [flag(300, 0.2, [1])]
    sneak = [{"half": 1, "player_id": 1, "start": 270.0, "end": 300.0, "duration": 30.0,
              "min_teammate_distance": 1500, "closest_flag": "axis_hq", "closest_flag_distance": 50}]
    assert "sneak cap" in build_plays(cap_tl, ROSTER, LIVES, sneak)["match_top"][0]["tags"]
    quick = [dict(sneak[0], start=288.0, duration=12.0)]
    assert "solo cap" in build_plays(cap_tl, ROSTER, LIVES, quick)["match_top"][0]["tags"]
    attempt = [dict(sneak[0], closest_flag_distance=300)]
    out = build_plays([frag(305, 3, 1, -0.03)], ROSTER, LIVES, attempt)
    play = next(p for p in _all(out) if p["excursion"])
    assert "attempt" in play["tags"]


def test_public_block_carries_names_only_and_passes_the_privacy_gate():
    tl = [frag(100, 1, 3, 0.04), frag(104, 1, 4, 0.05), frag(300, 3, 2, -0.04), frag(400, 4, 1, -0.04)]
    exc = [{"half": 1, "player_id": 1, "start": 338.0, "end": 398.0, "duration": 60.0,
            "min_teammate_distance": 2000, "closest_flag": "axis_hq", "closest_flag_distance": 1500}]
    plays = build_plays(tl, ROSTER, LIVES, exc)
    report = {
        "schema_version": 18, "match_id": "1.3-1-TST1", "generated_at": "2026-09-19 00:00:00",
        "match": {"match_id": "1.3-1-TST1", "map_name": "dod_anzio", "started_at": "2026-09-19 00:00:00",
                  "ended_at": "2026-09-19 00:40:00", "halves_played": 2, "duration_seconds": 2400},
        "players": ROSTER, "teams": [], "weapons": [], "duel_matrix": [], "assists": [],
        "capture_events": [], "capture_credits": [], "cap_participation": [],
        "shadow_explorations": {"plays": plays},
        "positional": {}, "spatial_layers": {}, "quality": {}, "source_mode": "database",
    }
    out = dto.sanitize_report(report)
    dto.assert_sanitized(out)
    block = out["plays"]
    assert block["status"] == "available"
    assert block["match_top"][0]["name"] == "alpha" and "player_id" not in block["match_top"][0]
    assert "dunce" not in block  # private only: end-of-season material, never the match page
    assert plays["dunce"]["player_id"] == 1  # still computed in the shadow block
    assert [row["name"] for row in block["per_player"]] == ["alpha", "bravo", "charlie", "delta"]


def test_a_capout_completion_is_tagged_and_summarised():
    tl = [dict(flag(300, 0.2, [1]), capout_completed=True)]
    out = build_plays(tl, ROSTER, LIVES)
    top = out["match_top"][0]
    assert "cap-out" in top["tags"] and top["capout_completions"] == 1
    assert "(capped out)" in top["summary"]


def test_a_touch_taken_ahead_of_the_team_is_a_fast_push():
    tl = [flag(300, 0.2, [1])]
    touches = [{"half": 1, "player_id": 1, "flag": "axis_hq", "game_time": 300.0,
                "teammate_gap": 1362, "depth": 0.805, "depth_gain": 0.14}]
    out = build_plays(tl, ROSTER, LIVES, touches=touches)
    play = out["match_top"][0]
    assert "fast push" in play["tags"] and "cap" not in play["tags"]
    assert play["teammate_gap_at_touch"] == 1362
    assert "pushed past the team to the flag" in play["summary"]


def test_a_touch_taken_with_the_team_is_an_ordinary_cap():
    tl = [flag(300, 0.2, [1])]
    touches = [{"half": 1, "player_id": 1, "flag": "axis_hq", "game_time": 300.0,
                "teammate_gap": 300, "depth": 0.8, "depth_gain": 0.1}]
    out = build_plays(tl, ROSTER, LIVES, touches=touches)
    assert out["match_top"][0]["tags"] == ["cap"]


def test_an_excursion_still_wins_over_the_fast_push_tag():
    tl = [flag(300, 0.2, [1])]
    exc = [{"half": 1, "player_id": 1, "start": 270.0, "end": 300.0, "duration": 30.0,
            "min_teammate_distance": 1500, "closest_flag": "axis_hq", "closest_flag_distance": 50}]
    touches = [{"half": 1, "player_id": 1, "flag": "axis_hq", "game_time": 300.0,
                "teammate_gap": 1500, "depth": 0.9, "depth_gain": 0.2}]
    out = build_plays(tl, ROSTER, LIVES, exc, touches=touches)
    assert "sneak cap" in out["match_top"][0]["tags"]
    assert "fast push" not in out["match_top"][0]["tags"]


def test_a_round_ending_cap_is_worth_what_was_still_outstanding():
    # The round was 77% won before the touch, so closing it is worth 0.23 --
    # not the 0.10 flag-control move.
    tl = [dict(flag(300, 0.10, [1]), capout_completed=True, terminal_value=0.23)]
    play = build_plays(tl, ROSTER, LIVES)["match_top"][0]
    assert abs(play["value"] - 0.23) < 1e-9 and "cap-out" in play["tags"]


def test_a_tap_in_on_a_round_already_won_is_worth_little():
    tl = [dict(flag(300, 0.10, [1]), capout_completed=True, terminal_value=0.04)]
    play = build_plays(tl, ROSTER, LIVES)["match_top"][0]
    assert abs(play["value"] - 0.04) < 1e-9


def test_three_players_on_the_flag_split_the_round_win():
    tl = [dict(flag(300, 0.10, [1, 2], denied=False), capout_completed=True, terminal_value=0.30)]
    out = build_plays(tl, ROSTER, LIVES)
    assert all(abs(p["value"] - 0.15) < 1e-9 for p in out["match_top"])


def test_an_ordinary_cap_still_prices_on_the_flag_delta():
    play = build_plays([flag(300, 0.2, [1])], ROSTER, LIVES)["match_top"][0]
    assert abs(play["value"] - 0.2) < 1e-9


def brink(t, credited, half=1):
    return {"half": half, "game_time": t, "credited": list(credited)}


def only(out):
    """The single play, read off the public envelope (there is no raw list)."""
    return out["match_top"][0]


# A cap that leaves the enemy one flag from losing is TAGGED, never repriced:
# measured 2x cap-out conversion over 963 brinks, which the swing curve cannot
# show because it flattens exactly there. Pricing belongs to infra-mmr-ratings.
def test_a_cap_that_reached_the_brink_is_tagged():
    play = only(build_plays([flag(100.0, 0.2, [1])], ROSTER, LIVES,
                            brinks=[brink(100.0, [1])]))
    assert "brink" in play["tags"]
    assert "one flag from a cap-out" in play["summary"]


def test_an_ordinary_cap_is_not_tagged_as_a_brink():
    play = only(build_plays([flag(100.0, 0.2, [1])], ROSTER, LIVES, brinks=[]))
    assert "brink" not in play["tags"]


def test_a_brink_credited_to_someone_else_does_not_tag_this_play():
    play = only(build_plays([flag(100.0, 0.2, [1])], ROSTER, LIVES,
                            brinks=[brink(100.0, [2])]))
    assert "brink" not in play["tags"]


def test_a_brink_in_another_half_does_not_tag_this_play():
    play = only(build_plays([flag(100.0, 0.2, [1])], ROSTER, LIVES,
                            brinks=[brink(100.0, [1], half=2)]))
    assert "brink" not in play["tags"]


def test_a_distant_brink_does_not_tag_this_play():
    play = only(build_plays([flag(100.0, 0.2, [1])], ROSTER, LIVES,
                            brinks=[brink(400.0, [1])]))
    assert "brink" not in play["tags"]


def test_the_brink_tag_does_not_change_the_value():
    plain = only(build_plays([flag(100.0, 0.2, [1])], ROSTER, LIVES, brinks=[]))
    tagged = only(build_plays([flag(100.0, 0.2, [1])], ROSTER, LIVES,
                              brinks=[brink(100.0, [1])]))
    assert plain["value"] == tagged["value"]
    assert plain["event_value"] == tagged["event_value"]
