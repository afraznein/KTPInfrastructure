"""The per-map scoring fit is gated on its condition number, not only on sample size.

A design where two features move together passes `_solve`'s pivot test and
fits coefficients that are pricing noise; `value()` clamps a negative price but
not an inflated one, so the published number looks sane. The gate rejects it.
"""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "mmr"))

import momentum as M  # noqa: E402
import momentum_report as R  # noqa: E402

TRUE = {"cap": 2.8, "hold3": 0.05, "hold4": 0.3, "capout": 18.0}
NOISE = [3, -4, 2, -1, 5, -3, 1, -2, 4, -5, 2, -1]


def collinear(i):
    """Capouts arrive almost exactly once per 90 s of holding four flags."""
    capouts = 1 + i % 3
    return {"cap": 4 + i % 5, "hold3": 30.0 * (i % 4) + 5,
            "hold4": 90.0 * capouts + (0.4, -0.3, 0.2, -0.5)[i % 4], "capout": capouts}


def separable(i):
    return {"cap": 4 + i % 5, "hold3": 30.0 * (i % 4) + 5,
            "hold4": 40.0 * ((i * 7) % 5) + 10, "capout": (i // 2) % 2}


def samples(design, n=12):
    return [(design(i), sum(TRUE[k] * v for k, v in design(i).items()) + NOISE[i % len(NOISE)])
            for i in range(n)]


def events_for(f, match, half, team):
    """Objective events whose `scoring_features` are exactly `f`."""
    base = {"match": match, "half": half, "team": team}
    ev = [{**base, "kind": "cap", "held": 3, "dt": f["hold3"]},
          {**base, "kind": "cap", "held": 4, "dt": f["hold4"]}]
    ev += [{**base, "kind": "cap", "held": 1, "dt": 0.0} for _ in range(int(f["cap"]) - 2)]
    ev += [{**base, "kind": "capout"} for _ in range(int(f["capout"]))]
    return ev


def corpus(design, mapname, n=12):
    """(labels, objs, mmap) for one map, four team-halves per match."""
    labels, objs, mmap = {}, [], {}
    for i, (f, pts) in enumerate(samples(design, n)):
        mid, half, team = f"{mapname}-{i // 4}", 1 + (i // 2) % 2, 1 + i % 2
        mmap[mid] = mapname
        L = labels.setdefault(mid, {"halves": {1: {}, 2: {}},
                                    "sides": {1: {"allies": "a", "axis": "b"}, 2: {"allies": "b", "axis": "a"}}})
        side = "allies" if team == 1 else "axis"
        L["halves"][half][L["sides"][half][side]] = pts
        objs += events_for(f, mid, half, team)
    return labels, objs, mmap


class ConditionNumber(unittest.TestCase):
    def test_collinear_design_passes_the_pivot_test_but_fits_noise(self):
        rows = samples(collinear)
        A, _ = M._normal_equations(rows)
        coef, _ = M.fit_scoring(rows)
        # every feature is present and gets a nonzero price: nothing in _solve fires
        self.assertTrue(all(A[i][i] > 0 for i in range(len(A))))
        self.assertTrue(all(v != 0.0 for v in coef.values()))
        # yet hold4 is priced at more than 10x its true value
        self.assertGreater(abs(coef["hold4"]), 10 * TRUE["hold4"])
        self.assertGreater(M.scoring_condition(rows), M.MAX_SCORING_CONDITION)

    def test_separable_design_is_under_the_threshold(self):
        self.assertLess(M.scoring_condition(samples(separable)), M.MAX_SCORING_CONDITION)

    def test_scale_alone_does_not_count_as_ill_conditioned(self):
        rows = samples(separable)
        scaled = [({**f, "hold4": f["hold4"] * 1000.0}, p) for f, p in rows]
        self.assertAlmostEqual(M.scoring_condition(scaled), M.scoring_condition(rows), places=6)

    def test_a_feature_that_never_occurs_is_infinitely_ill_conditioned(self):
        rows = [({**f, "capout": 0}, p) for f, p in samples(separable)]
        self.assertEqual(M.scoring_condition(rows), math.inf)

    def test_matches_a_known_condition_number(self):
        # diag(1, 4) equilibrates to the identity; [[1, .5], [.5, 1]] has eigenvalues 1.5 and 0.5
        self.assertAlmostEqual(max(M._symmetric_eigenvalues([[1.0, 0.5], [0.5, 1.0]])), 1.5, places=12)
        self.assertAlmostEqual(min(M._symmetric_eigenvalues([[1.0, 0.5], [0.5, 1.0]])), 0.5, places=12)


class Gate(unittest.TestCase):
    def test_ill_conditioned_map_falls_back_with_a_reason(self):
        fits, rejected = R.fit_scoring_by_map(*corpus(collinear, "dod_collinear"))
        self.assertNotIn("dod_collinear", fits)
        r = rejected["dod_collinear"]
        self.assertEqual(r["reason"], "ill_conditioned")
        self.assertGreater(r["condition_number"], M.MAX_SCORING_CONDITION)
        self.assertEqual(r["max_condition"], M.MAX_SCORING_CONDITION)
        self.assertEqual(r["n_team_halves"], 12)
        self.assertEqual(r["absent_features"], [])

    def test_well_conditioned_map_still_gets_its_fit(self):
        fits, rejected = R.fit_scoring_by_map(*corpus(separable, "dod_separable"))
        self.assertEqual(rejected, {})
        coef, r2, n, cond = fits["dod_separable"]
        self.assertEqual(n, 12)
        self.assertLess(cond, M.MAX_SCORING_CONDITION)

    def test_a_map_that_never_saw_a_feature_names_it(self):
        labels, objs, mmap = corpus(separable, "dod_nocapout")
        objs = [o for o in objs if o["kind"] != "capout"]
        _, rejected = R.fit_scoring_by_map(labels, objs, mmap)
        self.assertIsNone(rejected["dod_nocapout"]["condition_number"])
        self.assertEqual(rejected["dod_nocapout"]["absent_features"], ["capout"])

    def test_too_few_halves_is_still_the_first_gate(self):
        fits, rejected = R.fit_scoring_by_map(*corpus(separable, "dod_thin", n=8))
        self.assertEqual((fits, rejected), ({}, {}))


class Published(unittest.TestCase):
    def test_methodology_carries_the_rejection_on_the_fallback(self):
        import methodology as X
        rej = {"reason": "ill_conditioned", "condition_number": 3434786.3, "max_condition": 200.0,
               "absent_features": [], "n_team_halves": 12}
        params = {"definitions": {"fallback": {"curves": "pooled", "scoring": {"cap": 1.0, "capout": 1.0}}},
                  "pooled": {}, "rho": {"value": 0.3},
                  "maps": {"dod_x": {"halves": 12, "official_halves": 0, "multikills": 0, "caps": 0,
                                     "capouts": 0, "curves": None, "scoring": None, "scoring_rejected": rej}}}
        m = X.build(params, generated_at="2026-10-05T00:00:00+00:00")["momentum"]["maps"]["dod_x"]
        self.assertEqual(m["scoring"]["uses"], "fallback")
        self.assertEqual(m["scoring"]["rejected"], rej)


if __name__ == "__main__":
    unittest.main()
