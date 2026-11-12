"""outnumbered_kill_v1: enemy kills made while the killer's side was down by two or more.

Definition (docs/proposals/streaks-and-side-splits.md section 2, ruled 2026-10-05
as its own stat, published apart from fight_clutch_v1 and never summed with it):
- counts: hlstats_Events_Frags rows with the player as killer, the same frags the
  box score and kill_streak_v1 count; teamkills never count;
- the state is read just before the kill instant: a boundary at exactly that
  game_time has not happened yet, so the victim is still alive;
- sides come from the life ledger, per half: teammates are players on the
  killer's side that half, enemies the other side;
- the killer is always counted on their own side, alive or not, so a grenade
  landing after the thrower's death is judged as if they were still standing;
- outnumbered means living enemies minus (living teammates + the killer) is at
  least OUTNUMBERED_MARGIN;
- a kill is censored, never guessed, when the killer's side is unknown or a
  player present in the half must have been alive but has no boundary yet
  (their first boundary that half is an `end` after the kill). A player whose
  first boundary is a later `start` had not spawned and is simply not alive;
- a frag with no producer clock and no recoverable victim death cannot be
  placed in time and is left out, marking its row `lower_bound`.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence

from scripts.life_ledger import (
    SIDE_NAMES, as_int, boundaries_by_player_half, match_frags, place_frags,
    resolve_sides)

DEFINITION = "outnumbered_kill_v1"
DEFINITION_VERSION = 1
OUTNUMBERED_MARGIN = 2

PARAMETERS = {
    "clock": "producer_game_time",
    "state": "just_before_kill_instant",
    "margin": OUTNUMBERED_MARGIN,
    "killer_counted": "always",
    "unknown_liveness": "kill_censored",
}

COVERAGE_KEYS = ("kills", "evaluated", "censored", "unordered")


def unavailable(*flags: str) -> dict[str, Any]:
    return {
        "definition": DEFINITION, "definition_version": DEFINITION_VERSION,
        "parameters": dict(PARAMETERS),
        "status": "unavailable", "flags": sorted(set(flags)),
        "coverage": {k: 0 for k in COVERAGE_KEYS},
        "rows": [], "players": [],
    }


def _state_before(boundaries: Sequence[Mapping[str, Any]], at: float) -> bool | None:
    """Alive just before `at`; None when a player present in the half must have
    been alive but has no boundary yet."""
    state: bool | None = None
    for b in boundaries:
        if b["at"] >= at:
            if state is None:
                return None if b["kind"] == "end" else False
            break
        state = b["kind"] == "start"
    return state


def build_outnumbered_kills(
    frag_context: Iterable[Mapping[str, Any]] | None,
    life_boundaries: Iterable[Mapping[str, Any]] | None,
    players: Sequence[Mapping[str, Any]],
    *,
    match_id: str | None,
    source_available: bool,
) -> dict[str, Any]:
    if not source_available or frag_context is None or life_boundaries is None:
        return unavailable("source-not-captured")
    boundaries = list(life_boundaries)
    if not boundaries:
        return unavailable("no-life-boundaries")
    frags = match_frags(frag_context, match_id)
    if frags and all(f.get("game_time") is None for f in frags):
        return unavailable("no-frag-clock")

    placed = place_frags(frags, boundaries, match_id=match_id)
    ledger = boundaries_by_player_half(boundaries)
    sides = resolve_sides(boundaries)
    roster = {as_int(p.get("player_id")): p for p in players}
    present: dict[int, list[int]] = defaultdict(list)
    for half, pid in ledger:
        present[half].append(pid)

    counts: dict[tuple[int, int], dict[str, int]] = defaultdict(
        lambda: {"kills": 0, "outnumbered_kills": 0, "censored": 0, "unordered": 0})
    coverage = {k: 0 for k in COVERAGE_KEYS}
    margins: dict[int, int] = defaultdict(int)
    for frag in placed:
        killer, half = frag["killer_id"], frag["half"]
        if killer is None or half is None or killer not in roster:
            continue
        row = counts[(half, killer)]
        row["kills"] += 1
        coverage["kills"] += 1
        if frag["at"] is None:
            row["unordered"] += 1
            coverage["unordered"] += 1
            continue
        side = sides.get((half, killer))
        alive: dict[str, int] = {"own": 0, "enemy": 0}
        known = side is not None
        for pid in present.get(half, ()) if known else ():
            if pid == killer:
                continue
            state = _state_before(ledger[(half, pid)], frag["at"])
            if state is None:
                known = False
                break
            if not state:
                continue
            other = sides.get((half, pid))
            if other is None:
                known = False
                break
            alive["own" if other == side else "enemy"] += 1
        if not known:
            row["censored"] += 1
            coverage["censored"] += 1
            continue
        coverage["evaluated"] += 1
        margin = alive["enemy"] - (alive["own"] + 1)
        margins[margin] += 1
        if margin >= OUTNUMBERED_MARGIN:
            row["outnumbered_kills"] += 1

    flags: set[str] = set()
    if coverage["unordered"]:
        flags.add("unordered-frags")
    if coverage["censored"]:
        flags.add("censored-kills")
    rows = []
    for (half, pid), c in counts.items():
        player = roster[pid]
        rows.append({
            "player_id": pid,
            "player_name_at_match": player.get("player_name_at_match"),
            "team": as_int(player.get("team")),
            "half": half,
            "side": sides.get((half, pid)),
            "kills": c["kills"],
            "outnumbered_kills": c["outnumbered_kills"],
            "lower_bound": bool(c["censored"] or c["unordered"]),
        })
    rows.sort(key=lambda r: (r["half"], r["team"] or 0, -r["outnumbered_kills"],
                             str(r["player_name_at_match"])))
    return {
        "definition": DEFINITION, "definition_version": DEFINITION_VERSION,
        "parameters": dict(PARAMETERS),
        "status": "available", "flags": sorted(flags), "coverage": coverage,
        "margin_histogram": {str(k): v for k, v in sorted(margins.items())},
        "rows": rows, "players": _match_rows(rows),
    }


def _match_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_player: dict[int, dict[str, Any]] = {}
    for r in rows:
        p = by_player.setdefault(r["player_id"], {
            "player_id": r["player_id"],
            "player_name_at_match": r["player_name_at_match"],
            "team": r["team"], "kills": 0, "outnumbered_kills": 0,
            "by_side": {name: None for name in SIDE_NAMES.values()},
            "lower_bound": False,
        })
        p["kills"] += r["kills"]
        p["outnumbered_kills"] += r["outnumbered_kills"]
        p["lower_bound"] = p["lower_bound"] or r["lower_bound"]
        if r["side"] in p["by_side"]:
            p["by_side"][r["side"]] = (p["by_side"][r["side"]] or 0) + r["outnumbered_kills"]
    return sorted(by_player.values(),
                  key=lambda p: (p["team"] or 0, -p["outnumbered_kills"],
                                 str(p["player_name_at_match"])))
