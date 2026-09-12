"""Post-cron verification for the match-report pipeline. Exits non-zero.

Replaces the handover's sanity check, which could not fail:
`SELECT ... FROM ktp_match_reports ORDER BY id DESC LIMIT 5` returns 0 rows
when cron never ran, when cron ran and correctly found nothing, and when
cron ran and failed; and `/stats/matches` answers 200 in all three (a
nonsense match id answers 200 too — only the <title> differs).

Every check here is written so a broken pipeline makes it exit 1:

  RAN         the log's mtime, not its content — a durable artifact
  COMPLETE    a generate block must carry its own terminator line;
              a truncated run (crash, OOM, kill) fails instead of passing
  FAILURES    `failures: N` must be present AND zero
  DRAINED     no match that ended before the run may still be pending;
              a successful generate always writes a row per id it found
  COHERENT    publishable=0 alongside quality_status=PASS is incoherent
  SITE        the empty-state marker must agree with the report count,
              in both directions

Usage on the data server:
  python3 -m scripts.verify_report_pipeline --since 2026-09-13 \
      --log /var/log/ktp-report-service.log --site https://ktpleague.gg
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.report_service import (
    LocalMysql, OFFICIAL_MATCH_TYPES, _pending_corpus_sql)

EMPTY_STATE_MARKER = "No match reports have been published yet"
GENERATE_HEAD = re.compile(r"^pending: (\d+) matches \(schema v(\d+)\)$")
GENERATE_TAIL = re.compile(r"^mysql calls: \d+; failures: (\d+)$")


@dataclass(frozen=True)
class Finding:
    ok: bool
    name: str
    detail: str


@dataclass(frozen=True)
class GenerateRun:
    pending: int
    schema_version: int
    failures: int


def parse_last_generate(log_text: str) -> GenerateRun | None:
    """The last generate block that reached its terminator line.

    A block with no terminator is a run that died mid-flight; returning None
    for it is the point — the old check read that state as success.
    """
    head: re.Match[str] | None = None
    last: GenerateRun | None = None
    for line in log_text.splitlines():
        line = line.rstrip()
        m = GENERATE_HEAD.match(line)
        if m:
            head = m
            continue
        t = GENERATE_TAIL.match(line)
        if t and head is not None:
            last = GenerateRun(int(head.group(1)), int(head.group(2)),
                               int(t.group(1)))
            head = None
    return last


def check_ran(log: Path, now: datetime, max_age_hours: float) -> Finding:
    if not log.exists():
        return Finding(False, "RAN", f"{log} does not exist")
    mtime = datetime.fromtimestamp(log.stat().st_mtime, tz=timezone.utc)
    age = now - mtime
    if age > timedelta(hours=max_age_hours):
        return Finding(False, "RAN",
                       f"{log} last written {age} ago (limit "
                       f"{max_age_hours}h) — cron did not run")
    return Finding(True, "RAN", f"{log} written {age} ago")


def check_complete(run: GenerateRun | None) -> Finding:
    if run is None:
        return Finding(False, "COMPLETE",
                       "no generate block reached its 'mysql calls: ...; "
                       "failures: N' terminator — the run died mid-flight "
                       "or has never run")
    return Finding(True, "COMPLETE",
                   f"pending {run.pending} at schema v{run.schema_version}")


def check_failures(run: GenerateRun | None) -> Finding:
    if run is None:
        return Finding(False, "FAILURES", "no complete run to read")
    if run.failures:
        return Finding(False, "FAILURES",
                       f"{run.failures} match(es) failed to generate")
    return Finding(True, "FAILURES", "0")


def check_drained(still_pending: list[str]) -> Finding:
    """A generate with failures: 0 writes a row for every id it found, so
    nothing that ended before the run may still be pending. Matches that
    concluded after the run are excluded by the caller's ceiling."""
    if still_pending:
        return Finding(False, "DRAINED",
                       f"{len(still_pending)} match(es) ended before the run "
                       f"and still have no report: {', '.join(still_pending[:5])}")
    return Finding(True, "DRAINED", "no unreported match predates the run")


