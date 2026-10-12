"""The windowed capture-authorization rate, and the denominator that decides it.

`match_capture_authorization` answers this per match. The rate over a WEEK had
no tool at all, which is why the number the D5 daemon was deployed to move went
unmeasured: the fix was proven to execute and unproven to work, and re-deriving
it meant hand-writing the queries again.

The defect these tests exist to stop is not in the evaluator — that is reused,
not reimplemented. It is in the denominator. A "report" is a match carrying a
`ktp_match_reports` row, not a match: roughly a third of played matches never
get one, so counting `ktp_matches` is defensible, reads identical in a summary,
and gives a materially different percentage. It is also the wrong direction to
be wrong in, because the baseline on record was taken on the report
denominator, so swapping it turns a real improvement into a smaller one while
still looking like a comparison.

The fixture below makes that visible rather than arguable: the same rows score
differently under the two denominators, and a test asserts they disagree. A
fixture where they agreed would pass whichever one the code used.
"""
import io
import json
import unittest

from scripts import capture_authorization_rate as rate
from scripts import match_analytics as analytics

CAPABILITIES = (
    "frag_context,damage,position,assist,life,break,flag_state,flag_position,"
    "objective_attempt,team_membership,grenade_entity,position_state,"
    "map_revision,sequence,health"
)
REVISION = "b" * 64
REQUIRED = list(analytics.CAPTURE_EVENT_TYPES)


def manifest(match_id, half, start=1000, received=1000):
    return {
        "match_id": match_id, "half": half, "schema_version": 24,
        "capabilities": CAPABILITIES, "position_interval": 2.0,
        "map_revision_algorithm": "sha256", "map_revision_sha256": REVISION,
        "producer_activation_epoch": start, "activation_receipt_epoch": received,
        "match_start_epoch": start,
    }


def health(match_id, half, **broken):
    """One clean health row per required stream, with named breakages."""
    rows = []
    for event_type in REQUIRED:
        row = {
            "match_id": match_id, "half": half, "event_type": event_type,
            "attempted": 10, "enqueued": 10, "dropped": 0, "emitted": 10,
            "daemon_received": 10, "daemon_accepted": 10, "daemon_rejected": 0,
            "correlation_failure_count": 0, "sequence_gap_count": 0,
            "duplicate_or_reordered_count": 0,
        }
        row.update(broken.get(event_type, {}))
        rows.append(row)
    return rows


def match_rows(match_id, date, start_time, halves=(1, 2)):
    return [{"match_id": match_id, "half": half, "start_date": date,
             "start_time": start_time} for half in halves]


class Fixture:
    """Four matches: two with reports, two without, scoring differently."""

    # with a report, clean
    GOOD_REPORTED = "ktp-1-reported-clean"
    # with a report, one stream short of the daemon by two lines
    BAD_REPORTED = "ktp-2-reported-lossy"
    # no report, clean -- the match denominator counts it, the report one does not
    GOOD_UNREPORTED = "ktp-3-unreported-clean"
    # no report, clean
    ALSO_GOOD_UNREPORTED = "ktp-4-unreported-clean"

    def __init__(self):
        self.matches = (
            match_rows(self.GOOD_REPORTED, "2026-10-06", "2026-10-06 20:00:00")
            + match_rows(self.BAD_REPORTED, "2026-10-06", "2026-10-06 21:00:00")
            + match_rows(self.GOOD_UNREPORTED, "2026-10-07", "2026-10-07 20:00:00")
            + match_rows(self.ALSO_GOOD_UNREPORTED, "2026-10-07",
                         "2026-10-07 21:00:00"))
        self.manifests = []
        self.health = []
        for match_id in (self.GOOD_REPORTED, self.BAD_REPORTED,
                         self.GOOD_UNREPORTED, self.ALSO_GOOD_UNREPORTED):
            for half in (1, 2):
                self.manifests.append(manifest(match_id, half))
                broken = ({"position": {"daemon_received": 8,
                                        "daemon_accepted": 8}}
                          if match_id == self.BAD_REPORTED and half == 1 else {})
                self.health += health(match_id, half, **broken)
        self.reported = {self.GOOD_REPORTED, self.BAD_REPORTED}

    def evaluate(self, denominator):
        return rate.evaluate(
            self.matches, self.manifests, self.health,
            self.reported if denominator == "reports" else None)


FIXTURE = Fixture()
BY_REPORTS = FIXTURE.evaluate("reports")
BY_MATCHES = FIXTURE.evaluate("matches")


