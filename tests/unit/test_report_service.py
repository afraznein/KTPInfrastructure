"""Offline tests for scripts/report_service.py (no DB, no server).

Pure-logic tests always run. The corpus test runs only when
KTP_REPORT_SPECIMENS points at a directory of report-*.json files
(e.g. artifacts/real-match-tier2-20260906/prod-reports on the analysis box).
"""
import json
import os
import unittest
from pathlib import Path

from scripts.report_service import build_aggregates, is_publishable, sql_str

SPECIMENS = os.environ.get("KTP_REPORT_SPECIMENS")


def check(level, code):
    return {"level": level, "code": code, "message": "", "evidence": {}}


class PublishableGate(unittest.TestCase):
    def test_all_pass(self):
        self.assertTrue(is_publishable(
            {"quality": {"checks": [check("PASS", "x"), check("WARN", "y")]}}))

    def test_cosmetic_match_id_shape_fail_is_publishable(self):
        self.assertTrue(is_publishable(
            {"quality": {"checks": [check("FAIL", "match_id_shape"),
                                    check("PASS", "x")]}}))

    def test_hard_fail_blocks(self):
        self.assertFalse(is_publishable(
            {"quality": {"checks": [check("FAIL", "match_id_shape"),
                                    check("FAIL", "frag_reconciliation")]}}))

    def test_no_checks_is_publishable(self):
        # Empty checks means nothing failed; source_coverage gates elsewhere.
        self.assertTrue(is_publishable({"quality": {"checks": []}}))
        self.assertTrue(is_publishable({}))


class SqlStr(unittest.TestCase):
    def test_utf8_round_trip(self):
        name = "100％JESUS dicE[: :]Gorilla[bc] ünïcøde ' \" ; --"
        hexpart = sql_str(name).split("'")[1]
        self.assertEqual(bytes.fromhex(hexpart).decode("utf-8"), name)

    def test_only_hex_inside_literal(self):
        literal = sql_str("a'b--")
        inner = literal.split("'")[1]
        self.assertTrue(all(c in "0123456789abcdef" for c in inner))


class AggregatesSynthetic(unittest.TestCase):
    def _report(self, mapname, cells, ktpr_players=None):
        return {
            "schema_version": 7,
            "match": {"map_name": mapname},
            "players": [{"kills": 10}, {"kills": 5}],
            "duel_matrix": {"cells": cells},
            "shadow_timelines": {
                "trades": [{}] * 3,
                "fast_multikills": [{}] * 2,
                "trade_analysis": {"teams": [
                    {"team": 1, "team_death_response_rate": 0.22},
                    {"team": 2, "team_death_response_rate": 0.24}]},
            },
            "shadow_explorations": {
                "recap_speed": {"teams": [
                    {"team": 1, "recaps": 4, "median_seconds": 60.0}]},
                "ktpr_v2": {"definition_version": 1,
                            "players": ktpr_players or []},
            },
        }

    def test_map_profiles(self):
        aggs = build_aggregates([self._report("dod_anzio", [])])
        m = aggs["map_profiles"]["maps"][0]
        self.assertEqual(m["map"], "dod_anzio")
        self.assertEqual(m["kills_per_match"], 15.0)
        self.assertEqual(aggs["map_profiles"]["source_report_count"], 1)
        self.assertEqual(aggs["map_profiles"]["report_schema_version"], 7)

    def test_head_to_head_named_symmetric_thresholded(self):
        cell = {"killer_id": 2, "killer_name": "Bee", "victim_id": 1,
                "victim_name": "Ay", "kills": 25, "cross_team": True}
        rev = {"killer_id": 1, "killer_name": "Ay", "victim_id": 2,
               "victim_name": "Bee", "kills": 20, "cross_team": True}
        same_team = {"killer_id": 3, "killer_name": "C", "victim_id": 4,
                     "victim_name": "D", "kills": 99, "cross_team": False}
        aggs = build_aggregates(
            [self._report("dod_anzio", [cell, rev, same_team])])
        pairs = aggs["head_to_head"]["pairs"]
        self.assertEqual(len(pairs), 1)  # same-team excluded, >=40 met
        p = pairs[0]
        self.assertEqual((p["player_a"], p["player_b"]), ("Ay", "Bee"))
        self.assertEqual(p["kills_a_over_b"], 20)
        self.assertEqual(p["kills_b_over_a"], 25)
        self.assertEqual(p["matches"], 1)
        self.assertNotIn("player_id_a", p)

    def test_leaderboard_provisional_named_min_matches(self):
        rows = [{"player_id": 1, "team": 1, "rating": 1.0,
                 "player_name_at_match": "One"},
                {"player_id": 2, "team": 2, "rating": -1.0,
                 "player_name_at_match": "Two"}]
        reps = [self._report("dod_anzio", [], rows) for _ in range(3)]
        reps.append(self._report("dod_anzio", [], [
            {"player_id": 3, "team": 1, "rating": 0.5,
             "player_name_at_match": "Three"},
            {"player_id": 4, "team": 2, "rating": -0.5,
             "player_name_at_match": "Four"}]))
        lb = build_aggregates(reps)["leaderboard_ktpr_v22"]
        self.assertTrue(lb["provisional"])
        self.assertEqual(lb["method_version"], "ktpr_v2.2")
        self.assertEqual(lb["definition_versions"], [1])
        names = [p["name"] for p in lb["players"]]
        self.assertEqual(names, ["One", "Two"])  # 3-match players only
        self.assertTrue(all("player_id" not in p for p in lb["players"]))
        self.assertTrue(all(p["se"] >= 0 for p in lb["players"]))


@unittest.skipUnless(SPECIMENS and Path(SPECIMENS).is_dir(),
                     "KTP_REPORT_SPECIMENS not set")
class AggregatesCorpus(unittest.TestCase):
    def test_real_corpus(self):
        reports = [json.loads(p.read_text(encoding="utf-8"))
                   for p in sorted(Path(SPECIMENS).glob("report-*.json"))]
        self.assertTrue(reports)
        self.assertTrue(all(is_publishable(r) for r in reports))
        aggs = build_aggregates(reports)
        rates = [m["trade_response_rate_mean"]
                 for m in aggs["map_profiles"]["maps"]
                 if m["trade_response_rate_mean"] is not None
                 and m["matches"] >= 3]
        self.assertTrue(rates)
        self.assertTrue(all(0.10 < x < 0.40 for x in rates), rates)
        pairs = aggs["head_to_head"]["pairs"]
        self.assertTrue(pairs and pairs[0]["total_kills"] >= 40)
        self.assertTrue(pairs[0]["player_a"] and pairs[0]["player_b"])
        lb = aggs["leaderboard_ktpr_v22"]
        self.assertEqual(len(lb["players"]), 102)
        self.assertTrue(all(p["name"] for p in lb["players"]))
        body = json.dumps(aggs)
        self.assertNotIn("player_id", body)
        self.assertNotIn("Â¬", body)
