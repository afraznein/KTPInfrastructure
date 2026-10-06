#!/usr/bin/env python3
"""Rank every official player-half of the week against the player's own history and
the league, so "that half felt off" becomes a queue of evidenced anomalies.

Written after kroD-'s 10-kill half on 1791141012-NY2 (anzio, 2026-10-04), which took a day
of hand queries to reduce to "worst MP44 half, inside his own variance, aim not
registration". The questions asked by hand that day are the metrics here, so the next one
takes a minute, and the causes accumulate instead of the feelings.

Per player-half (official match types only):

  k100        kills per 100 shots            ktp_match_stats x ktp_ac_weapon_fires
  on_target   server-traced hits / shots     ktp_ac_weapon_fires.hitgroup IS NOT NULL -- the
                                             server's own geometry said the shot was on a
                                             hitbox when fired. Aim, before registration.
  reg         registered / traced            a confirmed damage row within 100 ms of a traced
                                             fire. Registration, after aim. Killing blows are
                                             absent from ktp_ac_weapon_hits, so this is a
                                             RELATIVE signal (compare halves), never a rate.
  hs_pct      headshots / kills              ktp_match_stats
  dmg_shot    damage per shot
  deaths
  ping_avg, ping_sd                          hlstats_Events_Latency (scoreboard, ~90 s)
  jit_share, lat_share, drop_share           share of 10 s windows where this player was the
                                             server's worst client (ktp_net_intervals keeps
                                             only the worst per gauge -- a flag, not a series)
  rewind_share                               share of windows where this player was the
                                             rewind-miss worst (ktp_rewind_intervals)

Each metric gets z_own (vs the player's other official halves, leave-one-out, at least
--min-prior of them) and z_map (vs every player-half on that map). A half's score is the
largest |z_own| over the core metrics; the week's halves are ranked by it, and matches get
their own line: how many players fell below their own hs baseline, where the match's hs%
sits among all halves, mean on-target z.

Shots come from the AC fires ledger rather than ktp_shot_events because the fires exist for
every official match and the counts are identical where both exist; shot_events are absent on
some servers. AC timestamps are UTC while ktp_matches/net/latency are server-local, so half
windows are converted with CONVERT_TZ(.., 'SYSTEM', '+00:00'), which needs no tz tables and
follows DST per date.

Runs on the data server; MySQL over the local socket, no credentials (public repository).
Read-only. Exits 1 when any half in the window scores at or above --alert-z, so a systemd
OnFailure can carry it to Discord like hlstatsx-ingest-monitor does; a report nobody opens
is the failure this exists to fix.

    weekly_outliers.py [--since 2026-09-13] [--window-days 7] [--min-prior 4]
                       [--alert-z 3.0] [--top 15] [--out report.md] [--tsv all.tsv]
"""
from __future__ import annotations

import argparse
import math
import statistics
import subprocess
import sys
from collections import defaultdict

OFFICIAL = "(0,4)"
CORE = ["k100", "on_target", "reg", "hs_pct", "dmg_shot", "deaths"]
NET = ["ping_avg", "ping_sd", "jit_share", "lat_share", "drop_share", "rewind_share"]


def q(sql: str, db: str) -> list[list[str]]:
    proc = subprocess.run(["mysql", "-N", "--batch", "--raw", "--default-character-set=utf8mb4",
                           db, "-e", sql], capture_output=True, text=True)
    if proc.returncode:
        # The server's one-line reason, not a 60-line SQL dump: a journal reader needs the former.
        raise SystemExit(f"mysql failed ({proc.returncode}): {proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else 'no stderr'}")
    return [line.split("\t") for line in proc.stdout.splitlines() if line]


def num(x: str) -> float | None:
    return None if x in ("NULL", "", None) else float(x)


