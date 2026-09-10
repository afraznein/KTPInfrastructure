"""Sandbagging detector, S9 pass 1: flag players whose per-match performance
is a statistical outlier relative to their OWN division's peers. A truly
Gold-caliber player parked in Silver/Bronze should show up as dominating
their division's own distribution, not just winning -- Elo/OpenSkill already
discount predictable blowout wins, so win/loss alone under-detects this
(the whole point of sandbagging is picking weak opponents on purpose).

Pass 1 uses kills/deaths only (S9 predates KTPR v2). Pass 2, once the
website key lands, adds: division HISTORY (a player who played Gold last
season and Silver this season is a much stronger signal than a stat
outlier alone) and KTPR v2 output/swing z-scores once Tier-2 stats exist
for labeled divisional matches.
"""
import csv, json, statistics, collections
from pathlib import Path

DATA = Path(__file__).parent / "data"


def team_division_map():
    """team name (upper) -> division, from the S9 fixture sheet."""
    out = {}
    for r in csv.DictReader(open(DATA / "s9_fixtures.tsv"), delimiter="\t"):
        if r["division"] != "NULL":
            out[r["team_a"].upper()] = r["division"]
            out[r["team_b"].upper()] = r["division"]
    return out


def player_division_and_stats():
    scores = {r["match_id"]: r for r in csv.DictReader(open(DATA / "s9_scores.tsv"), delimiter="\t")}
    teamdiv = team_division_map()
    # roster team ('1'/'2') per match -> canonical team name, via the same
    # side mapping as ladder.py (score a = roster team 2, b = roster team 1).
    match_team_name = {}
    for mid, s in scores.items():
        if s["anomaly"] != "NULL":
            continue
        ta, tb = s["team_a"].upper(), s["team_b"].upper()
        match_team_name[mid] = {"2": ta, "1": tb}

    player_div_votes = collections.defaultdict(collections.Counter)
    player_kd = collections.defaultdict(lambda: [0, 0])  # kills, deaths
    merges = json.loads((DATA / "identity_merges.json").read_text())
    merges = {int(k): int(v) for k, v in merges.items() if k != "_comment"}

    for r in csv.DictReader(open(DATA / "s9_players.tsv"), delimiter="\t"):
        if r["half"] not in ("1", "2") or r["excluded"] != "0":
            continue
        mid = r["match_id"]
        if mid not in match_team_name:
            continue
        pid = merges.get(int(r["player_id"]), int(r["player_id"]))
        team_name = match_team_name[mid].get(r["team"])
        div = teamdiv.get(team_name)
        if div:
            player_div_votes[pid][div] += 1
        s = player_kd[pid]
        s[0] += int(r["kills"]); s[1] += int(r["deaths"])

    # matches/player counted separately (halves collapse to one match)
    match_counts = collections.Counter()
    seen = set()
    for r in csv.DictReader(open(DATA / "s9_players.tsv"), delimiter="\t"):
        if r["half"] in ("1", "2") and r["excluded"] == "0":
            pid = merges.get(int(r["player_id"]), int(r["player_id"]))
            key = (pid, r["match_id"])
            if key not in seen:
                seen.add(key)
                match_counts[pid] += 1

    out = {}
    for pid, votes in player_div_votes.items():
        div = votes.most_common(1)[0][0]
        k, d = player_kd[pid]
        m = match_counts[pid]
        if m == 0:
            continue
        out[pid] = dict(division=div, matches=m, kills=k, deaths=d,
                         kd=round(k / max(d, 1), 3), kills_per_match=round(k / m, 2))
    return out


def main():
    stats = player_division_and_stats()
    names = json.load(open(Path(__file__).parents[1] / "real-match-tier2-20260906" / "season_names.json"))
    for row in csv.DictReader(open("scratch/missing_names.tsv"), delimiter="\t"):
        names[row["playerId"]] = row["lastName"]

    by_div = collections.defaultdict(list)
    for pid, s in stats.items():
        by_div[s["division"]].append((pid, s))

    rows = []
    for div, players in by_div.items():
        kpms = [s["kills_per_match"] for _, s in players]
        mean, stdev = statistics.mean(kpms), (statistics.pstdev(kpms) or 1.0)
        for pid, s in players:
            z = round((s["kills_per_match"] - mean) / stdev, 2)
            rows.append(dict(pid=pid, name=names.get(str(pid), "?"), division=div,
                              matches=s["matches"], kpm=s["kills_per_match"], kd=s["kd"],
                              div_mean_kpm=round(mean, 2), z=z))
    rows.sort(key=lambda r: -r["z"])

    esc_pipe = chr(124)
    escaped_pipe = chr(92) + chr(124)
    out = ["# Sandbagging candidates -- S9 pass 1 (kills/deaths only, 2026-09-07)\n",
           "Flags players whose kills-per-match is a statistical outlier within their",
           "OWN division, on the theory that a genuinely Gold-caliber player parked in",
           "Silver/Bronze on purpose will dominate that division's own stat line --",
           "win/loss rating alone under-detects this, since beating weak opponents on",
           "purpose is exactly the predictable win Elo/OpenSkill already discount.",
           "",
           "**This is a screening list for admin review, not an accusation.** A high",
           "z-score also fits a genuinely dominant player on a weak team, a stat-padder",
           "in blowouts, or small-sample noise (some players here have 5-6 matches).",
           "Division history (did this player play Gold last season?) and KTPR v2",
           "output/swing z-scores (once Tier-2 stats exist for labeled divisional",
           "matches) are the real second and third signals -- both wait on the website",
           "key. Kills-per-match alone is a first, coarse filter only.",
           "",
           "| PID | Name | Division | Matches | Kills/match | Division mean | Z (within division) | K/D |",
           "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        name = (r["name"] or "?").replace(esc_pipe, escaped_pipe)
        out.append(f"| {r['pid']} | {name} | {r['division']} | {r['matches']} | {r['kpm']} | "
                    f"{r['div_mean_kpm']} | {r['z']} | {r['kd']} |")
    Path(__file__).with_name("SANDBAGGING_CANDIDATES.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    flagged = [r for r in rows if r["division"] in ("Silver", "Bronze") and r["z"] > 1.5]
    print(f"{len(rows)} players scored, {len(flagged)} flagged (Silver/Bronze, z>1.5)")
    for r in flagged[:10]:
        print(f"  {r['name']} ({r['pid']}) {r['division']} z={r['z']} kpm={r['kpm']} (div mean {r['div_mean_kpm']})")


if __name__ == "__main__":
    main()
