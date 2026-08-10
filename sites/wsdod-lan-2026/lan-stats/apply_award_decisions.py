#!/usr/bin/env python3
"""Operator decisions on award membership, applied over awards.json.

The single-match awards came from a MySQL-backed script that never landed in
this repo, and their tie groups cannot be recomputed from anything tracked here
— assists, prone, grenade kills, team kills and damage taken are per-match HUD
figures that live only on the data server. So corrections that need the DB are
recorded here as decisions, with the query result that justified each one, and
applied idempotently.

Facts below were measured 2026-08-09 against the live `hlstatsx_lan` DB,
read-only, scoped to the 55 tournament matches (Sat/Sun `match_type=0`) and
deduped to one entry per player, which is the convention the published lists
already follow.

    python apply_award_decisions.py           # apply
    python apply_award_decisions.py --check   # exit 1 if any decision is unapplied
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
AWARDS = os.path.join(HERE, "awards.json")

# Awards removed entirely. Not a tie to extend — a stat with no resolution at
# match granularity, so there is no winner to find.
DROP = {
    "own-worst": (
        "Own Worst Enemy — most suicides in a single match. TWENTY-EIGHT players "
        "tie on 2 for 4th place; the published list showed two of them. Suicides "
        "do not discriminate per match. Same shape as No Cap For You, which was "
        "dropped for the same reason on 2026-08-09."
    ),
}

# Players cut by the five-row export while sharing a mark with players who were
# kept. Each entry is (slug, who, value, where) inserted after the last row
# holding the same value.
ADD_TIED = [
    # Benedict Arnold, most team kills in a match: FIVE players tie on 5
    # (cK, warchyld[dd], Gorilla[bc], element, Hub); four were published.
    # Context derived, not guessed: match 1785689244-KTP4, dod_harrington,
    # 2026-08-02 (Sunday), dicE vs NoSoul, and "Gorilla[bc]" is the display
    # name the leaderboard block already renders for that SteamID.
    ("benedict", "Gorilla[bc]", "5", "harrington · Sun · v NoSoul"),
    # Sidearm Specialist, most pistol kills in a match: SIX players tie on 6
    # (LaNGoNdd, element, NoName^, Ho0liii, vertex, ian); two were published.
    # The four below were cut. Ho0liii was only findable by SteamID — the export
    # recorded him under the alias "findus", so a name-based check misses him.
    ("sidearm", "LaNGoNdd", "6", "railroad2_s9a · Sun · v Best Buds"),
    ("sidearm", "NoName^", "6", "thunder2 · Sun · v dicE"),
    ("sidearm", "vertex", "6", "armory_b6 · Sun · v Arrested Development"),
    ("sidearm", "ian", "6", "lennon5_b1 · Sun · v North Atlantic Treaty Org"),
]

# Wholly new awards. These cannot live in fix_award_ties.py's recompute path,
# because their inputs are not in this repo — hud_kills is on the data server —
# so the ranks are baked here and that script skips them by slug.
ADD_AWARD = [
    ("decided", {
        "slug": "restraining",
        "title": "Restraining Order",
        "blurb": "Most kills on one specific opponent, all weekend. "
                 "piff and kroD killed each other 130 times.",
        "status": "proposed",
        "top": [
            {"rank": 1, "who": "NoName^", "value": "69",
             "where": "North Atlantic Treaty Org · v warchyld[dd]"},
            {"rank": 2, "who": "piff", "value": "68",
             "where": "Best Buds · v kroD"},
            {"rank": 3, "who": "warchyld[dd]", "value": "66",
             "where": "dicE · v Khoi"},
            {"rank": 3, "who": "player", "value": "66",
             "where": "dicE · v Hub"},
            {"rank": 5, "who": "kroD", "value": "62",
             "where": "Arrested Development · v piff"},
            {"rank": 5, "who": "Hub", "value": "62",
             "where": "North Atlantic Treaty Org · v player"},
        ],
        "leader": {"rank": 1, "who": "NoName^", "value": "69",
                   "where": "North Atlantic Treaty Org · v warchyld[dd]"},
        "tied": None,
    }),
]


def _rows(a):
    return a.get("top") or []


def apply(awards, dry=False):
    changed = []
    for section in ("decided", "single_match"):
        keep = []
        for a in awards.get(section, []):
            if a.get("slug") in DROP:
                changed.append(("drop", a.get("slug"), a.get("title")))
                if dry:
                    keep.append(a)
                continue
            keep.append(a)
        if not dry:
            awards[section] = keep

    for section, award in ADD_AWARD:
        if any(a.get("slug") == award["slug"] for a in awards.get(section, [])):
            continue
        changed.append(("new", award["slug"], award["title"]))
        if not dry:
            awards.setdefault(section, []).append(award)

    by_slug = {a["slug"]: a for s in ("decided", "single_match")
               for a in awards.get(s, [])}
    for slug, who, value, where in ADD_TIED:
        a = by_slug.get(slug)
        if a is None:
            sys.exit(f"award {slug!r} not found — cannot add {who!r}")
        if any(r.get("who") == who for r in _rows(a)):
            continue
        if not any(r.get("value") == value for r in _rows(a)):
            sys.exit(f"{slug}: no existing row holds value {value!r}, so {who!r} "
                     "is not sharing a mark — refusing to insert")
        changed.append(("add", slug, f"{who} ({value})"))
        if dry:
            continue
        rows, out, placed = _rows(a), [], False
        for i, r in enumerate(rows):
            out.append(r)
            nxt = rows[i + 1] if i + 1 < len(rows) else None
            if r.get("value") == value and (nxt is None or nxt.get("value") != value):
                out.append({"who": who, "value": value, "where": where})
                placed = True
        if not placed:
            sys.exit(f"{slug}: could not place {who!r}")
        a["top"] = out
    return changed


def main() -> int:
    awards = json.load(open(AWARDS, encoding="utf-8"))
    if "--check" in sys.argv:
        pending = apply(awards, dry=True)
        if pending:
            print(f"{len(pending)} decision(s) unapplied — re-run apply_award_decisions.py")
            for kind, slug, what in pending:
                print(f"  {kind}: {slug} — {what}")
            return 1
        print("award decisions are current")
        return 0

    changed = apply(awards)
    if not changed:
        print("no change")
        return 0
    json.dump(awards, open(AWARDS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for kind, slug, what in changed:
        print(f"  {kind:<5} {slug:<10} {what}")
    print("\nnow: re-run the shared-rank pass, then "
          "PYTHONHASHSEED=0 python build_ballots.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
