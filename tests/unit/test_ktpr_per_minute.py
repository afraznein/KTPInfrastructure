"""KTPR v2 definition 2: the count components are per observed minute.

Operator ruling 2026-11-27: a player who subbed in for part of a match must not
be penalised for the counts he had no time to earn, and overtime must not
inflate them. `multikill` and `swing` are divided by observed minutes before
z-scoring; z-scores are scale-invariant, so a match where everyone was observed
equally must rate exactly as definition 1 did.
"""
import unittest

from scripts.ktpr_v2 import build_ktpr_v2_shadow

FULL = 1200


def players(multikills, observed=None, duration=FULL):
    rows = []
    for i, fast_2k in enumerate(multikills):
        row = {"player_id": i, "player_name_at_match": f"p{i}",
               "team": 1 + i % 2, "damage_per_life": 100.0 + 10 * i,
               "kd_ratio": 1.0, "fast_2k": fast_2k, "fast_3k": 0,
               "fast_4k_plus": 0, "duration_seconds": duration}
        if observed is not None:
            row["observed_seconds"] = observed[i]
        rows.append(row)
    return rows


def swing_rows(values):
    return [{"player_id": i, "attributed_swing": v}
            for i, v in enumerate(values)]


MULTI = [4, 2, 1, 0]
SWING = [3.0, 1.0, -1.0, -3.0]


def build(multikills=MULTI, swing=SWING, observed=None, duration=FULL):
    return build_ktpr_v2_shadow(
        players(multikills, observed, duration), None, swing_rows(swing))


def by_id(envelope):
    return {p["player_id"]: p for p in envelope["players"]}


class PerMinuteCounts(unittest.TestCase):
    def test_equal_minutes_rate_exactly_as_before(self):
        today = build()
        for seconds in (FULL, 2400, 100):  # full, overtime, all under the floor
            equal = build(observed=[seconds] * 4)
            self.assertEqual(equal["parameters"]["count_components_per"],
                             "observed_minute")
            self.assertEqual(
                [(p["player_id"], p["rating"], p["components"])
                 for p in today["players"]],
                [(p["player_id"], p["rating"], p["components"])
                 for p in equal["players"]], seconds)

    def test_a_half_match_sub_rates_as_a_full_match_player(self):
        """Player 1 played half the match at player 0's per-minute output."""
        multikills, swing = [4, 2, 1, 0], [3.0, 1.5, -1.0, -3.0]
        timed = by_id(build(multikills, swing,
                            observed=[FULL, FULL / 2, FULL, FULL]))
        for name in ("multikill", "swing"):
            self.assertAlmostEqual(timed[0]["components"][name],
                                   timed[1]["components"][name], places=4)
        # Control: on raw counts the sub reads well below his equal.
        raw = by_id(build(multikills, swing))
        for name in ("multikill", "swing"):
            self.assertLess(raw[1]["components"][name],
                            raw[0]["components"][name])

    def test_rate_components_are_not_divided(self):
        timed = by_id(build(observed=[FULL, FULL / 2, FULL, FULL]))
        raw = by_id(build())
        self.assertEqual(timed[1]["components"]["output"],
                         raw[1]["components"]["output"])

    def test_unknown_minutes_divide_by_the_full_match(self):
        """None is unknown, not zero: the largest divisor he could have."""
        unknown = build(observed=[FULL, None, FULL, FULL])
        full = build(observed=[FULL] * 4)
        self.assertEqual(by_id(unknown)[1]["components"],
                         by_id(full)[1]["components"])
        # No duration on the row: fall back to the longest observed player.
        unknown = build(observed=[FULL, None, 900, 600], duration=None)
        longest = build(observed=[FULL, FULL, 900, 600], duration=None)
        self.assertEqual(by_id(unknown)[1]["components"],
                         by_id(longest)[1]["components"])

    def test_no_observed_time_at_all_keeps_raw_counts(self):
        none = build(observed=[None] * 4)
        absent = build()
        self.assertEqual(none["parameters"]["count_components_per"],
                         "match_no_observed_time")
        self.assertEqual(none["players"], absent["players"])

    def test_a_cameo_is_floored_not_excluded(self):
        """60 s and 300 s divide alike: a rate over a minute is noise."""
        cameo = build(observed=[FULL, 60, FULL, FULL])
        floor = build(observed=[FULL, 300, FULL, FULL])
        self.assertEqual(by_id(cameo)[1]["components"],
                         by_id(floor)[1]["components"])
        self.assertIn(1, by_id(cameo))
        self.assertEqual(cameo["parameters"]["minimum_observed_seconds"], 300.0)

    def test_definition_version_is_2(self):
        self.assertEqual(build()["definition_version"], 2)


class ObservedSecondsSource(unittest.TestCase):
    def test_legacy_stub_carries_every_column_the_facts_read(self):
        """An archive without position samples gets an empty stub table, and
        player_match_fact now reads its event_time -- without the column the
        whole box score fails, not just observed_seconds."""
        import re
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        stub = (root / "sql" / "compatibility"
                / "legacy_optional_sources.sql").read_text(encoding="utf-8")
        body = re.search(r"EXISTS ktp_position_samples AS(.*?);", stub, re.S)
        self.assertIn("AS event_time", body.group(1))
        for name in ("player_match_fact.sql", "player_half_fact.sql"):
            sql = (root / "sql" / "analytics" / name).read_text(encoding="utf-8")
            self.assertIn("TIMESTAMPDIFF(SECOND, MIN(event_time), MAX(event_time))",
                          sql, name)


if __name__ == "__main__":
    unittest.main()
