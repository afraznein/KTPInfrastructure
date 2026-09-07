"""Positional shadow analytics: map control, depth profiles, overextension.

Pure functions over the rows build_report() already loads (position samples,
flag origins, producer frag context, public player rows). Port of the
analytics lane's prototype (artifacts/real-match-tier2-20260906/
positional_metrics.py, 2026-09-06); every parameter is an uncalibrated
choice pinned in PositionalConfig and stamped as definition_version.

Geometry
  Lane axis: polyline through the map's flag origins in flag_index order.
  Each sample projects to its nearest point; the arc position (0..1) is the
  raw coordinate. Depth is side-normalized per (half, team): the team whose
  first `orientation_window_seconds` of samples sit nearer arc 0 keeps
  0 = own end, 1 = enemy end (sides swap at halftime, never assume team 1
  sits at arc 0).
  Frontline per `bin_seconds` bin = midpoint of team-1 depth at the
  `frontline_quantile` and team-2 depth mirrored; a bin with fewer than
  `min_side_samples_per_bin` samples on either side is censored.
  Overextension: a frag counts only when it carries producer position
  context AND falls in a resolved bin (numerator and denominator alike, so
  the frag-context coverage ceiling never biases the rates); "ahead" =
  depth > own frontline + `ahead_margin`.

Everything stays visibility private_shadow_only; the website DTO decides
what crosses (team-level curve, per-player scalars).
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Sequence

DEFINITION_VERSION = 1


@dataclass(frozen=True)
class PositionalConfig:
    bin_seconds: float = 4.0
    frontline_quantile: float = 0.75
    ahead_margin: float = 0.05
    min_side_samples_per_bin: int = 4
    orientation_window_seconds: float = 30.0
    min_position_samples: int = 1000
    min_flag_origins: int = 2


def project(poly: Sequence[tuple[float, float]], x: float, y: float) -> tuple[float, float]:
    """Arc-length position (0..1) of the nearest point on the polyline and
    the perpendicular distance to it."""
    total = sum(math.dist(poly[i], poly[i + 1]) for i in range(len(poly) - 1))
    best_arc, best_dist = 0.0, math.inf
    acc = 0.0
    for i in range(len(poly) - 1):
        ax, ay = poly[i]
        bx, by = poly[i + 1]
        seg = math.dist(poly[i], poly[i + 1])
        if seg == 0:
            continue
        t = max(0.0, min(1.0, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / (seg * seg)))
        px, py = ax + t * (bx - ax), ay + t * (by - ay)
        d = math.hypot(x - px, y - py)
        if d < best_dist:
            best_arc, best_dist = (acc + t * seg) / total, d
        acc += seg
    return best_arc, best_dist


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _envelope(definition: str, config: PositionalConfig) -> dict[str, Any]:
    return {
        "definition": definition,
        "definition_version": DEFINITION_VERSION,
        "parameters": asdict(config) | {"clock": "producer_game_time"},
        "status": "available",
        "visibility": "private_shadow_only",
        "writes": False,
        "rating_effect": False,
        "caveats": [],
    }


def _closed(blocks: dict[str, dict[str, Any]], status: str, caveat: str) -> dict[str, Any]:
    for block in blocks.values():
        block["status"] = status
        block["caveats"].append(caveat)
    return blocks


def build_positional_shadow(
    position_samples: Sequence[dict[str, Any]] | None,
    flag_positions: Sequence[dict[str, Any]] | None,
    frag_context: Sequence[dict[str, Any]] | None,
    players: Sequence[dict[str, Any]],
    config: PositionalConfig | None = None,
    *,
    source_available: bool = True,
    temporal_valid: bool = True,
) -> dict[str, dict[str, Any]]:
    cfg = config or PositionalConfig()
    blocks = {
        "map_control": _envelope("map_control_frontline_v1", cfg)
        | {"orientation_by_half": {}, "halves": {}, "mean_control_team1": None,
           "bins": {"resolved": 0, "censored": 0}},
        "depth_profiles": _envelope("depth_profile_v1", cfg) | {"players": []},
        "overextension": _envelope("overextension_frontline_v1", cfg)
        | {"players": [], "frags": {"total": 0, "with_context": 0,
                                    "in_resolved_bins": 0}},
    }
    if not temporal_valid:
        return _closed(blocks, "timed_metrics_suppressed",
                       "Replay timing is compressed; positional bins need real clocks.")
    if not source_available or position_samples is None or flag_positions is None:
        return _closed(blocks, "unavailable",
                       "Position samples or flag origins unavailable.")

    origins = sorted(
        (r for r in flag_positions
         if _f(r.get("origin_x")) is not None and _f(r.get("origin_y")) is not None),
        key=lambda r: int(r["flag_index"]))
    if len(origins) < cfg.min_flag_origins:
        return _closed(blocks, "unavailable",
                       f"Fewer than {cfg.min_flag_origins} flag origins; no lane axis.")
    poly = [(_f(r["origin_x"]), _f(r["origin_y"])) for r in origins]

    samples: dict[int, list[tuple[float, int, int, float, float]]] = defaultdict(list)
    for r in position_samples:
        x, y, t = _f(r.get("pos_x")), _f(r.get("pos_y")), _f(r.get("game_time"))
        team, half = r.get("team"), r.get("half")
        if None in (x, y, t) or team not in (1, 2) or not half:
            continue
        arc, lat = project(poly, x, y)
        samples[int(half)].append((t, int(team), int(r["player_id"]), arc, lat))
    if sum(len(v) for v in samples.values()) < cfg.min_position_samples:
        return _closed(blocks, "insufficient_samples",
                       f"Fewer than {cfg.min_position_samples} position samples.")

    # Orientation per half: the team whose early samples sit nearer arc 0
    # owns that end for the half.
    orient: dict[int, int] = {}
    for half, rows in samples.items():
        rows.sort()
        t0 = rows[0][0]
        early = {1: [], 2: []}
        for t, team, _pid, arc, _lat in rows:
            if t < t0 + cfg.orientation_window_seconds:
                early[team].append(arc)
        if early[1] and early[2]:
            orient[half] = 1 if statistics.mean(early[1]) < statistics.mean(early[2]) else -1
    if not orient:
        return _closed(blocks, "insufficient_samples",
                       "No half had both teams sampled inside the orientation window.")

    def depth(team: int, arc: float, half: int) -> float:
        own_at_zero = (team == 1) == (orient[half] == 1)
        return arc if own_at_zero else 1.0 - arc

    names = {int(p["player_id"]): p.get("player_name_at_match") for p in players}
    teams = {int(p["player_id"]): p.get("team") for p in players}

    profile: dict[int, dict[str, Any]] = defaultdict(
        lambda: {"n": 0, "sum": 0.0, "sum_sq": 0.0, "lat_sum": 0.0})
    frontline_at: dict[tuple[int, int], float] = {}
    curve_values: list[float] = []
    censored = 0
    q_index = int(round(cfg.frontline_quantile * 4)) - 1  # statistics.quantiles(n=4)
    for half, rows in samples.items():
        if half not in orient:
            continue
        bins: dict[int, dict[int, list[float]]] = defaultdict(lambda: {1: [], 2: []})
        for t, team, pid, arc, lat in rows:
            d = depth(team, arc, half)
            p = profile[pid]
            p["n"] += 1
            p["sum"] += d
            p["sum_sq"] += d * d
            p["lat_sum"] += lat
            bins[int(t // cfg.bin_seconds)][team].append(d)
        curve = []
        for b in sorted(bins):
            d1, d2 = bins[b][1], bins[b][2]
            if len(d1) < cfg.min_side_samples_per_bin or len(d2) < cfg.min_side_samples_per_bin:
                censored += 1
                continue
            q1 = statistics.quantiles(d1, n=4)[q_index]
            q2 = statistics.quantiles(d2, n=4)[q_index]
            f = (q1 + (1.0 - q2)) / 2.0  # team-1 coordinates: 1 = deep in team 2's end
            curve.append([round(b * cfg.bin_seconds, 1), round(f, 4)])
            frontline_at[(half, b)] = f
        if curve:
            blocks["map_control"]["halves"][str(half)] = curve
            blocks["map_control"]["orientation_by_half"][str(half)] = (
                "team1_at_arc0" if orient[half] == 1 else "team2_at_arc0")
            curve_values.extend(f for _, f in curve)
    blocks["map_control"]["bins"] = {"resolved": len(curve_values), "censored": censored}
    if not curve_values:
        blocks["map_control"]["status"] = "insufficient_samples"
        blocks["map_control"]["caveats"].append("No bin had both sides sampled.")
    else:
        blocks["map_control"]["mean_control_team1"] = round(statistics.mean(curve_values), 4)

    blocks["depth_profiles"]["players"] = sorted(
        ({"player_id": pid, "player_name_at_match": names.get(pid),
          "team": teams.get(pid), "samples": p["n"],
          "mean_depth": round(p["sum"] / p["n"], 4),
          "depth_sd": round(math.sqrt(max(p["sum_sq"] / p["n"] - (p["sum"] / p["n"]) ** 2, 0.0)), 4),
          "lateral_mean": round(p["lat_sum"] / p["n"], 1),
          "depth_sum": round(p["sum"], 4), "depth_sum_sq": round(p["sum_sq"], 4),
          "lateral_sum": round(p["lat_sum"], 1)}
         for pid, p in profile.items()),
        key=lambda r: -r["mean_depth"])

    over: dict[int, dict[str, int]] = defaultdict(
        lambda: {"kills_located": 0, "kills_ahead": 0,
                 "deaths_located": 0, "deaths_ahead": 0})
    frags = {"total": 0, "with_context": 0, "in_resolved_bins": 0}
    for r in frag_context or []:
        frags["total"] += 1
        half = r.get("producer_half") or r.get("half")
        t = _f(r.get("game_time"))
        if not half or t is None:
            continue
        half = int(half)
        located = [
            ("kill", r.get("killer_pos_x"), r.get("killer_pos_y"), r.get("killer_id"), r.get("killer_team")),
            ("death", r.get("victim_pos_x"), r.get("victim_pos_y"), r.get("victim_id"), r.get("victim_team")),
        ]
        if any(_f(px) is not None and _f(py) is not None for _r, px, py, _p, _t in located):
            frags["with_context"] += 1
        f = frontline_at.get((half, int(t // cfg.bin_seconds)))
        if f is None:
            continue
        counted = False
        for role, px, py, pid, team in located:
            x, y = _f(px), _f(py)
            if x is None or y is None or team not in (1, 2) or pid is None:
                continue
            arc, _lat = project(poly, x, y)
            d = depth(int(team), arc, half)
            own_frontline = f if int(team) == 1 else 1.0 - f
            ahead = d > own_frontline + cfg.ahead_margin
            o = over[int(pid)]
            o[f"{role}s_located"] += 1
            o[f"{role}s_ahead"] += int(ahead)
            counted = True
        if counted:
            frags["in_resolved_bins"] += 1
    blocks["overextension"]["frags"] = frags
    blocks["overextension"]["players"] = sorted(
        ({"player_id": pid, "player_name_at_match": names.get(pid),
          "team": teams.get(pid), **o,
          "kill_ahead_rate": round(o["kills_ahead"] / o["kills_located"], 3)
          if o["kills_located"] else None,
          "death_ahead_rate": round(o["deaths_ahead"] / o["deaths_located"], 3)
          if o["deaths_located"] else None}
         for pid, o in over.items()),
        key=lambda r: -(r["kills_located"] + r["deaths_located"]))
    if frag_context is None:
        blocks["overextension"]["status"] = "unavailable"
        blocks["overextension"]["caveats"].append("Producer frag context unavailable.")
    elif not over:
        blocks["overextension"]["status"] = "insufficient_samples"
        blocks["overextension"]["caveats"].append("No located frag fell in a resolved bin.")
    return blocks
