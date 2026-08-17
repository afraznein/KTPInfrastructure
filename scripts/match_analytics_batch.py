#!/usr/bin/env python3
"""Run read-only shadow analytics across every match in a local database dump.

The dump is restored into one disposable local database. Legacy compatibility
tables, when needed, are created only there. Reports never contact a website,
rating service, or shared database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import match_analytics as analytics  # noqa: E402
from tests.e2e_stats.ephemeral_mysql import EphemeralMysql  # noqa: E402


REPO = Path(__file__).resolve().parents[1]


def failed_codes(report: dict[str, Any]) -> list[str]:
    return [item["code"] for item in report["quality"]["checks"]
            if item["level"] == "FAIL"]


def safe_report_name(match_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", match_id)
    if safe == match_id:
        return safe
    digest = hashlib.sha256(match_id.encode("utf-8")).hexdigest()[:8]
    return f"{safe}-{digest}"


def source_match_ids(db: EphemeralMysql) -> dict[str, set[str]]:
    tables = (
        "ktp_matches", "ktp_match_players", "ktp_match_stats",
        "hlstats_Events_Frags", "hlstats_Events_Statsme", "hlstats_Events_Statsme2",
    )
    result: dict[str, set[str]] = {}
    for table in tables:
        rows = analytics.tsv_rows(db.sql(
            f"SELECT DISTINCT match_id FROM {table} "
            "WHERE match_id IS NOT NULL AND match_id <> '' ORDER BY match_id"
        ))
        result[table] = {str(row["match_id"]) for row in rows}
    return result


def source_table_counts(db: EphemeralMysql) -> dict[str, dict[str, int]]:
    tables = (
        "ktp_matches", "ktp_match_players", "ktp_match_stats",
        "hlstats_Events_Frags", "hlstats_Events_Statsme", "hlstats_Events_Statsme2",
    )
    result: dict[str, dict[str, int]] = {}
    for table in tables:
        row = analytics.tsv_rows(db.sql(
            "SELECT COUNT(*) AS total_rows, "
            "SUM(CASE WHEN match_id IS NOT NULL AND match_id <> '' THEN 1 ELSE 0 END) AS tagged_rows "
            f"FROM {table}"
        ))[0]
        result[table] = {key: int(value) for key, value in row.items()}
    return result


def choose_representatives(reports: list[dict[str, Any]]) -> dict[str, str]:
    """Pick deterministic examples for common and anomalous real-match shapes."""
    selected: dict[str, str] = {}

    def take(label: str, predicate: Any) -> None:
        match = next((r for r in reports if predicate(r)), None)
        if match:
            selected[label] = match["match_id"]

    for map_name in sorted({(r.get("match") or {}).get("map_name") for r in reports} - {None}):
        take(f"complete:{map_name}", lambda r, m=map_name:
             (r.get("match") or {}).get("map_name") == m
             and (r.get("match") or {}).get("halves_played") == 2
             and r["source_inventory"].get("roster_players") == 12
             and r["source_inventory"].get("frags", 0) > 0)
    take("substitute_or_reconnect", lambda r: r["source_inventory"].get("roster_players", 0) > 12)
    canonical = lambda r: bool(re.fullmatch(r"\d+-KTP\d+", r["match_id"]))
    take("malformed_or_orphan_id", lambda r: not canonical(r))
    take("missing_roster", lambda r: canonical(r) and r["source_inventory"].get("roster_players", 0) == 0)
    take("missing_aggregate_cache", lambda r: canonical(r) and r["source_inventory"].get("cached_player_totals", 0) == 0)
    take("overtime_or_extra_half", lambda r: (r.get("match") or {}).get("halves_played", 0) > 2)
    take("zero_frag", lambda r: canonical(r) and r["source_inventory"].get("frags", 0) == 0)
    return selected


def render_summary(
    fixture: Path,
    reports: list[dict[str, Any]],
    sources: dict[str, bool],
    representatives: dict[str, str],
    match_ids_by_source: dict[str, set[str]],
    table_counts: dict[str, dict[str, int]],
) -> str:
    statuses = Counter(r["quality"]["status"] for r in reports)
    maps = Counter((r.get("match") or {}).get("map_name") or "unknown" for r in reports)
    canonical_reports = [r for r in reports if re.fullmatch(r"\d+-KTP\d+", r["match_id"])]
    anomaly_reports = [r for r in reports if r not in canonical_reports]
    valid_ids = len(canonical_reports)
    totals = {
        key: sum(r["source_inventory"].get(key, 0) for r in canonical_reports)
        for key in ("frags", "statsme_rows", "statsme2_rows", "roster_players")
    }
    anomaly_totals = {
        key: sum(r["source_inventory"].get(key, 0) for r in anomaly_reports)
        for key in ("frags", "statsme_rows", "statsme2_rows", "roster_players")
    }
    out = [
        "# Phase B real-match shadow validation", "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}", "",
        f"Local source: `{fixture.name}` ({valid_ids} canonical match IDs; "
        f"{len(reports) - valid_ids} additional malformed/orphan IDs preserved for audit)", "",
        "No website, rating, production, or preprod writes were performed.", "",
        "## Result", "",
        f"Quality counts: PASS {statuses['PASS']}, WARN {statuses['WARN']}, FAIL {statuses['FAIL']}.", "",
        "A WARN can be expected for telemetry that this historical archive never captured. "
        "A FAIL is a source discrepancy or incomplete match shape to inspect; the exporter does not repair it.", "",
        "Canonical-match totals represented below: "
        f"{totals['frags']:,} frags, {totals['statsme_rows']:,} StatsMe rows, "
        f"{totals['statsme2_rows']:,} StatsMe2 rows, and {totals['roster_players']:,} roster rows.", "",
        "Malformed/orphan-ID telemetry retained separately: "
        f"{anomaly_totals['frags']:,} frags, {anomaly_totals['statsme_rows']:,} StatsMe rows, "
        f"{anomaly_totals['statsme2_rows']:,} StatsMe2 rows, and "
        f"{anomaly_totals['roster_players']:,} roster rows.", "",
        "## Match-ID coverage by source", "",
        "| Source table | Distinct tagged IDs |", "|---|---:|",
    ]
    for table, ids in match_ids_by_source.items():
        out.append(f"| `{table}` | {len(ids)} |")
    out += [
        "", "The batch uses the union of these IDs so orphan telemetry is visible rather than silently dropped.", "",
        "## Tagged-row coverage", "",
        "| Source table | All rows | Match-tagged rows | Untagged rows |", "|---|---:|---:|---:|",
    ]
    for table, counts in table_counts.items():
        total = counts["total_rows"]
        tagged = counts["tagged_rows"]
        out.append(f"| `{table}` | {total:,} | {tagged:,} | {total - tagged:,} |")
    out += [
        "", "Untagged rows remain outside match analytics; they are shown here so corpus totals are auditable.", "",
        "## Source coverage", "",
        "| Source | Captured in archive |", "|---|---|",
    ]
    labels = {
        "assists": "Assists", "capture_credits": "Capture credits",
        "per_hit_damage": "Per-hit damage", "positions": "Position samples",
        "statsme": "StatsMe weapon totals", "statsme2": "StatsMe2 hit locations",
        "legacy_match_cache": "Legacy match aggregate cache",
    }
    for key, label in labels.items():
        out.append(f"| {label} | {'yes' if sources.get(key) else 'no'} |")
    out += ["", "## Map coverage", "", "| Map | Matches |", "|---|---|"]
    out.extend(f"| `{name}` | {count} |" for name, count in sorted(maps.items()))
    out += ["", "## Representative reports", "", "| Shape | Match |", "|---|---|"]
    if representatives:
        out.extend(f"| {label} | [{match_id}](reports/{safe_report_name(match_id)}.md) |"
                   for label, match_id in representatives.items())
    else:
        out.append("| none | none |")
    out += [
        "", "## All matches", "",
        "| Match | Map | Halves | Roster | Frags | StatsMe | Cache rows | Quality | Failures |",
        "|---|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for report in reports:
        match = report.get("match") or {}
        inv = report["source_inventory"]
        failures = ", ".join(failed_codes(report)) or "—"
        out.append(
            f"| `{report['match_id']}` | `{match.get('map_name', '—')}` | "
            f"{match.get('halves_played', '—')} | {inv.get('roster_players', 0)} | "
            f"{inv.get('frags', 0)} | {inv.get('statsme_rows', 0)} | "
            f"{inv.get('cached_player_totals', 0)} | {report['quality']['status']} | {failures} |"
        )
    out += [
        "", "## Interpretation boundary", "",
        "This archive is real-match validation for kills, deaths, headshots, teamkills, suicides, "
        "rosters, halves, maps, weapon totals, hit locations, and legacy aggregate damage. It "
        "cannot validate assists, objectives, per-hit damage/taken, or aggregate position sampling. "
        "Those require the first completed real match captured after the new schema is deployed.", "",
    ]
    return "\n".join(out)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="local .sql or .sql.gz database dump")
    parser.add_argument("--output-dir", type=Path, default=REPO / "build" / "phase-b-real")
    parser.add_argument("--all-markdown", action="store_true", help="render Markdown for every match")
    parser.add_argument("--keep-db", action="store_true", help="keep isolated DB for debugging")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    reports: list[dict[str, Any]] = []
    with EphemeralMysql.start(keep=args.keep_db) as db:
        analytics.load_fixture(db, args.fixture)
        sources = analytics.source_capabilities(db)
        match_ids_by_source = source_match_ids(db)
        table_counts = source_table_counts(db)
        match_ids = sorted(set().union(*match_ids_by_source.values()))
        if not all((sources["per_hit_damage"], sources["capture_credits"], sources["positions"])):
            analytics.install_legacy_compatibility(db)
        for match_id in match_ids:
            reports.append(analytics.build_report(db, match_id, args.fixture, sources))

    reports_dir = args.output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    representatives = choose_representatives(reports)
    markdown_ids = set(representatives.values())
    if args.all_markdown:
        markdown_ids.update(r["match_id"] for r in reports)
    for report in reports:
        match_id = report["match_id"]
        file_name = safe_report_name(match_id)
        (reports_dir / f"{file_name}.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        if match_id in markdown_ids:
            (reports_dir / f"{file_name}.md").write_text(
                analytics.render_markdown(report), encoding="utf-8"
            )
    summary = args.output_dir / "PHASE_B_VALIDATION.md"
    summary.write_text(
        render_summary(
            args.fixture, reports, sources, representatives,
            match_ids_by_source, table_counts,
        ),
        encoding="utf-8",
    )
    print(f"Analyzed {len(reports)} matches: {summary}")
    print("Quality: " + ", ".join(
        f"{level}={sum(r['quality']['status'] == level for r in reports)}"
        for level in ("PASS", "WARN", "FAIL")
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
