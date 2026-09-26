"""Excursions: stretches of one life spent alone behind the enemy's lines.

The geometric half of hidden-value plays (see coordination workstream
infra-hidden-value-plays and the sweep of 220 matches, 2026-09-19). An
excursion is a run of position samples inside one life where the player is
past the enemy's rear line AND no living teammate is within the isolation
distance. It carries no events of its own: plays.py joins it to the
flag_swing timeline, which is where the caps, kills and death are priced.

Depth needs no per-map table. Each half's spawn side comes from where players
actually appear after a spawn boundary; depth is the projection onto the
own-spawn -> enemy-spawn axis (0 at own spawn, 1 at the enemy's). Flags rank
by that depth per side; the enemy's rear half is the deepest floor((N-1)/2)
of them and the rear line is the shallower of those. This handled every map
in the pool, neutral-authored ones included.

Isolation is the one parameter that does not generalise: the same distance
is "alone" on lennon and "standing near someone" on harrington. It is now
per map -- ISOLATION_BY_MAP, the p80 of each map's OWN distribution of
nearest-teammate distance measured while past the enemy rear line, over
87,958 samples from 260 matches (2026-09-22). The flat 1200 it replaces was
measuring the map rather than the player: 1200 is exceeded by 18% of those
samples on lennon5 and 58% on railroad2, so the same rule was far too tight
on the most-played map and far too loose on the widest ones. Private input:
raw coordinates never leave this module -- only distances, depths and times
do.

The window rule alone misses the FAST deep push: a player who goes in with
the team, breaks off for the last few seconds and takes the flag ahead of
everyone. Reported 2026-09-22 against 1789931256-NY1 h1 992 -- kroD pushed
with a teammate 95-358 units away, then finished alone (824 -> 1362 units,
enemies closer than his own side) and capped out. Ten seconds of isolation
is not what made it; depth and speed were. So `touches` measures every
rear-flag capture on its own terms -- the gap to the capper's nearest living
teammate at the moment of the touch, and how deep he was -- independent of
whether a window formed.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

DEFINITION = "excursions_v1"
DEFINITION_VERSION = 1

# p80 of each map's own distribution of nearest-living-teammate distance,
# sampled only while past the enemy rear line (87,958 samples, 260 matches,
# 2026-09-22). Keyed by map_name exactly as ktp_matches stores it. A map that
# is not here falls back to ExcursionConfig.isolation_units, so a new map in
# the pool degrades to the old league-wide behaviour instead of failing.
# Re-derive rather than hand-tune: coordination review/hidden-value.
ISOLATION_BY_MAP: dict[str, float] = {
    "dod_anzio": 1497.0,
    "dod_harrington": 1570.0,
    "dod_lennon2": 1111.0,
    "dod_lennon5_b1": 1145.0,
    "dod_railroad2_s9a": 2292.0,
    "dod_saints2_b3e": 1620.0,
    "dod_thunder2": 1591.0,
}


@dataclass(frozen=True)
class ExcursionConfig:
    isolation_units: float = 1200.0   # fallback when the map has no measured threshold
    min_seconds: float = 10.0         # shorter runs are just routing
    sample_tolerance: float = 2.5     # a teammate sample counts if within this of the runner's
    gap_tolerance: int = 1            # violating samples allowed inside one window
    max_sample_gap: float = 6.0       # a hole in the runner's own samples ends the window
    min_spawns_per_side: int = 3      # fewer and the spawn centroid is a guess

    def validate(self) -> None:
        if self.isolation_units <= 0 or self.min_seconds <= 0:
            raise ValueError("isolation_units and min_seconds must be positive")

    def isolation_for(self, map_name: str | None) -> float:
        """The measured threshold for this map, or the league-wide fallback.

        A caller that sets `isolation_units` explicitly is overriding the
        rule, so its value wins over the table -- that is how the sweep
        tooling pins one distance across every map to compare them.
        """
        if self.isolation_units != ExcursionConfig.isolation_units:
            return self.isolation_units
        return ISOLATION_BY_MAP.get(str(map_name or ""), self.isolation_units)


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _i(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _spawn_centroids(samples: dict[int, list[tuple]], boundaries: Sequence[dict[str, Any]],
                     half: int, min_spawns: int) -> dict[int, tuple[float, float]] | None:
    points: dict[int, list[tuple[float, float]]] = {1: [], 2: []}
    for row in boundaries:
        if _i(row.get("half")) != half or str(row.get("boundary_kind")) != "start":
            continue
        pid, team, at = _i(row.get("player_id")), _i(row.get("team")), _f(row.get("game_time"))
        if pid is None or team not in (1, 2) or at is None:
            continue
        for s in samples.get(pid, []):
            if 0 <= s[0] - at <= 4:
                points[team].append((s[1], s[2]))
                break
    if len(points[1]) < min_spawns or len(points[2]) < min_spawns:
        return None
    return {team: (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))
            for team, pts in points.items()}


def build_excursions(
    position_timeline: Sequence[dict[str, Any]] | None,
    flag_positions: Sequence[dict[str, Any]] | None,
    life_boundaries: Sequence[dict[str, Any]] | None,
    flag_states: Sequence[dict[str, Any]] | None,
    config: ExcursionConfig | None = None,
    capture_credits: Sequence[dict[str, Any]] | None = None,
    *,
    map_name: str | None = None,
    source_available: bool = True,
) -> dict[str, Any]:
    """Per-half solo deep runs, plus every rear-flag touch measured.

    `rows`: half, player_id, team (engine side), start, end, duration,
    min_teammate_distance, max_depth, closest_flag (name),
    closest_flag_distance (to an enemy-owned or neutral rear flag),
    rear_flags (names, from the runner's side).

    `touches` (needs `capture_credits`, rows of half/player_id/flag_name/
    game_time): half, player_id, team, flag, game_time,
    teammate_gap (nearest living teammate at the touch), depth, and
    depth_gain (how much deeper the capper got over the ten seconds before
    it) -- the fast-push signature the window rule cannot see."""
    cfg = config or ExcursionConfig()
    cfg.validate()
    isolation = cfg.isolation_for(map_name)
    envelope: dict[str, Any] = {
        "definition": DEFINITION,
        "definition_version": DEFINITION_VERSION,
        # The resolved distance, not just the config default: a reader of the
        # report should not have to know the table to know what was applied.
        "parameters": asdict(cfg) | {"isolation_units_applied": isolation},
        "status": "available",
        "visibility": "private_shadow_only",
        "writes": False,
        "rating_effect": False,
        "caveats": [
            f"Isolation distance {isolation:.0f} units"
            + (f" (p80 measured for {map_name})." if str(map_name or "") in ISOLATION_BY_MAP
               else " (league-wide fallback; this map has no measured p80)."),
        ],
        "rows": [],
        "touches": [],
        "halves": {},
    }
    if not source_available or not position_timeline or not flag_positions:
        envelope["status"] = "unavailable"
        envelope["caveats"].append("position samples or flag positions missing.")
        return envelope

    flags: dict[str, tuple[float, float]] = {}
    for row in flag_positions:
        name, x, y = row.get("flag_name"), _f(row.get("origin_x")), _f(row.get("origin_y"))
        if name and x is not None and y is not None:
            flags[str(name)] = (x, y)
    n_flags = len(flags)
    if n_flags < 3:
        envelope["status"] = "unavailable"
        envelope["caveats"].append("fewer than three flags located; no rear line.")
        return envelope

    by_half: dict[int, dict[int, list[tuple]]] = {}
    for row in position_timeline:
        half, pid = _i(row.get("half")), _i(row.get("player_id"))
        at, x, y = _f(row.get("game_time")), _f(row.get("pos_x")), _f(row.get("pos_y"))
        if half is None or pid is None or at is None or x is None or y is None:
            continue
        alive = row.get("is_alive")
        alive_flag = 1 if alive in (None, "", "NULL") else (_i(alive) or 0)
        by_half.setdefault(half, {}).setdefault(pid, []).append((at, x, y, alive_flag))

    sides: dict[int, dict[int, int]] = {}
    for row in life_boundaries or []:
        half, pid, team = _i(row.get("half")), _i(row.get("player_id")), _i(row.get("team"))
        if half is not None and pid is not None and team in (1, 2):
            sides.setdefault(half, {})[pid] = team

    ownership: dict[int, list[tuple[float, str, int]]] = {}
    for row in flag_states or []:
        half, at = _i(row.get("half")), _f(row.get("game_time"))
        name, owner = row.get("flag_name"), _i(row.get("owner_team"))
        if half is not None and at is not None and name:
            ownership.setdefault(half, []).append((at, str(name), owner if owner in (1, 2) else 0))
    for rows_ in ownership.values():
        rows_.sort()

    def owner_at(half: int, name: str, t: float) -> int:
        current = 0
        for at, fname, owner in ownership.get(half, []):
            if fname == name and at <= t:
                current = owner
        return current

    credits_by_half: dict[int, list[dict[str, Any]]] = {}
    for row in capture_credits or []:
        half, pid = _i(row.get("half")), _i(row.get("player_id"))
        at = _f(row.get("game_time"))
        if half is not None and pid is not None and at is not None and row.get("flag_name"):
            credits_by_half.setdefault(half, []).append(
                {"player_id": pid, "flag_name": str(row["flag_name"]), "game_time": at})

    rows: list[dict[str, Any]] = []
    touches: list[dict[str, Any]] = []
    for half in sorted(by_half):
        samples = by_half[half]
        for pid in samples:
            samples[pid].sort()
        side = sides.get(half, {})
        if len(set(side.values())) < 2:
            continue
        cen = _spawn_centroids(samples, life_boundaries or [], half, cfg.min_spawns_per_side)
        if cen is None:
            envelope["halves"][str(half)] = "no spawn centroid"
            continue
        axis = (cen[2][0] - cen[1][0], cen[2][1] - cen[1][1])
        length = math.hypot(*axis) or 1.0
        unit = (axis[0] / length, axis[1] / length)

        def depth(x: float, y: float, team: int) -> float:
            d = ((x - cen[1][0]) * unit[0] + (y - cen[1][1]) * unit[1]) / length
            return d if team == 1 else 1.0 - d

        ranked = {team: sorted(((depth(*flags[name], team), name) for name in flags), reverse=True)
                  for team in (1, 2)}
        k = max(1, (n_flags - 1) // 2)
        rear = {team: [name for _, name in ranked[team][:k]] for team in (1, 2)}
        rear_line = {team: ranked[team][k - 1][0] for team in (1, 2)}
        envelope["halves"][str(half)] = {
            "rear_flags": {"allies": rear[1], "axis": rear[2]},
            "rear_line_depth": {"allies": round(rear_line[1], 3), "axis": round(rear_line[2], 3)},
        }

        def nearest_mate(pid: int, t: float, x: float, y: float) -> float | None:
            team = side.get(pid)
            best = None
            for other, seq in samples.items():
                if other == pid or side.get(other) != team:
                    continue
                cand = [s for s in seq if abs(s[0] - t) <= cfg.sample_tolerance and s[3]]
                if not cand:
                    continue
                s = min(cand, key=lambda s: abs(s[0] - t))
                d = math.hypot(x - s[1], y - s[2])
                best = d if best is None or d < best else best
            return best

        for credit in credits_by_half.get(half, []):
            pid, at = credit["player_id"], credit["game_time"]
            team = side.get(pid)
            if team not in (1, 2) or credit["flag_name"] not in rear[team]:
                continue
            here = [s for s in samples.get(pid, []) if abs(s[0] - at) <= 3 and s[3]]
            if not here:
                continue
            s_now = min(here, key=lambda s: abs(s[0] - at))
            before = [s for s in samples.get(pid, [])
                      if at - 10 <= s[0] <= at and s[3]]
            depth_now = depth(s_now[1], s_now[2], team)
            touches.append({
                "half": half, "player_id": pid, "team": team,
                "flag": credit["flag_name"], "game_time": round(at, 2),
                "teammate_gap": (lambda d: round(d) if d is not None else None)(
                    nearest_mate(pid, s_now[0], s_now[1], s_now[2])),
                "depth": round(depth_now, 3),
                "depth_gain": round(depth_now - min(
                    depth(s[1], s[2], team) for s in before), 3) if before else None,
            })

        for pid, seq in samples.items():
            team = side.get(pid)
            if team not in (1, 2):
                continue
            enemy = 2 if team == 1 else 1
            i = 0
            while i < len(seq):
                t, x, y, alive = seq[i]
                if not (alive and depth(x, y, team) > rear_line[team]):
                    i += 1
                    continue
                mate = nearest_mate(pid, t, x, y)
                if mate is not None and mate <= isolation:
                    i += 1
                    continue
                j, bad, last_good = i, 0, i
                good: list[tuple] = []
                while j < len(seq):
                    t2, x2, y2, alive2 = seq[j]
                    if not alive2 or (j > i and t2 - seq[j - 1][0] > cfg.max_sample_gap):
                        break
                    d2 = depth(x2, y2, team)
                    m2 = nearest_mate(pid, t2, x2, y2)
                    if d2 > rear_line[team] and (m2 is None or m2 > isolation):
                        last_good, bad = j, 0
                        good.append((t2, x2, y2, d2, m2 if m2 is not None else float("inf")))
                    else:
                        bad += 1
                        if bad > cfg.gap_tolerance:
                            break
                    j += 1
                start, end = seq[i][0], seq[last_good][0]
                if end - start >= cfg.min_seconds and good:
                    closest, closest_name = None, None
                    for t2, x2, y2, _, _ in good:
                        for name in rear[team]:
                            if owner_at(half, name, t2) == team:
                                continue  # already ours: not a target
                            d = math.hypot(x2 - flags[name][0], y2 - flags[name][1])
                            if closest is None or d < closest:
                                closest, closest_name = d, name
                    rows.append({
                        "half": half, "player_id": pid, "team": team,
                        "start": round(start, 2), "end": round(end, 2),
                        "duration": round(end - start, 2),
                        "min_teammate_distance": round(min(g[4] for g in good)) if all(g[4] != float("inf") for g in good) else None,
                        "max_depth": round(max(g[3] for g in good), 3),
                        "closest_flag": closest_name,
                        "closest_flag_distance": round(closest) if closest is not None else None,
                        "rear_flags": list(rear[team]),
                    })
                i = max(j, i + 1)
    rows.sort(key=lambda r: (r["half"], r["start"], r["player_id"]))
    touches.sort(key=lambda r: (r["half"], r["game_time"], r["player_id"]))
    envelope["rows"] = rows
    envelope["rows_total"] = len(rows)
    envelope["touches"] = touches
    return envelope
