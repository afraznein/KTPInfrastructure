"""outnumbered_kill_v1 against a synthetic half whose alive counts are set by hand."""
import unittest

from scripts.outnumbered_kills import OUTNUMBERED_MARGIN, build_outnumbered_kills

E0 = 1_800_000_000
MATCH = "fixture-TEST"
# Team 1 is players 1-3, team 2 is players 4-7. Half 1: team 1 plays Allies.
PLAYERS = [{"player_id": pid, "player_name_at_match": f"p{pid}", "team": 1 if pid <= 3 else 2}
           for pid in range(1, 8)]


def life(half, pid, kind, t, reason=None):
    team = (1 if pid <= 3 else 2) if half == 1 else (2 if pid <= 3 else 1)
    return {"half": half, "player_id": pid, "boundary_kind": kind,
            "reason": reason or ("spawn" if kind == "start" else "death"),
            "team": team, "player_class": 1, "game_time": float(t),
            "event_epoch": E0 + half * 10_000 + int(t)}


def frag(half, killer, victim, t, clocked=True):
    epoch = E0 + half * 10_000 + int(t)
    return {"half": half if clocked else None, "stored_half": half,
            "producer_match_id": MATCH if clocked else None, "stored_match_id": MATCH,
            "killer_id": killer, "victim_id": victim, "weapon": "kar", "headshot": 0,
            "game_time": float(t) if clocked else None,
            "event_epoch": epoch if clocked else None, "receipt_epoch": epoch + 1}


def spawn_all(half=1, t=0, pids=range(1, 8)):
    return [life(half, pid, "start", t) for pid in pids]


def build(frags, lives, players=PLAYERS, **kw):
    return build_outnumbered_kills(frags, lives, players, match_id=MATCH,
                                   source_available=kw.pop("source_available", True), **kw)


def row(result, half, pid):
    return next(r for r in result["rows"] if r["half"] == half and r["player_id"] == pid)


