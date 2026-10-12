"""Canonical report team per player, for rosters that change between halves.

`ktp_match_players.team` is the engine side a player held in the LAST half
they appeared in -- the daemon overwrites the row each half. Sides swap at
half time, so a player who leaves at the break and is replaced keeps his
half-1 side, which in the second half belongs to the OPPONENT. He is then
filed on the enemy's roster, his kills land in their totals, and the teams
come out 7-vs-6.

Measured on 1789952635-NY1 (2026-09-20, official): Las1K64 played half 1 for
`[ o_o ]` on side 2, subbed out at half, and the report put him on `uD`
alongside six opponents. Sixteen players across sixteen matches since
2026-08-31 carry the same defect -- every one of them a player who missed the
final half.

The fix reads the side groups out of the life boundaries, which are per-half
and authoritative, and maps each (half, side) onto a canonical team by how
much the two halves' player sets overlap. The final half's sides ARE the
canonical labels, so nothing moves except the players the roster got wrong:
`game_team` remains the side at match end (knowledge/KTPInfrastructure.md).
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def sides_by_half(life_boundaries: Sequence[dict[str, Any]] | None,
                  ) -> dict[int, dict[int, int]]:
    """(half -> player_id -> engine side) from the life feed."""
    out: dict[int, dict[int, int]] = {}
    for row in life_boundaries or []:
        half, pid = _int(row.get("half")), _int(row.get("player_id"))
        team = _int(row.get("team"))
        if half and pid is not None and team in (1, 2):
            out.setdefault(half, {})[pid] = team
    return out


def canonical_teams(life_boundaries: Sequence[dict[str, Any]] | None,
                    ) -> dict[int, int]:
    """player_id -> canonical team, labelled by the final half's sides.

    Empty when the life feed is missing or only one half is present: with
    nothing to compare, the roster's own team is as good as it gets and the
    caller keeps it.
    """
    sides = sides_by_half(life_boundaries)
    halves = sorted(sides)
    if len(halves) < 2:
        return {}
    final = halves[-1]
    canonical = dict(sides[final])
    for half in reversed(halves[:-1]):
        # Which of the final half's sides does each side of THIS half
        # continue? Whichever shares more players. A swap is the norm; a
        # half played on the same sides (a replayed half) works too.
        same = sum(1 for pid, side in sides[half].items()
                   if canonical.get(pid) == side)
        swapped = sum(1 for pid, side in sides[half].items()
                      if canonical.get(pid) == (2 if side == 1 else 1))
        if same == 0 and swapped == 0:
            continue  # no overlap at all: nothing to carry, leave them out
        flip = swapped > same
        for pid, side in sides[half].items():
            if pid not in canonical:
                canonical[pid] = (2 if side == 1 else 1) if flip else side
    return canonical


def apply_canonical_teams(players: Sequence[dict[str, Any]],
                          life_boundaries: Sequence[dict[str, Any]] | None,
                          ) -> list[dict[str, Any]]:
    """Players with `team` corrected where the roster disagrees with the
    canonical mapping. Rows are copied; `roster_team` records the original
    when it changed, so a reader can see the correction happened."""
    canonical = canonical_teams(life_boundaries)
    out: list[dict[str, Any]] = []
    for player in players:
        row = dict(player)
        pid = _int(row.get("player_id"))
        want = canonical.get(pid) if pid is not None else None
        if want in (1, 2) and _int(row.get("team")) != want:
            row["roster_team"] = _int(row.get("team"))
            row["team"] = want
        out.append(row)
    return out


def restamp_frag_teams(frags: Sequence[dict[str, Any]],
                       players: Sequence[dict[str, Any]],
                       ) -> list[dict[str, Any]]:
    """Frag rows whose `killer_team`/`victim_team` come from the CORRECTED
    roster rather than straight off `ktp_match_players.team`.

    `sql/analytics/frag_timeline_fact.sql` joins both team columns to the roster
    table, so a half-time leaver carries the opponent's label here exactly as he
    did in `players[]` before `apply_canonical_teams`. The visible cost is worse
    than a mislabeled row: both sides of his frags then read the SAME team, so
    `match_timelines._frag_classification` calls every one of them an explicit
    team kill and drops it from the competitive set the trade and multikill
    analyzers run on -- which that function's own comment names a source-contract
    violation, because `hlstats_Events_Frags` already excludes teamkills.

    Takes the corrected `players` rather than the life feed on purpose: one place
    decides a player's team, and this reads its answer.
    """
    return _restamp(frags, players, ("killer", "victim"))


def restamp_damage_teams(damage: Sequence[dict[str, Any]],
                         players: Sequence[dict[str, Any]],
                         ) -> list[dict[str, Any]]:
    """`attacker_team`/`victim_team` from the corrected roster.

    `sql/analytics/damage_timeline_fact.sql` joins the same roster table as the
    frag feeds, so a half-time leaver's hits carry the opponent's label too --
    and `damage_conversion._normalize_damage` drops a row whose two sides read
    the same team as `self_or_team`, so his damage leaves the denominator
    entirely rather than landing on the wrong side of it.
    """
    return _restamp(damage, players, ("attacker", "victim"))


def _restamp(rows: Sequence[dict[str, Any]],
             players: Sequence[dict[str, Any]],
             roles: Sequence[str],
             ) -> list[dict[str, Any]]:
    team_by_pid: dict[int, int] = {}
    for player in players or []:
        pid, team = _int(player.get("player_id")), _int(player.get("team"))
        if pid is not None and team in (1, 2):
            team_by_pid[pid] = team
    out: list[dict[str, Any]] = []
    for source in rows or []:
        row = dict(source)
        for prefix in roles:
            pid = _int(row.get(f"{prefix}_id"))
            want = team_by_pid.get(pid) if pid is not None else None
            if want in (1, 2) and _int(row.get(f"{prefix}_team")) != want:
                row[f"{prefix}_roster_team"] = _int(row.get(f"{prefix}_team"))
                row[f"{prefix}_team"] = want
        out.append(row)
    return out
