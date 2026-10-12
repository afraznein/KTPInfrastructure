"""Canonical report teams when a player leaves at half and is replaced."""
from __future__ import annotations

from scripts.roster_teams import (
    apply_canonical_teams,
    canonical_teams,
    restamp_damage_teams,
    restamp_frag_teams,
)

# Team A: 1,2,3 (+4 who leaves at half). Team B: 5,6,7.
# Half 1: A on side 2, B on side 1.   Half 2: sides swap, 8 replaces 4.
H1 = [{"half": 1, "player_id": p, "team": 2, "boundary_kind": "start"} for p in (1, 2, 3, 4)] + \
     [{"half": 1, "player_id": p, "team": 1, "boundary_kind": "start"} for p in (5, 6, 7)]
H2 = [{"half": 2, "player_id": p, "team": 1, "boundary_kind": "start"} for p in (1, 2, 3, 8)] + \
     [{"half": 2, "player_id": p, "team": 2, "boundary_kind": "start"} for p in (5, 6, 7)]


def roster(**team_by_pid):
    return [{"player_id": int(pid), "team": team} for pid, team in team_by_pid.items()]


def test_the_half_one_leaver_is_filed_with_his_own_team():
    # The daemon left player 4 on side 2 -- his half-1 side, which in half 2
    # is the opponent's.
    got = canonical_teams(H1 + H2)
    assert got[4] == 1, "the leaver belongs with 1,2,3"
    assert {got[p] for p in (1, 2, 3, 8)} == {1}
    assert {got[p] for p in (5, 6, 7)} == {2}


def test_players_who_played_the_final_half_keep_their_side():
    players = roster(**{"1": 1, "2": 1, "3": 1, "8": 1, "5": 2, "6": 2, "7": 2, "4": 2})
    out = {p["player_id"]: p for p in apply_canonical_teams(players, H1 + H2)}
    assert all("roster_team" not in out[p] for p in (1, 2, 3, 8, 5, 6, 7))
    assert out[4]["team"] == 1 and out[4]["roster_team"] == 2


def test_input_rows_are_not_mutated():
    players = roster(**{"4": 2})
    apply_canonical_teams(players, H1 + H2)
    assert players[0]["team"] == 2


def test_one_half_or_no_life_feed_leaves_the_roster_alone():
    players = roster(**{"4": 2, "1": 2})
    for feed in (None, [], H1):
        out = apply_canonical_teams(players, feed)
        assert [p["team"] for p in out] == [2, 2]
        assert all("roster_team" not in p for p in out)


def test_a_half_played_on_the_same_sides_is_not_flipped():
    same = [{"half": 2, "player_id": p, "team": 2, "boundary_kind": "start"} for p in (1, 2, 3)] + \
           [{"half": 2, "player_id": p, "team": 1, "boundary_kind": "start"} for p in (5, 6, 7)]
    got = canonical_teams(H1 + same)
    assert got[4] == 2 and got[1] == 2 and got[5] == 1


def test_three_halves_carry_back_through_each_swap():
    h3 = [{"half": 3, "player_id": p, "team": 2, "boundary_kind": "start"} for p in (1, 2, 3)] + \
         [{"half": 3, "player_id": p, "team": 1, "boundary_kind": "start"} for p in (5, 6, 7)]
    got = canonical_teams(H1 + H2 + h3)
    # Final half is 3: team A is side 2 there, so A's label is 2.
    assert {got[p] for p in (1, 2, 3)} == {2} and got[4] == 2
    assert {got[p] for p in (5, 6, 7)} == {1}


# --- the frag feed carries the same roster error --------------------------
# `frag_timeline_fact.sql` joins killer_team/victim_team to ktp_match_players,
# so the half-1 leaver's frags read as team kills: both sides of them carry his
# wrong label, and match_timelines drops every one from the competitive set.

def frag(half, killer, killer_team, victim, victim_team):
    return {"half": half, "killer_id": killer, "killer_team": killer_team,
            "victim_id": victim, "victim_team": victim_team}


def corrected_players():
    players = roster(**{"1": 1, "2": 1, "3": 1, "8": 1, "5": 2, "6": 2, "7": 2, "4": 2})
    return apply_canonical_teams(players, H1 + H2)


