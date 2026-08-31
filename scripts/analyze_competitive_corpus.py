#!/usr/bin/env python3
"""Analyze every checksum-pinned fixture in a competitive-map handover.

Each SQL dump is restored into its own ephemeral MariaDB instance. Raw reports,
schema observations, and private positional working data stay under the private
output root. The public root receives only aggregate facts and derived player
totals with identifiers and positional details removed.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import statistics
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PLAYER_FIELDS = (
    "player_name_at_match", "team", "team_name", "kills", "deaths", "assists",
    "headshots", "team_kills", "suicides", "damage_dealt", "damage_taken",
    "damage_differential", "damage_per_minute", "damage_per_life", "team_damage",
    "self_damage", "capture_credits", "cap_breaks", "shots", "hits", "kd_ratio",
    "kda_ratio", "headshot_rate", "raw_accuracy",
)
PRIVATE_PUBLIC_KEYS = {
    "player_id", "steam_id", "victim_id", "attacker_id", "killer_id",
    "heatmap", "heatmap_cells", "cell_x", "cell_y", "pos_x", "pos_y", "pos_z",
    "nearest_flag", "nearest_flag_name", "flag_breakdown", "player_route", "path",
}


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def assert_public_safe(payload: Any, location: str = "root") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.casefold() in PRIVATE_PUBLIC_KEYS:
                raise ValueError(f"private key leaked at {location}.{key}")
            assert_public_safe(value, f"{location}.{key}")
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            assert_public_safe(value, f"{location}[{index}]")


def sanitize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            key: value
            for key, value in row.items()
            if key.casefold() not in PRIVATE_PUBLIC_KEYS and key != "match_id"
        }
        for row in rows
    ]


def public_players(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: row.get(key) for key in PLAYER_FIELDS} for row in rows]


def database_inventory(db: Any, analytics: Any) -> dict[str, Any]:
    tables = [
        {str(key).casefold(): value for key, value in row.items()}
        for row in analytics.tsv_rows(db.sql("""
SELECT table_name, engine
FROM information_schema.tables
WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE'
ORDER BY table_name
"""))
    ]
    columns = [
        {str(key).casefold(): value for key, value in row.items()}
        for row in analytics.tsv_rows(db.sql("""
SELECT table_name, column_name, ordinal_position, column_type, is_nullable,
       column_default, extra
FROM information_schema.columns
WHERE table_schema = DATABASE()
ORDER BY table_name, ordinal_position
"""))
    ]
    names = [str(row["table_name"]) for row in tables]
    count_query = " UNION ALL ".join(
        "SELECT " + analytics.sql_literal(name) + " AS table_name, "
        f"COUNT(*) AS row_count FROM `{name.replace('`', '``')}`"
        for name in names
    )
    counts = {
        str(row["table_name"]): int(row["row_count"])
        for original in analytics.tsv_rows(db.sql(count_query))
        for row in ({str(key).casefold(): value for key, value in original.items()},)
    }
    by_table: dict[str, list[dict[str, Any]]] = {name: [] for name in names}
    for column in columns:
        by_table[str(column["table_name"])].append({
            "name": column["column_name"],
            "ordinal": int(column["ordinal_position"]),
            "type": column["column_type"],
            "nullable": column["is_nullable"] == "YES",
            "default": column["column_default"],
            "extra": column["extra"],
        })
    return {
        "tables": [
            {
                "name": str(table["table_name"]),
                "engine": table["engine"],
                "row_count": counts[str(table["table_name"])],
                "columns": by_table[str(table["table_name"])],
            }
            for table in tables
        ]
    }


def ownership_inventory(db: Any, analytics: Any, match_id: str, sources: dict) -> dict:
    literal = analytics.sql_literal(match_id)
    flags = analytics.tsv_rows(db.sql(
        "SELECT COUNT(*) AS flag_positions FROM ktp_flag_positions"
    ))[0]
    result = {"flag_positions": int(flags["flag_positions"])}
    if not sources.get("flag_ownership"):
        return {**result, "state_events": 0, "initial_events": 0, "baseline_flags": 0}
    rows = analytics.tsv_rows(db.sql(f"""
