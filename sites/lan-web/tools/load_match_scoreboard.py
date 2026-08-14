#!/usr/bin/env python3
"""Load per-match scoreboards into ktp_lan, from a JSON the stats build emits.

    python tools/load_match_scoreboard.py match-scoreboard.json [--dry-run]

Why a file rather than a query: the stats live in hlstatsx_lan on the data
server and lan-web connects as ktp_lan with no privilege there, so the endpoint
cannot reach them. The build already reads that database over SSH; this takes
what it shaped and writes it where lan-web can read it. Same split the award
tables live with, and the reason is the same one recorded in build_awards.py —
writing lan-web's tables next to the stats is how lan_stats_publication ended
up unreadable by the app meant to read it.

Input, written by the build:

    {"edition": "philly-2026",
     "matches": [
       {"match_key": "1785715972-KTP1", "day": "08-02", "map": "railroad2",
        "teams": ["icyHOT", "North Atlantic Treaty Org"], "closed": false,
        "players": [
          {"steam_id": "0:10230748", "name": "hildebrand", "team": "icyHOT",
           "half": 1, "kills": 20, "deaths": 11, "headshots": 4, "damage": 3110,
           "flags": 2, "assists": 3, "best_streak": 5}]}]}

One row per player per half. Sources are the operator's rule, not this script's
choice — HLStatsX first, HUD only where HLStatsX has no equivalent:

    kills, deaths, headshots, damage   ktp_match_stats, halves 1 and 2
    flags                              hlstats_Events_PlayerActions (337, 338)
    best_streak                        hlstats_Events_Frags, rebuilt from kills
    assists                            hud_player_stats — nothing else has them

⚠️ HALF 0 IS THE MATCH TOTAL. Emitting it doubles every figure the endpoint
sums, so it is refused here and the table's CHECK refuses it again.

Delete-then-insert per match, so a reload is a full replacement and a player
dropped from the build does not linger."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402

COUNTERS = ("kills", "deaths", "headshots", "damage", "flags", "assists",
            "best_streak")


def _int(v) -> int:
    return int(v or 0)


def rows_of(m: dict) -> list[tuple]:
    """One match's player-half rows, or ValueError naming what is wrong.

    Validated before anything is written: a half the table would refuse, or a
    team the match does not field, is a build defect and a partial load would
    leave the board quietly wrong rather than visibly missing."""
    key = m["match_key"]
    teams = list(m.get("teams") or [])
    out = []
    for p in m.get("players") or []:
        half = _int(p.get("half"))
        if half not in (1, 2):
            raise ValueError(f"{key}: half {half!r} — halves 1 and 2 only, "
                             "half 0 is the match total")
        team = str(p.get("team") or "")
        if teams and team not in teams:
            raise ValueError(f"{key}: player on {team!r}, which is not one of {teams}")
        out.append((key, half, str(p["steam_id"]), str(p.get("name") or "")[:96],
                    team[:96], *(_int(p.get(c)) for c in COUNTERS)))
    return out


def load(data: dict, dry_run: bool = False) -> tuple[int, int]:
    edition = data.get("edition") or ""
    if not edition:
        raise ValueError("no edition in that file")
    matches = data.get("matches") or []
    if not matches:
        raise ValueError("no matches in that file")

    prepared = [(m, rows_of(m)) for m in matches]
    if dry_run:
        return len(prepared), sum(len(r) for _, r in prepared)

    written = 0
    with db.get_conn() as conn, conn.cursor() as cur:
        for m, rows in prepared:
            teams = list(m.get("teams") or ["", ""])
            cur.execute(
                "INSERT INTO lan_matches "
                "(match_key, edition, day, map_name, team_a, team_b, closed) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE "
                "edition=VALUES(edition), day=VALUES(day), map_name=VALUES(map_name), "
                "team_a=VALUES(team_a), team_b=VALUES(team_b), closed=VALUES(closed)",
                (m["match_key"], edition, m.get("day"), m.get("map"),
                 teams[0], teams[1], 0 if m.get("closed") is False else 1),
            )
            cur.execute("DELETE FROM lan_match_scoreboard WHERE match_key=%s",
                        (m["match_key"],))
            for row in rows:
                cur.execute(
                    "INSERT INTO lan_match_scoreboard "
                    "(match_key, half, steam_id, player_name, team, "
                    " kills, deaths, headshots, damage, flags, assists, best_streak) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", row)
            written += len(rows)
    return len(prepared), written


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        return print(__doc__) or 2
    dry = "--dry-run" in sys.argv
    data = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    try:
        matches, rows = load(data, dry)
    except (KeyError, ValueError) as e:
        return print(f"refused: {e}") or 1
    print(f"{'would load' if dry else 'loaded'} {matches} matches, {rows} player-half rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
