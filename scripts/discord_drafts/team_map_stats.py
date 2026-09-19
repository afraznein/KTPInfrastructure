"""
Per-team pick/ban map stats: for each team (canonicalized the same way as
build_rosters.py, so season-to-season emoji-tag variants like Team_Revo /
Team_Revo2 pool together), how many times they banned/picked each map, and
their signature first ban. Pure aggregation over drafts.json, no LLM,
deterministic and re-runnable.

Deciders aren't attributed to a team here -- a decider is whichever map
neither team eliminated or claimed, not a choice either team made (see
map_stats.py for decider stats).

Usage:
    python team_map_stats.py [--out data/TEAM_MAP_STATS.md]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter, defaultdict

from build_rosters import canon_team_key, display_name, known_team_keys
from map_stats import canon_map_key

HERE = os.path.dirname(os.path.abspath(__file__))


def load_drafts(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_team_stats(records: list[dict]) -> dict[str, dict]:
    stats: dict[str, dict] = defaultdict(lambda: {
        "drafts": set(), "bans": Counter(), "picks": Counter(), "first_ban": Counter(),
    })
    for r in records:
        seen_first_ban: set[str] = set()
        for a in r["actions"]:
            team = canon_team_key(a["team"])
            m = canon_map_key(a["map"])
            s = stats[team]
            s["drafts"].add(r["message_id"])
            if a["action"] == "ban":
                s["bans"][m] += 1
                if team not in seen_first_ban:
                    seen_first_ban.add(team)
                    s["first_ban"][m] += 1
            else:
                s["picks"][m] += 1
    return stats


def render_markdown(stats: dict[str, dict], tag_map: dict[str, Counter], total_drafts: int) -> str:
    teams = sorted(stats.keys(), key=lambda t: (-len(stats[t]["drafts"]), t))

    lines = []
    lines.append("# KTP Draft Map Stats — By Team")
    lines.append("")
    lines.append(f"Per-team breakdown of the same {total_drafts} drafts covered in `MAP_STATS.md`, "
                  "using the same map-name alignment (lennon2/railroad2/thunder2/saints2 families, dod_ prefix and "
                  "config-suffix stripping) and the same team-tag normalization used in `build_rosters.py` "
                  "(season-to-season emoji variants like `Team_Revo`/`Team_Revo2` pool together -- see "
                  "`team_tag_map.csv` for the merge audit trail). Deciders aren't attributed to a team here since "
                  "neither team chose the decider map -- see `MAP_STATS.md` for decider stats.")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Team | Drafts | Total Bans | Total Picks | Top Ban | Top Pick | Signature 1st Ban |")
    lines.append("|---|---:|---:|---:|---|---|---|")
    for t in teams:
        s = stats[t]
        name = display_name(tag_map[t]) if t in tag_map else t
        top_ban = s["bans"].most_common(1)
        top_pick = s["picks"].most_common(1)
        first_ban = s["first_ban"].most_common(1)
        lines.append(
            f"| {name} | {len(s['drafts'])} | {sum(s['bans'].values())} | {sum(s['picks'].values())} "
            f"| {top_ban[0][0] + f' ({top_ban[0][1]})' if top_ban else '-'} "
            f"| {top_pick[0][0] + f' ({top_pick[0][1]})' if top_pick else '-'} "
            f"| {first_ban[0][0] + f' ({first_ban[0][1]})' if first_ban else '-'} |"
        )
    lines.append("")

    lines.append("## Per-team detail")
    lines.append("")
    lines.append("Full ban/pick count per map for each team (only maps that team actually touched are listed).")
    lines.append("")
    for t in teams:
        s = stats[t]
        name = display_name(tag_map[t]) if t in tag_map else t
        lines.append(f"<details><summary><b>{name}</b> — {len(s['drafts'])} draft(s)</summary>")
        lines.append("")
        maps = sorted(set(s["bans"]) | set(s["picks"]))
        lines.append("| Map | Banned | Picked | 1st Ban |")
        lines.append("|---|---:|---:|---:|")
        for m in maps:
            lines.append(f"| {m} | {s['bans'].get(m, 0)} | {s['picks'].get(m, 0)} | {s['first_ban'].get(m, 0)} |")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    return "\n".join(lines)


def write_csvs(stats: dict[str, dict], tag_map: dict[str, Counter], out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    teams = sorted(stats.keys(), key=lambda t: (-len(stats[t]["drafts"]), t))

    with open(os.path.join(out_dir, "team_map_stats_summary.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["team", "drafts", "total_bans", "total_picks", "top_ban", "top_ban_count", "top_pick", "top_pick_count", "signature_1st_ban", "signature_1st_ban_count"])
        for t in teams:
            s = stats[t]
            name = display_name(tag_map[t]) if t in tag_map else t
            top_ban = s["bans"].most_common(1)
            top_pick = s["picks"].most_common(1)
            first_ban = s["first_ban"].most_common(1)
            w.writerow([
                name, len(s["drafts"]), sum(s["bans"].values()), sum(s["picks"].values()),
                top_ban[0][0] if top_ban else "", top_ban[0][1] if top_ban else 0,
                top_pick[0][0] if top_pick else "", top_pick[0][1] if top_pick else 0,
                first_ban[0][0] if first_ban else "", first_ban[0][1] if first_ban else 0,
            ])

    with open(os.path.join(out_dir, "team_map_stats_detail.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["team", "map", "banned", "picked", "first_ban"])
        for t in teams:
            s = stats[t]
            name = display_name(tag_map[t]) if t in tag_map else t
            maps = sorted(set(s["bans"]) | set(s["picks"]))
            for m in maps:
                w.writerow([name, m, s["bans"].get(m, 0), s["picks"].get(m, 0), s["first_ban"].get(m, 0)])


def _cli():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(HERE, "data", "TEAM_MAP_STATS.md"))
    ap.add_argument("--out-dir", default=os.path.join(HERE, "data"), help="directory for the CSV outputs")
    args = ap.parse_args()

    drafts_path = os.path.join(HERE, "data", "drafts.json")
    if not os.path.exists(drafts_path):
        raise SystemExit(f"no drafts.json at {drafts_path} -- run extract_drafts.py first")

    records = load_drafts(drafts_path)
    tag_map = known_team_keys(records)
    stats = compute_team_stats(records)
    report = render_markdown(stats, tag_map, len(records))

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(report)
    write_csvs(stats, tag_map, args.out_dir)

    print(f"{len(stats)} teams")
    print(f"wrote {args.out}")
    print(f"wrote team_map_stats_summary.csv / team_map_stats_detail.csv to {args.out_dir}")


if __name__ == "__main__":
    _cli()
