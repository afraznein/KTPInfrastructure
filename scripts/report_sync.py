"""Sync publishable match reports + season aggregates to the website Supabase.

Runs on the data server after report_service.py (cron, same box). Reads the
latest publishable row per match from ktp_match_reports (migration 026),
sanitizes it with analytics_report_dto.sanitize_report (whitelist DTO, names only,
no ids), and inserts missing rows into the website's Supabase `ktp` schema via
PostgREST. Latest season aggregates run through the same forbidden-key
assertion before insert; a kind whose builder still emits ids fails the run
rather than publishing.

Stateless and idempotent: asks Supabase which (match_id, schema, revision)
rows exist, inserts only the missing ones. Nothing is updated or deleted.

Also syncs the mmr_openskill season_aggregate (see sync_mmr()) -- a different
source from every other kind here: not this box's MySQL, but the public
mmr-ratings git branch scripts/mmr/run_weekly.py publishes to from CI. Same
idempotent shape (compares a payload hash, skips an unchanged publish), just
a different upstream.

Environment (operator-provisioned file, e.g. /etc/ktp/report-sync.env):
  KTP_SUPABASE_URL=https://<project>.supabase.co
  KTP_SUPABASE_SECRET_KEY=<service role secret; never the publishable key>
  KTP_SITE_REVALIDATE_SECRET=<INTERNAL_WARM_SECRET; optional, see revalidate_site()>

After a run that actually POSTs a new row to ktp.match_report, revalidate_site()
tells ktpleague.gg to drop its cache of the match-report pages. Without it a
synced report sits behind the site's cacheLife("hours") read until that cache
entry happens to turn over on its own -- up to about an hour. This step is
best-effort: it logs loudly and moves on rather than failing a run that already
committed rows.

Usage (from the KTPInfrastructure repo root):
  python3 -m scripts.report_sync --since 2026-09-13 [--dry-run]

--since is required, and only in-season reports are pushed: an official match
type (.ktp, .ktpOT) with a half on or after the floor. That is the scope
`report_service generate` discovers matches by, defined once in
scripts/report_scope.py, and it is what keeps a report written outside
generate's discovery (an explicit match id, a manual test run) off the website.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from scripts.analytics_report_dto import assert_sanitized, sanitize_report
from scripts.player_alias import apply_aliases, fetch_alias_index
from scripts.report_scope import (
    IN_SCOPE, classify, match_scope_columns, print_held)
from scripts.report_service import _os_user

DATABASE = "hlstatsx"
# Every kind here is name-keyed; database ids never cross to the website
# (2026-08-29 handover). Add a kind only after its builder emits names.
# head_to_head is deliberately absent: its pairs are still pid-keyed.
#
# mmr_openskill is NOT in this set. Every kind here comes from
# ktp_web_season_aggregates (this box's own MySQL), built by a job that runs
# here too. The OpenSkill ladder runs somewhere that deliberately has no
# database access at all (scripts/mmr/run_weekly.py, in CI, on public website
# data only) and publishes to its own public git branch instead -- see
# sync_mmr() below, which reads that branch, not MySQL.
SYNCABLE_AGGREGATE_KINDS = {"map_profiles", "leaderboard_ktpr_v22",
                            "season_positional", "season_spatial"}

# scripts/mmr/run_weekly.py publishes here (see mmr-weekly.yml's own comment
# on why: main is a protected branch a bot push can never satisfy). Public
# repo, public branch -- no auth needed to read it, same as the ladder's own
# "no game-server credentials" rule.
MMR_RATINGS_URL = "https://raw.githubusercontent.com/afraznein/KTPInfrastructure/mmr-ratings/ratings_current.json"
MMR_BRANCH_API = "https://api.github.com/repos/afraznein/KTPInfrastructure/branches/mmr-ratings"
# Players below this are omitted from the published payload entirely, not
# flagged -- the website never has to tell "not enough matches" apart from
# "nothing published yet". Matches leaderboard_ktpr_v22's own threshold.
MMR_MIN_MATCHES = 3
# mu - k*sigma: rate a player as if they were at the low end of plausible,
# so two matches of winning cannot outrank a settled record. Mirrors
# scripts/mmr/seeding_report.py's own CONSERVATISM exactly. Not imported --
# scripts/mmr/ has no __init__.py and its own files import each other as flat
# siblings (assuming scripts/mmr/ itself is on sys.path), which this file's
# package-style `python3 -m scripts.report_sync` invocation cannot reach
# cleanly. Keep the two constants in sync by hand if this one ever changes.
MMR_CONSERVATISM = 2.0

# Kept under PostgREST's default max-rows so a page is never server-truncated.
PAGE_SIZE = 500
# A server that ignores `offset` would otherwise page forever on one result.
MAX_PAGES = 4000

# The endpoint's body schema only accepts these four (searse/keep-the-prac
# src/app/api/internal/revalidate/route.ts); "match-reports" is a TAG name
# inside scopes.ts, not a POST-able scope. "ktp" is the narrowest of the four
# whose tag list carries MATCH_REPORTS_TAG.
REVALIDATE_SCOPE = "ktp"
REVALIDATE_TIMEOUT = 10

SINCE_RE = re.compile(r"\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}:\d{2})?")


def since_arg(value: str) -> str:
    if not SINCE_RE.fullmatch(value):
        raise argparse.ArgumentTypeError(
            f"must be 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS', got {value!r}")
    return value


def mysql(query: str) -> str:
    proc = subprocess.run(
        ["mysql", "--batch", "--raw", "--default-character-set=utf8mb4",
         f"--user={_os_user()}", DATABASE],
        input=query, capture_output=True, text=True, timeout=600,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"mysql rc={proc.returncode}: {proc.stderr[-800:]}")
    return proc.stdout


# Supabase's gateway 504s the odd read of an empty table; the next attempt answers.
READ_RETRY_DELAYS = (5, 15, 45)
RETRYABLE_STATUS = frozenset({500, 502, 503, 504})


def _send(url: str, method: str, data, headers: dict):
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method=method)
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else None


def _transient(exc: Exception) -> bool:
    # HTTPError is a URLError, so the status check has to come first.
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in RETRYABLE_STATUS
    return isinstance(exc, (urllib.error.URLError, TimeoutError,
                            ConnectionError))


def supabase(path: str, method: str = "GET", body=None):
    url = os.environ["KTP_SUPABASE_URL"].rstrip("/") + path
    key = os.environ["KTP_SUPABASE_SECRET_KEY"]
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept-Profile": "ktp",
        "Content-Profile": "ktp",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None
    # Never a POST: a 504 does not say whether the insert committed, and the
    # next tick's read-then-diff is the safe retry.
    delays = READ_RETRY_DELAYS if method == "GET" else ()
    for attempt, delay in enumerate((*delays, None), 1):
        try:
            return _send(url, method, data, headers)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if delay is None or not _transient(exc):
                raise
            print(f"supabase {method} {path.partition('?')[0]}: {exc}; "
                  f"retry {attempt}/{len(delays)} in {delay}s",
                  file=sys.stderr)
            time.sleep(delay)


def supabase_all(path: str) -> list[dict]:
    """Every row at `path`, walked page by page.

    PostgREST truncates a response at its own max-rows and says so only in
    Content-Range, so an unpaged read silently returns a prefix — and a short
    prefix of the already-synced set re-POSTs rows that violate a unique key.
    Stop on an empty page, never on a short one: the cap is the server's, not
    ours, and a short page is what truncation looks like.
    """
    joiner = "&" if "?" in path else "?"
    rows: list[dict] = []
    offset = 0
    for _ in range(MAX_PAGES):
        page = supabase(f"{path}{joiner}offset={offset}&limit={PAGE_SIZE}")
        if not page:
            return rows
        rows.extend(page)
        offset += len(page)
    raise RuntimeError(f"{path}: still returning rows after {MAX_PAGES} pages")


def pending_reports(since: str) -> list[tuple[str, int, int]]:
    """Latest publishable (match_id, schema_version, revision) per in-season
    match, minus rows Supabase already has."""
    out = mysql(
        "SELECT r.match_id, r.schema_version, r.revision, "
        f"{match_scope_columns('r')} FROM "
        "ktp_match_reports r JOIN (SELECT match_id, MAX(id) AS id "
        "FROM ktp_match_reports WHERE publishable = 1 GROUP BY match_id) "
        "latest ON latest.id = r.id"
    )
    rows = [f for ln in out.strip().splitlines()[1:]
            if (f := ln.split("\t")) and len(f) == 5]
    local, held = set(), {}
    for f in rows:
        verdict = classify(f[3], f[4], since)
        if verdict == IN_SCOPE:
            local.add((f[0], int(f[1]), int(f[2])))
        else:
            held[verdict] = held.get(verdict, 0) + 1
    print_held(held, since)
    have = {(row["match_id"], row["report_schema_version"], row["revision"])
            for row in supabase_all(
                "/rest/v1/match_report"
                "?select=match_id,report_schema_version,revision")}
    return sorted(local - have)


def fetch_report(match_id: str, schema_version: int, revision: int) -> dict:
    hexed = match_id.encode("utf-8").hex()
    out = mysql(
        "SELECT report FROM ktp_match_reports WHERE match_id = "
        f"CONVERT(UNHEX('{hexed}') USING utf8mb4) "
        f"AND schema_version = {schema_version} AND revision = {revision}"
    )
    lines = out.splitlines()
    return json.loads(lines[1])


def sync_reports(dry_run: bool, since: str) -> int:
    todo = pending_reports(since)
    print(f"reports to sync: {len(todo)}")
    alias_index = fetch_alias_index(supabase_all) if todo else {}
    print(f"website aliases: {len(alias_index)} steam ids")
    for match_id, schema_version, revision in todo:
        report = fetch_report(match_id, schema_version, revision)
        # Publish the canonical website alias, not whatever name was typed
        # into the game that night. Unmatched players keep theirs.
        alias_stats = apply_aliases(report, alias_index)
        if alias_stats["unresolved"]:
            print(f"  {match_id}: {len(alias_stats['unresolved'])} of "
                  f"{alias_stats['roster']} players have no website account: "
                  + ", ".join(alias_stats["unresolved"]))
        if alias_stats["ambiguous_names"]:
            print(f"  {match_id}: name shared by two players, left as played: "
                  + ", ".join(alias_stats["ambiguous_names"]))
        dto = sanitize_report(report)
        canonical = json.dumps(dto, ensure_ascii=False, sort_keys=True)
        row = {
            "match_id": match_id,
            "report_schema_version": schema_version,
            "revision": revision,
            "contract_version": dto["contract_version"],
            "generated_at": dto["source"]["generated_at"],
            "map_name": dto["match"]["map_name"],
            "started_at": dto["match"]["started_at"],
            "payload_sha256": hashlib.sha256(
                canonical.encode("utf-8")).hexdigest(),
            "payload": dto,
        }
        if dry_run:
            print(f"  DRY {match_id} v{schema_version} r{revision}")
            continue
        supabase("/rest/v1/match_report", "POST", row)
        print(f"  synced {match_id} v{schema_version} r{revision}")
    return len(todo)


def sync_aggregates(dry_run: bool) -> int:
    out = mysql(
        "SELECT a.kind, a.revision, a.generated_at, a.source_report_count, "
        "a.report_schema_version, a.payload_sha256, a.payload FROM "
        "ktp_web_season_aggregates a JOIN (SELECT kind, MAX(id) AS id "
        "FROM ktp_web_season_aggregates GROUP BY kind) latest "
        "ON latest.id = a.id"
    )
    lines = out.strip().splitlines()[1:]
    have = {(row["kind"], row["revision"])
            for row in supabase_all(
                "/rest/v1/season_aggregate?select=kind,revision")}
    synced = 0
    for ln in lines:
        (kind, revision, generated_at, source_count, schema_version,
         sha, payload) = ln.split("\t", 6)
        if kind not in SYNCABLE_AGGREGATE_KINDS:
            continue
        if (kind, int(revision)) in have:
            continue
        # Reports get this inside sanitize_report; aggregates are inserted as
        # built, so this is their only gate. Runs before the dry-run branch so
        # --dry-run cannot report an unpublishable aggregate as ready.
        body = json.loads(payload)
        try:
            assert_sanitized(body)
        except ValueError as exc:
            raise ValueError(f"aggregate {kind} r{revision}: {exc}") from exc
        if dry_run:
            print(f"  DRY aggregate {kind} r{revision}")
            synced += 1
            continue
        supabase("/rest/v1/season_aggregate", "POST", {
            "kind": kind, "revision": int(revision),
            "generated_at": generated_at,
            "source_report_count": int(source_count),
            "report_schema_version": int(schema_version),
            "payload_sha256": sha,
            "payload": body,
        })
        print(f"  synced aggregate {kind} r{revision}")
        synced += 1
    return synced


def _github_get(url: str):
    """Unauthenticated GET against a public GitHub URL (raw content or API).

    No token: the ladder's own rule ("no game-server credentials") extends to
    reading it back -- this is public data on a public branch. A 404 means
    "nothing published yet" (a fresh deploy, or a week with no completed
    matches), which is a normal state, not an error.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "ktp-report-sync"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def sync_mmr(dry_run: bool) -> int:
    """Translate the OpenSkill ladder's raw output into the mmr_openskill
    season_aggregate row the website's player-profile card reads, and
    publish it if it has changed.

    The ladder (scripts/mmr/run_weekly.py) publishes to its own public git
    branch, keyed by the website's raw player_id and carrying no alias, no
    display threshold, and no conservative rank score -- none of which
    belong in that pipeline, which recomputes from scratch every run and has
    no reason to know the website's own display conventions. This is that
    translation, the one place those two things are allowed to meet.
    """
    raw = _github_get(MMR_RATINGS_URL)
    if raw is None:
        print("  mmr: no ratings published on mmr-ratings yet -- nothing to sync")
        return 0

    players_by_id = {row["id"]: row["alias"]
                     for row in supabase_all("/rest/v1/player?select=id,alias")}

    players, unresolved = [], 0
    for pid_str, r in raw.items():
        matches = r.get("matches", 0)
        if matches < MMR_MIN_MATCHES:
            continue
        alias = players_by_id.get(int(pid_str))
        if alias is None:
            unresolved += 1
            continue
        mu, sigma = float(r["mu"]), float(r["sigma"])
        players.append({
            "name": alias,
            "matches": matches,
            "rating": mu,
            "uncertainty": sigma,
            "conservative": round(mu - MMR_CONSERVATISM * sigma, 2),
        })
    if unresolved:
        print(f"  mmr: {unresolved} rated player id(s) have no website account "
              "-- left out, not guessed")
    if not players:
        print("  mmr: no player has reached the display threshold yet "
              f"({MMR_MIN_MATCHES} matches) -- nothing to sync")
        return 0
    players.sort(key=lambda p: -p["conservative"])

    payload = {
        "provisional": True,
        "notice": "OpenSkill ratings recompute from the full season each run.",
        "method": "openskill-plackettluce",
        "min_matches": MMR_MIN_MATCHES,
        "players": players,
    }
    assert_sanitized(payload)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    existing = supabase_all(
        "/rest/v1/season_aggregate?select=revision,payload_sha256"
        "&kind=eq.mmr_openskill&order=revision.desc&limit=1")
    if existing and existing[0]["payload_sha256"] == sha:
        print("  mmr: unchanged since the last publish -- nothing to sync")
        return 0
    revision = (existing[0]["revision"] + 1) if existing else 1

    if dry_run:
        print(f"  DRY aggregate mmr_openskill r{revision} ({len(players)} players)")
        return 1

    branch = _github_get(MMR_BRANCH_API)
    generated_at = (
        (branch or {}).get("commit", {}).get("commit", {})
        .get("author", {}).get("date")
        or datetime.now(timezone.utc).isoformat()
    )
    supabase("/rest/v1/season_aggregate", "POST", {
        "kind": "mmr_openskill",
        "revision": revision,
        "generated_at": generated_at,
        # Not built from reports -- see SYNCABLE_AGGREGATE_KINDS's own
        # comment. Both columns are NOT NULL (season_aggregate_source_count_
        # nonneg, _schema_version_positive), so 0 / 1 are the honest stand-in
        # values for a kind this constraint was never written with in mind.
        "source_report_count": 0,
        "report_schema_version": 1,
        "payload_sha256": sha,
        "payload": payload,
    })
    print(f"  synced aggregate mmr_openskill r{revision} ({len(players)} players)")
    return 1


