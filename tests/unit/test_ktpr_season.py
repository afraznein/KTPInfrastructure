"""KTPR v2.2 season leaderboard: synthetic invariants always; exact
reproduction of the analytics lane's archived output when the corpus is
present (KTP_REPORT_SPECIMENS = dir of report-*.json, with
ktpr_v22_final.json in its parent)."""
import json
import os
import unittest
from pathlib import Path

from scripts.ktpr_season import build_ktpr_v22

SPECIMENS = os.environ.get("KTP_REPORT_SPECIMENS")


def report(match_id, rows):
    """rows: (pid, team, rating)."""
    return {"match_id": match_id, "shadow_explorations": {"ktpr_v2": {
        "definition_version": 1,
        "players": [{"player_id": pid, "team": team, "rating": z,
                     "player_name_at_match": f"p{pid}"}
                    for pid, team, z in rows]}}}


class Synthetic(unittest.TestCase):
    def test_no_reports(self):
        out = build_ktpr_v22([])
        self.assertEqual(out["players"], [])
        self.assertEqual(out["within_var"], 0.0)

    def test_schedule_strength_raises_rating(self):
        # A and B both post z=+1, but A always faces the strong C (+2 raw),
        # B always faces the weak D (-2 raw). A must rank above B.
        reps = []
        for i in range(4):
            reps.append(report(f"m{i}", [(1, 1, 1.0), (3, 2, 2.0)]))
            reps.append(report(f"n{i}", [(2, 1, 1.0), (4, 2, -2.0)]))
        by = {p["player_id"]: p for p in build_ktpr_v22(reps)["players"]}
        self.assertGreater(by[1]["rating"], by[2]["rating"])
        self.assertEqual(by[1]["matches"], 4)

    def test_centered_and_shrunk(self):
        reps = [report("m", [(1, 1, 1.0), (2, 2, -1.0)])] * 3
        out = build_ktpr_v22(reps, k=1.3)
        by = {p["player_id"]: p for p in out["players"]}
        self.assertAlmostEqual(sum(p["sos_rating"] for p in out["players"]), 0.0)
        for p in out["players"]:
            self.assertAlmostEqual(p["rating"], p["sos_rating"] * 3 / 4.3, 3)
        self.assertEqual(by[1]["name"], "p1")


@unittest.skipUnless(SPECIMENS and Path(SPECIMENS).is_dir(),
                     "KTP_REPORT_SPECIMENS not set")
class ArchivedReproduction(unittest.TestCase):
    def test_matches_ktpr_v22_final(self):
        spec = Path(SPECIMENS)
        ref_path = spec.parent / "ktpr_v22_final.json"
        if not ref_path.exists():
            self.skipTest("ktpr_v22_final.json not beside specimens")
        reports = [json.loads(p.read_text(encoding="utf-8"))
                   for p in sorted(spec.glob("report-*.json"))]
        ref = json.loads(ref_path.read_text(encoding="utf-8"))
        out = build_ktpr_v22(reports, beta=ref["beta"], k=ref["shrinkage_k"])
        mine = {p["player_id"]: p for p in out["players"]}
        self.assertAlmostEqual(out["within_var"], ref["within_var"], 3)
        for pid, r in ref["players"].items():
            m = mine[int(pid)]
            self.assertEqual(m["matches"], r["n"])
            self.assertAlmostEqual(m["sos_rating"], r["sos_rating"], 3)
            self.assertAlmostEqual(m["rating"], r["shrunk"], 3)
            self.assertAlmostEqual(m["se"], r["se"], 3)
        board = [p["player_id"] for p in out["players"]
                 if p["matches"] >= out["min_matches"]]
        ref_board = [pid for _, pid in sorted(
            ((v["shrunk"], int(pid)) for pid, v in ref["players"].items()
             if v["n"] >= 3), reverse=True)]
        self.assertEqual(board, ref_board)
