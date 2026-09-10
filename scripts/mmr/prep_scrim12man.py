"""Pre-season prep from scrim/12man rosters (match_type 1/2) while real S1-10
website data is blocked. NOT fed into the rating ladder: these matches carry
no winner labels (ktp_team_score_observations empty) and are ephemeral-14d
by policy (team_score_telemetry.retention_class) -- informal pickup play,
never meant to be permanent history. Two things ARE usable without labels:
  1. Exposure/connectivity graph: who has real reps and who is isolated,
     going into S10/S11 -- informs provisional handling on day one.
  2. KTPR v2 warm-start signal: outcome-independent per-player form from the
     81 already-computed Tier-2 report JSONs (all scrim/12man; S10 hasn't
     started and S9 predates the Tier-2 producers).
"""
import csv, json, collections
from pathlib import Path

DATA = Path(__file__).parent / "data"
REPORTS = Path(__file__).parents[1] / "real-match-tier2-20260906" / "prod-reports"
NAMES = json.load(open(Path(__file__).parents[1] / "real-match-tier2-20260906" / "season_names.json")) \
    if (Path(__file__).parents[1] / "real-match-tier2-20260906" / "season_names.json").exists() else {}


def load_identity_merges():
    """duplicate player_id -> canonical player_id; see ladder.py / data/identity_merges.json."""
    raw = json.loads((DATA / "identity_merges.json").read_text())
    return {int(k): int(v) for k, v in raw.items() if k != "_comment"}


MERGES = load_identity_merges()


def load_s9_players():
    s = {r["match_id"]: r for r in csv.DictReader(open(DATA / "s9_scores.tsv"), delimiter="\t")}
    pids = set()
    for r in csv.DictReader(open(DATA / "s9_players.tsv"), delimiter="\t"):
        if r["match_id"] in s and r["excluded"] == "0":
            pids.add(MERGES.get(int(r["player_id"]), int(r["player_id"])))
    return pids


def exposure_graph():
    rows = list(csv.DictReader(open(DATA / "scrim_12man_rosters.tsv"), delimiter="\t"))
    matches = collections.defaultdict(set)
    for r in rows:
        pid = int(r["player_id"])
        matches[r["match_id"]].add(MERGES.get(pid, pid))
    counts = collections.Counter(p for ps in matches.values() for p in ps)

    parent = {}
    def find(x):
        while parent.setdefault(x, x) != x:
            x = parent[x]
        return x
    for ps in matches.values():
        ps = list(ps)
        for p in ps[1:]:
            parent[find(p)] = find(ps[0])
    comps = collections.defaultdict(set)
    for p in parent:
        comps[find(p)].add(p)
    comp_sizes = sorted((len(c) for c in comps.values()), reverse=True)

    s9 = load_s9_players()
    bridge = sum(1 for p in counts if p in s9)
    return dict(
        matches=len(matches), players=len(counts),
        matches_per_player_median=sorted(counts.values())[len(counts) // 2],
        matches_per_player_min=min(counts.values()), matches_per_player_max=max(counts.values()),
        components=comp_sizes[:5], isolated_players=sum(1 for c in comp_sizes if c == 1),
        s9_carryover_players=bridge, s9_total_players=len(s9),
        new_since_s9=len(counts) - bridge,
        low_volume_lt5=sum(1 for c in counts.values() if c < 5),
    ), counts


def warm_start():
    """Outcome-independent per-player form from the 81 Tier-2 reports
    (shadow_explorations.ktpr_v2 -- private shadow, uncalibrated, no
    rating_effect; matches match_analytics's own caveat verbatim)."""
    agg = collections.defaultdict(lambda: dict(matches=0, rating=0.0, swing=0.0, output=0.0, multikill=0.0, name=""))
    for f in sorted(REPORTS.glob("*.json")):
        d = json.loads(f.read_text())
        players = d.get("shadow_explorations", {}).get("ktpr_v2", {}).get("players", [])
        for p in players:
            pid = int(p["player_id"])
            a = agg[MERGES.get(pid, pid)]
            a["matches"] += 1
            a["rating"] += p["rating"]
            a["name"] = p.get("player_name_at_match", a["name"])
            for k in ("swing", "output", "multikill"):
                a[k] += p["components"][k]
    return {pid: {**v, **{k: round(v[k] / v["matches"], 4) for k in ("rating", "swing", "output", "multikill")}}
            for pid, v in agg.items() if v["matches"] > 0}


def main():
    stats, counts = exposure_graph()
    print("scrim/12man exposure:", json.dumps(stats, indent=1))
    warm = warm_start()
    print(f"\nKTPR v2 warm-start coverage: {len(warm)} players scored across Tier-2 reports"
          f" (found ktpr_v2 payload in {'some' if warm else 'NO'} report files)")
    out = {"exposure": stats, "matches_per_player": counts, "warm_start": warm}
    Path(__file__).with_name("prep_scrim12man.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
