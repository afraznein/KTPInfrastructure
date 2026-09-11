"""Offline tests for scripts/report_service.py (no DB, no server).

Pure-logic tests always run. The corpus test runs only when
KTP_REPORT_SPECIMENS points at a directory of report-*.json files
(e.g. artifacts/real-match-tier2-20260906/prod-reports on the analysis box).
"""
import json
import os
import unittest
from pathlib import Path

from unittest import mock

from scripts import report_service
from scripts.report_service import (
    OFFICIAL_MATCH_TYPES, build_aggregates, excluded_by_match_type,
    is_publishable, latest_publishable_reports, pending_match_ids, sql_str)

SPECIMENS = os.environ.get("KTP_REPORT_SPECIMENS")


class AggregateSinceFloor(unittest.TestCase):
    """A publishable pre-season report must not be pooled into the season."""

    FLOOR = "2026-09-13"

    def _db(self):
        rows = [("2026-09-09 20:54:06", "pre"), ("2026-09-13 00:00:00", "on"),
                ("2026-09-14 21:00:00", "after"), ("NULL", "orphan")]
        body = "\n".join(f"{s}\t" + json.dumps({"match_id": m})
                         for s, m in rows)
        return FakeDb(response="match_start\treport\n" + body + "\n")

    def test_pre_floor_and_orphan_reports_are_not_pooled(self):
        got = [r["match_id"] for r in latest_publishable_reports(self._db(),
                                                                 self.FLOOR)]
        self.assertEqual(got, ["on", "after"])

    def test_query_reads_the_same_column_generate_does(self):
        db = self._db()
        latest_publishable_reports(db, self.FLOOR)
        self.assertIn("m.start_time", db.queries[0])

    def test_aggregate_without_a_floor_refuses_to_run(self):
        def must_not_run(args):
            raise AssertionError("aggregated without a floor")

        with mock.patch.object(report_service, "cmd_aggregate", must_not_run):
            with self.assertRaises(SystemExit) as ctx:
                report_service.main(["--repo", ".", "aggregate"])
        self.assertEqual(ctx.exception.code, 2)

    def test_aggregate_passes_its_floor_through(self):
        seen = []
        with mock.patch.object(report_service, "cmd_aggregate",
                               lambda args: seen.append(args.since) or 0):
            report_service.main(["--repo", ".", "aggregate",
                                 "--since", self.FLOOR])
        self.assertEqual(seen, [self.FLOOR])


def check(level, code):
    return {"level": level, "code": code, "message": "", "evidence": {}}


class FakeDb:
    """Duck-types LocalMysql.sql() to capture the query without a server."""

    def __init__(self, response="match_id\n1.3-1-X\n"):
        self.queries = []
        self.response = response

    def sql(self, query):
        self.queries.append(query)
        return self.response


class PendingMatchIdsSince(unittest.TestCase):
    def test_no_since_omits_clause(self):
        db = FakeDb()
        pending_match_ids(db, 8)
        self.assertNotIn("start_time", db.queries[0])

    def test_since_date_only(self):
        db = FakeDb()
        pending_match_ids(db, 8, "2026-09-13")
        self.assertIn("m.start_time >= '2026-09-13'", db.queries[0])

    def test_since_datetime(self):
        db = FakeDb()
        pending_match_ids(db, 8, "2026-09-13 00:00:00")
        self.assertIn("m.start_time >= '2026-09-13 00:00:00'", db.queries[0])

    def test_since_rejects_non_date_shape(self):
        db = FakeDb()
        for bad in ("2026-09-13'; DROP TABLE ktp_matches; --",
                   "not-a-date", "2026/09/13", ""):
            with self.assertRaises(ValueError):
                pending_match_ids(db, 8, bad)


