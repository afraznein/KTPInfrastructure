"""Phase 3 lite: mine backtest.json for confident wrong predictions on S9 and
build a dossier from what's actually available there (kills/deaths, roster
familiarity, margin). Full dossiers (KTPR v2 swing/output/multikill deltas)
wait for labeled Tier-2 matches -- S9 predates the Tier-2 producers.
"""
import csv, json, collections
from pathlib import Path

DATA = Path(__file__).parent / "data"
THRESHOLD = 0.70  # confident-miss cutoff from the research doc


def player_kills(match_id):
    """team -> {player_id: (kills, deaths)} for one match, halves 1-2 summed."""
    out = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
    for r in csv.DictReader(open(DATA / "s9_players.tsv"), delimiter="\t"):
        if r["match_id"] == match_id and r["half"] in ("1", "2") and r["excluded"] == "0":
            k = out[r["team"]][r["player_id"]]
            k[0] += int(r["kills"]); k[1] += int(r["deaths"])
    return out


def main():
    bt = json.loads((Path(__file__).with_name("backtest.json")).read_text())
    rows = bt["per_match"]["openskill_pl"]
    warmup = 30  # matches ladder.py's default reporting warmup
    misses = [r for i, r in enumerate(rows) if i >= warmup
              and abs(r["p_t1"] - r["y"]) > THRESHOLD]
    misses.sort(key=lambda r: -abs(r["p_t1"] - r["y"]))

    names = json.load(open(Path(__file__).parents[1] / "real-match-tier2-20260906" / "season_names.json"))
    for row in csv.DictReader(open("scratch/missing_names.tsv"), delimiter="\t"):
        names[row["playerId"]] = row["lastName"]

    out = ["# Upset dossiers -- confident misses, S9 corpus (OpenSkill, warmup 30)\n",
           f"{len(misses)} matches where the model's win probability for the roster-1 side"
           f" was more than {THRESHOLD:.0%} away from the actual result. Kills/deaths only --"
           " S9 predates KTPR v2, so no swing/output/multikill breakdown is possible here."
           " Full dossiers (why a favorite lost, which component predicted it) wait for"
           " labeled Tier-2 matches.\n"]
    for r in misses:
        winner = "roster team 1" if r["y"] == 1.0 else "roster team 2"
        favored = "team 1" if r["p_t1"] > 0.5 else "team 2"
        kd = player_kills(r["match_id"])
        out.append(f"## {r['match_id']} -- {r['map']} ({r['when']})")
        out.append(f"- Model gave roster {favored} a {max(r['p_t1'], 1-r['p_t1']):.0%} chance; "
                    f"{winner} won by {r['margin']} points. Roster familiarity: {r['familiarity']:.2f}.")
        for team in ("1", "2"):
            lines = []
            for pid, (k, d) in sorted(kd[team].items(), key=lambda kv: -kv[1][0]):
                nm = names.get(pid, "?")
                lines.append(f"{nm} ({pid}) {k}/{d}")
            out.append(f"  - team {team}: " + ", ".join(lines))
        out.append("")
    Path(__file__).with_name("UPSET_DOSSIERS.md").write_text("\n".join(out), encoding="utf-8")
    print(f"{len(misses)} confident misses written to UPSET_DOSSIERS.md")


if __name__ == "__main__":
    main()
