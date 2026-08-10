#!/usr/bin/env python3
"""Put shared placings on the award lists — a tie is one rank, not an order.

The award lists carry no rank, so the page numbered them 1..5 and two players
on the same figure read as ranked above one another. This writes competition
ranks into every `top` entry (1, 2, 2, 4, 5 — a tie shares its placing and
consumes the next), and stops the five-row cutoff slicing through a tie group:
where the boundary falls inside one, every member of the group is included.

Decided awards are recomputed in full from lan-stats.json, so a tie group the
MySQL export truncated is restored here — that is how a list can gain a name.
Single-match awards cannot be recomputed from this repo (their per-match
figures live only on the data server — the LAN match record for most, the HUD
tables for the four awards the match record cannot express), so their rows
only gain ranks. The match-record lists carry whole tie groups by
construction (apply_award_decisions.py); a tie AT the last shown mark of a
HUD-sourced award may extend beyond the export, and nothing local can prove
it either way.

    python fix_award_ties.py           # rewrite the ranks
    python fix_award_ties.py --check   # exit 1 if they are stale
"""
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
AWARDS = os.path.join(HERE, "awards.json")
STATS = os.path.join(HERE, "lan-stats.json")
BOARD = os.path.join(HERE, "season-board.json")

# Awards deliberately re-based onto a new metric, so the reproduce-the-published
# -list guard does not apply to them. Empty this once they have shipped.
REFORMULATED = {"mvp-sat", "mvp-sun"}

# Awards whose inputs are NOT in this repo, so they cannot be recomputed here:
# restraining needs hud_kills, melee needs the frag log by weapon, and both live
# only on the data server. Their rows and ranks are authored in
# apply_award_decisions.py and passed through untouched.
EXTERNAL = {"restraining", "melee"}
PAGE = os.path.normpath(os.path.join(HERE, "..", "design", "prototype.html"))

MIN_HALVES_RATE = 20   # the K/D and flags-per-half floors, as the export applied them
ASC = {"dont-touch"}   # least damage taken — the only list where lower wins


def parse_value(v):
    """The number inside a display value: '124,520', '6.91 / half', '17:44'."""
    m = re.fullmatch(r"(\d+):(\d\d)", v.strip())
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.match(r"[\d,]+(?:\.\d+)?", v.strip())
    if not m:
        sys.exit(f"unparseable award value {v!r}")
    return float(m.group(0).replace(",", ""))


def mmss(seconds):
    s = int(seconds)          # the export floored, it did not round
    return f"{s // 60}:{s % 60:02d}"


# ---- decided: full recompute, same figures the page's stats board uses ------

def weekend_rows():
    stats = json.load(open(STATS, encoding="utf-8"))
    agg = {}
    per_day = {}
    for dkey in sorted(stats["days"]):
        for p in stats["days"][dkey]["players"]:
            a = agg.setdefault(p["steam_id"], collections.Counter())
            for f in ("kills", "deaths", "flags", "halves", "headshots",
                      "assists", "cap_breaks"):
                a[f] += p.get(f) or 0
            a["prone"] += p.get("prone_seconds") or 0
            per_day.setdefault(dkey, {})[p["steam_id"]] = p.get("ktpr")
    return agg, per_day


def decided_metric(slug, agg, per_day):
    """[(steam_id, sort value, display value)] for one decided award, unsorted."""
    if slug in ("mvp-sat", "mvp-sun"):
        # season-board.json, not lan-stats.json: the day views there are scored
        # by the current team formula against that day's own medians, while
        # lan-stats.json's ktpr is still the legacy additive number the day
        # boards used before 2026-08-09. The MVPs follow the board they sit on.
        day = {"mvp-sat": "08-01", "mvp-sun": "08-02"}[slug]
        board = json.load(open(BOARD, encoding="utf-8"))
        return [(r["steam_id"], r["ktpr"], f'{r["ktpr"]:.3f} KTPR')
                for r in board["views"][day]["players"]]
    counters = {"fragger": "kills", "flagger": "flags",
                "breaks": "cap_breaks", "assists": "assists",
                "headshots": "headshots"}
    if slug in counters:
        return [(s, a[counters[slug]], str(a[counters[slug]]))
                for s, a in agg.items()]
    if slug == "flags-rate":
        return [(s, a["flags"] / a["halves"], f'{a["flags"] / a["halves"]:.2f} / half')
                for s, a in agg.items() if a["halves"] >= MIN_HALVES_RATE]
    if slug == "kd":
        return [(s, a["kills"] / a["deaths"], f'{a["kills"] / a["deaths"]:.2f} K/D')
                for s, a in agg.items()
                if a["halves"] >= MIN_HALVES_RATE and a["deaths"]]
    if slug == "prone":
        return [(s, a["prone"], mmss(a["prone"])) for s, a in agg.items()]
    sys.exit(f"no metric for decided award {slug!r}")


