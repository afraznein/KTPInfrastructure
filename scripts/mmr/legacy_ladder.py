"""Extend the rating ladder back through S1-S8 using the website's legacy
data (legacy_match + legacy_player_season), pulled 2026-09-09. S9 keeps
using the higher-fidelity ktp_s9_repair_* corpus (actual per-match rosters
from hlstats frag events) via ladder.load_matches() -- legacy_match only
fills S1-S8, where no hlstats event data exists at all.

Approximation, documented not hidden: legacy rosters are SEASON-level (one
roster per team per season from legacy_player_season), not match-level.
Every registered player on a team is credited/blamed for every match that
team played that season, including bench players who may not have played a
given fixture. This is the best signal available for S1-S8 (no per-match
lineups exist pre-hlstats), but it is noisier than S9's real per-match
rosters -- expect this history to help less per-match than S9 does.

Filters: score_unit == 'points' only (series_maps is a different unit, never
compared -- SCHEMA.md), not a forfeit (150-0 is an award, not a played
result), both scores present, no tie, and BOTH teams' rosters must resolve
to at least MIN_TEAM real hlstatsx players for that season.
"""
import json
from collections import defaultdict
from pathlib import Path

import ladder as L

DATA = Path(__file__).parent / "data"
MIN_TEAM = 4


def load_json(name):
    return json.loads((DATA / "website" / f"{name}.json").read_text(encoding="utf-8"))


def steam64_to_hlstats(steam_id64: str) -> str:
    n = int(steam_id64) - 76561197960265728
    return f"{n % 2}:{n // 2}"