SELECT COUNT(*) AS state_events,
       SUM(CASE WHEN is_initial = 1 THEN 1 ELSE 0 END) AS initial_events,
       COUNT(DISTINCT CASE WHEN is_initial = 1 THEN flag_index END) AS baseline_flags,
       COUNT(DISTINCT CASE WHEN owner_team IN (1, 2) THEN flag_index END) AS owned_flags
FROM ktp_flag_state_events
WHERE match_id = {literal}
"""))[0]
    result.update({key: int(value or 0) for key, value in rows.items()})
    return result


def accumulation_report(
    accumulation: Any,
    base: dict[str, Any],
    profile: dict[str, Any],
    points: dict[int, dict[str, float]],
) -> dict[str, Any]:
    empty = {
        "base_position_points": 0.0,
        "enemy_pressure_points": 0.0,
        "contested_points": 0.0,
        "double_cap_points": 0.0,
        "ownership_adjustment_points": 0.0,
        "last_flag_defense_points": 0.0,
        "position_points": 0.0,
    }
    players = [
        accumulation.accumulate_player(
            player, points.get(int(player["player_id"]), empty), profile
        )
        for player in base["players"]
    ]
    players.sort(key=lambda row: (-row["total_points"], row["player_name_at_match"] or ""))
    safe_players = sanitize_rows(players)
    event_points = sum(float(player["event_points"]) for player in safe_players)
    position_points = sum(float(player["position_points"]) for player in safe_players)
    return {
        "profile": profile["profile"]["name"],
        "status": profile["profile"]["status"],
        "event_points": round(event_points, 2),
        "position_points": round(position_points, 2),
        "combined_points": round(event_points + position_points, 2),
        "position_share_percent": round(
            100.0 * position_points / (event_points + position_points)
            if event_points + position_points else 0.0,
            2,
        ),
        "players": safe_players,
    }


def process_fixture(
    dataset_root: Path,
    public_root: Path,
    private_root: Path,
    dataset_id: str,
    map_name: str,
    map_item: dict,
    fixture: dict,
) -> dict[str, Any]:
    tools_root = dataset_root / "analysis-tools"
    if str(tools_root) not in sys.path:
        sys.path.insert(0, str(tools_root))
    from scripts import match_accumulation as accumulation  # type: ignore
    from scripts import match_analytics as analytics  # type: ignore
    from tests.e2e_stats.ephemeral_mysql import EphemeralMysql  # type: ignore

    match_id = fixture["match_id"]
    ordinal = int(fixture["ordinal"])
    source_info = fixture["files"]["hlstatsx-fixture.sql"]
    sql_path = dataset_root / source_info["path"]
    public_path = public_root / "matches" / map_name / f"{match_id}.json"
    raw_path = private_root / "raw-analytics" / map_name / f"{match_id}.json"
    schema_path = private_root / "schema" / map_name / f"{match_id}.json"

    profiles = [
        accumulation.load_profile(tools_root / "config" / "analytics" / name)
        for name in (
            "accumulation_v0.toml",
            "accumulation_v1.toml",
            "accumulation_v2_target10.toml",
        )
    ]
    with EphemeralMysql.start() as db:
        analytics.load_fixture(db, sql_path)
        sources = analytics.source_capabilities(db)
        if not all((sources["per_hit_damage"], sources["capture_credits"], sources["positions"])):
            analytics.install_legacy_compatibility(db)
        discovered = analytics.discover_match_ids(db)
        if discovered != [match_id]:
            raise ValueError(
                f"{map_name} fixture {ordinal}: expected only {match_id}, found {discovered}"
            )
        base = analytics.build_report(db, match_id, sql_path, sources)
        schema = database_inventory(db, analytics)
        ownership = ownership_inventory(db, analytics, match_id, sources)
        match = base.get("match") or {}
        samples, flags = accumulation.load_position_facts(
            db, match_id, int(match.get("server_id") or 0), map_name
        )
        topology = accumulation.load_map_objectives(
            tools_root / "config" / "analytics" / "map_objectives.toml", map_name
        )
        last_flag_kills = accumulation.load_last_flag_defense_kills(db, match_id)
        flag_states = accumulation.load_flag_state_facts(
            db, match_id, sources.get("flag_ownership", False)
        )
        accumulated = []
        for profile in profiles:
            points, private_players = accumulation.derive_private_positions(
                base["players"], samples, flags, profile, topology,
                last_flag_kills, flag_states,
            )
            accumulated.append(accumulation_report(accumulation, base, profile, points))
            private_payload = {
                "schema_version": 1,
                "classification": "PRIVATE_PLAYER_POSITIONAL_ANALYTICS",
                "redistribution": "prohibited",
                "dataset_id": dataset_id,
                "match_id": match_id,
                "map_name": map_name,
                "profile": profile,
                "map_topology": topology,
                "flags": flags,
                "flag_state_events": flag_states,
                "players": private_players,
            }
            accumulation.write_private_json(
                private_root / "accumulation" / profile["profile"]["name"]
                / map_name / f"{match_id}.private.json",
                private_payload,
            )

    raw_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(raw_path, base)
    atomic_json(schema_path, {
        "fixture_sha256": source_info["sha256"],
        "map": map_name,
        "match_id": match_id,
        **schema,
    })
    public = {
        "schema_version": 1,
        "privacy": "aggregate_and_derived_player_totals_only",
        "map": map_name,
        "cohort": map_item["cohort"],
        "quality_status": map_item["quality_status"],
        "fixture": {
            "ordinal": ordinal,
            "logical_run": fixture["logical_run"],
            "attempt": fixture["attempt"],
            "match_id": match_id,
            "quality": fixture["quality"],
            "metrics": fixture["metrics"],
            "substantive_failures": fixture["substantive_failures"],
            "warnings": fixture["ignored_failures"],
            "sql_sha256": source_info["sha256"],
        },
        "match": {
            key: match.get(key)
            for key in (
                "map_name", "started_at", "ended_at", "duration_seconds",
                "halves_played", "open_halves", "is_test_match",
            )
        },
        "quality": base["quality"],
        "source_coverage": base["source_coverage"],
        "source_inventory": base["source_inventory"],
        "ownership": ownership,
        "teams": base["teams"],
        "players": public_players(base["players"]),
        "assists": sanitize_rows(base["assists"]),
        "weapons": sanitize_rows(base["weapons"]),
        "capture_events": sanitize_rows(base["capture_events"]),
        "accumulation": accumulated,
    }
    assert_public_safe(public)
    atomic_json(public_path, public)
    return {
        "map": map_name,
        "ordinal": ordinal,
        "match_id": match_id,
        "quality": base["quality"]["status"],
        "public": str(public_path.relative_to(public_root)).replace("\\", "/"),
        "schema": str(schema_path.relative_to(private_root)).replace("\\", "/"),
    }


def describe(values: list[float]) -> dict[str, float]:
    if not values:
        return {"n": 0, "mean": 0, "median": 0, "sd": 0, "min": 0, "max": 0}
    return {
        "n": len(values),
        "mean": round(statistics.mean(values), 3),
        "median": round(statistics.median(values), 3),
        "sd": round(statistics.stdev(values), 3) if len(values) > 1 else 0,
        "min": round(min(values), 3),
        "max": round(max(values), 3),
    }


def build_schema_index(private_root: Path, completed: list[dict]) -> dict[str, Any]:
    observations: dict[str, list[dict]] = {}
    for item in completed:
        payload = json.loads((private_root / item["schema"]).read_text(encoding="utf-8"))
        for table in payload["tables"]:
            observations.setdefault(table["name"], []).append({
                "map": item["map"],
                "match_id": item["match_id"],
                "row_count": table["row_count"],
                "engine": table["engine"],
                "columns": table["columns"],
            })
    tables = []
    for name, rows in sorted(observations.items()):
        signatures: dict[str, dict] = {}
        for row in rows:
            signature = json.dumps(row["columns"], sort_keys=True)
            signatures.setdefault(signature, {
                "columns": row["columns"], "fixtures": 0, "maps": set()
            })
            signatures[signature]["fixtures"] += 1
            signatures[signature]["maps"].add(row["map"])
        tables.append({
            "name": name,
            "fixtures_present": len(rows),
            "fixtures_nonempty": sum(row["row_count"] > 0 for row in rows),
            "row_counts": describe([row["row_count"] for row in rows]),
            "schema_variants": [
                {
                    "fixtures": value["fixtures"],
                    "maps": sorted(value["maps"]),
                    "columns": value["columns"],
                }
                for value in signatures.values()
            ],
        })
    return {
        "schema_version": 1,
        "fixture_observations": len(completed),
        "table_count": len(tables),
        "tables": tables,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--public-output", type=Path, required=True)
    parser.add_argument("--private-output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--map", dest="maps", action="append",
                        help="analyze only this map (repeatable; intended for diagnostics)")
    parser.add_argument("--limit", type=int,
                        help="analyze at most this many selected fixtures")
    args = parser.parse_args()
    dataset_root = args.dataset_root.resolve()
    public_root = args.public_output.resolve()
    private_root = args.private_output.resolve()
    if public_root == private_root or public_root.is_relative_to(private_root) or private_root.is_relative_to(public_root):
        raise SystemExit("public and private output roots must be separate and non-nested")
    dataset = json.loads((dataset_root / "dataset.json").read_text(encoding="utf-8"))
    jobs = [
        (map_name, map_item, fixture)
        for map_name, map_item in dataset["maps"].items()
        if not args.maps or map_name in args.maps
        for fixture in map_item["fixtures"]
    ]
    if args.limit is not None:
        if args.limit < 1:
            raise SystemExit("--limit must be positive")
        jobs = jobs[:args.limit]
    public_root.mkdir(parents=True, exist_ok=True)
    private_root.mkdir(parents=True, exist_ok=True)
    completed: list[dict] = []
    failures: list[dict] = []

    if args.resume:
        index_path = private_root / "analysis-checkpoint.json"
        if index_path.is_file():
            checkpoint = json.loads(index_path.read_text(encoding="utf-8"))
            completed = checkpoint.get("completed", [])
            failures = []
    done = {(item["map"], int(item["ordinal"])) for item in completed}
    pending = [job for job in jobs if (job[0], int(job[2]["ordinal"])) not in done]
    print(f"competitive corpus: {len(completed)} resumed, {len(pending)} pending", flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        future_jobs = {
            pool.submit(
                process_fixture, dataset_root, public_root, private_root,
                dataset["dataset_id"], map_name, map_item, fixture,
            ): (map_name, fixture)
            for map_name, map_item, fixture in pending
        }
        for future in concurrent.futures.as_completed(future_jobs):
            map_name, fixture = future_jobs[future]
            try:
                result = future.result()
                completed.append(result)
                print(
                    f"[{len(completed)}/{len(jobs)}] {map_name} match-{int(fixture['ordinal']):02d}: {result['quality']}",
                    flush=True,
                )
            except Exception as exc:  # keep all independent fixtures running
                failure = {
                    "map": map_name,
                    "ordinal": fixture["ordinal"],
                    "match_id": fixture["match_id"],
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
                failures.append(failure)
                print(f"FAILED {map_name} match-{int(fixture['ordinal']):02d}: {exc}", flush=True)
            completed.sort(key=lambda item: (item["map"], int(item["ordinal"])))
            atomic_json(private_root / "analysis-checkpoint.json", {
                "dataset_id": dataset["dataset_id"],
                "completed": completed,
                "failures": failures,
            })

    schema_index = build_schema_index(private_root, completed)
    atomic_json(public_root / "schema-inventory.json", schema_index)
    index = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_id": dataset["dataset_id"],
        "privacy": "public aggregate and derived player totals only",
        "fixtures_expected": len(jobs),
        "fixtures_completed": len(completed),
        "fixtures_failed": len(failures),
        "quality_counts": {
            level: sum(item["quality"] == level for item in completed)
            for level in ("PASS", "WARN", "FAIL")
        },
        "matches": completed,
        "failures": [{key: value for key, value in item.items() if key != "traceback"} for item in failures],
    }
    assert_public_safe(index)
    atomic_json(public_root / "analysis-index.json", index)
    print(json.dumps({key: index[key] for key in ("fixtures_completed", "fixtures_failed", "quality_counts")}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
