"""spatial_layers v2: lattice indexing (128-unit cells, 256-unit lanes),
occupancy censoring, control sign, hotspot/lane contributor floors, flags,
per-half and windowed occupancy, public/private kill paths, fail-closed
envelopes, and a corpus smoke against the cached real match
(KTP_REPORT_SPECIMENS set, feedcache beside prod-reports)."""
import json
import os
import unittest
from pathlib import Path

from scripts.spatial_layers import (
    DEFINITION_VERSION, LATTICE_SCHEME, SpatialLayersConfig, build_spatial_layers,
    cell_center, cell_index)

SPECIMENS = os.environ.get("KTP_REPORT_SPECIMENS")
FLAGS = [{"flag_index": 0, "flag_name": "Laundry", "origin_x": -1495.0, "origin_y": -326.0},
         {"flag_index": 1, "flag_name": "Plaza", "origin_x": -698.0, "origin_y": 923.0}]
PLAYERS = [{"player_id": pid, "player_name_at_match": f"p{pid}", "team": 1 if pid < 7 else 2}
           for pid in range(1, 13)]


def samples(n, x, y, team, pid=1, alive=1, half=1, t0=0.0):
    return [{"player_id": pid, "team": team, "half": half, "pos_x": x, "pos_y": y,
             "is_alive": alive, "game_time": t0 + 2.0 * i} for i in range(n)]


def frag(kid, vid, kx, ky, vx, vy, half=1, headshot=0, t=10.0):
    return {"half": half, "game_time": t, "killer_id": kid, "victim_id": vid,
            "killer_name": f"p{kid}", "victim_name": f"p{vid}",
            "killer_team": 1 if kid < 7 else 2, "victim_team": 1 if vid < 7 else 2,
            "killer_pos_x": kx, "killer_pos_y": ky, "victim_pos_x": vx, "victim_pos_y": vy,
            "weapon": "kar", "headshot": headshot}


class Geometry(unittest.TestCase):
    def test_cell_index_floors_negative_too(self):
        self.assertEqual(cell_index(300.0, -1.0, 128.0), (2, -1))
        self.assertEqual(cell_index(-128.0, 0.0, 128.0), (-1, 0))
        self.assertEqual(cell_center(1, -1, 256.0), (384.0, -128.0))


class FailClosed(unittest.TestCase):
    def test_replay_and_missing_sources(self):
        out = build_spatial_layers([], FLAGS, [], PLAYERS, temporal_valid=False)
        self.assertEqual(out["status"], "timed_metrics_suppressed")
        self.assertEqual(out["definition_version"], DEFINITION_VERSION)
        out = build_spatial_layers(None, FLAGS, None, PLAYERS, source_available=False)
        self.assertEqual(out["status"], "unavailable")
        self.assertEqual(out["layers"]["occupancy"]["cells"], [])

    def test_nothing_located(self):
        out = build_spatial_layers([], [], [], PLAYERS)
        self.assertEqual(out["status"], "insufficient_samples")
        self.assertIsNone(out["lattice"])


