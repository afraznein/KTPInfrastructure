"""player_halves: per-half rows, the reconciliation against match totals, and
the legacy/replay cases that must not publish a number."""
import unittest

from scripts.player_halves import ADDITIVE, build_player_halves


def half_row(pid, half, **values):
    row = {"player_id": pid, "player_name_at_match": f"p{pid}", "team": 1,
           "half": half, "duration_seconds": 1200, "position_samples": 500}
    row.update({c: 0 for c in ADDITIVE})
    row.update(values)
    return row


def total(pid, **values):
    return {"player_id": pid, **{c: 0 for c in ADDITIVE}, **values}


ROWS = [
    half_row(1, 1, kills=10, deaths=5, headshots=2, shots=100, hits=25,
             damage_dealt=1200, damage_taken=900),
    half_row(1, 2, kills=6, deaths=7, assists=1, damage_dealt=800, damage_taken=1100),
    half_row(2, 1, position_samples=0),
    half_row(2, 2, kills=3, deaths=2),
]
TOTALS = [total(1, kills=16, deaths=12, headshots=2, assists=1, shots=100, hits=25,
                damage_dealt=2000, damage_taken=2000),
          total(2, kills=3, deaths=2)]


class PlayerHalves(unittest.TestCase):
    def test_rows_reconcile_with_totals(self):
        out = build_player_halves(ROWS, TOTALS, per_hit_damage=True, temporal_valid=True)
        self.assertEqual(out["status"], "available")
        self.assertTrue(out["reconciled"])
        self.assertEqual(out["mismatched_columns"], [])

    def test_a_half_the_player_did_not_play_has_no_row(self):
        out = build_player_halves(ROWS, TOTALS, per_hit_damage=True, temporal_valid=True)
        self.assertEqual([(r["player_id"], r["half"]) for r in out["rows"]],
                         [(1, 1), (1, 2), (2, 2)])

    def test_derived_fields(self):
        r = build_player_halves(ROWS, TOTALS, per_hit_damage=True,
                                temporal_valid=True)["rows"][0]
        self.assertEqual(r["kd_ratio"], 2.0)
        self.assertEqual(r["headshot_rate"], 0.2)
        self.assertEqual(r["raw_accuracy"], 0.25)
        self.assertEqual(r["damage_differential"], 300)
        self.assertEqual(r["damage_per_minute"], 60.0)
        self.assertEqual(r["kills_per_minute"], 0.5)

    def test_a_mismatch_names_the_column(self):
        totals = [dict(TOTALS[0], kills=17), TOTALS[1]]
        out = build_player_halves(ROWS, totals, per_hit_damage=True, temporal_valid=True)
        self.assertFalse(out["reconciled"])
        self.assertEqual(out["mismatched_columns"], ["kills"])

    def test_legacy_damage_is_null_and_not_reconciled(self):
        totals = [dict(TOTALS[0], damage_dealt=9999), TOTALS[1]]
        out = build_player_halves(ROWS, totals, per_hit_damage=False, temporal_valid=True)
        self.assertTrue(out["reconciled"])
        self.assertIsNone(out["rows"][0]["damage_dealt"])
        self.assertIsNone(out["rows"][0]["damage_per_minute"])

    def test_legacy_grenade_damage_is_null_not_zero(self):
        rows = [dict(r, grenade_damage=0, grenade_damage_taken=0) for r in ROWS]
        out = build_player_halves(rows, TOTALS, per_hit_damage=False, temporal_valid=True)
        for r in out["rows"]:
            self.assertIsNone(r["grenade_damage"])
            self.assertIsNone(r["grenade_damage_taken"])
        covered = build_player_halves(rows, TOTALS, per_hit_damage=True,
                                      temporal_valid=True)
        self.assertEqual(covered["rows"][0]["grenade_damage"], 0)

    def test_replay_has_no_per_minute_rates(self):
        r = build_player_halves(ROWS, TOTALS, per_hit_damage=True,
                                temporal_valid=False)["rows"][0]
        self.assertIsNone(r["kills_per_minute"])
        self.assertIsNone(r["damage_per_minute"])
        self.assertEqual(r["kills"], 10)

    def test_score_and_grenade_fields_pass_through_unreconciled(self):
        rows = [
            half_row(1, 1, kills=10, deaths=5, score=4, grenade_kills=1,
                     grenade_damage=50, grenade_damage_taken=20),
            half_row(1, 2, kills=6, deaths=7, score=3),
        ]
        # A half-sum/total mismatch on score must not flip `reconciled` --
        # ktp_match_stats half=0 is the daemon's own pre-summed total, not
        # derived from these half rows the way ADDITIVE columns are.
        totals = [total(1, kills=16, deaths=12, score=999)]
        out = build_player_halves(rows, totals, per_hit_damage=True, temporal_valid=True)
        assert out["reconciled"] is True
        assert out["rows"][0]["score"] == 4
        assert out["rows"][0]["points_per_minute"] == round(4 * 60.0 / 1200, 3)
        assert out["rows"][0]["grenade_kills"] == 1
        assert out["rows"][0]["grenade_damage"] == 50
        assert out["rows"][0]["grenade_damage_taken"] == 20
        assert out["rows"][1]["grenade_kills"] == 0

    def test_no_source_is_unavailable(self):
        for rows in (None, []):
            out = build_player_halves(rows, TOTALS, per_hit_damage=True, temporal_valid=True)
            self.assertEqual((out["status"], out["reconciled"], out["rows"]),
                             ("unavailable", None, []))


if __name__ == "__main__":
    unittest.main()