class OutnumberedKills(unittest.TestCase):
    def test_margin_is_two_and_the_killer_counts_on_their_own_side(self):
        self.assertEqual(OUTNUMBERED_MARGIN, 2)
        # Team 1 down to player 1 alone; 4 enemies alive before the kill: 4 - 1 = 3.
        lives = spawn_all() + [life(1, 2, "end", 10), life(1, 3, "end", 11),
                               life(1, 4, "end", 50)]
        result = build([frag(1, 1, 4, 50)], lives)
        self.assertEqual(result["status"], "available")
        self.assertEqual(row(result, 1, 1)["outnumbered_kills"], 1)
        self.assertEqual(result["margin_histogram"], {"3": 1})

    def test_one_short_of_the_margin_does_not_count(self):
        # 2 teammates alive (killer included) against 3 enemies: margin 1.
        lives = spawn_all() + [life(1, 3, "end", 10), life(1, 5, "end", 11),
                               life(1, 4, "end", 50)]
        result = build([frag(1, 1, 4, 50)], lives)
        self.assertEqual(row(result, 1, 1)["outnumbered_kills"], 0)
        self.assertEqual(result["margin_histogram"], {"1": 1})

    def test_the_victim_is_alive_just_before_the_kill(self):
        # Exactly at the margin only because the victim still counts: 3 enemies
        # before the kill (4, 5, 6) against the lone killer is 2, not 1.
        lives = spawn_all() + [life(1, 2, "end", 10), life(1, 3, "end", 11),
                               life(1, 7, "end", 12), life(1, 4, "end", 50)]
        result = build([frag(1, 1, 4, 50)], lives)
        self.assertEqual(row(result, 1, 1)["outnumbered_kills"], 1)

    def test_a_kill_after_the_killers_death_still_counts_the_killer(self):
        # Player 1 died at 40; their grenade lands at 50. Teammates 2 and 3 are
        # dead too. Counting the killer keeps the margin 4 - 1 = 3, not 4 - 0.
        lives = spawn_all() + [life(1, 1, "end", 40), life(1, 2, "end", 10),
                               life(1, 3, "end", 11), life(1, 4, "end", 50)]
        result = build([frag(1, 1, 4, 50)], lives)
        self.assertEqual(result["margin_histogram"], {"3": 1})

    def test_absent_and_unspawned_players_are_not_alive(self):
        # Player 7 never appears in half 1; player 6 first spawns at 80.
        lives = spawn_all(pids=range(1, 6)) + [
            life(1, 6, "start", 80), life(1, 2, "end", 10), life(1, 4, "end", 50)]
        result = build([frag(1, 1, 4, 50)], lives)
        # Own side 1 + 3 = 2, enemies 4 and 5 = 2: margin 0, and nothing censored.
        self.assertEqual(result["coverage"]["censored"], 0)
        self.assertEqual(result["margin_histogram"], {"0": 1})

    def test_a_player_who_must_have_been_alive_censors_the_kill(self):
        # Player 7's first boundary in the half is a death after the kill.
        lives = spawn_all(pids=range(1, 7)) + [life(1, 7, "end", 90),
                                                life(1, 4, "end", 50)]
        result = build([frag(1, 1, 4, 50)], lives)
        self.assertEqual(result["coverage"], {"kills": 1, "evaluated": 0,
                                              "censored": 1, "unordered": 0})
        self.assertTrue(row(result, 1, 1)["lower_bound"])
        self.assertIn("censored-kills", result["flags"])

    def test_an_unplaceable_frag_is_left_out_and_marks_a_lower_bound(self):
        # The unclocked frag sits nowhere near a death it could be recovered from.
        lives = spawn_all() + [life(1, 5, "end", 20)]
        result = build([frag(1, 1, 5, 20), frag(1, 1, 4, 50, clocked=False)], lives)
        self.assertEqual(result["coverage"]["unordered"], 1)
        self.assertEqual(row(result, 1, 1)["outnumbered_kills"], 0)
        self.assertTrue(row(result, 1, 1)["lower_bound"])

    def test_sides_come_from_the_ledger_per_half(self):
        # Half 2 swaps sides; team membership still decides who is a teammate.
        lives = spawn_all(half=2) + [life(2, 5, "end", 10), life(2, 6, "end", 11),
                                     life(2, 7, "end", 12), life(2, 1, "end", 50)]
        result = build([frag(2, 4, 1, 50)], lives)
        r = row(result, 2, 4)
        self.assertEqual((r["side"], r["outnumbered_kills"]), ("Allies", 1))
        player = next(p for p in result["players"] if p["player_id"] == 4)
        self.assertEqual(player["by_side"], {"Allies": 1, "Axis": None})

    def test_match_rows_add_halves(self):
        lives = (spawn_all() + [life(1, 2, "end", 10), life(1, 3, "end", 11),
                                life(1, 4, "end", 50)]
                 + spawn_all(half=2) + [life(2, 2, "end", 10), life(2, 3, "end", 11),
                                        life(2, 5, "end", 50)])
        result = build([frag(1, 1, 4, 50), frag(2, 1, 5, 50)], lives)
        player = next(p for p in result["players"] if p["player_id"] == 1)
        self.assertEqual((player["kills"], player["outnumbered_kills"]), (2, 2))
        self.assertEqual(player["by_side"], {"Allies": 1, "Axis": 1})

    def test_missing_sources_read_unavailable_not_zero(self):
        for result in (build(None, spawn_all()), build([], None),
                       build([], spawn_all(), source_available=False), build([], [])):
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["players"], [])

    def test_frags_with_no_clock_at_all_read_unavailable(self):
        result = build([frag(1, 1, 4, 50, clocked=False)], spawn_all())
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["flags"], ["no-frag-clock"])


if __name__ == "__main__":
    unittest.main()