def _revalidate_transient(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError))


def revalidate_site() -> None:
    """Tell ktpleague.gg its match-report cache is stale.

    Best-effort only -- by the time this runs, sync_reports() has already
    committed rows to Supabase, so a failure here must never fail the run
    (report_service.log alerting on a run this step killed would train
    everyone to ignore the alert). One retry, only for a transient failure;
    a bad secret (401) or a bad request (4xx) is not worth a second attempt.
    """
    secret = os.environ.get("KTP_SITE_REVALIDATE_SECRET")
    if not secret:
        print("KTP_SITE_REVALIDATE_SECRET is unset; skipping the site "
              "revalidate -- the synced report will wait for the site's "
              "own hourly cache refresh", file=sys.stderr)
        return
    url = os.environ.get("KTP_SITE", "https://ktpleague.gg") + "/api/internal/revalidate"
    body = json.dumps({"scope": REVALIDATE_SCOPE}).encode("utf-8")
    headers = {"content-type": "application/json",
               "x-internal-revalidate": secret}
    last_err: Exception | None = None
    for attempt in (1, 2):
        try:
            req = urllib.request.Request(url, data=body, headers=headers,
                                         method="POST")
            with urllib.request.urlopen(req, timeout=REVALIDATE_TIMEOUT) as resp:
                resp.read()
            print(f"site revalidate: scope={REVALIDATE_SCOPE} ok "
                  f"(attempt {attempt})")
            return
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_err = exc
            if attempt == 2 or not _revalidate_transient(exc):
                break
            print(f"site revalidate: transient error, retrying once: {exc}",
                  file=sys.stderr)
    # Never the secret value -- only the exception, which carries the URL and
    # HTTP status but not the header we sent.
    print(f"site revalidate FAILED, scope={REVALIDATE_SCOPE}: {last_err} -- "
          "the synced report will wait for the site's own hourly cache "
          "refresh", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    # Required with no default: a sync that forgot its floor would publish
    # every pre-season test and pracc report it can see.
    ap.add_argument("--since", type=since_arg, required=True,
                    help="season floor on the match's ktp_matches.start_time")
    args = ap.parse_args(argv)
    for var in ("KTP_SUPABASE_URL", "KTP_SUPABASE_SECRET_KEY"):
        if not os.environ.get(var):
            print(f"missing env {var}", file=sys.stderr)
            return 2
    n = sync_reports(args.dry_run, args.since)
    m = sync_aggregates(args.dry_run)
    p = sync_mmr(args.dry_run)
    print(f"done: {n} reports, {m} aggregates, {p} mmr aggregate")
    # sync_reports() raises on any failed POST, so reaching here with n > 0
    # means every one of those rows actually committed to Supabase. Same for
    # p: sync_mmr() raises on a failed POST too, never returns 1 on a dry run.
    if (n or p) and not args.dry_run:
        revalidate_site()
    return 0


if __name__ == "__main__":
    # Ubuntu's apport hook stats sys.argv[0], which is "-m" here, and buries the real traceback.
    sys.excepthook = sys.__excepthook__
    raise SystemExit(main())