def halves_sql(since: str) -> str:
    # One row per (match, half, player): stats + shots/traced/registered + ping.
    # Net and rewind shares come from a second query keyed by player NAME, because the
    # worst-of columns store names, not ids.
    return f"""
WITH m AS (
  SELECT match_id, half, map_name, server_id, start_time, end_time,
         CONVERT_TZ(start_time,'SYSTEM','+00:00') s_utc, CONVERT_TZ(end_time,'SYSTEM','+00:00') e_utc
  FROM ktp_matches WHERE match_type IN {OFFICIAL} AND start_time >= '{since}' AND end_time IS NOT NULL
), p AS (
  SELECT match_id, player_id, MIN(player_name) player_name, MIN(steam_id) steam_id
  FROM ktp_match_players GROUP BY 1,2
), latest AS (
  -- Display name = the one most recently seen. The per-match name above stays for joining
  -- the net worst-of columns, which store names. One player carried 60+ aliases this season,
  -- several of them other people's names, so an alphabetical pick labelled him as someone else.
  SELECT a.player_id, MIN(a.player_name) player_name
  FROM ktp_match_players a JOIN (SELECT player_id, MAX(joined_at) joined_at FROM ktp_match_players GROUP BY 1) b
    ON b.player_id = a.player_id AND b.joined_at = a.joined_at
  GROUP BY 1
), fires AS (
  SELECT m.match_id, m.half, f.steam_id,
         COUNT(*) shots, SUM(f.hitgroup IS NOT NULL) traced,
         SUM(f.hitgroup IS NOT NULL AND EXISTS (
             SELECT 1 FROM ktp_ac_weapon_hits h
             WHERE h.match_id = f.match_id AND h.attacker_steam_id = f.steam_id
               AND h.weapon_id = f.weapon_id
               AND ABS(CAST(h.hit_at_ms AS SIGNED) - CAST(f.ts_ms AS SIGNED)) <= 100)) registered
  FROM m JOIN ktp_ac_weapon_fires f
    ON f.match_id = m.match_id COLLATE utf8mb4_0900_ai_ci
   AND f.fired_at_utc BETWEEN m.s_utc AND m.e_utc
  GROUP BY 1,2,3
), ping AS (
  SELECT m.match_id, m.half, l.playerId player_id, AVG(l.ping) ping_avg, STDDEV(l.ping) ping_sd
  FROM m JOIN hlstats_Events_Latency l
    ON l.serverId = m.server_id AND l.eventTime BETWEEN m.start_time AND m.end_time
  GROUP BY 1,2,3
)
SELECT m.match_id, m.half, m.map_name, m.server_id, m.start_time, s.player_id, p.player_name,
       COALESCE(lt.player_name, p.player_name) latest_name,
       s.kills, s.deaths, s.headshots, s.damage,
       fi.shots, fi.traced, fi.registered, pg.ping_avg, pg.ping_sd
FROM ktp_match_stats s
JOIN m ON m.match_id = s.match_id AND m.half = s.half
JOIN p ON p.match_id = s.match_id AND p.player_id = s.player_id
LEFT JOIN latest lt ON lt.player_id = s.player_id
LEFT JOIN fires fi ON fi.match_id = m.match_id AND fi.half = m.half
                  AND fi.steam_id = CONCAT('STEAM_0:', p.steam_id) COLLATE utf8mb4_0900_ai_ci
LEFT JOIN ping pg ON pg.match_id = m.match_id AND pg.half = m.half AND pg.player_id = s.player_id
ORDER BY m.start_time, m.half, s.player_id
"""


def net_sql(since: str) -> str:
    return f"""
WITH m AS (
  SELECT match_id, half, start_time, end_time FROM ktp_matches
  WHERE match_type IN {OFFICIAL} AND start_time >= '{since}' AND end_time IS NOT NULL
), w AS (
  SELECT m.match_id, m.half, n.jitter_worst_name jit, n.latency_worst_name lat, n.drops_worst_name dr
  FROM m JOIN ktp_net_intervals n ON n.match_id = m.match_id AND n.ts BETWEEN m.start_time AND m.end_time
), r AS (
  SELECT m.match_id, m.half, x.miss_worst_name mw
  FROM m JOIN ktp_rewind_intervals x ON x.match_id = m.match_id AND x.ts BETWEEN m.start_time AND m.end_time
  WHERE x.miss_worst_n > 0
)
SELECT 'net', match_id, half, COUNT(*) n, 'jit', jit FROM w GROUP BY match_id, half, jit
UNION ALL SELECT 'net', match_id, half, COUNT(*), 'lat', lat FROM w GROUP BY match_id, half, lat
UNION ALL SELECT 'net', match_id, half, COUNT(*), 'dr', dr FROM w GROUP BY match_id, half, dr
UNION ALL SELECT 'rw', match_id, half, COUNT(*), 'mw', mw FROM r GROUP BY match_id, half, mw
"""


