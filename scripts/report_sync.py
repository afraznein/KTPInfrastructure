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

Environment (operator-provisioned file, e.g. /etc/ktp/report-sync.env):
  KTP_SUPABASE_URL=https://<project>.supabase.co
  KTP_SUPABASE_SECRET_KEY=<service role secret; never the publishable key>

Usage (from the KTPInfrastructure repo root):
  python3 -m scripts.report_sync [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.request

from scripts.analytics_report_dto import assert_sanitized, sanitize_report

DATABASE = "hlstatsx"
# Every kind here is name-keyed; database ids never cross to the website
# (2026-08-29 handover). Add a kind only after its builder emits names.
# head_to_head is deliberately absent: its pairs are still pid-keyed.
SYNCABLE_AGGREGATE_KINDS = {"map_profiles", "leaderboard_ktpr_v22",
                            "season_positional"}

# Kept under PostgREST's default max-rows so a page is never server-truncated.
PAGE_SIZE = 500
# A server that ignores `offset` would otherwise page forever on one result.
MAX_PAGES = 4000


def mysql(query: str) -> str:
    proc = subprocess.run(
        ["mysql", "--batch", "--raw", "--default-character-set=utf8mb4",
         DATABASE],
        input=query, capture_output=True, text=True, timeout=600,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"mysql rc={proc.returncode}: {proc.stderr[-800:]}")
    return proc.stdout


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
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method=method)
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else None


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


def pending_reports() -> list[tuple[str, int, int]]:
    """Latest publishable (match_id, schema_version, revision) per match,
    minus rows Supabase already has."""
    out = mysql(
        "SELECT r.match_id, r.schema_version, r.revision FROM "
        "ktp_match_reports r JOIN (SELECT match_id, MAX(id) AS id "
        "FROM ktp_match_reports WHERE publishable = 1 GROUP BY match_id) "
        "latest ON latest.id = r.id"
    )
    local = {(f[0], int(f[1]), int(f[2]))
             for ln in out.strip().splitlines()[1:]
             if (f := ln.split("\t")) and len(f) == 3}
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


def sync_reports(dry_run: bool) -> int:
    todo = pending_reports()
    print(f"reports to sync: {len(todo)}")
    for match_id, schema_version, revision in todo:
        report = fetch_report(match_id, schema_version, revision)
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    for var in ("KTP_SUPABASE_URL", "KTP_SUPABASE_SECRET_KEY"):
        if not os.environ.get(var):
            print(f"missing env {var}", file=sys.stderr)
            return 2
    n = sync_reports(args.dry_run)
    m = sync_aggregates(args.dry_run)
    print(f"done: {n} reports, {m} aggregates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
