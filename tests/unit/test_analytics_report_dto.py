"""analytics-report-dto-v1 sanitizer: whitelist DTO, forbidden-key scan, name repair.
Corpus sweep runs when KTP_REPORT_SPECIMENS points at report-*.json files."""
import json
import os
import unittest
from pathlib import Path

from scripts.analytics_report_dto import (
    CONTRACT_VERSION, _name, assert_sanitized, sanitize_report)

SPECIMENS = os.environ.get("KTP_REPORT_SPECIMENS")


def internal_report():
    player = {"player_id": 7, "steam_id": "0:123", "player_name_at_match": "A",
              "team": 1, "team_name": "Allies", "kills": 3, "deaths": "2",
              "damage_differential": "958", "kills_per_minute": "1.656"}
    return {
        "schema_version": 7, "generated_at": "2026-09-06 00:00:00",
        "match_id": "1.3-1-X", "quality": {"status": "FAIL", "checks": []},
        "match": {"map_name": "dod_anzio", "started_at": "2026-09-05",
                  "duration_seconds": 100, "halves_played": 2},
        "teams": [{"team": 1, "team_name": "Allies", "kills": 3}],
        "players": [player],
        "weapons": [{"player_id": 7, "player_name_at_match": "A", "team": 1,
                     "weapon": "kar", "kills": 3}],
        "duel_matrix": {"cells": [
            {"killer_id": 7, "killer_name": "A", "victim_id": 8,
             "victim_name": "B", "kills": 2, "cross_team": True},
            {"killer_id": 7, "killer_name": "A", "victim_id": 9,
             "victim_name": "C", "kills": 1, "cross_team": False}]},
        "shadow_timelines": {
            "definitions": {"basic_trade": {"definition_version": 2}},
            "trades": [{"half": 1, "seconds_after": 4, "death_event_id": 1,
                        "fallen_player": {"player_id": 8, "steam_id": "x",
                                          "name": "B", "team": 2},
                        "original_killer": {"name": "A", "team": 1},
                        "trader": {"name": "D", "team": 2},
                        "event_time": "wall clock"}],
            "fast_multikills": [{"classification": "fast_2k", "half": 1,
                                 "killer": {"player_id": 7, "name": "A",
                                            "team": 1},
                                 "kill_count": 2, "elapsed_seconds": 1,
                                 "started_unix": 1, "event_ids": [1, 2],
                                 "victims": [{"name": "B", "team": 2}],
                                 "objective_conversion": {"converted": True}}],
            "trade_analysis": {"teams": [
                {"team": 1, "trade_kills": 1,
                 "team_death_response_opportunities": 4,
                 "team_death_response_rate": 0.25}]},
        },
        "shadow_explorations": {
            "recap_speed": {"definition_version": 1,
                            "teams": [{"team": 1, "recaps": 1,
                                       "median_seconds": 10.0,
                                       "mean_seconds": 10.0}],
                            "recaps": [{"half": 1, "flag_index": 1,
                                        "flag_name": "alley", "team": 1,
                                        "lost_at": 1.0, "retaken_at": 11.0,
                                        "seconds": 10.0}]},
            "ktpr_v2": {"status": "available", "definition": "ktpr_v2_blend_v1",
                        "definition_version": 1,
                        "calibration": "uncalibrated_baseline",
                        "parameters": {"swing_weight": 0.4},
                        "components_used": ["swing"],
                        "players": [{"player_id": 7, "steam_id": "0:123",
                                     "player_name_at_match": "A", "team": 1,
                                     "rating": 1.5,
                                     "components": {"swing": 2.0}}]},
            "flag_swing": {"status": "available", "definition_version": 1,
                           "calibration": "uncalibrated_baseline",
                           "parameters": {"flag_coefficient": 2},
                           "timeline": [{"pos_x": 1}],
                           "players": [{"player_id": 7, "team": 1,
                                        "attributed_swing": 0.5,
                                        "weighted_frags": 3}],
                           "break_reel": []},
            "life_kat": {"private": True},
            "map_control": {"status": "available", "definition": "map_control_frontline_v1",
                            "definition_version": 1, "caveats": [],
                            "parameters": {"bin_seconds": 4.0, "frontline_quantile": 0.75,
                                           "ahead_margin": 0.05, "min_side_samples_per_bin": 4,
                                           "clock": "producer_game_time"},
                            "orientation_by_half": {"1": "team1_at_arc0"},
                            "halves": {"1": [[0.0, 0.5], [4.0, 0.61]]},
                            "mean_control_team1": 0.555,
                            "bins": {"resolved": 2, "censored": 0}},
            "depth_profiles": {"status": "available", "definition": "depth_profile_v1",
                               "definition_version": 1, "caveats": [],
                               "players": [{"player_id": 7, "player_name_at_match": "A",
                                            "team": 1, "samples": 300, "mean_depth": 0.41,
                                            "depth_sd": 0.3, "lateral_mean": 210.5,
                                            "depth_sum": 123.0, "depth_sum_sq": 77.4,
                                            "lateral_sum": 63150.0}]},
            "overextension": {"status": "available", "definition": "overextension_frontline_v1",
                              "definition_version": 1, "caveats": [],
                              "frags": {"total": 10, "with_context": 8, "in_resolved_bins": 7},
                              "players": [{"player_id": 7, "player_name_at_match": "A",
                                           "team": 1, "kills_located": 4, "kills_ahead": 2,
                                           "deaths_located": 3, "deaths_ahead": 1,
                                           "kill_ahead_rate": 0.5, "death_ahead_rate": 0.333}]},
        },
        "telemetry_lifecycles": {"private_facts": {}},
        "spatial_layers": {
            "status": "available", "definition": "spatial_layers_v2",
            "definition_version": 2, "caveats": [],
            "parameters": {"grid_size": 128.0, "lane_grid_size": 256.0, "sample_seconds": 2.0,
                           "cell_minimum_seconds": 15.0, "window_seconds": 60.0,
                           "window_cell_minimum_seconds": 6.0, "hotspot_minimum_events": 2,
                           "hotspot_minimum_contributors": 2, "lane_minimum_occurrences": 3,
                           "lane_minimum_contributors": 2, "publish_frag_vectors": True,
                           "lattice": "world_grid_v2", "clock": "producer_game_time"},
            "lattice": {"scheme": "world_grid_v2", "grid_size": 128.0,
                        "column_index_min": -12, "row_index_min": -3,
                        "columns": 29, "rows": 20},
            "flags": [{"flag_index": 0, "flag_name": "Laundry", "x": -1495.0,
                       "y": -326.0, "col": -12, "row": -3}],
            "coverage": {"samples_total": 20, "samples_used": 20, "frags_total": 5,
                         "frags_with_endpoints": 5, "frags_used": 4,
                         "cells_total": 2, "cells_censored": 1},
            "layers": {
                "occupancy": {"cells": [{"col": 0, "row": 0, "samples": 8, "seconds": 16.0,
                                         "team1_samples": 6, "team2_samples": 2,
                                         "control": 0.5}]},
                "kill_hotspots": {"cells": [{"col": 0, "row": 0, "kills": 3}]},
                "death_hotspots": {"cells": [{"col": 4, "row": 0, "deaths": 3}]},
                "recurring_lanes": {"vectors": [{
                    "origin": {"col": 0, "row": 0, "x": 128.0, "y": 128.0},
                    "destination": {"col": 2, "row": 0, "x": 640.0, "y": 128.0},
                    "count": 3, "mean_distance": 590.1, "mean_angle_degrees": 1.2,
                    "headshot_rate": 0.333}]},
                "halves": {"1": {"start": 0.0, "end": 14.0, "cells": [
                    {"col": 0, "row": 0, "samples": 8, "seconds": 16.0,
                     "team1_samples": 8, "team2_samples": 0, "control": 1.0}]}},
                "windows": {"window_seconds": 60.0, "minimum_seconds": 6.0,
                            "columns": ["half", "window", "col", "row", "team1", "team2"],
                            "rows": [[1, 0, 0, 0, 8, 0]]},
                "frag_vectors": {"published": True, "vectors": [{
                    "half": 1, "game_time": 10.0,
                    "attacker": {"name": "A", "team": 1}, "victim": {"name": "B", "team": 2},
                    "origin": {"x": 10.0, "y": 10.0}, "destination": {"x": 600.0, "y": 20.0},
                    "weapon": "kar", "headshot": False, "distance": 590.1, "angle_degrees": 1.0}]},
            },
            "private_frag_vectors": {"visibility": "private_shadow_only", "vectors": [
                {"half": 1, "attacker": {"name": "SECRET", "team": 1}}]},
        },
    }


