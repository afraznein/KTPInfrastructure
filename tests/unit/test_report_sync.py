"""Offline tests for scripts/report_sync.py (no MySQL, no network).

The script publishes to the public website and nothing pulls a row back, so
the properties under test here are the ones whose failure is irreversible:
that the already-synced set is read in full, and that no aggregate reaches
PostgREST without passing the forbidden-key assertion.
"""
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
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
        head = "match_id\tschema_version\trevision\tmatch_start\tofficial_start"
        body = [f"{r['match_id']}\t8\t1\t2026-09-14 21:00:00\t2026-09-14 21:00:00"
                for r in report_rows(self.LOCAL)]
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
                todo = report_sync.pending_reports("2026-09-13")
        self.assertEqual(len(todo), self.LOCAL - self.SYNCED)
        self.assertEqual(todo[0][0], f"m{self.SYNCED:05d}")
        self.assertTrue(server.calls > 1)


class TestReportRowTimestamps(unittest.TestCase):
    """The row POSTed here is the write. started_at lands in a timestamptz
    column, so it has to leave carrying an offset: sent naive, Postgres reads
    league time as UTC and every published label reads four hours early."""

    STARTED = "2026-09-14 21:00:00"
    MATCH = "1788919258-CHI1"

    def _posted_row(self):
        posted = []
        pending = ("match_id\tschema_version\trevision\tmatch_start\t"
                   "official_start\n"
                   f"{self.MATCH}\t9\t1\t{self.STARTED}\t{self.STARTED}")
        report = json.dumps({
            "schema_version": 9,
            "generated_at": "2026-09-14T21:05:00+00:00",
            "match_id": self.MATCH,
            "quality": {"status": "FAIL", "checks": []},
            "match": {"map_name": "dod_anzio", "started_at": self.STARTED,
                      "duration_seconds": 100, "halves_played": 2},
        })

        def fake_mysql(query):
            if "ktp_match_reports r" in query:
                return pending
            return "report\n" + report

        def fake_supabase(path, method="GET", body=None):
            if method == "POST":
                posted.append(body)
                return None
            return []

        with mock.patch.object(report_sync, "mysql", fake_mysql):
            with mock.patch.object(report_sync, "supabase", fake_supabase):
                report_sync.sync_reports(False, "2026-09-13")
        return posted[0]

    def test_started_at_is_written_with_its_offset(self):
        self.assertEqual(self._posted_row()["started_at"],
                         "2026-09-14T21:00:00-04:00")

    def test_the_naive_league_string_never_reaches_the_column(self):
        self.assertNotEqual(self._posted_row()["started_at"], self.STARTED)

    def test_generated_at_still_carries_utc(self):
        """Positive control in the same row: one of these stamps was already
        right, so finding an offset somewhere would not discriminate."""
        self.assertEqual(self._posted_row()["generated_at"],
                         "2026-09-14T21:05:00+00:00")


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


