"""Fit the flag-swing logistic baseline on historical halves (Tier 3).

Turns (flag control, man advantage) state samples labeled with the
authoritative half winner — engine team_score, never captures or KTPR —
into fitted FlagSwingConfig coefficients. Stdlib only: plain
gradient-descent logistic regression with a no-intercept model matching
build_flag_swing_shadow's symmetric baseline.

Sampling: one sample per state-changing event (flag change or death),
allies-perspective, labeled 1 when the Allies won the half. Halves without
an authoritative winner are skipped, never guessed.
"""
from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from scripts.flag_swing import sides_by_half


@dataclass
class FitResult:
    flag_coefficient: float
    alive_coefficient: float
    samples: int
    halves: int
    log_loss: float
    iterations: int

    def as_config_json(self) -> str:
        return json.dumps({
            "flag_coefficient": round(self.flag_coefficient, 4),
            "alive_coefficient": round(self.alive_coefficient, 4),
            "calibration": (
                f"fitted_team_score_{self.halves}_halves_"
                f"{self.samples}_samples"),
        }, indent=2)


def _sigmoid(x: float) -> float:
    if x < -60.0:
        return 0.0
    if x > 60.0:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


def extract_half_samples(
    flag_states: Sequence[dict[str, Any]],
    frags: Sequence[dict[str, Any]],
    life_boundaries: Sequence[dict[str, Any]],
    roster: Sequence[dict[str, Any]],
    half: int,
    winner_team: int,
    *,
    flag_count: int | None = None,
    initial_owners: dict[int, int] | None = None,
) -> list[tuple[float, float, int]]:
    """(flag_term, alive_term, allies_won) at each event in one half.

    ``winner_team`` is the ENGINE side that won this half (1 Allies, 2 Axis),
    the same frame as flag ``owner_team``. Player sides come from the life
    boundaries of this half (see flag_swing.sides_by_half); the roster's team
    is only the fallback, since it is the side of the last half played.
    """
    if winner_team not in (1, 2):
        return []
    teams = {int(p["player_id"]): p.get("team") for p in roster
             if p.get("team") in (1, 2)}
    half_sides = sides_by_half(life_boundaries).get(half, {})
    teams = {pid: half_sides.get(pid, team) for pid, team in teams.items()}
    if not teams:
        return []
    flags = {int(r["flag_index"]) for r in flag_states
             if r.get("flag_index") is not None}
    total_flags = float(flag_count or len(flags) or 5)
    roster_size = float(len(teams))
    label = 1 if winner_team == 1 else 0

    events: list[tuple[float, str, dict[str, Any]]] = []
    for row in flag_states:
        if int(row.get("half") or 0) == half and row.get("game_time") is not None:
            events.append((float(row["game_time"]), "flag", row))
    for row in frags:
        if int(row.get("half") or 0) == half and row.get("game_time") is not None:
            events.append((float(row["game_time"]), "frag", row))
    for row in life_boundaries:
        if (int(row.get("half") or 0) == half
                and row.get("game_time") is not None
                and str(row.get("boundary_kind")) == "start"):
            events.append((float(row["game_time"]), "spawn", row))
    events.sort(key=lambda item: item[0])

    owners: dict[int, int] = dict(initial_owners or {})
    alive: dict[int, bool] = {pid: True for pid in teams}
    samples: list[tuple[float, float, int]] = []
    for _at, kind, row in events:
        if kind == "flag":
            owner = row.get("owner_team")
            owners[int(row["flag_index"])] = (
                int(owner) if owner in (1, 2) else 0)
        elif kind == "frag":
            victim = row.get("victim_id")
            if victim is not None and int(victim) in alive:
                alive[int(victim)] = False
        else:
            pid = row.get("player_id")
            if pid is not None and int(pid) in alive:
                alive[int(pid)] = True
        allied = sum(1 for owner in owners.values() if owner == 1)
        axis = sum(1 for owner in owners.values() if owner == 2)
        allies_up = sum(1 for pid, up in alive.items()
                        if up and teams[pid] == 1)
        axis_up = sum(1 for pid, up in alive.items()
                      if up and teams[pid] == 2)
        samples.append(((allied - axis) / total_flags,
                        (allies_up - axis_up) / roster_size, label))
    return samples


