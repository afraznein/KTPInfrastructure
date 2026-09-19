"""Momentum credit: the deposit/payout ledger and the event extraction it runs on.

Pure logic over synthetic events; no TSVs, no network.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "mmr"))

import momentum as M  # noqa: E402

CURVES = {"cap": (1.8, 0.1), "capout": (2.9, 0.045)}


def frag(t, killer, victim, match="M", half=1):
    return {"match_id": match, "half": half, "game_time": str(t), "killerId": killer,
            "victimId": victim, "weapon": "x"}


def flag(t, index, owner, name=None, is_initial=0, match="M", half=1, event_time=None):
    return {"match_id": match, "half": half, "flag_index": index, "flag_name": name or f"F{index}",
            "owner_team": owner, "is_initial": is_initial, "game_time": str(t),
            "event_time": event_time or f"2026-01-01 00:{int(t)//60:02d}:{int(t)%60:02d}"}


SIDE = {("M", 1): {1: 1, 2: 1, 3: 1, 11: 2, 12: 2, 13: 2, 14: 2}}


class Multikills(unittest.TestCase):
    def test_three_kills_inside_the_gap_are_one_cluster_stamped_at_the_last_kill(self):
        mk = M.multikills([frag(10, 1, 11), frag(15, 1, 12), frag(19, 1, 13)], SIDE)
        self.assertEqual([(m["t"], m["n"], m["team"], m["player"]) for m in mk], [(19.0, 3, 1, 1)])

    def test_a_gap_over_the_limit_splits_the_run(self):
        mk = M.multikills([frag(10, 1, 11), frag(15, 1, 12), frag(40, 1, 13), frag(41, 1, 14)], SIDE)
        self.assertEqual(mk, [])

    def test_team_kills_do_not_count(self):
        mk = M.multikills([frag(10, 1, 2), frag(11, 1, 11), frag(12, 1, 12)], SIDE)
        self.assertEqual(mk, [])


class Objectives(unittest.TestCase):
    """Five flags. Reset sets all five; the home-flag seed pair follows; then play."""

    def half(self):
        rows = [flag(0, i, 0, is_initial=1) for i in range(5)]           # round start
        rows += [flag(10, 0, 1), flag(10, 4, 2)]                           # home seed
        rows += [flag(20, 1, 1), flag(30, 3, 2), flag(60, 2, 1)]           # streets, mid
        rows += [flag(100, 3, 1), flag(120, 4, 1)]                         # allies take the rest
        rows += [flag(123, i, 0) for i in range(5)]                        # post-capout reset
        return rows

    def test_reset_and_seed_are_not_objectives(self):
        obs = M.objectives(self.half())
        self.assertTrue(all(o["t"] >= 20 for o in obs))

    def test_caps_and_the_capout_instant(self):
        obs = M.objectives(self.half())
        self.assertEqual([(o["t"], o["kind"], o["team"]) for o in obs],
                         [(20.0, "cap", 1), (30.0, "cap", 2), (60.0, "cap", 1),
                          (100.0, "cap", 1), (120.0, "cap", 1), (120.0, "capout", 1)])

    def test_a_cap_records_what_it_enabled(self):
        """The 60s mid cap leaves allies holding 3 flags until 100s."""
        mid = next(o for o in M.objectives(self.half()) if o["t"] == 60.0)
        self.assertEqual((mid["held"], mid["dt"]), (3, 40.0))

    def test_the_capper_is_joined_by_flag_name_and_event_time(self):
        caps = [{"match_id": "M", "half": 1, "flag_name": "F1", "event_time": "2026-01-01 00:00:19", "player_id": 7}]
        obs = M.objectives(self.half(), caps)
        self.assertEqual(obs[0]["players"], [7])
        self.assertEqual(obs[1]["players"], [])


class Lift(unittest.TestCase):
    def test_attributable_fraction_is_zero_at_baseline_and_grows_with_lift(self):
        self.assertEqual(M.attributable(1e9, 1.8, 0.1), 0.0)
        self.assertAlmostEqual(M.attributable(0.0, 1.0, 0.1), 0.5)   # lift 2 -> half attributable

    def test_fit_recovers_a_planted_curve(self):
        rows = [{"bin": (lo, hi), "lift": 1.0 + 2.0 * pow(2.718281828, -0.05 * (lo + hi) / 2)}
                for lo, hi in M.LAG_BINS]
        A, lam = M.fit_lift(rows)
        self.assertAlmostEqual(A, 2.0, places=5)
        self.assertAlmostEqual(lam, 0.05, places=5)

    def test_matched_baseline_removes_a_strong_team(self):
        """Team 1 caps constantly; a multikill by team 1 shows NO lift because
        its own rate is the baseline."""
        objs = [{"match": "M", "half": 1, "t": float(t), "kind": "cap", "team": 1} for t in range(0, 600, 10)]
        mk = [{"match": "M", "half": 1, "t": 100.0, "kind": "multikill", "team": 1, "player": 1, "n": 3}]
        rows = M.lag_lift(mk, objs, {("M", 1): (0.0, 600.0)}, bins=((0, 15),))
        self.assertAlmostEqual(rows[0]["lift"], 1.0, places=6)


class Scoring(unittest.TestCase):
    def test_fit_recovers_planted_coefficients(self):
        truth = {"cap": 2.5, "hold3": 0.05, "hold4": 0.4, "capout": 45.0}
        samples = []
        for i in range(12):
            f = {"cap": 3 + i % 5, "hold3": 20.0 * (i % 4), "hold4": 15.0 * (i % 3), "capout": i % 2}
            samples.append((f, sum(truth[k] * f[k] for k in truth)))
        coef, r2 = M.fit_scoring(samples)
        for k in truth:
            self.assertAlmostEqual(coef[k], truth[k], places=6)
        self.assertAlmostEqual(r2, 1.0, places=9)

    def test_value_prices_the_hold_a_cap_enabled(self):
        scoring = {"cap": 2.0, "hold3": 0.0, "hold4": 0.5, "capout": 40.0}
        self.assertEqual(M.value({"kind": "cap", "held": 4, "dt": 30.0}, scoring), 17.0)
        self.assertEqual(M.value({"kind": "cap", "held": 2, "dt": 30.0}, scoring), 2.0)
        self.assertEqual(M.value({"kind": "capout"}, scoring), 40.0)

    def test_credit_uses_the_map_fit_when_there_is_one(self):
        scoring = {"dod_x": {"cap": 2.0, "hold3": 0.0, "hold4": 0.0, "capout": 40.0}}
        events = [{"match": "M", "half": 1, "t": 0.0, "kind": "cap", "team": 1, "players": [2],
                   "held": 1, "dt": 10.0, "map": "dod_x"}]
        self.assertAlmostEqual(M.credit(events, CURVES, 0.3, scoring=scoring)[("M", 1)][2]["total"], 2.0)
        events[0]["map"] = "dod_unfitted"
        self.assertAlmostEqual(M.credit(events, CURVES, 0.3, scoring=scoring)[("M", 1)][2]["total"], 1.0)


class LedgerMechanics(unittest.TestCase):
    def test_total_credit_equals_total_objective_value(self):
        """Payout redistributes; it never creates or destroys value."""
        events = [
            {"match": "M", "half": 1, "t": 0.0, "kind": "multikill", "team": 1, "player": 1, "n": 4},
            {"match": "M", "half": 1, "t": 20.0, "kind": "cap", "team": 1, "players": [2]},
            {"match": "M", "half": 1, "t": 50.0, "kind": "cap", "team": 1, "players": [3]},
            {"match": "M", "half": 1, "t": 50.0, "kind": "capout", "team": 1, "players": [3]},
        ]
        got = M.credit(events, CURVES, rho=0.3)[("M", 1)]
        self.assertAlmostEqual(sum(v["total"] for v in got.values()), 3.0)

    def test_the_4k_is_paid_by_the_cap_it_enabled_and_less_the_later_it_comes(self):
        def paid(lag):
            events = [
                {"match": "M", "half": 1, "t": 0.0, "kind": "multikill", "team": 1, "player": 1, "n": 4},
                {"match": "M", "half": 1, "t": lag, "kind": "cap", "team": 1, "players": [2]},
            ]
            return M.credit(events, CURVES, rho=0.3)[("M", 1)][1]["momentum"]
        self.assertGreater(paid(5.0), paid(20.0))
        self.assertGreater(paid(20.0), paid(60.0))
        self.assertGreater(paid(5.0), 0.0)

    def test_secondary_assist_flows_through_the_cap_to_the_4k(self):
        """4k -> cap -> capout: the capout pays the cap; the cap forwards rho
        of that to the 4k. With rho=0 the 4k gets only its direct cap share."""
        def chain(rho):
            events = [
                {"match": "M", "half": 1, "t": 0.0, "kind": "multikill", "team": 1, "player": 1, "n": 4},
                {"match": "M", "half": 1, "t": 30.0, "kind": "cap", "team": 1, "players": [2]},
                {"match": "M", "half": 1, "t": 60.0, "kind": "capout", "team": 1, "players": [3]},
            ]
            return M.credit(events, CURVES, rho=rho)[("M", 1)]
        self.assertGreater(chain(0.3)[1]["momentum"], chain(0.0)[1]["momentum"])
        self.assertLess(chain(0.3)[2]["total"], chain(0.0)[2]["total"])

    def test_an_enemy_cap_breaks_the_chain(self):
        events = [
            {"match": "M", "half": 1, "t": 0.0, "kind": "multikill", "team": 1, "player": 1, "n": 4},
            {"match": "M", "half": 1, "t": 5.0, "kind": "cap", "team": 2, "players": [11]},
            {"match": "M", "half": 1, "t": 10.0, "kind": "cap", "team": 1, "players": [2]},
        ]
        got = M.credit(events, CURVES, rho=0.3)[("M", 1)]
        self.assertEqual(got[1]["total"], 0.0)
        self.assertAlmostEqual(got[2]["total"], 1.0)

    def test_kills_alone_earn_nothing(self):
        events = [{"match": "M", "half": 1, "t": 0.0, "kind": "multikill", "team": 1, "player": 1, "n": 5}]
        self.assertEqual(M.credit(events, CURVES, rho=0.3)[("M", 1)][1]["total"], 0.0)

    def test_a_cap_with_no_known_capper_still_pays_momentum(self):
        events = [
            {"match": "M", "half": 1, "t": 0.0, "kind": "multikill", "team": 1, "player": 1, "n": 3},
            {"match": "M", "half": 1, "t": 5.0, "kind": "cap", "team": 1, "players": []},
        ]
        self.assertGreater(M.credit(events, CURVES, rho=0.3)[("M", 1)][1]["momentum"], 0.0)


if __name__ == "__main__":
    unittest.main()
