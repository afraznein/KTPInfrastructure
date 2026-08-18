#!/usr/bin/env python3
"""Count grenades thrown, per player per day, so a grenade kill % has a denominator.

Dry run by default: writes grenade-throws.json and grenade-throws-gate.json next
to this file and prints the verification. Nothing here writes to MySQL.

    python build_grenade_throws.py           # rebuild both files, run the gate
    python build_grenade_throws.py --check   # exit 1 if either file is stale

WHICH COLUMN IS A THROW
-----------------------
hlstats_Events_Statsme carries four grenade weapon names and only one pair can
be a throw count:

  grenade / grenade2          the held Allied / Axis grenade. Its `shots` is NOT
                              throws. dodx increments it from TWO paths -- the
                              CurWeapon clip decrement, and TraceLine_Post, which
                              fires once per trace the explosion's radius damage
                              casts at a candidate entity (dodx traceData maps
                              classname "grenade" to ACT_NADE_SHOT). Radius traces
                              dominate, so the count scales with map geometry and
                              with how many bodies were near the blast.
  handgrenade_ex /            the primed grenade, i.e. the pin-pulled weapon the
  stickgrenade_ex             player is holding when it leaves their hand. Records
                              `shots` and nothing else -- no hits, no damage, no
                              kills -- which is what a throw looks like.

Verified rather than assumed, in the curated set: the _ex pair splits cleanly by
side (no player-half carries both, and handgrenade_ex pairs with grenade damage
while stickgrenade_ex pairs with grenade2), so a player's throws is the sum of
whichever they threw across both halves. The held pair's per-player-half maximum
is several times what a player could physically throw in a half, while the _ex
maximum sits in a plausible range.

WHY THE GATE STILL FAILS
------------------------
_ex undercounts, per player, and the shortfall is not recoverable. Both the throw
and the pin-pull reach dodx as CurWeapon messages, and which weapon id is current
when the clip decrement lands is a frame-timing race: cook the grenade and the
decrement is seen against the _ex weapon, throw it fast enough and the client is
back on the held grenade before the message goes out, so the throw is counted
under `grenade`/`grenade2` -- where the radius-damage traces make it
unrecoverable. Some players register no _ex rows at all across the whole event
while scoring plenty of grenade kills.

So this generator computes both halves of the ratio and refuses to bless the
result: a non-zero exit and a `passed: false` in the gate file mean the
percentage would exceed 100 for real players and the column must not ship.

Kills come from the frag log, matching build_awards.py's `nade_kills`, so the
board and the award cannot disagree. Statsme's own kills column is reported
alongside for the discrepancy, never used.
"""

from __future__ import annotations

import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB = "hlstatsx_lan"
EDITION = "Philly LAN 2026"
OUT = os.path.join(HERE, "grenade-throws.json")
GATE = os.path.join(HERE, "grenade-throws-gate.json")

THROW_WEAPONS = ("handgrenade_ex", "stickgrenade_ex")
KILL_WEAPONS = ("grenade", "grenade2")


def connect():
    """SSH to the stats host. Credentials come from ktp_hosts.py, never from here.

    Same resolution order as build_awards.py: the env pair first for a clone,
    then a walk up for ktp_hosts.py -- counted from a fixed depth it works in a
    plain checkout and reports missing credentials inside a worktree.
    """
    import paramiko

    host = os.environ.get("KTP_DATA_HOST", "")
    if host:
        user, _, hostname = host.rpartition("@")
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(hostname, username=user or "root",
                  password=os.environ.get("KTP_DATA_PASSWORD") or None, timeout=25)
        return c

    hosts_dir = os.environ.get("KTP_HOSTS_DIR")
    if not hosts_dir:
        d = HERE
        while d != os.path.dirname(d):
            if os.path.exists(os.path.join(d, "ktp_hosts.py")):
                hosts_dir = d
                break
            d = os.path.dirname(d)
    if hosts_dir and hosts_dir not in sys.path:
        sys.path.insert(0, hosts_dir)
    try:
        from ktp_hosts import connect as ktp_connect
    except ImportError:
        raise SystemExit(
            "no credentials: set KTP_DATA_HOST (+ KTP_DATA_PASSWORD), or point "
            "KTP_HOSTS_DIR at the directory holding ktp_hosts.py")
    return ktp_connect("data")