def share(results):
    return sum(1 for row in results if row["authorized"]) / len(results)


class NonVacuity(unittest.TestCase):
    """A fixture that scored everything the same would pass every assertion."""

    def test_both_denominators_resolved_matches(self):
        self.assertEqual(len(BY_REPORTS), 2)
        self.assertEqual(len(BY_MATCHES), 4)

    def test_the_fixture_holds_both_outcomes(self):
        for results in (BY_REPORTS, BY_MATCHES):
            outcomes = {row["authorized"] for row in results}
            self.assertEqual(outcomes, {True, False},
                             "every match scored the same way, so nothing below "
                             "distinguishes a working evaluator from a stub")

    def test_the_two_denominators_actually_disagree(self):
        """The whole point. If they agreed, the choice would be untestable."""
        self.assertNotEqual(share(BY_REPORTS), share(BY_MATCHES))
        self.assertEqual(share(BY_REPORTS), 0.5)
        self.assertEqual(share(BY_MATCHES), 0.75)

    def test_the_report_denominator_is_a_subset_and_not_a_filter_on_quality(self):
        """The excluded matches are clean ones, so dropping the report join does
        not merely add noise -- it moves the answer in the flattering
        direction, which is how a swapped denominator survives review."""
        self.assertGreater(share(BY_MATCHES), share(BY_REPORTS))


class Evaluator(unittest.TestCase):
    """The verdict comes from match_analytics, not from a second implementation."""

    def test_a_clean_match_is_fully_authorized(self):
        clean = [row for row in BY_MATCHES if row["streams"] == row["authorized_streams"]]
        self.assertEqual(len(clean), 3)
        for row in clean:
            self.assertTrue(row["authorized"])
            self.assertEqual(row["withheld"], [])

    def test_a_two_line_shortfall_withholds_only_its_own_stream(self):
        lossy = [row for row in BY_MATCHES if not row["authorized"]]
        self.assertEqual(len(lossy), 1)
        self.assertEqual(len(lossy[0]["withheld"]), 1,
                         "a shortfall on one stream withheld a sibling, which is "
                         "the per-stream authorization this reuses, not reimplements")
        self.assertLess(lossy[0]["authorized_streams"], lossy[0]["streams"])

    def test_the_withheld_reason_names_where_the_data_was_lost(self):
        lossy = next(row for row in BY_MATCHES if not row["authorized"])
        buckets = {rate.classify(error)
                   for errors in lossy["withheld"] for error in errors}
        self.assertIn("lines never reached the daemon", buckets)


class Classify(unittest.TestCase):
    """Every bucket must be reachable from a string match_analytics emits, and
    an unknown reason must survive as itself rather than vanish."""

    def test_every_bucket_is_reachable(self):
        counters = {key: 0 for key in (
            "attempted", "enqueued", "dropped", "emitted", "daemon_received",
            "daemon_accepted", "daemon_rejected", "correlation_failure_count",
            "sequence_gap_count", "duplicate_or_reordered_count")}
        produced = set()
        for broken in ({"dropped": 3, "attempted": 13, "enqueued": 10},
                       {"emitted": 10, "daemon_received": 8,
                        "daemon_accepted": 8},
                       {"correlation_failure_count": 2},
                       {"daemon_rejected": 2, "daemon_received": 12,
                        "emitted": 12, "enqueued": 12, "attempted": 12,
                        "daemon_accepted": 10}):
            row = dict(counters, emitted=10, enqueued=10, attempted=10,
                       daemon_received=10, daemon_accepted=10)
            row.update(broken)
            for failure in analytics._reconcile_failures(row):
                produced.add(rate.classify(failure))
        self.assertNotIn(True, [b.startswith("UNCLASSIFIED") for b in produced],
                         f"a real reconcile failure fell through: {produced}")
        self.assertIn("lines never reached the daemon", produced)
        self.assertIn("frag correlation failure", produced)
        self.assertIn("producer dropped before emit", produced)
        self.assertIn("daemon rejected", produced)

    def test_an_unknown_reason_is_reported_verbatim_not_folded_away(self):
        bucket = rate.classify("half 1 position grew a new failure mode")
        self.assertTrue(bucket.startswith("UNCLASSIFIED"), bucket)
        self.assertIn("grew a new failure mode", bucket)


