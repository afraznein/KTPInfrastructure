#!/usr/bin/env python3
"""Collect a reproducible, read-only evidence bundle for one canary match.

The input is a local SQL dump (optionally gzip-compressed), never a live DB.
Optional game/daemon logs make unresolved-action and SQL-error checks decisive;
without them those checks are explicitly reported as unavailable.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import match_analytics as analytics  # noqa: E402
from scripts.match_timelines import TimelineConfig  # noqa: E402
from tests.e2e_stats.ephemeral_mysql import EphemeralMysql  # noqa: E402


REPO = Path(__file__).resolve().parents[1]
MATCH_TYPES = {
    0: "official", 1: "scrim", 2: "12man", 3: "draft",
    4: "official_ot", 5: "draft_ot",
}
ERROR_PATTERNS = {
    "unresolved_actions": re.compile(
        r"Unresolved action\s+['\"]|unknown action|action.{0,30}not found", re.I
    ),
    "sql_errors": re.compile(
        r"SQL_ERROR|DBD::mysql|SQL syntax|execute failed|prepare failed|mysql.{0,20}error", re.I
    ),
}
HEALTH_PATTERN = re.compile(
    r"KTP_HEALTH.*sql_failed=(\d+)\s+sql_retried=(\d+)\s+unresolved_actions=(\d+)",
    re.I,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_log(path: Path) -> str:
    opener = gzip.open if path.suffix == ".gz" else Path.open
    with opener(path, "rt", encoding="utf-8", errors="replace") as source:
        return source.read()


def inspect_logs(paths: list[Path]) -> dict[str, Any]:
    if not paths:
        return {
            "status": "not_provided", "files": [],
            "unresolved_actions": {"count": None, "samples": []},
            "sql_errors": {"count": None, "samples": []},
        }
    findings = {name: [] for name in ERROR_PATTERNS}
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"log not found: {path}")
        for number, line in enumerate(_read_log(path).splitlines(), 1):
            health = HEALTH_PATTERN.search(line)
            if health:
                sql_failed, sql_retried, unresolved = map(int, health.groups())
                sample = {"file": path.name, "line": number, "text": line[:500]}
                if sql_failed or sql_retried:
                    findings["sql_errors"].append(sample)
                if unresolved:
                    findings["unresolved_actions"].append(sample)
                # Do not double-count the same health line via generic patterns.
                continue
            for name, pattern in ERROR_PATTERNS.items():
                if pattern.search(line):
                    findings[name].append({
                        "file": path.name, "line": number, "text": line[:500],
                    })
    return {
        "status": "clean" if not any(findings.values()) else "errors_found",
        "files": [path.name for path in paths],
        **{name: {"count": len(rows), "samples": rows[:20]}
           for name, rows in findings.items()},
    }


def _column_exists(db: EphemeralMysql, table: str, column: str) -> bool:
    query = (
        "SELECT COUNT(*) AS present FROM information_schema.columns "
        f"WHERE table_schema=DATABASE() AND table_name={analytics.sql_literal(table)} "
        f"AND column_name={analytics.sql_literal(column)}"
    )
    rows = analytics.tsv_rows(db.sql(query))
    return bool(int(rows[0]["present"]))


def collect_classification(db: EphemeralMysql, match_id: str) -> list[dict[str, Any]]:
    if not _column_exists(db, "ktp_matches", "match_type"):
        return []
    literal = analytics.sql_literal(match_id)
    return analytics.tsv_rows(db.sql(f"""
SELECT half, match_type, start_time, end_time
FROM ktp_matches WHERE match_id={literal} ORDER BY half
"""))


def collect_ownership(db: EphemeralMysql, match_id: str, available: bool) -> list[dict[str, Any]]:
    if not available:
        return []
    literal = analytics.sql_literal(match_id)
    return analytics.tsv_rows(db.sql(f"""
SELECT id AS event_id, half, flag_index, flag_name, owner_team, is_initial,
       game_time, event_time
