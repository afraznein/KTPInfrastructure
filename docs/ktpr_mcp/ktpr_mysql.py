"""
MySQL data source for KTPR — runs queries over SSH against the `mysql` CLI,
so no local MySQL driver is required (the access pattern is
`ssh $KTPR_SSH_HOST` then `mysql hlstatsx_lan`).

Set `KTPR_SSH_HOST` (`user@host`) before use; it is deliberately not hardcoded
because this file lives in a public repo.

Status: SCAFFOLD. We do not have DB access yet and have not seen the real
schema, so `load_players_from_mysql` raises until the discovery step below
tells us the actual table/column names. Everything else is ready to run the
moment access lands.

Discovery (run once access works):
    python ktpr_mysql.py discover     # lists tables + columns of likely-relevant ones

Then wire the confirmed SQL into PLAYER_QUERY and implement load_players_from_mysql.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections import Counter

SSH_HOST = os.environ.get("KTPR_SSH_HOST", "")
DB = os.environ.get("KTPR_DB", "hlstatsx_lan")


def run_sql(sql: str, database: str = DB) -> str:
    """
    Execute SQL over SSH via the remote mysql CLI, return tab-separated stdout.
    Uses key auth from your ssh-agent. Batch mode (-B) => TSV, no box drawing.
    """
    if not SSH_HOST:
        raise RuntimeError(
            "KTPR_SSH_HOST is unset — set it to user@host for the stats box. "
            "Unset reads as a connection failure otherwise."
        )
    remote = f"mysql -B -N {database} -e {_shell_quote(sql)}"
    proc = subprocess.run(
        ["ssh",
         "-o", "BatchMode=yes",            # never prompt; rely on the loaded agent key
         "-o", "StrictHostKeyChecking=accept-new",
         "-o", "ConnectTimeout=20",
         SSH_HOST, remote],
        capture_output=True, text=True, timeout=60,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"remote mysql failed:\n{proc.stderr.strip()}")
    return proc.stdout


def _shell_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def discover() -> None:
    """Map the schema: list tables, then columns of any table that looks relevant."""
    print("=== TABLES ===")
    tables = [t for t in run_sql("SHOW TABLES;").splitlines() if t]
    for t in tables:
        print(" ", t)

    keywords = ("player", "frag", "kill", "death", "assist", "damage",
                "flag", "break", "action", "event", "rank", "stat")
    print("\n=== COLUMNS of likely-relevant tables ===")
    for t in tables:
        if any(k in t.lower() for k in keywords):
            print(f"\n[{t}]")
            cols = run_sql(f"SHOW COLUMNS FROM `{t}`;")
            for line in cols.splitlines():
                print("   ", line)


# Source of truth: hud_player_stats final rows (one per player-match-half).
# Aggregated per steam_id; per-half rates are computed in Python from the sums.
NIGHT_EXPR = "DATE(FROM_UNIXTIME(SUBSTRING_INDEX(match_id,'-',1)))"

# hud_spawns.class_id (primary weapon) -> role bucket, for within-class normalization.
ROLE_BY_CLASS = {
    1: "Rifle", 10: "Rifle", 11: "Rifle",     # garand, kar, k43
    5: "Sniper", 14: "Sniper",                 # springfield, scoped kar
    6: "Heavy", 13: "Heavy",                   # BAR, STG/mp44
    3: "SMG", 12: "SMG", 2: "SMG",             # thompson, mp40, carbine
}


def _load_roles() -> dict[str, str]:
    """steam_id -> primary role, from each player's most-spawned class."""
    sql = """
        SELECT steam_id, class_id FROM (
          SELECT steam_id, class_id,
                 ROW_NUMBER() OVER (PARTITION BY steam_id ORDER BY COUNT(*) DESC) AS rn
          FROM hud_spawns GROUP BY steam_id, class_id
        ) t WHERE rn = 1;
    """
    roles: dict[str, str] = {}
    for line in run_sql(sql).splitlines():
        if not line.strip():
            continue
        steam_id, class_id = line.split("\t")
        roles[steam_id] = ROLE_BY_CLASS.get(int(class_id), "?")
    return roles


# A "tournament match" = a completed match (has ktp_match_end) whose payload
# match_type is 0, played on Sat/Sun (the main-play days). Friday's for-fun games
# (match_type 1/2/3) and the 7 incomplete/warmup matches are excluded.
TOURNAMENT_MATCH_TYPES = ("0",)
TOURNAMENT_DAYS = ("2026-08-01", "2026-08-02")


