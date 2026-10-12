#!/usr/bin/env python3
"""Fully-capture-authorized reports per day, over a window, read-only.

`match_capture_authorization` answers this for ONE match. Nobody could answer
it for a WEEK without hand-writing the query again, which is why the rate the
D5 daemon was deployed to fix went four days without being re-derived: the
fix was proven to execute and unproven to work.

🔴 **The denominator is the trap, and it is worth more than the number.** A
"report" is a match that has a `ktp_match_reports` row, NOT a match. Counting
`ktp_matches` instead is defensible, reads identical in a summary, and gives a
materially different answer — measured 2026-10-12 over the same week,
21% against 27%, because roughly a third of played matches never get a report
generated. Worse, it is the wrong direction to be wrong in: the baseline this
is compared against was taken on the report denominator, so swapping it turns a
real improvement into a smaller one and the comparison silently stops being a
comparison. `--denominator matches` exists so the difference can be SEEN rather
than argued about, and it is not the default.

⚠️ **And the metric the question is usually asked in cannot see the
improvement at all.** Over the week after the deploy, fully-authorized reports
per day ran 0..5 against a 0..4 baseline — all but unchanged, because the
per-day COUNT is bounded by how much is played that day. The share is what
moved. A per-day count is a volume measure wearing a quality measure's name;
report both, which is why this prints the series and the ratio side by side.

Run it as root. `information_schema` hides a table the asking account cannot
see, so a service account that lacks `ktp_matches` reads every row as an
orphan — the same reason the integrity queries next door say so.

    sudo python3 scripts/capture_authorization_rate.py \\
        --since '2026-10-05 11:02:00' --until '2026-10-12 11:02:00' \\
        --baseline-since '2026-09-14 00:00:00'
"""
from __future__ import annotations

import argparse
import collections
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.match_analytics import (  # noqa: E402
    evaluate_capture_authorization, tsv_rows)

DATABASE = "hlstatsx"

# Where a withheld stream lost its data. The strings are `_reconcile_failures`'
# and the stream/match error wordings in match_analytics; a reason that matches
# none of them is reported verbatim rather than folded into an "other" bucket
# that hides a new failure mode.
REASONS = (
    ("never reached the daemon", "lines never reached the daemon"),
    ("correlation failure", "frag correlation failure"),
    ("producer dropped", "producer dropped before emit"),
    ("daemon rejected", "daemon rejected"),
    ("health type", "health stream absent or repeated"),
    ("sequence-gap", "unaccounted sequence gap"),
    ("duplicate or reordered", "duplicate or reordered"),
    ("manifest is not schema22+", "manifest not schema22+/2.00"),
    ("half set", "manifest/health halves != observed halves"),
    ("activation", "activation epoch or latency"),
    ("match start epoch", "match start epoch missing"),
    ("unknown health type", "unknown health type"),
    ("counter is negative", "negative counter"),
)


def classify(error: str) -> str:
    for needle, label in REASONS:
        if needle in error:
            return label
    return "UNCLASSIFIED: " + error[:70]


class Mysql:
    def __init__(self, mysql_bin: str, database: str) -> None:
        self.argv = [mysql_bin, "--batch", "--raw", database]

    def rows(self, query: str) -> list[dict]:
        proc = subprocess.run(
            self.argv, input="SET SESSION TRANSACTION READ ONLY;\n" + query,
            text=True, capture_output=True, check=False)
        if proc.returncode:
            raise SystemExit(
                f"mysql exited {proc.returncode}: {proc.stderr.strip()}")
        return tsv_rows(proc.stdout)


def window_sql(since: str, until: str) -> str:
    return (f"half > 0 AND start_time >= '{since}' AND start_time < '{until}'")


def load(db: Mysql, since: str, until: str, denominator: str):
    """Observed halves, manifests and health for every match in the window."""
    where = window_sql(since, until)
    matches = db.rows(f"""
SELECT match_id, half, DATE(start_time) AS start_date, start_time
FROM ktp_matches WHERE {where} ORDER BY match_id, half
""")
    scope = f"SELECT DISTINCT match_id FROM ktp_matches WHERE {where}"
    manifests = db.rows(f"""
SELECT cm.match_id, cm.half, cm.schema_version, cm.capabilities,
       cm.position_interval, cm.event_epoch AS producer_activation_epoch,
       UNIX_TIMESTAMP(cm.created_at) AS activation_receipt_epoch,
       UNIX_TIMESTAMP(m.start_time) AS match_start_epoch
FROM ktp_capture_manifests cm
LEFT JOIN ktp_matches m
  ON BINARY m.match_id = BINARY cm.match_id AND m.half = cm.half
WHERE cm.match_id IN ({scope})
ORDER BY cm.match_id, cm.half, cm.id
""")
    health = db.rows(f"""
SELECT match_id, half, event_type, attempted, enqueued, dropped, emitted,
       daemon_received, daemon_accepted, daemon_rejected,
       correlation_failure_count, sequence_gap_count,
       duplicate_or_reordered_count
FROM ktp_capture_health WHERE match_id IN ({scope})
ORDER BY match_id, half, event_type
""")
    reported = None
    if denominator == "reports":
        reported = {row["match_id"] for row in db.rows(
            "SELECT DISTINCT match_id FROM ktp_match_reports")}
    return matches, manifests, health, reported


