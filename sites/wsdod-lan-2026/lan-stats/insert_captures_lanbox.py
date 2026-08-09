#!/usr/bin/env python3
"""Write the recovered captures back to the LAN box's own hlstatsx.

The clone on the data server already has them; this makes the source of truth
agree with its copy, so the box is not left as the one system that disagrees.

Generates a .sql file locally and uploads it rather than shelling 6,000 INSERTs
through sudo -- quoting player-supplied map/match strings through two layers of
shell is exactly where an injection or a mangled row comes from.

Idempotent: the script deletes actionId 337/338/339 rows before inserting, so
re-running after a parser fix replaces rather than duplicates.
"""

from __future__ import annotations

import json
import os
import sys
import warnings

import paramiko

warnings.filterwarnings("ignore")

# The venue box's address and login, from the environment: this repo is public,
# and a committed password is a published one.
HOST = os.environ.get("KTP_LANBOX_HOST", "")
USER = os.environ.get("KTP_LANBOX_USER", "")
PW = os.environ.get("KTP_LANBOX_PASSWORD") or None
if not HOST or not USER:
    raise SystemExit(
        "KTP_LANBOX_HOST / KTP_LANBOX_USER are unset — set them for the venue "
        "box. Unset otherwise surfaces as a connection failure.")
PORT_TO_SERVER = {27015: 26, 27016: 27, 27017: 28, 27018: 29, 27019: 30}
ACTION_ID = {"dod_control_point": 337, "dod_capture_area": 338, "dod_object_goal": 339}
BONUS = 6

HEADER = """-- Recovered LAN capture events, rebuilt from the HLDS logs.
-- The LAN HLStatsX ran with an unseeded hlstats_Actions table, so every
-- dod_control_point / dod_capture_area event was discarded at ingest. Kills and
-- weapon stats were unaffected. Rebuilt to match the fleet's row shape exactly.
SET NAMES utf8mb4;
START TRANSACTION;

INSERT IGNORE INTO hlstats_Actions
 (id, game, code, reward_player, reward_team, team, description,
  for_PlayerActions, for_PlayerPlayerActions, for_TeamActions, for_WorldActions, count)
VALUES
 (337,'dod','dod_control_point',6,1,'','Control Points Captured','1','0','1','0',0),
 (338,'dod','dod_capture_area',6,1,'','Areas Captured','1','0','1','0',0),
 (339,'dod','dod_object_goal',4,0,'','Objectives Achieved','1','0','0','0',0);

DELETE FROM hlstats_Events_PlayerActions WHERE actionId IN (337,338,339);
"""

FOOTER = """
UPDATE hlstats_Actions a SET count =
  (SELECT COUNT(*) FROM hlstats_Events_PlayerActions e WHERE e.actionId = a.id)
  WHERE a.id IN (337,338,339);

COMMIT;
"""


def esc(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace("'", "\\'")


def main() -> int:
    caps = json.load(open("captures-placed.json", encoding="utf-8"))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PW, timeout=25)

    def sudo(script, t=600):
        cmd = "echo %s | sudo -S bash -c '%s' 2>&1" % (PW, script.replace("'", "'\\''"))
        _, o, _ = c.exec_command(cmd, timeout=t)
        return o.read().decode("utf-8", "replace").strip()

    # Resolve against the BOX's own id map, not the clone's. They should match,
    # but assuming that is how a silent mis-attribution happens.
    rows = sudo('mysql hlstatsx -N -e "SELECT playerId, uniqueId FROM hlstats_PlayerUniqueIds"')
    lookup = {}
    for line in rows.splitlines():
        pid, _, uid = line.partition("\t")
        if pid.strip().isdigit():
            lookup[uid.strip()] = int(pid)
    print("player id map on the box: %d entries" % len(lookup))

    values, unresolved = [], 0
    for cap in caps:
        pid = lookup.get(cap["steam"].split(":", 1)[1])
        server, action = PORT_TO_SERVER.get(cap["port"]), ACTION_ID.get(cap["action"])
        if pid is None or not server or not action:
            unresolved += 1
            continue
        values.append("('%s',%d,'%s','%s',%d,%d,%d)" % (
            cap["t"].replace("T", " "), server, esc(cap["map"]),
            esc(cap["match_id"]), pid, action, BONUS))
    print("resolved %d / %d  (unresolved %d)" % (len(values), len(caps), unresolved))
    if unresolved:
        print("!! refusing to write a partial recovery")
        return 1

    sql = [HEADER]
    cols = "INSERT INTO hlstats_Events_PlayerActions (eventTime, serverId, map, match_id, playerId, actionId, bonus) VALUES\n"
    for i in range(0, len(values), 500):
        sql.append(cols + ",\n".join(values[i:i + 500]) + ";\n")
    sql.append(FOOTER)
    blob = "".join(sql)

    local = "lanbox-captures-recovery.sql"
    with open(local, "w", encoding="utf-8", newline="\n") as f:
        f.write(blob)
    print("generated %s (%.1f MB)" % (local, len(blob) / 1048576))

    sf = c.open_sftp()
    sf.put(local, "/tmp/captures-recovery.sql")
    sf.close()

    print("\napplying...")
    out = sudo("mysql hlstatsx < /tmp/captures-recovery.sql && echo APPLIED")
    print(out or "(no output)")

    print("\n=== verification on the box ===")
    print(sudo('mysql hlstatsx -N -e "SELECT a.code, COUNT(*) events, '
               'COUNT(DISTINCT e.playerId) players, COUNT(DISTINCT e.match_id) matches '
               'FROM hlstats_Events_PlayerActions e JOIN hlstats_Actions a ON a.id=e.actionId '
               'GROUP BY a.code"'))
    print(sudo("rm -f /tmp/captures-recovery.sql && echo 'temp sql removed'"))
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