# HLstatsX DoD objective-capture actions = "flags" (matches the hud caps count).
FLAG_ACTION_CODES = ("dod_capture_area", "dod_control_point")


def _tournament_match_id_subquery() -> str:
    types = ",".join(f"'{t}'" for t in TOURNAMENT_MATCH_TYPES)
    days = ",".join(f"'{d}'" for d in TOURNAMENT_DAYS)
    return (
        "SELECT match_id COLLATE utf8mb4_0900_ai_ci FROM hud_events "
        "WHERE event='ktp_match_end' "
        f"AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.match_type')) IN ({types}) "
        f"AND DATE(FROM_UNIXTIME(SUBSTRING_INDEX(match_id,'-',1))) IN ({days})"
    )


def _tournament_match_ids(night: str | None = None) -> list[str]:
    """Tournament match_ids as a Python list (inlined as literals to dodge cross-table collation)."""
    ids = [x for x in run_sql(_tournament_match_id_subquery()).splitlines() if x.strip()]
    if night:
        ids = [m for m in ids if _epoch_day(m) == night]
    return ids


def _epoch_day(match_id: str) -> str:
    # local mirror of the SQL night expr, for optional python-side night filtering
    import datetime
    epoch = int(match_id.split("-", 1)[0])
    return datetime.datetime.utcfromtimestamp(epoch).strftime("%Y-%m-%d")


def _idlist(ids: list[str]) -> str:
    return ",".join("'" + m.replace("'", "") + "'" for m in ids)


def _aggregate_sql(night: str | None, tournament_only: bool = True) -> str:
    where = "is_final=1"
    if tournament_only:
        where += (f" AND match_id COLLATE utf8mb4_0900_ai_ci IN "
                  f"({_tournament_match_id_subquery()})")
    if night:
        where += f" AND {NIGHT_EXPR}='{night}'"
    return f"""
        SELECT steam_id,
               MAX(name)                              AS raw_name,
               COUNT(DISTINCT match_id)               AS matches,
               COUNT(DISTINCT match_id, half)         AS halves,
               SUM(kills)      AS kills,
               SUM(deaths)     AS deaths,
               SUM(assists)    AS assists,
               SUM(damage)     AS damage,
               SUM(caps)       AS caps,
               SUM(cap_breaks) AS breaks
        FROM hud_player_stats
        WHERE {where}
        GROUP BY steam_id
        HAVING halves > 0;
    """


def _load_roster(roster_csv: str | None) -> dict[str, str]:
    """steam_id -> clean display name, if a roster.csv is present."""
    import csv
    if not roster_csv:
        cand = os.path.join(os.path.dirname(os.path.abspath(__file__)), "roster.csv")
        roster_csv = cand if os.path.exists(cand) else None
    mapping: dict[str, str] = {}
    if roster_csv and os.path.exists(roster_csv):
        with open(roster_csv, encoding="utf-8-sig", newline="") as f:
            for row in csv.reader(f):
                if len(row) >= 2 and row[0].strip():
                    mapping[row[0].strip()] = row[1].strip()
    return mapping


def _load_roster_teams(roster_csv: str | None) -> dict[str, str]:
    """steam_id -> normalized team_name column from roster.csv, if present.
    This is the authoritative team label when available; _infer_teams only
    falls back to the _tag_of heuristic for steam_ids missing from roster.csv
    (e.g. a player added after the roster was last regenerated)."""
    import csv
    if not roster_csv:
        cand = os.path.join(os.path.dirname(os.path.abspath(__file__)), "roster.csv")
        roster_csv = cand if os.path.exists(cand) else None
    mapping: dict[str, str] = {}
    if roster_csv and os.path.exists(roster_csv):
        with open(roster_csv, encoding="utf-8-sig", newline="") as f:
            for row in csv.reader(f):
                if len(row) >= 3 and row[0].strip() and row[2].strip():
                    mapping[row[0].strip()] = row[2].strip()
    return mapping


def _parse_rows(text: str):
    for line in text.splitlines():
        if line.strip():
            yield line.split("\t")