class Report(unittest.TestCase):

    def render(self, results):
        out = io.StringIO()
        rate.report("TEST", results, out=out)
        return out.getvalue()

    def test_an_empty_window_says_so_instead_of_printing_a_zero(self):
        """A 0% over nothing is not a measurement, and reads exactly like one."""
        text = self.render([])
        self.assertIn("empty window", text)
        self.assertNotIn("= 0%", text)

    def test_the_per_day_series_is_printed_beside_the_share(self):
        """The share is what moved after the D5 daemon; the per-day count is
        bounded by how much was played and barely moved. Printing one without
        the other is how the same data reads as success or as nothing."""
        text = self.render(BY_MATCHES)
        self.assertIn("fully capture-authorized:", text)
        self.assertIn("PER DAY", text)
        self.assertIn("days with play: 2", text)

    def test_a_stream_short_in_both_halves_counts_its_cause_once(self):
        """The real shape, and the one a per-error tally gets wrong: one stream
        loses lines in half 1 AND half 2, so it carries two errors that bucket
        the SAME way. Counting errors scores that cause twice on one withheld
        stream and prints a share above 100%."""
        results = [{"date": "2026-10-06", "start": "2026-10-06 20:00:00",
                    "authorized": False, "streams": 11, "authorized_streams": 10,
                    "withheld": [[
                        "half 1 position counters do not reconcile: 2 of 10 "
                        "emitted never reached the daemon",
                        "half 2 position counters do not reconcile: 3 of 10 "
                        "emitted never reached the daemon"]]}]
        text = self.render(results)
        self.assertIn("withheld streams: 1", text)
        self.assertIn("1 (100%)  lines never reached the daemon", text)
        self.assertNotIn("2 (200%)", text)

    def test_a_stream_failing_several_ways_lists_each_cause_once(self):
        results = [{"date": "2026-10-06", "start": "2026-10-06 20:00:00",
                    "authorized": False, "streams": 11, "authorized_streams": 10,
                    "withheld": [["2 of 10 emitted never reached the daemon",
                                  "1 correlation failure(s)"]]}]
        text = self.render(results)
        self.assertIn("withheld streams: 1", text)
        self.assertIn("(100%)  lines never reached the daemon", text)
        self.assertIn("(100%)  frag correlation failure", text)


class Arguments(unittest.TestCase):

    def test_a_backwards_window_is_refused(self):
        with self.assertRaises(SystemExit):
            rate.parse_args(["--since", "2026-10-12 00:00:00",
                             "--until", "2026-10-05 00:00:00"])

    def test_a_baseline_inside_the_window_is_refused(self):
        with self.assertRaises(SystemExit):
            rate.parse_args(["--since", "2026-10-05 00:00:00",
                             "--until", "2026-10-12 00:00:00",
                             "--baseline-since", "2026-10-06 00:00:00"])

    def test_the_report_denominator_is_the_default(self):
        args = rate.parse_args(["--since", "2026-10-05 00:00:00",
                                "--until", "2026-10-12 00:00:00"])
        self.assertEqual(args.denominator, "reports")

    def test_the_window_clause_is_half_open_and_excludes_half_zero(self):
        clause = rate.window_sql("2026-10-05 11:02:00", "2026-10-12 11:02:00")
        self.assertIn("half > 0", clause)
        self.assertIn(">= '2026-10-05 11:02:00'", clause)
        self.assertIn("< '2026-10-12 11:02:00'", clause)


class ReadOnly(unittest.TestCase):

    def test_every_statement_is_sent_read_only(self):
        """A reporting tool must not be able to write, and the guarantee has to
        be in the code rather than in the operator's habits."""
        sent = []

        class FakeProc:
            returncode = 0
            stdout = ""
            stderr = ""

        original = rate.subprocess.run
        rate.subprocess.run = lambda *a, **kw: (sent.append(kw["input"]),
                                                FakeProc())[1]
        try:
            rate.Mysql("mysql", "hlstatsx").rows("SELECT 1")
        finally:
            rate.subprocess.run = original
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0].startswith("SET SESSION TRANSACTION READ ONLY;"),
                        sent[0][:60])

    def test_a_mysql_failure_is_raised_and_not_read_as_an_empty_result(self):
        """An exit code swallowed here reads as a window with no matches, which
        is the same shape as a true zero."""
        class FakeProc:
            returncode = 1
            stdout = ""
            stderr = "ERROR 1142: SELECT denied"

        original = rate.subprocess.run
        rate.subprocess.run = lambda *a, **kw: FakeProc()
        try:
            with self.assertRaises(SystemExit) as caught:
                rate.Mysql("mysql", "hlstatsx").rows("SELECT 1")
        finally:
            rate.subprocess.run = original
        self.assertIn("1142", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
