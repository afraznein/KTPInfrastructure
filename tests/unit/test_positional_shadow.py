"""positional_shadow: geometry, orientation, frontline, overextension on a
synthetic lane; fail-closed envelopes; and, when the feed cache + corpus are
present, exact reproduction of the analytics lane's prototype curve for
1.3-6736-ATL1 (KTP_REPORT_SPECIMENS set, feedcache beside prod-reports)."""
import json
import os
import unittest
from pathlib import Path

from scripts.positional_shadow import (
    DEFINITION_VERSION, PositionalConfig, build_positional_shadow, project)

SPECIMENS = os.environ.get("KTP_REPORT_SPECIMENS")

FLAGS = [{"flag_index": i, "flag_name": f"f{i}", "origin_x": 1000.0 * i, "origin_y": 0.0}
         for i in range(5)]
PLAYERS = [{"player_id": pid, "player_name_at_match": f"p{pid}", "team": 1 if pid < 7 else 2}
           for pid in range(1, 13)]


def samples(half, seconds, team1_x, team2_x, per_team=6):
    """Both teams sampled every 2 s for `seconds`; each team at a fixed x."""
    rows = []
    t = 0.0
    while t <= seconds:
        for k in range(per_team):
            rows.append({"player_id": 1 + k, "team": 1, "half": half,
                         "pos_x": team1_x, "pos_y": 10.0 * k, "game_time": t})
            rows.append({"player_id": 7 + k, "team": 2, "half": half,
                         "pos_x": team2_x, "pos_y": 10.0 * k, "game_time": t})
        t += 2.0
    return rows


class Geometry(unittest.TestCase):
    def test_project_endpoints_and_lateral(self):
        poly = [(0.0, 0.0), (4000.0, 0.0)]
        self.assertEqual(project(poly, -5.0, 0.0), (0.0, 5.0))
        arc, lat = project(poly, 1000.0, 30.0)
        self.assertAlmostEqual(arc, 0.25)
        self.assertAlmostEqual(lat, 30.0)
        self.assertEqual(project(poly, 9000.0, 0.0)[0], 1.0)


class FailClosed(unittest.TestCase):
    def test_replay_suppressed(self):
        out = build_positional_shadow([], FLAGS, [], PLAYERS, temporal_valid=False)
        for block in out.values():
            self.assertEqual(block["status"], "timed_metrics_suppressed")
            self.assertEqual(block["definition_version"], DEFINITION_VERSION)
            self.assertEqual(block["visibility"], "private_shadow_only")

    def test_missing_sources(self):
        out = build_positional_shadow(None, FLAGS, None, PLAYERS, source_available=False)
        self.assertTrue(all(b["status"] == "unavailable" for b in out.values()))
        out = build_positional_shadow([], [FLAGS[0]], None, PLAYERS)
        self.assertTrue(all(b["status"] == "unavailable" for b in out.values()))

    def test_too_few_samples(self):
        out = build_positional_shadow(samples(1, 10, 500.0, 3500.0), FLAGS, [], PLAYERS)
        self.assertTrue(all(b["status"] == "insufficient_samples" for b in out.values()))
        self.assertEqual(out["depth_profiles"]["players"], [])