class Sanitize(unittest.TestCase):
    def test_whitelist_and_forbidden_scan(self):
        dto = sanitize_report(internal_report())
        self.assertEqual(dto["contract_version"], CONTRACT_VERSION)
        body = json.dumps(dto)
        for bad in ("steam_id", "player_id", "event_id", "unix", "pos_x",
                    "life_kat", "private", "timeline", "break_reel",
                    "wall clock", "0:123"):
            self.assertNotIn(bad, body, bad)
        assert_sanitized(dto)

    def test_numeric_strings_coerced(self):
        p = sanitize_report(internal_report())["players"][0]
        self.assertEqual(p["deaths"], 2)
        self.assertEqual(p["damage_differential"], 958)
        self.assertEqual(p["kills_per_minute"], 1.656)

    def test_ratings_block_provisional_and_named(self):
        r = sanitize_report(internal_report())["ratings"]
        self.assertTrue(r["provisional"])
        self.assertIn("recomputed", r["notice"])
        self.assertEqual(r["ktpr_v2"]["players"][0]["name"], "A")
        self.assertEqual(r["ktpr_v2"]["definition_version"], 1)
        self.assertEqual(r["ktpr_v2"]["players"][0]["rating"], 122.5)
        # flag_swing rows carry no name internally; joined by id, id dropped
        self.assertEqual(r["flag_swing"]["players"][0]["name"], "A")
        self.assertNotIn("player_id", r["flag_swing"]["players"][0])

    def test_ktpr_rating_never_negative(self):
        rpt = internal_report()
        rpt["shadow_explorations"]["ktpr_v2"]["players"][0]["rating"] = -9.0
        r = sanitize_report(rpt)["ratings"]["ktpr_v2"]
        self.assertEqual(r["players"][0]["rating"], 50.0)

    def test_accumulation_unavailable_when_not_scored(self):
        acc = sanitize_report(internal_report())["ratings"]["accumulation"]
        self.assertEqual(acc, {"status": "unavailable", "players": []})

    def test_accumulation_block_and_points_per_life(self):
        rep = internal_report()
        rep["accumulation"] = {
            "schema_version": 1, "generated_at": "2026-09-06T00:00:00Z",
            "status": "experimental_shadow", "publication_state": "DRAFT",
            "profile": "accumulation_v5_momentum", "profile_sha256": "ab" * 32,
            "profile_status": "experimental_shadow",
            "impact_index": {"center_index": 100.0, "minimum_index": 50.0,
                             "points_per_robust_sigma": 30.0,
                             "reference_points_per_minute": 149.62,
                             "reference_log_scale": 0.3,
                             "range_contract": "floor_only_no_upper_bound",
                             "reference_source": "provisional_match_robust"},
            "quality_gates": {"bounded_combat": {"status": "PASS",
                                                 "detail": "secret detail"}},
            "players": [{"player_id": 7, "player_name_at_match": "A",
                         "team_name": "Team 1", "deaths": 8,
                         "total_points": 1000.0, "points_per_minute": 200.0,
                         "impact_index": 120.5, "observed_seconds": 300.0,
                         "participation_percent": 99.0, "rank": 1,
                         "combat_finisher_points": 999}],
        }
        dto = sanitize_report(rep)
        acc = dto["ratings"]["accumulation"]
        self.assertEqual(acc["status"], "experimental_shadow")
        self.assertEqual(acc["profile_sha256"], "ab" * 32)
        p = acc["players"][0]
        self.assertEqual(p["name"], "A")
        self.assertEqual(p["team"], 1)  # joined from the v7 roster by name
        # halves_played=2 in the fixture: lives = 8 deaths + 2 = 10
        self.assertEqual(p["points_per_life"], 100.0)
        self.assertEqual(p["impact_index"], 120.5)
        self.assertNotIn("combat_finisher_points", p)
        self.assertNotIn("quality_gates", acc)
        self.assertNotIn("secret detail", json.dumps(dto))
        assert_sanitized(dto)

    def test_positional_block_is_scalar_and_named(self):
        pos = sanitize_report(internal_report())["lane_analytics"]
        self.assertTrue(pos["provisional"])
        self.assertEqual(pos["map_control"]["status"], "available")
        self.assertEqual(pos["map_control"]["halves"]["1"], [[0.0, 0.5], [4.0, 0.61]])
        self.assertEqual(pos["map_control"]["mean_control_team1"], 0.555)
        self.assertEqual(pos["parameters"]["bin_seconds"], 4.0)
        d = pos["depth_profiles"]["players"][0]
        self.assertEqual(d, {"name": "A", "team": 1, "samples": 300, "mean_depth": 0.41,
                             "depth_sd": 0.3, "lateral_mean": 210.5})
        o = pos["overextension"]["players"][0]
        self.assertEqual(o["name"], "A")
        self.assertEqual(o["kill_ahead_rate"], 0.5)
        self.assertNotIn("player_id", json.dumps(pos))
        self.assertNotIn("depth_sum", json.dumps(pos))

    def test_spatial_block_copies_layers_and_published_paths(self):
        dto = sanitize_report(internal_report())
        sp = dto["spatial"]
        self.assertEqual(sp["status"], "available")
        self.assertTrue(sp["provisional"])
        self.assertEqual(sp["lattice"]["grid_size"], 128.0)
        self.assertEqual(sp["flags"][0]["flag_name"], "Laundry")
        self.assertEqual(sp["occupancy"][0]["control"], 0.5)
        self.assertEqual(sp["kill_hotspots"], [{"col": 0, "row": 0, "kills": 3}])
        self.assertEqual(sp["recurring_lanes"][0]["destination"]["x"], 640.0)
        self.assertEqual(sp["parameters"]["lane_grid_size"], 256.0)
        self.assertNotIn("publish_frag_vectors", sp["parameters"])
        self.assertEqual(sp["halves"]["1"]["cells"][0]["control"], 1.0)
        self.assertEqual(sp["halves"]["1"]["end"], 14.0)
        self.assertEqual(sp["windows"]["rows"], [[1, 0, 0, 0, 8, 0]])
        kp = sp["kill_paths"]
        self.assertTrue(kp["published"])
        self.assertEqual(kp["vectors"][0]["attacker"], {"name": "A", "team": 1})
        self.assertEqual(kp["vectors"][0]["destination"], {"x": 600.0, "y": 20.0})
        body = json.dumps(dto)
        self.assertNotIn("private_frag_vectors", body)
        self.assertNotIn("SECRET", body)
        assert_sanitized(dto)

    def test_spatial_paths_withheld_when_not_published(self):
        rep = internal_report()
        rep["spatial_layers"]["layers"]["frag_vectors"]["published"] = False
        sp = sanitize_report(rep)["spatial"]
        self.assertFalse(sp["kill_paths"]["published"])
        self.assertEqual(sp["kill_paths"]["vectors"], [])

    def test_spatial_unavailable_when_block_missing(self):
        rep = internal_report()
        rep.pop("spatial_layers")
        sp = sanitize_report(rep)["spatial"]
        self.assertEqual(sp["status"], "unavailable")
        self.assertIsNone(sp["lattice"])
        self.assertEqual(sp["occupancy"], [])
        self.assertEqual(sp["kill_paths"]["vectors"], [])

    def test_positional_unavailable_when_blocks_missing(self):
        rep = internal_report()
        for k in ("map_control", "depth_profiles", "overextension"):
            rep["shadow_explorations"].pop(k)
        pos = sanitize_report(rep)["lane_analytics"]
        self.assertEqual(pos["map_control"]["status"], "unavailable")
        self.assertEqual(pos["overextension"]["players"], [])

    def test_duels_cross_team_only(self):
        d = sanitize_report(internal_report())["duels"]
        self.assertEqual(d, [{"killer": "A", "victim": "B", "kills": 2}])

    def test_assert_sanitized_rejects(self):
        with self.assertRaises(ValueError):
            assert_sanitized({"players": [{"steam_id": "x"}]})
        with self.assertRaises(ValueError):
            assert_sanitized({"a": {"b": [{"pos_x": 1}]}})


class NameRepair(unittest.TestCase):
    def test_double_encoded_repaired(self):
        self.assertEqual(_name("SavageÂ¬"), "Savage¬")
        self.assertEqual(_name("100ï¼…JESUS"), "100％JESUS")

    def test_clean_names_untouched(self):
        for s in ("plain", "Savage¬", "ünïcøde", "dicE[: :]Gorilla[bc]", None):
            self.assertEqual(_name(s), s)


@unittest.skipUnless(SPECIMENS and Path(SPECIMENS).is_dir(),
                     "KTP_REPORT_SPECIMENS not set")
class Corpus(unittest.TestCase):
    def test_every_report_sanitizes(self):
        n = 0
        for p in sorted(Path(SPECIMENS).glob("report-*.json")):
            dto = sanitize_report(json.loads(p.read_text(encoding="utf-8")))
            body = json.dumps(dto)
            self.assertNotIn("steam_id", body)
            self.assertNotIn("Â¬", body)
            self.assertTrue(dto["ratings"]["ktpr_v2"]["players"])
            n += 1
        self.assertGreater(n, 0)
