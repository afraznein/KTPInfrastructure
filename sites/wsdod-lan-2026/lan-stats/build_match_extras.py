#!/usr/bin/env python3
"""Per-match score, flag count and bracket round, for the match-page baked shell.

None of the three is stored anywhere as a single column -- verified against the
live DB (hlstatsx_lan on the data server) and against bracket.json/veto.json,
which turned out to disagree with each other and with the site's own static
bracket markup in three separate places. Findings kept here so the next person
doesn't re-derive them:

SCORE (`points`). The team score a DoD match is actually decided on, from
hud_events rows with event='team_score' and an {allies_score, axis_score}
payload. Three things make it not a MAX() query:

  * `tick` RESETS mid-half and the rows either side keep the same `half`, so
    MAX(id) per half lands on a post-reset 0-0 row. Segment where tick jumps
    backwards and take the last row of the FIRST segment -- the same walk
    build_awards.py's _segments and kill_streaks.py both need.
  * HALF 2's SCORE IS CUMULATIVE. It opens at half 1's final with the sides
    swapped and keeps counting, so h2's last row is already the match total.
    The per-half figure is that minus half 1, not the raw reading.
  * Teams swap sides at halftime, so allies/axis is not one club across the
    match. Side comes from hud_player_stats.team, club from
    ktp_match_players.team (1/2, constant all match). Half 1's vote covers the
    whole roster and is unanimous everywhere; half 2's thins out to a single
    player in places and to nobody at all in one match, so half 2 is taken as
    the swap of half 1 and its own vote used only as a gate.

Gated on the plugin's own close events, which carry the same two numbers:
half_end for half 1 and ktp_match_end for the match, both reported in HALF-1
side terms. Every half agrees, and the ktp_match_end leg is a real check on the
side swap rather than a restatement of it -- it is expressed in the other half's
sides. The build fails rather than emit a figure they don't confirm, which is
also what would happen to a match abandoned partway through half 2: it has
team_score rows and no ktp_match_end, and nothing here should quietly report
a half in progress as a result.

FLAGS (`score`). Flags captured, NOT the match score, kept because the panel
that shows it says so. It's the count of actionId IN (337, 338)
(dod_control_point, dod_capture_area -- the same pair recover_captures.py used)
in hlstats_Events_PlayerActions, joined to ktp_match_players.team. half comes
from bucketing eventTime into ktp_matches' per-half [start_time, end_time]
window, since PlayerActions itself carries no half column.

hlstats_*/hud_* tables collate utf8mb4_unicode_ci; ktp_* tables collate
utf8mb4_0900_ai_ci. Joining match_id across the two 1267s ("Illegal mix of
collations") without an explicit COLLATE. The score queries dodge it by
joining in Python instead -- steam_id formats differ across those tables too
(the HUD stores STEAM_0:Y:Z, ktp_* store Y:Z), and build_stats.py's sid()
documents the canonicalisation both need.

captures-placed.json (5461 rows for the curated 56) is STALE against the live
DB (5515) -- built_stats.py's docstring dates the repair that explains the
gap. Trust the DB, not the committed recovery snapshot.

ROUND. bracket.json's own `map` field is missing for 4 of 15 series (literal
string "NULL": PI1, PI2, LS2, P910) and its score_a/score_b is not uniformly
"games won" -- P910 reads 0-2 for what is a single BO1 game (the static
bracket markup confirms one match, one "2-0"-looking line; that "2" is the
round's own flag score, not a series tally). The static bracket markup in
design/prototype.html is the production truth used to fill both gaps here.

Attribution method, verified match by match below: group the 56 curated
matches by team pair, keep the Sunday-dated ones (ET, not UTC -- see
freeze_match_slugs.py's DAY_LABEL for why that matters), and match each
series' known map list against those candidates' actual maps (from the
DB / captures-placed, order doesn't matter since we match by map identity
per game, not position). 25 of 26 Sunday matches resolve this way. The lone
holdout, 1785715156-KTP2 (Arrested Development v dicE on railroad2_s9a,
2026-08-02 19:59 ET), shares a team pair with P34's real decider
(1785711668-KTP2, armory_b6, matching P34's recorded map and the static
card) but isn't itself any of the 15 recorded slots -- real tournament play
per match-teams.json, with no bracket round to attribute it to. It renders
as "Sunday playoffs" rather than a guessed slot.

Run from WSL/Linux (needs tzdata for zoneinfo) with SSH access to the data
server (see .claude/skills/fleet-ssh) -- see connect_to_data() below.

Output: match-extras.json, committed. {match_id: {"round": str,
"mkey": str | null, "map": "dod_<map>", "score": {"h1": [a,b], "h2": [a,b],
"final": [a,b]} | null, "points": {"h1": [a,b] | null, "h2": [a,b] | null,
"total": [a,b] | null} | null}}
Both a and b index match-teams.json's pair for that match.
mkey is the veto-data/bracket.json key when the match resolved to a specific
bracket slot (join it there for that match's veto sequence); null for group
stage and the "Sunday playoffs" fallback, both of which have no veto record.
`score` is null only for 1785715972-KTP1 (the Final's second game -- logging
died before the close event, and even the partial captures that exist here
are from a match that never finished, so a number would overstate what's
known). Everything else has real data: 55 of 56 curated matches.
That match keeps its `points` half 1, which is real and confirmed by its own
half_end event, with half 2 and total null: half 2 never started, and a total
would be a half presented as a match.
"""
from __future__ import annotations

