#!/usr/bin/env python3
"""Generate a read-only JSON and Markdown analytics report for one match.

Phase A deliberately supports persisted local fixture dumps only. It starts an
isolated MySQL/MariaDB instance, imports the dump, runs SELECT-only SQL, writes
the report locally, and tears the database down. It has no HTTP client and no
production database configuration.

Usage (inside the Lane B image, with this repository mounted at /work):

    python3 scripts/match_analytics.py \
      tests/e2e_stats/fixtures/.../hlstatsx-fixture.sql.gz \
      --output-dir /work/build/match-analytics
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.e2e_stats.ephemeral_mysql import EphemeralMysql  # noqa: E402
from scripts.match_timelines import TimelineConfig, build_shadow_timelines  # noqa: E402


REPO = Path(__file__).resolve().parents[1]
SQL_DIR = REPO / "sql" / "analytics"
SCHEMA_VERSION = 3
TEAM_NAMES = {1: "Allies", 2: "Axis"}

INTEGER_COLUMNS = {
    "server_id", "player_id", "team", "duration_seconds", "halves_played",
    "open_halves", "is_test_match", "kills", "deaths", "assists",
    "headshots", "team_kills", "suicides", "damage_dealt", "damage_taken",
    "team_damage", "self_damage", "capture_credits", "cap_breaks", "shots",
    "hits", "position_samples", "headshot_kills", "head_hits", "chest_hits",
    "stomach_hits", "arm_hits", "leg_hits", "located_hits", "statsme_kills",
    "statsme_deaths", "statsme_damage", "half", "credited_players",
    "match_halves", "roster_players", "distinct_roster_players", "frags",
    "invalid_half_frags", "damage_events", "invalid_half_damage",
    "statsme_rows", "statsme2_rows", "statsme_hits", "unique_capture_events",
    "cached_player_totals", "cached_kills", "cached_deaths", "victim_id",
    "legacy_damage_dealt",
    "event_id", "event_unix", "killer_id", "killer_team", "victim_team",
    "match_type", "flag_index", "owner_team", "is_initial",
}
FLOAT_COLUMNS = {
    "kd_ratio", "kda_ratio", "damage_per_minute", "headshot_rate",
    "raw_accuracy",
}


def sql_literal(value: str) -> str:
    """Return a MySQL string literal for a value selected by the operator."""
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def read_query(name: str, match_id: str) -> str:
    path = SQL_DIR / name
    query = path.read_text(encoding="utf-8").replace(
        "{{MATCH_ID}}", sql_literal(match_id)
    )
    # This is a defense against an accidental mutating analytics file, not a
    # general SQL parser. The checked-in query files are also reviewed/tests.
    first = query.lstrip().lower()
    while first.startswith("--"):
        first = first.split("\n", 1)[1].lstrip()
    if not (first.startswith("select") or first.startswith("with")):
        raise ValueError(f"analytics query is not read-only: {path}")
    return query


def _value(name: str, raw: str) -> Any:
    if raw == "NULL":
        return None
    if name in INTEGER_COLUMNS:
        return int(raw)
    if name in FLOAT_COLUMNS:
        return float(raw)
    return raw


def tsv_rows(output: str) -> list[dict[str, Any]]:
    if not output.strip():
        return []
    # mysql --batch --raw emits TSV, not CSV. Quote characters are ordinary
    # field data (a malformed historical match_id contains them), so enabling
    # csv's default quote handling silently changes identifiers.
    reader = csv.DictReader(output.splitlines(), delimiter="\t", quoting=csv.QUOTE_NONE)
    return [
        {name: _value(name, raw) for name, raw in row.items()}
        for row in reader
    ]


def query_rows(db: EphemeralMysql, name: str, match_id: str) -> list[dict[str, Any]]:
    return tsv_rows(db.sql(read_query(name, match_id)))


def load_fixture(db: EphemeralMysql, fixture: Path) -> None:
    """Stream .sql or .sql.gz into the isolated database without extracting."""
    fixture = fixture.resolve()
    if not fixture.is_file():
        raise FileNotFoundError(f"fixture not found: {fixture}")
    argv = [
        db.client, "--no-defaults", f"--socket={db.socket_path}",
        "-u", "root", db.database,
    ]
    opener = gzip.open if fixture.suffix == ".gz" else Path.open
    with opener(fixture, "rb") as source:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        assert proc.stdin is not None
        try:
            shutil.copyfileobj(source, proc.stdin, length=1024 * 1024)
        finally:
            proc.stdin.close()
        stderr = proc.stderr.read() if proc.stderr is not None else b""
        rc = proc.wait()
    if rc:
        raise RuntimeError(
            f"fixture load failed ({fixture.name}): "
            f"{stderr.decode(errors='replace')[-1500:]}"
        )


def discover_match_ids(db: EphemeralMysql) -> list[str]:
    rows = tsv_rows(db.sql(
        "SELECT DISTINCT match_id FROM ktp_matches "
        "WHERE match_id IS NOT NULL ORDER BY match_id"
    ))
    return [str(row["match_id"]) for row in rows]


def source_capabilities(db: EphemeralMysql) -> dict[str, bool]:
    """Inventory source support before any local compatibility objects exist."""
    rows = tsv_rows(db.sql("""
