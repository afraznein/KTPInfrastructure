"""The reviewable half of the per-map fit: labels, corpus choice, and the diff."""
from __future__ import annotations

import unittest

from scripts.fit_map_coefficients import build, coefficients, diff, half_winners


class EngineLabels(unittest.TestCase):
    def row(self, allies, axis, mid="m1", half=1, mp="dod_x", mt=0):
        return {"match_id": mid, "half": half, "map_name": mp,
                "match_type": mt, "allies_points": allies, "axis_points": axis}

    def test_the_side_that_outscored_the_other_wins(self):
        got = half_winners([self.row(55, 46), self.row(46, 55, half=2)])
        self.assertEqual(got[("m1", 1)]["winner"], 1)
        self.assertEqual(got[("m1", 2)]["winner"], 2)

    def test_a_draw_yields_no_label_rather_than_a_guess(self):
        self.assertEqual(half_winners([self.row(50, 50)]), {})

    def test_map_and_type_are_carried_for_routing(self):
        got = half_winners([self.row(9, 1, mp="dod_thunder2", mt=2)])
        self.assertEqual(got[("m1", 1)]["map_name"], "dod_thunder2")
        self.assertEqual(got[("m1", 1)]["match_type"], 2)


def half(flag_term, label, n=30):
    return [(flag_term, 0.0, label)] * n


class CorpusChoice(unittest.TestCase):
    """Practice is training data whose keep-or-drop is decided by measurement."""

    def collector(self, official, practice):
        return lambda: (official, practice)

    def scorer(self, losses):
        """Stand in for the held-out scorer, keyed by how much extra data it got."""
        def score(official, extra, **_kw):
            return losses[sum(len(v) for v in extra.values())]
        return score

    def test_the_corpus_with_the_lowest_held_out_loss_wins(self):
        official = {"dod_x": [half(0.3, 1), half(-0.3, 0)] * 4}
        practice = {"dod_x": [(half(0.3, 1), 2)] * 3 + [(half(0.3, 1), 1)] * 2}
        # 0 extra = officials only, 3 = +12man, 5 = +all practice.
        out = build(self.collector(official, practice), "2026-09-13",
                    score=self.scorer({0: 0.70, 3: 0.60, 5: 0.65}))
        self.assertEqual(out["corpus_selected"], "officials_plus_12man")

    def test_a_marginal_gain_does_not_pull_practice_in(self):
        official = {"dod_x": [half(0.3, 1), half(-0.3, 0)] * 4}
        practice = {"dod_x": [(half(0.3, 1), 2)] * 3}
        out = build(self.collector(official, practice), "2026-09-13",
                    score=self.scorer({0: 0.700000, 3: 0.699999}))
        self.assertEqual(out["corpus_selected"], "officials_only")

    def test_every_candidate_is_scored_even_when_not_chosen(self):
        official = {"dod_x": [half(0.3, 1), half(-0.3, 0)] * 4}
        out = build(self.collector(official, {}), "2026-09-13")
        self.assertEqual(sorted(out["corpus_candidates"]),
                         ["officials_only", "officials_plus_12man",
                          "officials_plus_all_practice"])

    def test_a_tie_prefers_the_least_data(self):
        # Practice that says exactly what officials already say adds risk and
        # no information, so it must not be pulled in on a tie. This one runs
        # the REAL scorer: identical practice genuinely ties.
        official = {"dod_x": [half(0.3, 1), half(-0.3, 0)] * 4}
        practice = {"dod_x": [(half(0.3, 1), 2), (half(-0.3, 0), 2)] * 8}
        out = build(self.collector(official, practice), "2026-09-13")
        self.assertEqual(out["corpus_selected"], "officials_only")

    def test_practice_that_contradicts_officials_is_dropped(self):
        official = {"dod_x": [half(0.3, 1), half(-0.3, 0)] * 4}
        # Same states, opposite outcomes: if this were trusted the fit would
        # be dragged toward noise, so the held-out score must reject it.
        practice = {"dod_x": [(half(0.3, 0), 1), (half(-0.3, 1), 1)] * 8}
        out = build(self.collector(official, practice), "2026-09-13")
        self.assertEqual(out["corpus_selected"], "officials_only")

    def test_no_official_halves_refuses_to_write_a_table(self):
        with self.assertRaises(SystemExit):
            build(self.collector({}, {"dod_x": [(half(0.3, 1), 2)]}), "2026-09-13")

    def test_payload_carries_its_provenance(self):
        official = {"dod_x": [half(0.3, 1), half(-0.3, 0)] * 4}
        out = build(self.collector(official, {}), "2026-09-13")
        self.assertEqual(out["corpus_since"], "2026-09-13")
        self.assertIn("ktp_score_events", out["label_source"])
        row = out["maps"]["dod_x"]
        for key in ("official_halves", "training_halves", "shrinkage_weight",
                    "own_flag_coefficient", "log_loss"):
            self.assertIn(key, row)


