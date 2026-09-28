"""Flag Swing: the Round-Swing analog for DoD halves (Tier 3, definition v1).

Every state-changing event — a flag ownership change or a frag — is priced
as the change it makes to P(win half) for the Allies, from a transparent
logistic baseline over flag control and man advantage. Cap swing is split
across the credited cappers; frag swing goes to the killer; a cap break is
priced counterfactually as the cap swing it denied (the break-reel rank).

The baseline coefficients are UNCALIBRATED PRIORS until fitted on match
history against the authoritative engine team_score labels; every envelope
says so. Private shadow only: no writes, no rating impact.

Rounds end; P(win) does not survive the boundary. When a side caps out, the
engine neutralises every flag at one timestamp and play restarts. Pricing
those rows as ownership changes books the winning team LOSING everything it
just won -- measured 2026-09-22 on 1789931256-NY1: a cap-out worth -0.112
followed three seconds later by +0.381 of phantom swing handed to nobody,
p walked back to 0.500, and 8%% of all timeline movement across the corpus
was this artifact (596 resets since 08-31, 62 of them in officials). A reset
is now a BOUNDARY: no deltas, one `round` row naming the winner, and the
state machine starts the next round clean.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Any

CREDIT_JOIN_TOLERANCE_SECONDS = 3.0

# Per-map coefficients, shrunk toward the league fit, written here from
# scripts/fit_team_score_labels.py output. EMPTY means every map uses the
# league-wide prior, which is exactly the behaviour before this table existed
# -- so an unfitted map, or an unfitted league, changes nothing.
#
# The league plays one map a week, and the maps are not the same game: fitted
# on 54 labelled S10 halves, the flag coefficient comes out 1.76 on harrington,
# 1.51 on lennon5_b1 and 4.52 on thunder2 against a pooled 1.99. Held out over
# halves, pooled wins narrowly on the first two (they overfit their own 16-20
# halves) and per-map wins decisively on thunder2. That is why these are
# SHRUNK per-map values and not independent fits: a map has to earn its
# distance from the league. The alive coefficient is stable across maps
# (0.92-0.96); it is the flag term that is map-specific.
MAP_COEFFICIENTS: dict[str, tuple[float, float]] = {}


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

    def for_map(self, map_name: str | None) -> "FlagSwingConfig":
        """This config, with the map's fitted coefficients if we have them.

        A caller that set coefficients explicitly is overriding the model, so
        its values win over the table -- that is how the fit driver scores one
        vector across every map, and how a test pins a value.
        """
        default = (FlagSwingConfig.flag_coefficient,
                   FlagSwingConfig.alive_coefficient)
        if (self.flag_coefficient, self.alive_coefficient) != default:
            return self
        fitted = MAP_COEFFICIENTS.get(str(map_name or ""))
        if fitted is None:
            return self
        return replace(self, flag_coefficient=fitted[0],
                       alive_coefficient=fitted[1],
                       calibration=f"fitted_per_map:{map_name}")


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


def _round_boundaries(flag_states: Sequence[dict[str, Any]] | None,
                      flag_count: int) -> set[tuple[int, float]]:
    """(half, game_time) of every mass neutralisation -- the engine clearing
    the map between rounds. Three flags going neutral at one timestamp is
    not something play produces; the smallest real map here has five."""
    counts: dict[tuple[int, float], int] = {}
    for row in flag_states or []:
        if bool(row.get("is_initial")) or _int_or_none(row.get("owner_team")) not in (0, None):
            continue
        half, at = _int_or_none(row.get("half")), _game_time(row)
        if half is None or at is None:
            continue
        counts[(half, at)] = counts.get((half, at), 0) + 1
    need = max(3, (flag_count + 1) // 2)
    return {key for key, n in counts.items() if n >= need}


def _wall_seconds(value: Any) -> float | None:
    """A capture/flag event_time as seconds, or None when it is not a
    timestamp (fixtures use opaque strings)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            continue
    return None


