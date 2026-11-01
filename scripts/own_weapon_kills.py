#!/usr/bin/env python3
"""Nightly report: who got killed with their own gun. A public, fun stat.

stats_logging 1.35.0 keeps an owner stamp on every primary a player spawns with. When that gun
is dropped (death or the drop key) and someone else picks it up and kills the owner with it, the
plugin logs `"<killer>" triggered "own_weapon_kill" against "<owner>"`, and KTPHLStatsX migration
051 lands it as a `hlstats_Events_PlayerPlayerActions` row with `match_id`. Teammates count.

  kill       one PlayerPlayerActions row with code `own_weapon_kill`, inside a tracked match
  weapon     from the frag at the same eventTime with the same killer and victim
             (`hlstats_Events_Frags`, or `hlstats_Events_Teamkills` -- a match there means a
             teammate did it); `?` when neither row is found
  per match  robbed (or thefts) / matches the player appeared in (`ktp_match_players`) WHERE a
             half ran a producer that logs the line (capture manifest `producer_version` >=
             1.35.0), so a player is not diluted by matches that could not have recorded one

Names are the league's where the league knows the player, through the same index and the same
`/etc/ktp/reports.env` credentials voice_taunts.py uses; without them the report runs on in-game
names and says so in its header.

PUBLIC by decision (drew, 2026-10-31), unlike voice taunts: `--website` upserts snapshot() into
`ktp.own_weapon_kill_snapshot`, which anon may read, and keep-the-prac renders it.

Imports voice_taunts.py from its own directory (both deploy to /usr/local/bin) for the MySQL
reader, the league-name index and the version parser, rather than a third copy of them.

    own_weapon_kills.py --out /var/lib/ktp-own-weapon-kills/latest.md
                        [--since 2026-09-13] [--top 25] [--no-aliases] [--website]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone

import voice_taunts as vt

MIN_PRODUCER = (1, 35, 0)
RECENT = 25
FLUSH_LAG = 6


def kills_sql(since: str) -> str:
    # The frag row is looked up on (match, killer, victim) in both kill tables, up to FLUSH_LAG seconds
    # BEFORE the action row: the plugin buffers its own lines and flushes every 5 s, so the action is
    # logged 0-5 s after the frag (measured on assists, 2026-10-31: 103 rows, offsets 0..5). The same
    # killer cannot kill the same victim twice inside that, so MAX() just picks the one value.
    # match_id first rides idx_match_id (~300 frags) rather than victimId (~5,000). The hint caps it
    # server-side: these tables are MyISAM, so a runaway read holds a table lock that stalls the
    # daemon's inserts (measured 2026-10-31).
    return f"""
SELECT /*+ MAX_EXECUTION_TIME(120000) */ pa.id, pa.eventTime, pa.match_id, m.match_type, pa.map,
       pa.playerId, kp.lastName, pa.victimId, vp.lastName,
       IFNULL(MAX(f.weapon), IFNULL(MAX(t.weapon), '?')), COUNT(t.id) > 0
FROM hlstats_Events_PlayerPlayerActions pa
JOIN hlstats_Actions a ON a.id = pa.actionId AND a.code = 'own_weapon_kill'
JOIN (SELECT match_id, MIN(match_type) AS match_type, MIN(start_time) AS start_time
      FROM ktp_matches GROUP BY match_id) m ON m.match_id = pa.match_id
JOIN hlstats_Players kp ON kp.playerId = pa.playerId
JOIN hlstats_Players vp ON vp.playerId = pa.victimId
LEFT JOIN hlstats_Events_Frags f
       ON f.match_id = pa.match_id AND f.eventTime BETWEEN pa.eventTime - INTERVAL {FLUSH_LAG} SECOND AND pa.eventTime AND f.killerId = pa.playerId AND f.victimId = pa.victimId
LEFT JOIN hlstats_Events_Teamkills t
       ON t.match_id = pa.match_id AND t.eventTime BETWEEN pa.eventTime - INTERVAL {FLUSH_LAG} SECOND AND pa.eventTime AND t.killerId = pa.playerId AND t.victimId = pa.victimId