def matches_sql(since: str) -> str:
    # Every match type: the pathological nights found by hand (a 12-man at 321 drops/window, a
    # 12-man with 1,427 rewind requests/window past sv_maxunlag) were not officials, and they
    # are what made two servers look broken in a per-server average.
    return f"""
SELECT n.match_id, MIN(m.match_type), MIN(m.map_name), MIN(m.start_time), n.server_endpoint,
       COUNT(*) windows, AVG(n.drops), MAX(n.drops), AVG(n.maxunlag_hits), AVG(n.loss_worst),
       AVG(n.jitter_worst_ms), SUM(n.lagcomp_off)
FROM ktp_net_intervals n JOIN (SELECT match_id, MIN(match_type) match_type, MIN(map_name) map_name,
                                      MIN(start_time) start_time FROM ktp_matches
                               WHERE start_time >= '{since}' GROUP BY 1) m ON m.match_id = n.match_id
WHERE n.ts >= '{since}' AND n.clients >= 8
GROUP BY n.match_id, n.server_endpoint HAVING windows >= 60
"""


MATCH = ["drops_win", "maxunlag_win", "loss_worst", "jitter_worst"]


def load_matches(db: str, since: str) -> list[dict]:
    out = []
    for r in q(matches_sql(since), db):
        mid, mt, map_name, start, ep, win, dr, drmax, mu, lo, ji, lc = r
        out.append({"match_id": mid, "match_type": int(mt), "map": map_name, "start": start, "server": ep,
                    "windows": int(win), "drops_win": float(dr), "drops_max": float(drmax),
                    "maxunlag_win": float(mu), "loss_worst": float(lo), "jitter_worst": float(ji),
                    "lagcomp_off": int(lc)})
    return out


def match_anomalies(matches: list[dict], cutoff: str, flag_z: float = 2.0) -> list[dict]:
    """Matches in the window whose per-window drops, rewind-cap hits, loss or jitter sit far
    above every match this season. These are nights, not players: the per-player sections
    would file them under whoever happened to be worst."""
    for m in MATCH:
        vals = [x[m] for x in matches]
        if len(vals) < 2:
            return []
        mu, sd = statistics.fmean(vals), statistics.pstdev(vals)
        for x in matches:
            x[f"z_{m}"] = (x[m] - mu) / sd if sd > 1e-9 else 0.0
    flagged = []
    for x in matches:
        if x["start"] < cutoff:
            continue
        zs = {m: x[f"z_{m}"] for m in MATCH}
        x["net_driver"] = max(zs, key=zs.get)
        x["net_score"] = zs[x["net_driver"]]
        if x["net_score"] >= flag_z or x["lagcomp_off"]:
            flagged.append(x)
    return sorted(flagged, key=lambda x: -x["net_score"])


def load(db: str, since: str) -> list[dict]:
    rows = []
    for r in q(halves_sql(since), db):
        (mid, half, map_name, sid, start, pid, name, latest_name, k, d, hs, dmg, shots, traced, reg,
         ping_avg, ping_sd) = r
        k, d, hs, dmg = int(k), int(d), int(hs), int(dmg)
        shots, traced, reg = num(shots), num(traced), num(reg)
        rows.append({
            "match_id": mid, "half": int(half), "map": map_name, "server": int(sid),
            "start": start, "player_id": int(pid), "player": latest_name, "match_name": name,
            "kills": k, "deaths": d, "headshots": hs, "damage": dmg, "shots": shots,
            "k100": 100 * k / shots if shots else None,
            "on_target": traced / shots if shots else None,
            "reg": reg / traced if traced else None,
            "hs_pct": 100 * hs / k if k else None,
            "dmg_shot": dmg / shots if shots else None,
            "ping_avg": num(ping_avg), "ping_sd": num(ping_sd),
        })
    # worst-of shares, keyed by (match, half, name)
    totals: dict[tuple, int] = defaultdict(int)
    share: dict[tuple, int] = defaultdict(int)
    for src, mid, half, n, gauge, name in q(net_sql(since), db):
        key = (mid, int(half), gauge)
        totals[key] += int(n)
        if name and name != "NULL":
            share[(mid, int(half), gauge, name)] = int(n)
    col = {"jit": "jit_share", "lat": "lat_share", "dr": "drop_share", "mw": "rewind_share"}
    for row in rows:
        for g, c in col.items():
            t = totals.get((row["match_id"], row["half"], g), 0)
            row[c] = share.get((row["match_id"], row["half"], g, row["match_name"]), 0) / t if t else None
    return rows