class Occupancy(unittest.TestCase):
    def test_floor_and_control_on_fine_grid(self):
        # 8 samples = 16 s >= 15 s floor: kept. 7 samples: censored.
        rows = samples(6, 100.0, 100.0, 1) + samples(2, 100.0, 100.0, 2, pid=8)
        rows += samples(7, 700.0, 100.0, 2, pid=9)
        out = build_spatial_layers(rows, [], [], PLAYERS)
        cells = out["layers"]["occupancy"]["cells"]
        self.assertEqual(len(cells), 1)
        c = cells[0]
        self.assertEqual((c["col"], c["row"], c["samples"], c["seconds"]), (0, 0, 8, 16.0))
        self.assertEqual((c["team1_samples"], c["team2_samples"]), (6, 2))
        self.assertEqual(c["control"], 0.5)
        self.assertEqual(out["coverage"]["cells_censored"], 1)
        self.assertEqual(out["coverage"]["samples_used"], 15)
        self.assertEqual(out["lattice"]["scheme"], LATTICE_SCHEME)
        self.assertEqual(out["lattice"]["grid_size"], 128.0)

    def test_dead_and_teamless_samples_ignored(self):
        rows = samples(8, 100.0, 100.0, 1, alive=0) + samples(8, 100.0, 100.0, None)
        out = build_spatial_layers(rows, [], [], PLAYERS)
        self.assertEqual(out["coverage"]["samples_used"], 0)

    def test_halves_and_windows(self):
        # Half 1: team 1 holds cell (0,0) for 8 samples at t=0..14.
        # Half 2: team 2 holds it for 8 samples at t=100..114 (window 1 of 60 s).
        rows = samples(8, 10.0, 10.0, 1, half=1) + samples(8, 10.0, 10.0, 2, pid=8, half=2, t0=100.0)
        out = build_spatial_layers(rows, [], [], PLAYERS)
        whole = out["layers"]["occupancy"]["cells"][0]
        self.assertEqual((whole["samples"], whole["control"]), (16, 0.0))
        halves = out["layers"]["halves"]
        self.assertEqual(halves["1"]["cells"][0]["control"], 1.0)
        self.assertEqual(halves["2"]["cells"][0]["control"], -1.0)
        self.assertEqual((halves["2"]["start"], halves["2"]["end"]), (100.0, 114.0))
        win = out["layers"]["windows"]
        self.assertEqual(win["columns"], ["half", "window", "col", "row", "team1", "team2"])
        self.assertEqual(win["rows"], [[1, 0, 0, 0, 8, 0], [2, 1, 0, 0, 0, 8]])

    def test_window_floor_lower_than_match_floor(self):
        rows = samples(3, 10.0, 10.0, 1)          # 6 s: below the 15 s match floor
        out = build_spatial_layers(rows, [], [], PLAYERS, SpatialLayersConfig())
        self.assertEqual(out["layers"]["occupancy"]["cells"], [])
        self.assertEqual(out["layers"]["windows"]["rows"], [[1, 0, 0, 0, 3, 0]])


