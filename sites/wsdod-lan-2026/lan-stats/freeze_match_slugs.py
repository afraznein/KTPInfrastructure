#!/usr/bin/env python3
"""Freeze per-match URL slugs into match-slugs.json, committed.

Slug shape: <day>-<map>-<teamA>-vs-<teamB>, e.g. sun-railroad2-nato-vs-icyhot.
Day comes from the match_id epoch in EASTERN time, not UTC -- splitting by UTC
moves matches within ~4 hours of midnight ET to the wrong day (verified against
this file's own output: UTC gives Sat 25 / Sun 29 / a spurious "Aug 3" with 2,
ET correctly gives Sat 30 / Sun 26). Needs a real IANA tzdata (WSL/Linux; plain
Windows Python has none for zoneinfo) -- run this via WSL.

THE TRAP: slugs must be frozen on first generation and never recomputed. An
existing entry is copied forward byte-identical, every run, forever -- this
script does not even look at what a match's slug would be today unless asked
to with --check. Re-running only appends match_ids that aren't in the file
yet. A regenerated slug is a dead Discord link.

--check recomputes every entry from scratch (ignoring the frozen file) and
diffs against what's committed, without writing anything -- exit 1 on any
difference. That is the loud failure the spec asks for; the normal run path
structurally cannot cause it, because it never recomputes an existing entry.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(HERE, "match-slugs.json")

# The tournament ran two days; a match epoch landing outside these two ET
# dates is a data problem worth stopping for, not a third label to invent.
DAY_LABEL = {
    datetime.date(2026, 8, 1): "sat",
    datetime.date(2026, 8, 2): "sun",
}

# Short, stable, URL-safe club slugs. Hand-declared rather than mechanically
# stripped from lanboard-data's tags, because two of those tags are symbol-only
# once you remove non-alphanumerics ("[$]" -> "", "[bb]" -> "bb" is fine but
# coincidental) -- a fixed roster of 10 clubs is worth naming by hand once
# rather than trusting a transform to degrade gracefully for all of them.
CLUB_SLUG = {
    "North Atlantic Treaty Org": "nato",
    "icyHOT": "icyhot",
    "dicE": "dice",
    "Arrested Development": "bluth",          # their tag, BLUTH
    "onLAN thunder": "fjtm",                  # their tag, FJTM
    "Best Buds": "bb",                        # their tag, [bb]
    "NoSoul": "nosoul",
    "Price is Right": "pir",                  # tag is "[$]" -- symbol-only, no slug in it
    "b Team": "bteam",
    "Uncle Rico's Time Machine": "urtm",      # their tag, uR[TM]
}

# Map variant suffixes DoD appends per pool/config (armory_b6, railroad2_s9a,
# saints2_b3e, lennon5_b1 and friends) -- a trailing "_" + letter + digits +
# optional letter. thunder2/anzio/harrington have no such suffix and pass
# through unchanged.
_SUFFIX = re.compile(r"_[a-z]\d+[a-z]?$")


def club_slug(name: str) -> str:
    if name in CLUB_SLUG:
        return CLUB_SLUG[name]
    sys.stderr.write("WARNING: no declared slug for club %r -- falling back to "
                      "a mechanical one; add it to CLUB_SLUG and re-run.\n" % name)
    return re.sub(r"[^a-z0-9]", "", name.lower()) or "club"


def map_slug(dod_map: str) -> str:
    name = dod_map[4:] if dod_map.startswith("dod_") else dod_map
    return _SUFFIX.sub("", name)


def day_label(match_id: str, tz) -> str:
    epoch = int(match_id.split("-", 1)[0])
    date = datetime.datetime.fromtimestamp(epoch, tz).date()
    if date not in DAY_LABEL:
        raise SystemExit("match %s falls on %s (ET), which is neither tournament "
                          "day -- check the epoch, don't invent a third label"
                          % (match_id, date))
    return DAY_LABEL[date]


def build_slug(match_id: str, teams: list[str], dod_map: str, tz) -> str:
    a, b = (club_slug(teams[0]), club_slug(teams[1]))
    return "%s-%s-%s-vs-%s" % (day_label(match_id, tz), map_slug(dod_map), a, b)


def load(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return json.load(fh)


def match_maps() -> dict[str, str]:
    """match_id -> dod_<map> for the curated set, from captures-placed.json
    (verified: all 56 curated matches present, exactly one distinct map each)."""
    out = {}
    for row in load("captures-placed.json"):
        out.setdefault(row["match_id"], row["map"])
    return out


def main() -> int:
    check = "--check" in sys.argv
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/New_York")

    match_teams = load("match-teams.json")
    maps = match_maps()
    missing_map = [m for m in match_teams if m not in maps]
    if missing_map:
        raise SystemExit("no map on record for curated match(es): %s" % missing_map)

    existing: dict[str, str] = {}
    if os.path.exists(OUT_PATH):
        existing = json.load(open(OUT_PATH, encoding="utf-8"))

    if check:
        fresh = {mid: build_slug(mid, match_teams[mid], maps[mid], tz) for mid in match_teams}
        # only compares matches that are ALREADY frozen -- a not-yet-appended
        # new match differing from nothing isn't a regression
        diffs = {mid: (existing[mid], fresh[mid]) for mid in existing
                 if mid in fresh and existing[mid] != fresh[mid]}
        if diffs:
            for mid, (was, now) in diffs.items():
                print("CHANGED  %s: %s -> %s" % (mid, was, now))
            sys.exit("%d frozen slug(s) would change -- match-slugs.json must "
                      "never be regenerated from scratch" % len(diffs))
        orphaned = [mid for mid in existing if mid not in match_teams]
        if orphaned:
            print("note: %d frozen match(es) no longer in match-teams.json "
                  "(not an error -- the curated set can shrink): %s" % (len(orphaned), orphaned))
        print("match-slugs.json: %d entries, all match a fresh rebuild" % len(existing))
        return 0

    new_ids = sorted((mid for mid in match_teams if mid not in existing),
                      key=lambda m: int(m.split("-", 1)[0]))
    if not new_ids:
        print("match-slugs.json: %d entries, nothing new" % len(existing))
        return 0

    taken = set(existing.values())
    added = {}
    for mid in new_ids:
        base = build_slug(mid, match_teams[mid], maps[mid], tz)
        slug = base
        n = 2
        while slug in taken:
            slug = "%s-%d" % (base, n)
            n += 1
        taken.add(slug)
        added[mid] = slug

    out = dict(existing)
    out.update(added)
    with open(OUT_PATH, "w", encoding="utf-8", newline="") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")

    print("match-slugs.json: %d existing + %d new = %d entries"
          % (len(existing), len(added), len(out)))
    for mid, slug in added.items():
        print("  + %s -> %s" % (mid, slug))
    return 0


if __name__ == "__main__":
    sys.exit(main())