def _tag_of(name: str) -> str:
    """Best-effort clan/team tag from a display name: '[bb] foo' -> '[bb]',
    'x | y' -> 'x', 'iH.foo' -> 'iH'. Used only to LABEL an already-inferred
    team cluster (see _normalize_team_label for turning this into a clean
    display name)."""
    name = (name or "").strip()
    if name.startswith("["):
        end = name.find("]")
        if end != -1:
            return name[:end + 1]
    if " | " in name:
        return name.split(" | ", 1)[0].strip()
    parts = name.split()
    first = parts[0] if parts else name
    # Glued prefix with no separator, e.g. "iH.hildebrand?" -> "iH". Guarded
    # tight (2-5 alnum chars) so it doesn't misfire on names like
    # "Ke:>^1.de" (punctuation before the dot) or single-letter tags like
    # "b." (handled fine by the plain first-token fallback below).
    if "." in first:
        prefix = first.split(".", 1)[0]
        if 2 <= len(prefix) <= 5 and prefix.isalnum():
            return prefix
    return first


# Raw _tag_of() output -> clean display name. Strips the stylized/leetspeak
# clan-tag glyphs (e.g. "ßℓυ†н" is literal Unicode chosen to visually read as
# "Bluth") down to something readable and CSV/ASCII-safe. Anything not listed
# here falls back to a generic bracket/punctuation strip in _normalize_team_label.
TEAM_LABEL_MAP = {
    "[bb]": "bb",
    "[NATO]": "NATO",
    "[$]": "$",
    "ßℓυ†н": "Bluth",
    "dicE[:": "dice",
    "****JTM": "JTM",
    "uR[TM]*": "uR",
    "b.": "b",
    "NoSo": "NoSo",
    "iH": "iH",
}


def _normalize_team_label(raw_tag: str) -> str:
    """Clean a raw _tag_of() tag into a short, readable, ASCII-safe team name."""
    if raw_tag in TEAM_LABEL_MAP:
        return TEAM_LABEL_MAP[raw_tag]
    cleaned = raw_tag.strip().strip("[]*. ")
    return cleaned or raw_tag


def _strip_name_tag(name: str) -> str:
    """Strip the leading clan-tag portion off a display name, leaving the bare
    player nickname (e.g. 'ßℓυ†н | nicholson' -> 'nicholson', '[bb] Polak' ->
    'Polak', 'iH.hildebrand?' -> 'hildebrand?')."""
    name = (name or "").strip()
    tag = _tag_of(name)
    rest = name
    if name.startswith("["):
        end = name.find("]")
        if end != -1:
            rest = name[end + 1:]
    elif " | " in name:
        rest = name.split(" | ", 1)[1]
    elif tag and name.startswith(tag + "."):
        rest = name[len(tag) + 1:]
    elif tag and name.startswith(tag):
        rest = name[len(tag):]
    # drop any leftover separator punctuation ("!", ":]", ".", "-", spaces)
    # between the stripped tag and the actual nickname
    rest = re.sub(r"^[\s!.:\]\|\-]+", "", rest)
    return rest.strip()


def _infer_teams(tournament_only: bool = True, min_weight: int = 6) -> dict[str, str]:
    """
    steam_id (STEAM_0: form) -> fixed tournament team label.

    There's no explicit team-roster table in this schema: `ktp_match_players.team`
    (1/2) is only a per-match side slot. But it's stable across both halves of a
    match (DoD swaps Allies/Axis at halftime, not the roster-to-slot mapping), so
    clustering players who repeatedly shared a (match_id, team) slot recovers the
    real fixed rosters. A minimum shared-match-count threshold on each edge avoids
    merging two different teams through a one-off substitute who bridges both.
    """
    ids = _tournament_match_ids() if tournament_only else None
    where = f"match_id IN ({_idlist(ids)})" if ids is not None else "1=1"
    rows = list(_parse_rows(run_sql(
        f"SELECT match_id, team, steam_id FROM ktp_match_players WHERE {where} "
        f"ORDER BY match_id, team;"
    )))

    groups: dict[tuple[str, str], list[str]] = {}
    for match_id, team, steam_id in rows:
        groups.setdefault((match_id, team), []).append(steam_id)

    weight: dict[tuple[str, str], int] = {}
    for members in groups.values():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = sorted((members[i], members[j]))
                weight[(a, b)] = weight.get((a, b), 0) + 1

    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for (a, b), w in weight.items():
        if w >= min_weight:
            union(a, b)

    clusters: dict[str, list[str]] = {}
    for uid in parent:
        clusters.setdefault(find(uid), []).append(uid)

    roster = _load_roster(None)
    roster_teams = _load_roster_teams(None)
    labels: dict[str, str] = {}
    for root, members in clusters.items():
        if len(members) < 3:      # too small to be a real fixed roster
            continue
        # Prefer roster.csv's own team_name column (authoritative, hand-verified);
        # fall back to the name-parsing heuristic only for steam_ids not yet in it.
        known = [roster_teams["STEAM_0:" + uid] for uid in members if "STEAM_0:" + uid in roster_teams]
        if known:
            label = Counter(known).most_common(1)[0][0]
        else:
            tags = [t for t in (_tag_of(roster.get("STEAM_0:" + uid, "")) for uid in members) if t]
            raw_label = Counter(tags).most_common(1)[0][0] if tags else f"Team-{root}"
            label = _normalize_team_label(raw_label)
        for uid in members:
            labels["STEAM_0:" + uid] = label
    return labels


