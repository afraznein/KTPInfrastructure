"""Per-match spatial layers on the world_256_v1 lattice.

Pure functions over the rows build_report() already loads (position samples,
flag origins, producer frag context, public player rows). Produces the
aggregate, unattributed map layers the website explorer draws:

  occupancy        cells: samples, seconds, team1/team2 samples, signed control
  kill_hotspots    cells: kill count (attacker endpoint), unattributed
  death_hotspots   cells: death count (victim endpoint), unattributed
  recurring_lanes  origin-cell -> destination-cell pairs, thresholded
  flags            flag origins (map facts, not player data)

plus `private_frag_vectors`: one line per coordinate-complete frag with names.
That sub-block is for restricted local review only; the public DTO never
copies it. Per-frag kill angles stay private until a contributor-suppression
rule is ruled on (2026-08-29 website handover §12) — `publish_frag_vectors`
exists so that ruling can flip one flag rather than rewrite a builder.

Thresholds follow the reviewed atlas config (config/analytics/spatial_maps):
15 s occupancy per target cell, lanes need >= 3 occurrences; contributor
floors (>= 2 distinct attackers AND victims) are the provisional sparse-data
guard the doctrine asks for. Every parameter is pinned in SpatialLayersConfig
and stamped as definition_version. Coordinates are world units; the website
projects through the reviewed world_to_pixel matrix when it has one, and
draws a schematic otherwise.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Sequence

DEFINITION_VERSION = 1
LATTICE_SCHEME = "world_256_v1"


@dataclass(frozen=True)
class SpatialLayersConfig:
    grid_size: float = 256.0
    sample_seconds: float = 2.0            # position producer cadence
    cell_minimum_seconds: float = 15.0     # target-cell occupancy floor
    hotspot_minimum_events: int = 2
    hotspot_minimum_contributors: int = 2
    lane_minimum_occurrences: int = 3
    lane_minimum_contributors: int = 2     # distinct attackers AND distinct victims
    publish_frag_vectors: bool = False


def cell_index(x: float, y: float, grid: float) -> tuple[int, int]:
    return math.floor(x / grid), math.floor(y / grid)


def cell_center(col: int, row: int, grid: float) -> tuple[float, float]:
    return (col + 0.5) * grid, (row + 0.5) * grid


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _envelope(cfg: SpatialLayersConfig) -> dict[str, Any]:
    return {
        "definition": "spatial_layers_v1",
        "definition_version": DEFINITION_VERSION,
        "parameters": asdict(cfg) | {"lattice": LATTICE_SCHEME, "clock": "producer_game_time"},
        "status": "available",
        "visibility": "aggregate_only",
        "writes": False,
        "rating_effect": False,
        "caveats": [],
        "lattice": None,
        "flags": [],
        "coverage": {"samples_total": 0, "samples_used": 0, "frags_total": 0,
                     "frags_with_endpoints": 0, "frags_used": 0,
                     "cells_total": 0, "cells_censored": 0},
        "layers": {
            "occupancy": {"cells": []},
            "kill_hotspots": {"cells": []},
            "death_hotspots": {"cells": []},
            "recurring_lanes": {"vectors": []},
        },
        "private_frag_vectors": {
            "visibility": "private_shadow_only",
            "published": cfg.publish_frag_vectors,
            "vectors": [],
        },
    }


def _closed(block: dict[str, Any], status: str, caveat: str) -> dict[str, Any]:
    block["status"] = status
    block["caveats"].append(caveat)
    return block


def build_spatial_layers(
    position_samples: Sequence[dict[str, Any]] | None,
    flag_positions: Sequence[dict[str, Any]] | None,
    frag_context: Sequence[dict[str, Any]] | None,
    players: Sequence[dict[str, Any]],
    config: SpatialLayersConfig | None = None,
    *,
    source_available: bool = True,
    temporal_valid: bool = True,
) -> dict[str, Any]:
    cfg = config or SpatialLayersConfig()
    block = _envelope(cfg)
    if not temporal_valid:
        return _closed(block, "timed_metrics_suppressed",
                       "Replay timing is compressed; occupancy seconds need real clocks.")
    if not source_available or position_samples is None:
        return _closed(block, "unavailable", "Position samples unavailable.")

    grid = cfg.grid_size
    min_samples = math.ceil(cfg.cell_minimum_seconds / cfg.sample_seconds)

    # Occupancy: alive samples with a team and both coordinates.
    occ: dict[tuple[int, int], dict[str, int]] = defaultdict(lambda: {1: 0, 2: 0})
    samples_total = samples_used = 0
    for r in position_samples:
        samples_total += 1
        x, y = _f(r.get("pos_x")), _f(r.get("pos_y"))
        team = r.get("team")
        alive = r.get("is_alive")
        if x is None or y is None or team not in (1, 2):
            continue
        if alive is not None and not int(alive):
            continue
        occ[cell_index(x, y, grid)][int(team)] += 1
        samples_used += 1

    # Frags: producer-context rows with both endpoints.
    frags_total = frags_with_endpoints = frags_used = 0
    kills: dict[tuple[int, int], dict[str, Any]] = defaultdict(lambda: {"n": 0, "who": set()})
    deaths: dict[tuple[int, int], dict[str, Any]] = defaultdict(lambda: {"n": 0, "who": set()})
    lanes: dict[tuple[int, int, int, int], dict[str, Any]] = defaultdict(
        lambda: {"n": 0, "attackers": set(), "victims": set(), "dist": 0.0,
                 "dx": 0.0, "dy": 0.0, "hs": 0})
    private: list[dict[str, Any]] = []
    for r in frag_context or []:
        frags_total += 1
        kx, ky = _f(r.get("killer_pos_x")), _f(r.get("killer_pos_y"))
        vx, vy = _f(r.get("victim_pos_x")), _f(r.get("victim_pos_y"))
        if None in (kx, ky, vx, vy):
            continue
        frags_with_endpoints += 1
        half = r.get("half")
        if not half:
            continue
        frags_used += 1
        kc, vc = cell_index(kx, ky, grid), cell_index(vx, vy, grid)
        kid, vid = r.get("killer_id"), r.get("victim_id")
        kills[kc]["n"] += 1
        kills[kc]["who"].add(kid)
        deaths[vc]["n"] += 1
        deaths[vc]["who"].add(vid)
        dx, dy = vx - kx, vy - ky
        lane = lanes[(*kc, *vc)]
        lane["n"] += 1
        lane["attackers"].add(kid)
        lane["victims"].add(vid)
        lane["dist"] += math.hypot(dx, dy)
        lane["dx"] += dx
        lane["dy"] += dy
        lane["hs"] += 1 if r.get("headshot") else 0
        private.append({
            "half": int(half), "game_time": _f(r.get("game_time")),
            "attacker": {"name": r.get("killer_name"), "team": r.get("killer_team")},
            "victim": {"name": r.get("victim_name"), "team": r.get("victim_team")},
            "origin": {"x": kx, "y": ky}, "destination": {"x": vx, "y": vy},
            "weapon": r.get("weapon"), "headshot": bool(r.get("headshot")),
            "distance": round(math.hypot(dx, dy), 1),
            "angle_degrees": round(math.degrees(math.atan2(dy, dx)), 1),
        })

    flags = []
    for r in flag_positions or []:
        x, y = _f(r.get("origin_x")), _f(r.get("origin_y"))
        if x is None or y is None:
            continue
        col, row = cell_index(x, y, grid)
        flags.append({"flag_index": int(r["flag_index"]), "flag_name": r.get("flag_name"),
                      "x": x, "y": y, "col": col, "row": row})
    flags.sort(key=lambda f: f["flag_index"])

    # Lattice bounds over everything that will be drawn.
    keys = set(occ) | set(kills) | set(deaths) | {(f["col"], f["row"]) for f in flags}
    keys |= {(a, b) for (a, b, _c, _d) in lanes} | {(c, d) for (_a, _b, c, d) in lanes}
    if not keys:
        block["coverage"].update(samples_total=samples_total, frags_total=frags_total)
        return _closed(block, "insufficient_samples", "No located samples, frags or flags.")
    cmin, rmin = min(c for c, _ in keys), min(r for _, r in keys)
    cmax, rmax = max(c for c, _ in keys), max(r for _, r in keys)
    block["lattice"] = {"scheme": LATTICE_SCHEME, "grid_size": grid,
                        "column_index_min": cmin, "row_index_min": rmin,
                        "columns": cmax - cmin + 1, "rows": rmax - rmin + 1}
    block["flags"] = flags

    occupancy_cells, censored = [], 0
    for (col, row), t in sorted(occ.items()):
        total = t[1] + t[2]
        if total < min_samples:
            censored += 1
            continue
        occupancy_cells.append({
            "col": col, "row": row, "samples": total,
            "seconds": round(total * cfg.sample_seconds, 1),
            "team1_samples": t[1], "team2_samples": t[2],
            "control": round((t[1] - t[2]) / total, 4),
        })
    block["layers"]["occupancy"]["cells"] = occupancy_cells

    def hotspots(source: dict, key: str) -> list[dict[str, Any]]:
        return [{"col": c, "row": r, key: v["n"]}
                for (c, r), v in sorted(source.items())
                if v["n"] >= cfg.hotspot_minimum_events
                and len(v["who"] - {None}) >= cfg.hotspot_minimum_contributors]

    block["layers"]["kill_hotspots"]["cells"] = hotspots(kills, "kills")
    block["layers"]["death_hotspots"]["cells"] = hotspots(deaths, "deaths")

    vectors = []
    for (oc, orow, dc, drow), lane in lanes.items():
        if lane["n"] < cfg.lane_minimum_occurrences:
            continue
        if (len(lane["attackers"] - {None}) < cfg.lane_minimum_contributors
                or len(lane["victims"] - {None}) < cfg.lane_minimum_contributors):
            continue
        ox, oy = cell_center(oc, orow, grid)
        dx_, dy_ = cell_center(dc, drow, grid)
        vectors.append({
            "origin": {"col": oc, "row": orow, "x": ox, "y": oy},
            "destination": {"col": dc, "row": drow, "x": dx_, "y": dy_},
            "count": lane["n"],
            "mean_distance": round(lane["dist"] / lane["n"], 1),
            "mean_angle_degrees": round(math.degrees(math.atan2(lane["dy"], lane["dx"])), 1),
            "headshot_rate": round(lane["hs"] / lane["n"], 3),
        })
    vectors.sort(key=lambda v: -v["count"])
    block["layers"]["recurring_lanes"]["vectors"] = vectors
    block["private_frag_vectors"]["vectors"] = private

    block["coverage"] = {
        "samples_total": samples_total, "samples_used": samples_used,
        "frags_total": frags_total, "frags_with_endpoints": frags_with_endpoints,
        "frags_used": frags_used,
        "cells_total": len(occ), "cells_censored": censored,
    }
    if not occupancy_cells and not vectors and not flags:
        return _closed(block, "insufficient_samples", "Every cell fell below the occupancy floor.")
    if frag_context is None:
        block["caveats"].append("Producer frag context unavailable; hotspot and lane layers are empty.")
    return block