CHRONIC = ["jit_share", "drop_share", "lat_share", "rewind_share"]


def chronic(rows: list[dict], min_prior: int, flag_z: float = 2.0) -> list[dict]:
    """Season-long connection ranking: each player's mean worst-of shares, z'd against the
    population of player means. A connection that is bad in every half never shows against
    the player's own baseline, which is exactly the one the owner can fix at home."""
    by_player = defaultdict(list)
    for r in rows:
        by_player[r["player_id"]].append(r)
    players = []
    for pid, rs in by_player.items():
        if len(rs) < min_prior:
            continue
        rec = {"player_id": pid, "player": rs[-1]["player"], "halves": len(rs)}
        for m in CHRONIC + ["ping_avg"]:
            vals = [r[m] for r in rs if r[m] is not None]
            rec[m] = statistics.fmean(vals) if vals else None
        players.append(rec)
    for m in CHRONIC:
        vals = [p[m] for p in players if p[m] is not None]
        if len(vals) < 2:
            continue
        mu, sd = statistics.fmean(vals), statistics.pstdev(vals)
        for p in players:
            p[f"z_{m}"] = (p[m] - mu) / sd if p[m] is not None and sd > 1e-9 else None
    for p in players:
        zs = {m: p.get(f"z_{m}") for m in CHRONIC if p.get(f"z_{m}") is not None}
        p["net_driver"] = max(zs, key=zs.get) if zs else None
        p["net_score"] = zs[p["net_driver"]] if zs else None
    return sorted([p for p in players if p["net_score"] is not None and p["net_score"] >= flag_z],
                  key=lambda p: -p["net_score"])


PSEUDO = 4  # league-sd pseudo-halves blended into a player's own sd; see zscores()


def zscores(rows: list[dict], min_prior: int) -> None:
    by_player = defaultdict(list)
    by_map = defaultdict(list)
    for r in rows:
        by_player[r["player_id"]].append(r)
        by_map[r["map"]].append(r)
    for metric in CORE + NET:
        # League sd per metric, used two ways: as the z_map denominator and as a prior
        # blended into each player's own sd. A season is ~8 halves per player; with 5
        # points a lucky tight baseline makes z=11 out of one good half (seen on the
        # first run). Shrinking the sd toward the league's with PSEUDO pseudo-halves
        # keeps a 5-point baseline honest without hiding a real 3-sigma half.
        league_vals = [r[metric] for r in rows if r[metric] is not None]
        league_sd = statistics.pstdev(league_vals) if len(league_vals) > 1 else 0.0
        for group, tag in ((by_player, "own"), (by_map, "map")):
            for members in group.values():
                for r in members:
                    others = [o[metric] for o in members if o is not r and o[metric] is not None]
                    v = r[metric]
                    r[f"z_{tag}_{metric}"] = None
                    r[f"n_{tag}_{metric}"] = len(others)
                    if v is None or len(others) < min_prior:
                        continue
                    mu = statistics.fmean(others)
                    n = len(others)
                    sd = statistics.pstdev(others)
                    if tag == "own":
                        sd = math.sqrt((n * sd * sd + PSEUDO * league_sd * league_sd) / (n + PSEUDO))
                    r[f"z_{tag}_{metric}"] = (v - mu) / sd if sd > 1e-9 else 0.0
                    r[f"mu_{tag}_{metric}"] = mu
    for r in rows:
        zs = [abs(r[f"z_own_{m}"]) for m in CORE if r.get(f"z_own_{m}") is not None]
        r["score"] = max(zs) if zs else None
        r["driver"] = (max(CORE, key=lambda m: abs(r.get(f"z_own_{m}") or 0)) if zs else None)