def check_coherent(rows: list[tuple[str, str, int]]) -> Finding:
    """quality_status FAIL at publishable=1 is expected, not a defect:
    match_id_shape is cosmetic and never withholds a match. The incoherent
    direction is the one worth failing on."""
    bad = [mid for mid, status, pub in rows if pub == 0 and status == "PASS"]
    if bad:
        return Finding(False, "COHERENT",
                       f"{len(bad)} report(s) PASS quality yet publishable=0: "
                       f"{', '.join(bad[:5])}")
    return Finding(True, "COHERENT", f"{len(rows)} report row(s) coherent")


def check_site(body: str | None, publishable_count: int) -> Finding:
    """Assert on a body marker, never on the status code."""
    if body is None:
        return Finding(True, "SITE", "skipped (no --site)")
    empty = EMPTY_STATE_MARKER in body
    if publishable_count == 0 and not empty:
        return Finding(False, "SITE",
                       "0 publishable reports but the page does not show the "
                       "empty state — it is serving something else")
    if publishable_count > 0 and empty:
        return Finding(False, "SITE",
                       f"{publishable_count} publishable report(s) but the "
                       "page still shows the empty state — the sync or the "
                       "cache-tag purge did not land")
    return Finding(True, "SITE",
                   f"page agrees with {publishable_count} publishable report(s)")


def _rows(out: str) -> list[list[str]]:
    return [ln.split("\t") for ln in out.strip().splitlines()[1:] if ln.strip()]


def fetch(url: str, timeout: int = 20) -> str:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "ktp-verify"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"{url} answered {resp.status}")
        return resp.read().decode("utf-8", "replace")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--log", type=Path,
                    default=Path("/var/log/ktp-report-service.log"))
    ap.add_argument("--since", default=None,
                    help="the same --since the cron generate uses")
    ap.add_argument("--max-age-hours", type=float, default=26.0)
    ap.add_argument("--site", default=None,
                    help="site origin, e.g. https://ktpleague.gg")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    findings = [check_ran(args.log, now, args.max_age_hours)]
    log_text = args.log.read_text("utf-8", "replace") if args.log.exists() else ""
    run = parse_last_generate(log_text)
    findings += [check_complete(run), check_failures(run)]
    if not all(f.ok for f in findings):
        # Already known broken; do not query production to confirm it.
        return report(findings, run, [])

    db = LocalMysql()
    types = ", ".join(str(t) for t in OFFICIAL_MATCH_TYPES)
    if run is not None and args.log.exists():
        ceiling = datetime.fromtimestamp(
            args.log.stat().st_mtime, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S")
        pending = [r[0] for r in _rows(db.sql(_pending_corpus_sql(
            run.schema_version, args.since, "DISTINCT m.match_id",
            f"AND m.match_type IN ({types}) "
            f"AND m.start_time < '{ceiling}' ORDER BY m.match_id")))]
        findings.append(check_drained(pending))

    rows = [(r[0], r[1], int(r[2])) for r in _rows(db.sql(
        "SELECT r.match_id, r.quality_status, r.publishable "
        "FROM ktp_match_reports r JOIN (SELECT match_id, MAX(id) AS id "
        "FROM ktp_match_reports GROUP BY match_id) latest ON latest.id = r.id"))]
    findings.append(check_coherent(rows))

    body = fetch(f"{args.site.rstrip('/')}/stats/matches") if args.site else None
    findings.append(check_site(body, sum(1 for _, _, pub in rows if pub == 1)))
    return report(findings, run, rows)


def report(findings: list[Finding], run: GenerateRun | None,
           rows: list[tuple[str, str, int]]) -> int:
    for f in findings:
        print(f"{'PASS' if f.ok else 'FAIL'}  {f.name:<9} {f.detail}")
    failed = [f.name for f in findings if not f.ok]
    if failed:
        print(f"\nFAIL: {', '.join(failed)}", file=sys.stderr)
        return 1
    if run is not None and run.pending == 0 and not rows:
        print("\nIDLE: the pipeline is healthy and has had nothing to do — "
              "no official match has been played yet. This is NOT evidence "
              "that report generation works.")
    else:
        print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
