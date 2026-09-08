"""Offline tests for scripts/report_sync.py (no MySQL, no network).

The script publishes to the public website and nothing pulls a row back, so
the properties under test here are the ones whose failure is irreversible:
that the already-synced set is read in full, and that no aggregate reaches
PostgREST without passing the forbidden-key assertion.
"""
import unittest
from unittest import mock

from scripts import report_sync

# PostgREST's stock max-rows. The stub truncates here the way the server does:
# silently, in a 200, with the shortfall visible only in Content-Range.
SERVER_MAX_ROWS = 1000


class Postgrest:
    """Minimal PostgREST read surface: honours offset/limit, then truncates."""

    def __init__(self, rows, max_rows=SERVER_MAX_ROWS, honour_offset=True):
        self.rows = rows
        self.max_rows = max_rows
        self.honour_offset = honour_offset
        self.calls = 0

    def _param(self, path, name, default):
        for part in path.partition("?")[2].split("&"):
            key, _, value = part.partition("=")
            if key == name:
                return int(value)
        return default

    def __call__(self, path, method="GET", body=None):
        self.calls += 1
        offset = self._param(path, "offset", 0) if self.honour_offset else 0
        limit = self._param(path, "limit", len(self.rows))
        return self.rows[offset:offset + limit][:self.max_rows]


def report_rows(n, start=0):
    return [{"match_id": f"m{i:05d}", "report_schema_version": 8,
             "revision": 1} for i in range(start, start + n)]