class ReviewDiff(unittest.TestCase):
    """The diff is the review artifact, so it has to name what moved."""

    def payload(self, maps):
        return {"maps": {m: {"flag_coefficient": f, "alive_coefficient": a}
                         for m, (f, a) in maps.items()}}

    def test_unchanged_is_silent(self):
        p = self.payload({"dod_x": (1.5, 0.9)})
        self.assertEqual(diff(p, p), [])

    def test_a_moved_map_shows_both_ends(self):
        out = diff(self.payload({"dod_x": (1.5, 0.9)}),
                   self.payload({"dod_x": (1.8, 0.9)}))
        self.assertEqual(len(out), 1)
        self.assertIn("1.5000 -> 1.8000", out[0])

    def test_a_new_map_is_marked_new(self):
        out = diff(self.payload({}), self.payload({"dod_y": (2.0, 1.0)}))
        self.assertIn("+ dod_y", out[0])
        self.assertIn("(new)", out[0])

    def test_a_dropped_map_is_not_silently_lost(self):
        out = diff(self.payload({"dod_y": (2.0, 1.0)}), self.payload({}))
        self.assertIn("- dod_y", out[0])

    def test_coefficients_view_is_sorted_and_flat(self):
        got = coefficients(self.payload({"b": (1.0, 0.5), "a": (2.0, 1.0)}))
        self.assertEqual(list(got), ["a", "b"])
        self.assertEqual(got["a"], [2.0, 1.0])


if __name__ == "__main__":
    unittest.main()


class LedgerFallback(unittest.TestCase):
    """The engine feed starts 2026-09-17; the ledger covers what came before."""

    def setUp(self):
        from scripts.fit_map_coefficients import merge_ledger_fallback
        self.merge = merge_ledger_fallback
        self.shape = {("m1", 1): ("dod_thunder2", 0), ("m1", 2): ("dod_thunder2", 0)}

    def test_a_half_the_engine_labelled_is_not_overwritten(self):
        engine = {("m1", 1): {"winner": 1, "map_name": "dod_thunder2",
                              "match_type": 0, "label_source": "engine"}}
        got = self.merge(engine, {"m1": {1: 2}}, self.shape)
        self.assertEqual(got[("m1", 1)]["winner"], 1)
        self.assertEqual(got[("m1", 1)]["label_source"], "engine")

    def test_a_half_the_engine_missed_is_filled_and_marked(self):
        got = self.merge({}, {"m1": {2: 2}}, self.shape)
        self.assertEqual(got[("m1", 2)]["winner"], 2)
        self.assertEqual(got[("m1", 2)]["label_source"], "ledger")
        self.assertEqual(got[("m1", 2)]["map_name"], "dod_thunder2")

    def test_a_half_with_no_shape_is_skipped_rather_than_guessed(self):
        self.assertEqual(self.merge({}, {"unknown": {1: 1}}, self.shape), {})

    def test_the_mix_is_reported_in_the_payload(self):
        official = {"dod_x": [half(0.3, 1), half(-0.3, 0)] * 4}
        out = build(lambda: (official, {}), "2026-09-13",
                    extra={"label_mix": {"engine": 20, "ledger": 16}})
        self.assertEqual(out["label_mix"], {"engine": 20, "ledger": 16})