def fit_logistic(
    samples: Sequence[tuple[float, float, int]],
    *,
    halves: int = 0,
    learning_rate: float = 0.5,
    iterations: int = 2000,
    l2: float = 1e-3,
) -> FitResult:
    """No-intercept two-feature logistic fit; coefficients clamped >= 0.

    The symmetric baseline has no intercept by construction (a mirrored
    state must price to 1-P). Negative coefficients are clamped: a fit
    that claims holding flags hurts is evidence of bad labels, and the
    consumer validates coefficients as non-negative.
    """
    if not samples:
        raise ValueError("no samples to fit")
    a, b = 1.0, 1.0
    n = float(len(samples))
    for step in range(iterations):
        grad_a = grad_b = 0.0
        for flag_term, alive_term, label in samples:
            error = _sigmoid(a * flag_term + b * alive_term) - label
            grad_a += error * flag_term
            grad_b += error * alive_term
        a -= learning_rate * (grad_a / n + l2 * a)
        b -= learning_rate * (grad_b / n + l2 * b)
        a, b = max(a, 0.0), max(b, 0.0)
    loss = 0.0
    for flag_term, alive_term, label in samples:
        p = min(max(_sigmoid(a * flag_term + b * alive_term), 1e-12),
                1.0 - 1e-12)
        loss -= label * math.log(p) + (1 - label) * math.log(1.0 - p)
    return FitResult(a, b, len(samples), halves, round(loss / n, 6),
                     iterations)


# How many labelled halves a map needs before its own fit carries half the
# weight. The league plays one map a week, so a map arrives with 16-20 halves
# and an independent fit on that much data OVERFITS: measured on S10, per-map
# fits lost to pooled out of sample on harrington (by 0.0038) and lennon5 (by
# 0.0029) while winning on thunder2 (by 0.0347), whose flag coefficient is
# genuinely ~3x the league's. Shrinkage is what lets the third case through
# without the first two doing damage. Raise it to trust maps less.
PRIOR_HALVES = 20.0


@dataclass
class MapFitResult:
    map_name: str
    flag_coefficient: float      # shrunk toward the pooled fit -- what to ship
    alive_coefficient: float
    own_flag_coefficient: float  # the map's unshrunk fit, for inspection
    own_alive_coefficient: float
    halves: int
    samples: int
    weight: float                # how much of its own fit the map earned
    log_loss: float

    def as_entry(self) -> tuple[str, tuple[float, float]]:
        return self.map_name, (round(self.flag_coefficient, 4),
                               round(self.alive_coefficient, 4))


def fit_by_map(
    halves_by_map: dict[str, Sequence[Sequence[tuple[float, float, int]]]],
    *,
    prior_halves: float = PRIOR_HALVES,
    **fit_kwargs: Any,
) -> tuple[FitResult, list[MapFitResult]]:
    """Pooled fit, plus each map's fit shrunk toward it.

    `halves_by_map` is map -> halves -> samples; the halves matter because
    shrinkage weighs a map by how many HALVES it has, not how many samples.
    Samples within a half share one label and are strongly correlated, so
    counting them would let a single long half look like independent evidence.
    """
    pooled_samples = [s for halves in halves_by_map.values()
                      for half in halves for s in half]
    if not pooled_samples:
        raise ValueError("no samples to fit")
    pooled = fit_logistic(
        pooled_samples,
        halves=sum(len(h) for h in halves_by_map.values()),
        **fit_kwargs)

    out: list[MapFitResult] = []
    for map_name in sorted(halves_by_map):
        halves = [h for h in halves_by_map[map_name] if h]
        samples = [s for half in halves for s in half]
        if not samples:
            continue
        own = fit_logistic(samples, halves=len(halves), **fit_kwargs)
        weight = len(halves) / (len(halves) + prior_halves) if prior_halves >= 0 else 1.0
        flag = weight * own.flag_coefficient + (1.0 - weight) * pooled.flag_coefficient
        alive = weight * own.alive_coefficient + (1.0 - weight) * pooled.alive_coefficient
        loss = 0.0
        for flag_term, alive_term, label in samples:
            p = min(max(_sigmoid(flag * flag_term + alive * alive_term), 1e-12),
                    1.0 - 1e-12)
            loss -= label * math.log(p) + (1 - label) * math.log(1.0 - p)
        out.append(MapFitResult(
            map_name=map_name,
            flag_coefficient=flag, alive_coefficient=alive,
            own_flag_coefficient=own.flag_coefficient,
            own_alive_coefficient=own.alive_coefficient,
            halves=len(halves), samples=len(samples), weight=round(weight, 4),
            log_loss=round(loss / len(samples), 6)))
    return pooled, out