def five_placings(rows):
    """[(rank, display value, [steam_id, ...])] — whole groups, to 5th place."""
    groups = []
    for sid, _, disp in sorted(rows, key=lambda r: -r[1]):
        if groups and groups[-1][1] == disp:
            groups[-1][2].append(sid)
        else:
            groups.append([1 + sum(len(g[2]) for g in groups), disp, [sid]])
    return [g for g in groups if g[0] <= 5]


def names_and_aliases(awards):
    board = json.load(open(BOARD, encoding="utf-8"))
    page = open(PAGE, encoding="utf-8").read()
    m = re.search(r'<script id="lanboard-data" type="application/json">(.*?)</script>',
                  page, re.S)
    if not m:
        sys.exit("lanboard-data block not found — run inject_season_board.py first")
    # display name + team from the board block, the same rule as every other
    # name on the page (fix_positions_award.py resolves names the same way)
    by_full = {p["n"]: p
               for p in json.loads(m.group(1))["views"]["weekend"]["players"]}
    sid_row = {}
    for r in board["views"]["weekend"]["players"]:
        row = by_full.get(r["name"])
        if row:
            sid_row[r["steam_id"]] = row

    # a player's recorded alias, from any list they already appear on — the
    # export decided who carries one (ian does, LaNGoNdd does not) and a new
    # row should agree with the rows that exist
    alias = {}
    for a in awards.get("decided", []) + awards.get("single_match", []):
        for e in (a.get("top") or []) + (a.get("tied") or []):
            if e.get("as"):
                prior = alias.setdefault(e["who"], e["as"])
                if prior != e["as"]:
                    sys.exit(f'conflicting aliases for {e["who"]!r}: '
                             f'{prior!r} vs {e["as"]!r}')
    return sid_row, alias


def rebuild_decided(award, agg, per_day, sid_row, alias):
    placings = five_placings(decided_metric(award["slug"], agg, per_day))
    if len(placings[0][2]) > 1:
        sys.exit(f'{award["slug"]}: the top mark is now shared — this script '
                 "has no leader-tie path for decided awards, add one")

    old = {e["who"]: e for e in award["top"]}
    rows = []
    for rank, disp, sids in placings:
        for sid in sids:
            row = sid_row.get(sid)
            if not row:
                sys.exit(f'{award["slug"]}: no leaderboard row for {sid!r}')
            e = old.get(row["dn"])
            if e is not None:
                # a re-based award is expected to disagree with its published
                # figure; take the new value rather than refusing it
                if award["slug"] in REFORMULATED:
                    e = dict(e, value=disp)
                elif e["value"] != disp:
                    sys.exit(f'{award["slug"]}: {row["dn"]} recomputes to '
                             f'{disp!r} but the award says {e["value"]!r} — '
                             "the export and lan-stats.json disagree")
                else:
                    e = dict(e)
            else:
                e = {"who": row["dn"], "value": disp, "where": row["tm"]}
                if row["dn"] in alias:
                    e["as"] = alias[row["dn"]]
            e["rank"] = rank
            rows.append(e)

    # The guard exists so a wrong metric can't quietly rewrite an award. These
    # two are the exception on purpose: they were rated by the legacy additive
    # formula and are being re-based onto the team formula, so disagreeing with
    # what is published is the whole point. Every other decided award still has
    # to reproduce its published list exactly.
    if award["slug"] not in REFORMULATED:
        kept = [(e["who"], e["value"]) for e in rows if e["who"] in old]
        if kept != [(e["who"], e["value"]) for e in award["top"]]:
            sys.exit(f'{award["slug"]}: recompute does not reproduce the published '
                     "list — fix the metric before shipping ranks")
        return dict(award, top=rows)
    # A re-based award can change who leads it, and the card reads `leader`
    # rather than row one — leaving it stale showed the old winner above the
    # new list. Non-reformulated awards can't move, so they keep theirs.
    return dict(award, top=rows, leader=dict(rows[0]))