class TestPaging(unittest.TestCase):
    def test_stub_truncates_an_unpaged_read(self):
        """Control for every paging test below: without it, a passing paged
        read would not prove the cap was ever in play."""
        rows = report_rows(SERVER_MAX_ROWS + 7)
        server = Postgrest(rows)
        self.assertEqual(len(server("/rest/v1/match_report")), SERVER_MAX_ROWS)

    def test_supabase_all_returns_every_row_past_the_cap(self):
        rows = report_rows(SERVER_MAX_ROWS + 7)
        server = Postgrest(rows)
        with mock.patch.object(report_sync, "supabase", server):
            got = report_sync.supabase_all("/rest/v1/match_report?select=x")
        self.assertEqual(len(got), len(rows))
        self.assertEqual([r["match_id"] for r in got],
                         [r["match_id"] for r in rows])

    def test_supabase_all_pages_a_smaller_server_cap_too(self):
        """The cap belongs to the server, so stopping on a short page would
        be wrong for any max-rows below PAGE_SIZE."""
        rows = report_rows(SERVER_MAX_ROWS)
        server = Postgrest(rows, max_rows=report_sync.PAGE_SIZE // 3)
        with mock.patch.object(report_sync, "supabase", server):
            got = report_sync.supabase_all("/rest/v1/match_report")
        self.assertEqual(len(got), len(rows))

    def test_supabase_all_appends_its_query_correctly(self):
        seen = []

        def spy(path, method="GET", body=None):
            seen.append(path)
            return [] if len(seen) > 1 else report_rows(1)

        with mock.patch.object(report_sync, "supabase", spy):
            report_sync.supabase_all("/rest/v1/season_aggregate?select=kind")
        self.assertIn("select=kind&offset=0", seen[0])
        with mock.patch.object(report_sync, "supabase",
                               lambda p, method="GET", body=None: []):
            report_sync.supabase_all("/rest/v1/season_aggregate")

    def test_supabase_all_fails_loudly_when_offset_is_ignored(self):
        server = Postgrest(report_rows(10), honour_offset=False)
        with mock.patch.object(report_sync, "supabase", server):
            with self.assertRaises(RuntimeError):
                report_sync.supabase_all("/rest/v1/match_report")


class TestPendingReports(unittest.TestCase):
    """The boundary that matters: more already-synced rows than the cap."""

    LOCAL = SERVER_MAX_ROWS + 500
    SYNCED = SERVER_MAX_ROWS + 200

    def _mysql_out(self):
        head = "match_id\tschema_version\trevision"
        body = [f"{r['match_id']}\t8\t1" for r in report_rows(self.LOCAL)]
        return "\n".join([head] + body)

    def test_unpaged_read_would_resync_rows_past_the_cap(self):
        """Control: the defect this change removes, measured on the same
        fixture the fixed path uses."""
        server = Postgrest(report_rows(self.SYNCED))
        with mock.patch.object(report_sync, "mysql",
                               lambda q: self._mysql_out()):
            with mock.patch.object(report_sync, "supabase", server):
                have = {(r["match_id"], r["report_schema_version"],
                         r["revision"])
                        for r in server("/rest/v1/match_report")}
        self.assertEqual(len(have), SERVER_MAX_ROWS)
        self.assertEqual(self.LOCAL - len(have), 500)

    def test_pending_excludes_every_already_synced_row(self):
        server = Postgrest(report_rows(self.SYNCED))
        with mock.patch.object(report_sync, "mysql",
                               lambda q: self._mysql_out()):
            with mock.patch.object(report_sync, "supabase", server):
                todo = report_sync.pending_reports()
        self.assertEqual(len(todo), self.LOCAL - self.SYNCED)
        self.assertEqual(todo[0][0], f"m{self.SYNCED:05d}")
        self.assertTrue(server.calls > 1)


def aggregate_line(kind, payload_json, revision=1):
    return (f"{kind}\t{revision}\t2026-09-08 00:00:00\t3\t8\t"
            f"deadbeef\t{payload_json}")


class TestAggregateSanitization(unittest.TestCase):
    CLEAN = '{"rows": [{"name": "A", "team": 1, "kills": 2}]}'
    # A key name already listed in FORBIDDEN_KEY_PARTS; no identity value.
    FORBIDDEN = '{"rows": [{"name": "A", "player_id": 0}]}'

    def _run(self, lines, dry_run=False):
        posted = []

        def fake_supabase(path, method="GET", body=None):
            if method == "POST":
                posted.append(body)
                return None
            return []

        out = "\n".join(["kind\trevision\tgenerated_at\tn\tv\tsha\tpayload"]
                        + lines)
        with mock.patch.object(report_sync, "mysql", lambda q: out):
            with mock.patch.object(report_sync, "supabase", fake_supabase):
                return report_sync.sync_aggregates(dry_run), posted

    def test_clean_aggregate_syncs(self):
        """Positive control: without it, a passing rejection test could just
        mean nothing ever reaches the assertion."""
        synced, posted = self._run([aggregate_line("map_profiles", self.CLEAN)])
        self.assertEqual(synced, 1)
        self.assertEqual(len(posted), 1)

    def test_forbidden_key_aborts_before_any_post(self):
        with self.assertRaises(ValueError) as ctx:
            self._run([aggregate_line("map_profiles", self.FORBIDDEN)])
        self.assertIn("map_profiles", str(ctx.exception))

    def test_dry_run_asserts_too(self):
        """--dry-run is the rehearsal for the irreversible run; an aggregate
        it reports as ready must have passed the same gate."""
        with self.assertRaises(ValueError):
            self._run([aggregate_line("map_profiles", self.FORBIDDEN)],
                      dry_run=True)

    def test_dry_run_posts_nothing(self):
        synced, posted = self._run([aggregate_line("map_profiles", self.CLEAN)],
                                   dry_run=True)
        self.assertEqual((synced, posted), (1, []))


class TestSyncableKinds(unittest.TestCase):
    def test_head_to_head_is_not_syncable(self):
        self.assertNotIn("head_to_head", report_sync.SYNCABLE_AGGREGATE_KINDS)
        self.assertIn("map_profiles", report_sync.SYNCABLE_AGGREGATE_KINDS)

    def test_a_head_to_head_row_is_skipped_not_published(self):
        posted = []

        def fake_supabase(path, method="GET", body=None):
            if method == "POST":
                posted.append(body)
                return None
            return []

        out = "\n".join([
            "kind\trevision\tgenerated_at\tn\tv\tsha\tpayload",
            aggregate_line("head_to_head", '{"pairs": []}'),
            aggregate_line("map_profiles", '{"rows": []}'),
        ])
        with mock.patch.object(report_sync, "mysql", lambda q: out):
            with mock.patch.object(report_sync, "supabase", fake_supabase):
                synced = report_sync.sync_aggregates(False)
        self.assertEqual(synced, 1)
        self.assertEqual([b["kind"] for b in posted], ["map_profiles"])


if __name__ == "__main__":
    unittest.main()