SELECT
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'ktp_damage_events')
    AS per_hit_damage,
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'ktp_flag_captures')
    AS capture_credits,
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'ktp_position_samples')
    AS positions,
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'ktp_flag_state_events')
    AS flag_ownership,
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'hlstats_Events_Statsme')
    AS statsme,
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'hlstats_Events_Statsme2')
    AS statsme2,
  EXISTS(SELECT 1 FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'ktp_match_stats')
    AS legacy_match_cache,
  EXISTS(SELECT 1 FROM hlstats_Actions
    WHERE game = 'dod' AND code = 'assist')
    AS assists
"""))
    if not rows:
        raise RuntimeError("could not inventory analytics source capabilities")
    return {name: bool(int(value)) for name, value in rows[0].items()}


def install_legacy_compatibility(db: EphemeralMysql) -> None:
    """Install empty optional tables only in the caller's ephemeral database."""
    compatibility = REPO / "sql" / "compatibility" / "legacy_optional_sources.sql"
    db.sql(compatibility.read_text(encoding="utf-8"))


def check(level: str, code: str, message: str, **evidence: Any) -> dict[str, Any]:
    return {"level": level, "code": code, "message": message, "evidence": evidence}


def evaluate_quality(
    match_id: str,
    match: dict[str, Any] | None,
    players: list[dict[str, Any]],
    inventory: dict[str, Any],
    sources: dict[str, bool] | None = None,
    source_mode: str = "database",
) -> dict[str, Any]:
    """Return transparent checks; never repair a source mismatch here."""
    checks: list[dict[str, Any]] = []
    sources = sources or {
        "per_hit_damage": True, "capture_credits": True, "positions": True,
        "flag_ownership": True,
        "statsme": True, "statsme2": True, "legacy_match_cache": True,
        "assists": True,
    }
    checks.append(check(
        "PASS" if re.fullmatch(r"\d+-KTP\d+|[A-Za-z0-9._-]+-TEST", match_id) else "FAIL",
        "match_id_shape",
        "Match identifier has a recognized production or test shape."
        if re.fullmatch(r"\d+-KTP\d+|[A-Za-z0-9._-]+-TEST", match_id)
        else "Match identifier is malformed; preserve it for source-data investigation.",
        match_id=match_id,
    ))
    if source_mode == "replay":
        checks.append(check(
            "WARN", "replay_timing_compressed",
            "Replay preserves event facts but not original match duration; "
            "per-minute metrics are unavailable.",
        ))
    if match is None:
        checks.append(check("FAIL", "missing_match", "No ktp_matches row exists."))
    else:
        checks.append(check(
            "PASS" if match["open_halves"] == 0 else "FAIL",
            "closed_match",
            "All recorded halves are closed." if match["open_halves"] == 0
            else "At least one recorded half has no end boundary.",
            open_halves=match["open_halves"],
        ))

    roster = inventory.get("roster_players", 0)
    distinct = inventory.get("distinct_roster_players", 0)
    checks.append(check(
        "PASS" if roster > 0 and roster == distinct == len(players) else "FAIL",
        "roster_integrity",
        "Roster keys and canonical player rows reconcile."
        if roster > 0 and roster == distinct == len(players)
        else "Roster is empty, duplicated, or does not match the player fact.",
        roster_rows=roster, distinct_players=distinct, fact_rows=len(players),
    ))

    if match_id.endswith("-TEST"):
        checks.append(check(
            "PASS" if roster == 12 else "WARN",
            "test_roster_size",
            "Synthetic match has the current 6v6 roster."
            if roster == 12 else "Synthetic fixture is not the current 12-player shape.",
            roster_players=roster, expected=12,
        ))

    invalid = inventory.get("invalid_half_frags", 0) + inventory.get("invalid_half_damage", 0)
    checks.append(check(
        "PASS" if invalid == 0 else "FAIL",
        "valid_half_tags",
        "Frag and damage events use live half tags."
        if invalid == 0 else "Some frag or damage events have half <= 0.",
        invalid_rows=invalid,
    ))

    cached_rows = inventory.get("cached_player_totals", 0)
    fact_kills = sum(p["kills"] for p in players)
    fact_deaths = sum(p["deaths"] for p in players)
    if cached_rows == 0:
        checks.append(check(
            "WARN", "aggregate_cache_missing",
            "ktp_match_stats half=0 has no rows; raw event facts remain usable.",
        ))
    else:
        matches = (fact_kills == inventory["cached_kills"]
                   and fact_deaths == inventory["cached_deaths"])
        checks.append(check(
            "PASS" if matches else "FAIL", "aggregate_reconciliation",
            "Raw frag totals reconcile with ktp_match_stats half=0."
            if matches else "Raw frag totals disagree with ktp_match_stats half=0.",
            fact_kills=fact_kills, cached_kills=inventory["cached_kills"],
            fact_deaths=fact_deaths, cached_deaths=inventory["cached_deaths"],
        ))

    dealt = sum(p.get("damage_dealt") or 0 for p in players)
    taken = sum(p.get("damage_taken") or 0 for p in players)
    if not sources["per_hit_damage"]:
        checks.append(check(
            "WARN", "damage_source_not_captured",
            "This archive predates per-hit damage; legacy aggregate damage is shown.",
        ))
    elif inventory.get("damage_events", 0) == 0:
        checks.append(check("WARN", "damage_missing", "No per-hit damage rows exist."))
    else:
        checks.append(check(
            "PASS" if dealt == taken else "FAIL", "damage_balance",
            "Opponent damage dealt equals opponent damage taken."
            if dealt == taken else "Opponent damage dealt and taken do not balance.",
            damage_dealt=dealt, damage_taken=taken,
        ))

    checks.append(check(
        "PASS" if sources["assists"] else "WARN", "assist_source_coverage",
        "Assist event support is present." if sources["assists"]
        else "This archive predates the assist action; zero does not mean no assists occurred.",
    ))

    statsme_rows = inventory.get("statsme_rows", 0)
    statsme2_rows = inventory.get("statsme2_rows", 0)
    checks.append(check(
        "PASS" if statsme_rows > 0 else "WARN", "statsme_coverage",
        "Weapon shots and hits are present." if statsme_rows > 0
        else "No StatsMe weapon rows exist; accuracy is unavailable.",
        rows=statsme_rows,
    ))
    checks.append(check(
        "PASS" if statsme2_rows > 0 else "WARN", "hitbox_coverage",
        "Weapon hit-location rows are present." if statsme2_rows > 0
        else "No StatsMe2 hit-location rows exist.",
        rows=statsme2_rows,
    ))
    if statsme_rows and statsme2_rows:
        located = inventory["located_hits"]
        hits = inventory["statsme_hits"]
        checks.append(check(
            "PASS" if located <= hits else "WARN", "hitbox_reconciliation",
            "Located hits do not exceed StatsMe hits."
            if located <= hits else "Located hits exceed StatsMe hits; inspect flush semantics.",
            located_hits=located, statsme_hits=hits,
        ))

    credits = inventory.get("capture_credits", 0)
    events = inventory.get("unique_capture_events", 0)
    checks.append(check(
        "WARN" if not sources["capture_credits"] else
        ("PASS" if credits >= events else "FAIL"), "capture_grouping",
        "This archive predates dedicated capture credits; zero is unavailable."
        if not sources["capture_credits"] else
        "Capture credits group into plausible unique capture events."
        if credits >= events else "Unique capture count exceeds player credits.",
        capture_credits=credits, unique_capture_events=events,
    ))

    positions = inventory.get("position_samples", 0)
    checks.append(check(
        "PASS" if sources["positions"] and positions > 0 else "WARN",
        "aggregate_position_coverage",
        "This archive predates aggregate position samples."
        if not sources["positions"] else
        "Aggregate positional coverage is present and remains internal."
        if positions > 0 else "No position samples exist.",
        aggregate_samples=positions,
    ))

    bot_rows = sum(str(p.get("steam_id", "")).startswith("BOT:") for p in players)
    bots_allowed = match_id.endswith("-TEST") or bot_rows == 0
    checks.append(check(
        "PASS" if bots_allowed else "FAIL", "bot_containment",
        "Bot identities occur only in test data." if bots_allowed
        else "Bot identities were found in a non-test match.",
        bot_players=bot_rows,
    ))

    rank = {"PASS": 0, "WARN": 1, "FAIL": 2}
    status = max((c["level"] for c in checks), key=rank.get, default="FAIL")
    return {"status": status, "checks": checks}