import json
import os
import sys
import datetime
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))

ROUND_LABEL = {
    "PI": "Play-in", "QF": "Quarter-final", "SF": "Semi-final", "F": "Final",
    "LS": "Lower semi-final", "LF": "Lower final", "P34": "3rd place decider",
    "P56": "5th place decider", "P78": "7th place decider",
    "P910": "9th place decider",
}
# LS2 and P910 are missing/wrong in bracket.json's own "map" field or score
# fields (see module docstring); these are read off the static bracket
# markup in design/prototype.html instead, which is the production record.
LS2_MAPS = ["railroad2_s9a", "saints2_b3e"]
NO_CLOSE_EVENT_MATCH = "1785715972-KTP1"   # icyHOT v NATO, F game 2 -- logging died


def load(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return json.load(fh)


def et_date(match_id: str, tz) -> datetime.date:
    epoch = int(match_id.split("-", 1)[0])
    return datetime.datetime.fromtimestamp(epoch, tz).date()


def resolve_rounds(match_teams: dict, bracket: list, captures_placed: list, tz) -> tuple[dict, dict]:
    """match_id -> (round label, mkey|None). Saturday is uniformly "Group
    stage" (no mkey -- there's no veto-data entry for group play); Sunday is
    resolved to a specific bracket slot wherever the team-pair + map evidence
    is unambiguous, else the honest fallback "Sunday playoffs" (also no mkey:
    a label with no slot behind it has no veto sequence to link either)."""
    sunday = datetime.date(2026, 8, 2)
    mid_map = {}
    for r in captures_placed:
        mid_map.setdefault(r["match_id"], r["map"][4:] if r["map"].startswith("dod_") else r["map"])

    by_pair = defaultdict(list)
    for mid, teams in match_teams.items():
        by_pair[frozenset(teams)].append(mid)

    rounds: dict[str, str] = {}
    mkeys: dict[str, str | None] = {}
    for mid in match_teams:
        rounds[mid] = "Group stage" if et_date(mid, tz) != sunday else "Sunday playoffs"
        mkeys[mid] = None

    for s in bracket:
        pair = frozenset([s["team_a"], s["team_b"]])
        cands = sorted((m for m in by_pair.get(pair, []) if et_date(m, tz) == sunday),
                       key=lambda m: int(m.split("-", 1)[0]))
        if s["mkey"] == "LS2":
            series_maps = LS2_MAPS
        elif s["map"] == "NULL":
            series_maps = []
        else:
            series_maps = [x.strip() for x in s["map"].split("/")]

        label = ROUND_LABEL[s["stage"]]
        if series_maps:
            pool = list(cands)
            for wantmap in series_maps:
                hit = next((m for m in pool if mid_map.get(m) == wantmap), None)
                if hit:
                    rounds[hit] = label
                    mkeys[hit] = s["mkey"]
                    pool.remove(hit)
        elif len(cands) == 1:
            rounds[cands[0]] = label
            mkeys[cands[0]] = s["mkey"]
        # else: genuinely ambiguous (no map evidence, >1 candidate) -- leave
        # at the "Sunday playoffs" fallback rather than guess.
    return rounds, mkeys


def mysql(ssh, sql: str, what: str) -> list:
    """Run one read-only query on the data server, as rows of raw strings.

    The statement goes over SFTP rather than onto the command line: each of
    these carries the whole curated match-id list and a JSON path.
    """
    sftp = ssh.open_sftp()
    with sftp.open("/tmp/match_extras.sql", "w") as fh:
        fh.write(sql)
    sftp.close()
    _stdin, stdout, stderr = ssh.exec_command(
        "mysql hlstatsx_lan -N < /tmp/match_extras.sql", timeout=600)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace").strip()
    if err:
        raise SystemExit("%s query failed: %s" % (what, err))
    return [line.split("\t") for line in out.splitlines() if line.strip()]


def sid(v: str) -> str:
    """Canonical player key -- build_stats.py's sid(), and see its docstring:
    the HUD stores STEAM_0:Y:Z where ktp_match_players stores Y:Z, and left
    unnormalised the two never join."""
    v = (v or "").strip()
    if v.upper().startswith("STEAM_"):
        v = v.split(":", 1)[1] if ":" in v else v
    return v


def tick_segments(rows: list) -> list:
    """Split a HUD stream where `tick` jumps backwards.

    `tick` is the server's map uptime, not time within the half, and it resets
    on a map reload while the rows either side keep the same match_id and half.
    Rows arrive in insertion order (`id`), so the seam is the one place tick
    goes down. build_awards.py's _segments is the same walk against hud_prone.
    """
    out = [[]]
    for r in rows:
        if out[-1] and r[1] < out[-1][-1][1] - 1:
            out.append([])
        out[-1].append(r)
    return [s for s in out if s]


def side_map(match_teams: dict, ssh) -> dict:
    """(match_id, half) -> club (1/2) playing Allies that half.

    Half 1 is voted from the players themselves; half 2 is its swap. Not
    symmetric because the evidence isn't: hud_player_stats covers the full
    roster in half 1 of every match and is unanimous, while its half-2 coverage
    thins out to a single player in places and vanishes entirely in one match.
    The half-2 vote is still read, as a gate on the swap.
    """
    ids = ",".join("'%s'" % m for m in match_teams)
    club = defaultdict(dict)
    for mid, team, steam in mysql(ssh, """SELECT match_id, team, steam_id
        FROM ktp_match_players WHERE match_id IN (%s);""" % ids, "club"):
        club[mid][sid(steam)] = int(team)

    votes = defaultdict(Counter)
    for mid, half, side, steam in mysql(ssh, """SELECT DISTINCT
        match_id, half, team, steam_id FROM hud_player_stats
        WHERE match_id IN (%s) AND team IN ('allies','axis');""" % ids, "side"):
        c = club[mid].get(sid(steam))
        if c:
            votes[(mid, int(half))][c if side == "allies" else 3 - c] += 1

    out = {}
    for mid in match_teams:
        v1 = votes[(mid, 1)]
        if len(v1) != 1:
            raise SystemExit("%s half 1: allies is club %s -- the side vote "
                             "must be unanimous" % (mid, dict(v1) or "nobody"))
        allies1 = next(iter(v1))
        v2 = votes[(mid, 2)]
        if len(v2) > 1 or (v2 and next(iter(v2)) == allies1):
            raise SystemExit("%s half 2: allies is club %s, but halftime swaps "
                             "sides off club %d" % (mid, dict(v2), allies1))
        out[(mid, 1)] = allies1
        out[(mid, 2)] = 3 - allies1
    return out


def resolve_points(match_teams: dict, ssh) -> dict:
    """match_id -> {"h1": [a,b] | None, "h2": [a,b] | None, "total": [a,b] |
    None} by club -- the team score, not the flag count resolve_scores returns.

    `total` is read straight off half 2 rather than added up, because half 2's
    score is cumulative: it opens at half 1's final and keeps counting, so the
    last reading of half 2 IS each club's two-half total and is what the
    scoreboard showed at the whistle. The per-half half-2 figure is the derived
    one. Summing the halves gives the same number by construction -- that is
    the check, not the definition.
    """
    ids = ",".join("'%s'" % m for m in match_teams)
    stream = defaultdict(list)
    for mid, ident, half, tick, allies, axis in mysql(ssh, """SELECT match_id,
        id, half, COALESCE(tick, 0),
        CAST(JSON_EXTRACT(payload,'$.allies_score') AS SIGNED),
        CAST(JSON_EXTRACT(payload,'$.axis_score') AS SIGNED)
        FROM hud_events WHERE event = 'team_score' AND match_id IN (%s)
        ORDER BY match_id, id;""" % ids, "team_score"):
        if allies == "NULL" or axis == "NULL":
            continue
        stream[(mid, int(half))].append(
            (int(ident), float(tick), int(allies), int(axis)))

    # The plugin's own close events. Both are in HALF-1 side terms, including
    # ktp_match_end, which is why gating half 2 against it tests the side swap.
    closed = {}
    for mid, event, allies, axis in mysql(ssh, """SELECT match_id,
        event, CAST(JSON_EXTRACT(payload,'$.allies_score') AS SIGNED),
        CAST(JSON_EXTRACT(payload,'$.axis_score') AS SIGNED)
        FROM hud_events WHERE event IN ('half_end','ktp_match_end')
        AND match_id IN (%s);""" % ids, "close"):
        if allies != "NULL" and axis != "NULL":
            closed[(mid, event)] = (int(allies), int(axis))

    allies_club = side_map(match_teams, ssh)

    def by_club(mid, half, allies, axis):
        pair = [0, 0]
        pair[allies_club[(mid, half)] - 1] = allies
        pair[2 - allies_club[(mid, half)]] = axis
        return pair

    def final_of(mid, half):
        rows = stream.get((mid, half))
        return tick_segments(rows)[0][-1] if rows else None

    points = {}
    for mid in match_teams:
        h1_row, h2_row = final_of(mid, 1), final_of(mid, 2)
        h1 = by_club(mid, 1, h1_row[2], h1_row[3]) if h1_row else None
        total = by_club(mid, 2, h2_row[2], h2_row[3]) if h2_row else None
        for half, event, derived in ((1, "half_end", h1), (2, "ktp_match_end", total)):
            if derived is None:
                continue
            confirm = closed.get((mid, event))
            if confirm is None or by_club(mid, 1, *confirm) != derived:
                raise SystemExit(
                    "%s half %d: derived %s but %s says %s -- refusing to emit "
                    "a score its own close event doesn't confirm"
                    % (mid, half, derived, event, confirm))
        h2 = ([total[0] - h1[0], total[1] - h1[1]]
              if h1 and total else None)
        points[mid] = ({"h1": h1, "h2": h2, "total": total}
                       if h1 or total else None)
    return points


def resolve_scores(match_teams: dict, ssh) -> dict:
    """match_id -> {"h1": [a,b], "h2": [a,b], "final": [a,b]} by club -- FLAGS
    CAPTURED, not the match score (resolve_points has that). Uses
    ktp_match_players.team (1/2) as the index into match_teams[mid]. None for
    the one match with no close event."""
    ids = ",".join("'%s'" % m for m in match_teams)
    sql = """SELECT pa.match_id,
           CASE WHEN pa.eventTime BETWEEN h1.start_time AND h1.end_time THEN 1
                WHEN pa.eventTime BETWEEN h2.start_time AND h2.end_time THEN 2
                ELSE 0 END AS half,
           mp.team, COUNT(*)
    FROM hlstats_Events_PlayerActions pa
    JOIN ktp_match_players mp ON mp.match_id COLLATE utf8mb4_unicode_ci = pa.match_id
                              AND mp.player_id = pa.playerId
    LEFT JOIN ktp_matches h1 ON h1.match_id COLLATE utf8mb4_unicode_ci = pa.match_id AND h1.half = 1
    LEFT JOIN ktp_matches h2 ON h2.match_id COLLATE utf8mb4_unicode_ci = pa.match_id AND h2.half = 2
    WHERE pa.actionId IN (337,338) AND pa.match_id IN (%s)
    GROUP BY pa.match_id, half, mp.team;""" % ids

    per_match = defaultdict(lambda: {1: [0, 0], 2: [0, 0]})
    for mid, half, team, n in mysql(ssh, sql, "flags"):
        half, team, n = int(half), int(team), int(n)
        if half == 0 or mid == NO_CLOSE_EVENT_MATCH:
            continue   # unattributable half bucket, or the one match we refuse to score
        per_match[mid][half][team - 1] += n

    scores = {}
    for mid in match_teams:
        if mid == NO_CLOSE_EVENT_MATCH:
            scores[mid] = None
            continue
        h = per_match.get(mid)
        if not h:
            scores[mid] = None
            continue
        h1, h2 = h[1], h[2]
        scores[mid] = {"h1": h1, "h2": h2, "final": [h1[0] + h2[0], h1[1] + h2[1]]}
    return scores


def main() -> int:
    check = "--check" in sys.argv
    match_teams = load("match-teams.json")
    bracket = load("bracket.json")
    captures_placed = load("captures-placed.json")

    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/New_York")

    rounds, mkeys = resolve_rounds(match_teams, bracket, captures_placed, tz)

    for candidate in (r"N:\Nein_\KTP Git Projects", "/mnt/n/Nein_/KTP Git Projects"):
        if os.path.isdir(candidate):
            sys.path.insert(0, candidate)
            break
    else:
        sys.exit("can't find the project root (ktp_hosts.py) from either a "
                  "Windows or WSL mount path -- adjust the candidates above")
    from ktp_hosts import connect
    ssh = connect("data")
    try:
        scores = resolve_scores(match_teams, ssh)
        points = resolve_points(match_teams, ssh)
    finally:
        ssh.close()

    mid_map = {}
    for r in captures_placed:
        mid_map.setdefault(r["match_id"], r["map"])   # dod_-prefixed, suffix intact

    out = {mid: {"round": rounds[mid], "mkey": mkeys[mid], "score": scores[mid],
                 "points": points[mid], "map": mid_map[mid]}
           for mid in match_teams}

    unflagged = [m for m, v in out.items() if v["score"] is None]
    partial = [m for m, v in out.items()
               if v["points"] and v["points"]["total"] is None]
    unscored = [m for m, v in out.items() if v["points"] is None]
    unresolved_round = [m for m, v in out.items() if v["round"] == "Sunday playoffs"]
    print("matches: %d, no flag count: %s, no score at all: %s, "
          "score for half 1 only: %s, unresolved-round (Sunday playoffs "
          "fallback): %s" % (len(out), unflagged, unscored, partial, unresolved_round))

    path = os.path.join(HERE, "match-extras.json")
    if check:
        if not os.path.exists(path):
            sys.exit("match-extras.json does not exist -- run without --check first")
        current = json.load(open(path, encoding="utf-8"))
        if current != out:
            diffs = [m for m in out if current.get(m) != out.get(m)]
            sys.exit("match-extras.json is stale for %d match(es): %s" % (len(diffs), diffs))
        print("match-extras.json matches a fresh rebuild -- OK")
        return 0

    with open(path, "w", encoding="utf-8", newline="") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    print("wrote %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
