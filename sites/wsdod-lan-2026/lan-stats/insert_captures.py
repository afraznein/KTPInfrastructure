#!/usr/bin/env python3
"""Insert the recovered captures into `hlstatsx_lan` in prod's exact shape.

Idempotent: it clears any rows it previously wrote before inserting, so a re-run
after a parser fix does not double-count. It only ever touches
`hlstats_Events_PlayerActions` and `hlstats_Actions` in `hlstatsx_lan` -- never
the live league database, whose serverIds and playerIds overlap the LAN's.
"""

from __future__ import annotations

import json
import os
import sys
import warnings

import paramiko

warnings.filterwarnings("ignore")

DB = "hlstatsx_lan"
PORT_TO_SERVER = {27015: 26, 27016: 27, 27017: 28, 27018: 29, 27019: 30}
ACTION_ID = {"dod_control_point": 337, "dod_capture_area": 338, "dod_object_goal": 339}
BONUS = 6

# Mirrors prod's rows exactly, including the for_* flags -- those are what tell
# HLStatsX which event stream an action belongs to.
SEED = """
INSERT IGNORE INTO hlstats_Actions
 (id, game, code, reward_player, reward_team, team, description,
  for_PlayerActions, for_PlayerPlayerActions, for_TeamActions, for_WorldActions, count)
VALUES
 (337,'dod','dod_control_point',6,1,'','Control Points Captured','1','0','1','0',0),
 (338,'dod','dod_capture_area',6,1,'','Areas Captured','1','0','1','0',0),
 (339,'dod','dod_object_goal',4,0,'','Objectives Achieved','1','0','0','0',0);
"""


def main() -> int:
    caps = json.load(open("captures-placed.json", encoding="utf-8"))
    print("captures to insert:", len(caps))

    # Nothing hardcoded: this repo is public, and a committed password is a
    # published one. Key auth is the direction the data server is moving in;
    # KTP_DATA_PASSWORD stays as a fallback until that lands everywhere.
    host = os.environ.get("KTP_DATA_HOST", "")
    if not host:
        raise SystemExit(
            "KTP_DATA_HOST is unset — set it to the stats host (user@host or "
            "host). Unset otherwise surfaces as a connection failure.")
    user, _, hostname = host.rpartition("@")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(hostname, username=user or "root",
              password=os.environ.get("KTP_DATA_PASSWORD") or None, timeout=25)

    def sql(q, t=300):
        cmd = "mysql %s -N -e %s 2>&1" % (DB, _quote(q))
        _, o, _ = c.exec_command(cmd, timeout=t)
        return o.read().decode("utf-8", "replace").strip()

    print("\nseeding action definitions...")
    print(sql(SEED) or "  ok")
    print(sql("SELECT id, code, description FROM hlstats_Actions ORDER BY id"))

    # SteamID -> playerId. uniqueId is stored without the STEAM_0: prefix.
    rows = sql("SELECT playerId, uniqueId FROM hlstats_PlayerUniqueIds")
    lookup = {}
    for line in rows.splitlines():
        pid, _, uid = line.partition("\t")
        lookup[uid.strip()] = int(pid)
    print("\nplayer id map: %d entries" % len(lookup))

    values, unknown = [], {}
    for cap in caps:
        uid = cap["steam"].split(":", 1)[1]          # STEAM_0:1:x -> 1:x
        pid = lookup.get(uid)
        if pid is None:
            unknown[cap["steam"]] = unknown.get(cap["steam"], 0) + 1
            continue
        server = PORT_TO_SERVER.get(cap["port"])
        action = ACTION_ID.get(cap["action"])
        if not server or not action:
            continue
        values.append("('%s',%d,'%s','%s',%d,%d,%d)" % (
            cap["t"].replace("T", " "), server, _esc(cap["map"]),
            _esc(cap["match_id"]), pid, action, BONUS))

    print("resolved   : %d" % len(values))
    print("unresolved : %d players / %d events" % (len(unknown), sum(unknown.values())))
    for s, n in sorted(unknown.items(), key=lambda kv: -kv[1])[:5]:
        print("   %-24s %d" % (s, n))

    if not values:
        print("nothing to insert")
        return 1

    # Idempotent: drop what a previous run of this script inserted.
    print("\nclearing prior recovered rows...")
    print(sql("DELETE FROM hlstats_Events_PlayerActions WHERE actionId IN (337,338,339)") or "  ok")

    print("inserting in batches...")
    cols = "(eventTime, serverId, map, match_id, playerId, actionId, bonus)"
    for i in range(0, len(values), 500):
        chunk = ",".join(values[i:i + 500])
        err = sql("INSERT INTO hlstats_Events_PlayerActions %s VALUES %s" % (cols, chunk))
        if err:
            print("  batch %d: %s" % (i // 500, err[:200]))
            return 1
    print("  %d rows" % len(values))

    # Keep hlstats_Actions.count consistent with the events, as prod does.
    sql("UPDATE hlstats_Actions a SET count = "
        "(SELECT COUNT(*) FROM hlstats_Events_PlayerActions e WHERE e.actionId = a.id) "
        "WHERE a.id IN (337,338,339)")

    print("\n=== verification ===")
    print(sql("SELECT a.code, COUNT(*) events, COUNT(DISTINCT e.playerId) players, "
              "COUNT(DISTINCT e.match_id) matches FROM hlstats_Events_PlayerActions e "
              "JOIN hlstats_Actions a ON a.id = e.actionId GROUP BY a.code"))
    print("\nsample row (prod shape):")
    print(sql("SELECT * FROM hlstats_Events_PlayerActions ORDER BY id LIMIT 2"))
    c.close()
    return 0


def _esc(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace("'", "''")


def _quote(q: str) -> str:
    return "'" + q.replace("'", "'\\''") + "'"


if __name__ == "__main__":
    sys.exit(main())
