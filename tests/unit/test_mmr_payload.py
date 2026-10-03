"""The mmr_openskill season-aggregate payload.

This is a contract with a consumer in another repository (keep-the-prac
#760's profile card), so the tests pin the shape that consumer actually
reads, not merely that the function returns something.

Pure logic: no network, no openskill, no database.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "mmr"))

RATINGS = {"7": {"mu": 26.4, "sigma": 8.22, "ordinal": 1.74},
           "8": {"mu": 30.0, "sigma": 2.0, "ordinal": 24.0}}
PLAYED = {7: 2, 8: 9}
ALIASES = {7: "Ecl1ps3", 8: "seanality"}
WHEN = "2026-09-16T12:00:00+00:00"


def build(**kw):
    import mmr_payload as M
    return M.build(RATINGS, PLAYED, ALIASES, generated_at=WHEN, **kw)


class Contract(unittest.TestCase):
    """Field names and meanings the website reads. Changing any of these
    silently blanks the profile card rather than erroring."""

    def test_carries_the_kind_the_consumer_queries(self):
        self.assertEqual(build()["kind"], "mmr_openskill")

    def test_each_row_has_exactly_the_fields_the_card_reads(self):
        row = build()["players"][0]
        self.assertEqual(set(row), {"name", "matches", "rating", "uncertainty", "conservative"})

    def test_conservative_is_mu_minus_three_sigma(self):
        """Verified against the consumer's own fixture: rating 26.4,
        uncertainty 8.22, conservative 1.74."""
        # Gate opened: this is about the arithmetic, not about who is shown.
        row = next(r for r in build(min_matches=0, max_sigma=99)["players"]
                   if r["name"] == "Ecl1ps3")
        self.assertEqual(row["rating"], 26.4)
        self.assertEqual(row["uncertainty"], 8.22)
        self.assertEqual(row["conservative"], 1.74)

    def test_min_matches_travels_with_the_payload(self):
        """So the display threshold can move without a website deploy."""
        self.assertEqual(build(min_matches=5)["min_matches"], 5)

    def test_is_labelled_provisional(self):
        payload = build()
        self.assertTrue(payload["provisional"])
        self.assertIn("retroactively", payload["notice"])

    def test_carries_the_columns_the_aggregate_insert_needs(self):
        """So the existing insert path writes this row with no special case."""
        payload = build(source_report_count=9)
        self.assertEqual(payload["source_report_count"], 9)
        self.assertIsInstance(payload["report_schema_version"], int)


class Privacy(unittest.TestCase):
    def test_never_publishes_an_identifier(self):
        body = str(build())
        for banned in ("player_id", "steam_id", "steam_id64"):
            self.assertNotIn(banned, body)

    def test_a_player_without_an_alias_is_dropped_not_published_under_an_id(self):
        import mmr_payload as M
        payload = M.build(RATINGS, PLAYED, {7: "Ecl1ps3", 8: None}, generated_at=WHEN,
                          min_matches=0, max_sigma=99)
        self.assertEqual([r["name"] for r in payload["players"]], ["Ecl1ps3"])

    def test_a_blank_alias_counts_as_absent(self):
        import mmr_payload as M
        payload = M.build(RATINGS, PLAYED, {7: "  ", 8: "seanality"}, generated_at=WHEN,
                          min_matches=0, max_sigma=99)
        self.assertEqual([r["name"] for r in payload["players"]], ["seanality"])


class DisplayGate(unittest.TestCase):
    """Who gets a number on their profile, and why it is sigma not match count.

    Measured 2026-09-29: every displayable player had exactly 3 matches and an
    identical sigma of 8.16, so `conservative` was mu - 24.5 and NEGATIVE for
    20 of 41. Match count says how often someone turned up; sigma says whether
    the rating knows anything yet.

    Gated in the PRODUCER on purpose. The previous design published a
    `min_matches` threshold and trusted the consumer, and keep-the-prac's
    findMmrEntry never applied it -- its own docstring said it did -- so 120 of
    161 players below the threshold each got a card, 41 of them on one match.
    """

    def setUp(self):
        import mmr_payload as M
        self.M = M

    def test_the_gate_is_half_the_models_starting_sigma(self):
        self.assertAlmostEqual(self.M.MAX_SIGMA_FOR_DISPLAY, 25.0 / 3.0 * 0.5, places=6)

    def test_start_sigma_matches_the_ladder(self):
        """MODEL_START_SIGMA is duplicated rather than imported, because
        report_service loads this module on the data server and `ladder` drags
        in openskill, which is not installed there (#559). This pins the
        duplicate so it cannot drift silently."""
        import sys
        from pathlib import Path as P
        sys.path.insert(0, str(P(__file__).resolve().parents[2] / "scripts" / "mmr"))
        import ladder
        self.assertAlmostEqual(self.M.MODEL_START_SIGMA,
                               ladder.OpenSkill().m.rating().sigma, places=6)

    def test_an_unconverged_player_is_withheld_however_many_matches(self):
        r = {"1": {"mu": 25.0, "sigma": 8.16}}
        d = self.M.build(r, {1: 50}, {1: "played_fifty"}, generated_at="x")
        self.assertEqual(d["players"], [], "50 matches must not beat a wide sigma")
        self.assertEqual(d["rated_players"], 1)
        self.assertEqual(d["withheld_players"], 1)

    def test_a_converged_player_is_shown(self):
        r = {"1": {"mu": 27.0, "sigma": 3.5}}
        d = self.M.build(r, {1: 12}, {1: "converged"}, generated_at="x")
        self.assertEqual([p["name"] for p in d["players"]], ["converged"])
        self.assertEqual(d["withheld_players"], 0)

    def test_both_gates_apply_not_either(self):
        # Converged sigma but too few matches is still withheld.
        r = {"1": {"mu": 27.0, "sigma": 2.0}}
        d = self.M.build(r, {1: 1}, {1: "one_match"}, generated_at="x")
        self.assertEqual(d["players"], [])

    def test_the_thresholds_are_published_so_the_page_can_explain_itself(self):
        d = self.M.build({"1": {"mu": 25.0, "sigma": 8.2}}, {1: 3}, {1: "a"},
                         generated_at="x")
        self.assertEqual(d["min_matches"], self.M.MIN_MATCHES_FOR_DISPLAY)
        self.assertAlmostEqual(d["max_uncertainty"], self.M.MAX_SIGMA_FOR_DISPLAY, places=3)
        self.assertEqual(d["rated_players"], 1)

    def test_no_withheld_player_can_leak_through_the_published_rows(self):
        # The point of producer-side gating: a consumer that ignores every
        # threshold still cannot render someone it was never sent.
        r = {str(i): {"mu": 25.0, "sigma": 8.16} for i in range(1, 20)}
        d = self.M.build(r, {i: 3 for i in range(1, 20)},
                         {i: f"p{i}" for i in range(1, 20)}, generated_at="x")
        self.assertEqual(d["players"], [])
        self.assertEqual(d["rated_players"], 19)


class Stability(unittest.TestCase):
    def test_rows_are_ordered_best_first(self):
        names = [r["name"] for r in build(min_matches=0, max_sigma=99)["players"]]
        self.assertEqual(names, ["seanality", "Ecl1ps3"])

    def test_the_same_input_produces_the_same_payload(self):
        """An unordered payload would hash differently every run and publish
        a new revision weekly for no change."""
        self.assertEqual(build(), build())

    def test_matches_played_comes_from_participation_not_the_rating(self):
        row = next(r for r in build()["players"] if r["name"] == "seanality")
        self.assertEqual(row["matches"], 9)

    def test_a_player_with_no_participation_record_reports_zero(self):
        import mmr_payload as M
        payload = M.build(RATINGS, {}, ALIASES, generated_at=WHEN)
        self.assertTrue(all(r["matches"] == 0 for r in payload["players"]))

    def test_a_rating_missing_its_numbers_is_skipped(self):
        import mmr_payload as M
        payload = M.build({"7": {"mu": None, "sigma": 1.0}}, PLAYED, ALIASES, generated_at=WHEN)
        self.assertEqual(payload["players"], [])


class ImportGuards(unittest.TestCase):
    """What report_service.py import-mmr refuses before writing to production.

    Tested here because report_service imports the Unix-only `pwd` module and
    cannot be exercised on a dev machine at all -- the guards on a production
    write are exactly the code that must not ship untested.
    """

    def setUp(self):
        import mmr_payload as M
        self.M = M
        self.good = build()

    def test_a_well_formed_payload_passes(self):
        self.assertEqual(self.M.validate_for_import(self.good), [])

    def test_the_wrong_kind_is_refused(self):
        bad = {**self.good, "kind": "leaderboard_ktpr_v22"}
        self.assertIn("expected 'mmr_openskill'", " ".join(self.M.validate_for_import(bad)))

    def test_a_payload_that_rated_NOBODY_is_refused(self):
        """A build that produced no ratings at all is broken, and publishing it
        would blank every profile card at once."""
        self.assertIn("no players", " ".join(self.M.validate_for_import(
            {**self.good, "players": [], "rated_players": 0})))
        # Payloads predating `rated_players` fall back to len(players).
        bare = {k: v for k, v in self.good.items() if k != "rated_players"}
        self.assertIn("no players", " ".join(self.M.validate_for_import(
            {**bare, "players": []})))

    def test_rating_NOBODY_CONFIDENTLY_ENOUGH_is_allowed_through(self):
        """Distinct from the above, and the reason the guard had to be split.

        Early in a season every player's sigma is still near the starting
        value, so the display gate withholds everyone. That is the honest
        state, not a broken build, and it has to stay publishable -- otherwise
        the only way to ship is to show ratings that know nothing.
        """
        self.assertEqual(self.M.validate_for_import(
            {**self.good, "players": [], "rated_players": 161}), [])

    def test_rows_missing_a_field_the_card_reads_are_refused(self):
        bad = {**self.good, "players": [{"name": "x", "matches": 1, "rating": 1.0}]}
        problems = " ".join(self.M.validate_for_import(bad))
        self.assertIn("missing", problems)
        self.assertIn("conservative", problems)

    def test_a_payload_carrying_identifiers_is_refused(self):
        bad = {**self.good,
               "players": [{**self.good["players"][0], "steam_id64": "76561197960287930"}]}
        self.assertIn("identifiers", " ".join(self.M.validate_for_import(bad)))

    def test_a_non_object_is_refused_rather_than_crashing(self):
        self.assertTrue(self.M.validate_for_import([1, 2, 3]))
        self.assertTrue(self.M.validate_for_import(None))



# Invented identifiers only. The pseudonym is a hash of a made-up string.
SYNTHETIC_STEAM2 = "STEAM_0:1:1000001"
SYNTHETIC_STEAM64 = "76561190000000001"
PSEUDONYM = "p_" + __import__("hashlib").sha256(b"synthetic-player").hexdigest()[:16]


def _row(name):
    return {"name": name, "matches": 4, "rating": 25.0, "uncertainty": 3.0,
            "conservative": 16.0}


class ImportIdentifierKeys(unittest.TestCase):
    """The identifier leg must see keys, not only row field names: an
    object-keyed `players` used to be refused on shape before the leg ran."""

    def setUp(self):
        import mmr_payload as M
        self.M = M
        self.good = build()

    def problems(self, payload):
        return " ".join(self.M.validate_for_import(payload))

    def test_players_keyed_by_steam_id_is_refused_as_an_identifier_leak(self):
        bad = {**self.good, "players": {SYNTHETIC_STEAM2: _row("AliasOne"),
                                        SYNTHETIC_STEAM64: _row("AliasTwo")}}
        problems = self.problems(bad)
        self.assertIn("identifiers as keys", problems)
        self.assertIn("players is an object", problems)

    def test_players_keyed_by_raw_player_id_is_refused_as_an_identifier_leak(self):
        """The shape run_weekly's ratings file actually has."""
        bad = {**self.good, "players": {"101": _row("AliasOne"), "102": _row("AliasTwo")}}
        self.assertIn("identifiers as keys", self.problems(bad))

    def test_players_keyed_by_pseudonym_is_refused_on_shape_not_as_a_leak(self):
        bad = {**self.good, "players": {PSEUDONYM: _row("AliasOne")}}
        problems = self.M.validate_for_import(bad)
        self.assertIn("players is an object", " ".join(problems))
        self.assertFalse([p for p in problems if "identifier" in p], problems)

    def test_an_id_keyed_map_outside_players_is_refused(self):
        """The importer writes the whole document, not just `players`."""
        bad = {**self.good, "history": {SYNTHETIC_STEAM2: {"rating": 20.0}}}
        self.assertIn("identifiers as keys under ['history']", self.problems(bad))

    def test_a_pseudonym_keyed_map_outside_players_is_accepted(self):
        ok = {**self.good, "history": {PSEUDONYM: {"rating": 20.0}}}
        self.assertEqual(self.M.validate_for_import(ok), [])

    def test_a_differently_spelled_identifier_field_is_refused(self):
        bad = {**self.good, "players": [{**_row("AliasOne"), "steamId": SYNTHETIC_STEAM64}]}
        self.assertIn("identifiers as keys", self.problems(bad))

    def test_a_steam_id_published_as_the_alias_is_refused(self):
        bad = {**self.good, "players": [_row(SYNTHETIC_STEAM2)]}
        self.assertIn("SteamID-shaped values at ['players[].name']", self.problems(bad))

    def test_a_non_object_row_is_refused_rather_than_crashing(self):
        bad = {**self.good, "players": [_row("AliasOne"), 7]}
        self.assertIn("must all be objects", self.problems(bad))

    def test_the_published_list_shape_still_passes(self):
        ok = {**self.good, "players": [_row("AliasOne"), _row("AliasTwo")]}
        self.assertEqual(self.M.validate_for_import(ok), [])

if __name__ == "__main__":
    unittest.main()
