"""Swap the in-game alias for the canonical website alias on a match report.

A player may join a match under any name -- clan tags change, people rename
mid-season -- while being the same KTP player on the same team. The website
knows one canonical alias per player (`ktp.player.alias`), keyed by
`ktp.player_steam.steam_id64`; a report knows the name typed into the game
plus the player's `steam_id`. This module joins the two.

The join is exact, not fuzzy. `steam_id` on a report row is already in
hlstatsx's `auth:account` form, which is what `steam64_to_hlstats` produces
from the website's 64-bit id, so a player either matches or does not. An
unmatched player keeps the name they played under -- never blank, never
guessed.

Applied at sync time (report_sync), not generation time, so the internal
report keeps `player_name_at_match` as the historical fact of what was typed,
and a later alias change is picked up by the next sync without regenerating
anything.
"""
from __future__ import annotations

from typing import Any, Callable

STEAM64_BASE = 76561197960265728

# Name fields that sit beside a player_id, so the id decides the swap.
ID_NAME_KEYS = ("player_name_at_match", "name")
# Name fields that never carry an id -- duel matrix cells and kill-path
# endpoints. The only key available is the in-game name itself, matched
# against this match's own roster.
BARE_NAME_KEYS = ("victim_name_at_match", "killer_name", "victim_name")


def steam64_to_hlstats(steam_id64: Any) -> str | None:
    """76561198000000000 -> '0:20000136'. None when unparseable."""
    try:
        n = int(steam_id64) - STEAM64_BASE
    except (TypeError, ValueError):
        return None
    if n < 0:
        return None
    return f"{n % 2}:{n // 2}"


def build_alias_index(players: list[dict], player_steam: list[dict]) -> dict[str, str]:
    """hlstatsx steam id -> canonical website alias.

    Former steam ids are kept deliberately: a match played on an account the
    player has since retired still belongs to that player. No steam id in the
    live data maps to two players, so including them cannot create ambiguity.
    """
    alias_of = {p["id"]: p.get("alias") for p in players}
    index: dict[str, str] = {}
    for row in player_steam:
        key = steam64_to_hlstats(row.get("steam_id64"))
        alias = alias_of.get(row.get("player_id"))
        if key and alias and str(alias).strip():
            index[key] = str(alias)
    return index


def fetch_alias_index(fetch: Callable[[str], list[dict]]) -> dict[str, str]:
    """Build the index from PostgREST. `fetch` is report_sync's supabase_all."""
    return build_alias_index(
        fetch("/rest/v1/player?select=id,alias"),
        fetch("/rest/v1/player_steam?select=player_id,steam_id64"),
    )


def _roster_maps(report: dict, alias_index: dict[str, str]):
    by_pid: dict[Any, str] = {}
    by_name: dict[str, str] = {}
    ambiguous: set[str] = set()
    for row in report.get("players") or []:
        alias = alias_index.get(str(row.get("steam_id")))
        if not alias:
            continue
        by_pid[row.get("player_id")] = alias
        played_as = row.get("player_name_at_match")
        if played_as is None:
            continue
        played_as = str(played_as)
        # Two players under one name in a single match: the name alone can no
        # longer identify either of them, so refuse it rather than guess.
        if played_as in by_name and by_name[played_as] != alias:
            ambiguous.add(played_as)
        by_name[played_as] = alias
    for name in ambiguous:
        by_name.pop(name, None)
    return by_pid, by_name, ambiguous


def apply_aliases(report: dict, alias_index: dict[str, str]) -> dict[str, Any]:
    """Rewrite every display name in `report` in place. Returns a summary."""
    by_pid, by_name, ambiguous = _roster_maps(report, alias_index)
    roster = report.get("players") or []
    stats = {
        "roster": len(roster),
        "resolved": len(by_pid),
        "unresolved": [str(r.get("player_name_at_match")) for r in roster
                       if r.get("player_id") not in by_pid],
        "ambiguous_names": sorted(ambiguous),
        "rewritten": 0,
    }
    if not by_pid:
        return stats

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, dict):
            return
        has_id = "player_id" in node
        for key in ID_NAME_KEYS:
            if key not in node:
                continue
            # The row's own id names the row's own player. Without one, fall
            # back to the roster name -- an exact match, so a non-player field
            # would have to equal a roster alias verbatim to be touched.
            alias = by_pid.get(node.get("player_id")) if has_id else None
            if alias is None:
                alias = by_name.get(str(node.get(key)))
            if alias and node[key] != alias:
                node[key] = alias
                stats["rewritten"] += 1
        for key in BARE_NAME_KEYS:
            if key not in node:
                continue
            alias = by_name.get(str(node.get(key)))
            if alias and node[key] != alias:
                node[key] = alias
                stats["rewritten"] += 1
        for value in node.values():
            visit(value)

    visit(report)
    return stats