WHERE m.start_time >= '{since}' AND m.match_type IS NOT NULL
GROUP BY pa.id
ORDER BY pa.eventTime, pa.id"""


def shape(rows: list[list[str]]) -> list[dict]:
    return [{"id": int(i), "time": t, "match_id": mid, "match_type": int(mtype), "map": mp,
             "killer_id": int(k), "killer": kn, "victim_id": int(v), "victim": vn,
             "weapon": w, "teamkill": tk == "1"}
            for i, t, mid, mtype, mp, k, kn, v, vn, w, tk in rows]


def resolve_names(kills: list[dict], steam_of: dict[int, set[str]], alias_index: dict[str, str]) -> int:
    """League alias where any of the player's steam ids is known; returns players resolved."""
    def league(pid):
        return next((alias_index[s] for s in sorted(steam_of.get(pid, ())) if s in alias_index), None)
    resolved = set()
    for k in kills:
        for id_key, name_key in (("killer_id", "killer"), ("victim_id", "victim")):
            name = league(k[id_key])
            if name:
                k[name_key] = name
                resolved.add(k[id_key])
    return len(resolved)


def board(kills: list[dict], played: dict[tuple[int, int], int], types: tuple[int, ...],
          side: str) -> list[dict]:
    """side 'victim' = most robbed, 'killer' = biggest thieves. Per match divides by capable matches."""
    other = "killer" if side == "victim" else "victim"
    by: dict[int, dict] = {}
    for k in kills:
        if k["match_type"] not in types:
            continue
        r = by.setdefault(k[f"{side}_id"], {"pid": k[f"{side}_id"], "name": k[side], "n": 0, "teammate": 0,
                                            "others": Counter(), "weapons": Counter()})
        r["n"] += 1
        r["teammate"] += k["teamkill"]
        r["others"][k[other]] += 1
        r["weapons"][k["weapon"]] += 1
        r["name"] = k[side]  # latest name wins
    rows = []
    for r in by.values():
        n = sum(played.get((r["pid"], t), 0) for t in types)
        rows.append({"name": r["name"], "n": r["n"], "teammate": r["teammate"], "matches": n,
                     "per_match": r["n"] / n if n else None,
                     "top_other": max(r["others"].items(), key=lambda kv: (kv[1], kv[0]))[0],
                     "top_weapon": max(r["weapons"].items(), key=lambda kv: (kv[1], kv[0]))[0]})
    rows.sort(key=lambda r: (-r["n"], -(r["per_match"] or 0), r["name"]))
    return rows


def snapshot(kills: list[dict], played: dict[tuple[int, int], int], since: str, generated: str,
             names_note: str = "", matches: int = 0) -> dict:
    """Everything the report shows, as data: the markdown renders it and the website stores it as-is."""
    all_types = tuple(sorted({k["match_type"] for k in kills}))
    scopes = []
    for key, title, types in (("official", "Official matches", vt.OFFICIAL), ("all", "All match types", all_types)):
        scopes.append({"key": key, "title": title, "types": sorted({vt.TYPE_NAME[t] for t in types}),
                       "robbed": board(kills, played, types, "victim"),
                       "thieves": board(kills, played, types, "killer")})
    pairs = Counter((k["killer"], k["victim"]) for k in kills)
    return {
        "generated": generated, "since": since, "names_note": names_note,
        "kills": len(kills), "teammate": sum(k["teamkill"] for k in kills), "matches": matches,
        "scopes": scopes,
        "pairs": [{"killer": a, "victim": b, "n": n}
                  for (a, b), n in sorted(pairs.items(), key=lambda kv: (-kv[1], kv[0])) if n > 1],
        "weapons": [[w, n] for w, n in Counter(k["weapon"] for k in kills).most_common()],
        "recent": [{key: k[key] for key in ("time", "killer", "victim", "weapon", "teamkill", "map")}
                   for k in sorted(kills, key=lambda k: k["time"], reverse=True)[:RECENT]],
    }


