#!/usr/bin/env python3
"""Push completed match box scores from the game stack to ktpleague.gg.

`ktp.player_match_stat` on the site has four readers and no writer, so every
stats surface renders an empty room. This is the writer. Design and the
reasoning behind the split: `keep-the-prac/docs/PLAYER_STATS_INGEST.md`.

Push rather than pull, and not by preference: MySQL here binds 127.0.0.1, so a
site-side pull would need a tunnel from a serverless function into a production
game database. The site holds the service-role key; this host holds one shared
secret scoped to one endpoint.

This script stays dumb on purpose. It reads six tables, canonicalises SteamIDs,
emits JSON and POSTs it. It knows nothing about ktp.player, rosters, fixtures or
seasons -- all of that happens site-side, which is what lets a correction or a
late Steam link be re-derived from staged rows instead of another trip here.

    ktp-stats-export.py [--hours 48] [--dry-run] [--match-id ID] [--quiet]

Config: /etc/ktp/stats-export.conf (mode 600), or the environment.
    STATS_INGEST_URL     https://ktpleague.gg/api/internal/stats-ingest
    STATS_INGEST_SECRET  shared secret, matches Vercel's env of the same name
    STATS_EXPORT_DB_USER read-only MySQL user (default: ktp_site_export)
    STATS_EXPORT_DB_PASS
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

CONF = "/etc/ktp/stats-export.conf"
DB_NAME = "hlstatsx"
BATCH = 50  # the endpoint's own ceiling; a larger payload is a 400

# The two DoD objective actions. ⚠️ DoD writes `dod_control_point` /
# `dod_capture_area` -- grepping for CS's `Captured` returns 0 against millions
# of live rows and reads exactly like "the engine emits nothing".
FLAG_ACTIONS = ("dod_control_point", "dod_capture_area")

# hlstats_Events_* are utf8mb4_unicode_ci while the KTP ktp_* tables are
# utf8mb4_0900_ai_ci. Joining match_id across the families without this raises
# "Illegal mix of collations" -- which at least fails loudly, unlike most of the
# traps in this pipeline.
COLL = "COLLATE utf8mb4_unicode_ci"

STEAM64_BASE = 76561197960265728


class Db:
    """Thin wrapper over the `mysql` CLI, returning JSON.

    No python MySQL driver is installed on the data server and adding one to a
    production game-adjacent host to read six tables is not worth it -- the
    ingest monitor beside this script shells out the same way.

    Every query returns JSON built by MySQL rather than tab-separated columns.
    Player names carry tabs, newlines and fullwidth characters, and a delimiter
    parser silently mangles exactly the rows that identify a player.
    """

    def __init__(self, user: str, password: str, db: str = DB_NAME):
        self.args = ["mysql", "--default-character-set=utf8mb4", "--batch",
                     "--raw", "-N", "-u", user]
        if password:
            self.args.append(f"-p{password}")
        self.args.append(db)

    def json_rows(self, sql: str) -> list:
        out = subprocess.run(self.args + ["-e", sql], capture_output=True,
                             text=True, encoding="utf-8", errors="replace")
        if out.returncode != 0:
            raise SystemExit(f"mysql failed: {out.stderr.strip()[:400]}")
        body = out.stdout.strip()
        # JSON_ARRAYAGG over an empty set is NULL, which prints as the literal
        # "NULL" -- not an error and not valid JSON.
        if not body or body == "NULL":
            return []
        return json.loads(body)


def sql_str(value: str) -> str:
    """Quote a literal for MySQL. Inputs here are match ids read back out of the
    database, but quoting them anyway keeps that true if a caller changes."""
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def log(msg: str, *, quiet: bool = False) -> None:
    if not quiet:
        print(msg, flush=True)


def load_config() -> dict[str, str]:
    """Environment wins over the file, so a one-off run can override."""
    conf: dict[str, str] = {}
    if os.path.exists(CONF):
        with open(CONF, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                conf[k.strip()] = v.strip().strip('"').strip("'")
    for key in ("STATS_INGEST_URL", "STATS_INGEST_SECRET",
                "STATS_EXPORT_DB_USER", "STATS_EXPORT_DB_PASS"):
        if os.environ.get(key):
            conf[key] = os.environ[key]
    return conf


def steamid64(unique_id: str) -> str | None:
    """`Y:Z` -> 17-digit SteamID64.

    The game side stores no universe digit, so nothing can diverge here as long
    as nobody reconstructs a legacy `STEAM_0:` string on the way out -- which is
    exactly why the endpoint rejects those rather than normalising them.

    Returns None on anything unparseable: `HLTV` is a real row in
    hlstats_PlayerUniqueIds, and one bad row must degrade, never drop a batch.
    """
    raw = (unique_id or "").strip()
    if raw.startswith("STEAM_"):
        raw = raw.split(":", 1)[1] if ":" in raw else ""
    parts = raw.split(":")
    if len(parts) != 2:
        return None
    y, z = parts
    if y not in ("0", "1") or not z.isdigit():
        return None
    return str(STEAM64_BASE + int(z) * 2 + int(y))


def fetch_matches(db: Db, hours: int, match_id: str | None) -> list[dict]:
    """One row per match_id, with its half count and window.

    ktp_matches is per HALF -- a two-half match is two rows sharing a match_id.
    """
    if match_id:
        where = f"match_id = {sql_str(match_id)}"
    else:
        # The window is computed BY MySQL. These DATETIMEs are naive local time
        # (the box runs America/New_York), so comparing them against a UTC
        # instant silently shortens the window by the UTC offset -- 48 hours
        # became 44 and dropped four matches, with nothing to notice.
        where = (f"end_time is not null and end_time >= now() - interval {int(hours)} hour")
    # UNIX_TIMESTAMP resolves each DATETIME in the session zone, so it is right
    # per row across a DST boundary -- which a single run-wide offset would not
    # be on the nightly 14-day sweep.
    return db.json_rows(
        "select json_arrayagg(json_object("
        "  'gameMatchId', match_id, 'serverId', sid, 'mapName', map_,"
        "  'startedAt', started, 'endedAt', ended, 'halfCount', halves)) "
        "from (select match_id, max(server_id) sid, max(map_name) map_,"
        "             unix_timestamp(min(start_time)) started,"
        "             unix_timestamp(max(end_time)) ended,"
        "             count(*) halves "
        f"      from ktp_matches where {where} group by match_id) t"
    )


def fetch_box_score(db: Db, mid: str) -> dict[int, dict]:
    """Per-player totals for one match, keyed by hlstats playerId.

    ⚠️ `half = 0` is the MATCH TOTAL row, not a half. Summing every row returns
    exactly 2x the truth. Measured across 1,668 matches: 1,342 carry both a
    half-0 row and per-half rows, 326 carry ONLY half 0, none carry only
    per-half -- and the total never disagrees with the sum of its parts (0
    mismatches, against a control that found 19,677). So half 0 is both correct
    and the only shape present on every match; summing `half > 0` would silently
    drop the 326.
    """
    rows = db.json_rows(
        "select json_arrayagg(json_object("
        "  'playerId', player_id, 'kills', coalesce(kills,0),"
        "  'deaths', coalesce(deaths,0), 'headshots', coalesce(headshots,0),"
        "  'teamKills', coalesce(team_kills,0), 'suicides', coalesce(suicides,0),"
        "  'damage', coalesce(damage,0), 'score', coalesce(score,0))) "
        f"from ktp_match_stats where match_id = {sql_str(mid)} and half = 0"
    )
    return {r.pop("playerId"): r for r in rows}


def fetch_flags(db: Db, mid: str) -> dict[int, int]:
    """Objective captures per player. Not in ktp_match_stats -- only in events."""
    codes = ",".join(sql_str(c) for c in FLAG_ACTIONS)
    rows = db.json_rows(
        "select json_arrayagg(json_object('playerId', pid, 'flags', n)) from ("
        "  select e.playerId pid, count(*) n from hlstats_Events_PlayerActions e"
        "  join hlstats_Actions a on a.id = e.actionId "
        f" where a.code in ({codes}) and e.match_id {COLL} = {sql_str(mid)} "
        "  group by e.playerId) t"
    )
    return {r["playerId"]: int(r["flags"]) for r in rows}


def fetch_players(db: Db, mid: str) -> list[dict]:
    """Roster for one match. steam_id here is already `Y:Z`, no universe digit.

    Joined to hlstats_PlayerUniqueIds so the box score (keyed by playerId) and
    the roster (keyed by steam_id) can be matched without trusting names.
    """
    return db.json_rows(
        "select json_arrayagg(json_object("
        "  'steamId', p.steam_id, 'playerName', p.player_name,"
        "  'team', p.team, 'playerId', u.playerId)) "
        "from ktp_match_players p "
        # Second crossing of the same collation boundary as fetch_flags, and it
        # bites here too: hlstats_PlayerUniqueIds is utf8mb4_unicode_ci, the
        # ktp_* tables are utf8mb4_0900_ai_ci.
        f"left join hlstats_PlayerUniqueIds u on u.uniqueId = p.steam_id {COLL} "
        f"where p.match_id = {sql_str(mid)}"
    )


def build_match(db: Db, m: dict, quiet: bool) -> dict | None:
    mid = m["gameMatchId"]
    roster = fetch_players(db, mid)
    if not roster:
        return None

    box = fetch_box_score(db, mid)
    flags = fetch_flags(db, mid)

    players, skipped = [], 0
    for row in roster:
        sid64 = steamid64(row["steamId"])
        if sid64 is None:
            skipped += 1  # HLTV and other non-player unique ids land here
            continue
        stats = box.get(row["playerId"], {})
        team = row["team"] if row["team"] in (1, 2) else None
        entry = {
            "steamId64": sid64,
            "kills": stats.get("kills", 0),
            "deaths": stats.get("deaths", 0),
            "flags": flags.get(row["playerId"], 0),
        }
        if row["playerName"]:
            entry["playerName"] = row["playerName"][:64]
        if team:
            entry["gameTeam"] = team
        for key in ("headshots", "teamKills", "suicides", "damage", "score"):
            if key in stats:
                entry[key] = stats[key]
        players.append(entry)

    if skipped:
        log(f"  {mid}: skipped {skipped} unresolvable unique id(s)", quiet=quiet)

    def iso(epoch):
        """Epoch seconds -> RFC3339 UTC. The endpoint requires an offset, and a
        naive local DATETIME stamped with `Z` is wrong by the UTC offset while
        looking entirely well-formed."""
        if epoch is None:
            return None
        return (datetime.fromtimestamp(int(epoch), timezone.utc)
                .isoformat().replace("+00:00", "Z"))

    return {
        "gameMatchId": mid,
        "serverId": m["serverId"],
        "mapName": m["mapName"],
        "startedAt": iso(m["startedAt"]),
        "endedAt": iso(m["endedAt"]),
        "halfCount": m["halfCount"],
        # KTP_MATCH_END is the only writer of ktp_match_stats, so a crashed or
        # .forcereset match leaves a roster and no box score. Saying so lets the
        # site stage it and refuse to derive -- twelve 0/0/0 rows would render
        # identically to a match nobody scored in.
        "statsComplete": bool(box),
        "players": players,
    }


def post(url: str, secret: str, payload: dict, quiet: bool) -> bool:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "x-internal-stats": secret},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            log(f"  -> {resp.status} {resp.read(400).decode('utf-8', 'replace')}",
                quiet=quiet)
            return True
    except urllib.error.HTTPError as exc:
        # Print the body: the endpoint names the failing fields deliberately,
        # and a bare status against an unattended exporter is indistinguishable
        # from the site being down.
        detail = exc.read(800).decode("utf-8", "replace")
        print(f"  !! HTTP {exc.code}: {detail}", file=sys.stderr)
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"  !! {exc}", file=sys.stderr)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=48,
                    help="export matches ending within this window (default 48)")
    ap.add_argument("--match-id", help="export exactly one match, ignoring --hours")
    ap.add_argument("--dry-run", action="store_true",
                    help="build and print the payload; POST nothing")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    conf = load_config()
    if not args.dry_run:
        missing = [k for k in ("STATS_INGEST_URL", "STATS_INGEST_SECRET")
                   if not conf.get(k)]
        if missing:
            print(f"missing config: {', '.join(missing)} "
                  f"(set in {CONF} or the environment)", file=sys.stderr)
            return 2

    db = Db(conf.get("STATS_EXPORT_DB_USER", "ktp_site_export"),
            conf.get("STATS_EXPORT_DB_PASS", ""))

    matches = fetch_matches(db, args.hours, args.match_id)
    log(f"{len(matches)} match(es) in window", quiet=args.quiet)

    built = []
    for m in matches:
        b = build_match(db, m, args.quiet)
        if b:
            built.append(b)

    if not built:
        log("nothing to export", quiet=args.quiet)
        return 0

    incomplete = sum(1 for b in built if not b["statsComplete"])
    log(f"built {len(built)} match(es), {incomplete} without a box score",
        quiet=args.quiet)

    if args.dry_run:
        print(json.dumps({"source": "hlstatsx", "matches": built}, indent=2))
        return 0

    ok = True
    for i in range(0, len(built), BATCH):
        chunk = built[i:i + BATCH]
        log(f"POST {len(chunk)} match(es)", quiet=args.quiet)
        payload = {
            "source": "hlstatsx",
            "exportedAt": datetime.now(timezone.utc).isoformat(),
            "matches": chunk,
        }
        ok = post(conf["STATS_INGEST_URL"], conf["STATS_INGEST_SECRET"],
                  payload, args.quiet) and ok

    # Non-zero on failure so the systemd OnFailure wiring carries it to Discord.
    # An exporter that fails silently is the same defect as the stats it exists
    # to surface.
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
