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
import hashlib
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

# League play only. 0 is `.ktp`, 4 is `.ktpOT`; 1/2/3/5 are scrim, 12-man and
# draft, and NULL is untyped. Canonical copy lives in scripts/report_scope.py
# as OFFICIAL_MATCH_TYPES -- duplicated here because this script deploys as a
# standalone file to /usr/local/bin with no package to import from. Keep the
# two in step.
OFFICIAL_MATCH_TYPES = (0, 4)

# What was last sent, so a match already accepted is not re-POSTed on every
# tick. Keyed by match id, valued by a hash of the built payload, so a match
# whose stats are still being corrected is re-sent and a settled one is not.
STATE_PATH = os.environ.get(
    "STATS_EXPORT_STATE", "/var/lib/ktp-stats-export/sent.json")

# The two DoD objective actions. ⚠️ DoD writes `dod_control_point` /
# `dod_capture_area` -- grepping for CS's `Captured` returns 0 against millions
# of live rows and reads exactly like "the engine emits nothing".
#
# ⚠️ These are no longer what the site's Flags column ships. A capture ROW is
# not a scoreboard point: a 2-point flag captured by three players is three
# rows and six points. The review that found this was looking at 6 and 4 on the
# match page against 24 and 28 on the captains' screenshots. See
# fetch_objective_points().
FLAG_ACTIONS = ("dod_control_point", "dod_capture_area")

# A DoD round restart respawns everybody at one game_time, which is how the
# restart is found on halves recorded before the producer stamped round_live.
# Official matches are 6v6, so 8 is a quorum no ordinary respawn reaches.
RESTART_BURST_MIN_SPAWNS = 8

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
        # League play only -- see OFFICIAL_MATCH_TYPES. Without this the window
        # carries every pracc, scrim and 12-man match that happened to end in
        # it, and they reach the site as if they were results.
        types = ", ".join(str(t) for t in OFFICIAL_MATCH_TYPES)
        where = (f"end_time is not null and match_type in ({types}) "
                 f"and end_time >= now() - interval {int(hours)} hour")
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


def window_cte(mid: str) -> str:
    """The half's zero: the round RESTART, not the live command.

    DoD restarts a few seconds after the live command and the scoreboard zeroes
    at the restart, so a kill in that gap is on nobody's scoreboard. Measured
    across every match in the database: 422 such events, touching ~830 player
    rows, nearly all by one -- which is why this reads as a box score quietly
    off rather than as something broken.

    Two sources, preferred in order. `round_live` is the producer answering
    directly (plugin 1.24.5+). The spawn burst is the derivation for every half
    recorded before it, which is all of season 10 so far.

    ⚠️ MIN per half. A mid-half burst is a cap-out round restart, which does
    NOT reset the player rows.

    ⚠️ Everything here filters `ktp_life_events` by a literal match id and then
    joins on `half` alone. Joining the two table families on match_id would
    cross the utf8mb4_0900_ai_ci / utf8mb4_unicode_ci boundary COLL exists for;
    not joining on it at all is cheaper and cannot be got wrong.
    """
    return (
        "with stamped as ("
        "  select half, min(game_time) gt, min(event_time) et"
        "  from ktp_life_events"
        f" where match_id = {sql_str(mid)} and round_live = 1"
        "  group by half), "
        "burst as ("
        "  select half, min(game_time) gt, min(event_time) et from ("
        "    select half, game_time, min(event_time) event_time"
        "    from ktp_life_events"
        f"   where match_id = {sql_str(mid)}"
        "      and boundary_kind = 'start' and reason = 'spawn'"
        "    group by half, game_time"
        f"   having count(*) >= {RESTART_BURST_MIN_SPAWNS}) b"
        "  group by half), "
        "live as ("
        "  select h.half, coalesce(s.gt, b.gt) gt, coalesce(s.et, b.et) et"
        "  from (select half from stamped union select half from burst) h"
        "  left join stamped s on s.half = h.half"
        "  left join burst b on b.half = h.half) "
    )


