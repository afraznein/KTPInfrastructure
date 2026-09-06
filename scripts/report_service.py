"""Scheduled match-report + season-aggregate job for the KTP data server.

Runs ON the data server (local-socket mysql, no SSH hop), from the repo root:
  python3 -m scripts.report_service --repo . generate
  python3 -m scripts.report_service --repo . aggregate

`generate` discovers matches that have flag-state producer rows and no
persisted report at the current schema version, runs
scripts/match_analytics.py::build_report(), and appends one row per report to
ktp_match_reports (migration 026). Append-only: regeneration writes the next
revision, never mutates.

`aggregate` reads the latest publishable report per match from the table,
recomputes season aggregates (map profiles, name-keyed head-to-head, and the
PROVISIONAL KTPR v2.2 leaderboard — P2 ships per the 2026-09-06 decision),
and appends a new ktp_web_season_aggregates revision only when the payload
hash changed.

Production drifts absorbed (ported from the reference runner in
artifacts/real-match-tier2-20260906/run_production_report.py):
  - ktp_flag_captures.team holds 'Allies'/'Axis' strings (fixtures use 1/2).
  - UTF-8 player names end to end (mysql --batch --raw + utf8mb4, hex-literal
    INSERTs so no shell/SQL quoting ever touches a name).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from scripts.ktpr_season import build_ktpr_v22
from scripts.analytics_report_dto import PROVISIONAL_NOTICE, _name

DATABASE = "hlstatsx"
# Hard-check gate: FAIL on this code is cosmetic/expected for legacy '1.3-'
# match ids (see WEBSITE_SHADOW_STATS_PROMOTION_HANDOVER_20260906.md §4).
COSMETIC_FAIL_CODES = {"match_id_shape"}


class LocalMysql:
    """Duck-types EphemeralMysql.sql() over the local mysql CLI (auth_socket)."""

    def __init__(self, database: str = DATABASE) -> None:
        self.database = database
        self.calls = 0

    def sql(self, query: str) -> str:
        self.calls += 1
        proc = subprocess.run(
            ["mysql", "--batch", "--raw", "--default-character-set=utf8mb4",
             self.database],
            input=query, capture_output=True, text=True, timeout=600,
            encoding="utf-8", errors="replace",
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"mysql failed rc={proc.returncode}: {proc.stderr[-800:]}")
        return proc.stdout


def sql_str(value: str) -> str:
    """Hex-literal so names/JSON never pass through SQL quoting."""
    return f"CONVERT(UNHEX('{value.encode('utf-8').hex()}') USING utf8mb4)"


def is_publishable(report: dict) -> bool:
    checks = (report.get("quality") or {}).get("checks") or []
    return all(
        c.get("level") != "FAIL" or c.get("code") in COSMETIC_FAIL_CODES
        for c in checks
    )


def load_match_analytics(repo: Path):
    sys.path.insert(0, str(repo))
    sys.path.insert(0, str(repo / "scripts"))
    from scripts import match_analytics as ma

    # Production drift: team as 'Allies'/'Axis' strings.
    orig_value = ma._value
    team_names = {"Allies": 1, "Axis": 2}

    def tolerant_value(name, raw):
        try:
            return orig_value(name, raw)
        except ValueError:
            return team_names.get(raw, raw)

    ma._value = tolerant_value
    return ma


def pending_match_ids(db: LocalMysql, schema_version: int) -> list[str]:
    # Flag-state producer rows are the corpus criterion; verify the join
    # column names on the server before first run.
    out = db.sql(
        "SELECT DISTINCT m.match_id FROM ktp_matches m "
        "JOIN ktp_flag_state_events f ON BINARY f.match_id = BINARY m.match_id "
        "LEFT JOIN ktp_match_reports r ON BINARY r.match_id = BINARY m.match_id "
        f"AND r.schema_version = {schema_version} "
        "WHERE m.match_id IS NOT NULL AND r.id IS NULL "
        "ORDER BY m.match_id"
    )
    lines = out.strip().splitlines()
    return [ln for ln in lines[1:] if ln] if lines else []


def next_revision(db: LocalMysql, match_id: str, schema_version: int) -> int:
    out = db.sql(
        "SELECT COALESCE(MAX(revision),0) FROM ktp_match_reports "
        f"WHERE match_id = {sql_str(match_id)} "
        f"AND schema_version = {schema_version}"
    )
    return int(out.strip().splitlines()[-1]) + 1


def persist_report(db: LocalMysql, report: dict) -> None:
    body = json.dumps(report, ensure_ascii=False, default=str)
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    match_id = report["match_id"]
    schema_version = int(report["schema_version"])
    revision = next_revision(db, match_id, schema_version)
    quality = (report.get("quality") or {}).get("status") or "UNKNOWN"
    db.sql(
        "INSERT INTO ktp_match_reports (match_id, schema_version, revision, "
        "generated_at, quality_status, publishable, report_sha256, report) "
        f"VALUES ({sql_str(match_id)}, {schema_version}, {revision}, "
        f"{sql_str(str(report['generated_at']))}, {sql_str(quality)}, "
        f"{1 if is_publishable(report) else 0}, {sql_str(sha)}, "
        f"{sql_str(body)})"
    )


ACCUMULATION_PROFILE = "accumulation_v5_momentum"


def load_accumulation_scorer(repo: Path):
    """The accumulation scorer (build_facts + score_match) ships from the
    scoring lane; until it lands on main this returns None and reports carry
    ratings.accumulation.status = unavailable."""
    try:
        from scripts.accumulation_v3 import load_profile, score_match
        from scripts.lane_b_match_report import build_facts
    except ImportError:
        return None
    profile_path = repo / "config" / "analytics" / f"{ACCUMULATION_PROFILE}.toml"
    if not profile_path.exists():
        return None

    def score(db, match_id: str) -> dict:
        facts, _private = build_facts(db, match_id, profile_path=profile_path)
        scored = score_match(facts, load_profile(profile_path))
        keep = ("schema_version", "generated_at", "status",
                "publication_state", "profile", "profile_status",
                "impact_index", "quality_gates", "players")
        return {k: scored.get(k) for k in keep} | {
            "profile_sha256": hashlib.sha256(
                profile_path.read_bytes()).hexdigest()}

    return score


def cmd_generate(args: argparse.Namespace) -> int:
    ma = load_match_analytics(args.repo)
    db = LocalMysql()
    schema_version = int(getattr(ma, "REPORT_SCHEMA_VERSION", 7))
    sources = ma.source_capabilities(db)
    scorer = load_accumulation_scorer(args.repo)
    print(f"accumulation scorer: {'available' if scorer else 'unavailable'}")
    ids = args.match_ids or pending_match_ids(db, schema_version)
    print(f"pending: {len(ids)} matches (schema v{schema_version})")
    failures = 0
    for match_id in ids:
        try:
            report = ma.build_report(db, match_id, Path("production"),
                                     sources=sources)
            if scorer:
                try:
                    report["accumulation"] = scorer(db, match_id)
                except Exception as exc:  # scoring is best-effort per match
                    print(f"  {match_id}: accumulation FAILED "
                          f"{type(exc).__name__}: {exc}")
            persist_report(db, report)
            print(f"  {match_id}: persisted, publishable={is_publishable(report)}")
        except Exception as exc:
            failures += 1
            print(f"  {match_id}: FAILED {type(exc).__name__}: {exc}")
    print(f"mysql calls: {db.calls}; failures: {failures}")
    return 1 if failures else 0


def latest_publishable_reports(db: LocalMysql) -> list[dict]:
    out = db.sql(
        "SELECT r.report FROM ktp_match_reports r "
        "JOIN (SELECT match_id, MAX(id) AS id FROM ktp_match_reports "
        "      WHERE publishable = 1 GROUP BY match_id) latest "
        "ON latest.id = r.id"
    )
    lines = out.splitlines()
    return [json.loads(ln) for ln in lines[1:] if ln.strip()]


def build_aggregates(reports: list[dict]) -> dict[str, dict]:
    per_map = defaultdict(lambda: {"matches": 0, "kills": 0, "trades": 0,
                                   "multikills": 0, "trade_rates": [],
                                   "recap_medians": []})
    duels = defaultdict(lambda: {"a_over_b": 0, "b_over_a": 0, "matches": 0})
    names: dict[int, str] = {}
    schema_versions = set()
    for r in reports:
        schema_versions.add(int(r["schema_version"]))
        mapname = (r.get("match") or {}).get("map_name") or "?"
        st = r["shadow_timelines"]
        se = r["shadow_explorations"]
        pm = per_map[mapname]
        pm["matches"] += 1
        pm["kills"] += sum(p.get("kills") or 0 for p in r.get("players") or [])
        pm["trades"] += len(st.get("trades") or [])
        pm["multikills"] += len(st.get("fast_multikills") or [])
        for t in st["trade_analysis"].get("teams", []):
            pm["trade_rates"].append(t["team_death_response_rate"])
        meds = [t["median_seconds"] for t in se["recap_speed"].get("teams", [])
                if t.get("median_seconds") is not None]
        if meds:
            pm["recap_medians"].append(statistics.median(meds))
        seen_pairs = set()
        for c in r["duel_matrix"].get("cells", []):
            if not c.get("cross_team"):
                continue
            a, b = sorted((c["killer_id"], c["victim_id"]))
            names[c["killer_id"]] = _name(c.get("killer_name"))
            names[c["victim_id"]] = _name(c.get("victim_name"))
            d = duels[(a, b)]
            d["a_over_b" if c["killer_id"] == a else "b_over_a"] += c["kills"]
            if (a, b) not in seen_pairs:
                d["matches"] += 1
                seen_pairs.add((a, b))

    out: dict[str, dict] = {}
    out["map_profiles"] = {"maps": [
        {"map": m, "matches": pm["matches"],
         "kills_per_match": round(pm["kills"] / pm["matches"], 1),
         "trades_per_match": round(pm["trades"] / pm["matches"], 1),
         "fast_multikills_per_match": round(pm["multikills"] / pm["matches"], 1),
         "trade_response_rate_mean": round(statistics.mean(pm["trade_rates"]), 4)
         if pm["trade_rates"] else None,
         "recap_median_seconds": round(statistics.median(pm["recap_medians"]), 1)
         if pm["recap_medians"] else None}
        for m, pm in sorted(per_map.items(), key=lambda kv: -kv[1]["matches"])]}
    out["head_to_head"] = {"pairs": [
        {"player_a": names.get(a), "player_b": names.get(b),
         "kills_a_over_b": d["a_over_b"], "kills_b_over_a": d["b_over_a"],
         "total_kills": d["a_over_b"] + d["b_over_a"], "matches": d["matches"]}
        for (a, b), d in sorted(duels.items(),
                                key=lambda kv: -(kv[1]["a_over_b"]
                                                 + kv[1]["b_over_a"]))
        if d["a_over_b"] + d["b_over_a"] >= 40]}

    ktpr = build_ktpr_v22(reports)
    out["leaderboard_ktpr_v22"] = {
        "provisional": True,
        "notice": PROVISIONAL_NOTICE,
        "method_version": ktpr["method_version"],
        "definition_versions": ktpr["definition_versions"],
        "beta": ktpr["beta"],
        "shrinkage_k": ktpr["shrinkage_k"],
        "within_var": ktpr["within_var"],
        "min_matches": ktpr["min_matches"],
        # database ids stay server-side; the website gets names only
        "players": [
            {"name": _name(p["name"]), "matches": p["matches"],
             "rating": p["rating"], "sos_rating": p["sos_rating"],
             "se": p["se"]}
            for p in ktpr["players"] if p["matches"] >= ktpr["min_matches"]
        ],
    }
    for payload in out.values():
        payload["source_report_count"] = len(reports)
        payload["report_schema_version"] = max(schema_versions)
    return out


def cmd_aggregate(args: argparse.Namespace) -> int:
    db = LocalMysql()
    reports = latest_publishable_reports(db)
    if not reports:
        print("no publishable reports; nothing to aggregate")
        return 0
    from datetime import datetime, timezone
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    for kind, payload in build_aggregates(reports).items():
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
        out = db.sql(
            "SELECT payload_sha256, COALESCE(MAX(revision),0) "
            f"FROM ktp_web_season_aggregates WHERE kind = {sql_str(kind)} "
            "GROUP BY payload_sha256 ORDER BY MAX(id) DESC LIMIT 1"
        )
        lines = out.strip().splitlines()
        last_sha, last_rev = (lines[-1].split("\t") if len(lines) > 1
                              else ("", "0"))
        if last_sha == sha:
            print(f"  {kind}: unchanged (revision {last_rev})")
            continue
        db.sql(
            "INSERT INTO ktp_web_season_aggregates (kind, revision, "
            "generated_at, source_report_count, report_schema_version, "
            "payload_sha256, payload) "
            f"VALUES ({sql_str(kind)}, {int(last_rev) + 1}, "
            f"{sql_str(generated_at)}, {payload['source_report_count']}, "
            f"{payload['report_schema_version']}, {sql_str(sha)}, "
            f"{sql_str(body)})"
        )
        print(f"  {kind}: wrote revision {int(last_rev) + 1} "
              f"({payload['source_report_count']} reports)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, required=True,
                    help="KTPInfrastructure checkout on this server")
    sub = ap.add_subparsers(dest="cmd", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("match_ids", nargs="*",
                     help="explicit match ids; default: discover pending")
    sub.add_parser("aggregate")
    args = ap.parse_args()
    return cmd_generate(args) if args.cmd == "generate" else cmd_aggregate(args)


if __name__ == "__main__":
    raise SystemExit(main())
