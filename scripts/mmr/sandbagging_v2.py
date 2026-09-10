"""Sandbagging pass 2, real division history now available (website pull,
2026-09-09). Combines two signals per the user's own correction: a real
division DROP (held a higher division in an earlier season) AND a stat
outlier in the CURRENT (lower) division. Either signal alone is weak --
together, on a real drop with real dominance, it is the actual shape
described: average-or-fine up top, then noticeably better after moving down.

Division names, higher to lower: Gold > Silver > Bronze.
"""
import csv, json
from pathlib import Path

DATA = Path(__file__).parent / "data"
RANK = {"Gold": 0, "Silver": 1, "Bronze": 2}


def main():
    history = json.loads((Path(__file__).with_name("division_history.json")).read_text())
    names = json.load(open(Path(__file__).parents[1] / "real-match-tier2-20260906" / "season_names.json"))
    for row in csv.DictReader(open("scratch/missing_names.tsv"), delimiter="\t"):
        names[row["playerId"]] = row["lastName"]

    # Re-derive the S9 per-player kills-per-match z-score (same source as
    # sandbagging_s9.py) to pair with real division history.
    import sandbagging_s9 as s9
    stats = s9.player_division_and_stats()
    import statistics, collections
    by_div = collections.defaultdict(list)
    for pid, s in stats.items():
        by_div[s["division"]].append((pid, s))
    z_by_pid = {}
    for div, players in by_div.items():
        kpms = [s["kills_per_match"] for _, s in players]
        mean, stdev = statistics.mean(kpms), (statistics.pstdev(kpms) or 1.0)
        for pid, s in players:
            z_by_pid[pid] = round((s["kills_per_match"] - mean) / stdev, 2)

    rows = []
    for pid, s in stats.items():
        hist = history.get(str(pid), [])
        prior = [r for r in hist if r["season"] is not None and r["season"] < 9 and r["division"] in RANK]
        best_prior_rank = min((RANK[r["division"]] for r in prior), default=None)
        current_rank = RANK.get(s["division"])
        moved_down = best_prior_rank is not None and current_rank is not None and best_prior_rank < current_rank
        best_prior_div = {v: k for k, v in RANK.items()}.get(best_prior_rank)
        rows.append(dict(pid=pid, name=names.get(str(pid), "?"), current_division=s["division"],
                          best_prior_division=best_prior_div, moved_down=moved_down,
                          z=z_by_pid.get(pid), seasons_seen=sorted({r["season"] for r in hist if r["season"]})))

    flagged = [r for r in rows if r["moved_down"] and r["z"] is not None and r["z"] > 1.0]
    flagged.sort(key=lambda r: -r["z"])

    out = ["# Sandbagging candidates v2 -- real division drop + S9 stat outlier (2026-09-09)\n",
           "Both signals now real: a genuine division DROP (held a higher division in an",
           "earlier season, from the website's S1-S10 history) AND a kills-per-match",
           "outlier in the CURRENT (lower) division (S9). This is the actual shape from",
           "the user's own correction -- not just 'good player in a low division,' but",
           "'used to play up, now stat-dominates down.' Still a screening list for admin",
           "review, not a verdict: a real drop can also mean a team disbanded, a player",
           "took a season off and came back rusty-then-recovered, or genuine team-strength",
           "changes unrelated to the individual.\n",
           "| PID | Name | Best prior division | Current (S9) | S9 kills z-score | Seasons seen |",
           "|---|---|---|---|---|---|"]
    for r in flagged:
        name = (r["name"] or "?").replace("|", "\\|")
        out.append(f"| {r['pid']} | {name} | {r['best_prior_division']} | {r['current_division']} | "
                    f"{r['z']} | {','.join(f'S{s}' for s in r['seasons_seen'])} |")
    Path(__file__).with_name("SANDBAGGING_CANDIDATES_V2.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"{len(rows)} S9 players checked against real division history")
    print(f"{sum(1 for r in rows if r['moved_down'])} had a real division drop into S9")
    print(f"{len(flagged)} flagged (real drop AND z>1.0):")
    for r in flagged:
        print(f"  {r['name']} ({r['pid']}): {r['best_prior_division']} -> {r['current_division']}, z={r['z']}")


if __name__ == "__main__":
    main()