class Synthetic(unittest.TestCase):
    def setUp(self):
        cfg = PositionalConfig(min_position_samples=100)
        # Half 1: team 1 sits at x=500 (arc .125), team 2 at x=3500 (arc .875).
        # Half 2: sides swap.
        rows = samples(1, 120, 500.0, 3500.0) + samples(2, 120, 3500.0, 500.0)
        frags = [
            # team-1 killer deep in enemy half (ahead), victim near own base
            {"producer_half": 1, "game_time": 40.0, "killer_id": 1, "killer_team": 1,
             "killer_pos_x": 3000.0, "killer_pos_y": 0.0, "victim_id": 7, "victim_team": 2,
             "victim_pos_x": 3800.0, "victim_pos_y": 0.0},
            # no position context: must not count anywhere
            {"producer_half": 1, "game_time": 44.0, "killer_id": 2, "killer_team": 1,
             "killer_pos_x": None, "killer_pos_y": None, "victim_id": 8, "victim_team": 2,
             "victim_pos_x": None, "victim_pos_y": None},
            # outside any resolved bin (half 3): excluded from the denominator
            {"producer_half": 3, "game_time": 40.0, "killer_id": 1, "killer_team": 1,
             "killer_pos_x": 3000.0, "killer_pos_y": 0.0, "victim_id": 7, "victim_team": 2,
             "victim_pos_x": 100.0, "victim_pos_y": 0.0},
        ]
        self.out = build_positional_shadow(rows, FLAGS, frags, PLAYERS, cfg)

    def test_orientation_swaps_and_depth_is_side_normalized(self):
        mc = self.out["map_control"]
        self.assertEqual(mc["status"], "available")
        self.assertEqual(mc["orientation_by_half"], {"1": "team1_at_arc0", "2": "team2_at_arc0"})
        # Both halves: team 1 depth .125 (75th pct .125), team 2 depth .125
        # mirrored -> frontline (0.125 + 0.875)/2 = 0.5 every bin.
        for half in ("1", "2"):
            self.assertTrue(all(abs(f - 0.5) < 1e-9 for _, f in mc["halves"][half]))
        self.assertAlmostEqual(mc["mean_control_team1"], 0.5)
        self.assertEqual(mc["bins"]["censored"], 0)
        by = {p["player_id"]: p for p in self.out["depth_profiles"]["players"]}
        self.assertAlmostEqual(by[1]["mean_depth"], 0.125, 3)   # own end both halves
        self.assertAlmostEqual(by[7]["mean_depth"], 0.125, 3)
        self.assertAlmostEqual(by[1]["depth_sd"], 0.0, 3)
        self.assertEqual(by[1]["player_name_at_match"], "p1")

    def test_overextension_counts_only_located_frags_in_resolved_bins(self):
        ov = self.out["overextension"]
        self.assertEqual(ov["status"], "available")
        self.assertEqual(ov["frags"], {"total": 3, "with_context": 2, "in_resolved_bins": 1})
        by = {p["player_id"]: p for p in ov["players"]}
        self.assertEqual(by[1]["kills_located"], 1)
        self.assertEqual(by[1]["kills_ahead"], 1)      # depth .75 > frontline .5 + .05
        self.assertEqual(by[1]["kill_ahead_rate"], 1.0)
        self.assertEqual(by[7]["deaths_located"], 1)
        self.assertEqual(by[7]["deaths_ahead"], 0)     # depth .05 (own base)
        self.assertEqual(by[7]["death_ahead_rate"], 0.0)
        self.assertNotIn(2, by)


class DepthUnit(unittest.TestCase):
    """mean_depth is a clamped lane fraction, never a coordinate: players far
    behind their own flag read 0 and players far past the enemy flag read 1."""

    def test_depth_stays_inside_zero_one(self):
        rows = []
        for step in range(300):
            t = 2.0 * step
            deep = t >= 30.0  # after the orientation window team 1 runs past the far flag
            for k in range(6):
                rows.append({"player_id": 1 + k, "team": 1, "half": 1,
                             "pos_x": 12000.0 if deep else -3000.0,
                             "pos_y": 10.0 * k, "game_time": t})
                rows.append({"player_id": 7 + k, "team": 2, "half": 1,
                             "pos_x": 9000.0, "pos_y": 10.0 * k, "game_time": t})
        out = build_positional_shadow(rows, FLAGS, [], PLAYERS,
                                      PositionalConfig(min_position_samples=100))
        players = out["depth_profiles"]["players"]
        self.assertEqual(len(players), 12)
        for p in players:
            self.assertGreaterEqual(p["mean_depth"], 0.0)
            self.assertLessEqual(p["mean_depth"], 1.0)
            self.assertLessEqual(p["depth_sd"], 0.5)
        by = {p["player_id"]: p for p in players}
        self.assertEqual(by[7]["mean_depth"], 0.0)       # past their own end: clamped
        self.assertGreater(by[1]["mean_depth"], 0.9)     # past the enemy end: near 1
        self.assertLessEqual(by[1]["mean_depth"], 1.0)


