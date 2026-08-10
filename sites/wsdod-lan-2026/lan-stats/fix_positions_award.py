#!/usr/bin/env python3
"""Recompute "Best six by position" from the per-day team-formula KTPR.

The decided awards came from a MySQL-backed script that never landed in the
repo, and this one quoted the legacy additive KTPR the day boards used before
2026-08-09. Recomputed here because its inputs ARE tracked (season-board.json),
unlike the single-match awards, whose corrections live in
apply_award_decisions.py.

⚠️ Each slot must go to a DIFFERENT player. A player has a Saturday and a Sunday
rating, so ranking (player, day) pairs alone can hand one person both Rifle
slots. It does not happen on this dataset, but it is one good day away from
happening and a correct-by-luck award is not correct.
The dedupe keys on steam_id, NOT name: 18 of 61 players played the two days
under different names, so a name-keyed guard reads them as two people and the
protection above silently does not apply to them.

⚠️ The award compares a Saturday number against a Sunday one. Per-day baselines
make those formally non-comparable — a caveat inherited from the old award, and
sharper now that every view carries its own medians.

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

DAYS = (("08-01", "Sat"), ("08-02", "Sun"))
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
    for key, face in DAYS:
        for r in board["views"][key]["players"]:
            ranked.setdefault(r["position"], []).append(
                (r["ktpr"], r["name"], r["team"], face, r["steam_id"]))
    for pos in ranked:
        ranked[pos].sort(reverse=True)

    taken, rows = set(), []
    for label, pos in SLOTS:
        pick = next((x for x in ranked.get(pos, []) if x[4] not in taken), None)
        if pick is None:
            sys.exit(f"no candidate left for {label}")
        val, full, team, face, sid = pick
        taken.add(sid)
        rows.append({"role": label, "who": dn.get(full, full),
                     "value": f"{val:.3f} KTPR", "where": f"{face} · {team}"})
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
