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
) -> list[tuple[float, float, int]]:
    """(flag_term, alive_term, allies_won) at each event in one half."""
    if winner_team not in (1, 2):
        return []
    teams = {int(p["player_id"]): p.get("team") for p in roster
             if p.get("team") in (1, 2)}
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

    owners: dict[int, int] = {}
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