class OfficialMatchTypeFilter(unittest.TestCase):
    """The operator's .ktp-only ruling. KTPMatchHandler.sma spells the same
    set as is_official_match_type(): COMPETITIVE (0) and KTP_OT (4)."""

    def test_set_is_competitive_and_ktp_ot(self):
        self.assertEqual(OFFICIAL_MATCH_TYPES, (0, 4))

    def test_filter_is_in_the_pending_query(self):
        db = FakeDb()
        pending_match_ids(db, 8)
        self.assertIn("m.match_type IN (0, 4)", db.queries[0])

    def test_filter_survives_since(self):
        db = FakeDb()
        pending_match_ids(db, 8, "2026-09-13")
        self.assertIn("m.match_type IN (0, 4)", db.queries[0])
        self.assertIn("m.start_time >= '2026-09-13'", db.queries[0])

    def test_scrim_and_12man_are_not_official(self):
        for t in (1, 2, 3, 5):
            self.assertNotIn(t, OFFICIAL_MATCH_TYPES)

    def test_exclusion_report_is_the_complement(self):
        db = FakeDb("\t".join(("mt", "n")) + "\n")
        excluded_by_match_type(db, 8)
        q = db.queries[0]
        self.assertIn("m.match_type IS NULL OR m.match_type NOT IN (0, 4)", q)

    def test_exclusion_report_parses_counts(self):
        rows = "\t".join(("mt", "n")) + "\n" + "\n".join(
            "\t".join(r) for r in (("1", "68"), ("2", "145"), ("NULL", "3")))
        self.assertEqual(excluded_by_match_type(FakeDb(rows), 8),
                         {"scrim": 68, "12man": 145, "unset": 3})

    def test_exclusion_report_empty_when_nothing_dropped(self):
        header = "\t".join(("mt", "n")) + "\n"
        self.assertEqual(excluded_by_match_type(FakeDb(header), 8), {})

    def test_exclusion_report_validates_since(self):
        with self.assertRaises(ValueError):
            excluded_by_match_type(FakeDb(), 8, "not-a-date")


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

    def test_season_positional_pools_exactly(self):
        def rep(mapname, n, mean, sd, ka, kl, da, dl):
            r = self._report(mapname, [])
            r["shadow_explorations"]["map_control"] = {
                "status": "available", "definition_version": 1, "mean_control_team1": 0.6}
            r["shadow_explorations"]["depth_profiles"] = {
                "status": "available", "players": [{
                    "player_id": 1, "player_name_at_match": "One", "team": 1, "samples": n,
                    "mean_depth": mean, "depth_sd": sd, "lateral_mean": 100.0,
                    "depth_sum": mean * n, "depth_sum_sq": (sd * sd + mean * mean) * n,
                    "lateral_sum": 100.0 * n}]}
            r["shadow_explorations"]["overextension"] = {
                "status": "available", "players": [{
                    "player_id": 1, "player_name_at_match": "One", "team": 1,
                    "kills_located": kl, "kills_ahead": ka,
                    "deaths_located": dl, "deaths_ahead": da}]}
            return r
        reps = [rep("dod_anzio", 150, 0.4, 0.1, 5, 10, 8, 20),
                rep("dod_anzio", 150, 0.6, 0.1, 5, 10, 2, 20)]
        sp = build_aggregates(reps)["season_positional"]
        self.assertTrue(sp["provisional"])
        self.assertEqual(sp["matches_with_positions"], 2)
        self.assertEqual(sp["map_control"], [{"map": "dod_anzio", "matches": 2,
                                              "mean_control_team1": 0.6}])
        prof = sp["depth_profiles"][0]
        self.assertEqual((prof["map"], prof["name"], prof["samples"]), ("dod_anzio", "One", 300))
        self.assertAlmostEqual(prof["mean_depth"], 0.5, 4)
        # pooled sd: within .1 plus between-match spread .1 -> sqrt(.01+.01)
        self.assertAlmostEqual(prof["depth_sd"], (0.02) ** 0.5, 3)
        ov = sp["overextension"][0]
        self.assertEqual(ov["name"], "One")
        self.assertEqual(ov["kill_ahead_rate"], 0.5)
        self.assertEqual(ov["death_ahead_rate"], 0.25)
        self.assertEqual(ov["net_ahead"], 0.25)
        self.assertNotIn("player_id", json.dumps(sp))

    def test_season_positional_thresholds(self):
        r = self._report("dod_anzio", [])
        r["shadow_explorations"]["overextension"] = {"status": "available", "players": [{
            "player_id": 1, "player_name_at_match": "One", "team": 1,
            "kills_located": 3, "kills_ahead": 1, "deaths_located": 5, "deaths_ahead": 1}]}
        r["shadow_explorations"]["depth_profiles"] = {"status": "unavailable", "players": []}
        sp = build_aggregates([r])["season_positional"]
        self.assertEqual(sp["overextension"], [])   # < 30 located deaths
        self.assertEqual(sp["depth_profiles"], [])
        self.assertEqual(sp["matches_with_positions"], 0)

    def test_season_spatial_pools_and_rethresholds(self):
        def cell(col, row, t1, t2):
            return {"col": col, "row": row, "samples": t1 + t2, "seconds": 2.0 * (t1 + t2),
                    "team1_samples": t1, "team2_samples": t2,
                    "control": (t1 - t2) / (t1 + t2)}

        def rep(t1, t2, lane_count):
            r = self._report("dod_anzio", [])
            r["spatial_layers"] = {
                "status": "available", "definition_version": 1,
                "parameters": {"sample_seconds": 2.0, "grid_size": 256.0},
                "flags": [{"flag_index": 0, "flag_name": "L", "x": 0.0, "y": 0.0, "col": 0, "row": 0}],
                "layers": {
                    "occupancy": {"cells": [cell(0, 0, t1, t2), cell(5, 5, 8, 0)]},
                    "kill_hotspots": {"cells": [{"col": 0, "row": 0, "kills": 2}]},
                    "death_hotspots": {"cells": []},
                    "recurring_lanes": {"vectors": [{
                        "origin": {"col": 0, "row": 0, "x": 128.0, "y": 128.0},
                        "destination": {"col": 1, "row": 0, "x": 384.0, "y": 128.0},
                        "count": lane_count, "mean_distance": 256.0,
                        "mean_angle_degrees": 0.0, "headshot_rate": 0.5}]},
                }}
            return r

        # cell (0,0): 20 + 12 = 32 samples = 64 s >= 60 s corpus floor -> kept;
        # cell (5,5): 8 + 8 = 16 samples = 32 s -> dropped at season level.
        ss = build_aggregates([rep(12, 8, 3), rep(8, 4, 4)])["season_spatial"]
        self.assertTrue(ss["provisional"])
        self.assertEqual(ss["corpus_cell_minimum_seconds"], 60.0)
        m = ss["maps"][0]
        self.assertEqual((m["map"], m["matches"]), ("dod_anzio", 2))
        self.assertEqual(m["occupancy"], [{"col": 0, "row": 0, "samples": 32, "seconds": 64.0,
                                           "team1_samples": 20, "team2_samples": 12,
                                           "control": 0.25}])
        self.assertEqual(m["kill_hotspots"], [{"col": 0, "row": 0, "kills": 4}])
        lane = m["recurring_lanes"][0]
        self.assertEqual((lane["count"], lane["mean_distance"], lane["headshot_rate"]), (7, 256.0, 0.5))
        self.assertEqual(m["lattice"]["columns"], 2)
        self.assertEqual(m["flags"][0]["flag_name"], "L")
        self.assertNotIn("player", json.dumps(ss))

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
        # The corpus grows nightly; the board is everyone with >= min matches.
        counts = {}
        for r in reports:
            for p in r["shadow_explorations"]["ktpr_v2"]["players"]:
                counts[p["player_id"]] = counts.get(p["player_id"], 0) + 1
        expected = sum(1 for n in counts.values() if n >= lb["min_matches"])
        self.assertEqual(len(lb["players"]), expected)
        self.assertGreaterEqual(len(lb["players"]), 100)
        self.assertTrue(all(p["name"] for p in lb["players"]))
        body = json.dumps(aggs)
        self.assertNotIn("player_id", body)
        self.assertNotIn("Â¬", body)
