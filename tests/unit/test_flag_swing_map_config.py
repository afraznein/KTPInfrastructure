"""Per-map flag-swing coefficients: selection, precedence and the shrinkage."""
from __future__ import annotations

import unittest
from unittest import mock

from scripts import flag_swing
from scripts.flag_swing import FlagSwingConfig
from scripts.fit_flag_swing import fit_by_map


class ForMap(unittest.TestCase):
    def test_an_empty_table_leaves_the_league_prior_untouched(self):
        # An unfitted league, or a calibration file that failed to load, must
        # behave exactly as before per-map coefficients existed.
        with mock.patch.dict(flag_swing.MAP_COEFFICIENTS, {}, clear=True):
            cfg = FlagSwingConfig().for_map("dod_thunder2")
        self.assertEqual((cfg.flag_coefficient, cfg.alive_coefficient), (2.0, 1.0))
        self.assertEqual(cfg.calibration, "uncalibrated_baseline")

    def test_the_shipped_table_loads_and_is_usable(self):
        # The committed artifact is the thing production reads, so a malformed
        # or empty one should fail here rather than silently flatten every map
        # back to the league prior in a report nobody re-checks.
        self.assertTrue(flag_swing.MAP_COEFFICIENTS,
                        "config/map_coefficients.json did not load")
        for name, (flag, alive) in flag_swing.MAP_COEFFICIENTS.items():
            self.assertTrue(name.startswith("dod_"), name)
            self.assertGreater(flag, 0.0, name)
            self.assertGreater(alive, 0.0, name)
            FlagSwingConfig(flag_coefficient=flag,
                            alive_coefficient=alive).validate()

    def test_a_fitted_map_gets_its_own_coefficients(self):
        with mock.patch.dict(flag_swing.MAP_COEFFICIENTS,
                             {"dod_thunder2": (4.5, 0.96)}, clear=True):
            cfg = FlagSwingConfig().for_map("dod_thunder2")
        self.assertEqual((cfg.flag_coefficient, cfg.alive_coefficient), (4.5, 0.96))
        self.assertIn("dod_thunder2", cfg.calibration)

    def test_an_unfitted_map_falls_back_to_the_league_prior(self):
        with mock.patch.dict(flag_swing.MAP_COEFFICIENTS,
                             {"dod_thunder2": (4.5, 0.96)}, clear=True):
            cfg = FlagSwingConfig().for_map("dod_some_new_map")
        self.assertEqual((cfg.flag_coefficient, cfg.alive_coefficient), (2.0, 1.0))

    def test_no_map_name_falls_back(self):
        with mock.patch.dict(flag_swing.MAP_COEFFICIENTS,
                             {"dod_thunder2": (4.5, 0.96)}, clear=True):
            self.assertEqual(FlagSwingConfig().for_map(None).flag_coefficient, 2.0)

    def test_an_explicit_config_overrides_the_table(self):
        # The fit driver scores one vector across every map; it must not be
        # silently swapped for the map's own.
        with mock.patch.dict(flag_swing.MAP_COEFFICIENTS,
                             {"dod_thunder2": (4.5, 0.96)}, clear=True):
            cfg = FlagSwingConfig(flag_coefficient=1.25).for_map("dod_thunder2")
        self.assertEqual(cfg.flag_coefficient, 1.25)


def half(flag_term, label, n=40):
    """One half's worth of samples at a fixed state."""
    return [(flag_term, 0.0, label)] * n


class Shrinkage(unittest.TestCase):
    """A map earns its distance from the league; it is not handed to it."""

    def setUp(self):
        # 'steady' agrees with the league; 'wild' says flags decide everything.
        self.data = {
            "steady": [half(0.2, 1), half(-0.2, 0)] * 5,
            "wild": [half(0.05, 1), half(-0.05, 0)] * 5,
        }

    def test_weight_rises_with_halves_not_samples(self):
        few = {"m": [half(0.2, 1), half(-0.2, 0)]}
        many = {"m": [half(0.2, 1, n=4000), half(-0.2, 0, n=4000)]}
        _, few_fit = fit_by_map(few, prior_halves=20.0, iterations=50)
        _, many_fit = fit_by_map(many, prior_halves=20.0, iterations=50)
        self.assertEqual(few_fit[0].weight, many_fit[0].weight)
        self.assertAlmostEqual(few_fit[0].weight, 2 / 22.0, places=4)

    def test_a_thin_map_stays_near_the_league_fit(self):
        pooled, fits = fit_by_map(self.data, prior_halves=20.0, iterations=300)
        for f in fits:
            own_gap = abs(f.own_flag_coefficient - pooled.flag_coefficient)
            shrunk_gap = abs(f.flag_coefficient - pooled.flag_coefficient)
            self.assertLessEqual(shrunk_gap, own_gap + 1e-9)

    def test_zero_prior_is_an_independent_fit(self):
        _, fits = fit_by_map(self.data, prior_halves=0.0, iterations=300)
        for f in fits:
            self.assertEqual(f.weight, 1.0)
            self.assertAlmostEqual(f.flag_coefficient, f.own_flag_coefficient, places=9)

    def test_empty_input_is_refused_rather_than_fitted(self):
        with self.assertRaises(ValueError):
            fit_by_map({})


if __name__ == "__main__":
    unittest.main()