class TestSyncMmr(unittest.TestCase):
    RATING = {"mu": 30.0, "sigma": 5.0, "ordinal": 15.0}
    PLAYERS = [{"id": 1, "alias": "Ecl1ps3"}, {"id": 2, "alias": "gaul"}]

    def _run(self, ratings, dry_run=False, existing_revision=None,
            existing_sha=None, players=None, branch_date=None):
        posted = []

        def fake_get(url):
            if url == report_sync.MMR_RATINGS_URL:
                return ratings
            if url == report_sync.MMR_BRANCH_API:
                if branch_date is None:
                    return None
                return {"commit": {"commit": {"author": {"date": branch_date}}}}
            raise AssertionError(f"unexpected GET {url}")

        def fake_supabase(path, method="GET", body=None):
            if method == "POST":
                posted.append(body)
                return None
            if "offset=0" not in path:
                return []  # page 2 of anything: end the pagination
            if path.startswith("/rest/v1/player"):
                return players if players is not None else self.PLAYERS
            if path.startswith("/rest/v1/season_aggregate"):
                if existing_revision is None:
                    return []
                return [{"revision": existing_revision, "payload_sha256": existing_sha}]
            return []

        with mock.patch.object(report_sync, "_github_get", fake_get), \
                mock.patch.object(report_sync, "supabase", fake_supabase):
            synced = report_sync.sync_mmr(dry_run)
        return synced, posted

    def test_nothing_published_yet_syncs_nothing(self):
        synced, posted = self._run(None)
        self.assertEqual((synced, posted), (0, []))

    def test_a_qualified_player_publishes_with_the_conservative_score(self):
        ratings = {"1": {**self.RATING, "matches": 3}}
        synced, posted = self._run(ratings, branch_date="2026-09-16T12:00:00Z")
        self.assertEqual(synced, 1)
        self.assertEqual(len(posted), 1)
        row = posted[0]
        self.assertEqual(row["kind"], "mmr_openskill")
        self.assertEqual(row["revision"], 1)
        self.assertEqual(row["source_report_count"], 0)
        self.assertEqual(row["report_schema_version"], 1)
        self.assertEqual(row["generated_at"], "2026-09-16T12:00:00Z")
        p = row["payload"]["players"][0]
        self.assertEqual(p["name"], "Ecl1ps3")
        self.assertEqual(p["matches"], 3)
        self.assertEqual(p["rating"], 30.0)
        self.assertEqual(p["uncertainty"], 5.0)
        # mu - 2*sigma = 30 - 10 = 20, MMR_CONSERVATISM's own value
        self.assertEqual(p["conservative"], 20.0)

    def test_below_min_matches_is_omitted_not_flagged(self):
        ratings = {"1": {**self.RATING, "matches": report_sync.MMR_MIN_MATCHES - 1}}
        synced, posted = self._run(ratings)
        self.assertEqual((synced, posted), (0, []))

    def test_a_rating_with_no_website_account_is_left_out_not_guessed(self):
        ratings = {"999": {**self.RATING, "matches": 5}}
        synced, posted = self._run(ratings, branch_date="2026-09-16T12:00:00Z")
        self.assertEqual((synced, posted), (0, []))

    def test_unchanged_payload_is_not_reposted(self):
        ratings = {"1": {**self.RATING, "matches": 3}}
        payload = {
            "provisional": True,
            "notice": "OpenSkill ratings recompute from the full season each run.",
            "method": "openskill-plackettluce",
            "min_matches": report_sync.MMR_MIN_MATCHES,
            "players": [{"name": "Ecl1ps3", "matches": 3, "rating": 30.0,
                        "uncertainty": 5.0, "conservative": 20.0}],
        }
        sha = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        synced, posted = self._run(ratings, existing_revision=3, existing_sha=sha)
        self.assertEqual((synced, posted), (0, []))

    def test_a_changed_payload_gets_the_next_revision(self):
        ratings = {"1": {**self.RATING, "matches": 3}}
        synced, posted = self._run(
            ratings, existing_revision=3, existing_sha="stale-sha",
            branch_date="2026-09-16T12:00:00Z")
        self.assertEqual(synced, 1)
        self.assertEqual(posted[0]["revision"], 4)

    def test_dry_run_posts_nothing(self):
        ratings = {"1": {**self.RATING, "matches": 3}}
        synced, posted = self._run(ratings, dry_run=True)
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


