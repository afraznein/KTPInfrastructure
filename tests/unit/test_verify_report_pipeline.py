"""Offline tests for scripts/verify_report_pipeline.py.

Every check is asserted in BOTH directions. The check this script replaces
returned 0 rows whether or not the pipeline worked, so a test suite that
only proves the happy path would reproduce the defect one level up.
"""
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.verify_report_pipeline import (
    EMPTY_STATE_MARKER, GenerateRun, check_coherent, check_complete,
    check_drained, check_failures, check_ran, check_site, parse_last_generate)

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)

GOOD_LOG = """accumulation scorer: available
pending: 2 matches (schema v9)
excluded by match_type filter: 213 (12man 145, scrim 68)
  1.3-9001-ATL1: persisted, publishable=True
  1.3-9002-DAL2: persisted, publishable=True
mysql calls: 41; failures: 0
  map_profiles: wrote revision 1 (2 reports)
"""

TRUNCATED_LOG = """accumulation scorer: available
pending: 2 matches (schema v9)
  1.3-9001-ATL1: persisted, publishable=True
"""

FAILED_LOG = GOOD_LOG.replace("failures: 0", "failures: 1")


class ParseLastGenerate(unittest.TestCase):
    def test_reads_a_complete_block(self):
        self.assertEqual(parse_last_generate(GOOD_LOG), GenerateRun(2, 9, 0))

    def test_truncated_block_is_not_a_run(self):
        # The discriminating case: the old check read this as success.
        self.assertIsNone(parse_last_generate(TRUNCATED_LOG))

    def test_empty_log_is_not_a_run(self):
        self.assertIsNone(parse_last_generate(""))

    def test_last_block_wins(self):
        self.assertEqual(
            parse_last_generate(GOOD_LOG + FAILED_LOG), GenerateRun(2, 9, 1))

    def test_terminator_without_a_head_is_ignored(self):
        self.assertIsNone(parse_last_generate("mysql calls: 3; failures: 0\n"))


class CheckRan(unittest.TestCase):
    def _log(self, tmp, age_hours):
        p = Path(tmp) / "svc.log"
        p.write_text("x")
        stamp = (NOW - timedelta(hours=age_hours)).timestamp()
        import os
        os.utime(p, (stamp, stamp))
        return p

    def test_fresh_log_passes(self):
        with TemporaryDirectory() as tmp:
            self.assertTrue(check_ran(self._log(tmp, 2), NOW, 26).ok)

    def test_stale_log_fails(self):
        with TemporaryDirectory() as tmp:
            self.assertFalse(check_ran(self._log(tmp, 72), NOW, 26).ok)

    def test_missing_log_fails(self):
        with TemporaryDirectory() as tmp:
            self.assertFalse(check_ran(Path(tmp) / "nope.log", NOW, 26).ok)


class CheckComplete(unittest.TestCase):
    def test_run_passes(self):
        self.assertTrue(check_complete(GenerateRun(2, 9, 0)).ok)

    def test_no_run_fails(self):
        self.assertFalse(check_complete(None).ok)


class CheckFailures(unittest.TestCase):
    def test_zero_passes(self):
        self.assertTrue(check_failures(GenerateRun(2, 9, 0)).ok)

    def test_nonzero_fails(self):
        self.assertFalse(check_failures(GenerateRun(2, 9, 1)).ok)

    def test_absent_run_fails_rather_than_passes(self):
        self.assertFalse(check_failures(None).ok)


class CheckDrained(unittest.TestCase):
    def test_nothing_left_passes(self):
        self.assertTrue(check_drained([]).ok)

    def test_leftover_fails_and_names_ids(self):
        f = check_drained(["1.3-9001-ATL1"])
        self.assertFalse(f.ok)
        self.assertIn("1.3-9001-ATL1", f.detail)


class CheckCoherent(unittest.TestCase):
    def test_cosmetic_fail_at_publishable_is_expected(self):
        # quality_status FAIL at publishable=1 is a cosmetic match_id_shape
        # FAIL; failing on it would withhold the match over a label.
        self.assertTrue(check_coherent([("1.3-9001-ATL1", "FAIL", 1)]).ok)

    def test_pass_at_unpublishable_fails(self):
        self.assertFalse(check_coherent([("1.3-9001-ATL1", "PASS", 0)]).ok)

    def test_empty_is_coherent(self):
        self.assertTrue(check_coherent([]).ok)


class CheckSite(unittest.TestCase):
    EMPTY = f"<p>{EMPTY_STATE_MARKER}. Reports appear here after...</p>"
    LISTING = "<table><tr><td>1.3-9001-ATL1</td></tr></table>"

    def test_empty_marker_with_zero_reports_passes(self):
        self.assertTrue(check_site(self.EMPTY, 0).ok)

    def test_listing_with_reports_passes(self):
        self.assertTrue(check_site(self.LISTING, 2).ok)

    def test_empty_marker_while_reports_exist_fails(self):
        # Sync or cache-tag purge did not land. A 200 hides this entirely.
        self.assertFalse(check_site(self.EMPTY, 2).ok)

    def test_listing_while_no_reports_exist_fails(self):
        self.assertFalse(check_site(self.LISTING, 0).ok)

    def test_skipped_when_not_fetched(self):
        self.assertTrue(check_site(None, 0).ok)


if __name__ == "__main__":
    unittest.main()
