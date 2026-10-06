"""Scheduled match-report + season-aggregate job for the KTP data server.

Runs ON the data server (local-socket mysql, no SSH hop), from the repo root:
  python3 -m scripts.report_service --repo . generate
  python3 -m scripts.report_service --repo . aggregate --since 2026-09-13

`generate` discovers finished matches that have flag-state producer rows and
no report at the current schema version written after their last half closed,
runs scripts/match_analytics.py::build_report(), and appends one row per
report to ktp_match_reports (migration 026). Append-only: regeneration writes
the next revision, never mutates.

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
import copy
import hashlib
import json
import os
import pwd
import re
import math
from datetime import datetime
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from scripts.ktpr_season import build_ktpr_v22
from scripts.analytics_report_dto import (KTPR_DISPLAY_SCALE, PROVISIONAL_NOTICE,
                                          _name, ktpr_display)
from scripts.in_game_result import DEFAULT_OBSERVER_ROOT
from scripts.report_scope import (
    DISCOVERED_MATCH_TYPES, IN_SCOPE, OFFICIAL_MATCH_TYPES, SHADOW_MATCH_TYPES,
    classify, match_scope_columns, print_held)

DATABASE = "hlstatsx"
# Hard-check gate: a FAIL on this code never withholds a match. The shape
# check recognises every id KTPMatchHandler writes, so a FAIL here means an
# unrecognised id -- worth reporting, not worth dropping the match over.
COSMETIC_FAIL_CODES = {"match_id_shape"}


def _os_user() -> str:
    """The OS identity auth_socket is checked against.

    The client does not reliably default to it. Under `sudo -u ktpreports` the
    process really is uid ktpreports and $USER/$LOGNAME are already ktpreports,
    yet mysql still sends `root` and the server refuses with 1698 -- measured,
    including with --no-defaults and with the environment unset. Only an
    explicit --user works, so send one: the call then behaves identically under
    systemd, under sudo, and interactively.
    """
    return pwd.getpwuid(os.geteuid()).pw_name


class LocalMysql:
    """Duck-types EphemeralMysql.sql() over the local mysql CLI (auth_socket)."""

    def __init__(self, database: str = DATABASE) -> None:
        self.database = database
        self.calls = 0

    def sql(self, query: str) -> str:
        self.calls += 1
        proc = subprocess.run(
            ["mysql", "--batch", "--raw", "--default-character-set=utf8mb4",
             f"--user={_os_user()}", self.database],
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


# OFFICIAL_MATCH_TYPES and DISCOVERED_MATCH_TYPES live in scripts/report_scope.py,
# shared with aggregate and report_sync.

# ktp_matches.match_type, per that column's own COMMENT on the server.
MATCH_TYPE_LABELS = {
    "0": "competitive/.ktp", "1": "scrim", "2": "12man",
    "3": "draft", "4": "KTP OT/.ktpOT", "5": "draft OT", "NULL": "unset",
}


# Outlasts a half break or a tech pause between halves, so a match waiting on
# its next half is never mistaken for a finished one.
SETTLE_MINUTES = 20


def _pending_corpus_sql(schema_version: int, since: str | None,
                        select: str, tail: str,
                        as_of: str | None = None) -> str:
    """Matches ready for a report, as of `as_of` (server-local) or NOW()."""
    if since is not None and not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}:\d{2})?", since):
        raise ValueError(f"--since must be 'YYYY-MM-DD' or "
                         f"'YYYY-MM-DD HH:MM:SS', got {since!r}")
    if as_of is not None and not re.fullmatch(
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", as_of):
        raise ValueError(f"as_of must be 'YYYY-MM-DD HH:MM:SS', got {as_of!r}")
    since_clause = f"AND m.start_time >= '{since}' " if since else ""
    now = f"CAST('{as_of}' AS DATETIME)" if as_of else "NOW()"
    return (
        f"SELECT {select} FROM ktp_matches m "
        # ktp_matches has a row per half, so gate on the whole match: a closed
        # first half with the second not yet started looks exactly like the end.
        "JOIN (SELECT match_id, MAX(end_time) AS last_end FROM ktp_matches "
        "GROUP BY match_id HAVING SUM(end_time IS NULL) = 0 "
        f"AND MAX(end_time) <= {now} - INTERVAL {SETTLE_MINUTES} MINUTE) done "
        "ON done.match_id = m.match_id "
        "WHERE m.match_id IS NOT NULL "
        "AND EXISTS (SELECT 1 FROM ktp_flag_state_events f "
        "WHERE BINARY f.match_id = BINARY m.match_id) "
        # A report older than the last half's close is partial and gets a new
        # revision. persist_report writes generated_at in the session zone,
        # which is the zone the daemon's NOW() writes end_time in.
        "AND NOT EXISTS (SELECT 1 FROM ktp_match_reports r "
        "WHERE BINARY r.match_id = BINARY m.match_id "
        f"AND r.schema_version = {schema_version} "
        "AND r.generated_at > done.last_end) "
        f"{since_clause}{tail}"
    )


def pending_match_ids(db: LocalMysql, schema_version: int,
                      since: str | None = None) -> list[str]:
    # Flag-state producer rows are the corpus criterion; verify the join
    # column names on the server before first run.
    # `since` (e.g. "2026-09-13") is a coarse date floor on start_time, NOT
    # the official/scrim discriminator: match_type is, and it carries the
    # operator's 2026-09-08 .ktp-only ruling.
    # A NULL match_type is dropped, deliberately — IN excludes NULL, an
    # untyped match is not a provably official one, and failing closed
    # publishes nothing rather than publishing pracc traffic as league data.
    # cmd_generate prints what the filter dropped, so the drop is never silent.
    # DISCOVERED, not OFFICIAL: a shadow type is built here and held back at
    # publication by classify(), so widening discovery cannot widen the site.
    types = ", ".join(str(t) for t in DISCOVERED_MATCH_TYPES)
    out = db.sql(_pending_corpus_sql(
        schema_version, since, "DISTINCT m.match_id",
        f"AND m.match_type IN ({types}) ORDER BY m.match_id"))
    lines = out.strip().splitlines()
    return [ln for ln in lines[1:] if ln] if lines else []


def excluded_by_match_type(db: LocalMysql, schema_version: int,
                           since: str | None = None) -> dict[str, int]:
    """What the discovery filter drops, keyed by match_type label.

    Reported, never acted on. A filter whose effect nobody can see is how a
    wrong type set silently omits real matches instead of failing loudly.
    """
    types = ", ".join(str(t) for t in DISCOVERED_MATCH_TYPES)
    out = db.sql(_pending_corpus_sql(
        schema_version, since,
        "COALESCE(CAST(m.match_type AS CHAR), 'NULL') AS mt, "
        "COUNT(DISTINCT m.match_id) AS n",
        f"AND (m.match_type IS NULL OR m.match_type NOT IN ({types})) "
        "GROUP BY mt ORDER BY mt"))
    dropped: dict[str, int] = {}
    for line in out.strip().splitlines()[1:]:
        if not line.strip():
            continue
        mt, n = line.split("\t")
        dropped[MATCH_TYPE_LABELS.get(mt, f"match_type={mt}")] = int(n)
    return dropped


def next_revision(db: LocalMysql, match_id: str, schema_version: int) -> int:
    out = db.sql(
        "SELECT COALESCE(MAX(revision),0) FROM ktp_match_reports "
        f"WHERE match_id = {sql_str(match_id)} "
        f"AND schema_version = {schema_version}"
    )
    return int(out.strip().splitlines()[-1]) + 1


def session_zone_datetime(iso: str) -> str:
    """SQL for `iso` as a whole-second DATETIME in the session zone, like NOW().

    Never the ISO string itself: MySQL 8.0 converts an offset literal to the
    session zone only when its fraction rounds down, and stores a fraction that
    rounds up as the UTC wall clock, hours in the future.
    """
    moment = datetime.fromisoformat(iso)
    if moment.tzinfo is None:
        raise ValueError(f"generated_at has no UTC offset: {iso!r}")
    return f"FROM_UNIXTIME({math.floor(moment.timestamp())})"


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
        f"{session_zone_datetime(str(report['generated_at']))}, {sql_str(quality)}, "
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
    # No fallback on purpose: REPORT_SCHEMA_VERSION never existed, so the old
    # getattr default silently pinned the pending filter at 7 while writes
    # stamped 8, and every match regenerated on every run.
    schema_version = int(ma.SCHEMA_VERSION)
    dry_run = getattr(args, "dry_run", False)
    if not dry_run:
        sources = ma.source_capabilities(db)
        scorer = load_accumulation_scorer(args.repo)
        print(f"accumulation scorer: {'available' if scorer else 'unavailable'}")
    ids = args.match_ids or pending_match_ids(db, schema_version, args.since)
    print(f"pending: {len(ids)} matches (schema v{schema_version})")
    # Say it every run: the corpus is deliberately wider than what publishes,
    # so a reader of this log never has to infer whether a 12-man report is a
    # leak or the point.
    print(f"match types built: {', '.join(str(t) for t in OFFICIAL_MATCH_TYPES)}"
          f" official + {', '.join(str(t) for t in SHADOW_MATCH_TYPES)} shadow "
          "(built for analytics, held back by aggregate and report_sync)")
    if args.match_ids:
        for warning in explicit_scope_warnings(db, args.match_ids):
            print(f"WARNING: {warning}: persisted anyway, but aggregate and "
                  "report_sync hold its report back")
    else:
        dropped = excluded_by_match_type(db, schema_version, args.since)
        detail = ", ".join(f"{k} {v}" for k, v in sorted(dropped.items()))
        print(f"excluded by match_type filter: {sum(dropped.values())}"
              f"{f' ({detail})' if detail else ''}")
    if dry_run:
        print(f"dry run: would build {len(ids)} reports; nothing persisted")
        return 0
    failures = 0
    for match_id in ids:
        try:
            report = ma.build_report(db, match_id, Path("production"),
                                     sources=sources,
                                     observer_root=args.observer_root)
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


def since_arg(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}:\d{2})?", value):
        raise argparse.ArgumentTypeError(
            f"must be 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS', got {value!r}")
    return value


def latest_publishable_reports(db: LocalMysql, since: str) -> list[dict]:
    """Latest publishable report per in-season match: one with an official-type
    half that started on or after `since`. Without this, a report written outside
    generate's discovery (an explicit match id, a manual test) is pooled into the
    season aggregates."""
    out = db.sql(
        f"SELECT {match_scope_columns('r')}, r.report "
        "FROM ktp_match_reports r "
        "JOIN (SELECT match_id, MAX(id) AS id FROM ktp_match_reports "
        "      WHERE publishable = 1 GROUP BY match_id) latest "
        "ON latest.id = r.id"
    )
    kept, held = [], {}
    for ln in out.splitlines()[1:]:
        if not ln.strip():
            continue
        start, official, body = ln.split("\t", 2)
        verdict = classify(start, official, since)
        if verdict == IN_SCOPE:
            kept.append(json.loads(body))
        else:
            held[verdict] = held.get(verdict, 0) + 1
    print_held(held, since)
    return kept


def explicit_scope_warnings(db: LocalMysql, match_ids: list[str]) -> list[str]:
    """Explicit ids that aggregate and report_sync will hold back whatever the
    date: no ktp_matches row, or no official-type half. generate still persists
    them, because an explicit id is how the pipeline is tested."""
    ids = " UNION ALL ".join(f"SELECT {sql_str(m)} AS match_id"
                             for m in match_ids)
    out = db.sql(
        f"SELECT x.match_id, {match_scope_columns('x')} FROM ({ids}) x")
    warnings = []
    for ln in out.splitlines()[1:]:
        if not ln.strip():
            continue
        match_id, start, official = ln.split("\t")
        if start in ("", "NULL"):
            warnings.append(f"{match_id} has no ktp_matches row")
        elif official in ("", "NULL"):
            warnings.append(f"{match_id} is not an official match type")
    return warnings


MIN_LOCATED_DEATHS = 30      # overextension table row threshold (prototype)
MIN_PROFILE_SAMPLES = 200    # per (map, player) depth profile threshold


def build_season_positional(reports: list[dict]) -> dict:
    """Pool the per-match positional shadow blocks: overextension table
    (rates over pooled located frags), depth profiles per (map, player)
    (exact pooled mean/sd from the per-match sums), and per-map mean control.
    Names only; database ids stay server-side."""
    over: dict[int, dict] = defaultdict(lambda: {
        "name": None, "kills_located": 0, "kills_ahead": 0,
        "deaths_located": 0, "deaths_ahead": 0, "matches": 0})
    prof: dict[tuple[str, int], dict] = defaultdict(lambda: {
        "name": None, "n": 0, "sum": 0.0, "sum_sq": 0.0, "lat_sum": 0.0,
        "matches": 0})
    control: dict[str, list[float]] = defaultdict(list)
    versions = set()
    matches_with_positions = 0
    for r in reports:
        se = r.get("shadow_explorations") or {}
        mc, dp, ov = (se.get("map_control") or {}, se.get("depth_profiles") or {},
                      se.get("overextension") or {})
        mapname = (r.get("match") or {}).get("map_name") or "?"
        if mc.get("status") == "available" and mc.get("mean_control_team1") is not None:
            control[mapname].append(mc["mean_control_team1"])
            matches_with_positions += 1
            versions.add(mc.get("definition_version"))
        if dp.get("status") == "available":
            for p in dp.get("players") or []:
                row = prof[(mapname, p["player_id"])]
                row["name"] = _name(p.get("player_name_at_match")) or row["name"]
                row["n"] += p["samples"]
                row["sum"] += p.get("depth_sum", p["mean_depth"] * p["samples"])
                row["sum_sq"] += p.get("depth_sum_sq",
                                       (p["depth_sd"] ** 2 + p["mean_depth"] ** 2) * p["samples"])
                row["lat_sum"] += p.get("lateral_sum", p["lateral_mean"] * p["samples"])
                row["matches"] += 1
        if ov.get("status") == "available":
            for p in ov.get("players") or []:
                row = over[p["player_id"]]
                row["name"] = _name(p.get("player_name_at_match")) or row["name"]
                for k in ("kills_located", "kills_ahead", "deaths_located", "deaths_ahead"):
                    row[k] += p.get(k) or 0
                row["matches"] += 1

    table = []
    for row in over.values():
        if row["deaths_located"] < MIN_LOCATED_DEATHS:
            continue
        ka = (row["kills_ahead"] / row["kills_located"]) if row["kills_located"] else None
        da = row["deaths_ahead"] / row["deaths_located"]
        table.append({
            "name": row["name"], "matches": row["matches"],
            "kills_located": row["kills_located"], "deaths_located": row["deaths_located"],
            "kill_ahead_rate": round(ka, 3) if ka is not None else None,
            "death_ahead_rate": round(da, 3),
            "net_ahead": round(ka - da, 3) if ka is not None else None,
        })
    table.sort(key=lambda x: -(x["net_ahead"] if x["net_ahead"] is not None else -9))

    profiles = []
    for (mapname, _pid), row in prof.items():
        if row["n"] < MIN_PROFILE_SAMPLES:
            continue
        mean = row["sum"] / row["n"]
        var = max(row["sum_sq"] / row["n"] - mean * mean, 0.0)
        profiles.append({"map": mapname, "name": row["name"], "matches": row["matches"],
                         "samples": row["n"], "mean_depth": round(mean, 4),
                         "depth_sd": round(var ** 0.5, 4),
                         "lateral_mean": round(row["lat_sum"] / row["n"], 1)})
    profiles.sort(key=lambda x: (x["map"], -x["mean_depth"]))

    return {
        "provisional": True,
        "notice": PROVISIONAL_NOTICE,
        "definition_versions": sorted(v for v in versions if v is not None),
        "matches_with_positions": matches_with_positions,
        "min_located_deaths": MIN_LOCATED_DEATHS,
        "min_profile_samples": MIN_PROFILE_SAMPLES,
        "overextension": table,
        "depth_profiles": profiles,
        "map_control": [
            {"map": m, "matches": len(v), "mean_control_team1": round(statistics.mean(v), 4)}
            for m, v in sorted(control.items(), key=lambda kv: -len(kv[1]))],
    }


CORPUS_CELL_MINIMUM_SECONDS = 60.0   # season-level occupancy floor (atlas config)


def build_season_spatial(reports: list[dict]) -> dict:
    """Pool per-match spatial_layers per map: cells and lanes are additive
    counts, so the season layer is a sum re-thresholded at the corpus floor.
    Per-match contributor floors already applied before emission; pooling
    only adds evidence. Unattributed throughout — no ids ever enter."""
    per_map: dict[str, dict] = defaultdict(lambda: {
        "matches": 0, "occ": defaultdict(lambda: [0, 0]), "kills": defaultdict(int),
        "deaths": defaultdict(int), "lanes": defaultdict(lambda: [0, 0.0, 0.0, None]),
        "flags": {}, "sample_seconds": 2.0, "grid": 128.0})
    versions = set()
    for r in reports:
        sp = r.get("spatial_layers") or {}
        if sp.get("status") != "available":
            continue
        m = per_map[(r.get("match") or {}).get("map_name") or "?"]
        m["matches"] += 1
        versions.add(sp.get("definition_version"))
        params = sp.get("parameters") or {}
        m["sample_seconds"] = float(params.get("sample_seconds") or m["sample_seconds"])
        m["grid"] = float(params.get("grid_size") or m["grid"])
        layers = sp.get("layers") or {}
        for c in (layers.get("occupancy") or {}).get("cells") or []:
            t = m["occ"][(c["col"], c["row"])]
            t[0] += c["team1_samples"]
            t[1] += c["team2_samples"]
        for c in (layers.get("kill_hotspots") or {}).get("cells") or []:
            m["kills"][(c["col"], c["row"])] += c["kills"]
        for c in (layers.get("death_hotspots") or {}).get("cells") or []:
            m["deaths"][(c["col"], c["row"])] += c["deaths"]
        for v in (layers.get("recurring_lanes") or {}).get("vectors") or []:
            key = (v["origin"]["col"], v["origin"]["row"],
                   v["destination"]["col"], v["destination"]["row"])
            lane = m["lanes"][key]
            lane[0] += v["count"]
            lane[1] += v["count"] * v["mean_distance"]
            lane[2] += v["count"] * v["headshot_rate"]
            lane[3] = lane[3] or (v["origin"], v["destination"])  # lane-grid centers, world units
        for f in sp.get("flags") or []:
            m["flags"].setdefault(f["flag_index"], f)

    maps = []
    for mapname, m in sorted(per_map.items(), key=lambda kv: -kv[1]["matches"]):
        floor = math.ceil(CORPUS_CELL_MINIMUM_SECONDS / m["sample_seconds"])
        occupancy = [
            {"col": c, "row": r, "samples": t[0] + t[1],
             "seconds": round((t[0] + t[1]) * m["sample_seconds"], 1),
             "team1_samples": t[0], "team2_samples": t[1],
             "control": round((t[0] - t[1]) / (t[0] + t[1]), 4)}
            for (c, r), t in sorted(m["occ"].items()) if t[0] + t[1] >= floor]
        kills = [{"col": c, "row": r, "kills": n} for (c, r), n in sorted(m["kills"].items())]
        deaths = [{"col": c, "row": r, "deaths": n} for (c, r), n in sorted(m["deaths"].items())]
        grid = m["grid"]
        lanes = sorted((
            {"origin": dict(ends[0]), "destination": dict(ends[1]),
             "count": n, "mean_distance": round(dist / n, 1), "headshot_rate": round(hs / n, 3)}
            for (n, dist, hs, ends) in m["lanes"].values()),
            key=lambda v: -v["count"])
        flags = sorted(m["flags"].values(), key=lambda f: f["flag_index"])
        # Lanes live on the coarser lane grid; bound the fine lattice by their
        # endpoint coordinates rather than their coarse cell indices.
        keys = ({(c["col"], c["row"]) for c in occupancy + kills + deaths}
                | {(f["col"], f["row"]) for f in flags}
                | {(math.floor(v[e]["x"] / grid), math.floor(v[e]["y"] / grid))
                   for v in lanes for e in ("origin", "destination")})
        lattice = None
        if keys:
            cmin, rmin = min(c for c, _ in keys), min(r for _, r in keys)
            lattice = {"scheme": "world_grid_v2", "grid_size": grid,
                       "column_index_min": cmin, "row_index_min": rmin,
                       "columns": max(c for c, _ in keys) - cmin + 1,
                       "rows": max(r for _, r in keys) - rmin + 1}
        maps.append({"map": mapname, "matches": m["matches"], "lattice": lattice,
                     "flags": flags, "occupancy": occupancy, "kill_hotspots": kills,
                     "death_hotspots": deaths, "recurring_lanes": lanes})
    return {
        "provisional": True,
        "notice": PROVISIONAL_NOTICE,
        "definition_versions": sorted(v for v in versions if v is not None),
        "corpus_cell_minimum_seconds": CORPUS_CELL_MINIMUM_SECONDS,
        "maps": maps,
    }


def build_aggregates(reports: list[dict]) -> dict[str, dict]:
    per_map = defaultdict(lambda: {"matches": 0, "kills": 0, "trades": 0,
                                   "multikills": 0, "trade_rates": [],
                                   "recap_medians": [], "duration_seconds": 0,
                                   "points": 0})
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
        pm["points"] += sum(p.get("score") or 0 for p in r.get("players") or [])
        pm["duration_seconds"] += (r.get("match") or {}).get("duration_seconds") or 0
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
         "kills_per_minute": round(pm["kills"] * 60.0 / pm["duration_seconds"], 3)
         if pm["duration_seconds"] else None,
         "points_per_minute": round(pm["points"] * 60.0 / pm["duration_seconds"], 3)
         if pm["duration_seconds"] else None,
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

    out["season_positional"] = build_season_positional(reports)
    out["season_spatial"] = build_season_spatial(reports)

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
        # rating and sos_rating below are already on the display scale; se is
        # not (it stays in z units, since it is a spread, not a position).
        "display_scale": {"rating": copy.deepcopy(KTPR_DISPLAY_SCALE["rating"]),
                          "sos_rating": copy.deepcopy(KTPR_DISPLAY_SCALE["rating"]),
                          "se": {"kind": "raw_z_score",
                                 "note": "Standard error in z units, not rescaled."}},
        # database ids stay server-side; the website gets names only
        "players": [
            {"name": _name(p["name"]), "matches": p["matches"],
             "rating": ktpr_display(p["rating"]),
             "sos_rating": ktpr_display(p["sos_rating"]),
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
    reports = latest_publishable_reports(db, args.since)
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


def cmd_import_mmr(args: argparse.Namespace) -> int:
    """Insert a prebuilt mmr_openskill payload as a season-aggregate revision.

    The MMR ladder runs in CI, which holds only the website's public read key
    -- it cannot write here, and should not: giving a hosted runner a
    production write credential to publish a weekly number is a much larger
    step than the feature warrants. So CI produces the payload file
    (scripts/mmr/mmr_openskill_payload.json, published on the `mmr-ratings`
    branch) and this inserts it, on the box that already owns the credential.

    Deliberately dumb: it does not recompute ratings, it does not reach the
    network, and it refuses anything that is not already the right shape.
    Same revision/sha convention as cmd_aggregate, so an unchanged payload is
    a no-op rather than a new revision every week.

    That the ladder never runs here is a property of what this imports, not a
    promise in prose: both modules below are stdlib-only, and
    test_import_mmr_needs_no_solver imports whatever this function imports with
    the solver blocked.
    """
    sys.path.insert(0, str(Path(args.repo) / "scripts" / "mmr"))
    # The schema module, not methodology itself -- that one builds the document
    # out of the ladder's own constants and so imports the OpenSkill solver,
    # which this box has never had and needs none of to insert a finished file.
    import methodology_schema as METH
    import mmr_payload as MMRP

    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    # Two documents travel this path: the ratings (player rows, aliases only)
    # and the methodology (no rows at all). Each has its own guard.
    validators = {MMRP.AGGREGATE_KIND: MMRP.validate_for_import,
                  METH.AGGREGATE_KIND: METH.validate_for_import}
    kind = payload.get("kind") if isinstance(payload, dict) else None
    validate = validators.get(kind)
    problems = validate(payload) if validate else [f"kind is {kind!r}, expected one of {sorted(validators)}"]
    if problems:
        for problem in problems:
            print(f"refusing: {problem}")
        return 1
    players = payload.get("players", [])

    db = LocalMysql()
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    out = db.sql(
        "SELECT payload_sha256, COALESCE(MAX(revision),0) "
        f"FROM ktp_web_season_aggregates WHERE kind = {sql_str(kind)} "
        "GROUP BY payload_sha256 ORDER BY MAX(id) DESC LIMIT 1"
    )
    lines = out.strip().splitlines()
    last_sha, last_rev = (lines[-1].split("	") if len(lines) > 1 else ("", "0"))
    if last_sha == sha:
        print(f"  {kind}: unchanged (revision {last_rev})")
        return 0
    from datetime import datetime, timezone
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    db.sql(
        "INSERT INTO ktp_web_season_aggregates (kind, revision, "
        "generated_at, source_report_count, report_schema_version, "
        "payload_sha256, payload) "
        f"VALUES ({sql_str(kind)}, {int(last_rev) + 1}, "
        f"{sql_str(generated_at)}, {int(payload.get('source_report_count', 0))}, "
        f"{int(payload.get('report_schema_version', 9))}, {sql_str(sha)}, "
        f"{sql_str(body)})"
    )
    what = f"{len(players)} players" if players else "no player rows"
    print(f"  {kind}: wrote revision {int(last_rev) + 1} ({what}). "
          f"report_sync will publish it on its next run.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, required=True,
                    help="KTPInfrastructure checkout on this server")
    sub = ap.add_subparsers(dest="cmd", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("match_ids", nargs="*",
                     help="explicit match ids; default: discover pending")
    gen.add_argument("--since", default=None,
                     help="only auto-discover matches with start_time >= "
                          "this ('YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS'); "
                          "ignored when match_ids are given explicitly")
    gen.add_argument("--observer-root", type=Path, default=DEFAULT_OBSERVER_ROOT,
                     help="KTPHudObserver matches directory the in-game "
                          "result is read from (read only)")
    gen.add_argument("--dry-run", action="store_true",
                     help="report what would be built and persist nothing")
    agg = sub.add_parser("aggregate")
    # Required with no default, like report_sync's: an aggregate that forgot
    # its floor pools pre-season test reports into the published season.
    agg.add_argument("--since", type=since_arg, required=True,
                     help="only pool reports whose match start_time >= this")
    imp = sub.add_parser("import-mmr",
                         help="insert a prebuilt mmr_openskill payload built by CI")
    imp.add_argument("payload", type=Path,
                     help="path to mmr_openskill_payload.json")
    args = ap.parse_args(argv)
    if args.cmd == "generate":
        return cmd_generate(args)
    if args.cmd == "import-mmr":
        return cmd_import_mmr(args)
    return cmd_aggregate(args)


if __name__ == "__main__":
    raise SystemExit(main())
