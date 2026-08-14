#!/usr/bin/env python3
"""Per-match score and bracket round, for the match-page baked shell.

Neither is stored anywhere as a single column -- verified against the live DB
(hlstatsx_lan on the data server) and against bracket.json/veto.json, which
turned out to disagree with each other and with the site's own static bracket
markup in three separate places. Findings kept here so the next person doesn't
re-derive them:

SCORE. No table stores a team's round/flag tally. It's the count of
actionId IN (337, 338) (dod_control_point, dod_capture_area -- the same pair
recover_captures.py used) in hlstats_Events_PlayerActions, joined to
ktp_match_players.team (1/2, constant for the whole match -- DoD swaps a
player's in-game Allies/Axis side at halftime, but never their club, so
joining on club sidesteps the side-swap entirely). half comes from bucketing
eventTime into ktp_matches' per-half [start_time, end_time] window, since
PlayerActions itself carries no half column.

hlstats_* tables collate utf8mb4_unicode_ci; ktp_* tables collate
utf8mb4_0900_ai_ci. Joining match_id across the two 1267s ("Illegal mix of
collations") without an explicit COLLATE.

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
"final": [a,b]} | null}}
mkey is the veto-data/bracket.json key when the match resolved to a specific
bracket slot (join it there for that match's veto sequence); null for group
stage and the "Sunday playoffs" fallback, both of which have no veto record.
score is null only for 1785715972-KTP1 (the Final's second game -- logging
died before the close event, and even the partial captures that exist here
are from a match that never finished, so a number would overstate what's
known). Everything else has real data: 55 of 56 curated matches.
"""
from __future__ import annotations

import json
import os
import sys
import datetime
from collections import defaultdict

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


def resolve_scores(match_teams: dict, ssh) -> dict:
    """match_id -> {"h1": [a,b], "h2": [a,b], "final": [a,b]} by club, using
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

    sftp = ssh.open_sftp()
    with sftp.open("/tmp/match_extras_score.sql", "w") as fh:
        fh.write(sql)
    sftp.close()
    stdin, stdout, stderr = ssh.exec_command(
        "mysql hlstatsx_lan -N < /tmp/match_extras_score.sql", timeout=120)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace").strip()
    if err:
        raise SystemExit("score query failed: %s" % err)

    per_match = defaultdict(lambda: {1: [0, 0], 2: [0, 0]})
    for line in out.splitlines():
        if not line.strip():
            continue
        mid, half, team, n = line.split("\t")
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
    finally:
        ssh.close()

    mid_map = {}
    for r in captures_placed:
        mid_map.setdefault(r["match_id"], r["map"])   # dod_-prefixed, suffix intact

    out = {mid: {"round": rounds[mid], "mkey": mkeys[mid], "score": scores[mid],
                 "map": mid_map[mid]}
           for mid in match_teams}

    unscored = [m for m, v in out.items() if v["score"] is None]
    unresolved_round = [m for m, v in out.items() if v["round"] == "Sunday playoffs"]
    print("matches: %d, unscored: %s, unresolved-round (Sunday playoffs fallback): %s"
          % (len(out), unscored, unresolved_round))

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
