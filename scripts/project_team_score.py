#!/usr/bin/env python3
"""Create an immutable sanitized official-score release from retained rows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:  # direct script execution
    from team_score_telemetry import MysqlCli, MysqlCommandError, project_official_score
except ModuleNotFoundError:  # package import in tests/tooling
    from scripts.team_score_telemetry import MysqlCli, MysqlCommandError, project_official_score


def _write_immutable(path: Path, body: bytes) -> None:
    if path.exists():
        if path.read_bytes() != body:
            raise ValueError(
                f"immutable release path already contains different bytes: {path}"
            )
        return
    with path.open("xb") as handle:
        handle.write(body)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--match-id", required=True,
                        help="internal selector; never written to the public release")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--match-end-json", type=Path,
                        help="optional comparison-only quality evidence")
    parser.add_argument("--late-recovery", action="store_true")
    parser.add_argument("--mysql-bin", default="mysql")
    parser.add_argument("--database", default="hlstatsx_lan")
    parser.add_argument("--defaults-extra-file", type=Path)
    parser.add_argument("--socket", type=Path)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--user")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        mysql = MysqlCli(
            mysql_bin=args.mysql_bin, database=args.database,
            defaults_extra_file=args.defaults_extra_file, socket=args.socket,
            host=args.host, port=args.port, user=args.user,
        )
        snapshot = mysql.fetch_match(args.match_id)
        match_end = None
        if args.match_end_json:
            match_end = json.loads(args.match_end_json.read_text(encoding="utf-8"))
            if not isinstance(match_end, dict):
                raise ValueError("match-end JSON must be an object")
        result = project_official_score(
            snapshot.rows, conflict_keys=snapshot.conflict_keys,
            context=snapshot.context, match_end=match_end,
            late_recovery=args.late_recovery,
        )
        args.output_dir.mkdir(parents=True, exist_ok=True)
        _write_immutable(
            args.output_dir / "objective-score-timeline.json", result.canonical_json
        )
        _write_immutable(
            args.output_dir / "objective-score-release.json",
            json.dumps(
                result.release_metadata, sort_keys=True, separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8"),
        )
        _write_immutable(
            args.output_dir / "objective-score-private-release.json",
            json.dumps(
                result.private_release_metadata, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            ).encode("utf-8"),
        )
    except (FileNotFoundError, json.JSONDecodeError, MysqlCommandError, ValueError) as exc:
        print(f"team-score projection: {exc}", file=sys.stderr)
        return 2
    status = result.dto["objectiveScoreTimeline"]["quality"]["status"]
    print(json.dumps({"status": status, "sha256": result.sha256}, sort_keys=True))
    return int(status == "unavailable")


if __name__ == "__main__":
    raise SystemExit(main())
