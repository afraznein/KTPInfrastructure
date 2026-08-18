"""One match's scoreboard, per player, per half and totalled.

The rows are loaded into ktp_lan by tools/load_match_scoreboard.py — lan-web
has no privilege on hlstatsx_lan, so the stats cannot be queried where they
live. Nothing here writes.

Distinct from stat_awards.py, which ranks the weekend. This is the raw board
one match at a time."""
from __future__ import annotations

from . import db

# HLStatsX decides every stat it can measure and the HUD is a fallback, not a
# tie-break — the HUD counts teamkills, suicides and warmup as kills, so taking
# the larger number would redefine what a kill is. Source of truth for these
# strings is PROVENANCE in wsdod-lan-2026/lan-stats/build_awards.py; the drift
# test in tests/test_match_stats_api.py reads them back out of it.
SOURCES = {
    "kills": "Match record.",
    "deaths": "Match record.",
    "kd": "Match record.",
    "headshots": "Match record.",
    "damage": "Match record.",
    "flags": "HLStatsX — control points and areas captured.",
    "assists": "HUD — the match record has no assists at all.",
    "best_streak": "Frag log — rebuilt from the kills, not read off the HUD.",
}

COUNTERS = ("kills", "deaths", "headshots", "damage", "flags", "assists")

# ⚠️ half IN (1,2), never 0 — half 0 is the match total and summing it with the
# halves doubles every figure. The CHECK constraint in migration 0018 stops it
# being stored; this stops it being read if that is ever relaxed.
ROWS_SQL = (
    "SELECT half, steam_id, player_name, team, kills, deaths, headshots, "
    "       damage, flags, assists, best_streak "
    "FROM lan_match_scoreboard WHERE match_key=%s AND half IN (1,2) "
    "ORDER BY steam_id, half"
)


def match(match_key: str) -> dict | None:
    """The curated tournament entry, or None for a key no match owns."""
    return db.query_one(
        "SELECT match_key, edition, day, map_name, team_a, team_b, closed "
        "FROM lan_matches WHERE match_key=%s",
        (match_key,),
    )


def rows(match_key: str) -> list[dict]:
    return db.query_all(ROWS_SQL, (match_key,))


def kd(kills: int, deaths: int) -> float:
    """Kills per death, or the kill count itself when nobody died — the same
    reading build_stats.py takes, so a K/D here matches the weekend board."""
    return round(kills / deaths if deaths else float(kills), 3)


def _stats(rs: list[dict]) -> dict:
    out = {k: sum(int(r[k] or 0) for r in rs) for k in COUNTERS}
    # Summed streaks would be a number nobody achieved.
    out["best_streak"] = max((int(r["best_streak"] or 0) for r in rs), default=0)
    out["kd"] = kd(out["kills"], out["deaths"])
    return out


def _player(rs: list[dict]) -> dict:
    last = rs[-1]
    return {
        "steam_id": last["steam_id"],
        "who": last["player_name"],
        # The side they finished on. A player who swapped mid-match is rare
        # enough that a second row would read as two players.
        "team": last["team"],
        "total": _stats(rs),
        # An array, so the page reads halves in order rather than guessing which
        # keys a one-half match carries.
        "halves": [dict(_stats([r]), half=int(r["half"])) for r in rs],
    }


def scoreboard(m: dict) -> list[dict]:
    """Both teams' players, the home side first, best fragger first within a
    side. A match with no rows is an empty list — which is not the same answer
    as a match that does not exist."""
    by_player: dict[str, list[dict]] = {}
    for r in rows(m["match_key"]):
        by_player.setdefault(r["steam_id"], []).append(r)
    sides = {m["team_a"]: 0, m["team_b"]: 1}
    return sorted(
        (_player(rs) for rs in by_player.values()),
        # A team the curated entry does not name sorts last rather than
        # disappearing — a scoreboard is the wrong place to hide a row.
        key=lambda p: (sides.get(p["team"], 2), -p["total"]["kills"], p["who"]),
    )


def header(m: dict, players: list[dict]) -> dict:
    """What the match is, and how much of it was recorded.

    `halves` is what the scoreboard actually holds: a match abandoned after one
    half says [1], and the page can say so instead of printing a blank column."""
    return {
        "key": m["match_key"],
        "edition": m["edition"],
        "day": m["day"],
        "map": m["map_name"],
        "teams": [m["team_a"], m["team_b"]],
        "halves": sorted({h["half"] for p in players for h in p["halves"]}),
        "closed": bool(m["closed"]),
    }