def render(S: dict, top: int) -> str:
    esc = vt.esc
    L = ["# Killed with their own gun", "",
         f"Generated {S['generated']}. Tracked matches since {S['since']} on a server logging own-weapon kills "
         f"(stats_logging >= 1.35.0): {S['matches']} matches, {S['kills']} own-weapon kills, "
         f"{S['teammate']} of them by a teammate.", "",
         "An own-weapon kill = someone picks up the gun a player spawned with (dropped on death or with the "
         "drop key) and kills that player with it. Per match = count / matches the player appeared in on a "
         "server that logs the line. "
         + (S["names_note"] or "Names: league alias where the website knows the player, else the in-game alias."),
         ""]
    for s in S["scopes"]:
        for key, title, who, other in (("robbed", "Most robbed", "owner", "top thief"),
                                       ("thieves", "Biggest thieves", "thief", "top victim")):
            rows = s[key]
            L += [f"## {title} — {s['title']} (top {min(top, len(rows))} of {len(rows)})", ""]
            if not rows:
                L += ["none", ""]
                continue
            L += [f"| # | {who} | kills | by/of a teammate | matches | per match | {other} | top gun |",
                  "|---|---|---|---|---|---|---|---|"]
            for i, r in enumerate(rows[:top], 1):
                L.append(f"| {i} | {esc(r['name'])} | {r['n']} | {r['teammate']} | {r['matches']} "
                         f"| {vt.fmt(r['per_match'])} | {esc(r['top_other'])} | {r['top_weapon']} |")
            L.append("")
    L += ["## Repeat offenders (same thief, same owner, more than once)", ""]
    if S["pairs"]:
        L += ["| thief | owner | kills |", "|---|---|---|"]
        L += [f"| {esc(p['killer'])} | {esc(p['victim'])} | {p['n']} |" for p in S["pairs"][:top]]
    else:
        L.append("none")
    L += ["", f"## Latest {len(S['recent'])}", ""]
    if S["recent"]:
        L += ["| time | thief | owner | gun | teammate | map |", "|---|---|---|---|---|---|"]
        L += [f"| {r['time']} | {esc(r['killer'])} | {esc(r['victim'])} | {r['weapon']} "
              f"| {'yes' if r['teamkill'] else ''} | {r['map']} |" for r in S["recent"]]
    else:
        L.append("none")
    L += ["", "| gun | own-weapon kills |", "|---|---|"]
    L += [f"| {w} | {n} |" for w, n in S["weapons"]]
    return "\n".join(L) + "\n"


def publish_snapshot(S: dict, day: str) -> None:
    """Upsert tonight's snapshot into ktp.own_weapon_kill_snapshot (anon-readable). Keyed by date."""
    base = os.environ["KTP_SUPABASE_URL"].rstrip("/")
    key = os.environ["KTP_SUPABASE_SECRET_KEY"]
    req = urllib.request.Request(
        f"{base}/rest/v1/own_weapon_kill_snapshot?on_conflict=snapshot_date", method="POST",
        data=json.dumps({"snapshot_date": day, "payload": S}).encode("utf-8"),
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Profile": "ktp",
                 "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"})
    with urllib.request.urlopen(req, timeout=60):
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default="hlstatsx")
    ap.add_argument("--since", default="2026-09-13", help="season floor; matches starting before it are ignored")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--out", help="write the markdown here instead of stdout")
    ap.add_argument("--no-aliases", action="store_true", help="skip the website lookup; in-game names only")
    ap.add_argument("--website", action="store_true",
                    help="also upsert the snapshot into ktp.own_weapon_kill_snapshot (the public page reads it)")
    a = ap.parse_args()

    rc = 0
    kills = shape(vt.q(kills_sql(a.since), a.db))
    capable = {mid for mid, ver in vt.q(vt.manifests_sql(a.since), a.db) if vt.version_tuple(ver) >= MIN_PRODUCER}
    played = vt.matches_played(vt.q(vt.played_sql(a.since), a.db), capable)
    names_note = ""
    if a.no_aliases:
        names_note = "Names: in-game aliases (--no-aliases)."
    else:
        index, problem = vt.fetch_alias_index()
        if problem:
            names_note = f"Names: in-game aliases only — league lookup skipped ({problem})."
            print(f"warning: {problem}; in-game names used", file=sys.stderr)
        else:
            steam_of: dict[int, set[str]] = defaultdict(set)
            for pid, sid in vt.q(vt.STEAM_SQL, a.db):
                steam_of[int(pid)].add(sid)
            players = {k["killer_id"] for k in kills} | {k["victim_id"] for k in kills}
            n = resolve_names(kills, steam_of, index)
            names_note = (f"Names: league alias for {n} of {len(players)} players the website knows; "
                          "the rest keep the alias they played under.")
    now = datetime.now(timezone.utc)
    snap = snapshot(kills, played, a.since, now.strftime("%Y-%m-%d %H:%M UTC"), names_note, len(capable))
    text = render(snap, a.top)
    if a.website:
        # A failed upsert must not cost the night's markdown: write it anyway and exit 3 so the alert fires.
        try:
            publish_snapshot(snap, now.strftime("%Y-%m-%d"))
            print(f"website: ktp.own_weapon_kill_snapshot upserted for {now:%Y-%m-%d}")
        except (KeyError, urllib.error.URLError, TimeoutError) as exc:
            print(f"website: snapshot NOT published ({exc!r})", file=sys.stderr)
            rc = 3
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"own-weapon kills: {len(kills)} in {len(capable)} capable matches; report: {a.out}")
    else:
        sys.stdout.write(text)
    return rc


if __name__ == "__main__":
    sys.exit(main())
