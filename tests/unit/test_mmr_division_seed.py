"""Division seeding: the prior that orders disconnected rating pools.

League divisions never play each other -- measured 2026-09-30, zero
cross-division league matches in S9 -- so each pool is anchored at the model's
starting mu by the prior, not by evidence. These tests pin the properties that
make the prior safe: it is weak, it decays, and it cannot overwrite a rating a
player earned.
"""
import json
import sys
import unittest
from pathlib import Path

MMR = Path(__file__).resolve().parents[2] / "scripts" / "mmr"
sys.path.insert(0, str(MMR))

OFFSETS = {"Gold": 1.87, "Silver": 0.0, "Bronze": -1.64}


class Seeding(unittest.TestCase):
    def setUp(self):
        import ladder
        self.L = ladder
        self.lad = ladder.OpenSkill()

    def test_it_orders_the_pools(self):
        self.lad.seed_from_divisions({1: "Gold", 2: "Silver", 3: "Bronze"}, OFFSETS)
        r = self.lad.ratings()
        self.assertGreater(r[1]["mu"], r[3]["mu"])
        # Silver takes no offset, so it is simply unseeded rather than present.
        self.assertAlmostEqual(r[1]["mu"] - r[3]["mu"], 1.87 + 1.64, places=2)

    def test_the_prior_is_deliberately_WEAK(self):
        """A division step must be small against sigma, or the ordering calcifies.

        If the gap approached sigma, a seeded player would need an implausible
        run of results to cross a division boundary and the seeding would become
        the rating rather than a prior on it.
        """
        self.lad.seed_from_divisions({1: "Gold"}, OFFSETS)
        r = self.lad.ratings()[1]
        self.assertLess(OFFSETS["Gold"], r["sigma"] / 2,
                        "a division step should be well under half a sigma")

    def test_sigma_stays_at_the_models_starting_value_so_evidence_wins(self):
        default_sigma = self.lad.m.rating().sigma
        self.lad.seed_from_divisions({1: "Gold", 3: "Bronze"}, OFFSETS)
        for pid in (1, 3):
            self.assertAlmostEqual(self.lad.ratings()[pid]["sigma"], default_sigma, places=2)

    def test_it_never_overwrites_a_rating_a_player_earned(self):
        # Gold player 1 loses to Bronze player 3, then seeding is applied late.
        self.lad.update([1], [3], 0.0)
        earned = self.lad.ratings()[1]["mu"]
        self.lad.seed_from_divisions({1: "Gold", 3: "Bronze"}, OFFSETS)
        self.assertAlmostEqual(self.lad.ratings()[1]["mu"], earned, places=6)

    def test_an_unlabelled_player_is_left_alone(self):
        self.lad.seed_from_divisions({1: "Gold", 99: None, 98: "Platinum"}, OFFSETS)
        r = self.lad.ratings()
        self.assertIn(1, r)
        self.assertNotIn(99, r)      # no label
        self.assertNotIn(98, r)      # label with no offset

    def test_results_can_still_cross_a_division_boundary(self):
        """The point of a weak prior: a seeded bronze player who keeps beating
        seeded gold players must be able to pass them."""
        self.lad.seed_from_divisions({1: "Gold", 2: "Gold", 3: "Bronze"}, OFFSETS)
        start_gap = self.lad.ratings()[1]["mu"] - self.lad.ratings()[3]["mu"]
        for _ in range(6):
            self.lad.update([3], [1], 1.0)
            self.lad.update([3], [2], 1.0)
        end_gap = self.lad.ratings()[1]["mu"] - self.lad.ratings()[3]["mu"]
        self.assertLess(end_gap, 0, "bronze beating gold repeatedly must overtake it")
        self.assertLess(end_gap, start_gap)


class OffsetsFile(unittest.TestCase):
    """`division_offsets.json` is fitted on the data server and committed, the
    same way momentum_params.json is, because CI cannot see 12-mans."""

    def setUp(self):
        self.path = MMR / "division_offsets.json"
        if not self.path.exists():
            self.skipTest("division_offsets.json not fitted in this checkout")
        self.doc = json.loads(self.path.read_text(encoding="utf-8"))

    def test_it_is_about_nobody(self):
        body = json.dumps(self.doc)
        for k in ("players", "player_id", "steam_id", "alias"):
            self.assertNotIn(f'"{k}"', body)

    def test_the_divisions_are_ordered_and_the_baseline_is_zero(self):
        d = self.doc["divisions"]
        self.assertEqual(d[self.doc["baseline"]]["mu_offset"], 0.0)
        mus = [v["mu_offset"] for v in d.values()]
        self.assertEqual(mus, sorted(mus, reverse=True), "emitted highest-first")

    def test_every_offset_is_weak_relative_to_the_starting_sigma(self):
        import ladder
        sigma = ladder.OpenSkill().m.rating().sigma
        for name, v in self.doc["divisions"].items():
            self.assertLess(abs(v["mu_offset"]), sigma / 2,
                            f"{name} offset is too strong to be a prior")

    def test_it_declares_that_the_mu_conversion_is_a_prior_not_a_measurement(self):
        # The fit is in performance-sigma; nothing in the data converts that to
        # mu. If that ever stops being flagged, the page would publish a chosen
        # constant as though it were measured.
        self.assertIn("prior", self.doc["mu_per_performance_sigma_is"])
        self.assertGreater(self.doc["mu_per_performance_sigma"], 0)

    def test_the_fit_is_stable_across_eras(self):
        """S9 labels against S10-era play. If these diverge the labels are stale
        and the offsets should not be trusted."""
        for name, v in self.doc["divisions"].items():
            eras = v.get("by_era_z_kd") or {}
            if len(eras) < 2:
                continue
            self.assertLess(max(eras.values()) - min(eras.values()), 0.25,
                            f"{name} moved too much between eras: {eras}")


class PublishedHonestly(unittest.TestCase):
    """Seeding changes what the rating MEANS, so the payload has to say so.

    A reader comparing bottom-gold against mid-silver is entitled to know
    whether the ordering they are looking at was measured or assumed.
    """

    def setUp(self):
        sys.path.insert(0, str(MMR.parents[1] / "scripts"))
        sys.path.insert(0, str(MMR.parents[1]))
        import methodology
        self.M = methodology
        self.params = methodology.load_params()

    def _doc(self, seed):
        return self.M.build(self.params, generated_at="2026-09-30T00:00:00+00:00",
                            division_seed=seed)

    def test_a_seeded_run_declares_the_prior_and_the_circularity(self):
        d = self._doc({"enabled": True, "offsets": OFFSETS, "labelled_players": 120})
        ds = d["mmr"]["division_seeding"]
        self.assertTrue(ds["enabled"])
        self.assertEqual(ds["offsets_mu"], OFFSETS)
        self.assertIn("prior", ds["status"])
        self.assertIn("circular", ds["caveat"])

    def test_an_unseeded_run_warns_the_scales_are_not_comparable(self):
        ds = self._doc(None)["mmr"]["division_seeding"]
        self.assertFalse(ds["enabled"])
        self.assertIn("NOT on a common scale", ds["what"])
        self.assertIsNone(ds["caveat"])

    def test_it_still_passes_the_publish_gate(self):
        # `life_` once made this whole aggregate unpublishable (#559); any new
        # field has to clear assert_sanitized, not just validate_for_import.
        from analytics_report_dto import assert_sanitized
        assert_sanitized(self._doc({"enabled": True, "offsets": OFFSETS,
                                    "labelled_players": 120}))


if __name__ == "__main__":
    unittest.main()