def _match_results(tournament_only: bool = True) -> dict[str, dict]:
    """
    match_id -> {'team_scores': {team_label: total}, 'winner': team_label}.

    Deliberately does NOT read `ktp_match_end`'s axis_score/allies_score: that
    event's payload has those two fields SWAPPED relative to the true score,
    confirmed two ways —
      1. Ground-truthed: team '[$]' actually went 3-9 (2-4 Sat, 1-5 Sun); reading
         ktp_match_end at face value ("higher wins") produced an exact inversion
         (9-3), because [$]'s real (low) score shows up under the field that
         looks like the opponent's.
      2. Mechanistically: cross-checked every one of the 55 tournament matches'
         `ktp_match_end` payload against the LAST `team_score` event of that same
         match (which is internally consistent tick-to-tick and matches the
         half_end event for half 1) — axis_score/allies_score are swapped in
         100% of the 55 matches. Not a coincidence; a bug in that specific event.

    So: use the last `team_score` event of the match's final half as the real
    score (normal "higher wins"), mapped to a physical team via whichever side
    it occupied in that half.
    """
    ids = _tournament_match_ids() if tournament_only else \
        [x for x in run_sql("SELECT DISTINCT match_id COLLATE utf8mb4_0900_ai_ci FROM hud_events")
         .splitlines() if x.strip()]
    idl = _idlist(ids)
    teams = _infer_teams(tournament_only)

    side_of: dict[tuple[str, int], dict[str, str]] = {}
    for match_id, half, steam_id, side in _parse_rows(run_sql(
        f"SELECT match_id, half, steam_id, team FROM hud_player_stats "
        f"WHERE is_final=1 AND match_id IN ({idl});"
    )):
        label = teams.get(steam_id)
        if label:
            side_of.setdefault((match_id, int(half)), {})[label] = side

    # last team_score row per match: ORDER BY half, tick so a low tick at the
    # start of half 2 doesn't get mistaken for "later than" a high tick in half 1.
    last_score: dict[str, tuple[float, float]] = {}
    for match_id, half, tick, payload in _parse_rows(run_sql(
        f"SELECT match_id, half, tick, payload FROM hud_events "
        f"WHERE event='team_score' AND match_id IN ({idl}) "
        f"ORDER BY match_id, half, tick;"
    )):
        d = json.loads(payload)
        last_score[match_id] = (float(d["axis_score"]), float(d["allies_score"]))

    last_half: dict[str, int] = {}
    for match_id, half in side_of:
        last_half[match_id] = max(half, last_half.get(match_id, 0))

    results: dict[str, dict] = {}
    for match_id in ids:
        if match_id not in last_score or match_id not in last_half:
            continue
        f_axis, f_allies = last_score[match_id]
        side_map = side_of.get((match_id, last_half[match_id]), {})
        if len(side_map) != 2:
            continue   # a team we couldn't cluster (e.g. all one-off casual subs)
        score_of_side = {"axis": f_axis, "allies": f_allies}
        team_scores = {label: score_of_side[side] for label, side in side_map.items()}
        winner = max(team_scores, key=team_scores.get)
        results[match_id] = {"team_scores": team_scores, "winner": winner}
    return results


def _match_maps(tournament_only: bool = True) -> dict[str, str]:
    """match_id -> map_name (same map for both halves of a match)."""
    ids = _tournament_match_ids() if tournament_only else None
    where = f"match_id IN ({_idlist(ids)})" if ids is not None else "1=1"
    return {match_id: map_name for match_id, map_name in _parse_rows(run_sql(
        f"SELECT DISTINCT match_id, map_name FROM ktp_matches WHERE {where};"
    ))}


