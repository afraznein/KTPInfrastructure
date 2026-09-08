"""Flag Swing: the Round-Swing analog for DoD halves (Tier 3, definition v1).

Every state-changing event — a flag ownership change or a frag — is priced
as the change it makes to P(win half) for the Allies, from a transparent
logistic baseline over flag control and man advantage. Cap swing is split
across the credited cappers; frag swing goes to the killer; a cap break is
priced counterfactually as the cap swing it denied (the break-reel rank).

The baseline coefficients are UNCALIBRATED PRIORS until fitted on match
history against the authoritative engine team_score labels; every envelope
says so. Private shadow only: no writes, no rating impact.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class FlagSwingConfig:
    """Logistic baseline P(allies win half) = sigmoid(a*flag + b*alive).

    flag term: (allied_flags - axis_flags) / total_flags in [-1, 1].
    alive term: (allies_alive - axis_alive) / roster_size in [-1, 1].
    Priors chosen so full flag control ~ 88%% and a two-man advantage in a
    6v6 ~ 58%% with even flags; replace by a fitted vector via calibration.
    """

    flag_coefficient: float = 2.0
    alive_coefficient: float = 1.0
    calibration: str = "uncalibrated_baseline"

    def validate(self) -> None:
        if self.flag_coefficient < 0 or self.alive_coefficient < 0:
            raise ValueError("flag-swing coefficients must be >= 0")


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _game_time(row: dict[str, Any]) -> float | None:
    value = row.get("game_time")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class _HalfState:
    """Mutable half state: flag owners and alive sets, allies-perspective."""

    def __init__(self, flag_count: int, roster_size: int,
                 config: FlagSwingConfig,
                 initial_owners: dict[int, int] | None = None) -> None:
        self.owners: dict[int, int] = dict(initial_owners or {})
        self.alive: dict[int, bool] = {}
        self.teams: dict[int, int] = {}
        self.flag_count = max(flag_count, 1)
        self.roster_size = max(roster_size, 1)
        self.config = config

    def p_allies(self) -> float:
        allied = sum(1 for owner in self.owners.values() if owner == 1)
        axis = sum(1 for owner in self.owners.values() if owner == 2)
        flag_term = (allied - axis) / float(self.flag_count)
        allies_alive = sum(1 for pid, up in self.alive.items()
                           if up and self.teams.get(pid) == 1)
        axis_alive = sum(1 for pid, up in self.alive.items()
                         if up and self.teams.get(pid) == 2)
        alive_term = (allies_alive - axis_alive) / float(self.roster_size)
        return _sigmoid(self.config.flag_coefficient * flag_term
                        + self.config.alive_coefficient * alive_term)

    def alive_count(self, team: int) -> int:
        return sum(1 for pid, up in self.alive.items()
                   if up and self.teams.get(pid) == team)


def build_flag_swing_shadow(
    flag_states: Sequence[dict[str, Any]] | None,
    frags: Sequence[dict[str, Any]] | None,
    life_boundaries: Sequence[dict[str, Any]] | None,
    capture_events: Sequence[dict[str, Any]] | None,
    roster: Sequence[dict[str, Any]] | None,
    breaks: Sequence[dict[str, Any]] | None = None,
    config: FlagSwingConfig | None = None,
    *,
    source_available: bool = True,
    temporal_valid: bool = True,
    spawn_ownership: dict[int, int] | None = None,
) -> dict[str, Any]:
    """Per-event swing timeline, per-player attributed swing, break ranking.

    ``capture_events`` rows are per-credit rows (half, game_time or
    event_time ordering, flag_name, team, player_id) used to split a cap's
    swing across its credited cappers.  ``breaks`` rows (half, game_time,
    player_id, flag_index) are priced counterfactually.  Duel difficulty:
    each frag's swing is also reported with the killer's man-advantage at
    the kill, the Tier 3 economy analog.

    ``spawn_ownership`` (flag_index -> 1/2) seeds each half's starting
    ownership for flags whose authored spawn owner was reconstructed from
    HUD recordings -- see
    handover/FLAG_OWNERSHIP_ANALYTICS_HANDOVER_20260908.md. Collection
    records these flags' initial state as neutral (engine ownership is not
    yet readable at match-context-available), and an uncontested flag then
    never emits a correcting transition, so without this seed the flag
    silently undercounts its holder for the whole half. Real transitions
    from ``flag_states`` still override the seed the moment they arrive;
    this only fills the gap before the first one.
    """
    config = config or FlagSwingConfig()
    config.validate()
    envelope: dict[str, Any] = {
        "definition": "flag_swing_v1",
        "definition_version": 1,
        "parameters": {**asdict(config), "perspective": "allies",
                       "clock": "producer_game_time"},
        "status": "available",
        "calibration": config.calibration,
        "visibility": "private_shadow_only",
        "writes": False,
        "rating_effect": False,
        "caveats": [
            "Coefficients are uncalibrated priors until fitted on engine "
            "team_score labels; magnitudes are comparative, not absolute.",
        ],
        "timeline": [],
        "players": [],
        "break_reel": [],
    }
    if not temporal_valid:
        envelope["status"] = "timed_metrics_suppressed"
        return envelope
    if (not source_available or flag_states is None or frags is None
            or life_boundaries is None or roster is None):
        envelope["status"] = "unavailable"
        envelope["caveats"].append(
            "Flag states, producer frags, life boundaries, and a roster "
            "are all required.")
        return envelope

    teams = {int(p["player_id"]): p.get("team") for p in roster
             if p.get("team") in (1, 2)}
    if not teams:
        envelope["status"] = "unavailable"
        return envelope
    spawn_ownership = spawn_ownership or {}
    flag_ids = ({ _int_or_none(r.get("flag_index"))
                 for r in flag_states } | set(spawn_ownership)) - {None}
    if spawn_ownership:
        envelope["caveats"].append(
            "Initial ownership for flag_index "
            f"{sorted(spawn_ownership)} is reconstructed from HUD "
            "recordings (authored spawn owner), not observed from "
            "collection -- see "
            "handover/FLAG_OWNERSHIP_ANALYTICS_HANDOVER_20260908.md. "
            "Real transitions still override it as soon as one arrives.")
        envelope["reconstructed_initial_flags"] = sorted(spawn_ownership)

    events: list[tuple[float, int, int, str, dict[str, Any]]] = []
    for order, row in enumerate(flag_states):
        half, at = _int_or_none(row.get("half")), _game_time(row)
        if half and at is not None:
            events.append((at, order, half, "flag", row))
    for order, row in enumerate(frags):
        half, at = _int_or_none(row.get("half")), _game_time(row)
        if half and at is not None:
            events.append((at, order, half, "frag", row))
    for order, row in enumerate(life_boundaries or []):
        half, at = _int_or_none(row.get("half")), _game_time(row)
        kind = str(row.get("boundary_kind") or "")
        if half and at is not None and kind == "start":
            events.append((at, order, half, "spawn", row))
    events.sort(key=lambda item: (item[2], item[0], item[1]))

    caps_by_key: dict[tuple[int, Any, Any], list[int]] = {}
    for row in capture_events or []:
        key = (_int_or_none(row.get("half")), row.get("flag_name"),
               row.get("event_time"))
        pid = _int_or_none(row.get("player_id"))
        if pid is not None:
            caps_by_key.setdefault(key, []).append(pid)

    swing_by_player: dict[int, float] = {pid: 0.0 for pid in teams}
    frag_count: dict[int, int] = {pid: 0 for pid in teams}
    timeline: list[dict[str, Any]] = []
    state: _HalfState | None = None
    current_half: int | None = None
    for at, _order, half, kind, row in events:
        if half != current_half:
            current_half = half
            state = _HalfState(len(flag_ids) or 5, len(teams), config,
                                initial_owners=spawn_ownership)
            for pid in teams:
                state.teams[pid] = teams[pid]
                state.alive[pid] = True
        assert state is not None
        before = state.p_allies()
        if kind == "flag":
            flag = _int_or_none(row.get("flag_index"))
            owner = _int_or_none(row.get("owner_team"))
            is_initial_row = bool(row.get("is_initial"))
            reconstructed = flag in spawn_ownership
            if not (is_initial_row and reconstructed):
                # Collection's own is_initial=1 row is near-always a wrong
                # "neutral" for a flag we have a trusted reconstructed
                # spawn owner for (that wrong reading is the defect this
                # seed corrects) -- keep the seed until a REAL transition
                # (is_initial=0) arrives.
                state.owners[flag] = owner if owner in (1, 2) else 0
            delta = state.p_allies() - before
            credited = caps_by_key.get(
                (half, row.get("flag_name"), row.get("event_time")), [])
            share = delta / len(credited) if credited else 0.0
            for pid in credited:
                if pid in swing_by_player:
                    team_sign = 1.0 if teams.get(pid) == 1 else -1.0
                    swing_by_player[pid] += share * team_sign
            if abs(delta) > 1e-9 and not bool(row.get("is_initial")):
                timeline.append({
                    "half": half, "game_time": at, "kind": "flag",
                    "flag_index": flag, "owner": owner,
                    "p_allies_after": round(state.p_allies(), 4),
                    "delta": round(delta, 4),
                })
        elif kind == "frag":
            victim = _int_or_none(row.get("victim_id"))
            killer = _int_or_none(row.get("killer_id"))
            if victim in state.alive:
                killer_team = teams.get(killer)
                advantage = (state.alive_count(killer_team)
                             - state.alive_count(1 if killer_team == 2 else 2)
                             ) if killer_team in (1, 2) else 0
                state.alive[victim] = False
                delta = state.p_allies() - before
                if killer in swing_by_player and killer_team in (1, 2):
                    team_sign = 1.0 if killer_team == 1 else -1.0
                    # Duel difficulty: an even or disadvantaged kill keeps
                    # full weight; each man of existing advantage halves it.
                    weight = 1.0 / (2.0 ** max(advantage, 0))
                    swing_by_player[killer] += delta * team_sign * weight
                    frag_count[killer] += 1
                timeline.append({
                    "half": half, "game_time": at, "kind": "frag",
                    "killer_id": killer, "victim_id": victim,
                    "killer_man_advantage": advantage,
                    "p_allies_after": round(state.p_allies(), 4),
                    "delta": round(delta, 4),
                })
        elif kind == "spawn":
            pid = _int_or_none(row.get("player_id"))
            if pid in state.alive:
                state.alive[pid] = True

    break_reel: list[dict[str, Any]] = []
    if breaks:
        for row in breaks:
            half, at = _int_or_none(row.get("half")), _game_time(row)
            pid = _int_or_none(row.get("player_id"))
            if half is None or at is None:
                continue
            # Counterfactual price: the flag-control delta the denied cap
            # would have produced, from the uncalibrated flag term alone.
            denied = 2.0 * config.flag_coefficient / (
                4.0 * (len(flag_ids) or 5))
            break_reel.append({
                "half": half, "game_time": at, "player_id": pid,
                "flag_index": _int_or_none(row.get("flag_index")),
                "denied_swing": round(denied, 4),
            })
        break_reel.sort(key=lambda b: -b["denied_swing"])

    envelope["timeline"] = timeline
    envelope["players"] = [
        {"player_id": pid, "team": teams[pid],
         "attributed_swing": round(swing_by_player[pid], 4),
         "weighted_frags": frag_count[pid]}
        for pid in sorted(teams)
    ]
    envelope["break_reel"] = break_reel
    return envelope
