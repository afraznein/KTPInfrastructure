#!/usr/bin/env python3
"""Rank every official player-half of the week against the player's own history and
the league, so "that half felt off" becomes a queue of evidenced anomalies.

Written after kroD-'s 10-kill half on 1791141012-NY2 (anzio, 2026-10-04), which took a day
of hand queries to reduce to "worst MP44 half, inside his own variance, aim not
registration". The questions asked by hand that day are the metrics here, so the next one
takes a minute, and the causes accumulate instead of the feelings.

Per player-half (every match type by default -- official, scrim, 12-man; `--types` narrows it,
and the type is a column in every table):

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

Each metric gets z_own (vs the player's other halves, leave-one-out, at least --min-prior of
them) and z_map (vs every player-half on that map). A half's score is the largest |z_own| over
the core metrics; the week's halves are ranked by it, and matches get their own line: how many
players fell below their own hs baseline, where the match's hs% sits among all halves, mean
on-target z.

Four more sections answer the questions a per-half rank cannot:
  Chronic connections   season-mean worst-of shares vs the league (bad in every half)
  Short-term movers     last --change-days vs the player's own earlier halves (got worse/better)
  Servers               within-player offsets per server (the box and the route, roster cancelled)
  Pathological matches  per-match telemetry vs the season, every match type (a night, not a player)

`--pick-server a,b,c` is the per-roster question: rank the servers by those players' own
measured ping history, worst player first. League-wide the boxes sit within 2 ms of each
other within-player, so "best location" only has an answer per roster.

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

TYPES = "(0,1,2,4)"  # official, scrim, 12-man, official; --types narrows it
TYPE_NAME = {0: "official", 1: "scrim", 2: "12man", 4: "official"}
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


def halves_sql(since: str, types: str = TYPES) -> str:
    # One row per (match, half, player): stats + shots/traced/registered + ping.
    # Net and rewind shares come from a second query keyed by player NAME, because the
    # worst-of columns store names, not ids.
    return f"""
