#!/usr/bin/env python3
"""Emit per-match scoreboards for lan-web, in the shape its loader consumes.

    python build_match_scoreboard.py            # writes match-scoreboard.json
    python build_match_scoreboard.py --check    # verify only, write nothing

Then, from sites/lan-web:

    python tools/load_match_scoreboard.py <path>/match-scoreboard.json

Why a file and not a direct write: the stats live in `hlstatsx_lan` on the data
server and lan-web connects as `ktp_lan` with no privilege there. This reads the
stats database over SSH and shapes rows; the loader puts them where the endpoint
can read them. The same split the award tables live with.

⛔ The output must NOT be written under the site tree. `StaticFiles` serves
anything below `site_dir` byte for byte, which would be an ungated second door
onto the dataset `stats_published` exists to withhold.

Sources are the operator's precedence, and match `build_awards.PROVENANCE`:

    kills, deaths, headshots, damage   ktp_match_stats, halves 1 and 2
    flags                              hlstats_Events_PlayerActions (337, 338)
    best_streak                        hlstats_Events_Frags, rebuilt from kills
    assists                            hud_player_stats — nothing else has them

Half 0 is `ktp_match_stats`' own match total and is never emitted; the loader
refuses it and the table's CHECK refuses it again.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict

from build_awards import EDITION, Facts, connect, sid, sql

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "match-scoreboard.json")
CAPTURE_ACTIONS = (337, 338)


def fetch(c, match_ids):
    """Every per-half figure the scoreboard needs, keyed (match, half, steam)."""
    ids = ",".join("'%s'" % m for m in sorted(match_ids))
    out = {
        "halves": {},        # (match, half) -> (start, end)
        "map": {},           # match -> map name, dod_ stripped
        "day": {},           # match -> MM-DD
        "stats": {},         # (match, half, steam) -> record row
        "assists": Counter(),
        "flags": Counter(),
        "streak": {},
        "closed": set(),
    }

    for mid, half, mp, start, end in sql(c, """
            SELECT match_id, half, map_name, start_time, end_time
            FROM ktp_matches WHERE match_id IN (%s)""" % ids):
        out["halves"][(mid, int(half))] = (start, end or "2030-01-01 00:00:00")
        out["map"][mid] = mp[4:] if mp.startswith("dod_") else mp
        out["day"].setdefault(mid, start[5:10])

    for mid, half, steam_raw, name, k, d, hs, dmg in sql(c, """
            SELECT s.match_id, s.half, p.steam_id, MAX(p.player_name),
                   SUM(s.kills), SUM(s.deaths), SUM(s.headshots), SUM(s.damage)
            FROM ktp_match_stats s
            JOIN ktp_match_players p
              ON p.match_id = s.match_id AND p.player_id = s.player_id
            WHERE s.half IN (1,2) AND s.match_id IN (%s)
            GROUP BY s.match_id, s.half, p.steam_id""" % ids):
        out["stats"][(mid, int(half), sid(steam_raw))] = {
            "name": name, "kills": int(k or 0), "deaths": int(d or 0),
            "headshots": int(hs or 0), "damage": int(dmg or 0)}

    for mid, half, steam_raw, assists in sql(c, """
            SELECT match_id, half, steam_id, SUM(assists) FROM hud_player_stats
            WHERE is_final = 1 AND half IN (1,2) AND match_id IN (%s)
            GROUP BY match_id, half, steam_id""" % ids):
        out["assists"][(mid, int(half), sid(steam_raw))] = int(assists or 0)

    # PlayerActions has no `half` column, so each capture is placed by its
    # eventTime inside that half's own window from ktp_matches. Coverage is
    # asserted by the caller rather than assumed.
    actions = sql(c, """
        SELECT e.match_id, u.uniqueId, e.eventTime
        FROM hlstats_Events_PlayerActions e
        JOIN hlstats_PlayerUniqueIds u ON u.playerId = e.playerId
        WHERE e.actionId IN (%s) AND e.match_id IN (%s)"""
        % (",".join(str(a) for a in CAPTURE_ACTIONS), ids))
    out["actions_total"] = len(actions)
    placed = 0
    for mid, steam_raw, when in actions:
        for half in (1, 2):
            window = out["halves"].get((mid, half))
            if window and window[0] <= when <= window[1]:
                out["flags"][(mid, half, sid(steam_raw))] += 1
                placed += 1
                break
    out["actions_placed"] = placed

    # A streak cannot survive a death and does not carry across the side swap,
    # so it is built per half from the frag log in insertion order.
    seq = defaultdict(list)
    for mid, half, killer_raw, victim_raw in sql(c, """
            SELECT f.match_id, f.half, ku.uniqueId, vu.uniqueId
            FROM hlstats_Events_Frags f
            JOIN hlstats_PlayerUniqueIds ku ON ku.playerId = f.killerId
            JOIN hlstats_PlayerUniqueIds vu ON vu.playerId = f.victimId
            WHERE f.half IN (1,2) AND f.match_id IN (%s) ORDER BY f.id""" % ids):
        seq[(mid, int(half))].append((sid(killer_raw), sid(victim_raw)))
    for (mid, half), events in seq.items():
        run, best = Counter(), Counter()
        for killer, victim in events:
            if killer != victim:
                run[killer] += 1
                best[killer] = max(best[killer], run[killer])
            run[victim] = 0
        for steam, n in best.items():
            out["streak"][(mid, half, steam)] = n

    for (mid,) in sql(c, """
            SELECT DISTINCT match_id FROM hud_events
            WHERE event = 'ktp_match_end' AND match_id IN (%s)""" % ids):
        out["closed"].add(mid)

    return out


def build(facts, data):
    """The loader's JSON, one entry per curated match."""
    matches, problems = [], []
    for mid in sorted(facts.match_teams):
        clubs = list(facts.match_teams[mid])
        players = []
        for (m, half, steam), rec in sorted(data["stats"].items()):
            if m != mid:
                continue
            club = facts.teams.get(steam)
            if club not in clubs:
                # The loader refuses the whole file on this, so it is reported
                # here with the row that caused it rather than as a load error.
                problems.append("%s: %s is on %r, not one of %s"
                                % (mid, steam, club, clubs))
                continue
            players.append({
                "steam_id": steam,
                "name": facts.names.canon(steam, rec["name"]),
                "team": club,
                "half": half,
                "kills": rec["kills"], "deaths": rec["deaths"],
                "headshots": rec["headshots"], "damage": rec["damage"],
                "flags": data["flags"].get((mid, half, steam), 0),
                "assists": data["assists"].get((mid, half, steam), 0),
                "best_streak": data["streak"].get((mid, half, steam), 0),
            })
        matches.append({
            "match_key": mid,
            "day": data["day"].get(mid),
            "map": data["map"].get(mid),
            "teams": clubs,
            "closed": mid in data["closed"],
            "players": players,
        })
    return {"edition": EDITION, "matches": matches}, problems