class FragsAndLanes(unittest.TestCase):
    def setUp(self):
        # Three frags from lane cell (0,0) into lane cell (2,0) [256-unit] by
        # two attackers on two victims; one lone frag elsewhere; one with no
        # half (no producer context) that must not count anywhere public.
        self.frags = [
            frag(1, 8, 10, 10, 600, 20, t=5.0),
            frag(1, 9, 20, 20, 610, 30, headshot=1, t=70.0),
            frag(2, 8, 30, 30, 620, 40, t=130.0),
            frag(3, 10, 2000, 2000, 2100, 2100, half=2, t=9.0),
            frag(4, 11, 10, 10, 600, 20, half=None),
        ]
        self.out = build_spatial_layers(samples(8, 100.0, 100.0, 1), FLAGS, self.frags, PLAYERS)

    def test_coverage_counts(self):
        cov = self.out["coverage"]
        self.assertEqual((cov["frags_total"], cov["frags_with_endpoints"], cov["frags_used"]), (5, 5, 4))

    def test_lane_threshold_and_contributors_on_coarse_grid(self):
        lanes = self.out["layers"]["recurring_lanes"]["vectors"]
        self.assertEqual(len(lanes), 1)
        lane = lanes[0]
        self.assertEqual((lane["origin"]["col"], lane["origin"]["row"]), (0, 0))
        self.assertEqual((lane["destination"]["col"], lane["destination"]["row"]), (2, 0))
        self.assertEqual(lane["count"], 3)
        self.assertEqual(lane["headshot_rate"], 0.333)
        self.assertEqual((lane["origin"]["x"], lane["destination"]["x"]), (128.0, 640.0))

    def test_lane_needs_distinct_attackers_and_victims(self):
        same = [frag(1, 8, 10, 10, 600, 20) for _ in range(5)]
        out = build_spatial_layers(samples(8, 100.0, 100.0, 1), [], same, PLAYERS)
        self.assertEqual(out["layers"]["recurring_lanes"]["vectors"], [])
        self.assertEqual(out["layers"]["kill_hotspots"]["cells"], [])  # one attacker
        self.assertEqual(len(out["layers"]["frag_vectors"]["vectors"]), 5)  # paths are per frag

    def test_hotspots_unattributed_on_fine_grid(self):
        kills = self.out["layers"]["kill_hotspots"]["cells"]
        deaths = self.out["layers"]["death_hotspots"]["cells"]
        self.assertEqual(kills, [{"col": 0, "row": 0, "kills": 3}])
        self.assertEqual(deaths, [{"col": 4, "row": 0, "deaths": 3}])   # x=600..620 / 128
        for cell in kills + deaths:
            self.assertFalse({"name", "player_id", "who"} & set(cell))

    def test_flags_and_lattice_bounds(self):
        self.assertEqual([f["flag_name"] for f in self.out["flags"]], ["Laundry", "Plaza"])
        lat = self.out["lattice"]
        self.assertEqual(lat["column_index_min"], -12)  # Laundry at x=-1495 / 128
        self.assertEqual(lat["row_index_min"], -3)      # Laundry at y=-326 / 128
        self.assertEqual(lat["columns"], 16 - (-12) + 1)  # reaches the (16,16) lone frag

    def test_kill_paths_public_by_ruling(self):
        fv = self.out["layers"]["frag_vectors"]
        self.assertTrue(fv["published"])
        self.assertEqual(len(fv["vectors"]), 4)
        self.assertEqual(self.out["private_frag_vectors"]["vectors"], [])
        first = fv["vectors"][0]
        self.assertEqual((first["half"], first["game_time"]), (1, 5.0))
        self.assertEqual(first["attacker"], {"name": "p1", "team": 1})
        self.assertEqual(first["distance"], 590.1)
        # sorted by half then time
        self.assertEqual([(v["half"], v["game_time"]) for v in fv["vectors"]],
                         [(1, 5.0), (1, 70.0), (1, 130.0), (2, 9.0)])

    def test_publish_flag_off_keeps_paths_private(self):
        cfg = SpatialLayersConfig(publish_frag_vectors=False)
        out = build_spatial_layers(samples(8, 100.0, 100.0, 1), FLAGS, self.frags, PLAYERS, cfg)
        self.assertFalse(out["layers"]["frag_vectors"]["published"])
        self.assertEqual(out["layers"]["frag_vectors"]["vectors"], [])
        self.assertEqual(len(out["private_frag_vectors"]["vectors"]), 4)


@unittest.skipUnless(SPECIMENS and Path(SPECIMENS).is_dir(), "KTP_REPORT_SPECIMENS not set")
class CorpusSmoke(unittest.TestCase):
    def test_real_match_from_cache(self):
        import sys
        art = Path(SPECIMENS).parent
        if not (art / "feedcache").is_dir():
            self.skipTest("feed cache missing")
        sys.path.insert(0, str(art))
        from run_production_report import SshMysql
        from scripts import match_analytics as ma
        db = SshMysql(cache_dir=art / "feedcache")
        mid = "1.3-6736-ATL1"
        report = json.loads((Path(SPECIMENS) / f"report-{mid}.json").read_text(encoding="utf-8"))
        out = build_spatial_layers(
            ma.query_rows(db, "position_sample_fact.sql", mid),
            ma.query_rows(db, "flag_position_fact.sql", mid),
            ma.query_rows(db, "frag_context_fact.sql", mid),
            report["players"])
        self.assertEqual(out["status"], "available")
        L = out["layers"]
        self.assertGreater(len(L["occupancy"]["cells"]), 100)
        self.assertGreater(len(L["recurring_lanes"]["vectors"]), 0)
        self.assertEqual(len(out["flags"]), 5)
        self.assertEqual(set(L["halves"]), {"1", "2"})
        self.assertGreater(len(L["windows"]["rows"]), 100)
        self.assertEqual(len(L["frag_vectors"]["vectors"]), out["coverage"]["frags_used"])
        self.assertLessEqual(out["coverage"]["frags_used"], out["coverage"]["frags_with_endpoints"])