@unittest.skipUnless(SPECIMENS and Path(SPECIMENS).is_dir(), "KTP_REPORT_SPECIMENS not set")
class PrototypeReproduction(unittest.TestCase):
    """Rebuild 1.3-6736-ATL1 from the cached feeds and compare with the
    prototype's positional_metrics.json (curve, profiles, overextension)."""

    def test_curve_and_overextension_match_prototype(self):
        import sys
        art = Path(SPECIMENS).parent
        proto_path = art / "positional_metrics.json"
        cache = art / "feedcache"
        if not (proto_path.exists() and cache.is_dir()):
            self.skipTest("prototype output or feed cache missing")
        sys.path.insert(0, str(art))
        from run_production_report import SshMysql  # cache-backed db
        from scripts import match_analytics as ma
        db = SshMysql(cache_dir=cache)
        mid = "1.3-6736-ATL1"
        report = json.loads((Path(SPECIMENS) / f"report-{mid}.json").read_text(encoding="utf-8"))
        out = build_positional_shadow(
            ma.query_rows(db, "position_sample_fact.sql", mid),
            ma.query_rows(db, "flag_position_fact.sql", mid),
            ma.query_rows(db, "frag_context_fact.sql", mid),
            report["players"])
        proto = json.loads(proto_path.read_text(encoding="utf-8"))
        mine = out["map_control"]["halves"]
        ref = proto["control_curves"][mid]["halves"]
        for half in ref:
            self.assertEqual([tuple(p) for p in mine[half]], [tuple(p) for p in ref[half]])
        # Per-match overextension is a subset of the prototype's corpus totals:
        # every located frag counted here must be <= the corpus count.
        corpus = proto["overextension"]
        for p in out["overextension"]["players"]:
            c = corpus.get(str(p["player_id"]))
            if c:
                self.assertLessEqual(p["deaths_located"], c["deaths"])
                self.assertLessEqual(p["kills_located"], c["kills"])


