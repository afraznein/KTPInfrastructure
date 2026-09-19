"""
Aggregate stats on which maps got banned, picked, and decided -- and in what
order -- across every parsed draft. Pure aggregation over drafts.json, no
LLM involved, deterministic and re-runnable.

Map-name normalization (also written into the generated report so nothing's
hidden): strips a leading 'dod_' prefix and a trailing build/season-config
suffix like '_b6', '_s9a', '_test', '_deez' (these are clearly config tags,
not different maps -- 'armory_b6' and 'dod_armory_b6' are the same map as
'armory'). Per league confirmation, the numbered-remake families are each one
map and fold onto their current version: lennon/lennon2/lennon5 -> lennon2,
railroad/railroad2/rr2 -> railroad2, thunder/thunder2 -> thunder2,
saints/saints2 -> saints2 (railyard has no remake and stays as-is). The
report lists exactly which raw tokens got merged into each row.

Usage:
    python map_stats.py <channel_id> [--out data/MAP_STATS.md]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))

CONFIG_SUFFIX_RE = re.compile(r"_(?:b\d+[a-z]*|s\d+[a-z]*|\d+|test|deez)$", re.IGNORECASE)
# Confirmed by the league: each numbered-remake family is one map, named for
# its current version. railyard has no remake, so it's just itself.
FAMILY_CANONICAL = {
    "lennon": "lennon2", "lennon2": "lennon2", "lennon5": "lennon2",
    "railroad": "railroad2", "railroad2": "railroad2", "rr2": "railroad2",
    "thunder": "thunder2", "thunder2": "thunder2",
    "saints": "saints2", "saints2": "saints2",
    "railyard": "railyard",
}


def canon_map_key(raw: str) -> str:
    name = raw.lower()
    if name.startswith("dod_"):
        name = name[len("dod_"):]
    while True:
        stripped = CONFIG_SUFFIX_RE.sub("", name)
        if stripped == name:
            break
        name = stripped
    name = FAMILY_CANONICAL.get(name, name)
    return name


def load_drafts(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_map_tag_map(records: list[dict]) -> dict[str, Counter]:
    tag_map: dict[str, Counter] = defaultdict(Counter)
    for r in records:
        for a in r["actions"]:
            tag_map[canon_map_key(a["map"])][a["map"]] += 1
        if r["decider_map"]:
            tag_map[canon_map_key(r["decider_map"])][r["decider_map"]] += 1
    return tag_map


def compute_stats(records: list[dict]):
    total_drafts = len(records)
    stats: dict[str, dict] = defaultdict(lambda: {
        "times_banned": 0, "times_picked": 0, "times_decider": 0,
        "ban_pos": Counter(), "pick_pos": Counter(), "drafts_seen": set(),
    })

    total_bans = total_picks = total_deciders = 0

    for r in records:
        bans_this_draft = [a for a in r["actions"] if a["action"] == "ban"]
        picks_this_draft = [a for a in r["actions"] if a["action"] == "pick"]
        for i, a in enumerate(bans_this_draft, 1):
            key = canon_map_key(a["map"])
            s = stats[key]
            s["times_banned"] += 1
            s["ban_pos"][i] += 1
            s["drafts_seen"].add(r["message_id"])
            total_bans += 1
        for i, a in enumerate(picks_this_draft, 1):
            key = canon_map_key(a["map"])
            s = stats[key]
            s["times_picked"] += 1
            s["pick_pos"][i] += 1
            s["drafts_seen"].add(r["message_id"])
            total_picks += 1
        if r["decider_map"]:
            key = canon_map_key(r["decider_map"])
            s = stats[key]
            s["times_decider"] += 1
            s["drafts_seen"].add(r["message_id"])
            total_deciders += 1

    rows = []
    for key, s in stats.items():
        total_appearances = s["times_banned"] + s["times_picked"] + s["times_decider"]
        rows.append({
            "map": key,
            "times_banned": s["times_banned"],
            "ban_1st": s["ban_pos"].get(1, 0), "ban_2nd": s["ban_pos"].get(2, 0),
            "ban_3rd": s["ban_pos"].get(3, 0), "ban_4th_plus": sum(v for k, v in s["ban_pos"].items() if k >= 4),
            "times_picked": s["times_picked"],
            "pick_1st": s["pick_pos"].get(1, 0), "pick_2nd": s["pick_pos"].get(2, 0),
            "pick_3rd_plus": sum(v for k, v in s["pick_pos"].items() if k >= 3),
            "times_decider": s["times_decider"],
            "total_appearances": total_appearances,
            "drafts_seen_in": len(s["drafts_seen"]),
        })
    rows.sort(key=lambda r: -r["total_appearances"])

    totals = {
        "total_drafts": total_drafts, "total_bans": total_bans,
        "total_picks": total_picks, "total_deciders": total_deciders,
    }
    return rows, totals


def render_markdown(rows: list[dict], totals: dict, tag_map: dict[str, Counter]) -> str:
    n = totals["total_drafts"]
    lines = []
    lines.append("# KTP Draft Map Stats")
    lines.append("")
    lines.append(f"Generated from {n} parsed pick/ban drafts pulled from the KTP match channel. "
                  "Pure aggregation over regex-parsed draft dumps, not manual tally -- see `extract_drafts.py` "
                  "for the source data and `scripts/discord_drafts/README.md` for how to re-crawl/re-extract.")
    lines.append("")
    lines.append(f"- Total drafts analyzed: **{n}**")
    lines.append(f"- Total ban actions: **{totals['total_bans']}**")
    lines.append(f"- Total pick actions: **{totals['total_picks']}**")
    lines.append(f"- Total resolved deciders: **{totals['total_deciders']}**")
    lines.append("")

    lines.append("## Map-by-map")
    lines.append("")
    lines.append("`Appearance %` = fraction of the 56 drafts the map showed up in at all (as a ban, pick, or "
                  "decider) -- a rough proxy for how often it was in that week's map pool.")
    lines.append("")
    lines.append("| Map | Banned | Ban 1st | Ban 2nd | Ban 3rd | Ban 4th+ | Ban % | Picked | Pick 1st | Pick 2nd | Pick % | Decider | Decider % | Appeared In | Appearance % |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        ban_pct = f"{100 * r['times_banned'] / n:.0f}%"
        pick_pct = f"{100 * r['times_picked'] / n:.0f}%"
        decider_pct = f"{100 * r['times_decider'] / n:.0f}%"
        appear_pct = f"{100 * r['drafts_seen_in'] / n:.0f}%"
        lines.append(
            f"| {r['map']} | {r['times_banned']} | {r['ban_1st']} | {r['ban_2nd']} | {r['ban_3rd']} | {r['ban_4th_plus']} | {ban_pct} "
            f"| {r['times_picked']} | {r['pick_1st']} | {r['pick_2nd']} | {pick_pct} "
            f"| {r['times_decider']} | {decider_pct} "
            f"| {r['drafts_seen_in']} | {appear_pct} |"
        )
    lines.append("")

    def top(key, k=5, reverse=True):
        return sorted(rows, key=lambda r: r[key], reverse=reverse)[:k]

    lines.append("## Quick reads")
    lines.append("")
    lines.append("**Most banned overall:**")
    for r in top("times_banned"):
        if r["times_banned"] == 0:
            break
        lines.append(f"- {r['map']}: banned {r['times_banned']} times ({100 * r['times_banned'] / n:.0f}% of drafts)")
    lines.append("")
    lines.append("**Most often banned first** (drawn as the very first ban -- the map captains fear most immediately):")
    for r in top("ban_1st"):
        if r["ban_1st"] == 0:
            break
        lines.append(f"- {r['map']}: first ban in {r['ban_1st']} drafts")
    lines.append("")
    lines.append("**Most picked overall:**")
    for r in top("times_picked"):
        if r["times_picked"] == 0:
            break
        lines.append(f"- {r['map']}: picked {r['times_picked']} times ({100 * r['times_picked'] / n:.0f}% of drafts)")
    lines.append("")
    lines.append("**Most often the decider** (survives every ban/pick -- neither team wanted it gone or claimed it):")
    for r in top("times_decider"):
        if r["times_decider"] == 0:
            break
        lines.append(f"- {r['map']}: decider {r['times_decider']} times ({100 * r['times_decider'] / n:.0f}% of drafts)")
    lines.append("")

    lines.append("## Methodology")
    lines.append("")
    lines.append("- Source: every message in the match channel matching the captains' "
                  "`<team emoji> (bans|picks) <map>` draft-dump format (56 found out of 1051 messages crawled "
                  "channel-wide, 2023-01-13 to 2026-05-04). See `drafts_needs_review.csv` for the 5 drafts that "
                  "didn't fully resolve (ambiguous decider, off-format team count) and were excluded here.")
    lines.append("- Ban/pick order (\"1st\", \"2nd\", ...) is each map's rank **among same-type actions in that "
                  "draft** (e.g. the 2nd ban recorded in a message, regardless of how many picks came between "
                  "bans), not the raw message line number.")
    lines.append("- Map names are normalized: a leading `dod_` prefix and a trailing build/season-config suffix "
                  "(`_b6`, `_s9a`, `_test`, `_deez`) are stripped, since those are clearly config tags rather than "
                  "different maps. Per league confirmation, each numbered-remake family is one map and is named for "
                  "its current version: `lennon`/`lennon5` -> **lennon2**, `railroad`/`rr2` -> **railroad2**, "
                  "`thunder` -> **thunder2**, `saints` -> **saints2** (`railyard` has no remake and stays as-is). "
                  "The audit table below shows exactly which raw tokens folded into each row.")
    lines.append("")
    lines.append("<details><summary>Raw map-name variants merged into each row above</summary>")
    lines.append("")
    lines.append("| Canonical | Raw variants seen |")
    lines.append("|---|---|")
    for key in sorted(tag_map):
        variants = ", ".join(f"`{v}` ({c})" for v, c in tag_map[key].most_common())
        lines.append(f"| {key} | {variants} |")
    lines.append("")
    lines.append("</details>")
    lines.append("")

    return "\n".join(lines)


def write_csv(rows: list[dict], totals: dict, out_path: str):
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "map", "times_banned", "ban_1st", "ban_2nd", "ban_3rd", "ban_4th_plus", "ban_pct",
            "times_picked", "pick_1st", "pick_2nd", "pick_3rd_plus", "pick_pct",
            "times_decider", "decider_pct", "appeared_in_drafts", "appearance_pct",
        ])
        n = totals["total_drafts"]
        for r in rows:
            w.writerow([
                r["map"], r["times_banned"], r["ban_1st"], r["ban_2nd"], r["ban_3rd"], r["ban_4th_plus"],
                round(100 * r["times_banned"] / n, 1),
                r["times_picked"], r["pick_1st"], r["pick_2nd"], r["pick_3rd_plus"],
                round(100 * r["times_picked"] / n, 1),
                r["times_decider"], round(100 * r["times_decider"] / n, 1),
                r["drafts_seen_in"], round(100 * r["drafts_seen_in"] / n, 1),
            ])


def _cli():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("channel_id", nargs="?", help="unused except for a friendlier error message; reads data/drafts.json")
    ap.add_argument("--out", default=os.path.join(HERE, "data", "MAP_STATS.md"))
    ap.add_argument("--out-csv", default=os.path.join(HERE, "data", "map_stats.csv"))
    args = ap.parse_args()

    drafts_path = os.path.join(HERE, "data", "drafts.json")
    if not os.path.exists(drafts_path):
        raise SystemExit(f"no drafts.json at {drafts_path} -- run extract_drafts.py first")

    records = load_drafts(drafts_path)
    tag_map = build_map_tag_map(records)
    rows, totals = compute_stats(records)
    report = render_markdown(rows, totals, tag_map)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(report)
    write_csv(rows, totals, args.out_csv)

    print(f"{len(rows)} canonical maps across {totals['total_drafts']} drafts")
    print(f"wrote {args.out}")
    print(f"wrote {args.out_csv}")


if __name__ == "__main__":
    _cli()
