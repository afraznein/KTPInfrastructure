"""S2b: the KTPR error bar from half-to-half reliability.

The arithmetic is checked on hand-built pairs, and `compute_reliability` is run end to
end on synthetic half rows so the pairing and the accounting are exercised, not assumed.
"""
import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "docs" / "ktpr_mcp"))

import ktpr_engine as E  # noqa: E402


def half(name, match_id, kills, deaths=5.0):
    return E.Player(name=name, matches=1.0, kd_ratio=kills / deaths, kills_half=kills,
                    deaths_half=deaths, flags_half=0.0, role="Rifle", team="T",
                    match_id=match_id, side="axis")


def season(name, kills, matches=6.0):
    return E.Player(name=name, matches=matches, kd_ratio=kills / 5.0, kills_half=kills,
                    deaths_half=5.0, flags_half=0.0, role="Rifle", team="T")


class PairedArithmetic(unittest.TestCase):
    def test_identical_halves_have_no_noise(self):
        pairs = [(v, v) for v in (0.8, 0.9, 1.0, 1.1, 1.2, 0.7, 1.3, 0.95, 1.05, 1.15)]
        out = E.paired_half_reliability(pairs, [0.8, 1.0, 1.2])
        self.assertEqual(out["r_halves"], 1.0)
        self.assertEqual(out["r_full"], 1.0)
        self.assertEqual(out["sem"], 0.0)

    def test_spearman_brown_and_sem(self):
        rng = random.Random(7)
        pairs = []
        for _ in range(400):
            true = rng.gauss(1.0, 0.2)
            pairs.append((true + rng.gauss(0, 0.2), true + rng.gauss(0, 0.2)))
        season_vals = [0.6, 0.8, 1.0, 1.2, 1.4]
        out = E.paired_half_reliability(pairs, season_vals)
        r = out["r_halves"]
        self.assertGreater(r, 0.35)
        self.assertLess(r, 0.65)
        self.assertAlmostEqual(out["r_full"], 2 * r / (1 + r), places=3)
        expected = E._stdev(season_vals) * math.sqrt(1 - 2 * r / (1 + r))
        self.assertAlmostEqual(out["sem"], expected, places=3)

    def test_order_within_a_pair_does_not_matter(self):
        rng = random.Random(3)
        pairs = [(rng.random(), rng.random()) for _ in range(50)]
        flipped = [(b, a) if i % 2 else (a, b) for i, (a, b) in enumerate(pairs)]
        a = E.paired_half_reliability(pairs, [0.5, 1.0])
        b = E.paired_half_reliability(flipped, [0.5, 1.0])
        self.assertEqual(a["r_halves"], b["r_halves"])

    def test_too_few_pairs_publishes_nothing(self):
        out = E.paired_half_reliability([(1.0, 1.1)] * 3, [0.9, 1.1])
        self.assertIsNone(out["r_halves"])
        self.assertIsNone(out["sem"])
        self.assertIn("fewer than", out["reason"])

    def test_non_positive_reliability_publishes_no_sem(self):
        pairs = [(1.0, 0.0), (0.0, 1.0)] * 10
        out = E.paired_half_reliability(pairs, [0.5, 1.0])
        self.assertLessEqual(out["r_halves"], 0)
        self.assertIsNone(out["sem"])

    def test_rank_equivalent_counts_neighbours_within_one_sem(self):
        pairs = [(v, v + 0.1) for v in (0.5, 0.7, 0.9, 1.1, 1.3, 1.5, 0.6, 0.8, 1.0, 1.2)]
        out = E.paired_half_reliability(pairs, [1.0, 1.01, 1.02, 2.0, 3.0])
        self.assertIsNotNone(out["sem"])
        sem = out["sem"]
        vals = [1.0, 1.01, 1.02, 2.0, 3.0]
        within = sorted((sum(1 for w in vals if abs(w - v) <= sem) - 1) / 2 for v in vals)
        self.assertEqual(out["rank_equivalent"], within[len(within) // 2])


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.p = E.load_params("new")
        self.season = [season(n, k) for n, k in
                       (("a", 6.0), ("b", 8.0), ("c", 10.0), ("d", 12.0), ("e", 14.0))]

    def test_pairs_and_accounting(self):
        rows = []
        for i in range(12):
            m = f"m{i}"
            for name, k in (("a", 6.0), ("b", 8.0), ("c", 10.0), ("d", 12.0)):
                rows.append(half(name, m, k))
                rows.append(half(name, m, k + (1.0 if i % 2 else -1.0)))
        rows.append(half("e", "m0", 14.0))                   # one half only
        rows.extend(half("e", "m1", 14.0) for _ in range(3))  # overtime
        out = E.compute_reliability(self.season, rows, self.p)
        self.assertEqual(out["pairs"], 48)
        self.assertEqual(out["skipped_one_half"], 1)
        self.assertEqual(out["skipped_over_two_halves"], 1)
        self.assertFalse(out["side_adjusted"])
        self.assertGreater(out["r_halves"], 0.5)
        self.assertLess(out["r_halves"], 1.0)
        self.assertGreater(out["sem"], 0.0)

    def test_needs_the_team_formula(self):
        with self.assertRaises(ValueError):
            E.compute_reliability(self.season, [], E.load_params("old"))


if __name__ == "__main__":
    unittest.main()