class ReportTeamSpace(unittest.TestCase):
    """The frag feed's team is a REPORT team; depth is engine-side geometry.

    Half 1 is the swapped half (report team 1 played engine side 2); half 2 is
    the terminal half, where the conventions agree by construction and nothing
    may move. Same rows, same geometry -- only the space of the label changes.
    """

    # Half 1: engine side 1 at x=500 (arc .125), side 2 at x=3500 (arc .875).
    # Half 2: those positions swap, so `orient` flips with them.
    ROWS = samples(1, 120, 500.0, 3500.0) + samples(2, 120, 3500.0, 500.0)
    SWAP = {1: 2, 2: 1}
    CFG = PositionalConfig(min_position_samples=100)

    @staticmethod
    def frag(half, x):
        # A report-team-1 killer. Victim carries no position, so only the kill
        # side of the row counts and the assertion stays one-dimensional.
        return {"producer_half": half, "game_time": 40.0,
                "killer_id": 1, "killer_team": 1,
                "killer_pos_x": x, "killer_pos_y": 0.0,
                "victim_id": 7, "victim_team": 2,
                "victim_pos_x": None, "victim_pos_y": None}

    def over(self, frags, team1_engine_side):
        out = build_positional_shadow(
            self.ROWS, FLAGS, frags, PLAYERS, self.CFG,
            team1_engine_side=team1_engine_side)
        self.assertEqual(out["overextension"]["status"], "available")
        rows = out["overextension"]["players"]
        return {r["player_id"]: r for r in rows}

    def test_a_swapped_half_kill_in_his_own_end_is_not_ahead(self):
        # x=3000 is arc .75. Report team 1 played engine side 2 in half 1, and
        # side 2's own end that half is arc 1 -- so this kill is BEHIND the
        # frontline. Read as engine side 1 it looks deep in enemy territory.
        frags = [self.frag(1, 3000.0)]
        raw = self.over(frags, None)
        fixed = self.over(frags, self.SWAP)
        self.assertEqual(raw[1]["kills_located"], 1)
        self.assertEqual(raw[1]["kills_ahead"], 1, "untranslated: wrong end")
        self.assertEqual(fixed[1]["kills_located"], 1, "the row does not vanish")
        self.assertEqual(fixed[1]["kills_ahead"], 0)

    def test_the_terminal_half_does_not_move(self):
        # The built-in control: in half 2 report team 1 IS engine side 1, so
        # the translation is the identity and the number must be untouched.
        frags = [self.frag(2, 500.0)]
        raw = self.over(frags, None)
        fixed = self.over(frags, self.SWAP)
        self.assertEqual(raw[1]["kills_ahead"], 1)
        self.assertEqual(fixed[1]["kills_ahead"], 1)
        self.assertEqual(raw[1], fixed[1], "byte-identical in the terminal half")

    def test_no_row_is_lost_to_the_translation(self):
        # Unlike the frag-feed defects, this one never dropped a row -- it got
        # the value wrong. A fix that silently shrank the denominator would be
        # a different bug, so the count is pinned on both sides.
        frags = [self.frag(1, 3000.0), self.frag(1, 500.0),
                 self.frag(2, 500.0), self.frag(2, 3000.0)]
        raw = self.over(frags, None)
        fixed = self.over(frags, self.SWAP)
        self.assertEqual(raw[1]["kills_located"], 4)
        self.assertEqual(fixed[1]["kills_located"], 4)

    def test_an_unresolvable_half_drops_the_frag_rather_than_guessing(self):
        # No side for half 1: translating is impossible, and counting it under
        # either end would be a confident wrong answer. With nothing left to
        # measure the block fails closed rather than publishing an empty rate.
        out = build_positional_shadow(
            self.ROWS, FLAGS, [self.frag(1, 3000.0)], PLAYERS, self.CFG,
            team1_engine_side={2: 1})
        self.assertEqual(out["overextension"]["status"], "insufficient_samples")
        self.assertEqual(out["overextension"]["players"], [])

    def test_an_empty_side_map_fails_closed_rather_than_falling_back(self):
        # The distinction is `is not None`, not truthiness: {} means the life
        # feed resolved nothing, and silently reverting to the raw label there
        # is the defect. Passing nothing at all is the standalone caller.
        empty = build_positional_shadow(
            self.ROWS, FLAGS, [self.frag(1, 3000.0)], PLAYERS, self.CFG,
            team1_engine_side={})
        self.assertEqual(empty["overextension"]["players"], [])
        absent = self.over([self.frag(1, 3000.0)], None)
        self.assertEqual(absent[1]["kills_ahead"], 1, "legacy caller unchanged")

    def test_the_sample_fed_blocks_are_untouched_by_the_frag_space(self):
        # map_control and depth_profiles come from the sample feed, where every
        # row carries its own side. The fix must not reach them.
        frags = [self.frag(1, 3000.0)]
        raw = build_positional_shadow(self.ROWS, FLAGS, frags, PLAYERS, self.CFG)
        fixed = build_positional_shadow(self.ROWS, FLAGS, frags, PLAYERS, self.CFG,
                                        team1_engine_side=self.SWAP)
        self.assertEqual(raw["map_control"], fixed["map_control"])
        self.assertEqual(raw["depth_profiles"], fixed["depth_profiles"])