def fetch_scoreboard_totals(db: Db, mid: str) -> dict[int, dict]:
    """Kills and deaths as the end-of-round scoreboard counts them.

    NOT `ktp_match_stats` -- that row is dodx's own counter and disagrees with
    the scoreboard three ways. Checked against both captains' screenshots of
    1789348403-ATL2, 36 cells: kills wrong on the player who got two kills
    before the restart, deaths wrong on six of twelve, and `score` short on
    eight. The event tables reproduce all 24 player rows exactly.

    A death is a frag row, a teamkill row or a suicide row. The three are
    DISJOINT -- no teamkill or suicide shares a victim and a second with a frag
    row, the nearest is 16 seconds away -- so they add, with no de-duplication.

    ⚠️ NULL-safe on the window. Some frag rows carry no game_time (2 of 535 on
    the worked match) and `NULL >= x` is NULL, so a naive predicate discards
    them silently; those fall back to the wall clock.
    """
    return {
        r.pop("playerId"): r
        for r in db.json_rows(
            window_cte(mid)
            + "select json_arrayagg(json_object("
            "  'playerId', pid, 'kills', k, 'deaths', d)) from ("
            "  select pid,"
            "         sum(case when role = 'killer' then 1 else 0 end) k,"
            "         sum(case when role = 'victim' then 1 else 0 end) d"
            "  from ("
            "    select f.killerId pid, 'killer' role from hlstats_Events_Frags f"
            "    left join live w on w.half = f.half"
            f"   where f.match_id {COLL} = {sql_str(mid)}"
            "      and (w.gt is null"
            "           or (f.game_time is not null and f.game_time >= w.gt)"
            "           or (f.game_time is null and f.eventTime >= w.et))"
            "    union all"
            "    select f.victimId, 'victim' from hlstats_Events_Frags f"
            "    left join live w on w.half = f.half"
            f"   where f.match_id {COLL} = {sql_str(mid)}"
            "      and (w.gt is null"
            "           or (f.game_time is not null and f.game_time >= w.gt)"
            "           or (f.game_time is null and f.eventTime >= w.et))"
            "    union all"
            # Teamkills and suicides carry no game_time, so they cut on the
            # wall clock. One-second granularity: a death inside the restart
            # second counts.
            "    select t.victimId, 'victim' from hlstats_Events_Teamkills t"
            "    left join live w on w.half = t.half"
            f"   where t.match_id {COLL} = {sql_str(mid)}"
            "      and (w.et is null or t.eventTime >= w.et)"
            "    union all"
            "    select u.playerId, 'victim' from hlstats_Events_Suicides u"
            "    left join live w on w.half = u.half"
            f"   where u.match_id {COLL} = {sql_str(mid)}"
            "      and (w.et is null or u.eventTime >= w.et)"
            "  ) events group by pid) t"
        )
    }


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


def fetch_objective_points(db: Db, mid: str) -> dict[int, int]:
    """The scoreboard's objective column: captures x what that flag is worth.

    NOT a count of capture rows, which is what this shipped until now and what
    the stats review caught: `-#over. chi` read 6 on the match page against 24
    on the screenshot. A flag is worth `ktp_flag_positions.points_for_cap` (2
    on most maps, 1 on the HQs), and every player who helped take it is
    credited the full value -- so three players on a 2-point flag is three rows
    and six points, and counting rows understates by about three times.

    Falls back to 1 point per capture where the map's flag value has not been
    observed yet: an unknown-value flag is still a capture, and the count is
    the same answer this function used to give.
    """
    rows = db.json_rows(
        window_cte(mid)
        + "select json_arrayagg(json_object('playerId', pid, 'flags', n)) from ("
        "  select fc.player_id pid, sum(coalesce(fp.points_for_cap, 1)) n"
        "  from ktp_flag_captures fc"
        "  left join (select map_name, flag_name, min(points_for_cap) points_for_cap"
        "             from ktp_flag_positions where points_for_cap is not null"
        "             group by map_name, flag_name) fp"
        "         on fp.flag_name = fc.flag_name"
        f"        and fp.map_name = (select max(map_name) from ktp_matches"
        f"                           where match_id = {sql_str(mid)})"
        "  left join live w on w.half = fc.half"
        f" where fc.match_id = {sql_str(mid)}"
        "    and (w.et is null or fc.event_time >= w.et)"
        "  group by fc.player_id) t"
    )
    return {r["playerId"]: int(r["flags"]) for r in rows}


