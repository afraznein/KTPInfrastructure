"""Brinks: when a side is one flag short, who put it there, and what followed."""
from __future__ import annotations

import unittest

from scripts.brinks import BrinkConfig, build_brinks


def state(t, flag, owner, half=1, initial=False):
    return {"half": half, "flag_name": flag, "owner_team": owner,
            "game_time": t, "is_initial": initial}


def credit(t, pid, flag, half=1):
    return {"half": half, "player_id": pid, "flag_name": flag, "game_time": t}


FIVE = ["a", "b", "c", "d", "e"]


def opening(owner=2):
    """All five flags start with `owner`, so side 1 has to take them."""
    return [state(0.0, f, owner, initial=True) for f in FIVE]


class Brinks(unittest.TestCase):
    def test_four_of_five_is_a_brink(self):
        evs = opening() + [state(10.0 + i, f, 1) for i, f in enumerate(FIVE[:4])]
        out = build_brinks(evs)
        self.assertEqual(len(out["rows"]), 1)
        row = out["rows"][0]
        self.assertEqual((row["side"], row["flags_held"], row["flag_count"]), (1, 4, 5))
        self.assertEqual(row["flag"], "d")          # the flag that got them there

    def test_three_of_five_is_not(self):
        evs = opening() + [state(10.0 + i, f, 1) for i, f in enumerate(FIVE[:3])]
        self.assertEqual(build_brinks(evs)["rows"], [])

    def test_the_capper_who_reached_it_is_credited(self):
        evs = opening() + [state(10.0 + i, f, 1) for i, f in enumerate(FIVE[:4])]
        out = build_brinks(evs, [credit(13.1, 77, "d")])
        self.assertEqual(out["rows"][0]["credited"], [77])

    def test_a_credit_outside_the_tolerance_is_not_the_capper(self):
        evs = opening() + [state(10.0 + i, f, 1) for i, f in enumerate(FIVE[:4])]
        out = build_brinks(evs, [credit(40.0, 77, "d")],
                           BrinkConfig(credit_tolerance=3.0))
        self.assertEqual(out["rows"][0]["credited"], [])

    def test_conversion_inside_the_window_is_recorded(self):
        evs = opening() + [state(10.0 + i, f, 1) for i, f in enumerate(FIVE[:4])]
        evs.append(state(20.0, "e", 1))
        row = build_brinks(evs)["rows"][0]
        self.assertTrue(row["converted"])
        self.assertEqual(row["flags_at_window_end"], 5)

    def test_a_cap_out_after_the_window_is_not_a_conversion(self):
        evs = opening() + [state(10.0 + i, f, 1) for i, f in enumerate(FIVE[:4])]
        evs.append(state(500.0, "e", 1))
        row = build_brinks(evs, config=BrinkConfig(window_seconds=90.0))["rows"][0]
        self.assertFalse(row["converted"])

    def test_losing_ground_is_recorded_but_not_priced(self):
        evs = opening() + [state(10.0 + i, f, 1) for i, f in enumerate(FIVE[:4])]
        evs += [state(20.0, f, 2) for f in ("a", "b")]      # back to 2 of 5
        row = build_brinks(evs)["rows"][0]
        self.assertEqual(row["flags_at_window_end"], 2)
        self.assertTrue(row["collapsed"])
        self.assertNotIn("debit", row)
        self.assertNotIn("penalty", row)

    def test_re_reaching_the_brink_is_a_second_row(self):
        evs = opening() + [state(10.0 + i, f, 1) for i, f in enumerate(FIVE[:4])]
        evs.append(state(20.0, "a", 2))        # drop to 3
        evs.append(state(30.0, "a", 1))        # back to 4
        self.assertEqual(len(build_brinks(evs)["rows"]), 2)

    def test_staying_on_the_brink_is_one_row(self):
        # Flags churn below the brink without the count changing: still one.
        evs = opening() + [state(10.0 + i, f, 1) for i, f in enumerate(FIVE[:4])]
        evs.append(state(20.0, "d", 1))       # a no-op re-transition
        self.assertEqual(len(build_brinks(evs)["rows"]), 1)

    def test_both_sides_can_reach_it(self):
        evs = opening(owner=1) + [state(10.0 + i, f, 2) for i, f in enumerate(FIVE[:4])]
        out = build_brinks(evs)
        self.assertEqual([r["side"] for r in out["rows"]], [2])

    def test_a_two_flag_map_has_no_brink(self):
        # One flag short of a cap-out on two flags IS the cap; not a threat.
        evs = [state(0.0, f, 2, initial=True) for f in ("a", "b")]
        evs.append(state(10.0, "a", 1))
        self.assertEqual(build_brinks(evs)["rows"], [])

    def test_a_missing_feed_is_unavailable(self):
        self.assertEqual(build_brinks(None)["status"], "unavailable")
        self.assertEqual(
            build_brinks(opening(), source_status="unavailable")["status"],
            "unavailable")


class PricesNothing(unittest.TestCase):
    """Upside measured, debit deliberately absent (drew asked for one; team-level
    data says a brink makes collapse LESS likely, so there is nothing to debit)."""

    def test_the_block_carries_its_measurement(self):
        out = build_brinks(opening())
        self.assertEqual(out["measured"]["brink"]["converts"], 0.261)
        self.assertEqual(out["measured"]["fair"]["converts"], 0.134)
        self.assertGreater(out["measured"]["convert_lift_vs_fair"], 1.5)

    def test_collapse_is_measured_as_no_worse_than_not_pushing(self):
        m = build_brinks(opening())["measured"]
        self.assertLess(m["brink"]["collapses"], m["fair"]["collapses"])
        self.assertLessEqual(m["collapse_lift_vs_fair"], 1.0)

    def test_no_rating_effect(self):
        out = build_brinks(opening())
        self.assertFalse(out["rating_effect"])
        self.assertEqual(out["visibility"], "private_shadow_only")


if __name__ == "__main__":
    unittest.main()
