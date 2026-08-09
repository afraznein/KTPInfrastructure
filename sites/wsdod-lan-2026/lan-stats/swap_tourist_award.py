#!/usr/bin/env python3
"""Replace "No Cap For You" with "Difficulty: Tourist".

No Cap For You awarded the most enemy captures broken up in a single match, and
the stat has no resolution at that granularity: the ceiling is 4 and EIGHT
players reached it, so the award had no winner. It also duplicated Party Pooper,
which awards the same stat across the weekend and separates people cleanly
(20 / 16 / 14 / 12 / 12).

Difficulty: Tourist is the best K/D in a single match with a 30-kill floor —
the floor is what stops a 3-0 cameo taking it. Measured spread on this dataset:
5.15 / 3.60 / 2.78 / 2.45 / 2.27, no ties.

Unlike every other single_match award, this one is computed from data tracked in
this repo rather than by the MySQL-backed script that never landed, so it can
actually be regenerated. Sources: ktp_match_stats.tsv (kills/deaths per player
per match per half), captures-placed.json (match_id -> map, 56/56 coverage),
match-teams.json (the two clubs), season-board.json (club per player).

⚠️ Run order matters. This adds an award with no `rank` fields; run whatever
assigns shared ranks AFTER this, so the new award gets them too, then re-embed
with build_ballots.py (PYTHONHASHSEED=0 — it is hash-order dependent).

    python swap_tourist_award.py           # swap the award
    python swap_tourist_award.py --check   # exit 1 if stale
"""
import collections
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
AWARDS = os.path.join(HERE, "awards.json")
PAGE = os.path.normpath(os.path.join(HERE, "..", "design", "prototype.html"))
OLD_SLUG, NEW_SLUG = "no-cap", "tourist"
MIN_KILLS = 30


def load(name):
    return json.load(open(os.path.join(HERE, name), encoding="utf-8"))


def build():
    scope = set(load("match-teams.json"))
    teams_of_match = load("match-teams.json")
    board = load("season-board.json")["views"]["weekend"]["players"]
    club = {r["steam_id"]: r["team"] for r in board}
    full = {r["steam_id"]: r["name"] for r in board}

    m = re.search(r'<script id="lanboard-data" type="application/json">(.*?)</script>',
                  open(PAGE, encoding="utf-8").read(), re.S)
    if not m:
        sys.exit("lanboard-data block not found — run inject_season_board.py first")
    dn = {p["n"]: p["dn"] for p in json.loads(m.group(1))["views"]["weekend"]["players"]}

    uid = {}
    for line in open(os.path.join(HERE, "hlstats_PlayerUniqueIds.tsv"), encoding="utf-8"):
        p = line.rstrip("\n").split("\t")
        if len(p) >= 2:
            uid[p[0]] = p[1]

    # match_id -> map, from the capture stream; every event carries both
    maps = {}
    for e in load("captures-placed.json"):
        if e.get("match_id") and e.get("map"):
            maps.setdefault(e["match_id"], e["map"])
    missing = scope - set(maps)
    if missing:
        sys.exit(f"no map resolved for {len(missing)} matches: {sorted(missing)[:3]}")

    kills, deaths = collections.Counter(), collections.Counter()
    for line in open(os.path.join(HERE, "ktp_match_stats.tsv"), encoding="utf-8"):
        r = line.rstrip("\n").split("\t")
        if len(r) < 11 or r[1] not in scope or r[3] == "0":   # half 0 is the match total
            continue
        sid = uid.get(r[2])
        if not sid:
            continue
        kills[(sid, r[1])] += int(r[4])
        deaths[(sid, r[1])] += int(r[5])

    runs = []
    for key, k in kills.items():
        d = deaths[key]
        if k >= MIN_KILLS and d:
            runs.append((k / d, k, d, key))
    runs.sort(reverse=True)

    # one entry per player: a player's two good matches should not take two slots
    rows, seen = [], set()
    for ratio, k, d, (sid, mid) in runs:
        if sid in seen:
            continue
        seen.add(sid)
        mine = club.get(sid, "?")
        pair = teams_of_match.get(mid, [])
        opp = next((t for t in pair if t != mine), "?")
        day = datetime.datetime.utcfromtimestamp(int(mid.split("-", 1)[0]))
        face = "Sat" if day.strftime("%Y-%m-%d") == "2026-08-01" else "Sun"
        mp = maps[mid][4:] if maps[mid].startswith("dod_") else maps[mid]
        rows.append({"who": dn.get(full.get(sid, ""), full.get(sid, sid)),
                     "value": f"{ratio:.2f} K/D ({k}-{d})",
                     "where": f"{mp} · {face} · v {opp}"})
        if len(rows) == 5:
            break

    return {
        "slug": NEW_SLUG,
        "title": "Difficulty: Tourist",
        "blurb": f"Best K/D in a single match, {MIN_KILLS}-kill minimum. Match record.",
        "status": "proposed",
        "top": rows,
        "leader": dict(rows[0]),
        "tied": None,
    }


def main() -> int:
    awards = json.load(open(AWARDS, encoding="utf-8"))
    sm = awards["single_match"]
    idx = next((i for i, a in enumerate(sm) if a["slug"] in (OLD_SLUG, NEW_SLUG)), None)
    if idx is None:
        sys.exit(f"neither {OLD_SLUG!r} nor {NEW_SLUG!r} found in single_match")

    new = build()
    # keep any rank fields a later pass added, so this stays idempotent alongside it
    cur = sm[idx]
    if cur.get("slug") == NEW_SLUG:
        for a, b in zip(cur.get("top", []), new["top"]):
            if "rank" in a and a.get("who") == b.get("who"):
                b["rank"] = a["rank"]
        if "rank" in cur.get("leader", {}):
            new["leader"]["rank"] = cur["leader"]["rank"]

    if "--check" in sys.argv:
        if cur != new:
            print("Difficulty: Tourist is STALE — re-run swap_tourist_award.py")
            return 1
        print("Difficulty: Tourist is current")
        return 0

    if cur == new:
        print("no change")
        return 0
    was = cur.get("title", "?")
    sm[idx] = new
    json.dump(awards, open(AWARDS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"replaced {was!r} with {new['title']!r}:")
    for r in new["top"]:
        print(f"  {r['who']:<14} {r['value']:<20} {r['where']}")
    print("\nnow: re-run the shared-rank pass, then "
          "PYTHONHASHSEED=0 python build_ballots.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