def fmt(v, nd=1):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def report(rows: list[dict], window: list[dict], top: int, alert_z: float, min_prior: int,
           anomalies: list[dict] | None = None, n_matches: int = 0) -> str:
    L = ["# Weekly outliers", "",
         f"{len(window)} player-halves in the window, {len(rows)} in the baseline "
         f"({len({r['player_id'] for r in rows})} players, "
         f"{len({(r['match_id'], r['half']) for r in rows})} halves). "
         f"Score = max |z| vs the player's own other halves over {', '.join(CORE)}.", ""]
    ranked = sorted([r for r in window if r["score"] is not None], key=lambda r: -r["score"])
    L += [f"## Top {min(top, len(ranked))} player-halves (alert at |z| >= {alert_z})", "",
          "| score | player | match | half | map | driver | value | own mean | k/d/hs | k100 | on_target | reg | hs% | ping | jit share |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in ranked[:top]:
        d = r["driver"]
        flag = " ⚠" if r["score"] >= alert_z else ""
        L.append(f"| {r['score']:.1f}{flag} | {r['player']} | {r['match_id']} | {r['half']} | {r['map'].replace('dod_', '')} "
                 f"| {d} z={r[f'z_own_{d}']:+.1f} (n={r[f'n_own_{d}']}) | {fmt(r[d], 2)} | {fmt(r.get(f'mu_own_{d}'), 2)} "
                 f"| {r['kills']}/{r['deaths']}/{r['headshots']} | {fmt(r['k100'])} | {fmt(r['on_target'], 2)} "
                 f"| {fmt(r['reg'], 2)} | {fmt(r['hs_pct'], 0)} | {fmt(r['ping_avg'], 0)}±{fmt(r['ping_sd'], 0)} "
                 f"| {fmt((r['jit_share'] or 0) * 100, 0)}% |")
    unscored = [r for r in window if r["score"] is None]
    if unscored:
        L += ["", f"{len(unscored)} player-halves unscored: fewer than the minimum prior halves "
                  f"({', '.join(sorted({r['player'] for r in unscored})[:12])}{'…' if len(unscored) > 12 else ''})."]
    # match-level
    L += ["", "## Matches in the window", "",
          "| match | map | server | players | players below own hs% | match hs% h1/h2 | hs% rank (low→high, of N) | mean z on_target | mean z reg |",
          "|---|---|---|---|---|---|---|---|---|"]
    all_half_hs = {}
    for r in rows:
        all_half_hs.setdefault((r["match_id"], r["half"]), [0, 0])
        all_half_hs[(r["match_id"], r["half"])][0] += r["headshots"]
        all_half_hs[(r["match_id"], r["half"])][1] += r["kills"]
    half_hs = {k: 100 * a / b for k, (a, b) in all_half_hs.items() if b}
    hs_sorted = sorted(half_hs.values())
    by_match = defaultdict(list)
    for r in window:
        by_match[r["match_id"]].append(r)
    for mid, rs in by_match.items():
        players = {r["player_id"]: r for r in rs}
        # Per player over the whole match, not per half-row: one vote per person.
        below = scored = 0
        for pid in players:
            mine = [r for r in rs if r["player_id"] == pid and r.get("mu_own_hs_pct") is not None]
            k = sum(r["kills"] for r in mine)
            if not mine or not k:
                continue
            scored += 1
            below += 100 * sum(r["headshots"] for r in mine) / k < statistics.fmean(r["mu_own_hs_pct"] for r in mine)
        hs_halves = [half_hs[(mid, h)] for h in (1, 2) if (mid, h) in half_hs]
        ranks = [sum(1 for v in hs_sorted if v < x) + 1 for x in hs_halves]
        mzo = [r["z_own_on_target"] for r in rs if r.get("z_own_on_target") is not None]
        mzr = [r["z_own_reg"] for r in rs if r.get("z_own_reg") is not None]
        L.append(f"| {mid} | {rs[0]['map'].replace('dod_', '')} | {rs[0]['server']} | {len(players)} "
                 f"| {below}/{scored} | {'/'.join(f'{x:.0f}' for x in hs_halves)} "
                 f"| {'/'.join(str(x) for x in ranks)} of {len(hs_sorted)} "
                 f"| {fmt(statistics.fmean(mzo) if mzo else None, 2)} | {fmt(statistics.fmean(mzr) if mzr else None, 2)} |")
    chron = chronic(rows, min_prior)
    L += ["", f"## Chronic connections (season, official halves, {len(chron)} players at z >= 2 vs the league)", "",
          "Mean share of 10 s windows in which the player was the server's worst client. Bad in every half never "
          "shows against the player's own baseline; this is the list to hand to the player.", "",
          "| player | halves | driver | jitter-worst | drops-worst | latency-worst | rewind-worst | ping |",
          "|---|---|---|---|---|---|---|---|"]
    for p in chron[:top]:
        L.append(f"| {p['player']} | {p['halves']} | {p['net_driver']} z={p['net_score']:+.1f} "
                 f"| {fmt((p['jit_share'] or 0) * 100, 0)}% | {fmt((p['drop_share'] or 0) * 100, 0)}% "
                 f"| {fmt((p['lat_share'] or 0) * 100, 0)}% | {fmt((p['rewind_share'] or 0) * 100, 0)}% | {fmt(p['ping_avg'], 0)} |")
    anomalies = anomalies or []
    L += ["", f"## Pathological matches (all match types, {len(anomalies)} flagged of {n_matches} this season)", "",
          "Per-10 s-window server telemetry z'd against every match since the season floor. A night, not a player; "
          "the servers themselves read the same once these are removed.", "",
          "| match | type | map | server | windows | driver | drops/win (max) | maxunlag hits/win | loss worst | jitter worst | lagcomp off |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for x in anomalies[:top]:
        L.append(f"| {x['match_id']} | {x['match_type']} | {x['map'].replace('dod_', '')} | {x['server']} | {x['windows']} "
                 f"| {x['net_driver']} z={x['net_score']:+.1f} | {x['drops_win']:.1f} ({x['drops_max']:.0f}) | {x['maxunlag_win']:.1f} "
                 f"| {x['loss_worst']:.2f} | {x['jitter_worst']:.0f} | {x['lagcomp_off']} |")
    L += ["", "## Reading it", "",
          "- `on_target` low and `reg` normal: the shots were not on a hitbox when fired -- aim or exposure, not the server.",
          "- `reg` low with `on_target` normal: traced fires did not become damage rows -- the registration question. "
          "Killing blows are missing from the hits ledger, so compare against the player's own `reg`, never read it as a rate.",
          "- `jit_share` high in one half only is a network event; high in every half is that player's connection -- see Chronic connections.",
          "- `rewind-worst` is only scored in windows that had a miss at all, which is rare, so a few windows can read as 100%; weigh it by halves.",
          "- `ping_sd` is from ~90 s scoreboard samples and cannot see jitter; `ktp_net_intervals` stores only the worst client "
          "per window, so there is no per-player series yet (infra-weekly-outliers, telemetry gap 1)."]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default="hlstatsx")
    ap.add_argument("--since", default="2026-09-13", help="baseline floor (season start)")
    ap.add_argument("--window-days", type=int, default=7, help="halves started in the last N days are scored")
    ap.add_argument("--min-prior", type=int, default=4, help="other halves a player needs before being scored")
    ap.add_argument("--alert-z", type=float, default=3.0)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--out", help="write the markdown report here instead of stdout")
    ap.add_argument("--tsv", help="also dump every scored row with all z columns")
    ap.add_argument("--match", help="score only this match's halves (still ranked against the full baseline)")
    a = ap.parse_args()

    rows = load(a.db, a.since)
    if not rows:
        print("no official halves since", a.since, file=sys.stderr)
        return 2
    zscores(rows, a.min_prior)
    latest = max(r["start"] for r in rows)
    cutoff = q(f"SELECT DATE_SUB('{latest}', INTERVAL {a.window_days} DAY)", a.db)[0][0]
    window = [r for r in rows if r["start"] >= cutoff and (not a.match or r["match_id"] == a.match)]
    matches = load_matches(a.db, a.since)
    anomalies = match_anomalies(matches, cutoff)
    text = report(rows, window, a.top, a.alert_z, a.min_prior, anomalies, len(matches))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    if a.tsv:
        cols = ["match_id", "half", "map", "server", "start", "player_id", "player", "kills", "deaths", "headshots",
                "damage", "shots", "score", "driver"] + CORE + NET + \
               [f"z_own_{m}" for m in CORE + NET] + [f"z_map_{m}" for m in CORE + NET]
        with open(a.tsv, "w", encoding="utf-8") as fh:
            fh.write("\t".join(cols) + "\n")
            for r in rows:
                fh.write("\t".join("" if r.get(c) is None else str(r.get(c)) for c in cols) + "\n")
    worst = max((r["score"] for r in window if r["score"] is not None), default=0.0)
    return 1 if worst >= a.alert_z else 0


if __name__ == "__main__":
    sys.exit(main())
