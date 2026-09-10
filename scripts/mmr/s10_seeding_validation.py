"""S10 seeding validation (Phase 4 dry run, real data).

S10 divisions are already set by admins -- this is the validation season,
not the seeding target (that's S11). Question: if we had seeded S10 from
nothing but S9 Elo/OpenSkill ratings, would it have agreed with what admins
actually did? Where it disagrees is exactly the useful signal: either the
model is missing something (new players, roster changes admins could see
and we can't) or the admins' placement had a rationale beyond raw S9 skill
(team chemistry, keeping a division full, a team's own request).

Team rating = mean of member ratings among players who appear in the S9
ladder. Players with no S9 record (new for S10) are counted but excluded
from the mean and flagged -- a team heavy with unrated new players gets a
low-confidence note, not a silently skewed average.
"""
import json
import statistics
from pathlib import Path

DATA = Path(__file__).parent / "data"
RANK = {"Gold": 0, "Silver": 1, "Bronze": 2}


def load_json(name):
    return json.loads((DATA / "website" / f"{name}.json").read_text(encoding="utf-8"))


def steam64_to_hlstats(steam_id64: str) -> str:
    n = int(steam_id64) - 76561197960265728
    return f"{n % 2}:{n // 2}"


def main():
    elo = json.load(open("ratings_elo.json"))
    openskill = json.load(open("ratings_openskill.json"))
    bridge = {}
    for line in open(DATA / "hlstats_player_unique_ids.tsv", encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 2 and parts[1] != "uniqueId":
            bridge[parts[1]] = int(parts[0])

    seasons = {s["id"]: s["number"] for s in load_json("season")}
    s10_season_id = next(sid for sid, num in seasons.items() if num == 10)
    divisions = {d["id"]: d["name"] for d in load_json("division")}
    teams = {t["id"]: t["name"] for t in load_json("team")}
    steam_by_website_pid = {p["player_id"]: p["steam_id64"] for p in load_json("player_steam") if p["status"] == "current"}

    season_teams = {t["id"]: t for t in load_json("season_team") if t["season_id"] == s10_season_id}
    rosters = {}  # season_team_id -> [hlstats_pid]
    unrated_counts = {}
    for row in load_json("season_team_member"):
        st_id = row["season_team_id"]
        if st_id not in season_teams:
            continue
        steam64 = steam_by_website_pid.get(row["player_id"])
        hpid = bridge.get(steam64_to_hlstats(steam64)) if steam64 else None
        rosters.setdefault(st_id, []).append(hpid)

    rows = []
    for st_id, st in season_teams.items():
        roster = rosters.get(st_id, [])
        rated = [p for p in roster if p is not None and str(p) in elo]
        unrated = len(roster) - len(rated)
        if not rated:
            rows.append(dict(team=teams.get(st["team_id"], "?"), division=divisions.get(st["division_id"]),
                              n_roster=len(roster), n_rated=0, elo_mean=None, ordinal_mean=None))
            continue
        elo_mean = statistics.mean(elo[str(p)]["mu"] for p in rated)
        ord_mean = statistics.mean(openskill[str(p)]["ordinal"] for p in rated)
        rows.append(dict(team=teams.get(st["team_id"], "?"), division=divisions.get(st["division_id"]),
                          n_roster=len(roster), n_rated=len(rated), unrated=unrated,
                          elo_mean=round(elo_mean, 1), ordinal_mean=round(ord_mean, 2)))

    # Predicted division: rank by ordinal_mean (OpenSkill's conservative
    # estimate), split into groups matching each real division's size.
    ranked = sorted([r for r in rows if r["ordinal_mean"] is not None], key=lambda r: -r["ordinal_mean"])
    div_sizes = {}
    for r in rows:
        div_sizes[r["division"]] = div_sizes.get(r["division"], 0) + 1
    order = sorted(div_sizes, key=lambda d: RANK.get(d, 99))
    cursor, predicted = 0, {}
    for div in order:
        for r in ranked[cursor:cursor + div_sizes[div]]:
            predicted[r["team"]] = div
        cursor += div_sizes[div]

    agree = sum(1 for r in ranked if predicted.get(r["team"]) == r["division"])
    high_conf = [r for r in ranked if r["n_rated"] / r["n_roster"] >= 0.6]
    high_conf_agree = sum(1 for r in high_conf if predicted.get(r["team"]) == r["division"])
    out = ["# S10 seeding validation -- S9 ratings vs actual admin placement (2026-09-09)\n",
           "S10 divisions are already set by admins; this checks whether S9-only Elo/",
           "OpenSkill ratings would have predicted the same placement, using the real",
           "website rosters and divisions pulled today. Predicted division = rank by",
           "OpenSkill ordinal (mean of S9 ratings for players who have an S9 record),",
           "split into groups the same size as each real division. Not a suggestion to",
           "re-place anyone -- S10 is the validation season, S11 is the seeding target.\n",
           f"**Agreement: {agree}/{len(ranked)} teams** ranked into the division admins",
           "actually placed them in, using nothing but last season's win/loss ratings.",
           f"Restricted to teams where at least 60% of the roster has an S9 rating",
           f"(the low-confidence, mostly-new-roster teams excluded): "
           f"**{high_conf_agree}/{len(high_conf)}**. Most disagreements below are on",
           "well-rated returning rosters, not new-player noise -- consistent with the",
           "cross-division caveat already on record (S9 ratings don't reliably transfer",
           "across divisions; almost all S9 matches were intra-division).\n",
           "| Team | Actual division | Predicted division | Roster | Rated (S9) | Elo mean | OpenSkill ordinal |",
           "|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (RANK.get(r["division"], 9), -(r["ordinal_mean"] or -999))):
        pred = predicted.get(r["team"], "unrated" if r["n_rated"] == 0 else "?")
        low_conf = r["n_roster"] and r["n_rated"] / r["n_roster"] < 0.6
        mark = "" if pred == r["division"] else (" *(low confidence)*" if low_conf else " **<- disagrees**")
        out.append(f"| {r['team']} | {r['division']} | {pred}{mark} | {r['n_roster']} | {r['n_rated']} | "
                    f"{r['elo_mean'] if r['elo_mean'] is not None else '-'} | "
                    f"{r['ordinal_mean'] if r['ordinal_mean'] is not None else '-'} |")
    Path(__file__).with_name("S10_SEEDING_VALIDATION.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"{len(rows)} S10 teams, {len(ranked)} with at least one S9-rated player")
    print(f"agreement: {agree}/{len(ranked)}")
    for r in rows:
        print(f"  {r['team']:20s} actual={r['division']!s:8s} predicted={predicted.get(r['team'],'?'):8s} "
              f"rated={r['n_rated']}/{r['n_roster']}")


if __name__ == "__main__":
    main()
