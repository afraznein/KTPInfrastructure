#!/usr/bin/env python3
"""Recompute the "Heavy Hitter" award from HLStatsX damage.

The decided awards were built by a MySQL-backed script that never landed in the
repo, so this one award is recomputed here instead. It is the only decided award
whose figure moved when damage came off the HUD, and leaving it would have the
award disagreeing with every damage column on the page.

⚠️ This changes the shortlist, not just the numbers: on HLStatsX damage Savage¬
enters at #2 and baiko drops out. Damage TAKEN awards ("Human Shield", "Don't
Touch Me") stay HUD — the match record has no damage-taken figure at all.

    python fix_damage_award.py           # rewrite the award
    python fix_damage_award.py --check   # exit 1 if it is stale
"""
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
AWARDS = os.path.join(HERE, "awards.json")
STATS = os.path.join(HERE, "lan-stats.json")
PAGE = os.path.normpath(os.path.join(HERE, "..", "design", "prototype.html"))
SLUG = "damage"


def top5():
    """(display name, team, damage) for the five biggest HLStatsX damage totals."""
    stats = json.load(open(STATS, encoding="utf-8"))
    board = json.load(open(os.path.join(HERE, "season-board.json"), encoding="utf-8"))
    page = open(PAGE, encoding="utf-8").read()
    m = re.search(r'<script id="lanboard-data" type="application/json">(.*?)</script>',
                  page, re.S)
    if not m:
        sys.exit("lanboard-data block not found — run inject_season_board.py first")
    # display name + team come from the leaderboard block, so the award answers
    # to the same naming rule as every other name on the page
    by_full = {p["n"]: p for p in json.loads(m.group(1))["players"]}
    sid_name = {r["steam_id"]: r["name"] for r in board["players"]}

    dmg = collections.Counter()
    for day in stats["days"].values():
        for p in day["players"]:
            dmg[p["steam_id"]] += p.get("damage_hlstatsx") or 0

    out = []
    for sid, v in dmg.most_common(5):
        row = by_full.get(sid_name.get(sid, ""), {})
        if not row:
            sys.exit(f"no leaderboard row for {sid_name.get(sid)!r}")
        out.append((row["dn"], row["tm"], v))
    return out


def build(existing):
    # keep each player's recorded alias where the old list already carried one
    alias = {e["who"]: e["as"] for e in existing.get("top", []) if e.get("as")}
    rows = []
    for who, where, val in top5():
        e = {"who": who, "value": f"{val:,}", "where": where}
        if who in alias:
            e["as"] = alias[who]
        rows.append(e)
    out = dict(existing, top=rows, leader=dict(rows[0]))
    return out


def main() -> int:
    awards = json.load(open(AWARDS, encoding="utf-8"))
    idx = next((i for i, a in enumerate(awards["decided"]) if a["slug"] == SLUG), None)
    if idx is None:
        sys.exit(f"no decided award with slug {SLUG!r}")

    new = build(awards["decided"][idx])
    if "--check" in sys.argv:
        if awards["decided"][idx] != new:
            print("Heavy Hitter is STALE — re-run fix_damage_award.py")
            return 1
        print("Heavy Hitter is current")
        return 0

    if awards["decided"][idx] == new:
        print("no change")
        return 0
    awards["decided"][idx] = new
    json.dump(awards, open(AWARDS, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("rewrote Heavy Hitter from HLStatsX damage:")
    for e in new["top"]:
        print(f"  {e['who']:<14} {e['value']:>9}  {e['where']}")
    print("\nnow re-embed it into the page:  python build_ballots.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