def test_the_leavers_frags_stop_reading_as_team_kills():
    # Player 4 (roster team 2, canonical team 1) killing player 5 (team 2) in
    # half 1: the feed hands both of them team 2.
    feed = [frag(1, 4, 2, 5, 2), frag(1, 5, 2, 4, 2)]
    out = restamp_frag_teams(feed, corrected_players())
    assert [r["killer_team"] for r in out] == [1, 2]
    assert [r["victim_team"] for r in out] == [2, 1]
    assert all(r["killer_team"] != r["victim_team"] for r in out)


def test_a_restamped_row_records_what_the_roster_said():
    out = restamp_frag_teams([frag(1, 4, 2, 5, 2)], corrected_players())
    assert out[0]["killer_roster_team"] == 2
    assert "victim_roster_team" not in out[0], "player 5 was never wrong"


def test_everyone_who_played_the_final_half_is_untouched():
    feed = [frag(2, 1, 1, 5, 2), frag(2, 6, 2, 3, 1)]
    out = restamp_frag_teams(feed, corrected_players())
    assert out == feed, "a report with no leaver must come out byte-identical"


def test_rows_are_copied_not_mutated():
    feed = [frag(1, 4, 2, 5, 2)]
    restamp_frag_teams(feed, corrected_players())
    assert feed[0]["killer_team"] == 2


def test_a_player_outside_the_roster_keeps_whatever_the_feed_said():
    # frags_outside_roster is a real, counted case; inventing a team for one
    # would turn an unknown into a confident wrong answer.
    out = restamp_frag_teams([frag(1, 99, 1, 5, 2)], corrected_players())
    assert out[0]["killer_team"] == 1 and "killer_roster_team" not in out[0]


def test_no_life_feed_means_no_restamping():
    players = roster(**{"4": 2, "5": 2})
    out = restamp_frag_teams([frag(1, 4, 2, 5, 2)],
                             apply_canonical_teams(players, None))
    assert out[0]["killer_team"] == 2, "nothing to correct from, so nothing moves"


def damage(half, attacker, attacker_team, victim, victim_team, amount=50):
    return {"event_id": f"d{half}{attacker}{victim}", "half": half,
            "attacker_id": attacker, "attacker_team": attacker_team,
            "victim_id": victim, "victim_team": victim_team,
            "game_time": 10.0, "damage_capped": amount}


def test_the_leavers_hits_stop_reading_as_friendly_fire():
    # damage_timeline_fact.sql joins the same roster table, and
    # damage_conversion drops a same-team row as `self_or_team` -- so his
    # damage leaves the denominator rather than landing on the wrong side.
    feed = [damage(1, 4, 2, 5, 2), damage(1, 5, 2, 4, 2)]
    out = restamp_damage_teams(feed, corrected_players())
    assert [r["attacker_team"] for r in out] == [1, 2]
    assert [r["victim_team"] for r in out] == [2, 1]
    assert all(r["attacker_team"] != r["victim_team"] for r in out)


def test_a_restamped_damage_row_records_what_the_roster_said():
    out = restamp_damage_teams([damage(1, 4, 2, 5, 2)], corrected_players())
    assert out[0]["attacker_roster_team"] == 2
    assert "victim_roster_team" not in out[0], "player 5 was never wrong"


def test_real_friendly_fire_is_still_friendly_fire():
    # The guard exists for a reason: two teammates really hitting each other
    # must stay same-team after the correction, or the fix would launder it.
    out = restamp_damage_teams([damage(1, 1, 2, 2, 2)], corrected_players())
    assert out[0]["attacker_team"] == out[0]["victim_team"] == 1


def test_damage_rows_in_the_terminal_half_are_untouched():
    feed = [damage(2, 1, 1, 5, 2), damage(2, 6, 2, 3, 1)]
    assert restamp_damage_teams(feed, corrected_players()) == feed


def test_damage_rows_are_copied_not_mutated():
    feed = [damage(1, 4, 2, 5, 2)]
    restamp_damage_teams(feed, corrected_players())
    assert feed[0]["attacker_team"] == 2


def test_damage_restamp_leaves_the_killer_prefix_alone():
    # Shared implementation with the frag restamp; a role mix-up would write
    # killer_team onto a damage row and silently do nothing useful.
    out = restamp_damage_teams([damage(1, 4, 2, 5, 2)], corrected_players())
    assert "killer_team" not in out[0] and "killer_roster_team" not in out[0]