def load_match_player_stats(tournament_only: bool = True):
    """
    Return list[ktpr_engine.Player], one row PER (player, match), with `.team`,
    `.match_id`, `.won`, `.opponent_team`, `.margin_ratio`, `.map_name` set —
    the input to ktpr_engine.compute_match_splits (win/loss, margin-of-victory,
    and opponent-strength cuts). Same two telemetry systems as
    load_players_from_mysql, grouped additionally by match_id.
    """
    import ktpr_engine as E
    roster = _load_roster(None)
    roles = _load_roles()
    teams = _infer_teams(tournament_only)
    results = _match_results(tournament_only)
    maps = _match_maps(tournament_only)

    ids = _tournament_match_ids() if tournament_only else \
        [x for x in run_sql("SELECT DISTINCT match_id COLLATE utf8mb4_0900_ai_ci FROM hud_events")
         .splitlines() if x.strip()]
    idl = _idlist(ids)
    flagcodes = ",".join(f"'{c}'" for c in FLAG_ACTION_CODES)

    pid2uid: dict[str, str] = {}
    for pid, uid in _parse_rows(run_sql("SELECT playerId, uniqueId FROM hlstats_PlayerUniqueIds")):
        pid2uid.setdefault(pid, uid)

    spine_sql = f"""
        SELECT pid, match_id, SUM(is_kill) AS kills, SUM(is_death) AS deaths,
               COUNT(DISTINCT half) AS halves
        FROM (
          SELECT killerId AS pid, match_id, half, 1 AS is_kill, 0 AS is_death
            FROM hlstats_Events_Frags WHERE match_id IN ({idl})
          UNION ALL
          SELECT victimId, match_id, half, 0, 1
            FROM hlstats_Events_Frags WHERE match_id IN ({idl})
          UNION ALL
          SELECT victimId, match_id, half, 0, 1
            FROM hlstats_Events_Teamkills WHERE match_id IN ({idl})
        ) e GROUP BY pid, match_id;
    """
    spine = list(_parse_rows(run_sql(spine_sql)))

    flags_sql = f"""
        SELECT pa.playerId, pa.match_id, COUNT(*) AS flags
        FROM hlstats_Events_PlayerActions pa
        JOIN hlstats_Actions a ON a.id = pa.actionId
        WHERE pa.match_id IN ({idl}) AND a.code IN ({flagcodes})
        GROUP BY pa.playerId, pa.match_id;
    """
    flags: dict[tuple[str, str], float] = {}
    for pid, match_id, cnt in _parse_rows(run_sql(flags_sql)):
        flags[(pid, match_id)] = float(cnt)

    hud_sql = f"""
        SELECT steam_id, match_id, SUM(assists) AS a, SUM(damage) AS d, SUM(cap_breaks) AS b,
               COUNT(DISTINCT half) AS hh
        FROM hud_player_stats
        WHERE is_final=1 AND match_id IN ({idl})
        GROUP BY steam_id, match_id;
    """
    hud: dict[tuple[str, str], tuple[float, float, float, int]] = {}
    for steam_id, match_id, a, d, b, hh in _parse_rows(run_sql(hud_sql)):
        hud[(steam_id, match_id)] = (float(a), float(d), float(b), int(hh))

    out = []
    for pid, match_id, kills, deaths, halves in spine:
        kills, deaths, halves = float(kills), float(deaths), int(halves)
        if halves == 0:
            continue
        uid = pid2uid.get(pid)
        if not uid or ":" not in uid:
            continue
        steam_id = "STEAM_0:" + uid
        assists, damage, breaks, hud_halves = hud.get((steam_id, match_id), (0.0, 0.0, 0.0, 0))
        hud_h = hud_halves or halves
        name = roster.get(steam_id) or roster.get(uid) or f"[{steam_id}]"
        team = teams.get(steam_id, "?")
        mr = results.get(match_id)
        won = opponent = None
        margin_ratio = None
        if mr and team in mr["team_scores"]:
            opponent = next((t for t in mr["team_scores"] if t != team), None)
            if opponent is not None:
                my_score, opp_score = mr["team_scores"][team], mr["team_scores"][opponent]
                total = my_score + opp_score
                margin_ratio = (my_score - opp_score) / total if total else 0.0
                won = my_score > opp_score
        out.append(E.Player(
            name=name,
            matches=1.0,
            kd_ratio=(kills / deaths) if deaths else kills,
            kills_half=kills / halves,
            deaths_half=deaths / halves,
            flags_half=flags.get((pid, match_id), 0.0) / halves,
            assists_half=assists / hud_h,
            damage_half=damage / hud_h,
            breaks_half=breaks / hud_h,
            role=roles.get(steam_id, "?"),
            team=team,
            match_id=match_id,
            won=won,
            opponent_team=opponent,
            margin_ratio=margin_ratio,
            map_name=maps.get(match_id),
        ))
    return out


