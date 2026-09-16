"""Fixture-to-game-match binding, and the per-player divergence it enables.

The binding is what makes this a PLAYER rating. Rated off the registered
season roster, every team-mate moves together forever and 152 players hold
17 ratings -- one per team. Rated off who actually played, a player who sits
a week out stops moving while their team-mates keep going.

Pure logic, no network and no openskill for the binding tests, so they run on
the Tier 1 gate. The divergence test needs the model and importorskips.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "mmr"))


def game(gid, started_at):
    return {"id": gid, "game_match_id": f"gm-{gid}", "started_at": started_at}


def people(pairs):
    """[(player_id, game_team), ...] -> game_match_player rows."""
    return [{"player_id": p, "game_team": t, "player_name": f"p{p}"} for p, t in pairs]


FIXTURE = {"id": 900, "scheduled_at": "2026-09-13T19:00:00+00:00",
           "home_season_team_id": 1, "away_season_team_id": 2}
ROSTERS = {1: {1, 2, 3, 4, 5, 6, 7}, 2: {11, 12, 13, 14, 15, 16, 17}}
PLAYED = people([(1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (6, 1),
                 (11, 2), (12, 2), (13, 2), (14, 2), (15, 2), (16, 2)])


class Binding(unittest.TestCase):
    def setUp(self):
        import match_binding as MB
        self.MB = MB

    def test_binds_and_returns_who_actually_played(self):
        bound, unbound = self.MB.bind(
            [FIXTURE], [game(1, "2026-09-13T19:12:00+00:00")], {1: PLAYED}, ROSTERS)
        self.assertEqual(unbound, [])
        b = bound[900]
        # Player 7 and 17 are registered but did NOT play; they must not appear.
        self.assertEqual(b["home_players"], [1, 2, 3, 4, 5, 6])
        self.assertEqual(b["away_players"], [11, 12, 13, 14, 15, 16])
        self.assertEqual(b["overlap"], 12)

    def test_game_teams_are_oriented_onto_the_fixture_not_trusted(self):
        """Game team numbers are arbitrary relative to home/away."""
        swapped = people([(1, 2), (2, 2), (3, 2), (4, 2), (5, 2), (6, 2),
                          (11, 1), (12, 1), (13, 1), (14, 1), (15, 1), (16, 1)])
        bound, _ = self.MB.bind(
            [FIXTURE], [game(1, "2026-09-13T19:12:00+00:00")], {1: swapped}, ROSTERS)
        self.assertEqual(bound[900]["home_players"], [1, 2, 3, 4, 5, 6])

    def test_two_plausible_candidates_bind_to_neither(self):
        """A guess would credit the wrong people, so ambiguity refuses."""
        games = [game(1, "2026-09-13T19:12:00+00:00"), game(2, "2026-09-13T20:30:00+00:00")]
        bound, unbound = self.MB.bind([FIXTURE], games, {1: PLAYED, 2: PLAYED}, ROSTERS)
        self.assertEqual(bound, {})
        self.assertIn("ambiguous", unbound[0]["reason"])

    def test_a_match_on_another_night_is_not_this_fixture(self):
        bound, unbound = self.MB.bind(
            [FIXTURE], [game(1, "2026-09-20T19:00:00+00:00")], {1: PLAYED}, ROSTERS)
        self.assertEqual(bound, {})
        self.assertEqual(unbound[0]["reason"], "no candidate")

    def test_one_sided_overlap_is_refused(self):
        """Both teams must be present, or it is some other team's match."""
        one_side = people([(1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (6, 1),
                           (90, 2), (91, 2), (92, 2), (93, 2), (94, 2), (95, 2)])
        bound, unbound = self.MB.bind(
            [FIXTURE], [game(1, "2026-09-13T19:12:00+00:00")], {1: one_side}, ROSTERS)
        self.assertEqual(bound, {})

    def test_a_substitute_does_not_break_the_binding(self):
        """Real case: 11 of 12 recognised, one player not on either roster."""
        with_sub = people([(1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (99, 1),
                           (11, 2), (12, 2), (13, 2), (14, 2), (15, 2), (16, 2)])
        bound, _ = self.MB.bind(
            [FIXTURE], [game(1, "2026-09-13T19:12:00+00:00")], {1: with_sub}, ROSTERS)
        self.assertIn(99, bound[900]["home_players"], "the sub must be rated, not dropped")
        self.assertEqual(bound[900]["overlap"], 11)
        self.assertEqual(bound[900]["ringers"], [], "unrostered-anywhere is a sub, not a ringer")

    def test_a_ringer_is_recorded_but_excluded_from_rating(self):
        """Player 21 is registered to a THIRD team (not home or away) and
        plays this match for home -- a ringer, not a sub. Recorded in
        `ringers`, dropped from `home_players` so the ladder never rates it,
        and the rest of the side is unaffected."""
        three_teams = {**ROSTERS, 3: {21, 22, 23, 24, 25, 26, 27}}
        with_ringer = people([(1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (21, 1),
                              (11, 2), (12, 2), (13, 2), (14, 2), (15, 2), (16, 2)])
        bound, _ = self.MB.bind(
            [FIXTURE], [game(1, "2026-09-13T19:12:00+00:00")], {1: with_ringer}, three_teams)
        self.assertEqual(bound[900]["home_players"], [1, 2, 3, 4, 5])
        self.assertEqual(bound[900]["ringers"], [21])
        self.assertNotIn(21, bound[900]["home_players"])

    def test_a_ringer_can_appear_on_either_side(self):
        """Same case, mirrored onto away, and combined with a home-side ringer
        too -- both are caught and neither leaks onto the wrong side."""
        three_teams = {**ROSTERS, 3: {21, 22, 23, 24, 25, 26, 27}}
        both_ringers = people([(1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (21, 1),
                               (11, 2), (12, 2), (13, 2), (14, 2), (15, 2), (22, 2)])
        bound, _ = self.MB.bind(
            [FIXTURE], [game(1, "2026-09-13T19:12:00+00:00")], {1: both_ringers}, three_teams)
        self.assertEqual(bound[900]["home_players"], [1, 2, 3, 4, 5])
        self.assertEqual(bound[900]["away_players"], [11, 12, 13, 14, 15])
        self.assertEqual(bound[900]["ringers"], [21, 22])


class Divergence(unittest.TestCase):
    """The reason the binding matters: team-mates must be able to drift apart."""

    def setUp(self):
        import importlib
        if importlib.util.find_spec("openskill") is None:
            self.skipTest("openskill not installed")
        from ladder import OpenSkill
        self.OpenSkill = OpenSkill

    def test_sitting_a_match_out_separates_a_player_from_their_team(self):
        m = self.OpenSkill()
        team, opponent = [1, 2, 3, 4, 5, 6], [11, 12, 13, 14, 15, 16]
        m.update(team, opponent, 1.0)                 # everyone plays week 1
        rested, kept_playing = team[0], team[1]
        self.assertEqual(m.r[rested].mu, m.r[kept_playing].mu, "identical after a shared match")

        # Week 2: player 1 sits out, a substitute takes the slot.
        m.update([99] + team[1:], opponent, 1.0)
        self.assertNotEqual(m.r[rested].mu, m.r[kept_playing].mu,
                            "a player who sat out must not move with the team")
        self.assertGreater(m.games[kept_playing], m.games[rested])

    def test_each_match_played_reduces_that_players_uncertainty(self):
        """'Every subsequent match improves their individual MMR' -- the
        rating becomes better evidenced, which is sigma falling."""
        m = self.OpenSkill()
        team, opponent = [1, 2, 3, 4, 5, 6], [11, 12, 13, 14, 15, 16]
        start = m.r[1].sigma
        seen = [start]
        for _ in range(3):
            m.update(team, opponent, 1.0)
            seen.append(m.r[1].sigma)
        self.assertEqual(seen, sorted(seen, reverse=True),
                         "sigma must fall with every match played")
        self.assertLess(seen[-1], start)

    def test_a_player_who_never_played_is_not_rated_at_all(self):
        m = self.OpenSkill()
        m.update([1, 2, 3, 4, 5, 6], [11, 12, 13, 14, 15, 16], 1.0)
        self.assertNotIn(7, m.ratings(), "a registered but unplayed player earns no rating")

    def test_ratings_carries_matches_played_alongside_mu_sigma_ordinal(self):
        """report_sync.py's publish step needs a games-played count per
        player to gate the website's display threshold -- ratings() is the
        only place that count (self.games) is exposed outside the model."""
        m = self.OpenSkill()
        team, opponent = [1, 2, 3, 4, 5, 6], [11, 12, 13, 14, 15, 16]
        m.update(team, opponent, 1.0)
        m.update(team, opponent, 1.0)
        r = m.ratings()[1]
        self.assertEqual(r["matches"], 2)
        self.assertEqual(set(r.keys()), {"mu", "sigma", "ordinal", "matches"})


if __name__ == "__main__":
    unittest.main()