class TestSinceFloor(unittest.TestCase):
    """A publishable report for a pre-season match must never reach the site."""

    FLOOR = "2026-09-13"
    # (match_id, match_start, official_start): every match here is official.
    ROWS = [
        ("1.3-6774-ATL1", "2026-09-09 20:54:06", "2026-09-09 20:54:06"),
        ("1.3-7000-ATL1", "2026-09-13 00:00:00", "2026-09-13 00:00:00"),
        ("1.3-7001-DAL1", "2026-09-14 21:00:00", "2026-09-14 21:00:00"),
        ("orphan-no-match-row", "NULL", "NULL"),
    ]

    def _mysql_out(self):
        head = "match_id\tschema_version\trevision\tmatch_start\tofficial_start"
        return "\n".join([head] + [f"{m}\t9\t1\t{s}\t{o}"
                                   for m, s, o in self.ROWS])

    def _pending(self, since):
        with mock.patch.object(report_sync, "mysql",
                               lambda q: self._mysql_out()):
            with mock.patch.object(report_sync, "supabase",
                                   lambda p, method="GET", body=None: []):
                return [m for m, _, _ in report_sync.pending_reports(since)]

    def test_pre_floor_report_is_held_back(self):
        self.assertNotIn("1.3-6774-ATL1", self._pending(self.FLOOR))

    def test_on_and_after_floor_reports_sync(self):
        """Positive control: without it, holding back everything would pass."""
        self.assertEqual(self._pending(self.FLOOR),
                         ["1.3-7000-ATL1", "1.3-7001-DAL1"])

    def test_report_without_a_match_row_is_held_back(self):
        self.assertNotIn("orphan-no-match-row", self._pending("2000-01-01"))

    def test_query_reads_the_same_column_generate_does(self):
        seen = []
        with mock.patch.object(report_sync, "mysql",
                               lambda q: seen.append(q) or self._mysql_out()):
            with mock.patch.object(report_sync, "supabase",
                                   lambda p, method="GET", body=None: []):
                report_sync.pending_reports(self.FLOOR)
        self.assertIn("m.start_time", seen[0])
        self.assertIn("ktp_matches", seen[0])

    def test_no_floor_refuses_to_run(self):
        env = {"KTP_SUPABASE_URL": "https://x.test",
               "KTP_SUPABASE_SECRET_KEY": "k"}

        def must_not_run(*a, **k):
            raise AssertionError("synced without a floor")

        with mock.patch.dict("os.environ", env):
            with mock.patch.object(report_sync, "sync_reports", must_not_run):
                with mock.patch.object(report_sync, "sync_aggregates",
                                       must_not_run):
                    with self.assertRaises(SystemExit) as ctx:
                        report_sync.main(["--dry-run"])
        self.assertEqual(ctx.exception.code, 2)

    def test_floor_rejects_non_date_shape(self):
        for bad in ("2026-09-13'; DROP TABLE x; --", "2026/09/13", ""):
            with self.assertRaises(SystemExit):
                report_sync.main(["--since", bad])


class TestMatchTypeScope(unittest.TestCase):
    """A publishable report for an in-date scrim or 12man must never reach the
    site: sync applies the same official-type rule generate discovers by."""

    FLOOR = "2026-09-13"
    ROWS = [
        # an official match after the floor: the positive control
        ("1.3-7001-DAL1", "2026-09-14 21:00:00", "2026-09-14 21:00:00"),
        # a 12man after the floor: rows exist, no official-type half
        ("1.3-7002-NY1", "2026-09-14 22:00:00", "NULL"),
        # official half before the floor, a later non-official half after it
        ("1.3-6990-ATL1", "2026-09-14 20:00:00", "2026-09-12 20:00:00"),
    ]

    def _mysql_out(self):
        head = "match_id\tschema_version\trevision\tmatch_start\tofficial_start"
        return "\n".join([head] + [f"{m}\t9\t1\t{s}\t{o}"
                                   for m, s, o in self.ROWS])

    def _run(self):
        seen, printed = [], []
        with mock.patch.object(report_sync, "mysql",
                               lambda q: seen.append(q) or self._mysql_out()):
            with mock.patch.object(report_sync, "supabase",
                                   lambda p, method="GET", body=None: []):
                with mock.patch("builtins.print",
                                lambda *a, **k: printed.append(" ".join(
                                    str(x) for x in a))):
                    todo = [m for m, _, _ in
                            report_sync.pending_reports(self.FLOOR)]
        return todo, seen, printed

    def test_only_the_official_in_date_match_syncs(self):
        todo, _, _ = self._run()
        self.assertEqual(todo, ["1.3-7001-DAL1"])

    def test_in_date_12man_is_held_back_and_counted(self):
        _, _, printed = self._run()
        self.assertIn("held back by match_type (official only: 0, 4): "
                      "1 publishable report(s)", printed)

    def test_official_half_must_itself_be_after_the_floor(self):
        _, _, printed = self._run()
        self.assertIn("held back by --since 2026-09-13: "
                      "1 publishable report(s)", printed)

    def test_query_filters_on_the_official_set(self):
        _, seen, _ = self._run()
        self.assertIn("m.match_type IN (0, 4)", seen[0])


def http_error(code):
    return urllib.error.HTTPError("https://x.test/rest/v1/match_report", code,
                                  "err", {}, io.BytesIO(b""))