def public_players(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove individual positional coverage from shareable player records."""
    public = []
    for player in players:
        row = {key: value for key, value in player.items()
               if key != "position_samples"}
        row["team_name"] = TEAM_NAMES.get(row.get("team"), "Unknown")
        public.append(row)
    return public


def with_team_names(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    named = []
    for source in rows:
        row = dict(source)
        row["team_name"] = TEAM_NAMES.get(row.get("team"), "Unknown")
        named.append(row)
    return named


def team_summary(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    additive = (
        "kills", "deaths", "assists", "damage_dealt", "damage_taken",
        "team_damage", "self_damage", "capture_credits", "cap_breaks",
        "shots", "hits",
    )
    teams: dict[int, dict[str, Any]] = {}
    for player in players:
        team = player.get("team")
        if team not in TEAM_NAMES:
            continue
        row = teams.setdefault(team, {
            "team": team, "team_name": TEAM_NAMES[team], "players": 0,
            **{field: 0 for field in additive},
        })
        row["players"] += 1
        for field in additive:
            row[field] += player.get(field, 0) or 0
    for row in teams.values():
        has_taken = all(p.get("damage_taken") is not None
                        for p in players if p.get("team") == row["team"])
        if not has_taken:
            row["damage_taken"] = None
        row["damage_differential"] = (
            row["damage_dealt"] - row["damage_taken"] if has_taken else None
        )
        row["raw_accuracy"] = (
            round(row["hits"] / row["shots"], 3) if row["shots"] else None
        )
    return [teams[key] for key in sorted(teams)]


def md(value: Any) -> str:
    if value is None:
        return "—"
    return str(value).replace("|", "\\|").replace("\n", " ")


def markdown_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    if not rows:
        return "_No rows._\n"
    lines = [
        "| " + " | ".join(label for _, label in columns) + " |",
        "|" + "|".join("---" for _ in columns) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(md(row.get(key)) for key, _ in columns) + " |")
    return "\n".join(lines) + "\n"


def render_markdown(report: dict[str, Any]) -> str:
    match = report.get("match") or {}
    quality = report["quality"]
    out = [
        f"# Match analytics — {report['match_id']}", "",
        f"Quality: **{quality['status']}**", "",
        f"Source mode: `{report.get('source_mode', 'database')}`  ",
        f"Temporal metrics valid: "
        f"{'yes' if report.get('temporal_metrics_valid', True) else 'no'}  ",
        f"Map: `{md(match.get('map_name'))}`  ",
        f"Halves: {md(match.get('halves_played'))}  ",
        f"Live duration: {md(match.get('duration_seconds'))} seconds  ",
        "", "## Source coverage", "",
        "| Source | Captured |", "|---|---|",
    ]
    for source, captured in report.get("source_coverage", {}).items():
        out.append(f"| `{source}` | {'yes' if captured else 'no'} |")
    out += [
        "", "Uncaptured sources are reported as unavailable, not as observed zeroes. "
        "For legacy archives, Damage uses `ktp_match_stats`; damage taken and +/- remain unavailable.",
        "", "## Team summary", "",
        markdown_table(report["teams"], [
            ("team_name", "Team"), ("kills", "K"), ("deaths", "D"),
            ("assists", "Assists"), ("damage_dealt", "Damage"),
            ("damage_taken", "Taken"), ("damage_differential", "+/-"),
            ("capture_credits", "Caps"), ("cap_breaks", "Breaks"),
            ("raw_accuracy", "Raw acc."),
        ]),
        "", "## Box score", "",
        markdown_table(report["players"], [
            ("player_name_at_match", "Player"), ("team_name", "Team"),
            ("kills", "K"), ("deaths", "D"), ("assists", "Assists"),
            ("kd_ratio", "K/D"), ("damage_dealt", "Damage"),
            ("damage_taken", "Taken"), ("damage_differential", "+/-"),
            ("headshots", "HS"), ("capture_credits", "Caps"),
            ("cap_breaks", "Breaks"), ("raw_accuracy", "Raw acc."),
            ("damage_per_minute", "Dmg/min"),
        ]),
        "Raw accuracy is descriptive by weapon and is not suitable for player "
        "ranking; Garand chamber-clearing shots are not distinguishable from misses.",
        "", "## Assists", "",
        markdown_table(report["assists"], [
            ("player_name_at_match", "Assister"), ("team_name", "Team"),
            ("victim_name_at_match", "Assisted against"),
            ("assists", "Assists"),
        ]),
        "Assist weapon is not reported because the assist event does not carry "
        "one; nearby damage is not treated as a safe substitute.",
        "", "## Private shadow timelines", "",
        f"Status: `{report.get('shadow_timelines', {}).get('status', 'not_collected')}`  ",
        "Exploratory only: no database writes, public API output, or rating impact.",
        "",
        markdown_table(report.get("shadow_timelines", {}).get("opening_duels", []), [
            ("half", "Half"), ("event_time", "Opening time"),
            ("weapon", "Weapon"), ("headshot", "Headshot"),
        ]),
        f"Fast multikills: {len(report.get('shadow_timelines', {}).get('fast_multikills', []))}  ",
        f"Basic trades: {len(report.get('shadow_timelines', {}).get('trades', []))}  ",
        f"Head-to-head pairs: {len(report.get('shadow_timelines', {}).get('head_to_head', []))}",
        "", "## Weapon facts", "",
        markdown_table(report["weapons"], [
            ("player_name_at_match", "Player"), ("weapon", "Weapon"),
            ("kills", "K"), ("damage_dealt", "Damage"), ("shots", "Shots"),
            ("hits", "Hits"), ("raw_accuracy", "Raw acc."),
            ("head_hits", "Head"), ("chest_hits", "Chest"),
            ("stomach_hits", "Stomach"), ("arm_hits", "Arms"),
            ("leg_hits", "Legs"),
        ]),
        "", "## Capture credits", "",
        markdown_table(report["capture_credits"], [
            ("player_name_at_match", "Player"), ("team_name", "Team"),
            ("flag_name", "Flag"), ("capture_credits", "Credits"),
        ]),
        "", "## Unique capture events", "",
        markdown_table(report["capture_events"], [
            ("event_time", "Time"), ("half", "Half"), ("team_name", "Team"),
            ("flag_name", "Flag"), ("credited_players", "Credited players"),
        ]),
        "", "## Data quality", "",
        "| Result | Check | Detail |", "|---|---|---|",
    ]
    for item in quality["checks"]:
        out.append(f"| {item['level']} | `{item['code']}` | {md(item['message'])} |")
    out += [
        "", "## Positional privacy", "",
        "Raw player positions and individual positional coverage are intentionally "
        "excluded. Only the aggregate sample count is used as an internal quality check.",
        "",
    ]
    return "\n".join(out)


def build_report(
    db: EphemeralMysql,
    match_id: str,
    fixture: Path,
    sources: dict[str, bool] | None = None,
    source_mode: str = "database",
    timeline_config: TimelineConfig | None = None,
) -> dict[str, Any]:
    match_rows = query_rows(db, "match_fact.sql", match_id)
    players = query_rows(db, "player_match_fact.sql", match_id)
    weapons = query_rows(db, "weapon_fact.sql", match_id)
    assists = (query_rows(db, "assist_fact.sql", match_id)
               if sources is None or sources.get("assists", True) else [])
    credits = (query_rows(db, "capture_credit_fact.sql", match_id)
               if sources is None or sources.get("capture_credits", True) else [])
    events = (query_rows(db, "capture_event_fact.sql", match_id)
              if sources is None or sources.get("capture_credits", True) else [])
    frag_timeline = query_rows(db, "frag_timeline_fact.sql", match_id)
    objective_timeline = (query_rows(db, "objective_timeline_fact.sql", match_id)
                          if sources is None or sources.get("capture_credits", True)
                          else [])
    inventory_rows = query_rows(db, "quality_inventory.sql", match_id)
    inventory = inventory_rows[0] if inventory_rows else {}
    match = match_rows[0] if match_rows else None
    sources = sources or source_capabilities(db)
    if not sources["per_hit_damage"]:
        cached = {
            row["player_id"]: row["legacy_damage_dealt"]
            for row in query_rows(db, "legacy_player_cache.sql", match_id)
        }
        duration = (match or {}).get("duration_seconds", 0) or 0
        for player in players:
            damage = cached.get(player["player_id"])
            player["damage_dealt"] = damage
            player["damage_taken"] = None
            player["damage_differential"] = None
            player["damage_per_minute"] = (
                round(damage * 60.0 / duration, 2)
                if damage is not None and duration else None
            )
    if source_mode == "replay":
        for player in players:
            player["damage_per_minute"] = None
    quality = evaluate_quality(
        match_id, match, players, inventory, sources, source_mode
    )
    players_public = public_players(players)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_fixture": fixture.name,
        "source_mode": source_mode,
        "temporal_metrics_valid": source_mode != "replay",
        "source_coverage": sources,
        "match_id": match_id,
        "match": match,
        "quality": quality,
        "source_inventory": inventory,
        "teams": team_summary(players_public),
        "players": players_public,
        "assists": with_team_names(assists),
        "weapons": with_team_names(weapons),
        "capture_credits": with_team_names(credits),
        "capture_events": events,
        "shadow_timelines": build_shadow_timelines(
            frag_timeline, objective_timeline, timeline_config,
            temporal_valid=source_mode != "replay",
        ),
        "positional": {
            "privacy": "aggregate_only",
            "aggregate_sample_count": inventory.get("position_samples", 0),
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="local .sql or .sql.gz fixture")
    parser.add_argument("--match-id", help="required only when a dump has multiple matches")
    parser.add_argument("--output-dir", type=Path, default=REPO / "build" / "match-analytics")
    parser.add_argument("--keep-db", action="store_true", help="keep isolated DB for debugging")
    parser.add_argument("--source-mode", choices=("database", "replay"),
                        default="database",
                        help="replay suppresses invalid time-normalized metrics")
    parser.add_argument("--multikill-seconds", type=float, default=10.0)
    parser.add_argument("--trade-seconds", type=float, default=5.0)
    parser.add_argument("--objective-conversion-seconds", type=float, default=30.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    with EphemeralMysql.start(keep=args.keep_db) as db:
        load_fixture(db, args.fixture)
        sources = source_capabilities(db)
        if not all((sources["per_hit_damage"], sources["capture_credits"],
                    sources["positions"])):
            install_legacy_compatibility(db)
        match_ids = discover_match_ids(db)
        if args.match_id:
            if args.match_id not in match_ids:
                raise SystemExit(f"match {args.match_id!r} not in fixture: {match_ids}")
            match_id = args.match_id
        elif len(match_ids) == 1:
            match_id = match_ids[0]
        else:
            raise SystemExit(
                f"fixture contains {len(match_ids)} matches; pass --match-id. "
                f"Available: {match_ids}"
            )
        report = build_report(
            db, match_id, args.fixture, sources, args.source_mode,
            TimelineConfig(
                multikill_seconds=args.multikill_seconds,
                trade_seconds=args.trade_seconds,
                objective_conversion_seconds=args.objective_conversion_seconds,
            ),
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / f"{match_id}.json"
    md_path = args.output_dir / f"{match_id}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"{report['quality']['status']}: {match_id}")
    print(json_path)
    print(md_path)
    return 0 if report["quality"]["status"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