def load_raw_match_stats(tournament_only: bool = True):
    """
    Return list[ktpr_engine.RawMatchStats], one row PER (player, match), with
    RAW (undivided) counts — not per-half rates like the other loaders. This is
    the input to leave-one-out validation (ktpr_engine.compute_prediction_accuracy):
    a player's season total minus one match's raw contribution can be computed
    by subtraction, which isn't possible once stats are already divided into a
    per-half rate. Same two telemetry systems, same grouping, as
    load_match_player_stats — just stops one step earlier.
    """
    import ktpr_engine as E
    roster = _load_roster(None)
    roles = _load_roles()
    teams = _infer_teams(tournament_only)

    ids = _tournament_match_ids() if tournament_only else \
        [x for x in run_sql("SELECT DISTINCT match_id COLLATE utf8mb4_0900_ai_ci FROM hud_events")
         .splitlines() if x.strip()]
    idl = _idlist(ids)
    flagcodes = ",".join(f"'{c}'" for c in FLAG_ACTION_CODES)

    pid2uid: dict[str, str] = {}
    for pid, uid in _parse_rows(run_sql("SELECT playerId, uniqueId FROM hlstats_PlayerUniqueIds")):
        pid2uid.setdefault(pid, uid)

    spine_sql = f"""
        SELECT pid, match_id, SUM(is_kill) AS kills, SUM(is_death) AS deaths,
               COUNT(DISTINCT half) AS halves
        FROM (
          SELECT killerId AS pid, match_id, half, 1 AS is_kill, 0 AS is_death
            FROM hlstats_Events_Frags WHERE match_id IN ({idl})
          UNION ALL
          SELECT victimId, match_id, half, 0, 1
            FROM hlstats_Events_Frags WHERE match_id IN ({idl})
          UNION ALL
          SELECT victimId, match_id, half, 0, 1
            FROM hlstats_Events_Teamkills WHERE match_id IN ({idl})
        ) e GROUP BY pid, match_id;
    """
    spine = list(_parse_rows(run_sql(spine_sql)))

    flags_sql = f"""
        SELECT pa.playerId, pa.match_id, COUNT(*) AS flags
        FROM hlstats_Events_PlayerActions pa
        JOIN hlstats_Actions a ON a.id = pa.actionId
        WHERE pa.match_id IN ({idl}) AND a.code IN ({flagcodes})
        GROUP BY pa.playerId, pa.match_id;
    """
    flags: dict[tuple[str, str], float] = {}
    for pid, match_id, cnt in _parse_rows(run_sql(flags_sql)):
        flags[(pid, match_id)] = float(cnt)

    hud_sql = f"""
        SELECT steam_id, match_id, SUM(assists) AS a, SUM(damage) AS d, SUM(cap_breaks) AS b,
               COUNT(DISTINCT half) AS hh
        FROM hud_player_stats
        WHERE is_final=1 AND match_id IN ({idl})
        GROUP BY steam_id, match_id;
    """
    hud: dict[tuple[str, str], tuple[float, float, float, int]] = {}
    for steam_id, match_id, a, d, b, hh in _parse_rows(run_sql(hud_sql)):
        hud[(steam_id, match_id)] = (float(a), float(d), float(b), int(hh))

    out = []
    for pid, match_id, kills, deaths, halves in spine:
        kills, deaths, halves = float(kills), float(deaths), int(halves)
        if halves == 0:
            continue
        uid = pid2uid.get(pid)
        if not uid or ":" not in uid:
            continue
        steam_id = "STEAM_0:" + uid
        assists, damage, breaks, hud_halves = hud.get((steam_id, match_id), (0.0, 0.0, 0.0, 0))
        name = roster.get(steam_id) or roster.get(uid) or f"[{steam_id}]"
        out.append(E.RawMatchStats(
            steam_id=steam_id,
            name=name,
            match_id=match_id,
            role=roles.get(steam_id, "?"),
            team=teams.get(steam_id, "?"),
            kills=kills, deaths=deaths,
            assists=assists, damage=damage,
            flags=flags.get((pid, match_id), 0.0), breaks=breaks,
            halves=halves, hud_halves=hud_halves,
        ))
    return out


