#!/usr/bin/env python3
"""Purge expired non-official KTP match analytics through the mysql CLI.

Dry-run is the default. Scheduled execution must pass --apply explicitly.
Official, KTP OT, draft, draft OT, and unclassified matches are fail-closed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys


DEFAULT_DAYS = 14
DATABASE = "hlstatsx"

# Every known match-scoped table is explicit. New tables must be reviewed and
# added deliberately; broad information_schema-driven deletion is too risky.
MATCH_TABLES = (
    "hlstats_Events_Admin",
    "hlstats_Events_ChangeName",
    "hlstats_Events_ChangeRole",
    "hlstats_Events_ChangeTeam",
    "hlstats_Events_Chat",
    "hlstats_Events_Connects",
    "hlstats_Events_Disconnects",
    "hlstats_Events_Entries",
    "hlstats_Events_Frags",
    "hlstats_Events_Latency",
    "hlstats_Events_PlayerActions",
    "hlstats_Events_PlayerPlayerActions",
    "hlstats_Events_Statsme",
    "hlstats_Events_Statsme2",
    "hlstats_Events_StatsmeLatency",
    "hlstats_Events_StatsmeTime",
    "hlstats_Events_Suicides",
    "hlstats_Events_TeamBonuses",
    "hlstats_Events_Teamkills",
    "ktp_damage_events",
    "ktp_flag_captures",
    "ktp_match_players",
    "ktp_match_stats",
    "ktp_position_samples",
)


def should_purge(match_type: int | None, match_id: str) -> bool:
    """Mirror the SQL allowlist for tests and operator tooling."""
    return match_type in (1, 2) or match_id.endswith("-TEST")


def candidate_sql(days: int) -> str:
    return f"""
CREATE TEMPORARY TABLE purge_match_ids (
    match_id VARCHAR(64) PRIMARY KEY
) ENGINE=InnoDB;
INSERT INTO purge_match_ids (match_id)
SELECT match_id
FROM ktp_matches
WHERE @retention_lock = 1
GROUP BY match_id
HAVING MAX(COALESCE(end_time, start_time)) < DATE_SUB(NOW(), INTERVAL {days} DAY)
   AND (
       RIGHT(match_id, 5) = '-TEST'
       OR (
           COUNT(match_type) = COUNT(*)
           AND MIN(match_type) IN (1, 2)
           AND MAX(match_type) = MIN(match_type)
       )
   );
""".strip()


def build_sql(days: int, apply: bool) -> str:
    prefix = "SELECT GET_LOCK('ktp_match_retention', 0) INTO @retention_lock;\n"
    candidates = candidate_sql(days)
    preview = """
SELECT COUNT(*) AS candidate_matches FROM purge_match_ids;
SELECT p.match_id, MIN(m.match_type) AS match_type,
       MAX(COALESCE(m.end_time, m.start_time)) AS last_activity
FROM purge_match_ids p JOIN ktp_matches m USING (match_id)
GROUP BY p.match_id ORDER BY last_activity;
""".strip()
    if not apply:
        return f"{prefix}{candidates}\n{preview}\nSELECT IF(@retention_lock = 1, RELEASE_LOCK('ktp_match_retention'), 0);\n"

    deletes = []
    for table in MATCH_TABLES:
        deletes.append(
            f"DELETE t FROM `{table}` t JOIN purge_match_ids p ON p.match_id = t.match_id;\n"
            f"SELECT '{table}' AS table_name, ROW_COUNT() AS deleted_rows;"
        )
    # Metadata is last, so an interrupted run remains discoverable and retryable.
    deletes.append(
        "DELETE t FROM `ktp_matches` t JOIN purge_match_ids p ON p.match_id = t.match_id;\n"
        "SELECT 'ktp_matches' AS table_name, ROW_COUNT() AS deleted_rows;"
    )
    return (
        f"{prefix}{candidates}\n{preview}\n"
        + "\n".join(deletes)
        + "\nSELECT IF(@retention_lock = 1, RELEASE_LOCK('ktp_match_retention'), 0);\n"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--database", default=DATABASE)
    parser.add_argument("--mysql-bin", default="mysql")
    parser.add_argument("--print-sql", action="store_true")
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be at least 1")
    return args


def main() -> int:
    args = parse_args()
    sql = build_sql(args.days, args.apply)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"ktp-match-retention: mode={mode} days={args.days}", file=sys.stderr)
    if args.print_sql:
        print(sql)
        return 0
    proc = subprocess.run(
        [args.mysql_bin, "--batch", "--raw", args.database],
        input=sql,
        text=True,
        check=False,
    )
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
