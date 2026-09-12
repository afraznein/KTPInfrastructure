"""Offline tests for scripts/player_alias.py (no network, no DB).

Covers the steam-id join, the fallbacks when a player has no website
account, and the rule that a name shared by two players in one match stops
identifying either of them.
"""
import unittest

from scripts.player_alias import (
    STEAM64_BASE,
    apply_aliases,
    build_alias_index,
    steam64_to_hlstats,
)


def index():
    return build_alias_index(
        [{"id": 1, "alias": "eman"},
         {"id": 2, "alias": "GorillaBC"},
         {"id": 3, "alias": "   "}],
        [{"player_id": 1, "steam_id64": str(STEAM64_BASE + 10)},
         {"player_id": 1, "steam_id64": str(STEAM64_BASE + 11)},
         {"player_id": 2, "steam_id64": str(STEAM64_BASE + 20)},
         {"player_id": 3, "steam_id64": str(STEAM64_BASE + 30)}],
    )


def report():
    return {
        "players": [
            {"player_id": 7, "steam_id": "0:5",
             "player_name_at_match": "-Nt- e`man"},
            {"player_id": 8, "steam_id": "0:10",
             "player_name_at_match": "dicE[: :]Gorilla"},
            {"player_id": 9, "steam_id": "0:999",
             "player_name_at_match": "stranger"},
        ],
        "duel_matrix": {"cells": [
            {"killer_name": "-Nt- e`man", "victim_name": "stranger"}]},
        "assists": [{"player_id": 7, "player_name_at_match": "-Nt- e`man",
                     "victim_name_at_match": "dicE[: :]Gorilla"}],
        "shadow_timelines": {"trades": [
            {"trader": {"player_id": 8, "name": "dicE[: :]Gorilla"}}]},
        "spatial_layers": {"layers": {"frag_vectors": {"vectors": [
            {"attacker": {"name": "-Nt- e`man"},
             "victim": {"name": "stranger"}}]}}},
        "match": {"map_name": "dod_anzio"},
    }


class SteamIds(unittest.TestCase):
    def test_converts_to_hlstats_form(self):
        self.assertEqual(steam64_to_hlstats(STEAM64_BASE + 10), "0:5")
        self.assertEqual(steam64_to_hlstats(str(STEAM64_BASE + 11)), "1:5")

    def test_unparseable_is_none_not_a_wrong_match(self):
        for bad in ("nonsense", None, "", STEAM64_BASE - 1):
            self.assertIsNone(steam64_to_hlstats(bad))

    def test_alt_accounts_collapse_and_blank_alias_is_dropped(self):
        self.assertEqual(index(),
                         {"0:5": "eman", "1:5": "eman", "0:10": "GorillaBC"})


class ApplyAliases(unittest.TestCase):
    def test_roster_names_become_website_aliases(self):
        r = report()
        stats = apply_aliases(r, index())
        self.assertEqual([p["player_name_at_match"] for p in r["players"]],
                         ["eman", "GorillaBC", "stranger"])
        self.assertEqual(stats["resolved"], 2)
        self.assertEqual(stats["roster"], 3)

    def test_player_without_website_account_keeps_played_name(self):
        r = report()
        stats = apply_aliases(r, index())
        self.assertEqual(r["players"][2]["player_name_at_match"], "stranger")
        self.assertEqual(stats["unresolved"], ["stranger"])

    def test_name_only_sites_resolve_through_the_roster(self):
        r = report()
        apply_aliases(r, index())
        cell = r["duel_matrix"]["cells"][0]
        self.assertEqual(cell["killer_name"], "eman")
        self.assertEqual(cell["victim_name"], "stranger")
        vec = r["spatial_layers"]["layers"]["frag_vectors"]["vectors"][0]
        self.assertEqual(vec["attacker"]["name"], "eman")
        self.assertEqual(vec["victim"]["name"], "stranger")

    def test_row_id_does_not_rewrite_the_other_player_beside_it(self):
        r = report()
        apply_aliases(r, index())
        self.assertEqual(r["assists"][0]["player_name_at_match"], "eman")
        self.assertEqual(r["assists"][0]["victim_name_at_match"], "GorillaBC")

    def test_actor_blocks_resolve_by_id(self):
        r = report()
        apply_aliases(r, index())
        self.assertEqual(
            r["shadow_timelines"]["trades"][0]["trader"]["name"], "GorillaBC")

    def test_non_player_fields_untouched(self):
        r = report()
        apply_aliases(r, index())
        self.assertEqual(r["match"]["map_name"], "dod_anzio")

    def test_empty_index_leaves_the_report_alone(self):
        r = report()
        stats = apply_aliases(r, {})
        self.assertEqual(stats["rewritten"], 0)
        self.assertEqual(r["players"][0]["player_name_at_match"], "-Nt- e`man")


class SharedName(unittest.TestCase):
    """Two players under one name: the name no longer identifies either."""

    def setUp(self):
        self.report = {
            "players": [
                {"player_id": 7, "steam_id": "0:5",
                 "player_name_at_match": "ringer"},
                {"player_id": 8, "steam_id": "0:10",
                 "player_name_at_match": "ringer"},
            ],
            "duel_matrix": {"cells": [{"killer_name": "ringer"}]},
        }
        self.stats = apply_aliases(self.report, index())

    def test_flagged_and_left_as_played(self):
        self.assertEqual(self.stats["ambiguous_names"], ["ringer"])
        self.assertEqual(
            self.report["duel_matrix"]["cells"][0]["killer_name"], "ringer")

    def test_their_own_rows_still_resolve_by_id(self):
        self.assertEqual(
            [p["player_name_at_match"] for p in self.report["players"]],
            ["eman", "GorillaBC"])


if __name__ == "__main__":
    unittest.main()