def load_half_player_stats(tournament_only: bool = True):
    """
    Return list[ktpr_engine.Player], one row PER (player, match, half), with
    `.team`/`.match_id`/`.side` (axis|allies) set — the input to
    ktpr_engine.compute_side_splits. Each row already IS one half's worth of
    data, so unlike the other loaders no per-half division is needed.
    """
    import ktpr_engine as E
    roster = _load_roster(None)
    roles = _load_roles()
    teams = _infer_teams(tournament_only)

    ids = _tournament_match_ids() if tournament_only else \
        [x for x in run_sql("SELECT DISTINCT match_id COLLATE utf8mb4_0900_ai_ci FROM hud_events")
         .splitlines() if x.strip()]
    idl = _idlist(ids)

    pid2uid: dict[str, str] = {}
    for pid, uid in _parse_rows(run_sql("SELECT playerId, uniqueId FROM hlstats_PlayerUniqueIds")):
        pid2uid.setdefault(pid, uid)

    spine_sql = f"""
        SELECT pid, match_id, half, SUM(is_kill) AS kills, SUM(is_death) AS deaths
        FROM (
          SELECT killerId AS pid, match_id, half, 1 AS is_kill, 0 AS is_death
            FROM hlstats_Events_Frags WHERE match_id IN ({idl})
          UNION ALL
          SELECT victimId, match_id, half, 0, 1
            FROM hlstats_Events_Frags WHERE match_id IN ({idl})
          UNION ALL
          SELECT victimId, match_id, half, 0, 1
            FROM hlstats_Events_Teamkills WHERE match_id IN ({idl})
        ) e GROUP BY pid, match_id, half;
    """
    spine = list(_parse_rows(run_sql(spine_sql)))

    # Flags per half: HLstatsX's hlstats_Events_PlayerActions has no `half`
    # column, so (only here, at per-half granularity) fall back to HUD's own
    # capture log, which is half-aware and steam_id-keyed already.
    flags_sql = f"""
        SELECT steam_id, match_id, half, COUNT(*) AS flags
        FROM hud_flag_events
        WHERE event='captured' AND match_id IN ({idl})
        GROUP BY steam_id, match_id, half;
    """
    flags: dict[tuple[str, str, int], float] = {}
    for steam_id, match_id, half, cnt in _parse_rows(run_sql(flags_sql)):
        flags[(steam_id, match_id, int(half))] = float(cnt)

    hud_sql = f"""
        SELECT steam_id, match_id, half, SUM(assists) AS a, SUM(damage) AS d, SUM(cap_breaks) AS b, team
        FROM hud_player_stats
        WHERE is_final=1 AND match_id IN ({idl})
        GROUP BY steam_id, match_id, half, team;
    """
    hud: dict[tuple[str, str, int], tuple[float, float, float, str]] = {}
    for steam_id, match_id, half, a, d, b, side in _parse_rows(run_sql(hud_sql)):
        hud[(steam_id, match_id, int(half))] = (float(a), float(d), float(b), side)

    out = []
    for pid, match_id, half, kills, deaths in spine:
        kills, deaths, half = float(kills), float(deaths), int(half)
        uid = pid2uid.get(pid)
        if not uid or ":" not in uid:
            continue
        steam_id = "STEAM_0:" + uid
        key = (steam_id, match_id, half)
        assists, damage, breaks, side = hud.get(key, (0.0, 0.0, 0.0, None))
        if side is None:
            continue    # no HUD row for this player/match/half -> can't tell which side
        name = roster.get(steam_id) or roster.get(uid) or f"[{steam_id}]"
        out.append(E.Player(
            name=name,
            matches=1.0,
            kd_ratio=(kills / deaths) if deaths else kills,
            kills_half=kills,
            deaths_half=deaths,
            flags_half=flags.get(key, 0.0),
            assists_half=assists,
            damage_half=damage,
            breaks_half=breaks,
            role=roles.get(steam_id, "?"),
            team=teams.get(steam_id, "?"),
            match_id=match_id,
            side=side,
        ))
    return out