WITH m AS (
  SELECT match_id, half, match_type, map_name, server_id, start_time, end_time,
         CONVERT_TZ(start_time,'SYSTEM','+00:00') s_utc, CONVERT_TZ(end_time,'SYSTEM','+00:00') e_utc
  FROM ktp_matches WHERE match_type IN {types} AND start_time >= '{since}' AND end_time IS NOT NULL
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
SELECT m.match_id, m.half, m.match_type, m.map_name, m.server_id, m.start_time, s.player_id, p.player_name,
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


def net_sql(since: str, types: str = TYPES) -> str:
    return f"""
WITH m AS (
  SELECT match_id, half, start_time, end_time FROM ktp_matches
  WHERE match_type IN {types} AND start_time >= '{since}' AND end_time IS NOT NULL
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


def load(db: str, since: str, types: str = TYPES) -> list[dict]:
    rows = []
    for r in q(halves_sql(since, types), db):
        (mid, half, mtype, map_name, sid, start, pid, name, latest_name, k, d, hs, dmg, shots, traced, reg,
         ping_avg, ping_sd) = r
        k, d, hs, dmg = int(k), int(d), int(hs), int(dmg)
        shots, traced, reg = num(shots), num(traced), num(reg)
        rows.append({
            "match_id": mid, "half": int(half), "match_type": int(mtype),
            "type": TYPE_NAME.get(int(mtype), str(mtype)), "map": map_name, "server": int(sid),
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
    for src, mid, half, n, gauge, name in q(net_sql(since, types), db):
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


CHANGE = ["jit_share", "drop_share", "on_target", "k100"]


def recent_change(rows: list[dict], cutoff: str, min_recent: int = 3, min_prior: int = 4,
                  flag_z: float = 2.0) -> list[dict]:
    """Short-term movers: each player's mean over halves since `cutoff` against their own
    earlier halves, in units of their earlier spread (league spread blended in, as in
    zscores). A chronic connection does not show here; one that got better or worse does --
    the 09-27..10-04 calm stretch and the 10-07 relapse are exactly this shape."""
    by_player = defaultdict(list)
    for r in rows:
        by_player[r["player_id"]].append(r)
    league_sd = {}
    for m in CHANGE:
        vals = [r[m] for r in rows if r[m] is not None]
        league_sd[m] = statistics.pstdev(vals) if len(vals) > 1 else 0.0
    out = []
    for pid, rs in by_player.items():
        recent = [r for r in rs if r["start"] >= cutoff]
        prior = [r for r in rs if r["start"] < cutoff]
        if len(recent) < min_recent or len(prior) < min_prior:
            continue
        rec = {"player_id": pid, "player": rs[-1]["player"], "recent": len(recent), "prior": len(prior)}
        zs = {}
        for m in CHANGE:
            a = [r[m] for r in recent if r[m] is not None]
            b = [r[m] for r in prior if r[m] is not None]
            if len(a) < min_recent or len(b) < min_prior:
                continue
            n = len(b)
            sd = statistics.pstdev(b)
            sd = math.sqrt((n * sd * sd + PSEUDO * league_sd[m] ** 2) / (n + PSEUDO))
            rec[f"now_{m}"], rec[f"was_{m}"] = statistics.fmean(a), statistics.fmean(b)
            zs[m] = (rec[f"now_{m}"] - rec[f"was_{m}"]) / sd if sd > 1e-9 else 0.0
            rec[f"z_{m}"] = zs[m]
        if not zs:
            continue
        rec["change_driver"] = max(zs, key=lambda m: abs(zs[m]))
        rec["change_score"] = abs(zs[rec["change_driver"]])
        if rec["change_score"] >= flag_z:
            out.append(rec)
    return sorted(out, key=lambda p: -p["change_score"])


SERVER_M = ["jit_share", "drop_share", "ping_avg"]


def server_offsets(rows: list[dict], min_halves: int = 2, min_pairs: int = 8) -> list[dict]:
    """Within-player server comparison: a player's mean on a server minus their mean across all
    their servers, averaged per server over every player measured there. Who plays where cancels
    out, so this is the box and the route, not the roster. A per-server raw average is not this:
    NY hosts the far teams and reads worst raw while sitting at zero here."""
    by_player = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by_player[r["player_id"]][r["server"]].append(r)
    acc = defaultdict(lambda: {m: [] for m in SERVER_M})
    for servers in by_player.values():
        if len(servers) < 2:
            continue
        own = {}
        for m in SERVER_M:
            vals = [r[m] for rs in servers.values() for r in rs if r[m] is not None]
            own[m] = statistics.fmean(vals) if vals else None
        for sid, rs in servers.items():
            if len(rs) < min_halves:
                continue
            for m in SERVER_M:
                vals = [r[m] for r in rs if r[m] is not None]
                if vals and own[m] is not None:
                    acc[sid][m].append(statistics.fmean(vals) - own[m])
    out = []
    for sid, d in acc.items():
        n = max(len(v) for v in d.values())
        if n < min_pairs:
            continue
        rec = {"server": sid, "pairs": n}
        for m in SERVER_M:
            rec[m] = statistics.fmean(d[m]) if d[m] else None
            rec[f"sd_{m}"] = statistics.pstdev(d[m]) if len(d[m]) > 1 else None
        out.append(rec)
    return sorted(out, key=lambda r: -(r["jit_share"] or 0))


def pick_server_sql(player_ids: list[int], since: str) -> str:
    ids = ",".join(str(i) for i in player_ids)
    return f"""
SELECT l.playerId, l.serverId, s.name, ROUND(AVG(l.ping),1), COUNT(*)
FROM hlstats_Events_Latency l JOIN hlstats_Servers s ON s.serverId = l.serverId
WHERE l.playerId IN ({ids}) AND l.eventTime >= '{since}' AND l.ping > 0
GROUP BY 1,2,3 HAVING COUNT(*) >= 5
"""


def rank_servers(pings: dict[tuple[int, int], float], player_ids: list[int]) -> list[dict]:
    """Rank servers for a set of players by their worst measured ping there, then the mean.
    A server one of them has never been measured on is listed last with the gap named: a
    missing number is not a good number."""
    servers = {sid for (_, sid) in pings}
    out = []
    for sid in servers:
        known = {pid: pings[(pid, sid)] for pid in player_ids if (pid, sid) in pings}
        worst_pid = max(known, key=known.get) if known else None
        out.append({"server": sid, "n_known": len(known), "n": len(player_ids),
                    "worst": known[worst_pid] if known else None, "worst_pid": worst_pid,
                    "mean": statistics.fmean(known.values()) if known else None,
                    "missing": [pid for pid in player_ids if pid not in known]})
    return sorted(out, key=lambda r: (r["n_known"] < len(player_ids), r["worst"] if r["worst"] is not None else 1e9, r["mean"] or 1e9))


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
           anomalies: list[dict] | None = None, n_matches: int = 0,
           movers: list[dict] | None = None, servers: list[dict] | None = None, change_days: int = 14) -> str:
    types = sorted({r["type"] for r in rows})
    L = ["# Weekly outliers", "",
         f"{len(window)} player-halves in the window, {len(rows)} in the baseline "
         f"({len({r['player_id'] for r in rows})} players, "
         f"{len({(r['match_id'], r['half']) for r in rows})} halves, types: {', '.join(types)}). "
         f"Score = max |z| vs the player's own other halves over {', '.join(CORE)}.", ""]
    ranked = sorted([r for r in window if r["score"] is not None], key=lambda r: -r["score"])
    L += [f"## Top {min(top, len(ranked))} player-halves (alert at |z| >= {alert_z})", "",
          "| score | player | match | type | half | map | driver | value | own mean | k/d/hs | k100 | on_target | reg | hs% | ping | jit share |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in ranked[:top]:
        d = r["driver"]
        flag = " ⚠" if r["score"] >= alert_z else ""
        L.append(f"| {r['score']:.1f}{flag} | {r['player']} | {r['match_id']} | {r['type']} | {r['half']} | {r['map'].replace('dod_', '')} "
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
    movers = movers or []
    L += ["", f"## Short-term movers (last {change_days} days vs the player's own earlier halves, {len(movers)} at |z| >= 2)", "",
          "A connection or a game that changed recently. Chronic never shows here; a relapse or a fix does.", "",
          "| player | halves now/before | driver | now | before | jitter-worst now/before | drops-worst now/before | on_target now/before | k100 now/before |",
          "|---|---|---|---|---|---|---|---|---|"]
    for p in movers[:top]:
        d = p["change_driver"]
        def nb(m, scale=1.0, nd=2):
            a, b = p.get(f"now_{m}"), p.get(f"was_{m}")
            return f"{fmt(a * scale if a is not None else None, nd)} / {fmt(b * scale if b is not None else None, nd)}"
        L.append(f"| {p['player']} | {p['recent']}/{p['prior']} | {d} z={p[f'z_{d}']:+.1f} | {fmt(p[f'now_{d}'], 3)} | {fmt(p[f'was_{d}'], 3)} "
                 f"| {nb('jit_share', 100, 0)}% | {nb('drop_share', 100, 0)}% | {nb('on_target', 1, 2)} | {nb('k100', 1, 1)} |")
    servers = servers or []
    L += ["", f"## Servers, within-player (season, {len(servers)} servers with >= 8 player pairs)", "",
          "Each player's mean on a server minus their mean across all their servers, averaged per server. "
          "Who plays where cancels out; a raw per-server average does not (NY hosts the far teams).", "",
          "| server | pairs | jitter-worst share vs own | drops-worst share vs own | ping vs own (ms) |",
          "|---|---|---|---|---|"]
    for s in servers:
        L.append(f"| {s['server']} | {s['pairs']} | {fmt((s['jit_share'] or 0) * 100, 1)} pts (sd {fmt((s['sd_jit_share'] or 0) * 100, 0)}) "
                 f"| {fmt((s['drop_share'] or 0) * 100, 1)} pts (sd {fmt((s['sd_drop_share'] or 0) * 100, 0)}) "
                 f"| {fmt(s['ping_avg'], 1)} (sd {fmt(s['sd_ping_avg'], 0)}) |")
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


def pick_server(db: str, since: str, names: list[str]) -> int:
    """--pick-server: which box is fairest for THESE players, from their own ping history.
    League-wide the boxes sit within 2 ms of each other within-player; the same box is 15-28 ms
    better for one player and worse for another, so the question only has an answer per roster."""
    ids: list[int] = []
    label: dict[int, str] = {}
    for name in names:
        safe = name.replace("'", "''")
        hits = q(f"SELECT player_id, MIN(player_name), MAX(joined_at) FROM ktp_match_players "
                 f"WHERE player_name LIKE '%{safe}%' GROUP BY 1 ORDER BY 3 DESC LIMIT 3", db)
        if not hits:
            print(f"{name}: no player matches", file=sys.stderr)
            return 2
        if len(hits) > 1:
            print(f"{name}: ambiguous, taking the most recent of: " + "; ".join(f"{h[0]}={h[1]}" for h in hits), file=sys.stderr)
        ids.append(int(hits[0][0]))
        label[int(hits[0][0])] = name
    pings: dict[tuple[int, int], float] = {}
    server_name: dict[int, str] = {}
    for pid, sid, sname, ping, n in q(pick_server_sql(ids, since), db):
        pings[(int(pid), int(sid))] = float(ping)
        server_name[int(sid)] = sname
    ranked = rank_servers(pings, ids)
    print(f"servers ranked for {len(ids)} players by worst measured ping, then mean (history since {since}):")
    print("rank  server                  worst  (who)             mean  measured")
    for i, r in enumerate(ranked, 1):
        gap = "" if not r["missing"] else f"  missing {len(r['missing'])}: " + ", ".join(label.get(m, str(m)) for m in r["missing"][:4])
        who = label.get(r["worst_pid"], "") if r["worst_pid"] is not None else ""
        print(f"{i:>4}  {server_name.get(r['server'], r['server']):<22} {fmt(r['worst'], 0):>5}  {who[:16]:<16} {fmt(r['mean'], 0):>5}  {r['n_known']}/{r['n']}{gap}")
    return 0


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
    ap.add_argument("--types", default="0,1,2,4", help="ktp_matches.match_type values to include (0/4 official, 1 scrim, 2 12-man)")
    ap.add_argument("--change-days", type=int, default=14, help="window for the short-term movers section")
    ap.add_argument("--pick-server", metavar="NAMES",
                    help="comma-separated player names (substring match); rank servers by those players' own measured ping and exit")
    a = ap.parse_args()

    if a.pick_server:
        return pick_server(a.db, a.since, [n.strip() for n in a.pick_server.split(",") if n.strip()])

    types = "(" + ",".join(str(int(t)) for t in a.types.split(",")) + ")"
    rows = load(a.db, a.since, types)
    if not rows:
        print("no halves since", a.since, "for types", types, file=sys.stderr)
        return 2
    zscores(rows, a.min_prior)
    latest = max(r["start"] for r in rows)
    cutoff = q(f"SELECT DATE_SUB('{latest}', INTERVAL {a.window_days} DAY)", a.db)[0][0]
    change_cutoff = q(f"SELECT DATE_SUB('{latest}', INTERVAL {a.change_days} DAY)", a.db)[0][0]
    window = [r for r in rows if r["start"] >= cutoff and (not a.match or r["match_id"] == a.match)]
    matches = load_matches(a.db, a.since)
    anomalies = match_anomalies(matches, cutoff)
    movers = recent_change(rows, change_cutoff, min_prior=a.min_prior)
    servers = server_offsets(rows)
    text = report(rows, window, a.top, a.alert_z, a.min_prior, anomalies, len(matches), movers, servers, a.change_days)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        # The journal is what the OnFailure embed carries, and for this unit the journal is
        # the only copy anyone sees before Monday coffee: say what was found, not just that
        # something was. Top rows only; the file has the rest.
        flagged = [r for r in window if r["score"] is not None and r["score"] >= a.alert_z]
        print(f"weekly outliers: {len(flagged)} player-half(s) at |z| >= {a.alert_z}, "
              f"{len(movers)} short-term mover(s), {len(anomalies)} pathological match(es); report: {a.out}")
        for r in sorted(flagged, key=lambda r: -r["score"])[:8]:
            d = r["driver"]
            print(f"  {r['score']:.1f}  {r['player']}  {r['match_id']} h{r['half']} {r['type']}  {d} z={r[f'z_own_{d}']:+.1f}")
        for p in movers[:4]:
            d = p["change_driver"]
            print(f"  mover  {p['player']}  {d} z={p[f'z_{d}']:+.1f}  now {fmt(p[f'now_{d}'], 3)} was {fmt(p[f'was_{d}'], 3)}")
    else:
        sys.stdout.write(text)
    if a.tsv:
        cols = ["match_id", "half", "type", "map", "server", "start", "player_id", "player", "kills", "deaths", "headshots",
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
