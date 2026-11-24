#!/usr/bin/env python3
"""Load the LAN HUD archive into hlstatsx_lan. Runs ON the data server.

Every event lands in `hud_events` verbatim; the ones worth querying directly are
also written to typed tables. Raw-first is deliberate -- the typed tables can be
dropped and rebuilt from `hud_events` if the shape turns out wrong, without
going back to the LAN box.

Idempotent: truncates the hud_* tables before loading, so a re-run replaces
rather than doubles.

`hud_player_stats` is a lossy snapshot and `hud_kill_assists` is ground truth:
its `assists` counter under-reports, because the producer reads it while it is
being incremented. The miss is spread thinly across nearly every match rather
than concentrated, so a consumer reading the counter is quietly a few percent
low with nothing to notice. Read the event tables.

Not a per-kill cap, which is the first theory anyone reaches for: every assisted
kill carries exactly one assister, so there is no second assister to lose. The
producer is the externally maintained HUD observer, so the shortfall is theirs
and this note is the whole of our side of it.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile

DB = "hlstatsx_lan"
ARCHIVE = "/opt/ktp-lan-archive/philly-2026/lan-hud-matches.tar.gz"
BATCH = 2000


def esc(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v).replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ").replace("\r", " ")
    return "'" + s + "'"


class Sink:
    """Batches INSERTs into the mysql client, one long-lived process per run."""

    def __init__(self, table: str, cols: list[str]):
        self.table, self.cols, self.rows, self.total = table, cols, [], 0

    def add(self, *vals):
        self.rows.append("(" + ",".join(esc(v) for v in vals) + ")")
        if len(self.rows) >= BATCH:
            self.flush()

    def flush(self):
        if not self.rows:
            return
        sql = "INSERT INTO %s (%s) VALUES %s;" % (
            self.table, ",".join(self.cols), ",".join(self.rows))
        p = subprocess.run(["mysql", DB], input=sql, text=True, capture_output=True)
        if p.returncode:
            print("  !! %s: %s" % (self.table, p.stderr[:300]))
            sys.exit(1)
        self.total += len(self.rows)
        self.rows = []


def steam(v):
    """user_id is the SteamID; anything else (bots, world) is dropped to NULL."""
    return v if isinstance(v, str) and v.startswith("STEAM_") else None


def main() -> int:
    print("truncating hud_* tables...")
    tables = ["hud_events", "hud_player_stats", "hud_damage", "hud_kills",
              "hud_kill_assists", "hud_prone", "hud_flag_events", "hud_spawns"]
    subprocess.run(["mysql", DB], text=True,
                   input="".join("TRUNCATE TABLE %s;" % t for t in tables))

    sinks = {
        "events": Sink("hud_events", ["match_id", "half", "tick", "sent_at", "event", "payload"]),
        "stats": Sink("hud_player_stats",
                      ["match_id", "half", "tick", "steam_id", "name", "team", "kills", "deaths",
                       "assists", "damage", "hits", "hs_hits", "hs_kills", "gun_kills",
                       "nade_kills", "caps", "cap_breaks", "obj_score", "best_streak"]),
        "damage": Sink("hud_damage",
                       ["match_id", "half", "tick", "attacker_id", "victim_id", "damage",
                        "hitplace", "weapon", "victim_health"]),
        "kills": Sink("hud_kills",
                      ["match_id", "half", "tick", "killer_id", "victim_id", "weapon",
                       "headshot", "killer_prone", "victim_prone", "kill_class", "kill_type"]),
        "prone": Sink("hud_prone", ["match_id", "half", "tick", "steam_id", "state"]),
        "flags": Sink("hud_flag_events",
                      ["match_id", "half", "tick", "event", "flag_id", "flag_name",
                       "team", "steam_id"]),
        "spawns": Sink("hud_spawns",
                       ["match_id", "half", "tick", "steam_id", "name", "team", "class_id",
                        "weapon_primary", "weapon_secondary"]),
    }

    tar = tarfile.open(ARCHIVE, "r:gz")
    files = [m for m in tar.getmembers() if m.name.endswith("events.jsonl")]
    print("match files: %d" % len(files))

    seen = 0
    for i, member in enumerate(files, 1):
        fh = io.TextIOWrapper(tar.extractfile(member), encoding="utf-8", errors="replace")
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            seen += 1
            mid, half = o.get("match_id"), o.get("half", 0)
            tick, ev = o.get("tick"), o.get("event", "?")
            sinks["events"].add(mid, half, tick, o.get("plugin_sent_at"), ev, json.dumps(o))

            if ev == "player_stats_summary":
                for p in (o.get("players") or []):
                    sinks["stats"].add(
                        mid, half, tick, steam(p.get("user_id")), p.get("name"), p.get("team"),
                        p.get("kills", 0), p.get("deaths", 0), p.get("assists", 0),
                        p.get("damage", 0), p.get("hits", 0), p.get("hs_hits", 0),
                        p.get("hs_kills", 0), p.get("gun_kills", 0), p.get("nade_kills", 0),
                        p.get("caps", 0), p.get("cap_breaks", 0), p.get("obj_score", 0),
                        p.get("best_streak", 0))
            elif ev == "damage":
                sinks["damage"].add(mid, half, tick, steam(o.get("attacker_id")),
                                    steam(o.get("victim_id")), o.get("damage", 0),
                                    o.get("hitplace"), o.get("weapon"), o.get("victim_health"))
            elif ev == "kill":
                sinks["kills"].add(mid, half, tick, steam(o.get("killer_id")),
                                   steam(o.get("victim_id")), o.get("weapon"),
                                   1 if o.get("headshot") else 0, o.get("killer_prone"),
                                   o.get("victim_prone"), o.get("kill_class"), o.get("kill_type"))
            elif ev == "prone_change":
                sinks["prone"].add(mid, half, tick, steam(o.get("user_id")), o.get("state"))
            elif ev in ("flag_captured", "flag_cap_started", "flag_cap_stopped", "cap_break"):
                short = ev.replace("flag_", "")
                who = o.get("captor_ids") or ([o.get("breaker_id")] if o.get("breaker_id") else [])
                team = o.get("new_owner") or o.get("capping_team") or o.get("broke_team")
                if not who:
                    sinks["flags"].add(mid, half, tick, short, o.get("flag_id"),
                                       o.get("flag_name"), team, None)
                for w in who:
                    sinks["flags"].add(mid, half, tick, short, o.get("flag_id"),
                                       o.get("flag_name"), team, steam(w))
            elif ev == "player_spawn":
                sinks["spawns"].add(mid, half, tick, steam(o.get("user_id")), o.get("name"),
                                    o.get("team"), o.get("class_id"),
                                    o.get("weapon_primary"), o.get("weapon_secondary"))
        if i % 25 == 0:
            print("  %d/%d files, %d events" % (i, len(files), seen))

    for s in sinks.values():
        s.flush()
    print("\nevents read: %d" % seen)
    for k, s in sinks.items():
        print("  %-8s -> %-18s %8d rows" % (k, s.table, s.total))

    # kill assists: explode the list now that hud_kills has ids.
    # The join key is not unique -- two kills sharing a tick, killer and victim
    # would each take the other's assisters. Latent, not seen in the archive.
    print("\nexploding assist_ids...")
    sql = """
    INSERT INTO hud_kill_assists (kill_id, steam_id)
    SELECT k.id, jt.sid FROM hud_events e
    JOIN JSON_TABLE(e.payload->'$.assist_ids', '$[*]' COLUMNS (sid VARCHAR(32) PATH '$')) jt
    JOIN hud_kills k ON k.match_id = e.match_id AND k.half = e.half
                    AND k.tick <=> e.tick
                    AND k.killer_id <=> JSON_UNQUOTE(e.payload->'$.killer_id')
                    AND k.victim_id <=> JSON_UNQUOTE(e.payload->'$.victim_id')
    WHERE e.event = 'kill' AND JSON_LENGTH(e.payload->'$.assist_ids') > 0
      AND jt.sid LIKE 'STEAM\\\\_%';
    """
    p = subprocess.run(["mysql", DB], input=sql, text=True, capture_output=True)
    print(p.stderr[:300] if p.returncode else "  ok")

    # mark the final emission per player per half -- the summary repeats during
    # play, so anything reading it must take the last, never the sum.
    print("marking final stats rows...")
    subprocess.run(["mysql", DB], text=True, input="""
    UPDATE hud_player_stats s
    JOIN (SELECT match_id, half, steam_id, MAX(tick) mt FROM hud_player_stats
          GROUP BY match_id, half, steam_id) m
      ON m.match_id = s.match_id AND m.half = s.half
     AND m.steam_id = s.steam_id AND m.mt = s.tick
    SET s.is_final = 1;""")

    print("\n=== loaded ===")
    for t in tables:
        p = subprocess.run(["mysql", DB, "-N", "-e", "SELECT COUNT(*) FROM " + t],
                           text=True, capture_output=True)
        print("  %-20s %s" % (t, p.stdout.strip()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