def _side_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def sides_by_half(life_sides: list[dict]) -> dict[int, dict[int, int]]:
    """(half -> player_id -> engine side) from the life feed."""
    out: dict[int, dict[int, int]] = {}
    for row in life_sides:
        half = _side_int(row.get("half"))
        pid = _side_int(row.get("playerId"))
        team = _side_int(row.get("team"))
        if half and pid is not None and team in (1, 2):
            out.setdefault(half, {})[pid] = team
    return out


def canonical_teams(life_sides: list[dict]) -> dict[int, int]:
    """player_id -> canonical team, labelled by the final half's sides.

    ⚠️ Canonical copy is `scripts/roster_teams.py::canonical_teams`, which this
    file cannot import for the same reason as OFFICIAL_MATCH_TYPES above: it
    deploys standalone to /usr/local/bin with no package. Keep the two in step
    -- `tests/unit/test_stats_export_canonical_teams.py` fails on any drift.

    Empty when the feed is missing or only one half is present: with nothing to
    compare against, the roster's own team is as good as it gets.
    """
    sides = sides_by_half(life_sides)
    halves = sorted(sides)
    if len(halves) < 2:
        return {}
    final = halves[-1]
    canonical = dict(sides[final])
    for half in reversed(halves[:-1]):
        same = sum(1 for pid, side in sides[half].items()
                   if canonical.get(pid) == side)
        swapped = sum(1 for pid, side in sides[half].items()
                      if canonical.get(pid) == (2 if side == 1 else 1))
        if same == 0 and swapped == 0:
            continue
        flip = swapped > same
        for pid, side in sides[half].items():
            if pid not in canonical:
                canonical[pid] = (2 if side == 1 else 1) if flip else side
    return canonical


def fetch_life_sides(db: Db, mid: str) -> list[dict]:
    """Every (half, player, engine side) the life feed recorded for one match.

    Same guards as `sql/analytics/life_boundary_fact.sql`, so the correction
    this feeds reaches the same answer the match report does. No collation
    crossing here: both sides of the filter are ktp_* .
    """
    return db.json_rows(
        "select json_arrayagg(json_object("
        "  'half', half, 'playerId', player_id, 'team', team)) "
        "from ktp_life_events "
        f"where match_id = {sql_str(mid)} and half > 0 "
        "  and game_time >= 0 and event_epoch > 0 and team in (1, 2)"
    )


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
        # Second crossing of the same collation boundary as the event queries,
        # and it bites here too: hlstats_PlayerUniqueIds is utf8mb4_unicode_ci, the
        # ktp_* tables are utf8mb4_0900_ai_ci.
        f"left join hlstats_PlayerUniqueIds u on u.uniqueId = p.steam_id {COLL} "
        f"where p.match_id = {sql_str(mid)}"
    )


