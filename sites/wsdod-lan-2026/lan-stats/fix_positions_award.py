#!/usr/bin/env python3
"""Recompute "Best six by position" from the per-day team-formula KTPR.

The decided awards came from a MySQL-backed script that never landed in the
repo, and this one quoted the legacy additive KTPR the day boards used before
2026-08-09. Recomputed here because its inputs ARE tracked (season-board.json),
unlike the single-match awards, whose corrections live in
apply_award_decisions.py.

Scored on the WEEKEND view (2026-08-09). It previously ranked (player, day)
pairs across the two day views, which meant a Saturday rating competing against
a Sunday one — two different sets of medians, so the numbers were formally
non-comparable and the card had to stamp each row Sat or Sun to admit it. One
view, one baseline, one rating per player fixes that.

⚠️ It also changes what the award measures: a player's best DAY became their
whole weekend, so a big day off a short sample no longer outranks two solid
ones. bR0M (16 halves) and nicholson lost their slots to Seanality and TillJim
under exactly that effect.

⚠️ The Heavy #1 / Heavy #2 ORDER rests on 1.149 vs 1.148, and season-board.json
stores ktpr already rounded to three decimals — so the label could flip on a
recompute. Only the label: both hold a slot either way, and every slot's
membership boundary is 0.007 or wider.

    python fix_positions_award.py           # rewrite the award
    python fix_positions_award.py --check   # exit 1 if it is stale
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
AWARDS = os.path.join(HERE, "awards.json")
BOARD = os.path.join(HERE, "season-board.json")
PAGE = os.path.normpath(os.path.join(HERE, "..", "design", "prototype.html"))

# roster shape, in the order the page lists them
SLOTS = (("Rifle #1", "Rifle"), ("Heavy #1", "Heavy"), ("3rd", "3rd"),
         ("Rifle #2", "Rifle"), ("Heavy #2", "Heavy"), ("Sniper", "Sniper"))


def build(existing):
    board = json.load(open(BOARD, encoding="utf-8"))
    m = re.search(r'<script id="lanboard-data" type="application/json">(.*?)</script>',
                  open(PAGE, encoding="utf-8").read(), re.S)
    if not m:
        sys.exit("lanboard-data block not found — run inject_season_board.py first")
    # short display name, from the same block every other name on the page uses
    dn = {p["n"]: p["dn"] for p in json.loads(m.group(1))["views"]["weekend"]["players"]}

    ranked = {}
    for r in board["views"]["weekend"]["players"]:
        ranked.setdefault(r["position"], []).append(
            (r["ktpr"], r["name"], r["team"]))
    for pos in ranked:
        ranked[pos].sort(reverse=True)

    rows, used = [], []
    for label, pos in SLOTS:
        pool = [x for x in ranked.get(pos, []) if x[1] not in used]
        if not pool:
            sys.exit(f"no candidate left for {label}")
        val, full, team = pool[0]
        used.append(full)
        rows.append({"role": label, "who": dn.get(full, full),
                     "value": f"{val:.3f} KTPR", "where": team})

    # Six slots, six people. The weekend view holds one row per player and a
    # player has one position, so this cannot fire today — it is here because
    # the version that ranked (player, day) pairs COULD hand one person both
    # Rifle slots, and nothing but the data shape stops that coming back.
    if len(set(r["who"] for r in rows)) != len(SLOTS):
        sys.exit(f"a player took two slots: {[r['who'] for r in rows]}")
    return dict(existing, rows=rows)


def main() -> int:
    awards = json.load(open(AWARDS, encoding="utf-8"))
    if "positions" not in awards:
        sys.exit("no 'positions' award in awards.json")
    new = build(awards["positions"])

    if "--check" in sys.argv:
        if awards["positions"] != new:
            print("Best six by position is STALE — re-run fix_positions_award.py")
            return 1
        print("Best six by position is current")
        return 0

    if awards["positions"] == new:
        print("no change")
        return 0
    old = {r["role"]: r for r in awards["positions"]["rows"]}
    awards["positions"] = new
    json.dump(awards, open(AWARDS, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("rewrote Best six by position:")
    for r in new["rows"]:
        was = old.get(r["role"], {})
        flag = "" if was.get("who") == r["who"] else f"   (was {was.get('who', '?')})"
        print(f"  {r['role']:<9} {r['who']:<14} {r['value']:<12} {r['where']}{flag}")
    print("\nnow re-embed it into the page:  python build_ballots.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
