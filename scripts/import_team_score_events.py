#!/usr/bin/env python3
"""Import settled official team_score rows from retained local events.jsonl."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:  # direct script execution
    from team_score_telemetry import (
        MIGRATION, SETTLEMENT_SECONDS, ImportResult, JsonlValidationError,
        MysqlCli, MysqlCommandError, read_event_files,
    )
except ModuleNotFoundError:  # package import in tests/tooling
    from scripts.team_score_telemetry import (
        MIGRATION, SETTLEMENT_SECONDS, ImportResult, JsonlValidationError,
        MysqlCli, MysqlCommandError, read_event_files,
    )


def _connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mysql-bin", default="mysql")
    parser.add_argument("--database", default="hlstatsx_lan")
    parser.add_argument("--defaults-extra-file", type=Path)
    parser.add_argument("--socket", type=Path)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--user")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", nargs="+", type=Path,
                        help="completed local/mounted events.jsonl path(s)")
    parser.add_argument("--settlement-seconds", type=int, default=SETTLEMENT_SECONDS)
    parser.add_argument(
        "--source-server-root", action="append", required=True,
        metavar="SOURCE_SERVER=ROOT",
        help="allowlisted metadata sourceServer and its exact mounted matches root; repeatable",
    )
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--migrate", action="store_true",
                        help="apply the idempotent migration before import")
    parser.add_argument("--migration", type=Path, default=MIGRATION)
    _connection_args(parser)
    return parser.parse_args(argv)


def _validated_only(parsed) -> ImportResult:
    from collections import Counter
    classes = Counter(row.retention_class for row in parsed.observations)
    return ImportResult(
        input_lines=parsed.input_lines,
        ignored_events=parsed.ignored_events,
        ignored_legacy_team_scores=parsed.ignored_legacy_team_scores,
        official_rows=len(parsed.observations),
        unique_candidates=len({
            (row.order_key, row.raw_event_sha256) for row in parsed.observations
        }),
        inserted=0, idempotent_duplicates=0, conflicting_rows=0,
        conflict_keys=0, retention_classes=dict(classes),
    )


def _source_server_roots(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        source_server, separator, root = value.partition("=")
        if not separator or not source_server or not root:
            raise ValueError("--source-server-root must be SOURCE_SERVER=ROOT")
        if source_server in result:
            raise ValueError(f"duplicate --source-server-root for {source_server}")
        result[source_server] = Path(root)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        parsed = read_event_files(
            args.events, settlement_seconds=args.settlement_seconds,
            source_server_roots=_source_server_roots(args.source_server_root),
        )
        if args.validate_only:
            result = _validated_only(parsed)
        else:
            mysql = MysqlCli(
                mysql_bin=args.mysql_bin, database=args.database,
                defaults_extra_file=args.defaults_extra_file, socket=args.socket,
                host=args.host, port=args.port, user=args.user,
            )
            if args.migrate:
                mysql.apply_migration(args.migration)
            result = mysql.import_observations(parsed)
    except (FileNotFoundError, JsonlValidationError, MysqlCommandError, ValueError) as exc:
        print(f"team-score import: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result.as_dict(), sort_keys=True, separators=(",", ":")))
    return int(result.conflict_keys > 0)


if __name__ == "__main__":
    raise SystemExit(main())