def sides_by_half(life_boundaries: Sequence[dict[str, Any]] | None,
                  ) -> dict[int, dict[int, int]]:
    """(half -> player_id -> engine side) from life boundaries.

    Flag ``owner_team`` is the engine side of that half, while the roster's
    ``team`` is the side held in the LAST half played (ktp_match_players is
    overwritten each half). Sides swap between halves, so without this map
    every half-1 flag delta points the wrong way against the alive term.
    """
    sides: dict[int, dict[int, int]] = {}
    for row in life_boundaries or []:
        half, pid = _int_or_none(row.get("half")), _int_or_none(row.get("player_id"))
        team = _int_or_none(row.get("team"))
        if half and pid is not None and team in (1, 2):
            sides.setdefault(half, {})[pid] = team
    return sides


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
        self.capped_out_team: int | None = None

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

    def flags_held(self, team: int) -> int:
        return sum(1 for owner in self.owners.values() if owner == team)


def build_flag_swing_shadow(
    flag_states: Sequence[dict[str, Any]] | None,
    frags: Sequence[dict[str, Any]] | None,
    life_boundaries: Sequence[dict[str, Any]] | None,
    capture_events: Sequence[dict[str, Any]] | None,
    roster: Sequence[dict[str, Any]] | None,
    breaks: Sequence[dict[str, Any]] | None = None,
    config: FlagSwingConfig | None = None,
    *,
    map_name: str | None = None,
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
    config = (config or FlagSwingConfig()).for_map(map_name)
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
            "A cap that ends a round carries `terminal_value` = 1 - P(the "
            "capping side wins the round) just before it: the closing play "
            "realises the outcome rather than shifting it. `delta` stays "
            "the ordinary flag-control move, so a consumer reading only "
            "`delta` is unchanged. How that value splits between the capper "
            "and the team that set the round up is the momentum ledger's "
            "fitted job, not a number chosen here.",
        ],
        "timeline": [],
        "players": [],
        "break_reel": [],
        "capouts": [],
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
    sides = sides_by_half(life_boundaries)
    spawn_ownership = spawn_ownership or {}
    flag_ids = ({ _int_or_none(r.get("flag_index"))
                 for r in flag_states } | set(spawn_ownership)) - {None}
    boundaries = _round_boundaries(flag_states, len(flag_ids) or 5)
    rounds_seen = 0
    if spawn_ownership:
        envelope["caveats"].append(
            "Initial ownership for flag_index "
            f"{sorted(spawn_ownership)} is the map's AUTHORED spawn owner, "
            "read from its BSP (point_default_owner) rather than observed "
            "from collection -- see config/analytics/spawn_ownership.toml. "
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

    # Credits join a flag transition by half + flag + wall clock. The two
    # tables are written by different paths and disagree by a second on real
    # matches (state 21:49:44, credit 21:49:43 on 1789348403-ATL2), so the
    # match is nearest-within-tolerance, not exact; rows whose event_time is
    # not a timestamp (fixtures) still join on equality.
    credits_by_flag: dict[tuple[int | None, Any], list[tuple[Any, int]]] = {}
    for row in capture_events or []:
        pid = _int_or_none(row.get("player_id"))
        if pid is not None:
            credits_by_flag.setdefault(
                (_int_or_none(row.get("half")), row.get("flag_name")), []
            ).append((row.get("event_time"), pid))

    def _credited(half: int, flag_name: Any, event_time: Any) -> list[int]:
        rows = credits_by_flag.get((half, flag_name), [])
        stamp = _wall_seconds(event_time)
        out: list[int] = []
        for at, pid in rows:
            other = _wall_seconds(at)
            if stamp is not None and other is not None:
                if abs(other - stamp) <= CREDIT_JOIN_TOLERANCE_SECONDS:
                    out.append(pid)
            elif at == event_time:
                out.append(pid)
        return out

    swing_by_player: dict[int, float] = {pid: 0.0 for pid in teams}
    frag_count: dict[int, int] = {pid: 0 for pid in teams}
    timeline: list[dict[str, Any]] = []
    capouts: list[dict[str, Any]] = []
    state: _HalfState | None = None
    current_half: int | None = None
    for at, _order, half, kind, row in events:
        if half != current_half:
            current_half = half
            state = _HalfState(len(flag_ids) or 5, len(teams), config,
                                initial_owners=spawn_ownership)
            for pid in teams:
                state.teams[pid] = sides.get(half, {}).get(pid, teams[pid])
                state.alive[pid] = True
        assert state is not None
        before = state.p_allies()
        if kind == "flag" and (half, at) in boundaries:
            # Round boundary, not play: price nothing, name the winner, and
            # start the next round from the reset state.
            held = {side: state.flags_held(side) for side in (1, 2)}
            winner = next((side for side in (1, 2)
                           if held[side] == state.flag_count), None)
            if winner is None:
                winner = (1 if held[1] > held[2] else
                          2 if held[2] > held[1] else None)
            if not any(e.get("kind") == "round" and e.get("half") == half
                       and e.get("game_time") == at for e in timeline):
                rounds_seen += 1
                timeline.append({
                    "half": half, "game_time": at, "kind": "round",
                    "winner": winner,
                    "reason": "capout" if state.flag_count in held.values() else "expired",
                    "allies_flags": held[1], "axis_flags": held[2],
                    "delta": 0.0,
                })
            state.owners[_int_or_none(row.get("flag_index"))] = 0
            continue
        if kind == "flag":
            flag = _int_or_none(row.get("flag_index"))
            owner = _int_or_none(row.get("owner_team"))
            is_initial_row = bool(row.get("is_initial"))
            reconstructed = flag in spawn_ownership
            # A cap that takes a flag from a side holding all but one is the
            # cap-out denial: the loser was one flag from ending the round.
            loser = 2 if owner == 1 else 1 if owner == 2 else None
            capout_denied = bool(
                loser is not None and not is_initial_row
                and state.owners.get(flag) == loser
                and state.flags_held(loser) == state.flag_count - 1)
            capout_completed = False
            if not (is_initial_row and reconstructed):
                # Collection's own is_initial=1 row is near-always a wrong
                # "neutral" for a flag we have a trusted reconstructed
                # spawn owner for (that wrong reading is the defect this
                # seed corrects) -- keep the seed until a REAL transition
                # (is_initial=0) arrives.
                state.owners[flag] = owner if owner in (1, 2) else 0
            # One side now owns every flag. Both consumers below key off this
            # single test: the top-level `capouts` event (deduped per hold, so
            # a fresh round in the same half gets its own event) and the
            # per-cap `capout_completed` flag. They were written out
            # separately eight lines apart and would have drifted the first
            # time either was touched.
            owns_every_flag = bool(
                not is_initial_row and owner in (1, 2)
                and state.flags_held(owner) == state.flag_count)
            if owns_every_flag and state.capped_out_team != owner:
                state.capped_out_team = owner
                capouts.append({"half": half, "game_time": at, "team": owner})
            elif (not is_initial_row and state.capped_out_team is not None
                    and state.flags_held(state.capped_out_team) < state.flag_count):
                state.capped_out_team = None
            delta = state.p_allies() - before
            capout_completed = owns_every_flag
            credited = _credited(half, row.get("flag_name"), row.get("event_time"))
            share = delta / len(credited) if credited else 0.0
            for pid in credited:
                if pid in swing_by_player:
                    team_sign = 1.0 if state.teams.get(pid) == 1 else -1.0
                    swing_by_player[pid] += share * team_sign
            if abs(delta) > 1e-9 and not bool(row.get("is_initial")):
                timeline.append({
                    "half": half, "game_time": at, "kind": "flag",
                    "flag_index": flag, "owner": owner,
                    "credited": [pid for pid in credited if pid in swing_by_player],
                    "allies_flags": state.flags_held(1),
                    "axis_flags": state.flags_held(2),
                    "capout_denied": capout_denied,
                    "capout_completed": capout_completed,
                    # A cap that ends the round does not move P(win) -- it
                    # REALISES it. The closing play is therefore worth the
                    # probability still outstanding, 1 - P(the capping side
                    # wins), which is derived from the model rather than
                    # chosen: closing a round already 95%% won is worth 0.05,
                    # closing a coin-flip is worth 0.50. Consumers that only
                    # read `delta` still see an ordinary flag flip.
                    "terminal_value": (
                        round((1.0 - before) if owner == 1 else before, 4)
                        if capout_completed else None),
                    "p_allies_after": round(state.p_allies(), 4),
                    "delta": round(delta, 4),
                })
        elif kind == "frag":
            victim = _int_or_none(row.get("victim_id"))
            killer = _int_or_none(row.get("killer_id"))
            if victim in state.alive:
                killer_team = state.teams.get(killer)
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

    envelope["rounds"] = rounds_seen
    envelope["timeline"] = timeline
    envelope["capouts"] = capouts
    envelope["players"] = [
        {"player_id": pid, "team": teams[pid],
         "attributed_swing": round(swing_by_player[pid], 4),
         "weighted_frags": frag_count[pid]}
        for pid in sorted(teams)
    ]
    envelope["break_reel"] = break_reel
    return envelope