def build_match(db: Db, m: dict, quiet: bool) -> dict | None:
    mid = m["gameMatchId"]
    roster = fetch_players(db, mid)
    if not roster:
        return None

    # `ktp_match_players.team` is the side held in the LAST half a player
    # appeared in, and sides swap at the break -- so a player who leaves at
    # half keeps a side that by then belongs to the OPPONENT, and the site
    # files him on the enemy roster (and, since he is registered elsewhere,
    # marks the stint a RINGER for the team he played against). Measured on
    # 1789952635-NY1: 16 players across 16 matches since 2026-08-31.
    # KTPInfrastructure#496 corrected the match report and deliberately left
    # this field alone; the site reads this field and nothing else.
    canonical = canonical_teams(fetch_life_sides(db, mid))

    box = fetch_box_score(db, mid)
    # Kills and deaths come from the events, not from dodx's counter in
    # ktp_match_stats; the rest of that row (headshots, damage, score...) still
    # does, and `score` keeps its known savedScore undercount -- the site does
    # not render it, and correcting it is a separate decision.
    scoreboard = fetch_scoreboard_totals(db, mid)
    flags = fetch_objective_points(db, mid)

    players, skipped = [], 0
    for row in roster:
        sid64 = steamid64(row["steamId"])
        if sid64 is None:
            skipped += 1  # HLTV and other non-player unique ids land here
            continue
        stats = box.get(row["playerId"], {})
        truth = scoreboard.get(row["playerId"], {})
        team = row["team"] if row["team"] in (1, 2) else None
        # A no-op for everyone present at match end: the canonical labels
        # ARE the final half's sides, so only the rows the roster got
        # wrong move. `gameTeam` keeps its meaning (the side the player's
        # team held at match end) and starts being true for half-leavers.
        if canonical.get(row["playerId"]) in (1, 2):
            team = canonical[row["playerId"]]
        entry = {
            "steamId64": sid64,
            "kills": truth.get("kills", 0),
            "deaths": truth.get("deaths", 0),
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


def payload_digest(built: dict) -> str:
    return hashlib.sha256(json.dumps(
        built, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def load_sent() -> dict[str, str]:
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            state = json.load(fh)
    except (FileNotFoundError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def save_sent(sent: dict[str, str]) -> None:
    """Best effort. Losing this costs a redundant POST, never a missing match,
    so a read-only state directory must not fail the export."""
    try:
        os.makedirs(os.path.dirname(STATE_PATH) or ".", exist_ok=True)
        tmp = f"{STATE_PATH}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(sent, fh, indent=1, sort_keys=True)
        os.replace(tmp, STATE_PATH)
    except OSError as exc:
        print(f"warning: could not write {STATE_PATH}: {exc}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=48,
                    help="export matches ending within this window (default 48)")
    ap.add_argument("--match-id", help="export exactly one match, ignoring --hours")
    ap.add_argument("--dry-run", action="store_true",
                    help="build and print the payload; POST nothing")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--resend", action="store_true",
                    help="ignore what was already sent and POST the whole "
                         "window again (use if the site lost data)")
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

    # A match sits in the window for `hours` after it ends, so without this the
    # same settled payload is POSTed on every tick -- the endpoint answers
    # "unchanged" and nothing is learned. Re-send only what actually changed.
    skip_state = args.resend or args.dry_run or args.match_id
    sent = {} if skip_state else load_sent()
    digests = {b["gameMatchId"]: payload_digest(b) for b in built}
    fresh = [b for b in built
             if sent.get(b["gameMatchId"]) != digests[b["gameMatchId"]]]
    if not fresh:
        log(f"nothing new to export ({len(built)} already sent unchanged)",
            quiet=args.quiet)
        return 0
    if len(fresh) != len(built):
        log(f"{len(fresh)} new or changed, {len(built) - len(fresh)} unchanged",
            quiet=args.quiet)
    built = fresh

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
        if post(conf["STATS_INGEST_URL"], conf["STATS_INGEST_SECRET"],
                payload, args.quiet):
            # Per chunk, not per run: a later chunk failing must not discard
            # the record of an earlier one the site already accepted.
            for b in chunk:
                sent[b["gameMatchId"]] = digests[b["gameMatchId"]]
        else:
            ok = False
    if not skip_state:
        save_sent(sent)

    # Non-zero on failure so the systemd OnFailure wiring carries it to Discord.
    # An exporter that fails silently is the same defect as the stats it exists
    # to surface.
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
