"""Phase 1 MMR ladder MVP: chronological backtest of Elo and OpenSkill over the
S9 labeled corpus (ktp_s9_repair_scores, Score-Bot reported engine scores).

Evaluation: log-loss, Brier, ECE (5 bins), accuracy. Baselines: constant 0.5.
Side mapping (empirical, see NOTES.md): score column a = roster team 2,
b = roster team 1. Team = set of players credited in halves 1-2, excluded=0.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

from openskill.models import PlackettLuce

DATA = Path(__file__).parent / "data"
MIN_TEAM = 4


def load_identity_merges():
    """duplicate player_id -> canonical player_id, for one person holding two
    Steam IDs in hlstatsx (see data/identity_merges.json for provenance)."""
    raw = json.loads((DATA / "identity_merges.json").read_text())
    return {int(k): int(v) for k, v in raw.items() if k != "_comment"}


def load_matches():
    merges = load_identity_merges()
    scores = {r["match_id"]: r for r in csv.DictReader(open(DATA / "s9_scores.tsv"), delimiter="\t")}
    rosters = defaultdict(lambda: defaultdict(set))
    for r in csv.DictReader(open(DATA / "s9_players.tsv"), delimiter="\t"):
        if r["half"] in ("1", "2") and r["excluded"] == "0":
            pid = int(r["player_id"])
            rosters[r["match_id"]][r["team"]].add(merges.get(pid, pid))
    out = []
    for mid, s in scores.items():
        if s["final_a"] == "NULL" or s["anomaly"] != "NULL":
            continue
        a, b = int(s["final_a"]), int(s["final_b"])
        t1, t2 = rosters[mid]["1"], rosters[mid]["2"]
        if a == b or len(t1) < MIN_TEAM or len(t2) < MIN_TEAM:
            continue
        when = s["start_time"] if s["start_time"] != "NULL" else s["match_date"]
        # label: did roster team 1 (= score b) win?
        out.append(dict(match_id=mid, when=when, map=s["map_name"],
                        t1=sorted(t1), t2=sorted(t2), y=1.0 if b > a else 0.0,
                        margin=abs(a - b)))
    out.sort(key=lambda m: m["when"])
    return out


# ---------------------------------------------------------------- metrics
def metrics(preds, ys, bins=5):
    n = len(ys)
    eps = 1e-6
    ll = -sum(y * math.log(max(p, eps)) + (1 - y) * math.log(max(1 - p, eps)) for p, y in zip(preds, ys)) / n
    brier = sum((p - y) ** 2 for p, y in zip(preds, ys)) / n
    acc = sum((p > 0.5) == (y == 1.0) for p, y in zip(preds, ys)) / n
    ece, diag = 0.0, []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        idx = [j for j, p in enumerate(preds) if lo <= p < hi or (i == bins - 1 and p == 1.0)]
        if not idx:
            continue
        conf = sum(preds[j] for j in idx) / len(idx)
        obs = sum(ys[j] for j in idx) / len(idx)
        ece += len(idx) / n * abs(conf - obs)
        diag.append((round(lo, 2), round(hi, 2), len(idx), round(conf, 3), round(obs, 3)))
    return dict(n=n, log_loss=round(ll, 4), brier=round(brier, 4), acc=round(acc, 3), ece=round(ece, 4), reliability=diag)


# ---------------------------------------------------------------- models
class Elo:
    """Chess-style anchor: init 1000 (not 1500) so an average player sits near
    800-1200 and only a wide, established gap reaches 2000 -- matching how
    chess Elo actually looks. Per-player provisional K (USCF-style: K=40
    for a player's first 10 games, K=20 after) lets real separation show up
    fast for new players instead of needing hundreds of games to diverge,
    which is what a fixed low K would otherwise require."""

    def __init__(self, k=20, k_provisional=40, provisional_games=10, init=1000.0):
        self.k, self.k_provisional, self.provisional_games = k, k_provisional, provisional_games
        self.r = defaultdict(lambda: init)
        self.games = defaultdict(int)

    def _k(self, p):
        return self.k_provisional if self.games[p] < self.provisional_games else self.k

    def predict(self, t1, t2):
        d = sum(self.r[p] for p in t1) / len(t1) - sum(self.r[p] for p in t2) / len(t2)
        return 1 / (1 + 10 ** (-d / 400))

    def update(self, t1, t2, y):
        margin = y - self.predict(t1, t2)
        for p in t1:
            self.r[p] += self._k(p) * margin
            self.games[p] += 1
        for p in t2:
            self.r[p] -= self._k(p) * margin
            self.games[p] += 1

    def ratings(self):
        return {p: dict(mu=round(r, 1)) for p, r in self.r.items()}

    def widen_at_season_boundary(self, fraction=0.5):
        """Carry ratings forward across a season, but re-open the
        provisional window partially: multiply each player's game count by
        `fraction` so early-season play moves their rating faster again,
        without resetting them to a stranger's 1000 like a hard reset would.
        fraction=1.0 is a no-op; fraction=0.0 fully re-provisions everyone."""
        for p in list(self.games):
            self.games[p] = int(self.games[p] * fraction)


class OpenSkill:
    def __init__(self, **kw):
        self.m = PlackettLuce(**kw)
        self.r = defaultdict(self.m.rating)

    def predict(self, t1, t2):
        return self.m.predict_win([[self.r[p] for p in t1], [self.r[p] for p in t2]])[0]

    def update(self, t1, t2, y):
        a, b = [self.r[p] for p in t1], [self.r[p] for p in t2]
        na, nb = self.m.rate([a, b], ranks=[1, 2] if y == 1.0 else [2, 1])
        for p, r in zip(t1, na):
            self.r[p] = r
        for p, r in zip(t2, nb):
            self.r[p] = r

    def widen_at_season_boundary(self, factor=1.5):
        """Carry mu forward across a season, but widen sigma back up (capped
        at the model's own starting sigma) so the rating can move again
        instead of being frozen by false confidence from last season.
        factor=1.0 is a no-op."""
        default_sigma = self.m.rating().sigma
        for p, r in list(self.r.items()):
            self.r[p] = self.m.rating(mu=r.mu, sigma=min(r.sigma * factor, default_sigma))

    def ratings(self):
        return {p: dict(mu=round(r.mu, 2), sigma=round(r.sigma, 2), ordinal=round(r.ordinal(), 2)) for p, r in self.r.items()}


class Constant:
    def predict(self, t1, t2): return 0.5
    def update(self, *a): pass
    def ratings(self): return {}


def roster_familiarity(matches):
    """Per-match causal familiarity: fraction of same-team pairs in this
    match who have shared a team in any EARLIER match (no future leakage).
    High familiarity = an established roster; low = a scratch/mixed team."""
    from itertools import combinations
    seen_pairs = set()
    out = {}
    for m in matches:
        pairs_now, familiar = [], 0
        for team in (m["t1"], m["t2"]):
            for a, b in combinations(sorted(team), 2):
                pairs_now.append((a, b))
                if (a, b) in seen_pairs:
                    familiar += 1
        out[m["match_id"]] = familiar / len(pairs_now) if pairs_now else 0.0
        seen_pairs.update(pairs_now)
    return out


def split_metrics(rows, warmup, groups):
    """rows = backtest() per-match rows (already skip nothing); groups =
    {label: predicate(row)}. Applies the same warmup cutoff as backtest."""
    out = {}
    for label, pred in groups.items():
        sel = [r for i, r in enumerate(rows) if i >= warmup and pred(r)]
        if sel:
            out[label] = metrics([r["p_t1"] for r in sel], [r["y"] for r in sel])
    return out


def backtest(model, matches, warmup=0):
    preds, ys, rows = [], [], []
    for i, m in enumerate(matches):
        p = model.predict(m["t1"], m["t2"])
        if i >= warmup:
            preds.append(p); ys.append(m["y"])
        rows.append(dict(match_id=m["match_id"], when=m["when"], map=m["map"], p_t1=round(p, 3), y=m["y"], margin=m["margin"]))
        model.update(m["t1"], m["t2"], m["y"])
    return metrics(preds, ys), rows


def _selfcheck():
    m = metrics([0.9, 0.1, 0.5, 0.5], [1, 0, 1, 0], bins=2)
    assert abs(m["log_loss"] - 0.3993) < 1e-3 and abs(m["brier"] - 0.13) < 1e-3 and m["acc"] == 0.75, m
    e = Elo(); init = e.r[999]; e.update([1], [2], 1.0)
    assert e.r[1] > init > e.r[2] and e.predict([1], [2]) > 0.5


def main():
    _selfcheck()
    matches = load_matches()
    players = Counter(p for m in matches for p in m["t1"] + m["t2"])
    print(f"matches={len(matches)} players={len(players)} span={matches[0]['when']}..{matches[-1]['when']}")
    print(f"matches/player: min={min(players.values())} median={sorted(players.values())[len(players)//2]} max={max(players.values())}")
    warmup = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    models = {"constant_0.5": Constant, "elo_chess": Elo, "elo_k64_flat": lambda: Elo(64, 64, 0),
              "openskill_pl": OpenSkill, "openskill_pl_beta2": lambda: OpenSkill(beta=25 / 6 * 2)}
    results, per_match = {}, {}
    for name, mk in models.items():
        model = mk()
        results[name], per_match[name] = backtest(model, matches, warmup)
        if name == "openskill_pl":
            Path(__file__).with_name("ratings_openskill.json").write_text(json.dumps(
                {str(p): dict(**r, matches=players[p]) for p, r in sorted(model.ratings().items(), key=lambda kv: -kv[1]["ordinal"])}, indent=1))
        if name == "elo_chess":
            Path(__file__).with_name("ratings_elo.json").write_text(json.dumps(
                {str(p): dict(**r, matches=players[p]) for p, r in sorted(model.ratings().items(), key=lambda kv: -kv[1]["mu"])}, indent=1))
    print(f"\n{'model':22s} n   logloss brier  acc   ece   (warmup={warmup})")
    for name, r in results.items():
        print(f"{name:22s} {r['n']:<3d} {r['log_loss']:.4f}  {r['brier']:.4f} {r['acc']:.3f} {r['ece']:.4f}")
    print("\nreliability openskill_pl:", results["openskill_pl"]["reliability"])

    # Splits promised in the original methodology doc, run on openskill_pl.
    fam = roster_familiarity(matches)
    fam_vals = sorted(fam.values())
    fam_median = fam_vals[len(fam_vals) // 2]
    rows = per_match["openskill_pl"]
    for r in rows:
        r["familiarity"] = round(fam[r["match_id"]], 3)
    maps = sorted({r["map"] for r in rows})
    by_map = split_metrics(rows, warmup, {mp: (lambda r, mp=mp: r["map"] == mp) for mp in maps})
    by_fam = split_metrics(rows, warmup, {
        "low_familiarity": lambda r: r["familiarity"] < fam_median,
        "high_familiarity": lambda r: r["familiarity"] >= fam_median,
    })
    print(f"\nopenskill_pl by map (median familiarity={fam_median:.2f}):")
    for mp, met in sorted(by_map.items(), key=lambda kv: -kv[1]["n"]):
        print(f"  {mp:20s} n={met['n']:<3d} logloss={met['log_loss']:.4f} brier={met['brier']:.4f} acc={met['acc']:.3f}")
    print("openskill_pl by roster familiarity:")
    for label, met in by_fam.items():
        print(f"  {label:16s} n={met['n']:<3d} logloss={met['log_loss']:.4f} brier={met['brier']:.4f} acc={met['acc']:.3f}")

    Path(__file__).with_name("backtest.json").write_text(json.dumps(
        dict(results=results, per_match=per_match, splits=dict(by_map=by_map, by_familiarity=by_fam)), indent=1))


if __name__ == "__main__":
    main()
