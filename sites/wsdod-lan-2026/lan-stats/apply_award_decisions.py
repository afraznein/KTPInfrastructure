#!/usr/bin/env python3
"""Operator decisions on award membership, applied over awards.json.

The single-match awards came from a MySQL-backed script that never landed in
this repo, and their figures cannot be recomputed from anything tracked here —
the per-match numbers live only on the data server. So corrections that need
the DB are recorded here as decisions, with the query result that justified
each one, and applied idempotently.

Facts below were measured 2026-08-09 against the live `hlstatsx_lan` DB,
read-only, scoped to the 55 tournament matches (`hud_events` ktp_match_end
rows with match_type 0 falling on Aug 1-2 — exactly 55) and deduped to one
entry per player (their best match), which is the convention the published
lists already follow. Match-record figures are `ktp_match_stats` summed over
halves 1 and 2 (half 0 is the match total and would double everything), which
reproduces the published Difficulty: Tourist row exactly (hildebrand 67-13);
weapon-scoped counts are `hlstats_Events_Frags` filtered by weapon, which
agrees with `ktp_match_stats.kills` on all 55 match totals.

⚠️ The melee award added later that day is scoped to `match-teams.json` (56),
not to those 55. The two sets are not the same question: 55 is "matches that
logged a ktp_match_end", 56 is the curated tournament set, which also holds
`1785715972-KTP1` — real play, 12 players, 263 kills, whose logging died before
the match could close. Anything counted off the frag log should use the 56.

    python apply_award_decisions.py           # apply
    python apply_award_decisions.py --check   # exit 1 if any decision is unapplied
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
AWARDS = os.path.join(HERE, "awards.json")

# Awards removed from a section entirely, keyed (section, slug).
DROP = {
    ("single_match", "own-worst"): (
        "Own Worst Enemy — most suicides in a single match. TWENTY-EIGHT players "
        "tie on 2 for 4th place; the published list showed two of them. Suicides "
        "do not discriminate per match. Same shape as No Cap For You, which was "
        "dropped for the same reason on 2026-08-09."
    ),
    ("decided", "damage"): (
        "Heavy Hitter — most damage dealt across the weekend. Re-created in "
        "single_match as a single-match record (operator decision 2026-08-09): "
        "the weekend total already lives on the stats board, and the move "
        "rebalances the two sections to 12 cards each."
    ),
    ("single_match", "sidearm"): (
        "Sidearm Specialist — most pistol kills in a single match. NINE players "
        "tie on 5 for 4th (see the CONVERT list below, kept here as the record "
        "of what it looked like). Pistol kills per match do not discriminate: "
        "the whole list spans 9 down to 5. Operator decision 2026-08-09, same "
        "reasoning as Own Worst Enemy and No Cap For You."
    ),
    ("decided", "streak"): (
        "On A Tear — longest kill streak. NOT retired: re-created in "
        "single_match below (operator decision 2026-08-09). A streak cannot "
        "span matches, so it was always a single-match record wearing a "
        "weekend card; the move only adds the match it happened in. Same seven "
        "players, same figures, same placings."
    ),
}

# single_match awards re-sourced from the match record instead of the HUD
# (operator decision 2026-08-09). Rows are rank-less — fix_award_ties.py derives
# the shared placings. Where the same player+match already appeared on the
# published list, its `as`/match choice is carried; where a player's best is
# shared across matches, the published match is kept if it is in the tie, else
# the earliest.
#
# Validation against the HUD lists they replace (every leader/membership move):
#   one-man     leader holds (sTarK_ 86). cK 82→84 passes vertex 83; the 79
#               mark is shared three ways, pulling in jules and Savage¬.
#   hurt-me     LEADER CHANGES: Ke:>^1.de 72→77 overtakes tokih 77→76.
#               o[bb]y (75 HUD, 70 record) drops out; Jee enters on 72.
#   headhunter  leader holds (bR0M 20). e p y o n 19→18 falls to a new 4-way
#               5th; m00cat :D enters there.
#   benedict    identical list — HUD and match record agree row for row.
#   sidearm     leader holds, patten 10→9. Sq =))) 7→5 and Ho0liii/ian/
#               NoName^/vertex 6→5 slide into a NINE-way 4th; element (6 HUD,
#               4 record) drops out; arachnid, hey hi, stealthlol enter.
#   amazon      leader holds (cK 29→30). TillJim enters sharing 5th on 19.
CONVERT = {
    "one-man": {
        "blurb": "Most kills in a single match. Match record.",
        "top": [
            {"who": "sTarK_ x_0", "value": "86",
             "where": "saints2_b3e · Sun · v Uncle Rico's Time Machine",
             "as": "sTarK_ x_0 <3＃77"},
            {"who": "cK", "value": "84",
             "where": "harrington · Sun · v Price is Right",
             "as": "cK- ＃phillylan2026"},
            {"who": "vertex", "value": "83",
             "where": "railroad2_s9a · Sun · v Price is Right"},
            {"who": "nomistizzle", "value": "80",
             "where": "harrington · Sat · v Uncle Rico's Time Machine"},
            {"who": "piff", "value": "79",
             "where": "lennon5_b1 · Sun · v Price is Right",
             "as": "piff ＃4Monty"},
            {"who": "jules", "value": "79",
             "where": "railroad2_s9a · Sun · v Best Buds"},
            {"who": "Savage¬", "value": "79",
             "where": "armory_b6 · Sun · v Price is Right"},
        ],
    },
    "hurt-me": {
        "blurb": "Most deaths in a single match. Match record.",
        "top": [
            {"who": "Ke:>^1.de", "value": "77",
             "where": "lennon5_b1 · Sat · v North Atlantic Treaty Org"},
            {"who": "tokih", "value": "76",
             "where": "harrington · Sun · v Best Buds"},
            {"who": "billbsod", "value": "74",
             "where": "harrington · Sun · v icyHOT"},
            {"who": "nomistizzle", "value": "73",
             "where": "lennon5_b1 · Sun · v Best Buds"},
            {"who": "Jee", "value": "72",
             "where": "saints2_b3e · Sun · v b Team",
             "as": "Jee ＃22e＃minou"},
        ],
    },
    "headhunter": {
        "blurb": "Most headshot kills in a single match. Match record.",
        "top": [
            {"who": "bR0M", "value": "20",
             "where": "anzio · Sat · v b Team", "as": "bR0M ＃wetya"},
            {"who": "nein", "value": "19",
             "where": "railroad2_s9a · Sun · v b Team", "as": "nein_"},
            {"who": "Ke:>^1.de", "value": "19",
             "where": "armory_b6 · Sun · v NoSoul"},
            {"who": "element", "value": "19",
             "where": "armory_b6 · Sun · v Arrested Development"},
            {"who": "jules", "value": "18",
             "where": "armory_b6 · Sat · v b Team"},
            {"who": "billbsod", "value": "18",
             "where": "armory_b6 · Sat · v dicE"},
            {"who": "e p y o n", "value": "18",
             "where": "thunder2 · Sat · v icyHOT"},
            {"who": "m00cat :D", "value": "18",
             "where": "harrington · Sun · v NoSoul"},
        ],
    },
    "benedict": {
        "blurb": "Most team kills in a single match. Match record.",
        "top": [
            {"who": "Ke:>^1.de", "value": "6",
             "where": "armory_b6 · Sat · v icyHOT"},
            {"who": "element", "value": "5",
             "where": "lennon5_b1 · Sat · v NoSoul"},
            {"who": "Hub", "value": "5",
             "where": "harrington · Sat · v dicE"},
            {"who": "cK", "value": "5",
             "where": "harrington · Sat · v NoSoul",
             "as": "cK- ＃phillylan2026"},
            {"who": "warchyld[dd]", "value": "5",
             "where": "anzio · Sat · v icyHOT"},
            {"who": "Gorilla[bc]", "value": "5",
             "where": "harrington · Sun · v NoSoul"},
        ],
    },
    "sidearm": {
        "blurb": "Most pistol kills in a single match. Match record.",
        "top": [
            {"who": "patten", "value": "9",
             "where": "harrington · Sat · v b Team"},
            {"who": "nomistizzle", "value": "6",
             "where": "lennon5_b1 · Sun · v Best Buds"},
            {"who": "LaNGoNdd", "value": "6",
             "where": "railroad2_s9a · Sun · v Best Buds"},
            {"who": "arachnid", "value": "5",
             "where": "lennon5_b1 · Sat · v dicE"},
            {"who": "hey hi", "value": "5",
             "where": "harrington · Sat · v Arrested Development",
             "as": "hey hi <3 dustbin"},
            {"who": "stealthlol", "value": "5",
             "where": "anzio · Sat · v icyHOT",
             "as": "stealthlol＃kingCOOP"},
            {"who": "Ho0liii", "value": "5",
             "where": "lennon5_b1 · Sun · v onLAN thunder"},
            {"who": "ian", "value": "5",
             "where": "lennon5_b1 · Sun · v North Atlantic Treaty Org"},
            {"who": "Sq =)))", "value": "5",
             "where": "saints2_b3e · Sun · v onLAN thunder"},
            {"who": "NoName^", "value": "5",
             "where": "thunder2 · Sun · v dicE"},
            {"who": "vertex", "value": "5",
             "where": "armory_b6 · Sun · v Arrested Development"},
        ],
    },
    "amazon": {
        "blurb": "Most grenade kills in a single match. Match record.",
        "top": [
            {"who": "cK", "value": "30",
             "where": "lennon5_b1 · Sun · v Price is Right",
             "as": "cK- ＃phillylan2026"},
            {"who": "s i k", "value": "26",
             "where": "lennon5_b1 · Sat · v Arrested Development",
             "as": "s i k <3 n a t"},
            {"who": "vertex", "value": "23",
             "where": "harrington · Sun · v Price is Right"},
            {"who": "LaNGoNdd", "value": "21",
             "where": "armory_b6 · Sat · v b Team"},
            {"who": "warchyld[dd]", "value": "19",
             "where": "harrington · Sat · v North Atlantic Treaty Org"},
            {"who": "TillJim", "value": "19",
             "where": "harrington · Sat · v b Team"},
        ],
    },
}

# The four single-match awards that STAY on the HUD, each saying why — the
# match record has no assists, no prone, and no damage-taken figure at all.
REBLURB = {
    "helping-hand": "Most assists in a single match. HUD — the match record "
                    "has no assists at all.",
    "horizontal": "Most time prone in a single match. HUD — nothing else "
                  "measured prone.",
    "dont-touch": "Least damage taken in a full match. HUD — the match record "
                  "logs damage dealt only.",
    "sponge": "Most damage taken in a single match. HUD — the match record "
              "logs damage dealt only.",
}

# Players cut by the five-row export while sharing a mark with players who were
# kept. Empty since 2026-08-09: the five entries recorded here (benedict ×1,
# sidearm ×4) corrected the HUD lists and are superseded by the match-record
# conversion above, whose lists carry whole tie groups to begin with.
ADD_TIED = []

# Wholly new awards. The restraining ranks are authored (hud_kills is on the
# data server, so fix_award_ties.py lists it EXTERNAL and passes it through);
# the damage rows are rank-less like the CONVERT lists and get their placings
# from fix_award_ties.py.
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
    # Bring A Gun Next Time — the replacement for Sidearm Specialist. Melee is
    # not in lan-stats.json (it has gun_kills and nade_kills, nothing else), so
    # like restraining this is EXTERNAL in fix_award_ties.py and its ranks are
    # authored here. Scoped to the 56 curated matches, half > 0, killer != victim
    # (a melee suicide is not a kill), resolved by SteamID rather than name.
    ("decided", {
        "slug": "melee",
        "title": "Welcome to Philly",
        "blurb": "Most melee kills all weekend — spade, knife, bayonet and "
                 "rifle butt. The whole event produced 68 of them.",
        "status": "proposed",
        "top": [
            {"rank": 1, "who": "hey hi", "value": "10", "where": "b Team",
             "as": "hey hi <3 dustbin"},
            {"rank": 2, "who": "reppoĦ", "value": "9", "where": "Best Buds"},
            {"rank": 3, "who": "Khoi", "value": "6", "where": "NoSoul"},
            {"rank": 4, "who": "m00cat :D", "value": "5", "where": "dicE"},
            {"rank": 5, "who": "ian", "value": "3", "where": "onLAN thunder",
             "as": "bonchon"},
            {"rank": 5, "who": "Ke:>^1.de", "value": "3",
             "where": "Uncle Rico's Time Machine"},
            {"rank": 5, "who": "warchyld[dd]", "value": "3", "where": "dicE"},
        ],
        "leader": {"rank": 1, "who": "hey hi", "value": "10", "where": "b Team",
                   "as": "hey hi <3 dustbin"},
        "tied": None,
    }),
    # On A Tear, moved from decided. lan-stats.json already carries the match a
    # player's best streak happened in (`streak_detail`), so the move is the
    # published list plus that context — no figure changes. Rank-less: the
    # values are sorted, so fix_award_ties.py derives 1,2,2,4,5,5,5.
    ("single_match", {
        "slug": "streak",
        "title": "On A Tear",
        "blurb": "Longest kill streak in a single match. Match record — "
                 "rebuilt from the frag log, not read off the HUD.",
        "status": "proposed",
        "top": [
            {"who": "Seanality", "value": "14",
             "where": "thunder2 · Sat · v b Team"},
            {"who": "hildebrand?", "value": "13",
             "where": "armory_b6 · Sat · v Uncle Rico's Time Machine"},
            {"who": "jules", "value": "13",
             "where": "thunder2 · Sat · v Uncle Rico's Time Machine"},
            {"who": "Polak", "value": "12",
             "where": "anzio · Sat · v b Team"},
            {"who": "ddorito", "value": "11",
             "where": "railroad2_s9a · Sun · v Best Buds"},
            {"who": "ian", "value": "11",
             "where": "thunder2 · Sat · v Uncle Rico's Time Machine",
             "as": "bonchon"},
            {"who": "LaNGoNdd", "value": "11",
             "where": "railroad2_s9a · Sun · v NoSoul"},
        ],
        "leader": {"who": "Seanality", "value": "14",
                   "where": "thunder2 · Sat · v b Team", "ties": 1},
        "tied": None,
    }),
    # Heavy Hitter, moved from decided (weekend total) to a single-match
    # record. Same measurement as the CONVERT lists: ktp_match_stats.damage,
    # halves 1+2, best match per player.
    ("single_match", {
        "slug": "damage",
        "title": "Heavy Hitter",
        "blurb": "Most damage dealt in a single match. Match record.",
        "status": "proposed",
        "top": [
            {"who": "vertex", "value": "14,038",
             "where": "railroad2_s9a · Sun · v Price is Right"},
            {"who": "cK", "value": "13,930",
             "where": "lennon5_b1 · Sun · v Price is Right",
             "as": "cK- ＃phillylan2026"},
            {"who": "NoName^", "value": "13,816",
             "where": "saints2_b3e · Sun · v dicE"},
            {"who": "Savage¬", "value": "13,580",
             "where": "armory_b6 · Sun · v Price is Right"},
            {"who": "element", "value": "13,430",
             "where": "railroad2_s9a · Sun · v NoSoul"},
        ],
        "leader": {"who": "vertex", "value": "14,038",
                   "where": "railroad2_s9a · Sun · v Price is Right",
                   "ties": 1},
        "tied": None,
    }),
]


def _rows(a):
    return a.get("top") or []


def _bare(rows):
    return [{k: v for k, v in e.items() if k != "rank"} for e in rows]


def apply(awards, dry=False):
    changed = []
    for section in ("decided", "single_match"):
        keep = []
        for a in awards.get(section, []):
            if (section, a.get("slug")) in DROP:
                changed.append(("drop", a.get("slug"), a.get("title")))
                if dry:
                    keep.append(a)
                continue
            keep.append(a)
        if not dry:
            awards[section] = keep

    for section, award in ADD_AWARD:
        live = next((a for a in awards.get(section, [])
                     if a.get("slug") == award["slug"]), None)
        if live is not None:
            # An award authored here stays authored: editing its title above has
            # to reach awards.json, or the two disagree and --check still passes.
            # Title and blurb only — rows gain ranks from fix_award_ties.py, so
            # reconciling `top` would make the two scripts overwrite each other.
            for field in ("title", "blurb"):
                if live.get(field) != award[field]:
                    changed.append(("retitle" if field == "title" else "reblurb",
                                    award["slug"],
                                    f'{live.get(field)!r} -> {award[field]!r}'))
                    if not dry:
                        live[field] = award[field]
            continue
        changed.append(("new", award["slug"], award["title"]))
        if not dry:
            awards.setdefault(section, []).append(award)

    for a in awards.get("single_match", []):
        slug = a.get("slug")
        conv = CONVERT.get(slug)
        if conv is not None:
            leader = dict(_bare([conv["top"][0]])[0], ties=1)
            same = (a.get("blurb") == conv["blurb"]
                    and _bare(_rows(a)) == conv["top"]
                    and {k: v for k, v in (a.get("leader") or {}).items()
                         if k != "rank"} == leader)
            if not same:
                changed.append(("convert", slug, a.get("title")))
                if not dry:
                    a["blurb"] = conv["blurb"]
                    a["top"] = [dict(e) for e in conv["top"]]
                    a["leader"] = leader
                    a["tied"] = None
        elif slug in REBLURB and a.get("blurb") != REBLURB[slug]:
            changed.append(("reblurb", slug, a.get("title")))
            if not dry:
                a["blurb"] = REBLURB[slug]

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
        print(f"  {kind:<7} {slug:<12} {what}")
    print("\nnow: re-run the shared-rank pass, then "
          "PYTHONHASHSEED=0 python build_ballots.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
