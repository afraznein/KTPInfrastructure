"""Offline tests for scripts/report_scope.py: the one definition of which
matches the report pipeline may publish."""
import unittest

from scripts import report_scope
from scripts.report_scope import (
    HELD_BY_SINCE, HELD_BY_TYPE, IN_SCOPE, OFFICIAL_MATCH_TYPES, classify,
    match_scope_columns)

FLOOR = "2026-09-13"


class Classify(unittest.TestCase):
    def test_official_half_on_or_after_the_floor_is_in_scope(self):
        for start in ("2026-09-13 00:00:00", "2026-09-14 21:00:00"):
            self.assertEqual(classify(start, start, FLOOR), IN_SCOPE)

    def test_no_official_half_is_held_by_type(self):
        self.assertEqual(classify("2026-09-14 21:00:00", "NULL", FLOOR),
                         HELD_BY_TYPE)
        self.assertEqual(classify("2026-09-14 21:00:00", "", FLOOR),
                         HELD_BY_TYPE)

    def test_official_half_before_the_floor_is_held_by_date(self):
        self.assertEqual(classify("2026-09-14 20:00:00",
                                  "2026-09-12 20:00:00", FLOOR),
                         HELD_BY_SINCE)

    def test_no_match_row_is_held(self):
        self.assertEqual(classify("NULL", "NULL", FLOOR), HELD_BY_SINCE)


class OneDefinition(unittest.TestCase):
    def test_official_set_is_competitive_and_ktp_ot(self):
        self.assertEqual(OFFICIAL_MATCH_TYPES, (0, 4))

    def test_every_step_reads_the_same_set(self):
        from scripts import report_service
        self.assertIs(report_service.OFFICIAL_MATCH_TYPES,
                      report_scope.OFFICIAL_MATCH_TYPES)

    def test_sql_uses_in_so_zero_counts_and_null_does_not(self):
        # match_type 0 (.ktp) is falsy in Python; the type is filtered in SQL
        # with IN, which keeps 0 and drops NULL, and is never read into Python.
        sql = match_scope_columns("r")
        self.assertIn("m.match_type IN (0, 4)", sql)
        self.assertIn("BINARY m.match_id = BINARY r.match_id", sql)
        self.assertIn("AS match_start", sql)
        self.assertIn("AS official_start", sql)


if __name__ == "__main__":
    unittest.main()