class Sender:
    """Stands in for the HTTP round-trip: replays outcomes, counts attempts."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, url, method, data, headers):
        self.calls += 1
        outcome = self.outcomes[min(self.calls, len(self.outcomes)) - 1]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class TestTransientReadRetry(unittest.TestCase):
    """Production shape: a gateway 504 on a GET of an empty table, which the
    next attempt answers with []."""

    ENV = {"KTP_SUPABASE_URL": "https://x.test", "KTP_SUPABASE_SECRET_KEY": "k"}

    def _call(self, sender, path="/rest/v1/match_report?select=match_id",
              method="GET", body=None):
        sleeps, err = [], io.StringIO()
        with mock.patch.dict("os.environ", self.ENV), \
                mock.patch.object(report_sync, "_send", sender), \
                mock.patch.object(report_sync.time, "sleep", sleeps.append), \
                mock.patch("sys.stderr", err):
            try:
                return report_sync.supabase(path, method, body), sleeps, err.getvalue()
            except Exception as exc:
                exc.sleeps, exc.stderr = sleeps, err.getvalue()
                raise

    def test_a_504_on_a_read_is_retried_and_the_run_carries_on(self):
        sender = Sender(http_error(504), [])
        got, sleeps, err = self._call(sender)
        self.assertEqual((got, sender.calls), ([], 2))
        self.assertEqual(sleeps, [report_sync.READ_RETRY_DELAYS[0]])
        self.assertIn("HTTP Error 504", err)
        self.assertIn("retry 1/", err)

    def test_every_retry_is_logged_and_the_query_string_is_not(self):
        sender = Sender(http_error(502), http_error(503), TimeoutError("t"), [])
        _, sleeps, err = self._call(sender)
        self.assertEqual(sleeps, list(report_sync.READ_RETRY_DELAYS))
        self.assertEqual(err.count("retry "), 3)
        self.assertNotIn("select=", err)

    def test_a_persistent_outage_still_raises_after_bounded_retries(self):
        sender = Sender(http_error(504))
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._call(sender)
        self.assertEqual(sender.calls, len(report_sync.READ_RETRY_DELAYS) + 1)
        self.assertEqual(ctx.exception.sleeps, list(report_sync.READ_RETRY_DELAYS))

    def test_timeouts_and_dropped_connections_are_retried(self):
        for exc in (TimeoutError("timed out"),
                    urllib.error.URLError("connection reset"),
                    ConnectionResetError("reset")):
            sender = Sender(exc, [{"kind": "map_profiles"}])
            got, _, _ = self._call(sender)
            self.assertEqual((got, sender.calls), ([{"kind": "map_profiles"}], 2))

    def test_a_client_error_is_not_retried(self):
        """Control: without it, 'retries' could mean retrying everything,
        including a revoked key that no wait will fix."""
        for code in (400, 401, 404, 409):
            sender = Sender(http_error(code), [])
            with self.assertRaises(urllib.error.HTTPError):
                self._call(sender)
            self.assertEqual(sender.calls, 1, code)

    def test_a_post_is_never_retried(self):
        sender = Sender(http_error(504), None)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._call(sender, "/rest/v1/match_report", "POST", {"match_id": "m"})
        self.assertEqual((sender.calls, ctx.exception.sleeps), (1, []))

    def test_supabase_all_survives_a_504_on_the_empty_first_page(self):
        sender = Sender(http_error(504), [])
        with mock.patch.dict("os.environ", self.ENV), \
                mock.patch.object(report_sync, "_send", sender), \
                mock.patch.object(report_sync.time, "sleep", lambda s: None), \
                mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(report_sync.supabase_all("/rest/v1/match_report"), [])
        self.assertEqual(sender.calls, 2)

    def test_main_fails_when_the_outage_outlasts_the_retries(self):
        head = "match_id\tschema_version\trevision\tmatch_start\tofficial_start"
        with mock.patch.dict("os.environ", self.ENV), \
                mock.patch.object(report_sync, "mysql", lambda q: head), \
                mock.patch.object(report_sync, "_send", Sender(http_error(504))), \
                mock.patch.object(report_sync.time, "sleep", lambda s: None), \
                mock.patch("sys.stderr", io.StringIO()), \
                mock.patch("builtins.print"):
            with self.assertRaises(urllib.error.HTTPError):
                report_sync.main(["--since", "2026-09-13"])


class FakeResponse:
    """Stands in for the `with urlopen(...) as resp:` context manager."""

    def read(self):
        return b'{"ok":true,"scope":"ktp","invalidated":["match-reports"]}'

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestRevalidateSite(unittest.TestCase):
    """report_sync.revalidate_site() in isolation: the request it builds and
    how it behaves under failure. Never allowed to raise -- that is the
    property the caller (main()) depends on."""

    WITH_SECRET = {"KTP_SITE_REVALIDATE_SECRET": "s3cr3t"}

    def test_skips_with_a_warning_when_the_secret_is_unset(self):
        err = io.StringIO()
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch("sys.stderr", err), \
                mock.patch("urllib.request.urlopen") as urlopen:
            report_sync.revalidate_site()
        urlopen.assert_not_called()
        self.assertIn("KTP_SITE_REVALIDATE_SECRET", err.getvalue())

    def test_sends_the_scope_and_secret_the_endpoint_expects(self):
        seen = []

        def fake_urlopen(req, timeout=None):
            seen.append(req)
            return FakeResponse()

        with mock.patch.dict("os.environ", self.WITH_SECRET), \
                mock.patch("urllib.request.urlopen", fake_urlopen):
            report_sync.revalidate_site()
        self.assertEqual(len(seen), 1)
        req = seen[0]
        self.assertEqual(req.full_url,
                         "https://ktpleague.gg/api/internal/revalidate")
        self.assertEqual(req.get_header("X-internal-revalidate"), "s3cr3t")
        self.assertEqual(json.loads(req.data), {"scope": "ktp"})

    def test_the_secret_value_never_reaches_a_log_line(self):
        err = io.StringIO()
        with mock.patch.dict("os.environ", self.WITH_SECRET), \
                mock.patch("sys.stderr", err), \
                mock.patch("urllib.request.urlopen",
                           side_effect=http_error(401)):
            report_sync.revalidate_site()
        self.assertNotIn("s3cr3t", err.getvalue())

    def test_a_401_is_not_retried(self):
        err = io.StringIO()
        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(1)
            raise http_error(401)

        with mock.patch.dict("os.environ", self.WITH_SECRET), \
                mock.patch("sys.stderr", err), \
                mock.patch("urllib.request.urlopen", fake_urlopen):
            report_sync.revalidate_site()  # must not raise
        self.assertEqual(len(calls), 1)
        self.assertIn("FAILED", err.getvalue())

    def test_a_5xx_is_retried_once_then_gives_up(self):
        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(1)
            raise http_error(503)

        with mock.patch.dict("os.environ", self.WITH_SECRET), \
                mock.patch("sys.stderr", io.StringIO()), \
                mock.patch("urllib.request.urlopen", fake_urlopen):
            report_sync.revalidate_site()  # must not raise
        self.assertEqual(len(calls), 2)

    def test_a_timeout_is_retried_once_then_gives_up(self):
        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(1)
            raise TimeoutError("timed out")

        with mock.patch.dict("os.environ", self.WITH_SECRET), \
                mock.patch("sys.stderr", io.StringIO()), \
                mock.patch("urllib.request.urlopen", fake_urlopen):
            report_sync.revalidate_site()  # must not raise
        self.assertEqual(len(calls), 2)

    def test_succeeds_on_the_retry(self):
        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(1)
            if len(calls) == 1:
                raise http_error(502)
            return FakeResponse()

        with mock.patch.dict("os.environ", self.WITH_SECRET), \
                mock.patch("sys.stderr", io.StringIO()), \
                mock.patch("urllib.request.urlopen", fake_urlopen):
            report_sync.revalidate_site()
        self.assertEqual(len(calls), 2)


class TestRevalidateTrigger(unittest.TestCase):
    """main()'s decision whether to call revalidate_site() at all."""

    ENV = {"KTP_SUPABASE_URL": "https://x.test", "KTP_SUPABASE_SECRET_KEY": "k"}

    def _run(self, argv, n, p=0):
        calls = []
        with mock.patch.dict("os.environ", self.ENV), \
                mock.patch.object(report_sync, "sync_reports",
                                  lambda dry_run, since: n), \
                mock.patch.object(report_sync, "sync_aggregates",
                                  lambda dry_run: 0), \
                mock.patch.object(report_sync, "sync_mmr",
                                  lambda dry_run: p), \
                mock.patch.object(report_sync, "revalidate_site",
                                  lambda: calls.append(1)):
            rc = report_sync.main(argv)
        return rc, calls

    def test_called_once_after_a_sync_that_changed_something(self):
        rc, calls = self._run(["--since", "2026-09-13"], n=2)
        self.assertEqual((rc, calls), (0, [1]))

    def test_called_once_when_only_mmr_changed(self):
        """A week with no new reports but a fresh MMR publish still needs
        the site's cache dropped -- the profile card is stale otherwise."""
        rc, calls = self._run(["--since", "2026-09-13"], n=0, p=1)
        self.assertEqual((rc, calls), (0, [1]))

    def test_not_called_when_nothing_changed(self):
        rc, calls = self._run(["--since", "2026-09-13"], n=0)
        self.assertEqual((rc, calls), (0, []))

    def test_not_called_on_a_dry_run_even_with_rows_pending(self):
        """--dry-run never POSTs to Supabase, so there is nothing for the
        site to see yet -- revalidating would purge a still-accurate cache."""
        rc, calls = self._run(["--since", "2026-09-13", "--dry-run"], n=3)
        self.assertEqual((rc, calls), (0, []))


