"""analytics-report-dto-v1: sanitize a match_analytics schema-v7 report for the website.

Whitelist-only construction — nothing is copied wholesale from the internal
report. Output carries player names (public on a stats site) and NEVER:
player_id, steam_id, event ids, wall-clock unix stamps, positional keys, or
any shadow/private block outside Tier P1 (see
WEBSITE_SHADOW_STATS_PROMOTION_HANDOVER_20260906.md §2-3; pid-only rule
applies to review artifacts, not the website).

CLI: python analytics_report_dto.py report.json [...] --out DIR
       [--accumulation accumulation-report.json]  (attach a scorer output)
Library: sanitize_report(report_dict) -> dict, assert_sanitized(dto).

Accumulation (points, points per life, impact index) comes from the separate
accumulation scorer (accumulation_v3 + momentum v5 profile). report_service
attaches its shareable part under report["accumulation"] when the scorer ran;
otherwise the DTO's ratings.accumulation block is status "unavailable" and the
website renders Unavailable, never zero.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

CONTRACT_VERSION = "analytics-report-dto-v1.0.0"

# Key names that must never appear anywhere in a sanitized DTO (identity,
# raw event/positional keys, private blocks). Rating blocks are allowed
# since the 2026-09-06 P2 decision, labeled provisional.
FORBIDDEN_KEY_PARTS = (
    "player_id", "steam_id", "steamid", "event_id", "unix", "pos_",
    "private", "life_", "timeline", "break_reel",
)

PROVISIONAL_NOTICE = (
    "Provisional rating: uncalibrated model, recomputed as calibration "
    "matures. Published values change retroactively."
)


def _num(value):
    """Internal reports carry some numerics as strings ('1.656', '958')."""
    if value is None or isinstance(value, (int, float)):
        return value
    try:
        f = float(value)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return None


def ktpr_display(z, *, floor: float = 50.0, center: float = 100.0,
                  per_z: float = 15.0):
    """Map a KTPR v2 z-score rating onto a floored display scale.

    Operator ruling 2026-09-09: KTPR v2 must never show a negative number
    on the website; 50 is the floor. Internal z-score math (ktpr_v2.py,
    ktpr_season.py) is unaffected — this only shapes what ships in the DTO.
    """
    value = _num(z)
    if value is None:
        return None
    return round(max(floor, center + per_z * value), 2)


def _name(value):
    """Repair double-encoded UTF-8 ('SavageÂ¬' -> 'Savage¬').

    Reports generated over the SSH console path carry names that were UTF-8
    bytes re-decoded as latin-1. A strict latin-1 -> utf-8 round trip only
    succeeds on such strings, so a correct name passes through untouched.
    Server-local report generation does not need this; kept as defense.
    """
    if not isinstance(value, str):
        return value
    for codec in ("latin-1", "cp1252"):
        try:
            return value.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return value


def _actor(a: dict) -> dict:
    return {"name": _name(a.get("name")), "team": a.get("team")}


POINTS_PER_LIFE_DEFINITION = (
    "total_points / (deaths + halves_played): every life ends in a death "
    "except the last one of each half"
)


def _accumulation_block(report: dict, team_by_name: dict) -> dict:
    """Shareable slice of the accumulation scorer output (attached by
    report_service as report['accumulation']); fail-closed when absent."""
    acc = report.get("accumulation") or {}
    players = acc.get("players") or []
    if not players:
        return {"status": "unavailable", "players": []}
    halves = _num((report.get("match") or {}).get("halves_played")) or 0
    rows = []
    for p in players:
        name = _name(p.get("player_name_at_match"))
        total = _num(p.get("total_points"))
        deaths = _num(p.get("deaths"))
        lives = (deaths or 0) + halves
        rows.append({
            "name": name,
            "team": team_by_name.get(name),
            "total_points": total,
            "points_per_minute": _num(p.get("points_per_minute")),
            "points_per_life": (round(total / lives, 2)
                                if total is not None and lives > 0 else None),
            "impact_index": _num(p.get("impact_index")),
            "observed_seconds": _num(p.get("observed_seconds")),
            "participation_percent": _num(p.get("participation_percent")),
            "rank": _num(p.get("rank")),
        })
    impact = acc.get("impact_index") or {}
    return {
        "status": acc.get("status"),
        "publication_state": acc.get("publication_state"),
        "profile": acc.get("profile"),
        "profile_sha256": acc.get("profile_sha256"),
        "profile_status": acc.get("profile_status"),
        "schema_version": acc.get("schema_version"),
        "generated_at": str(acc.get("generated_at")) if acc.get("generated_at") else None,
        "lives_rule": POINTS_PER_LIFE_DEFINITION,
        "impact_index": {k: _num(impact.get(k)) for k in (
            "center_index", "points_per_robust_sigma", "minimum_index",
            "reference_points_per_minute", "reference_log_scale")}
        | {"range_contract": impact.get("range_contract"),
           "reference_source": impact.get("reference_source")},
        "players": rows,
    }


def sanitize_report(report: dict) -> dict:
    match = report.get("match") or {}
    st = report.get("shadow_timelines") or {}
    se = report.get("shadow_explorations") or {}
    ta = st.get("trade_analysis") or {}
    rs = se.get("recap_speed") or {}
    ktpr = se.get("ktpr_v2") or {}
    swing = se.get("flag_swing") or {}
    # flag_swing players carry no name; join on the internal id here so
    # only the name crosses.
    names_by_id = {p.get("player_id"): _name(p.get("player_name_at_match"))
                   for p in report.get("players") or []}
    team_by_name = {_name(p.get("player_name_at_match")): p.get("team")
                    for p in report.get("players") or []}

    dto = {
        "contract_version": CONTRACT_VERSION,
        "source": {
            "report_schema_version": report.get("schema_version"),
            "generated_at": str(report.get("generated_at")),
            "quality_status": (report.get("quality") or {}).get("status"),
        },
        "match": {
            "match_id": report.get("match_id"),
            "map_name": match.get("map_name"),
            "started_at": str(match.get("started_at")),
            "duration_seconds": _num(match.get("duration_seconds")),
            "halves_played": _num(match.get("halves_played")),
        },
        "teams": [
            {k: _num(t.get(k)) for k in (
                "team", "players", "kills", "deaths", "assists",
                "damage_dealt", "damage_taken", "team_damage",
                "capture_credits", "cap_breaks", "shots", "hits",
                "damage_differential", "raw_accuracy")}
            | {"team_name": t.get("team_name")}
            for t in report.get("teams") or []
        ],
        "players": [
            {"name": _name(p.get("player_name_at_match")),
             "team": p.get("team"), "team_name": p.get("team_name")}
            | {k: _num(p.get(k)) for k in (
                "kills", "deaths", "assists", "headshots", "team_kills",
                "suicides", "damage_dealt", "damage_taken",
                "damage_differential", "capture_credits", "cap_breaks",
                "shots", "hits", "raw_accuracy", "kd_ratio",
                "damage_per_minute", "kills_per_minute", "damage_per_life",
                "headshot_rate", "fast_2k", "fast_3k", "fast_4k_plus")}
            for p in report.get("players") or []
        ],
        "weapons": [
            {"name": _name(w.get("player_name_at_match")), "team": w.get("team"),
             "weapon": w.get("weapon")}
            | {k: _num(w.get(k)) for k in (
                "kills", "headshot_kills", "damage_dealt", "shots", "hits",
                "raw_accuracy")}
            for w in report.get("weapons") or []
        ],
        "duels": [
            {"killer": _name(c.get("killer_name")),
             "victim": _name(c.get("victim_name")),
             "kills": _num(c.get("kills"))}
            for c in (report.get("duel_matrix") or {}).get("cells") or []
            if c.get("cross_team")
        ],
        "trades": {
            "definitions": {
                name: {"definition_version":
                       (d or {}).get("definition_version")}
                for name, d in (st.get("definitions") or {}).items()
            },
            "events": [
                {"half": _num(t.get("half")),
                 "seconds_after": _num(t.get("seconds_after")),
                 "fallen": _actor(t.get("fallen_player") or {}),
                 "original_killer": _actor(t.get("original_killer") or {}),
                 "trader": _actor(t.get("trader") or {})}
                for t in st.get("trades") or []
            ],
            "teams": [
                {"team": _num(t.get("team")),
                 "trade_kills": _num(t.get("trade_kills")),
                 "opportunities": _num(
                     t.get("team_death_response_opportunities")),
                 "response_rate": _num(t.get("team_death_response_rate"))}
                for t in ta.get("teams") or []
            ],
        },
        "fast_multikills": [
            {"classification": m.get("classification"),
             "half": _num(m.get("half")),
             "killer": _actor(m.get("killer") or {}),
             "kill_count": _num(m.get("kill_count")),
             "elapsed_seconds": _num(m.get("elapsed_seconds")),
             "victims": [_actor(v) for v in m.get("victims") or []],
             "objective_converted":
                 bool((m.get("objective_conversion") or {}).get("converted"))}
            for m in st.get("fast_multikills") or []
        ],
        "recap_speed": {
            "definition_version": rs.get("definition_version"),
            "teams": [
                {"team": _num(t.get("team")), "recaps": _num(t.get("recaps")),
                 "median_seconds": _num(t.get("median_seconds")),
                 "mean_seconds": _num(t.get("mean_seconds"))}
                for t in rs.get("teams") or []
            ],
            "events": [
                {"half": _num(e.get("half")), "flag_name": e.get("flag_name"),
                 "team": _num(e.get("team")),
                 "seconds": _num(e.get("seconds"))}
                for e in rs.get("recaps") or []
            ],
        },
        "ratings": {
            "provisional": True,
            "notice": PROVISIONAL_NOTICE,
            "ktpr_v2": {
                "status": ktpr.get("status"),
                "definition": ktpr.get("definition"),
                "definition_version": ktpr.get("definition_version"),
                "calibration": ktpr.get("calibration"),
                "parameters": dict(ktpr.get("parameters") or {}),
                "components_used": list(ktpr.get("components_used") or []),
                "players": [
                    {"name": _name(p.get("player_name_at_match"))
                     or names_by_id.get(p.get("player_id")),
                     "team": p.get("team"),
                     "rating": ktpr_display(p.get("rating")),
                     "components": {k: _num(v) for k, v in
                                    (p.get("components") or {}).items()}}
                    for p in ktpr.get("players") or []
                ],
            },
            "flag_swing": {
                "status": swing.get("status"),
                "definition": swing.get("definition"),
                "definition_version": swing.get("definition_version"),
                "calibration": swing.get("calibration"),
                "parameters": dict(swing.get("parameters") or {}),
                "players": [
                    {"name": names_by_id.get(p.get("player_id")),
                     "team": p.get("team"),
                     "attributed_swing": _num(p.get("attributed_swing")),
                     "weighted_frags": _num(p.get("weighted_frags"))}
                    for p in swing.get("players") or []
                ],
            },
            "accumulation": _accumulation_block(report, team_by_name),
        },
        "lane_analytics": _positional_block(se, names_by_id),
        "spatial": _spatial_block(report),
    }
    assert_sanitized(dto)
    return dto


def _positional_block(se: dict, names_by_id: dict) -> dict:
    """Positional shadow (WEBSITE_POSITIONAL_ANALYTICS_PLAN_20260906 §2):
    team-level control curve (GREEN), per-player overextension scalars
    (GREEN), per-player depth profile scalars (aggregate, identity-attached —
    user sign-off recorded in the plan). No coordinates cross: depth is a
    0..1 lane position, lateral is a mean distance."""
    mc = se.get("map_control") or {}
    dp = se.get("depth_profiles") or {}
    ov = se.get("overextension") or {}

    def envelope(block: dict) -> dict:
        return {"status": block.get("status", "unavailable"),
                "definition": block.get("definition"),
                "definition_version": block.get("definition_version"),
                "caveats": list(block.get("caveats") or [])}

    params = mc.get("parameters") or {}
    return {
        "provisional": True,
        "notice": PROVISIONAL_NOTICE,
        "parameters": {k: params.get(k) for k in (
            "bin_seconds", "frontline_quantile", "ahead_margin",
            "min_side_samples_per_bin")},
        "map_control": envelope(mc) | {
            "orientation_by_half": dict(mc.get("orientation_by_half") or {}),
            "halves": {h: [[_num(t), _num(f)] for t, f in curve]
                       for h, curve in (mc.get("halves") or {}).items()},
            "mean_control_team1": _num(mc.get("mean_control_team1")),
            "bins": dict(mc.get("bins") or {}),
        },
        "depth_profiles": envelope(dp) | {"players": [
            {"name": _name(p.get("player_name_at_match"))
             or names_by_id.get(p.get("player_id")),
             "team": p.get("team"), "samples": _num(p.get("samples")),
             "mean_depth": _num(p.get("mean_depth")),
             "depth_sd": _num(p.get("depth_sd")),
             "lateral_mean": _num(p.get("lateral_mean"))}
            for p in dp.get("players") or []]},
        "overextension": envelope(ov) | {
            "frags": dict(ov.get("frags") or {}),
            "players": [
                {"name": _name(p.get("player_name_at_match"))
                 or names_by_id.get(p.get("player_id")),
                 "team": p.get("team")}
                | {k: _num(p.get(k)) for k in (
                    "kills_located", "kills_ahead", "deaths_located",
                    "deaths_ahead", "kill_ahead_rate", "death_ahead_rate")}
                for p in ov.get("players") or []]},
    }


SPATIAL_PARAMETERS = (
    "grid_size", "lane_grid_size", "sample_seconds", "cell_minimum_seconds",
    "window_seconds", "window_cell_minimum_seconds",
    "hotspot_minimum_events", "hotspot_minimum_contributors",
    "lane_minimum_occurrences", "lane_minimum_contributors", "lattice",
)
OCCUPANCY_FIELDS = ("col", "row", "samples", "seconds", "team1_samples", "team2_samples", "control")


def _spatial_block(report: dict) -> dict:
    """Map layers (spatial_layers_v2): occupancy/control cells (whole match,
    per half, per time window), unattributed kill/death hotspot cells,
    thresholded recurring lanes, flag origins — and, by the operator's
    2026-09-09 ruling, per-frag kill paths with attacker/victim names when the
    producer published them. Coordinates are world units. The producer's
    `private_frag_vectors` (paths held back when the publish flag is off) is
    never copied."""
    sp = report.get("spatial_layers") or {}
    layers = sp.get("layers") or {}
    params = sp.get("parameters") or {}

    def cell_rows(rows, fields: tuple) -> list:
        return [{k: _num(c.get(k)) for k in fields} for c in rows or []]

    def cells(name: str, fields: tuple) -> list:
        return cell_rows((layers.get(name) or {}).get("cells"), fields)

    def endpoint(e: dict) -> dict:
        return {k: _num(e.get(k)) for k in ("col", "row", "x", "y")}

    halves = {
        str(h): {"start": _num(v.get("start")), "end": _num(v.get("end")),
                 "cells": cell_rows(v.get("cells"), OCCUPANCY_FIELDS)}
        for h, v in (layers.get("halves") or {}).items()
    }
    windows = layers.get("windows") or {}
    frag_layer = layers.get("frag_vectors") or {}
    paths = [
        {"half": _num(v.get("half")), "game_time": _num(v.get("game_time")),
         "attacker": _actor(v.get("attacker") or {}), "victim": _actor(v.get("victim") or {}),
         "origin": {k: _num((v.get("origin") or {}).get(k)) for k in ("x", "y")},
         "destination": {k: _num((v.get("destination") or {}).get(k)) for k in ("x", "y")},
         "weapon": v.get("weapon"), "headshot": bool(v.get("headshot")),
         "distance": _num(v.get("distance")), "angle_degrees": _num(v.get("angle_degrees"))}
        for v in (frag_layer.get("vectors") or []) if frag_layer.get("published")
    ]

    return {
        "halves": halves,
        "windows": {
            "window_seconds": _num(windows.get("window_seconds")),
            "minimum_seconds": _num(windows.get("minimum_seconds")),
            "columns": list(windows.get("columns") or []),
            "rows": [[_num(x) for x in row] for row in windows.get("rows") or []],
        },
        "kill_paths": {"published": bool(frag_layer.get("published")), "vectors": paths},
        "status": sp.get("status", "unavailable"),
        "definition": sp.get("definition"),
        "definition_version": sp.get("definition_version"),
        "caveats": list(sp.get("caveats") or []),
        "provisional": True,
        "notice": PROVISIONAL_NOTICE,
        "parameters": {k: params.get(k) for k in SPATIAL_PARAMETERS},
        "lattice": (dict(sp.get("lattice")) if sp.get("lattice") else None),
        "flags": [
            {"flag_index": _num(f.get("flag_index")), "flag_name": f.get("flag_name"),
             "x": _num(f.get("x")), "y": _num(f.get("y")),
             "col": _num(f.get("col")), "row": _num(f.get("row"))}
            for f in sp.get("flags") or []
        ],
        "coverage": {k: _num(v) for k, v in (sp.get("coverage") or {}).items()},
        "occupancy": cells("occupancy", OCCUPANCY_FIELDS),
        "kill_hotspots": cells("kill_hotspots", ("col", "row", "kills")),
        "death_hotspots": cells("death_hotspots", ("col", "row", "deaths")),
        "recurring_lanes": [
            {"origin": endpoint(v.get("origin") or {}),
             "destination": endpoint(v.get("destination") or {}),
             "count": _num(v.get("count")),
             "mean_distance": _num(v.get("mean_distance")),
             "mean_angle_degrees": _num(v.get("mean_angle_degrees")),
             "headshot_rate": _num(v.get("headshot_rate"))}
            for v in (layers.get("recurring_lanes") or {}).get("vectors") or []
        ],
    }


def _walk_keys(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield f"{path}.{k}", k
            yield from _walk_keys(v, f"{path}.{k}")
    elif isinstance(node, list):
        for item in node:
            yield from _walk_keys(item, path + "[]")


def assert_sanitized(dto: dict) -> None:
    for path, key in _walk_keys(dto):
        lowered = key.lower()
        for part in FORBIDDEN_KEY_PARTS:
            if part in lowered:
                raise ValueError(f"forbidden key {key!r} at {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("reports", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--accumulation", type=Path, default=None,
                    help="accumulation scorer report.json to attach "
                         "(single-report runs)")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for src in args.reports:
        report = json.loads(src.read_text(encoding="utf-8"))
        if args.accumulation:
            acc = json.loads(args.accumulation.read_text(encoding="utf-8"))
            # The scorer bundle keeps the profile hash in its manifest;
            # report_service computes it directly when it runs the scorer.
            manifest = args.accumulation.with_name("manifest.json")
            if not acc.get("profile_sha256") and manifest.exists():
                acc["profile_sha256"] = json.loads(
                    manifest.read_text(encoding="utf-8")).get("profile_sha256")
            report["accumulation"] = acc
        dto = sanitize_report(report)
        dest = args.out / f"public-{src.name}"
        dest.write_text(json.dumps(dto, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        print(f"{dest} ({dest.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