def evaluate(matches, manifests, health, reported):
    """One verdict per match, using the shipped evaluator and nothing else."""
    by_match: dict[str, dict] = {}
    for row in matches:
        entry = by_match.setdefault(
            row["match_id"], {"halves": set(), "date": row["start_date"],
                              "start": row["start_time"]})
        entry["halves"].add(int(row["half"]))
        if row["start_time"] < entry["start"]:
            entry["start"], entry["date"] = row["start_time"], row["start_date"]
    man_by: dict[str, list] = collections.defaultdict(list)
    for row in manifests:
        man_by[row["match_id"]].append(row)
    health_by: dict[str, list] = collections.defaultdict(list)
    for row in health:
        health_by[row["match_id"]].append(row)

    results = []
    for match_id, entry in by_match.items():
        if reported is not None and match_id not in reported:
            continue
        verdict = evaluate_capture_authorization(
            entry["halves"], man_by.get(match_id, []),
            health_by.get(match_id, []), require_activation=True)
        streams = verdict["stream_authorization"]
        results.append({
            "date": entry["date"],
            "start": entry["start"],
            "authorized": verdict["authorized"],
            "streams": len(streams),
            "authorized_streams": len(verdict["authorized_streams"]),
            "withheld": [entry2["errors"] for entry2 in streams.values()
                         if not entry2["authorized"]],
        })
    results.sort(key=lambda row: row["start"])
    return results


def report(label: str, results: list[dict], out=sys.stdout) -> None:
    print(f"\n=== {label}: {len(results)} report(s)", file=out)
    if not results:
        print("  nothing in this window -- a zero here is an empty window, "
              "not a measurement", file=out)
        return
    fully = [row for row in results if row["authorized"]]
    streams = sum(row["streams"] for row in results)
    ok = sum(row["authorized_streams"] for row in results)
    print(f"  fully capture-authorized: {len(fully)} of {len(results)}"
          f" = {100 * len(fully) / len(results):.0f}%", file=out)
    print(f"  stream authorization:     {ok} of {streams}"
          f" = {100 * ok / streams:.0f}%" if streams else "  no streams", file=out)
    per_day = collections.Counter(row["date"] for row in fully)
    days = sorted({row["date"] for row in results})
    series = [per_day.get(day, 0) for day in days]
    print(f"  days with play: {len(days)}; fully-authorized PER DAY "
          f"min {min(series)} max {max(series)} -- {series}", file=out)
    for day in days:
        total = sum(1 for row in results if row["date"] == day)
        print(f"    {day}  fully {per_day.get(day, 0):3d} / {total:3d}", file=out)
    buckets: collections.Counter = collections.Counter()
    withheld = 0
    for row in results:
        for errors in row["withheld"]:
            withheld += 1
            # Per stream, not per error: one stream failing three ways is one
            # withheld stream, and counting errors inflates the busiest cause.
            for bucket in {classify(error) for error in errors}:
                buckets[bucket] += 1
    print(f"  withheld streams: {withheld}", file=out)
    for bucket, count in buckets.most_common():
        share = f" ({100 * count / withheld:.0f}%)" if withheld else ""
        print(f"    {count:6d}{share}  {bucket}", file=out)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", required=True,
                        help="window start, 'YYYY-MM-DD HH:MM:SS' in the "
                             "MySQL session zone (the box is America/New_York)")
    parser.add_argument("--until", required=True, help="window end, exclusive")
    parser.add_argument("--baseline-since",
                        help="also report the window from here up to --since, "
                             "which is the only honest way to read the first "
                             "number")
    parser.add_argument("--denominator", choices=("reports", "matches"),
                        default="reports",
                        help="'reports' (default) counts matches that have a "
                             "ktp_match_reports row; 'matches' counts every "
                             "played match and is NOT comparable to the "
                             "recorded baseline -- see the module docstring")
    parser.add_argument("--database", default=DATABASE)
    parser.add_argument("--mysql-bin", default="mysql")
    args = parser.parse_args(argv)
    if args.until <= args.since:
        parser.error("--until must be after --since")
    if args.baseline_since and args.baseline_since >= args.since:
        parser.error("--baseline-since must be before --since")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    db = Mysql(args.mysql_bin, args.database)
    print(f"denominator: {args.denominator}", file=sys.stderr)
    if args.baseline_since:
        report(f"BASELINE {args.baseline_since} .. {args.since}",
               evaluate(*load(db, args.baseline_since, args.since,
                              args.denominator)))
    report(f"WINDOW {args.since} .. {args.until}",
           evaluate(*load(db, args.since, args.until, args.denominator)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
