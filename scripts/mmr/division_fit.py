"""Fit the cross-division skill offsets the ladder uses as a seeding prior.

WHY THIS EXISTS. OpenSkill puts two players on a common scale only if a path of
matches connects them. It does not: measured 2026-09-30, S9's Gold (5 teams),
Silver (7) and Bronze (5) played ZERO cross-division league matches -- not one
team appears in more than one division. So each division is its own disconnected
graph, anchored at mu=25 by the starting prior rather than by evidence, and a
dominant silver player drifts above a struggling gold player purely because they
each only played their own pool. No amount of within-division data fixes that.

WHAT BRIDGES THEM. 12-mans. Of 1,305 with labelled players, every single one
mixes divisions (plus 313 scrims; officials span in only 25 of 111, being
ringers). The weekly ladder cannot see any of it -- run_weekly pulls official
results from the website with the public anon key, while 12-mans live only in
hlstatsx on the data server. So the fit runs HERE, over ssh, and ships its
result as a committed parameter file that CI consumes. Same shape as
momentum_params.json.

HOW IT MEASURES. Per 12-man, each labelled player's K/D and damage-per-death are
z-scored WITHIN that match, then averaged by division. Within-match
normalisation means map, teams, roster quality and era all cancel: this is a
head-to-head comparison, not a cross-population one. Matches with fewer than
MIN_LABELLED labelled players are dropped so the within-match mean means
something.

Carries no player rows -- output is one row per division. That is why it can be
committed, unlike momentum_fetch.py's TSVs.

Usage:
    python division_fit.py              # -> division_offsets.json
    python division_fit.py --dry-run    # print, write nothing
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

HOST = "krodssh@api.ktpdod.com"
OUT = Path(__file__).resolve().parent / "division_offsets.json"

METHOD_VERSION = "division_offsets_v1"

# A within-match mean over fewer than this many labelled players is noise.
MIN_LABELLED = 8

# Divisions are ordered, and the baseline is the one the offsets are measured
# against. Silver is the middle division, so it carries offset 0 by
# construction and Gold/Bronze are read relative to it.
BASELINE = "Silver"

# ---------------------------------------------------------------------------
# The one number here that is NOT measured.
#
# The fit is in units of within-12-man performance spread (sigma of K/D across
# players in a match). The ladder needs mu, which is a different unit, and
# nothing in the data converts between them -- doing that properly needs
# cross-division match OUTCOMES, which ktp_match_stats does not carry.
#
# So this is a PRIOR, chosen and declared, not a finding. The anchor is
# OpenSkill's own performance-deviation convention, beta = sigma_0 / 2 = 4.167
# skill units: one unit of performance spread is treated as one beta of skill.
# That makes a division step worth roughly 1.9 mu against a starting sigma of
# 8.33 -- deliberately WEAK, so the prior orders the pools on day one and is
# then overwritten by real results instead of calcifying.
#
# Anyone changing this is changing what the published rating means. Say so on
# the transparency page.
MU_PER_PERFORMANCE_SIGMA = 4.167

_SQL = """
WITH s9 AS (
  SELECT mp.player_id, r.league_division AS dname, COUNT(*) AS halves
  FROM ktp_match_players mp
  JOIN ktp_s9_repair_matches r ON r.match_id = mp.match_id
  WHERE r.is_league_match = 1 AND r.league_division IS NOT NULL
  GROUP BY mp.player_id, r.league_division
), pdiv AS (
  SELECT player_id, dname FROM (
    SELECT player_id, dname,
           ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY halves DESC) AS rn
    FROM s9
  ) z WHERE rn = 1
), pm AS (
  SELECT s.match_id, s.player_id, d.dname,
         CASE WHEN m.start_time >= '2026-09-13' THEN 'S10' ELSE 'pre_S10' END AS era,
         SUM(s.kills) AS k, SUM(s.deaths) AS dth, SUM(s.damage) AS dmg
  FROM ktp_match_stats s
  JOIN ktp_matches m ON m.match_id = s.match_id AND m.match_type IN (1, 2)
  JOIN pdiv d ON d.player_id = s.player_id
  GROUP BY s.match_id, s.player_id, d.dname, era
), metric AS (
  SELECT match_id, dname, era,
         k / GREATEST(dth, 1) AS kd,
         dmg / GREATEST(dth, 1) AS dpd,
         COUNT(*) OVER (PARTITION BY match_id) AS n_lab
  FROM pm WHERE dth + k > 0
), zs AS (
  SELECT dname, era,
    (kd  - AVG(kd)  OVER (PARTITION BY match_id))
      / NULLIF(STDDEV_SAMP(kd)  OVER (PARTITION BY match_id), 0) AS z_kd,
    (dpd - AVG(dpd) OVER (PARTITION BY match_id))
      / NULLIF(STDDEV_SAMP(dpd) OVER (PARTITION BY match_id), 0) AS z_dpd
  FROM metric WHERE n_lab >= {min_labelled}
)
SELECT dname, era, COUNT(*) AS player_matches, AVG(z_kd), AVG(z_dpd)
FROM zs WHERE z_kd IS NOT NULL GROUP BY dname, era ORDER BY dname, era;
"""


def fetch_rows(host=HOST, min_labelled=MIN_LABELLED):
    """(division, era, player_matches, z_kd, z_dpd) straight off the box.

    Read-only, via the operator's own grants through auth_socket inside the ssh
    session -- no tunnel and no credential on this side, same as
    momentum_fetch.py.
    """
    sql = _SQL.format(min_labelled=int(min_labelled))
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host, "mysql --batch --skip-column-names hlstatsx"],
        input=sql, capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ssh/mysql rc={proc.returncode}: {proc.stderr[-800:]}")
    rows = []
    for line in proc.stdout.strip().splitlines():
        f = line.split("\t")
        if len(f) == 5:
            rows.append((f[0], f[1], int(f[2]), float(f[3]), float(f[4])))
    if not rows:
        raise RuntimeError("no rows returned; the S9 division labels or "
                           "ktp_match_stats join may have moved")
    return rows


def build(rows, *, fitted_at, mu_per_sigma=MU_PER_PERFORMANCE_SIGMA, baseline=BASELINE):
    """`division_offsets.json` from the fetched rows. Carries no player rows."""
    pooled, by_era = {}, {}
    for dname, era, n, z_kd, z_dpd in rows:
        agg = pooled.setdefault(dname, {"n": 0, "kd": 0.0, "dpd": 0.0})
        agg["n"] += n
        agg["kd"] += z_kd * n
        agg["dpd"] += z_dpd * n
        by_era.setdefault(dname, {})[era] = round(z_kd, 3)
    for agg in pooled.values():
        agg["kd"] /= agg["n"]
        agg["dpd"] /= agg["n"]

    base_kd = pooled[baseline]["kd"] if baseline in pooled else 0.0
    divisions = {}
    for dname, agg in sorted(pooled.items(), key=lambda kv: -kv[1]["kd"]):
        rel = agg["kd"] - base_kd
        divisions[dname] = {
            "player_matches": agg["n"],
            "z_kd": round(agg["kd"], 3),
            "z_damage_per_death": round(agg["dpd"], 3),
            "relative_to_baseline_sigma": round(rel, 3),
            "mu_offset": round(rel * mu_per_sigma, 2),
            "by_era_z_kd": by_era.get(dname, {}),
        }
    return {
        "method_version": METHOD_VERSION,
        "fitted_at": fitted_at,
        "what": "Cross-division skill offsets, measured on 12-mans because league "
                "divisions never play each other. Used as a SEEDING PRIOR only.",
        "baseline": baseline,
        "min_labelled_players_per_match": MIN_LABELLED,
        "mu_per_performance_sigma": mu_per_sigma,
        "mu_per_performance_sigma_is": "a declared prior, not a measurement -- see "
                                       "division_fit.py for why nothing in the data fixes it",
        "divisions": divisions,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    ap.add_argument("--host", default=HOST)
    args = ap.parse_args(argv)

    doc = build(fetch_rows(args.host),
                fitted_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    text = json.dumps(doc, indent=1, ensure_ascii=False)
    if args.dry_run:
        print(text)
        return 0
    OUT.write_text(text + "\n", encoding="utf-8")
    print(f"wrote {OUT.name}")
    for d, v in doc["divisions"].items():
        print(f"  {d:8} z_kd {v['z_kd']:+.3f}  mu_offset {v['mu_offset']:+.2f}  "
              f"n={v['player_matches']}  eras={v['by_era_z_kd']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
