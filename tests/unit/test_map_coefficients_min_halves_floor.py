"""The refit keeps a measured row instead of dropping a map to the prior."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import scripts.fit_map_coefficients as F
from scripts import flag_swing
from scripts.fit_flag_swing import PRIOR_HALVES
from scripts.fit_map_coefficients import FLOOR_MARKER, apply_floor
from scripts.flag_swing import FlagSwingConfig, build_flag_swing_shadow

REPO = Path(__file__).resolve().parents[2]
N = PRIOR_HALVES


def row(flag, alive, halves):
    return {"flag_coefficient": flag, "alive_coefficient": alive,
            "official_halves": halves, "training_halves": halves,
            "shrinkage_weight": round(halves / (halves + N), 4)}


def table(maps, fitted_at):
    return {"fitted_at": fitted_at, "corpus_selected": "officials_only",
            "corpus_candidates": {}, "maps": maps}


PREVIOUS = table({"dod_solitude2": row(1.2309, 0.85, 8),
                  "dod_anzio": row(1.40, 1.35, 24),
                  "dod_thin": row(1.60, 0.90, 14),
                  "dod_growing": row(1.91, 1.10, 6)}, "2026-11-09T16:13:30Z")


class RefitFloor(unittest.TestCase):
    def floored(self, new_maps, previous=PREVIOUS, n=N):
        return apply_floor(table(new_maps, "2026-11-16T14:00:00Z"), previous, n)

    def test_a_map_dropped_from_the_fit_keeps_its_previous_row(self):
        out, kept = self.floored({"dod_anzio": row(1.45, 1.30, 26)})
        got = out["maps"]["dod_solitude2"]
        self.assertEqual((got["flag_coefficient"], got["alive_coefficient"]),
                         (1.2309, 0.85))
        self.assertEqual(got[FLOOR_MARKER], "absent_from_fit")
        self.assertEqual(got["kept_from_fitted_at"], "2026-11-09T16:13:30Z")
        self.assertEqual(got["refit_official_halves"], 0)
        self.assertTrue(any("dod_solitude2" in line for line in kept))

    def test_a_thin_map_that_lost_halves_keeps_its_previous_row(self):
        out, _ = self.floored({"dod_thin": row(2.40, 0.70, 5)})
        got = out["maps"]["dod_thin"]
        self.assertEqual(got["flag_coefficient"], 1.60)
        self.assertEqual(got[FLOOR_MARKER], "fewer_official_halves")
        self.assertEqual(got["refit_official_halves"], 5)

    def test_a_thin_map_that_gained_halves_takes_its_new_fit(self):
        # railroad2_s10a's shape: 6 halves, still under the floor, but growing.
        out, _ = self.floored({"dod_growing": row(1.70, 1.00, 9)})
        self.assertEqual(out["maps"]["dod_growing"]["flag_coefficient"], 1.70)
        self.assertNotIn(FLOOR_MARKER, out["maps"]["dod_growing"])

    def test_a_map_that_lost_halves_but_stays_at_the_floor_takes_its_new_fit(self):
        out, _ = self.floored({"dod_anzio": row(1.50, 1.30, int(N))})
        self.assertEqual(out["maps"]["dod_anzio"]["flag_coefficient"], 1.50)
        self.assertNotIn(FLOOR_MARKER, out["maps"]["dod_anzio"])

    def test_a_never_measured_map_is_left_to_the_fit(self):
        out, _ = self.floored({"dod_brand_new": row(1.30, 0.90, 2)})
        self.assertEqual(out["maps"]["dod_brand_new"]["flag_coefficient"], 1.30)
        self.assertNotIn(FLOOR_MARKER, out["maps"]["dod_brand_new"])

    def test_a_row_kept_twice_still_names_the_fit_that_measured_it(self):
        once, _ = self.floored({})
        twice, _ = apply_floor(table({}, "2026-11-23T14:00:00Z"), once, N)
        self.assertEqual(twice["maps"]["dod_solitude2"]["kept_from_fitted_at"],
                         "2026-11-09T16:13:30Z")

    def test_no_previous_table_changes_nothing(self):
        out, kept = self.floored({"dod_x": row(1.3, 0.9, 3)}, previous={})
        self.assertEqual(set(out["maps"]), {"dod_x"})
        self.assertEqual(kept, [])

    def test_the_floor_is_recorded_in_the_table(self):
        out, _ = self.floored({}, n=12)
        self.assertEqual(out["min_official_halves"], 12)


class RefitWritesTheFloor(unittest.TestCase):
    """Through main(--write), which is what the weekly job runs."""

    def run_main(self, committed, fitted, *extra):
        fake = types.ModuleType("scripts.report_service")

        class _Ma:
            def source_capabilities(self, db):
                return {}

        fake.LocalMysql = lambda: object()
        fake.load_match_analytics = lambda repo: _Ma()
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "map_coefficients.json"
            out.write_text(json.dumps(committed, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
            buf = io.StringIO()
            with mock.patch.dict(sys.modules, {"scripts.report_service": fake}), \
                    mock.patch.object(F, "build", lambda *a, **k: fitted), \
                    redirect_stdout(buf):
                rc = F.main(["--write", "--out", str(out), *extra])
            return rc, json.loads(out.read_text(encoding="utf-8")), buf.getvalue()

    def test_a_dropped_map_is_still_in_the_written_table(self):
        rc, written, printed = self.run_main(
            PREVIOUS, table({"dod_anzio": row(1.45, 1.30, 26),
                             "dod_thin": row(1.60, 0.90, 14),
                             "dod_growing": row(1.91, 1.10, 6)},
                            "2026-11-16T14:00:00Z"))
        self.assertEqual(rc, 0)
        self.assertEqual(written["maps"]["dod_solitude2"]["flag_coefficient"], 1.2309)
        self.assertEqual(written["maps"]["dod_anzio"]["flag_coefficient"], 1.45)
        self.assertIn("kept by the floor", printed)
        self.assertNotIn("- dod_solitude2", printed)

    def test_the_floor_follows_prior_halves_unless_set(self):
        # dod_growing moves, so the table is written at all.
        fitted = table({"dod_anzio": row(1.45, 1.30, 10),
                        "dod_growing": row(1.70, 1.00, 9)}, "2026-11-16T14:00:00Z")
        _, default, _ = self.run_main(PREVIOUS, fitted)
        _, lowered, _ = self.run_main(PREVIOUS, fitted, "--min-official-halves", "8")
        self.assertEqual(default["maps"]["dod_anzio"][FLOOR_MARKER],
                         "fewer_official_halves")
        self.assertEqual(lowered["maps"]["dod_anzio"]["flag_coefficient"], 1.45)


def tables(live=None, kept=None, retained=None):
    return (mock.patch.dict(flag_swing.MAP_COEFFICIENTS, live or {}, clear=True),
            mock.patch.dict(flag_swing.FLOOR_KEPT_MAP_COEFFICIENTS, kept or {},
                            clear=True),
            mock.patch.dict(flag_swing.RETAINED_MAP_COEFFICIENTS, retained or {},
                            clear=True),
            mock.patch.dict(flag_swing.MAP_COEFFICIENT_CARRY_FORWARD, {}, clear=True))


class ConsumerReadsTheFloor(unittest.TestCase):
    def resolve(self, name, **kw):
        a, b, c, d = tables(**kw)
        with a, b, c, d:
            cfg = FlagSwingConfig().for_map(name)
            env = build_flag_swing_shadow(None, None, None, None, None,
                                          map_name=name, source_available=False)
        return (cfg.flag_coefficient, cfg.alive_coefficient), cfg.calibration, env

    def test_a_kept_row_prices_the_map_and_says_it_is_not_fresh(self):
        coeffs, cal, env = self.resolve(
            "dod_solitude2", kept={"dod_solitude2": (1.2309, 0.85, "2026-11-09T16:13:30Z")})
        self.assertEqual(coeffs, (1.2309, 0.85))
        self.assertEqual(cal, "retained_fit:dod_solitude2@2026-11-09T16:13:30Z")
        self.assertIs(env["coefficients_retained"], True)

    def test_a_kept_row_wins_over_the_older_retained_file(self):
        coeffs, _, _ = self.resolve(
            "dod_x", kept={"dod_x": (1.3, 0.9, "2026-11-09T16:13:30Z")},
            retained={"dod_x": (0.94, 0.68, "c" * 40)})
        self.assertEqual(coeffs, (1.3, 0.9))

    def test_a_never_measured_map_still_prices_on_the_prior(self):
        coeffs, cal, _ = self.resolve(
            "dod_never", kept={"dod_solitude2": (1.2309, 0.85, "2026-11-09T16:13:30Z")})
        self.assertEqual((coeffs, cal), ((2.0, 1.0), "uncalibrated_baseline"))

    def test_a_kept_row_is_not_loaded_as_a_fresh_fit(self):
        payload = table({"dod_fresh": row(1.5, 0.9, 20),
                         "dod_kept": {**row(1.2, 0.8, 8), FLOOR_MARKER: "absent_from_fit",
                                      "kept_from_fitted_at": "w1"}}, "w2")
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config").mkdir()
            (Path(d) / "config" / "map_coefficients.json").write_text(
                json.dumps(payload), encoding="utf-8")
            fake_file = str(Path(d) / "scripts" / "flag_swing.py")
            with mock.patch.object(flag_swing, "__file__", fake_file):
                live = flag_swing._load_map_coefficients()
                kept = flag_swing._load_floor_kept_map_coefficients()
        self.assertEqual(set(live), {"dod_fresh"})
        self.assertEqual(kept, {"dod_kept": (1.2, 0.8, "w1")})


class ShippedTable(unittest.TestCase):
    def test_the_committed_table_has_no_kept_rows_yet(self):
        # Every map the 2026-11-09 fit measured is still fresh, so this change
        # reprices nothing until a refit actually drops or thins a map.
        payload = json.loads((REPO / "config" / "map_coefficients.json")
                             .read_text(encoding="utf-8"))
        self.assertFalse([m for m, r in payload["maps"].items() if r.get(FLOOR_MARKER)])
        self.assertEqual(set(flag_swing.MAP_COEFFICIENTS), set(payload["maps"]))
        self.assertEqual(flag_swing.FLOOR_KEPT_MAP_COEFFICIENTS, {})

    def test_the_accepted_refit_would_have_come_out_the_same(self):
        # Replaying the floor over the 2026-11-09 refit: every map it fitted keeps
        # its reviewed number, and only the four maps it dropped come back.
        if subprocess.run(["git", "-C", str(REPO), "rev-parse",
                           "--is-shallow-repository"],
                          capture_output=True, text=True).stdout.strip() != "false":
            if os.environ.get("GITHUB_ACTIONS"):
                self.fail("CI checkout lost the history this check reads")
            self.skipTest("no full git history here")

        def at(rev):
            return json.loads(subprocess.run(
                ["git", "-C", str(REPO), "show", f"{rev}:config/map_coefficients.json"],
                check=True, capture_output=True, text=True, encoding="utf-8").stdout)

        before, after = at("c39fa04"), at("166a059")
        out, _ = apply_floor(after, before, N)
        for name, fresh in after["maps"].items():
            self.assertEqual(out["maps"][name], fresh, name)
        kept = {m for m, r in out["maps"].items() if r.get(FLOOR_MARKER)}
        self.assertEqual(kept, {"dod_armory_b6", "dod_halle",
                                "dod_saints2_b3e", "dod_saints2_b4e"})


if __name__ == "__main__":
    unittest.main()
