"""KTPR v2.2 season leaderboard: strength-of-schedule + shrinkage + se.

Pure function over match_analytics report dicts (schema v7,
shadow_explorations.ktpr_v2.players[]). Method validated 2026-09-06 by the
analytics lane (HANDOFF-analytics.md "KTPR V2.2 FINAL"): split-half
reliability 0.93, duel-prediction corr 0.60.

  sos_p   = mean over p's matches of ( z_pm + beta * mean_{o in opp(m)} sos_o )
            iterated to a fixed point (opponent strength is itself SoS-adjusted)
  shrunk  = sos_p * n_p / (n_p + k)          empirical-Bayes toward the mean (0)
  se_p    = sqrt(within_var / n_p)           within_var pooled over player-matches

beta and k are fitted constants pinned here; refits land as a new
METHOD_VERSION and a regenerated aggregate revision, never an in-place edit.
"""
from __future__ import annotations

from collections import defaultdict

METHOD_VERSION = "ktpr_v2.2"
BETA = 0.975          # self-consistent + duel-optimal on the 71-match corpus
SHRINKAGE_K = 1.3     # within-var / between-var ratio on the same corpus
MIN_MATCHES = 3
MAX_ITER = 500
TOLERANCE = 1e-9


def build_ktpr_v22(reports: list[dict], beta: float = BETA,
                   k: float = SHRINKAGE_K) -> dict:
    # observations[pid] = [(z, [opponent pids]), ...]; names[pid] = latest name
    observations: dict[int, list[tuple[float, list[int]]]] = defaultdict(list)
    names: dict[int, str] = {}
    definition_versions = set()
    for r in reports:
        block = (r.get("shadow_explorations") or {}).get("ktpr_v2") or {}
        players = block.get("players") or []
        if not players:
            continue
        definition_versions.add(block.get("definition_version"))
        for p in players:
            opponents = [o["player_id"] for o in players
                         if o.get("team") != p.get("team")]
            observations[p["player_id"]].append((float(p["rating"]), opponents))
            if p.get("player_name_at_match"):
                names[p["player_id"]] = p["player_name_at_match"]

    sos = {pid: 0.0 for pid in observations}
    for _ in range(MAX_ITER):
        delta = 0.0
        new = {}
        for pid, obs in observations.items():
            total = 0.0
            for z, opponents in obs:
                opp_mean = (sum(sos[o] for o in opponents) / len(opponents)
                            if opponents else 0.0)
                total += z + beta * opp_mean
            new[pid] = total / len(obs)
            delta = max(delta, abs(new[pid] - sos[pid]))
        sos = new
        if delta < TOLERANCE:
            break

    # Keep the z-score convention: mean rating over players is 0.
    center = sum(sos.values()) / len(sos) if sos else 0.0
    sos = {pid: value - center for pid, value in sos.items()}

    # Within-player variance: mean of per-player sample variances of the
    # SoS-adjusted per-match scores, over players with >= MIN_MATCHES.
    per_player_var = []
    for obs in observations.values():
        if len(obs) < MIN_MATCHES:
            continue
        adjusted = [z + beta * (sum(sos[o] for o in opponents) / len(opponents)
                                if opponents else 0.0)
                    for z, opponents in obs]
        mean = sum(adjusted) / len(adjusted)
        per_player_var.append(sum((a - mean) ** 2 for a in adjusted)
                              / (len(adjusted) - 1))
    within_var = (sum(per_player_var) / len(per_player_var)
                  if per_player_var else 0.0)

    players = []
    for pid, obs in observations.items():
        n = len(obs)
        players.append({
            "player_id": pid,
            "name": names.get(pid),
            "matches": n,
            "sos_rating": round(sos[pid], 4),
            "rating": round(sos[pid] * n / (n + k), 4),
            "se": round((within_var / n) ** 0.5, 4),
        })
    players.sort(key=lambda p: -p["rating"])
    return {
        "method_version": METHOD_VERSION,
        "definition_versions": sorted(v for v in definition_versions
                                      if v is not None),
        "beta": beta,
        "shrinkage_k": k,
        "within_var": round(within_var, 4),
        "min_matches": MIN_MATCHES,
        "players": players,
    }