def sql(c, q, t=900):
    cmd = "mysql %s -N --raw -e '%s' 2>&1" % (DB, q.replace("'", "'\\''"))
    _, o, _ = c.exec_command(cmd, timeout=t)
    out = o.read().decode("utf-8", "replace").strip()
    if out.startswith("ERROR"):
        raise RuntimeError(out[:400])
    return [ln.split("\t") for ln in out.splitlines() if ln.strip()]


def sid(v):
    """Canonical player key 'Y:Z' -- the form lan-stats.json keys on."""
    v = (v or "").strip()
    if v.upper().startswith("STEAM_"):
        v = v.split(":", 1)[1] if ":" in v else v
    return v


def quoted(names):
    return ",".join("'%s'" % n for n in names)


def gather(c):
    """Throws, kills and the day each match belongs to, for the curated set."""
    with open(os.path.join(HERE, "match-teams.json"), encoding="utf-8") as fh:
        curated = sorted(json.load(fh))
    ids = quoted(curated)

    days = {}
    for mid, start in sql(c, "SELECT match_id, MIN(start_time) FROM ktp_matches "
                             "WHERE match_id IN (%s) GROUP BY match_id" % ids):
        days[mid] = start[5:10]
    missing = set(curated) - set(days)
    if missing:
        raise SystemExit("ktp_matches has no row for %d curated match(es): %s"
                         % (len(missing), sorted(missing)))

    # half IN (1,2): half 0 is the match total and would double everything.
    throws = {}
    for mid, uid, n in sql(c, """
            SELECT s.match_id, u.uniqueId, SUM(s.shots)
            FROM hlstats_Events_Statsme s
            JOIN hlstats_PlayerUniqueIds u ON u.playerId = s.playerId
            WHERE s.half IN (1,2) AND s.match_id IN (%s) AND s.weapon IN (%s)
            GROUP BY s.match_id, u.uniqueId""" % (ids, quoted(THROW_WEAPONS))):
        throws[(mid, sid(uid))] = int(n or 0)

    # killerId <> victimId: a grenade suicide is not a grenade kill.
    kills = {}
    for mid, uid, n in sql(c, """
            SELECT f.match_id, u.uniqueId, COUNT(*)
            FROM hlstats_Events_Frags f
            JOIN hlstats_PlayerUniqueIds u ON u.playerId = f.killerId
            WHERE f.half IN (1,2) AND f.match_id IN (%s) AND f.weapon IN (%s)
              AND f.killerId <> f.victimId
            GROUP BY f.match_id, u.uniqueId""" % (ids, quoted(KILL_WEAPONS))):
        kills[(mid, sid(uid))] = int(n or 0)

    statsme_kills = sum(int(n or 0) for _, n in sql(c, """
            SELECT s.weapon, SUM(s.kills) FROM hlstats_Events_Statsme s
            WHERE s.half IN (1,2) AND s.match_id IN (%s) AND s.weapon IN (%s)
            GROUP BY s.weapon""" % (ids, quoted(KILL_WEAPONS))))

    names = {}
    for uid, name in sql(c, """
            SELECT u.uniqueId, MAX(p.lastName) FROM hlstats_PlayerUniqueIds u
            JOIN hlstats_Players p ON p.playerId = u.playerId GROUP BY u.uniqueId"""):
        names[sid(uid)] = name
    return curated, days, throws, kills, statsme_kills, names


def fold(days, per_match):
    out = {}
    for (mid, steam), n in per_match.items():
        key = (days[mid], steam)
        out[key] = out.get(key, 0) + n
    return out