# ---- single-match: ranks only, plus the one tie group the export recorded --

def rebuild_single(award):
    slug, top = award["slug"], award["top"]
    lead = award.get("leader") or {}
    ties = lead.get("ties") or 0

    if ties > 1 and award.get("tied"):
        if len(award["tied"]) != ties:
            sys.exit(f"{slug}: leader.ties says {ties} but tied lists "
                     f'{len(award["tied"])}')
        shown = {(e["who"], e["where"]) for e in top
                 if parse_value(e["value"]) == parse_value(lead["value"])}
        listed = {(t["who"], t["where"]) for t in award["tied"]}
        if not shown <= listed:
            sys.exit(f"{slug}: a top row on the shared mark is missing from tied")
        rows = []
        for t in award["tied"]:
            e = {"who": t["who"], "value": lead["value"], "where": t["where"]}
            if t.get("as"):
                e["as"] = t["as"]
            e["rank"] = 1
            rows.append(e)
        # anything below the shared mark would rank past it; the export kept
        # five rows, so with 5+ tied at the top there is nothing left to show
        rest = [e for e in top
                if parse_value(e["value"]) != parse_value(lead["value"])]
        if rest:
            sys.exit(f"{slug}: rows below a 5-way shared lead — extend the "
                     "ranking here before shipping")
        return dict(award, top=rows)

    vals = [parse_value(e["value"]) for e in top]
    for a, b in zip(vals, vals[1:]):
        if (b > a) if slug not in ASC else (b < a):
            sys.exit(f"{slug}: values are not sorted; refusing to rank them")
    rows, ranks = [], []
    for i, e in enumerate(top):
        ranks.append(ranks[-1] if i and vals[i] == vals[i - 1] else i + 1)
        rows.append(dict(e, rank=ranks[-1]))
    return dict(award, top=rows)


def build(awards):
    agg, per_day = weekend_rows()
    sid_row, alias = names_and_aliases(awards)
    out = dict(awards)
    out["decided"] = [a if a["slug"] in EXTERNAL
                      else rebuild_decided(a, agg, per_day, sid_row, alias)
                      for a in awards["decided"]]
    out["single_match"] = [rebuild_single(a) for a in awards["single_match"]]
    return out


def main() -> int:
    awards = json.load(open(AWARDS, encoding="utf-8"))
    # rebuild from rank-less lists so a re-run reproduces itself. EXTERNAL
    # awards are exempt: their ranks are authored, not derived, so stripping
    # them here would delete the only copy — build() passes them through
    # untouched and has nothing to regenerate them from.
    stripped = json.loads(json.dumps(awards))
    for section in ("decided", "single_match"):
        for a in stripped[section]:
            if a["slug"] in EXTERNAL:
                continue
            for e in a["top"]:
                e.pop("rank", None)
    new = build(stripped)

    if "--check" in sys.argv:
        if awards != new:
            print("award ranks are STALE — re-run fix_award_ties.py")
            return 1
        print("award ranks are current")
        return 0

    if awards == new:
        print("no change")
        return 0
    json.dump(new, open(AWARDS, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    for section in ("decided", "single_match"):
        for a, was in zip(new[section], awards[section]):
            added = [e for e in a["top"]
                     if e["who"] not in {x["who"] for x in was.get("top", [])}]
            ranks = ",".join(str(e["rank"]) for e in a["top"])
            note = "".join(f'  +{e["who"]} ({e["value"]})' for e in added)
            print(f'  {a["slug"]:<13} ranks {ranks}{note}')
    print("\nnow re-embed it into the page:  python build_ballots.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