class TestRevalidateNeverFailsTheRun(unittest.TestCase):
    """End to end through main(): a broken revalidate must not turn a
    successful sync into a non-zero exit or a raised exception."""

    ENV = {"KTP_SUPABASE_URL": "https://x.test", "KTP_SUPABASE_SECRET_KEY": "k",
          "KTP_SITE_REVALIDATE_SECRET": "s3cr3t"}

    def _run_main(self, urlopen_side_effect):
        with mock.patch.dict("os.environ", self.ENV), \
                mock.patch.object(report_sync, "sync_reports",
                                  lambda dry_run, since: 1), \
                mock.patch.object(report_sync, "sync_aggregates",
                                  lambda dry_run: 0), \
                mock.patch.object(report_sync, "sync_mmr",
                                  lambda dry_run: 0), \
                mock.patch("sys.stderr", io.StringIO()), \
                mock.patch("urllib.request.urlopen",
                           side_effect=urlopen_side_effect):
            return report_sync.main(["--since", "2026-09-13"])

    def test_run_succeeds_when_revalidate_gets_a_401(self):
        self.assertEqual(self._run_main(http_error(401)), 0)

    def test_run_succeeds_when_revalidate_gets_5xx_on_every_attempt(self):
        self.assertEqual(self._run_main(http_error(503)), 0)

    def test_run_succeeds_when_revalidate_times_out_on_every_attempt(self):
        self.assertEqual(self._run_main(TimeoutError("timed out")), 0)


class TestExceptHook(unittest.TestCase):
    """Under `python3 -m`, a foreign excepthook (apport, on the data server)
    must not replace the real traceback."""

    HOOK = ("import sys\n"
            "sys.excepthook = lambda *a: sys.stderr.write('FOREIGN-HOOK\\n')\n")

    def _run(self, args):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "sitecustomize.py").write_text(self.HOOK)
            env = dict(os.environ, PYTHONPATH=tmp, PATH=tmp,
                       KTP_SUPABASE_URL="https://x.test",
                       KTP_SUPABASE_SECRET_KEY="k")
            return subprocess.run([sys.executable, *args], cwd=root, env=env,
                                  capture_output=True, text=True, timeout=120)

    def test_control_the_injected_hook_is_active(self):
        proc = self._run(["-c", "raise RuntimeError('control')"])
        self.assertIn("FOREIGN-HOOK", proc.stderr)

    def test_report_sync_prints_its_own_traceback(self):
        # PATH holds no mysql binary, so the first query raises.
        proc = self._run(["-m", "scripts.report_sync", "--since", "2026-09-13"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("FOREIGN-HOOK", proc.stderr)
        self.assertIn("Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main()
