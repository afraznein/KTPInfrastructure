"""The retained-row floor under the weekly map-coefficient refit."""
from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from scripts import flag_swing
from scripts import map_coefficients_retained as R
from scripts.flag_swing import FlagSwingConfig, build_flag_swing_shadow

REPO = Path(__file__).resolve().parents[2]
COMMIT = "c39fa0489173053b61aa84f1e8985a6b4aeccb13"


def tables(live=None, retained=None, carry=None):
    return (mock.patch.dict(flag_swing.MAP_COEFFICIENTS, live or {}, clear=True),
            mock.patch.dict(flag_swing.RETAINED_MAP_COEFFICIENTS, retained or {},
                            clear=True),
            mock.patch.dict(flag_swing.MAP_COEFFICIENT_CARRY_FORWARD, carry or {},
                            clear=True))


def resolve(name, config=None, **kw):
    a, b, c = tables(**kw)
    with a, b, c:
        cfg = (config or FlagSwingConfig()).for_map(name)
    return (cfg.flag_coefficient, cfg.alive_coefficient), cfg.calibration


class Precedence(unittest.TestCase):
    def test_a_retained_row_fills_a_map_the_live_table_lacks(self):
        coeffs, cal = resolve("dod_gone", live={"dod_here": (1.5, 0.9)},
                              retained={"dod_gone": (0.94, 0.68, COMMIT)})
        self.assertEqual(coeffs, (0.94, 0.68))
        self.assertEqual(cal, f"retained_fit:dod_gone@{COMMIT[:12]}")

    def test_a_live_row_wins_over_a_retained_one(self):
        # Once a refit fits the map again its retained row must go inert by itself.
        coeffs, cal = resolve("dod_back", live={"dod_back": (1.7, 0.8)},
                              retained={"dod_back": (0.94, 0.68, COMMIT)})
        self.assertEqual((coeffs, cal), ((1.7, 0.8), "fitted_per_map:dod_back"))

    def test_a_carry_forward_wins_over_a_retained_row(self):
        coeffs, cal = resolve("dod_new", live={"dod_old": (1.47, 1.1)},
                              retained={"dod_new": (0.94, 0.68, COMMIT)},
                              carry={"dod_new": "dod_old"})
        self.assertEqual((coeffs, cal), ((1.47, 1.1), "carried_forward_from:dod_old"))

    def test_a_retained_row_fills_in_when_the_carry_forward_source_is_gone(self):
        coeffs, cal = resolve("dod_new", retained={"dod_new": (0.94, 0.68, COMMIT)},
                              carry={"dod_new": "dod_absent"})
        self.assertEqual(coeffs, (0.94, 0.68))
        self.assertTrue(cal.startswith("retained_fit:"))

    def test_an_explicit_config_overrides_a_retained_row(self):
        coeffs, _ = resolve("dod_gone", config=FlagSwingConfig(flag_coefficient=1.25),
                            retained={"dod_gone": (0.94, 0.68, COMMIT)})
        self.assertEqual(coeffs[0], 1.25)

    def test_a_map_in_neither_table_still_prices_on_the_prior(self):
        coeffs, cal = resolve("dod_never", retained={"dod_gone": (0.94, 0.68, COMMIT)})
        self.assertEqual((coeffs, cal), ((2.0, 1.0), "uncalibrated_baseline"))


class EnvelopeFlag(unittest.TestCase):
    def envelope(self, name, **kw):
        a, b, c = tables(**kw)
        with a, b, c:
            return build_flag_swing_shadow(None, None, None, None, None,
                                           map_name=name, source_available=False)

    def test_a_retained_row_is_flagged_in_the_output(self):
        env = self.envelope("dod_gone", retained={"dod_gone": (0.94, 0.68, COMMIT)})
        self.assertIs(env["coefficients_retained"], True)
        self.assertTrue(env["calibration"].startswith("retained_fit:dod_gone@"))
        self.assertEqual(env["parameters"]["flag_coefficient"], 0.94)

    def test_a_fresh_fit_and_the_prior_are_not_flagged(self):
        fresh = self.envelope("dod_here", live={"dod_here": (1.5, 0.9)})
        prior = self.envelope("dod_never")
        self.assertIs(fresh["coefficients_retained"], False)
        self.assertIs(prior["coefficients_retained"], False)


