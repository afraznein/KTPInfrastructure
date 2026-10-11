"""The per-class swing correction: a sniper's component is not his absence.

`flag_swing` attributes flag control and a sniper holds mid without standing on
it, so the component read the role as absence. Both sniper classes measured
several standard errors below zero on swing (coordination
`hv_class_bias.py`, handed to this lane 2026-10-11) while the overall rating
gap was not significant. The deficit is attribution, not lower contribution:
within the 44 players who played sniper in some officials and another class in
others, sniping cost 0.568 sigma of swing while the team's win rate did not
move (+0.034, +0.70 SE).
"""
import unittest

from scripts.ktpr_v2 import build_ktpr_v2_shadow


def players(n=4):
    return [{"player_id": i, "player_name_at_match": f"p{i}", "team": 1 + i % 2,
             "damage_per_life": 100.0, "kd_ratio": 1.0} for i in range(n)]


def swing_rows(values):
    return [{"player_id": i, "attributed_swing": v}
            for i, v in enumerate(values)]


class ClassSwingCorrection(unittest.TestCase):
    def build(self, values, class_of=None, offsets=None):
        return build_ktpr_v2_shadow(
            players(len(values)), None, swing_rows(values),
            class_of=class_of, class_swing_offsets=offsets)

    def test_absent_offsets_change_nothing(self):
        plain = self.build([3.0, 1.0, -1.0, -3.0])
        self.assertFalse(plain["class_swing_adjustment"]["applied"])
        with_map = self.build([3.0, 1.0, -1.0, -3.0], class_of={0: 14})
        self.assertEqual(
            [p["rating"] for p in plain["players"]],
            [p["rating"] for p in with_map["players"]])

    def test_a_sniper_is_lifted_relative_to_a_rifleman(self):
        """Player 0 and 1 post identical swing; only 0 is a sniper."""
        base = self.build([2.0, 2.0, -2.0, -2.0])
        fixed = self.build([2.0, 2.0, -2.0, -2.0],
                           class_of={0: 14, 1: 1, 2: 1, 3: 1},
                           offsets={"14": -0.419})
        by_id = {p["player_id"]: p for p in fixed["players"]}
        flat = {p["player_id"]: p for p in base["players"]}
        self.assertEqual(flat[0]["components"]["swing"],
                         flat[1]["components"]["swing"])
        # The sniper now sits ABOVE the rifleman who matched him.
        self.assertGreater(by_id[0]["components"]["swing"],
                           by_id[1]["components"]["swing"])
        self.assertAlmostEqual(
            by_id[0]["components"]["swing"] - by_id[1]["components"]["swing"],
            0.419, places=3)

    def test_the_component_still_averages_zero(self):
        """`normalization: per_match_z_scores` is published metadata, and a
        consumer once applied a second z-transform after reading it
        (keep-the-prac #679/#691). The claim has to stay exactly true."""
        fixed = self.build([2.0, 1.0, -1.0, -2.0],
                           class_of={0: 14, 1: 14, 2: 1, 3: 6},
                           offsets={"14": -0.419, "6": 0.27})
        swing = [p["components"]["swing"] for p in fixed["players"]]
        self.assertAlmostEqual(sum(swing) / len(swing), 0.0, places=6)

    def test_same_class_ordering_is_untouched(self):
        fixed = self.build([3.0, 1.0, -1.0, -3.0],
                           class_of={i: 14 for i in range(4)},
                           offsets={"14": -0.419})
        order = [p["player_id"] for p in fixed["players"]]
        self.assertEqual(order, [0, 1, 2, 3])
        # Every player shares the offset, so re-centring cancels it entirely.
        plain = self.build([3.0, 1.0, -1.0, -3.0])
        self.assertEqual([p["rating"] for p in fixed["players"]],
                         [p["rating"] for p in plain["players"]])

    def test_what_was_applied_is_published(self):
        fixed = self.build([2.0, 1.0, -1.0, -2.0],
                           class_of={0: 14, 1: 1, 2: 1, 3: 1},
                           offsets={"14": -0.419, "5": -0.334})
        adj = fixed["class_swing_adjustment"]
        self.assertTrue(adj["applied"])
        # Only the offset actually used is reported, not the whole table.
        self.assertEqual(adj["offsets_used"], {"14": -0.419})

    def test_an_unknown_class_is_left_alone(self):
        fixed = self.build([2.0, 1.0, -1.0, -2.0],
                           class_of={0: 99}, offsets={"14": -0.419})
        self.assertFalse(fixed["class_swing_adjustment"]["applied"])

    def test_no_swing_component_is_not_an_error(self):
        out = build_ktpr_v2_shadow(players(3), None, None,
                                   class_of={0: 14},
                                   class_swing_offsets={"14": -0.419})
        self.assertFalse(out["class_swing_adjustment"]["applied"])
        self.assertNotIn("swing", out["components_used"])


if __name__ == "__main__":
    unittest.main()