def summarise(out, data, problems):
    matches = out["matches"]
    rows = sum(len(m["players"]) for m in matches)
    empty = [m["match_key"] for m in matches if not m["players"]]
    unclosed = [m["match_key"] for m in matches if not m["closed"]]
    halves = Counter(p["half"] for m in matches for p in m["players"])
    print("edition %s — %d matches, %d player-half rows" % (out["edition"], len(matches), rows))
    print("  halves present: %s" % dict(sorted(halves.items())))
    print("  captures placed in a half: %d of %d"
          % (data["actions_placed"], data["actions_total"]))
    print("  matches with no scoreboard rows: %s" % (empty or "none"))
    print("  matches flagged not closed: %s" % (unclosed or "none"))
    for p in problems:
        print("  PROBLEM %s" % p)
    biggest = max(matches, key=lambda m: len(m["players"]))
    print("  largest board: %s with %d rows" % (biggest["match_key"], len(biggest["players"])))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="verify and summarise without writing the file")
    args = ap.parse_args()

    facts = Facts()
    c = connect()
    try:
        data = fetch(c, facts.match_teams)
    finally:
        c.close()

    out, problems = build(facts, data)
    summarise(out, data, problems)
    if data["actions_placed"] != data["actions_total"]:
        print("\nrefusing: %d capture(s) fell outside both half windows"
              % (data["actions_total"] - data["actions_placed"]))
        return 1
    if problems:
        print("\nrefusing: the loader would reject this file")
        return 1
    if args.check:
        print("\ncheck only — nothing written")
        return 0
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("\nwrote %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