def load_legacy_matches(exclude_season_numbers=(9, 10)):
    bridge = {}
    for line in open(DATA / "hlstats_player_unique_ids.tsv", encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 2 and parts[1] != "uniqueId":
            bridge[parts[1]] = int(parts[0])
    merges = L.load_identity_merges()

    seasons = {s["id"]: s["number"] for s in load_json("season")}
    teams_by_id = {t["id"]: t for t in load_json("legacy_season_team")}

    # (season_id, team_name) -> set of hlstats player_ids
    rosters = defaultdict(set)
    unresolved_stints = 0
    for row in load_json("legacy_player_season"):
        team = teams_by_id.get(row["legacy_season_team_id"])
        if not team or not row.get("steam_id64"):
            continue
        pid = bridge.get(steam64_to_hlstats(row["steam_id64"]))
        if pid is None:
            unresolved_stints += 1
            continue
        rosters[(row["season_id"], team["name"])].add(merges.get(pid, pid))

    out, skipped = [], 0
    for r in load_json("legacy_match"):
        num = seasons.get(r["season_id"])
        if num in exclude_season_numbers:
            continue
        if r["score_unit"] != "points" or r["forfeit"] or r["score_a"] is None or r["score_b"] is None:
            continue
        if not r["played_on"]:
            continue  # chronological ordering needs a real date -- see ladder.py's no-shuffle rule
        if r["score_a"] == r["score_b"]:
            continue
        t1 = rosters.get((r["season_id"], r["team_a"]), set())
        t2 = rosters.get((r["season_id"], r["team_b"]), set())
        if len(t1) < MIN_TEAM or len(t2) < MIN_TEAM:
            skipped += 1
            continue
        out.append(dict(match_id=f"legacy-S{num}-{r['team_a']}-{r['team_b']}-{r['played_on']}",
                         when=r["played_on"], map=r["map"] or "?",
                         t1=sorted(t1), t2=sorted(t2),
                         y=1.0 if r["score_a"] > r["score_b"] else 0.0,  # t1 wins iff team_a wins
                         margin=abs(r["score_a"] - r["score_b"]), season=num))
    print(f"legacy: {len(out)} usable matches, {skipped} skipped (roster too small/unresolved), "
          f"{unresolved_stints} player-season stints had no hlstatsx match")
    return out


def combined_matches():
    legacy = load_legacy_matches()
    s9 = L.load_matches()
    for m in s9:
        m["season"] = 9
    combined = legacy + s9
    combined.sort(key=lambda m: m["when"])
    return combined, len(legacy)


def main():
    combined, n_legacy = combined_matches()
    print(f"combined corpus: {len(combined)} matches ({n_legacy} legacy S1-S8 + {len(combined) - n_legacy} S9)")

    # Apples-to-apples: evaluate on the SAME 63 held-out S9 matches (S9[30:])
    # in both cases -- baseline updates on S9[:30] only (cold start), the
    # legacy variant updates on all of S1-S8 plus S9[:30] first. Same test
    # set either way, so the only difference is what the model saw before it.
    s9_only = [m for m in combined if m["season"] == 9]
    holdout = s9_only[30:]
    baseline, _ = L.backtest(L.OpenSkill(), s9_only, warmup=30)

    def run_with_widen(factor):
        """factor=1.0 replicates the earlier unwidened run (kept for the
        record); factor>1.0 re-widens sigma at every real season boundary
        crossed (S1->S2, ..., S8->S9), same mechanism season_boundary_
        rehearsal.py proved out on a fake boundary."""
        m2 = L.OpenSkill()
        season_seen = None
        for m in combined:
            if m["season"] == 9:
                break
            if season_seen is not None and m["season"] != season_seen and factor != 1.0:
                m2.widen_at_season_boundary(factor)
            season_seen = m["season"]
            m2.update(m["t1"], m["t2"], m["y"])
        if factor != 1.0:
            m2.widen_at_season_boundary(factor)  # S8 -> S9 boundary
        for m in s9_only[:30]:
            m2.update(m["t1"], m["t2"], m["y"])
        preds, ys = [], []
        for m in holdout:
            preds.append(m2.predict(m["t1"], m["t2"]))
            ys.append(m["y"])
            m2.update(m["t1"], m["t2"], m["y"])
        return L.metrics(preds, ys)

    warmed = run_with_widen(1.0)

    print(f"\nS9 prediction, S9-only cold start (warmup=30):        "
          f"n={baseline['n']} logloss={baseline['log_loss']} brier={baseline['brier']} acc={baseline['acc']} ece={baseline['ece']}")
    print(f"S9 prediction, legacy history, no boundary widen:     "
          f"n={warmed['n']} logloss={warmed['log_loss']} brier={warmed['brier']} acc={warmed['acc']} ece={warmed['ece']}")
    for factor in (1.5, 2.0, 3.0, 5.0):
        m = run_with_widen(factor)
        print(f"S9 prediction, legacy history, widen factor={factor:<4}: "
              f"n={m['n']} logloss={m['log_loss']} brier={m['brier']} acc={m['acc']} ece={m['ece']}")

    def run_weighted(weight):
        """Treat every legacy update as WEIGHT strength evidence instead of a
        full match -- season-level rosters are noisier than a real per-match
        roster (bench players credited/blamed for matches they may not have
        played), so this asks whether a gentle nudge helps where a full-
        strength carry-over hurt."""
        m2 = L.OpenSkill()
        for m in combined:
            if m["season"] == 9:
                break
            t1, t2, y = m["t1"], m["t2"], m["y"]
            a, b = [m2.r[p] for p in t1], [m2.r[p] for p in t2]
            na, nb = m2.m.rate([a, b], ranks=[1, 2] if y == 1.0 else [2, 1],
                                weights=[[weight] * len(t1), [weight] * len(t2)])
            for p, r in zip(t1, na):
                m2.r[p] = r
            for p, r in zip(t2, nb):
                m2.r[p] = r
        for m in s9_only[:30]:
            m2.update(m["t1"], m["t2"], m["y"])
        preds, ys = [], []
        for m in holdout:
            preds.append(m2.predict(m["t1"], m["t2"]))
            ys.append(m["y"])
            m2.update(m["t1"], m["t2"], m["y"])
        return L.metrics(preds, ys)

    for weight in (0.5, 0.3, 0.15, 0.05):
        m = run_weighted(weight)
        print(f"S9 prediction, legacy history, update weight={weight:<4}: "
              f"n={m['n']} logloss={m['log_loss']} brier={m['brier']} acc={m['acc']} ece={m['ece']}")
    print("(flat across weights -- OpenSkill's `weights` is per-player partial-play "
          "within a match; uniform weights across a whole team cancel out, wrong lever "
          "for scaling a match's overall strength. Not pursued further.)")

    def run_seasons_only(min_season):
        m2 = L.OpenSkill()
        season_seen = None
        for m in combined:
            if m["season"] == 9 or m["season"] < min_season:
                continue
            if season_seen is not None and m["season"] != season_seen:
                m2.widen_at_season_boundary(2.0)
            season_seen = m["season"]
            m2.update(m["t1"], m["t2"], m["y"])
        if season_seen is not None:
            m2.widen_at_season_boundary(2.0)
        for m in s9_only[:30]:
            m2.update(m["t1"], m["t2"], m["y"])
        preds, ys = [], []
        for m in holdout:
            preds.append(m2.predict(m["t1"], m["t2"]))
            ys.append(m["y"])
            m2.update(m["t1"], m["t2"], m["y"])
        n_used = sum(1 for m in combined if m["season"] != 9 and m["season"] >= min_season)
        return L.metrics(preds, ys), n_used

    print()
    for min_season in (8, 7, 6, 1):
        m, n_used = run_seasons_only(min_season)
        print(f"S9 prediction, legacy from S{min_season} onward ({n_used} matches, widened): "
              f"logloss={m['log_loss']} brier={m['brier']} acc={m['acc']} ece={m['ece']}")

    # Full-history ratings (S1-S9), for the S10 seeding re-check.
    full_model = L.OpenSkill()
    elo_model = L.Elo()
    for m in combined:
        full_model.update(m["t1"], m["t2"], m["y"])
        elo_model.update(m["t1"], m["t2"], m["y"])
    from collections import Counter
    match_counts = Counter(p for m in combined for p in m["t1"] + m["t2"])
    Path(__file__).with_name("ratings_openskill_full_history.json").write_text(json.dumps(
        {str(p): dict(**r, matches=match_counts[p]) for p, r in
         sorted(full_model.ratings().items(), key=lambda kv: -kv[1]["ordinal"])}, indent=1), encoding="utf-8")
    Path(__file__).with_name("ratings_elo_full_history.json").write_text(json.dumps(
        {str(p): dict(**r, matches=match_counts[p]) for p, r in
         sorted(elo_model.ratings().items(), key=lambda kv: -kv[1]["mu"])}, indent=1), encoding="utf-8")
    print(f"\n{len(full_model.r)} players rated across full S1-S9 history -> "
          f"ratings_openskill_full_history.json / ratings_elo_full_history.json")


if __name__ == "__main__":
    main()