class ShippedFloor(unittest.TestCase):
    """Against the committed artifacts, which is what production reads."""

    def test_every_retained_row_loads_and_is_usable(self):
        self.assertTrue(flag_swing.RETAINED_MAP_COEFFICIENTS,
                        "config/map_coefficients_retained.json did not load")
        for name, (flag, alive, commit) in flag_swing.RETAINED_MAP_COEFFICIENTS.items():
            self.assertTrue(name.startswith("dod_"), name)
            self.assertRegex(commit, r"^[0-9a-f]{40}$", name)
            FlagSwingConfig(flag_coefficient=flag, alive_coefficient=alive).validate()

    def test_a_dropped_map_no_longer_falls_to_the_prior(self):
        # dod_halle left the live table at the 2026-11-09 refit and is still listed
        # competitive; without the floor it would price on (2.0, 1.0).
        self.assertNotIn("dod_halle", flag_swing.MAP_COEFFICIENTS)
        cfg = FlagSwingConfig().for_map("dod_halle")
        self.assertNotEqual((cfg.flag_coefficient, cfg.alive_coefficient), (2.0, 1.0))
        self.assertTrue(cfg.calibration.startswith("retained_fit:dod_halle@"))

    def test_without_the_floor_the_same_map_is_back_on_the_prior(self):
        # The mutation: emptying the retained table is exactly the pre-floor state.
        with mock.patch.dict(flag_swing.RETAINED_MAP_COEFFICIENTS, {}, clear=True):
            cfg = FlagSwingConfig().for_map("dod_halle")
        self.assertEqual((cfg.flag_coefficient, cfg.alive_coefficient), (2.0, 1.0))

    def test_every_retained_row_matches_the_commit_it_names(self):
        shallow = subprocess.run(["git", "-C", str(REPO), "rev-parse",
                                  "--is-shallow-repository"],
                                 capture_output=True, text=True).stdout.strip()
        if shallow != "false":
            if os.environ.get("GITHUB_ACTIONS"):
                self.fail("CI checkout lost the history this provenance check reads")
            self.skipTest("no full git history here")
        retained = json.loads((REPO / R.RETAINED).read_text(encoding="utf-8"))["maps"]
        for name, row in retained.items():
            then = json.loads(subprocess.run(
                ["git", "-C", str(REPO), "show", f"{row['retained_from_commit']}:{R.LIVE}"],
                check=True, capture_output=True, text=True, encoding="utf-8").stdout)
            src = then["maps"][name]
            self.assertEqual((row["flag_coefficient"], row["alive_coefficient"]),
                             (src["flag_coefficient"], src["alive_coefficient"]), name)
            self.assertEqual(row["retained_from_fitted_at"], then.get("fitted_at"), name)

    def test_no_map_ever_fitted_is_left_on_the_prior(self):
        if subprocess.run(["git", "-C", str(REPO), "rev-parse",
                           "--is-shallow-repository"],
                          capture_output=True, text=True).stdout.strip() != "false":
            if os.environ.get("GITHUB_ACTIONS"):
                self.fail("CI checkout lost the history this check reads")
            self.skipTest("no full git history here")
        self.assertEqual(R.main(["--check", "--repo", str(REPO)]), 0)


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                    "-c", "commit.gpgsign=false", *args], check=True,
                   capture_output=True, text=True)


class Derivation(unittest.TestCase):
    """The refit drops a map; --check must notice and --write must carry its last row."""

    def commit_live(self, repo, maps, fitted_at):
        (repo / "config").mkdir(exist_ok=True)
        (repo / R.LIVE).write_text(json.dumps(
            {"fitted_at": fitted_at, "corpus_selected": "officials_only",
             "maps": maps}), encoding="utf-8")
        git(repo, "add", R.LIVE)
        git(repo, "commit", "-q", "-m", fitted_at)
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              check=True, capture_output=True, text=True).stdout.strip()

    def test_a_dropped_map_is_a_gap_until_written(self):
        row = lambda f, a: {"flag_coefficient": f, "alive_coefficient": a,
                            "official_halves": 4, "training_halves": 4,
                            "shrinkage_weight": 0.17, "log_loss": 0.6}
        with TemporaryDirectory() as d:
            repo = Path(d)
            git(repo, "init", "-q")
            self.commit_live(repo, {"dod_a": row(1.0, 0.9), "dod_b": row(1.3, 0.8)}, "w1")
            last_b = self.commit_live(repo, {"dod_a": row(1.1, 0.9),
                                             "dod_b": row(1.2, 0.7)}, "w2")
            self.commit_live(repo, {"dod_a": row(1.2, 0.9)}, "w3")

            self.assertEqual(R.main(["--check", "--repo", str(repo)]), 1)
            self.assertEqual(R.main(["--write", "--repo", str(repo)]), 0)
            written = json.loads((repo / R.RETAINED).read_text(encoding="utf-8"))["maps"]
            self.assertEqual(set(written), {"dod_b"})
            self.assertEqual(written["dod_b"]["retained_from_commit"], last_b)
            self.assertEqual((written["dod_b"]["flag_coefficient"],
                              written["dod_b"]["alive_coefficient"]), (1.2, 0.7))
            self.assertEqual(written["dod_b"]["retained_from_fitted_at"], "w2")
            self.assertNotIn("log_loss", written["dod_b"])
            self.assertEqual(R.main(["--check", "--repo", str(repo)]), 0)

    def test_an_existing_retained_row_is_never_rewritten(self):
        live = {"dod_a": 1}
        retained = {"dod_b": {"retained_from_commit": "old"}}
        fitted = {"dod_a": {}, "dod_b": {"retained_from_commit": "new"},
                  "dod_c": {"retained_from_commit": "x"}}
        self.assertEqual(set(R.gaps(live, retained, fitted)), {"dod_c"})

    def test_a_shallow_clone_cannot_pass(self):
        with mock.patch.object(R, "_git", return_value="true\n"):
            self.assertEqual(R.main(["--check", "--repo", str(REPO)]), 2)


if __name__ == "__main__":
    unittest.main()