def build(c):
    curated, days, throws, kills, statsme_kills, names = gather(c)
    day_throws = fold(days, throws)
    day_kills = fold(days, kills)

    report = {"generated_for": EDITION, "days": {}}
    for day in sorted(set(days.values())):
        report["days"][day] = {
            s: n for (d, s), n in sorted(day_throws.items()) if d == day}

    cells = sorted(set(day_throws) | set(day_kills))
    violations = [
        {"day": d, "steam_id": s, "name": names.get(s, ""),
         "kills": day_kills.get((d, s), 0), "throws": day_throws.get((d, s), 0)}
        for (d, s) in cells
        if day_kills.get((d, s), 0) > day_throws.get((d, s), 0)]
    violations.sort(key=lambda v: -(v["kills"] - v["throws"]))

    rated = [day_kills.get(k, 0) / day_throws[k]
             for k in day_throws if day_throws[k] > 0]
    rated.sort()
    total_throws = sum(day_throws.values())
    total_kills = sum(day_kills.values())

    gate = {
        "generated_for": EDITION,
        "passed": not violations,
        "denominator": "hlstats_Events_Statsme shots for %s" % ", ".join(THROW_WEAPONS),
        "numerator": "hlstats_Events_Frags weapon in %s, self-kills excluded"
                     % ", ".join(KILL_WEAPONS),
        "matches": len(curated),
        "cells": len(cells),
        "violations": len(violations),
        "violation_detail": violations,
        "throws": total_throws,
        "kills": total_kills,
        "statsme_kills": statsme_kills,
        "event_percent": round(100.0 * total_kills / total_throws, 2)
        if total_throws else None,
        "per_player_day_rate": {
            "n": len(rated),
            "min": round(rated[0], 3) if rated else None,
            "median": round(statistics.median(rated), 3) if rated else None,
            "max": round(rated[-1], 3) if rated else None,
        },
        "zero_throw_players": sorted(
            {v["steam_id"] for v in violations if v["throws"] == 0}),
    }
    return report, gate


def announce(gate):
    print("matches %d  cells %d  throws %d  frag-log kills %d  (statsme says %d)"
          % (gate["matches"], gate["cells"], gate["throws"], gate["kills"],
             gate["statsme_kills"]))
    print("event-wide grenade kill rate: %s%%" % gate["event_percent"])
    r = gate["per_player_day_rate"]
    print("per player-day rate: min %s  median %s  max %s  (n=%s)"
          % (r["min"], r["median"], r["max"], r["n"]))
    if gate["passed"]:
        print("GATE PASSED: no player has more grenade kills than grenades thrown")
        return
    print("GATE FAILED: %d of %d player-days have more grenade kills than throws"
          % (gate["violations"], gate["cells"]))
    for v in gate["violation_detail"][:15]:
        print("   %-6s %-14s kills %3d  throws %3d  %s"
              % (v["day"], v["steam_id"], v["kills"], v["throws"],
                 v["name"].encode("ascii", "replace").decode("ascii")))
    print("DO NOT INJECT - the denominator undercounts, see this file's docstring")


def dump(path, obj):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, indent=1)
        fh.write("\n")


def current(path, obj):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh) == obj
    except (OSError, ValueError):
        return False


def main() -> int:
    check = "--check" in sys.argv[1:]
    c = connect()
    try:
        report, gate = build(c)
    finally:
        c.close()
    announce(gate)

    if check:
        stale = [n for n, p, o in (("grenade-throws.json", OUT, report),
                                   ("grenade-throws-gate.json", GATE, gate))
                 if not current(p, o)]
        if stale:
            print("STALE: %s - re-run build_grenade_throws.py" % ", ".join(stale))
            return 1
        print("both files are current")
        return 0 if gate["passed"] else 1

    dump(OUT, report)
    dump(GATE, gate)
    print("wrote %s and %s" % (os.path.basename(OUT), os.path.basename(GATE)))
    return 0 if gate["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
