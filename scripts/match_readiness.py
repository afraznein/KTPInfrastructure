#!/usr/bin/env python3
"""Validate one match in a local SQL fixture and write an aggregate-only gate.

This command does not start MySQL, contact a shared service, or publish data.
It parses a ``.sql`` or ``.sql.gz`` fixture directly, applies deterministic
source-quality checks, and writes JSON plus Markdown suitable for CI artifacts.

Exit codes: 0 = PASS/WARN, 1 = FAIL, 2 = invalid invocation/source.
Use ``--strict`` when WARN should also return 1.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


SCHEMA_VERSION = 1
MATCH_ID_RE = re.compile(r"(?:\d+-KTP\d+|[A-Za-z0-9._-]+-TEST)$")
INSERT_RE = re.compile(r"^INSERT INTO `([^`]+)` \((.*?)\) VALUES \((.*)\);$")
TEAM_NAMES = {1: "Allies", 2: "Axis"}
REQUIRED_EVENT_TABLES = (
    "hlstats_Events_Frags",
    "ktp_damage_events",
    "ktp_position_samples",
)
WANTED_TABLES = {
    "hlstats_Actions",
    "hlstats_Events_Frags",
    "hlstats_Events_PlayerActions",
    "hlstats_Events_PlayerPlayerActions",
    "hlstats_Events_Statsme",
    "hlstats_Events_Statsme2",
    "ktp_damage_events",
    "ktp_flag_captures",
    "ktp_flag_state_events",
    "ktp_match_players",
    "ktp_matches",
    "ktp_position_samples",
}
FORBIDDEN_PUBLIC_KEYS = {
    "player_name", "steam_id", "player_id", "killer_id", "victim_id",
    "attacker_id", "assister_id", "pos_x", "pos_y", "pos_z",
    "pos_victim_x", "pos_victim_y", "pos_victim_z",
}
FORBIDDEN_PUBLIC_KEY_TOKENS = {
    re.sub(r"[^a-z0-9]", "", key.lower()) for key in FORBIDDEN_PUBLIC_KEYS
}


def _open_text(path: Path):
    return gzip.open(path, "rt", encoding="utf-8", errors="replace") \
        if path.suffix == ".gz" else path.open("r", encoding="utf-8", errors="replace")


def parse_value(value: str) -> str | None:
    value = value.strip()
    return None if value.upper() == "NULL" else value


def iter_rows(path: Path, wanted: set[str] | None = None) -> Iterator[tuple[str, dict[str, str | None]]]:
    """Yield single-row INSERT records from a Lane B mysqldump fixture."""
    with _open_text(path) as handle:
        for line_number, line in enumerate(handle, start=1):
            match = INSERT_RE.match(line.rstrip("\r\n"))
            if not match:
                continue
            table, columns_text, tuple_text = match.groups()
            if wanted is not None and table not in wanted:
                continue
            columns = [column.strip().strip("`") for column in columns_text.split(",")]
            values = next(csv.reader(
                [tuple_text], delimiter=",", quotechar="'", escapechar="\\"
            ))
            if len(columns) != len(values):
                raise ValueError(
                    f"{path.name}:{line_number}: {table} has {len(columns)} columns "
                    f"but {len(values)} values"
                )
            yield table, {
                column: parse_value(value) for column, value in zip(columns, values)
            }


def load_tables(path: Path) -> dict[str, list[dict[str, str | None]]]:
    tables: dict[str, list[dict[str, str | None]]] = defaultdict(list)
    for table, row in iter_rows(path, WANTED_TABLES):
        tables[table].append(row)
    return dict(tables)


def discover_match_ids(tables: dict[str, list[dict[str, Any]]]) -> list[str]:
    return sorted({
        str(row["match_id"])
        for rows in tables.values()
        for row in rows
        if row.get("match_id")
    })


def integer(value: Any, default: int = 0) -> int:
    return default if value in (None, "") else int(value)


def floating(value: Any, default: float = 0.0) -> float:
    return default if value in (None, "") else float(value)


def timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")


def rows_for(tables: dict[str, list[dict[str, Any]]], table: str, match_id: str) -> list[dict[str, Any]]:
    return [row for row in tables.get(table, []) if row.get("match_id") == match_id]


def finding(level: str, code: str, message: str, **evidence: Any) -> dict[str, Any]:
    return {"level": level, "code": code, "message": message, "evidence": evidence}


def duplicate_count(rows: Iterable[dict[str, Any]], ignored=("id", "created_at")) -> int:
    seen: set[tuple] = set()
    duplicates = 0
    for row in rows:
        signature = tuple(sorted((key, value) for key, value in row.items() if key not in ignored))
        if signature in seen:
            duplicates += 1
        else:
            seen.add(signature)
    return duplicates


def coordinate_coverage(frags: list[dict[str, Any]]) -> tuple[int, float]:
    coordinate_rows = sum(
        all(row.get(key) is not None for key in (
            "pos_x", "pos_y", "pos_victim_x", "pos_victim_y"
        ))
        for row in frags
    )
    return coordinate_rows, (100.0 * coordinate_rows / len(frags) if frags else 0.0)


def position_interval_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_player: dict[int, list[datetime]] = defaultdict(list)
    for row in rows:
        when = timestamp(row.get("event_time"))
        if when is not None:
            by_player[integer(row.get("player_id"))].append(when)
    gaps: list[float] = []
    for times in by_player.values():
        times.sort()
        gaps.extend((right - left).total_seconds() for left, right in zip(times, times[1:]) if right > left)
    if not gaps:
        return {"players_with_timing": len(by_player), "gap_count": 0, "median_seconds": None, "p95_seconds": None}
    gaps.sort()
    p95_index = min(len(gaps) - 1, math.ceil(0.95 * len(gaps)) - 1)
    return {
        "players_with_timing": len(by_player),
        "gap_count": len(gaps),
        "median_seconds": round(statistics.median(gaps), 3),
        "p95_seconds": round(gaps[p95_index], 3),
    }


def damage_alignment(damage: list[dict[str, Any]], positions: list[dict[str, Any]], max_seconds=3.0) -> tuple[int, int]:
    by_player: dict[int, list[datetime]] = defaultdict(list)
    for row in positions:
        when = timestamp(row.get("event_time"))
        if when is not None:
            by_player[integer(row.get("player_id"))].append(when)
    for times in by_player.values():
        times.sort()
    aligned = 0
    for row in damage:
        when = timestamp(row.get("event_time"))
        if when is None:
            continue
        candidates = by_player.get(integer(row.get("attacker_id")), [])
        if candidates and min(abs((sample - when).total_seconds()) for sample in candidates) <= max_seconds:
            aligned += 1
    return aligned, len(damage)


def public_payload_is_safe(value: Any, path="report") -> list[str]:
    violations: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized_key in FORBIDDEN_PUBLIC_KEY_TOKENS:
                violations.append(f"{path}.{key}")
            violations.extend(public_payload_is_safe(nested, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            violations.extend(public_payload_is_safe(nested, f"{path}[{index}]"))
    return violations


def validate_fixture(path: Path, match_id: str | None = None) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    tables = load_tables(path)
    match_ids = discover_match_ids(tables)
    if match_id is None:
        if len(match_ids) != 1:
            raise ValueError(f"fixture contains {len(match_ids)} match IDs; pass --match-id")
        match_id = match_ids[0]
    if match_id not in match_ids:
        raise ValueError(f"match ID {match_id!r} is absent; available: {', '.join(match_ids)}")

    matches = rows_for(tables, "ktp_matches", match_id)
    roster = rows_for(tables, "ktp_match_players", match_id)
    frags = rows_for(tables, "hlstats_Events_Frags", match_id)
    damage = rows_for(tables, "ktp_damage_events", match_id)
    positions = rows_for(tables, "ktp_position_samples", match_id)
    captures = rows_for(tables, "ktp_flag_captures", match_id)
    ownership = rows_for(tables, "ktp_flag_state_events", match_id)
    player_actions = rows_for(tables, "hlstats_Events_PlayerActions", match_id)
    player_player_actions = rows_for(tables, "hlstats_Events_PlayerPlayerActions", match_id)
    statsme = rows_for(tables, "hlstats_Events_Statsme", match_id)
    statsme2 = rows_for(tables, "hlstats_Events_Statsme2", match_id)
    action_codes = {integer(row.get("id")): row.get("code") for row in tables.get("hlstats_Actions", [])}
    assists = [row for row in player_player_actions if action_codes.get(integer(row.get("actionId"))) == "assist"]
    cap_breaks = [row for row in player_actions if action_codes.get(integer(row.get("actionId"))) == "cap_break"]

    coordinate_rows, coordinate_percent = coordinate_coverage(frags)
    unique_captures = len({
        (row.get("half"), row.get("flag_name"), row.get("event_time")) for row in captures
    })
    position_timing = position_interval_summary(positions)
    damage_aligned, damage_total = damage_alignment(damage, positions)
    damage_alignment_percent = 100.0 * damage_aligned / damage_total if damage_total else 0.0
    team_counts = Counter(integer(row.get("team")) for row in roster)
    bot_count = sum(str(row.get("steam_id") or "").startswith("BOT:") for row in roster)
    event_players = {
        integer(row.get(key))
        for row, keys in (
            *((row, ("killerId", "victimId")) for row in frags),
            *((row, ("attacker_id", "victim_id")) for row in damage),
            *((row, ("player_id",)) for row in positions),
        )
        for key in keys
        if row.get(key) not in (None, "", "0", 0)
    }
    roster_players = {integer(row.get("player_id")) for row in roster}
    orphan_players = event_players - roster_players if roster else set()
    invalid_half_rows = sum(integer(row.get("half")) <= 0 for row in frags + damage + positions + captures)

    inventory = {
        "match_rows": len(matches),
        "roster_players": len(roster_players),
        "team_counts": {TEAM_NAMES.get(team, str(team)): count for team, count in sorted(team_counts.items())},
        "event_players": len(event_players),
        "frags": len(frags),
        "coordinate_frags": coordinate_rows,
        "coordinate_coverage_percent": round(coordinate_percent, 2),
        "damage_events": len(damage),
        "damage_sample_aligned": damage_aligned,
        "damage_alignment_percent": round(damage_alignment_percent, 2),
        "position_samples": len(positions),
        "position_timing": position_timing,
        "capture_credits": len(captures),
        "unique_capture_events": unique_captures,
        "flag_state_events": len(ownership),
        "assists": len(assists),
        "cap_breaks": len(cap_breaks),
        "statsme_rows": len(statsme),
        "statsme2_rows": len(statsme2),
    }
    checks: list[dict[str, Any]] = []
    checks.append(finding(
        "PASS" if MATCH_ID_RE.fullmatch(match_id) else "FAIL", "match_id_shape",
        "Match identifier has an accepted production or test shape." if MATCH_ID_RE.fullmatch(match_id)
        else "Match identifier is malformed.",
    ))
    checks.append(finding(
        "PASS" if len(matches) == 1 else "FAIL", "single_match_record",
        "Exactly one ktp_matches row exists." if len(matches) == 1
        else "Expected exactly one ktp_matches row.", rows=len(matches),
    ))
    closed = len(matches) == 1 and bool(matches[0].get("end_time"))
    checks.append(finding(
        "PASS" if closed else "FAIL", "closed_match",
        "The match has an end boundary." if closed else "The match is missing its end boundary.",
    ))

    if roster:
        expected_test = match_id.endswith("-TEST")
        roster_ok = len(roster_players) == len(roster) and (not expected_test or team_counts == Counter({1: 6, 2: 6}))
        checks.append(finding(
            "PASS" if roster_ok else "FAIL", "roster_integrity",
            "Roster identifiers are unique and the test roster is 6v6." if roster_ok
            else "Roster identifiers are duplicated or the test roster is not 6v6.",
            players=len(roster_players), teams=inventory["team_counts"],
        ))
        checks.append(finding(
            "PASS" if not orphan_players else "FAIL", "event_roster_consistency",
            "All event participants belong to the match roster." if not orphan_players
            else "Some event participants are absent from the match roster.",
            orphan_player_count=len(orphan_players),
        ))
    else:
        checks.append(finding(
            "WARN", "roster_source_missing",
            "This fixture predates ktp_match_players; event-player cardinality is retained as coverage.",
            event_players=len(event_players),
        ))

    bot_safe = match_id.endswith("-TEST") or bot_count == 0
    checks.append(finding(
        "PASS" if bot_safe else "FAIL", "bot_containment",
        "Bot identities are confined to test data." if bot_safe
        else "A bot identity appears in a non-test match.", bot_players=bot_count,
    ))
    checks.append(finding(
        "PASS" if invalid_half_rows == 0 else "FAIL", "valid_half_tags",
        "All match events use positive half tags." if invalid_half_rows == 0
        else "Some match events have half <= 0.", invalid_rows=invalid_half_rows,
    ))

    for table, rows in (("frags", frags), ("damage", damage), ("positions", positions)):
        checks.append(finding(
            "PASS" if rows else "FAIL", f"{table}_present",
            f"{table.capitalize()} rows are present." if rows else f"No {table} rows were captured.",
            rows=len(rows),
        ))

    coordinate_level = "PASS" if coordinate_percent >= 90.0 else "WARN" if coordinate_percent >= 75.0 else "FAIL"
    checks.append(finding(
        coordinate_level, "frag_coordinate_coverage",
        "At least 90% of frags contain both spatial endpoints." if coordinate_level == "PASS"
        else "Frag coordinate coverage is incomplete; spatial products will exclude rows.",
        coordinate_rows=coordinate_rows, total_rows=len(frags), percent=round(coordinate_percent, 2),
    ))
    alignment_level = "PASS" if damage_alignment_percent >= 90.0 else "WARN" if damage_alignment_percent >= 75.0 else "FAIL"
    checks.append(finding(
        alignment_level, "damage_position_alignment",
        "At least 90% of damage can be aligned to a <=3-second attacker sample." if alignment_level == "PASS"
        else "Sample-aligned damage coverage is incomplete.",
        aligned=damage_aligned, total=damage_total, percent=round(damage_alignment_percent, 2),
    ))
    median_gap = position_timing["median_seconds"]
    timing_ok = median_gap is not None and 3.0 <= median_gap <= 8.0
    checks.append(finding(
        "PASS" if timing_ok else "WARN", "position_sampling_interval",
        "Median sampling interval is compatible with the configured 5-second cadence." if timing_ok
        else "Sampling cadence is unavailable or outside the expected 3-8 second band.",
        **position_timing,
    ))

    duplicate_specs = (
        # Damage timestamps have one-second precision, so two identical hits in
        # the same second are suspicious but not proof of duplicate ingestion.
        ("frags", frags, "FAIL"), ("damage", damage, "WARN"),
        ("captures", captures, "FAIL"), ("positions", positions, "WARN"),
    )
    for label, rows, duplicate_level in duplicate_specs:
        duplicates = duplicate_count(rows)
        checks.append(finding(
            "PASS" if duplicates == 0 else duplicate_level, f"duplicate_{label}",
            f"No exact duplicate {label} rows were found." if duplicates == 0
            else f"Exact duplicate {label} rows were found.", duplicates=duplicates,
        ))

    checks.append(finding(
        "PASS" if assists else "WARN", "assist_coverage",
        "Assist rows are present." if assists else "No assist rows are present; distinguish zero from unavailable.",
        rows=len(assists),
    ))
    checks.append(finding(
        "PASS" if statsme else "WARN", "statsme_coverage",
        "Weapon totals are present." if statsme else "StatsMe weapon totals are unavailable.", rows=len(statsme),
    ))
    checks.append(finding(
        "PASS" if statsme2 else "WARN", "statsme2_coverage",
        "Hit-location totals are present." if statsme2 else "StatsMe2 hit-location totals are unavailable.", rows=len(statsme2),
    ))
    checks.append(finding(
        "PASS" if len(captures) >= unique_captures else "FAIL", "capture_grouping",
        "Capture credits group into plausible unique capture events." if len(captures) >= unique_captures
        else "Unique capture events exceed capture-credit rows.",
        credits=len(captures), unique_events=unique_captures,
    ))
    checks.append(finding(
        "PASS" if ownership else "WARN", "flag_ownership_coverage",
        "Flag ownership events are present." if ownership
        else "Flag ownership events are unavailable; capout reconstruction may be incomplete.", rows=len(ownership),
    ))

    severity = {"PASS": 0, "WARN": 1, "FAIL": 2}
    status = max((item["level"] for item in checks), key=severity.get, default="FAIL")
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "fixture": path.name,
        "match_id": match_id,
        "status": status,
        "privacy": "aggregate_only",
        "inventory": inventory,
        "checks": checks,
    }
    violations = public_payload_is_safe(report)
    if violations:
        raise AssertionError(f"public readiness payload contains private fields: {violations}")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    inventory = report["inventory"]
    out = [
        "# Match readiness report", "",
        f"- Result: **{report['status']}**",
        f"- Match: `{report['match_id']}`",
        f"- Fixture: `{report['fixture']}`",
        "- Privacy: aggregate-only; no player identities, individual coordinates, or routes", "",
        "## Source inventory", "",
        "| Source | Rows/coverage |", "|---|---:|",
        f"| Roster | {inventory['roster_players']} |",
        f"| Event participants | {inventory['event_players']} |",
        f"| Frags | {inventory['frags']} |",
        f"| Frags with both endpoints | {inventory['coordinate_frags']} ({inventory['coordinate_coverage_percent']}%) |",
        f"| Damage events | {inventory['damage_events']} |",
        f"| Damage aligned to <=3s sample | {inventory['damage_sample_aligned']} ({inventory['damage_alignment_percent']}%) |",
        f"| Position samples | {inventory['position_samples']} |",
        f"| Assists | {inventory['assists']} |",
        f"| Cap breaks | {inventory['cap_breaks']} |",
        f"| Capture credits / unique events | {inventory['capture_credits']} / {inventory['unique_capture_events']} |",
        f"| Flag ownership events | {inventory['flag_state_events']} |",
        f"| StatsMe / StatsMe2 | {inventory['statsme_rows']} / {inventory['statsme2_rows']} |", "",
        "## Checks", "",
        "| Result | Code | Explanation | Evidence |", "|---|---|---|---|",
    ]
    for item in report["checks"]:
        evidence = ", ".join(f"{key}={value}" for key, value in item["evidence"].items()) or "-"
        out.append(f"| {item['level']} | `{item['code']}` | {item['message']} | {evidence} |")
    out += ["", "A `FAIL` blocks promotion. A `WARN` records a known coverage limitation and is non-blocking unless `--strict` is used.", ""]
    return "\n".join(out)


def write_report(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "match-readiness.json"
    markdown_path = output_dir / "MATCH_READINESS.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="local .sql or .sql.gz fixture")
    parser.add_argument("--match-id", help="required when the fixture contains multiple matches")
    parser.add_argument("--output-dir", type=Path, default=Path("build/match-readiness"))
    parser.add_argument("--strict", action="store_true", help="treat WARN as a failing exit status")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = validate_fixture(args.fixture, args.match_id)
        json_path, markdown_path = write_report(report, args.output_dir)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"match-readiness: {exc}", file=sys.stderr)
        return 2
    print(f"Match readiness: {report['status']}")
    print(f"  Markdown: {markdown_path}")
    print(f"  JSON: {json_path}")
    return int(report["status"] == "FAIL" or (args.strict and report["status"] == "WARN"))


if __name__ == "__main__":
    raise SystemExit(main())