def load_players_from_mysql(night: str | None = None, roster_csv: str | None = None,
                            tournament_only: bool = True):
    """
    Return list[ktpr_engine.Player] for the tournament, using the TWO telemetry
    systems as designed:
      * HLstatsX (authoritative) -> kills, deaths, flags, matches, halves
      * HUD (new stats)          -> assists, damage, breaks
    per-half rates all use the HLstatsX half count (the primary participation basis).

    tournament_only=True (default) restricts to Sat/Sun match_type=0 matches.
    """
    import ktpr_engine as E
    roster = _load_roster(roster_csv)
    roles = _load_roles()
    teams = _infer_teams(tournament_only)

    ids = _tournament_match_ids(night) if tournament_only else \
        [x for x in run_sql("SELECT DISTINCT match_id COLLATE utf8mb4_0900_ai_ci FROM hud_events").splitlines() if x.strip()]
    idl = _idlist(ids)
    flagcodes = ",".join(f"'{c}'" for c in FLAG_ACTION_CODES)

    # playerId -> uniqueId (steam suffix). Keep first uniqueId per player.
    pid2uid: dict[str, str] = {}
    for pid, uid in _parse_rows(run_sql("SELECT playerId, uniqueId FROM hlstats_PlayerUniqueIds")):
        pid2uid.setdefault(pid, uid)

    # HLstatsX spine: kills, deaths, matches, halves per playerId
    spine_sql = f"""
        SELECT pid, SUM(is_kill) AS kills, SUM(is_death) AS deaths,
               COUNT(DISTINCT match_id) AS matches,
               COUNT(DISTINCT match_id, half) AS halves
        FROM (
          SELECT killerId AS pid, match_id, half, 1 AS is_kill, 0 AS is_death
            FROM hlstats_Events_Frags WHERE match_id IN ({idl})
          UNION ALL
          SELECT victimId, match_id, half, 0, 1
            FROM hlstats_Events_Frags WHERE match_id IN ({idl})
          UNION ALL
          SELECT victimId, match_id, half, 0, 1
            FROM hlstats_Events_Teamkills WHERE match_id IN ({idl})
        ) e GROUP BY pid;
    """
    spine = {r[0]: r for r in _parse_rows(run_sql(spine_sql))}

    # HLstatsX flags (objective captures) per playerId
    flags_sql = f"""
        SELECT pa.playerId, COUNT(*) AS flags
        FROM hlstats_Events_PlayerActions pa
        JOIN hlstats_Actions a ON a.id = pa.actionId
        WHERE pa.match_id IN ({idl}) AND a.code IN ({flagcodes})
        GROUP BY pa.playerId;
    """
    flags = {r[0]: float(r[1]) for r in _parse_rows(run_sql(flags_sql))}

    # HUD new stats per steam_id. Keep HUD's OWN half count: HUD sometimes drops
    # half-snapshots, so a HUD total must be divided by the halves HUD actually
    # captured (not the HLstatsX halves) or the per-half rate is understated.
    hud_sql = f"""
        SELECT steam_id, SUM(assists) AS a, SUM(damage) AS d, SUM(cap_breaks) AS b,
               COUNT(DISTINCT match_id, half) AS hh
        FROM hud_player_stats
        WHERE is_final=1 AND match_id IN ({idl})
        GROUP BY steam_id;
    """
    hud = {r[0]: (float(r[1]), float(r[2]), float(r[3]), int(r[4]))
           for r in _parse_rows(run_sql(hud_sql))}

    out = []
    for pid, row in spine.items():
        _, kills, deaths, matches, halves = row
        kills, deaths = float(kills), float(deaths)
        matches, halves = int(matches), int(halves)
        if halves == 0:
            continue
        uid = pid2uid.get(pid)
        if not uid or ":" not in uid:      # skip HLTV / bots / unmapped
            continue
        steam_id = "STEAM_0:" + uid
        assists, damage, breaks, hud_halves = hud.get(steam_id, (0.0, 0.0, 0.0, 0))
        hud_h = hud_halves or halves            # fall back to HLstatsX halves if HUD absent
        name = roster.get(steam_id) or roster.get(uid) or f"[{steam_id}]"
        out.append(E.Player(
            name=name,
            matches=float(matches),
            kd_ratio=(kills / deaths) if deaths else kills,
            kills_half=kills / halves,           # HLstatsX stats / HLstatsX halves
            deaths_half=deaths / halves,
            flags_half=flags.get(pid, 0.0) / halves,
            assists_half=assists / hud_h,        # HUD stats / HUD halves
            damage_half=damage / hud_h,
            breaks_half=breaks / hud_h,
            role=roles.get(steam_id, "?"),
            team=teams.get(steam_id, "?"),
        ))
    return out


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "discover":
        discover()
    else:
        print(__doc__)