FROM ktp_flag_state_events
WHERE match_id={literal} ORDER BY half, flag_index, game_time, id
"""))


def classification_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [row.get("match_type") for row in rows]
    distinct = sorted({value for value in values if value is not None})
    consistent = bool(rows) and len(distinct) == 1 and len(values) == len([v for v in values if v is not None])
    value = distinct[0] if consistent else None
    return {
        "available": bool(rows), "consistent": consistent,
        "match_type": value, "match_type_name": MATCH_TYPES.get(value),
        "halves": rows,
    }


def ownership_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((int(row["half"]), int(row["flag_index"])), []).append(row)
    baselines = []
    for (half, flag_index), events in sorted(groups.items()):
        initial = [event for event in events if int(event["is_initial"]) == 1]
        baselines.append({
            "half": half, "flag_index": flag_index,
            "initial_rows": len(initial),
            "starts_at_zero": len(initial) == 1 and float(initial[0]["game_time"]) == 0,
        })
    invalid = [row for row in rows if int(row["owner_team"]) not in (0, 1, 2)]
    baseline_ok = bool(groups) and all(
        item["initial_rows"] == 1 and item["starts_at_zero"] for item in baselines
    )
    return {
        "available": bool(rows), "event_count": len(rows),
        "transition_count": sum(int(row["is_initial"]) == 0 for row in rows),
        "baseline_ok": baseline_ok, "invalid_owner_count": len(invalid),
        "baselines": baselines,
    }


def retention_evidence(
    match_id: str, classification: dict[str, Any], *, days: int,
    as_of: datetime,
) -> dict[str, Any]:
    halves = classification.get("halves", [])
    ended = [row.get("end_time") or row.get("start_time") for row in halves]
    last = max((value for value in ended if value), default=None)
    age_days = None
    if last:
        parsed = datetime.fromisoformat(str(last)).replace(tzinfo=timezone.utc)
        age_days = (as_of - parsed).total_seconds() / 86400
    match_type = classification.get("match_type")
    purge_class = bool(match_id.endswith("-TEST") or match_type in (1, 2))
    eligible = bool(purge_class and age_days is not None and age_days >= days)
    return {
        "policy_days": days, "purge_class": purge_class,
        "age_days": round(age_days, 3) if age_days is not None else None,
        "eligible_now": eligible,
        "reason": (
            "expired temporary analytics" if eligible else
            "temporary analytics inside retention window" if purge_class else
            "retained match class"
        ),
    }


def build_evidence(
    analytics_report: dict[str, Any], classifications: list[dict[str, Any]],
    ownership_rows: list[dict[str, Any]], logs: dict[str, Any],
    provenance: dict[str, Any], *, expected_server_id: int | None = None,
    retention_days: int = 14, as_of: datetime | None = None,
) -> dict[str, Any]:
    classification = classification_evidence(classifications)
    ownership = ownership_evidence(ownership_rows)
    retention = retention_evidence(
        analytics_report["match_id"], classification, days=retention_days,
        as_of=as_of or datetime.now(timezone.utc),
    )
    sources = analytics_report["source_coverage"]
    checks = []

    def add(level: str, code: str, detail: str) -> None:
        checks.append({"level": level, "code": code, "detail": detail})

    add(analytics_report["quality"]["status"], "analytics_quality",
        "Shared match analytics quality gate.")
    add("PASS" if classification["consistent"] else "FAIL", "match_type_consistency",
        "Every half has one consistent persisted match type.")
    add("PASS" if ownership["baseline_ok"] else "FAIL", "ownership_baselines",
        "Every observed half/flag starts with exactly one game_time=0 baseline.")
    add("PASS" if ownership["invalid_owner_count"] == 0 else "FAIL", "ownership_values",
        "Ownership values are restricted to neutral, Allies, or Axis.")
    required = ("per_hit_damage", "capture_credits", "positions", "flag_ownership",
                "statsme", "statsme2", "assists")
    missing = [name for name in required if not sources.get(name)]
    add("PASS" if not missing else "FAIL", "required_sources",
        "All current canary sources are present." if not missing else f"Missing: {', '.join(missing)}")
    if expected_server_id is not None:
        actual = (analytics_report.get("match") or {}).get("server_id")
        add("PASS" if actual == expected_server_id else "FAIL", "expected_server",
            f"Expected server {expected_server_id}; observed {actual}.")
    if logs["status"] == "not_provided":
        add("WARN", "operational_logs", "No game/daemon logs supplied; error checks are unavailable.")
    else:
        clean = logs["status"] == "clean"
        add("PASS" if clean else "FAIL", "operational_logs",
            "No unresolved-action or SQL errors found." if clean else "Operational errors found; inspect samples.")

    status = "FAIL" if any(row["level"] == "FAIL" for row in checks) else (
        "WARN" if any(row["level"] == "WARN" for row in checks) else "PASS"
    )
    timelines = analytics_report["shadow_timelines"]
    return {
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status, "match_id": analytics_report["match_id"],
        "provenance": provenance, "checks": checks,
        "match_type": classification, "ownership": ownership,
        "source_coverage": sources,
        "analytics_coverage": {
            "players": len(analytics_report["players"]),
            "assists": sum(row["assists"] for row in analytics_report["assists"]),
            "damage_events": analytics_report["source_inventory"].get("damage_events"),
            "capture_events": len(analytics_report["capture_events"]),
            "position_samples": analytics_report["positional"]["aggregate_sample_count"],
            "weapon_rows": len(analytics_report["weapons"]),
        },
        "shadow_timeline_summary": {
            "status": timelines["status"], "config": timelines["config"],
            "fast_multikills": len(timelines["fast_multikills"]),
            "trades": len(timelines["trades"]),
            "opening_duels": len(timelines["opening_duels"]),
            "head_to_head_pairs": len(timelines["head_to_head"]),
        },
        "operational_logs": logs, "retention": retention,
        "analytics_report": analytics_report,
    }


def render_markdown(evidence: dict[str, Any]) -> str:
    lines = [
        f"# Canary evidence — {evidence['match_id']}", "",
        f"Gate: **{evidence['status']}**", "",
        "## Checks", "", "| Result | Check | Detail |", "|---|---|---|",
    ]
    for check in evidence["checks"]:
        lines.append(f"| {check['level']} | `{check['code']}` | {check['detail']} |")
    classification, ownership = evidence["match_type"], evidence["ownership"]
    lines += [
        "", "## Classification and retention", "",
        f"Persisted type: `{classification.get('match_type_name')}`; "
        f"consistent: `{classification['consistent']}`.  ",
        f"Retention: {evidence['retention']['reason']}; "
        f"eligible now: `{evidence['retention']['eligible_now']}`.",
        "", "## Ownership", "",
        f"Events: {ownership['event_count']}; transitions: {ownership['transition_count']}; "
        f"baselines valid: `{ownership['baseline_ok']}`.",
        "", "## Shadow timelines", "",
        "Private/read-only exploratory output; no rating or public API writes.", "",
        "```json", json.dumps(evidence["shadow_timeline_summary"], indent=2), "```", "",
        "## Provenance", "", "```json", json.dumps(evidence["provenance"], indent=2), "```", "",
    ]
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--output-dir", type=Path, default=REPO / "build" / "canary-evidence")
    parser.add_argument("--game-log", type=Path, action="append", default=[])
    parser.add_argument("--daemon-log", type=Path, action="append", default=[])
    parser.add_argument("--expected-server-id", type=int)
    parser.add_argument("--retention-days", type=int, default=14)
    parser.add_argument("--source-mode", choices=("database", "replay"), default="database")
    parser.add_argument("--multikill-seconds", type=float, default=10.0)
    parser.add_argument("--trade-seconds", type=float, default=5.0)
    parser.add_argument("--objective-conversion-seconds", type=float, default=30.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    fixture = args.fixture.resolve()
    with EphemeralMysql.start() as db:
        analytics.load_fixture(db, fixture)
        sources = analytics.source_capabilities(db)
        if not all((sources["per_hit_damage"], sources["capture_credits"], sources["positions"])):
            analytics.install_legacy_compatibility(db)
        if args.match_id not in analytics.discover_match_ids(db):
            raise SystemExit(f"match {args.match_id!r} not found in fixture")
        report = analytics.build_report(
            db, args.match_id, fixture, sources, args.source_mode,
            TimelineConfig(args.multikill_seconds, args.trade_seconds,
                           args.objective_conversion_seconds),
        )
        classifications = collect_classification(db, args.match_id)
        ownership = collect_ownership(db, args.match_id, sources.get("flag_ownership", False))

    evidence = build_evidence(
        report, classifications, ownership,
        inspect_logs(args.game_log + args.daemon_log),
        {
            "fixture": fixture.name, "fixture_bytes": fixture.stat().st_size,
            "fixture_sha256": _sha256(fixture), "source_mode": args.source_mode,
            "analytics_schema_version": analytics.SCHEMA_VERSION,
        },
        expected_server_id=args.expected_server_id,
        retention_days=args.retention_days,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.match_id}-canary-evidence"
    json_path, md_path = args.output_dir / f"{stem}.json", args.output_dir / f"{stem}.md"
    json_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(evidence), encoding="utf-8")
    print(f"{evidence['status']}: {args.match_id}")
    print(json_path)
    print(md_path)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
