#!/usr/bin/env python3
"""Generate award candidates for an edition, from the catalogue in award_catalog.py.

Dry-run by default: writes awards_candidates.json and awards_candidates.sql next
to this file and prints a summary. `--apply` is the only path that touches MySQL,
and it only ever writes `lan_award_types` defaults and `lan_award_candidates` —
`lan_award_selections` is operator intent and is never written from here.

HLStatsX decides every stat it can measure; the HUD is a fallback and nothing
else. Operator rule, 2026-08-14, and it is not a tie-break — the HUD counts
teamkills, suicides and warmup as kills, so taking the larger number would
silently redefine what a kill is. Every award states its source in the default
sting so a reader can tell which side of that line a figure came from.

  ktp_match_stats     kills, deaths, headshots, teamkills, damage. Halves 1 and
                      2 only — half 0 is the match total and would double it.
  hlstats_Events_Frags weapon-scoped counts (pistol, melee, grenade, gun), kill
                      streaks and the nemesis pair.
  hlstats_Events_PlayerActions  captures, both control points and areas.
  hlstats_Events_Statsme / …2   shots landed, and which hitbox they landed on.
  lan-stats.json      weekend and per-day totals, which already apply this same
                      precedence; any column it fills from the HUD that HLStatsX
                      can also measure is re-derived here rather than folded.
  hud_*               only what HLStatsX has no equivalent for: assists, cap
                      breaks, objective score, prone, damage TAKEN (HLStatsX
                      logs damage dealt), and suicides — of which HLStatsX
                      recorded none at this event.
  season-board.json   the per-day team-formula KTPR the positions panel ranks on.

Scoping follows apply_award_decisions.py: the tournament set is the 56 curated
matches in match-teams.json, not the 55 that logged a `ktp_match_end`.

    python build_awards.py                  # dry run, writes the two files
    python build_awards.py --check-anchors   # regression check, non-zero on drift
    python build_awards.py --apply           # the only writing path
"""

from __future__ import annotations

import argparse
import bisect
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict

import award_catalog
import kill_streaks
from award_catalog import FMT_CLOCK, FMT_INT, FMT_KTPR, FMT_RATE, FMT_RATIO

HERE = os.path.dirname(os.path.abspath(__file__))
DB = "hlstatsx_lan"
# Reads and writes go to DIFFERENT databases. The stats live in hlstatsx_lan;
# the award tables are lan-web's, and lan-web connects as ktp_lan with no
# privilege outside it — writing them next to the stats is how lan_stats_publication
# ended up unreadable by the app that was supposed to read it.
AWARD_DB = os.environ.get("KTP_AWARD_DB", "ktp_lan")
EDITION = "philly-2026"

# The two competition days, in order, with the face the page prints. Award slugs
# use the ordinal rather than the date so an operator rename survives to 2027.
DAYS = (("08-01", "Sat"), ("08-02", "Sun"))

# Rows kept per award: five, then whatever else shares the fifth mark. Carrying
# whole tie groups is what the published lists do, and a truncated group renders
# as a record that fewer players hold than really do.
TOP_N = 5

POSITIONS_SLUG = "weekend-positions"
POSITIONS_TITLE = "Best six by position"
POSITIONS_STING = ("Top KTPR at each position — two rifles, two heavies, a 3rd "
                   "and a sniper, the way a roster is built.")
# Display order of the panel, which is not (role, slot) order. rank_pos carries it.
POSITION_SLOTS = (("Rifle", 1), ("Heavy", 1), ("3rd", 1),
                  ("Rifle", 2), ("Heavy", 2), ("Sniper", 1))

PISTOLS = ("colt", "luger")
MELEE = ("spade", "amerknife", "bayonet", "garandbutt", "k43butt")
GRENADES = ("grenade", "grenade2")
CAPTURE_ACTIONS = (337, 338)

# Where each stat comes from, printed on the card. A HUD entry has to say what
# HLStatsX lacks, because "HUD" on its own reads as a preference rather than the
# absence it actually is.
PROVENANCE = {
    "kills": "Match record.", "deaths": "Match record.",
    "kd": "Match record.", "headshots": "Match record.",
    "damage_dealt": "Match record.", "damage_hlstatsx": "Match record.",
    "teamkills": "Match record.", "score": "Match record.",
    "kills_per_half": "Match record.", "matches": "Match record.",
    "flags": "HLStatsX — control points and areas captured.",
    "flags_per_half": "HLStatsX — control points and areas captured.",
    "pistol_kills": "Frag log.", "melee_kills": "Frag log.",
    "nade_kills": "Frag log.", "gun_kills": "Frag log.",
    "best_streak": "Frag log — rebuilt from the kills, not read off the HUD.",
    "nemesis_pair": "Frag log.",
    "hits": "HLStatsX — per-weapon shots landed.",
    "hs_hits": "HLStatsX — per-weapon shots landed on a head.",
    "ktpr": "Match record — rated against that day's field, so it does not "
            "compare across days.",
    "assists": "HUD — the match record has no assists at all.",
    "cap_breaks": "HUD — nothing else records a broken capture.",
    "obj_score": "HUD — nothing else scores the objective.",
    "prone_seconds": "HUD — nothing else measured prone.",
    "prone_events": "HUD — nothing else measured prone.",
    "damage_taken": "HUD — the match record logs damage dealt only.",
    "suicides": "HUD — the event's frag log recorded no suicides at all.",
    "caps_hud": "HUD — completed captures, where the match record counts control "
                "points and areas together.",
}

# Eligibility floors, keyed by slug. A low-direction award without one is won by
# whoever showed up least, and two of the K/D awards state their own floor in the
# sting — which makes the sting a promise the generator has to keep.
FLOORS = {
    "weekend-kd-high": {"min_stat_key": "halves", "min_stat": 20},
    "weekend-kd-low": {"min_stat_key": "halves", "min_stat": 20},
    "match-kd-high": {"min_stat_key": "kills", "min_stat": 30},
    "match-kd-low": {"min_stat_key": "deaths", "min_stat": 30},
    "match-damage-taken-low": {"min_stat_key": "halves", "min_stat": 2},
}
# Every other low-direction weekend award gets the operator's played-half-the-games
# rule instead.
DEFAULT_LOW_MIN_SHARE = 0.5


# --------------------------------------------------------------- data server

def connect():
    """SSH to the stats host. Credentials come from ktp_hosts.py, never from here.

    This repo is public, so a password committed here is a published password.
    KTP_DATA_HOST/KTP_DATA_PASSWORD stay supported as the clone-friendly path,
    matching build_stats.py.
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

    # Found by walking up rather than by a fixed depth: a git worktree sits three
    # directories deeper than a plain checkout, so a counted path works in one
    # layout and reports missing credentials in the other.
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


def sql(c, q, t=900, db=None):
    cmd = "mysql %s -N --raw -e '%s' 2>&1" % (db or DB, q.replace("'", "'\\''"))
    _, o, _ = c.exec_command(cmd, timeout=t)
    out = o.read().decode("utf-8", "replace").strip()
    if out.startswith("ERROR"):
        raise RuntimeError(out[:400])
    return [line.split("\t") for line in out.splitlines() if line.strip()]


def sid(v):
    """Canonical player key 'Y:Z' — the HUD stores STEAM_0:Y:Z, HLStatsX Y:Z."""
    v = (v or "").strip()
    if v.upper().startswith("STEAM_"):
        v = v.split(":", 1)[1] if ":" in v else v
    return v


def load(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return json.load(fh)


# ------------------------------------------------------------------- naming

class Names:
    """Display names, derived the way the awards board and the ballots derive them.

    Mirrors build_ballots.py rather than importing it: that module does its work
    at import time and rewrites awards.json on the way out, so importing it to
    borrow four functions would be a side effect nobody asked for.
    """

    def __init__(self, stats, teams, aliases):
        self.aliases = aliases
        by_team = defaultdict(set)
        for day in stats["days"].values():
            for p in day["players"]:
                t = (teams.get(p["steam_id"]) or {}).get("team")
                if t:
                    by_team[t].add(p["name"])
        prefixes = []
        for names in by_team.values():
            names = sorted(names)
            if len(names) < 2:
                continue
            pre = names[0]
            for n in names:
                i = 0
                while i < len(pre) and i < len(n) and pre[i] == n[i]:
                    i += 1
                pre = pre[:i]
            if len(pre) >= 2:
                prefixes.append(pre)
        prefixes.sort(key=len, reverse=True)
        self.prefixes = prefixes

    def short(self, n):
        """Drop the clan tag, which is a prefix shared across a team's names."""
        for p in self.prefixes:
            if n.startswith(p):
                s = n[len(p):].strip()
                if s:
                    return s
        return n

    @staticmethod
    def trim_flair(n):
        """Cut the shoutout people hang off the back of a name."""
        for pat in ("<3", r"\s+4\s*\S", "＃", r"\s#", "#"):
            m = re.search(pat, n)
            if m and m.start() > 0:
                n = n[:m.start()]
        return n.strip(" -_") or n

    def untag(self, name, known):
        """Drop a one-off tag the team-wide prefix derivation cannot see."""
        best = name
        for other in known:
            o = self.trim_flair(self.short(other))
            if len(o) >= len(best) or not best.lower().endswith(o.lower()):
                continue
            if best[len(best) - len(o) - 1].isalnum():
                continue
            best = o
        return best

    def canon(self, steam, seen_as=None):
        known = self.aliases.get(steam) or []
        seen = self.trim_flair(self.short(known[0] if known else (seen_as or steam)))
        return self.untag(seen, known)

    def alias(self, steam, raw):
        """The name worn at the time, when it is not what the card calls them."""
        if not raw:
            return None
        worn = self.short(raw)
        return worn if worn != self.canon(steam, raw) else None


def key(n):
    n = unicodedata.normalize("NFKD", n).lower()
    n = re.split(r"[<＃#|]", n)[0]
    return re.sub(r"[^a-z0-9]", "", n)


# ------------------------------------------------------------------ fetching

class Facts:
    """Everything the awards are computed from, fetched once."""

    def __init__(self):
        self.stats = load("lan-stats.json")
        self.teams = {k: v.get("team") for k, v in load("player_teams.json").items()}
        self.match_teams = load("match-teams.json")
        self.board = load("season-board.json")
        self.names = Names(self.stats, load("player_teams.json"),
                           load("player_aliases.json"))
        self.matches = {}          # match_id -> {map, day, face, teams}
        self.record = {}           # (match, steam) -> dict of match-record stats
        self.hud = {}              # (match, steam) -> dict of HUD-only stats
        self.frags = defaultdict(Counter)   # (match, steam) -> weapon counter
        self.streaks = {}          # (match, steam) -> longest run without dying
        self.nemesis = defaultdict(Counter)  # steam -> Counter victim steam
        self.flags = Counter()     # (match, steam) -> captures
        self.suicides = Counter()  # (match, steam) -> suicides
        self.prone = {}            # (match, steam) -> (seconds, events)
        self.prone_intervals = {}  # steam -> credited intervals, for --prone-audit
        self.hits = Counter()      # (match, steam) -> shots landed
        self.hs_hits = Counter()   # (match, steam) -> shots landed on a head
        self.player_name = {}      # steam -> last raw in-game name seen
        self.totals = {}           # source -> stat -> event total, for --sources

    # -- helpers ---------------------------------------------------------

    def ids_sql(self):
        return ",".join("'%s'" % m for m in sorted(self.match_teams))

    def opponent(self, match_id, steam):
        clubs = self.match_teams.get(match_id) or []
        mine = self.teams.get(steam)
        other = [t for t in clubs if t != mine]
        return other[0] if len(other) == 1 else None

    def where_match(self, match_id, steam):
        m = self.matches.get(match_id)
        if not m:
            return None
        opp = self.opponent(match_id, steam)
        parts = [m["map"], m["face"]]
        if opp:
            parts.append("v " + opp)
        return " · ".join(parts)

    # -- the fetch --------------------------------------------------------

    def fetch(self, c):
        ids = self.ids_sql()

        for mid, mp, start in sql(c, """
                SELECT match_id, MIN(map_name), MIN(start_time) FROM ktp_matches
                WHERE match_id IN (%s) GROUP BY match_id""" % ids):
            day = start[5:10]
            self.matches[mid] = {
                "map": mp[4:] if mp.startswith("dod_") else mp,
                "day": day,
                "face": dict(DAYS).get(day, day),
                "teams": self.match_teams.get(mid) or [],
            }
        missing = set(self.match_teams) - set(self.matches)
        if missing:
            raise SystemExit("ktp_matches has no row for %d curated match(es): %s"
                             % (len(missing), sorted(missing)))

        # half IN (1,2): half 0 is the match total and would double everything.
        for mid, steam_raw, name, k, d, hs, tk, dmg, sc, halves in sql(c, """
                SELECT s.match_id, p.steam_id, MAX(p.player_name),
                       SUM(s.kills), SUM(s.deaths), SUM(s.headshots),
                       SUM(s.team_kills), SUM(s.damage), SUM(s.score),
                       COUNT(DISTINCT s.half)
                FROM ktp_match_stats s
                JOIN ktp_match_players p
                  ON p.match_id = s.match_id AND p.player_id = s.player_id
                WHERE s.half IN (1,2) AND s.match_id IN (%s)
                GROUP BY s.match_id, p.steam_id""" % ids):
            steam = sid(steam_raw)
            self.player_name[steam] = name
            self.record[(mid, steam)] = {
                "kills": int(k or 0), "deaths": int(d or 0),
                "headshots": int(hs or 0), "teamkills": int(tk or 0),
                "damage_dealt": int(dmg or 0), "score": int(sc or 0),
                "halves": int(halves or 0), "name": name,
            }

        # Only the columns HLStatsX has no equivalent for. kills, deaths,
        # headshots, damage and hits are all in this table too and all ignored.
        for mid, steam_raw, assists, breaks, obj, caps in sql(c, """
                SELECT match_id, steam_id, SUM(assists), SUM(cap_breaks),
                       SUM(obj_score), SUM(caps)
                FROM hud_player_stats
                WHERE is_final = 1 AND match_id IN (%s)
                GROUP BY match_id, steam_id""" % ids):
            self.hud[(mid, sid(steam_raw))] = {
                "assists": int(assists or 0), "cap_breaks": int(breaks or 0),
                "obj_score": int(obj or 0), "caps_hud": int(caps or 0),
                "damage_taken": 0,
            }

        # Statsme counts every landed shot; Statsme2 breaks the same shots down by
        # hitbox but has no generic bucket, so the two do not add up and only
        # Statsme can answer "hits".
        for mid, steam_raw, hits in sql(c, """
                SELECT s.match_id, u.uniqueId, SUM(s.hits)
                FROM hlstats_Events_Statsme s
                JOIN hlstats_PlayerUniqueIds u ON u.playerId = s.playerId
                WHERE s.match_id IN (%s)
                GROUP BY s.match_id, u.uniqueId""" % ids):
            self.hits[(mid, sid(steam_raw))] = int(hits or 0)

        for mid, steam_raw, head in sql(c, """
                SELECT s.match_id, u.uniqueId, SUM(s.head)
                FROM hlstats_Events_Statsme2 s
                JOIN hlstats_PlayerUniqueIds u ON u.playerId = s.playerId
                WHERE s.match_id IN (%s)
                GROUP BY s.match_id, u.uniqueId""" % ids):
            self.hs_hits[(mid, sid(steam_raw))] = int(head or 0)

        for mid, steam_raw, taken in sql(c, """
                SELECT match_id, victim_id, SUM(damage) FROM hud_damage
                WHERE match_id IN (%s) AND victim_id IS NOT NULL
                GROUP BY match_id, victim_id""" % ids):
            row = self.hud.setdefault((mid, sid(steam_raw)), {
                "assists": 0, "cap_breaks": 0, "obj_score": 0, "caps_hud": 0,
                "hs_hits": 0, "damage_taken": 0})
            row["damage_taken"] = int(taken or 0)

        # hlstats has no suicide rows for this event at all — the HUD's own kill
        # classification is the only source that records them.
        for mid, steam_raw, n in sql(c, """
                SELECT match_id, victim_id, COUNT(*) FROM hud_kills
                WHERE match_id IN (%s) AND kill_type = 'suicide'
                GROUP BY match_id, victim_id""" % ids):
            self.suicides[(mid, sid(steam_raw))] = int(n or 0)

        for mid, steam_raw, n in sql(c, """
                SELECT e.match_id, u.uniqueId, COUNT(*)
                FROM hlstats_Events_PlayerActions e
                JOIN hlstats_PlayerUniqueIds u ON u.playerId = e.playerId
                WHERE e.actionId IN (%s) AND e.match_id IN (%s)
                GROUP BY e.match_id, u.uniqueId"""
                % (",".join(str(a) for a in CAPTURE_ACTIONS), ids)):
            self.flags[(mid, sid(steam_raw))] = int(n or 0)

        # killerId <> victimId: a melee suicide is not a melee kill.
        for mid, steam_raw, weapon, n in sql(c, """
                SELECT f.match_id, u.uniqueId, f.weapon, COUNT(*)
                FROM hlstats_Events_Frags f
                JOIN hlstats_PlayerUniqueIds u ON u.playerId = f.killerId
                WHERE f.match_id IN (%s) AND f.killerId <> f.victimId
                GROUP BY f.match_id, u.uniqueId, f.weapon""" % ids):
            self.frags[(mid, sid(steam_raw))][weapon] = int(n or 0)

        for kill_raw, victim_raw, n in sql(c, """
                SELECT ku.uniqueId, vu.uniqueId, COUNT(*)
                FROM hlstats_Events_Frags f
                JOIN hlstats_PlayerUniqueIds ku ON ku.playerId = f.killerId
                JOIN hlstats_PlayerUniqueIds vu ON vu.playerId = f.victimId
                WHERE f.match_id IN (%s) AND f.killerId <> f.victimId
                GROUP BY ku.uniqueId, vu.uniqueId""" % ids):
            self.nemesis[sid(kill_raw)][sid(victim_raw)] = int(n or 0)

        self._fetch_streaks(c, ids)
        self._fetch_prone(c, ids)
        self._fetch_overlap(c, ids)

    def _fetch_overlap(self, c, ids):
        """Event totals from both sources, for the stats both of them hold.

        Nothing here feeds an award — it exists so the precedence rule can be
        audited rather than trusted, and so a gap that grows into a data problem
        is visible instead of buried under HLStatsX winning by fiat.
        """
        hud = sql(c, """
            SELECT SUM(kills), SUM(deaths), SUM(hs_kills), SUM(damage),
                   SUM(caps), SUM(hits), SUM(hs_hits), SUM(nade_kills),
                   SUM(gun_kills)
            FROM hud_player_stats WHERE is_final = 1 AND match_id IN (%s)""" % ids)
        cols = ("kills", "deaths", "headshots", "damage", "flags", "hits",
                "hs_hits", "nade_kills", "gun_kills")
        self.totals["hud"] = dict(zip(cols, (int(v or 0) for v in hud[0])))

        weapons = Counter()
        for counter in self.frags.values():
            weapons += counter
        nades = sum(weapons[w] for w in GRENADES)
        melee = sum(weapons[w] for w in MELEE)
        self.totals["hlstatsx"] = {
            "kills": sum(r["kills"] for r in self.record.values()),
            "deaths": sum(r["deaths"] for r in self.record.values()),
            "headshots": sum(r["headshots"] for r in self.record.values()),
            "damage": sum(r["damage_dealt"] for r in self.record.values()),
            "flags": sum(self.flags.values()),
            "hits": sum(self.hits.values()),
            "hs_hits": sum(self.hs_hits.values()),
            "nade_kills": nades,
            "gun_kills": sum(weapons.values()) - nades - melee,
        }
        self.totals["weapons"] = dict(weapons)

    def _fetch_streaks(self, c, ids):
        """Longest run of kills without dying, per match.

        The walk itself lives in kill_streaks.py because build_stats.py needs
        the same one for the weekend board, and the HUD column it used to read
        instead disagrees with the frag log for a sixth of the field.
        """
        rows = [(mid, int(half), sid(killer_raw), sid(victim_raw), weapon)
                for mid, half, killer_raw, victim_raw, weapon in sql(c, """
                    SELECT f.match_id, f.half, ku.uniqueId, vu.uniqueId, f.weapon
                    FROM hlstats_Events_Frags f
                    JOIN hlstats_PlayerUniqueIds ku ON ku.playerId = f.killerId
                    JOIN hlstats_PlayerUniqueIds vu ON vu.playerId = f.victimId
                    WHERE f.half IN (1,2) AND f.match_id IN (%s)
                    ORDER BY f.id""" % ids)]
        folded = kill_streaks.best_by(kill_streaks.best_runs(rows),
                                      lambda mid, _half, steam: (mid, steam))
        self.streaks = {key: run.length for key, (_where, run) in folded.items()}

    @staticmethod
    def _segments(rows):
        """Split a HUD stream where `tick` jumps backwards.

        `tick` is the server's map uptime, not time within the half, and it
        RESETS when the map reloads — while the rows either side of the reset
        keep the same match_id and half. Ordering by tick therefore interleaves
        two different real-time periods, and pairing across the seam invents an
        interval that never happened. Rows arrive in insertion order (`id`),
        which is the order the events actually occurred in, so the seam is
        visible as the one place tick goes down.
        """
        out = [[]]
        for r in rows:
            if out[-1] and r[1] < out[-1][-1][1] - 1:
                out.append([])
            out[-1].append(r)
        return [s for s in out if s]

    def _fetch_prone(self, c, ids):
        """Prone time, bounded by the player's next death, within one tick run.

        `hud_prone` records a `standing` row on every spawn, so an interval left
        to run to the next transition counts the whole respawn wait as time on
        the deck. Bounding at the death reproduces lan-stats.json for most of
        the field; segmenting at the tick reset removes the rest of the gap,
        which was four players credited with several minutes each across a map
        reload.
        """
        trans, deaths = defaultdict(list), defaultdict(list)
        for ident, mid, half, tick, steam_raw, state in sql(c, """
                SELECT id, match_id, half, tick, steam_id, state FROM hud_prone
                WHERE match_id IN (%s) ORDER BY id""" % ids):
            trans[(mid, int(half), sid(steam_raw))].append(
                (int(ident), float(tick or 0), state))
        for ident, mid, half, tick, steam_raw in sql(c, """
                SELECT id, match_id, half, tick, victim_id FROM hud_kills
                WHERE match_id IN (%s) ORDER BY id""" % ids):
            deaths[(mid, int(half), sid(steam_raw))].append(
                (int(ident), float(tick or 0)))

        acc = defaultdict(lambda: [0.0, 0])
        self.prone_intervals = defaultdict(list)
        for (mid, half, steam), rows in trans.items():
            kill_runs = self._segments(deaths.get((mid, half, steam), []))
            for run in self._segments(rows):
                lo, hi = run[0][1], run[-1][1]
                ends = sorted(t for k in kill_runs for _i, t in k
                              if lo - 1 <= t <= hi + 1)
                for i, (_ident, tick, state) in enumerate(run):
                    if state != "prone":
                        continue
                    acc[(mid, steam)][1] += 1
                    end = run[i + 1][1] if i + 1 < len(run) else None
                    j = bisect.bisect_right(ends, tick)
                    if j < len(ends):
                        end = ends[j] if end is None else min(end, ends[j])
                        bound = "death" if end == ends[j] else "transition"
                    else:
                        bound = "transition" if end is not None else "nothing"
                    if end is None:
                        self.prone_intervals[steam].append(
                            (0.0, mid, half, tick, None, "nothing"))
                        continue
                    acc[(mid, steam)][0] += end - tick
                    self.prone_intervals[steam].append(
                        (end - tick, mid, half, tick, end, bound))
        self.prone = {k: (round(v[0], 1), v[1]) for k, v in acc.items()}

    # -- derived views ----------------------------------------------------

    def weekend_players(self):
        """Weekend totals per player, folded from the two per-day rows.

        Rates are recomputed from the weekend totals rather than averaged: a mean
        of two per-day rates weights a four-half day the same as a twelve-half one.

        Four columns are re-derived rather than folded. lan-stats.json fills
        `hits`, `hs_hits`, `nade_kills` and `gun_kills` from the HUD, and
        HLStatsX carries all four — Statsme for shots landed, Statsme2 for the
        ones that hit a head, the frag log for the two kill breakdowns — so the
        operator precedence puts them back on HLStatsX.
        """
        agg = {}
        summed = ("kills", "deaths", "flags", "headshots", "assists",
                  "damage_hlstatsx", "caps_hud", "cap_breaks",
                  "obj_score", "prone_seconds", "prone_events", "halves", "matches")
        for day in self.stats["days"].values():
            for p in day["players"]:
                a = agg.setdefault(p["steam_id"], dict.fromkeys(summed, 0))
                a["name"] = p["name"]
                a["best_streak"] = max(a.get("best_streak", 0), p.get("best_streak") or 0)
                for f in summed:
                    a[f] += p.get(f) or 0

        hits, hs_hits, weapons = Counter(), Counter(), defaultdict(Counter)
        for (_mid, steam), n in self.hits.items():
            hits[steam] += n
        for (_mid, steam), n in self.hs_hits.items():
            hs_hits[steam] += n
        for (_mid, steam), counter in self.frags.items():
            weapons[steam] += counter

        for steam, a in agg.items():
            halves = a["halves"] or 1
            w = weapons.get(steam, Counter())
            a["hits"] = hits.get(steam, 0)
            a["hs_hits"] = hs_hits.get(steam, 0)
            a["nade_kills"] = sum(w[g] for g in GRENADES)
            a["melee_kills"] = sum(w[m] for m in MELEE)
            a["pistol_kills"] = sum(w[p] for p in PISTOLS)
            a["gun_kills"] = sum(w.values()) - a["nade_kills"] - a["melee_kills"]
            a["kd"] = a["kills"] / a["deaths"] if a["deaths"] else float(a["kills"])
            a["kills_per_half"] = a["kills"] / halves
            a["flags_per_half"] = a["flags"] / halves
            a["club"] = self.teams.get(steam)
        return agg

    def match_players(self):
        """One row per (match, player), every match-scope stat on it."""
        out = {}
        for (mid, steam), rec in self.record.items():
            hud = self.hud.get((mid, steam), {})
            weapons = self.frags[(mid, steam)]
            prone_sec, prone_ev = self.prone.get((mid, steam), (0.0, 0))
            row = dict(rec)
            row.update({
                "assists": hud.get("assists", 0),
                "cap_breaks": hud.get("cap_breaks", 0),
                "obj_score": hud.get("obj_score", 0),
                "damage_taken": hud.get("damage_taken", 0),
                "flags": self.flags.get((mid, steam), 0),
                "suicides": self.suicides.get((mid, steam), 0),
                "pistol_kills": sum(weapons[w] for w in PISTOLS),
                "melee_kills": sum(weapons[w] for w in MELEE),
                "nade_kills": sum(weapons[w] for w in GRENADES),
                # A pistol is a gun; only thrown and swung kills come off the total.
                "gun_kills": (sum(weapons.values())
                              - sum(weapons[w] for w in GRENADES)
                              - sum(weapons[w] for w in MELEE)),
                "hits": self.hits.get((mid, steam), 0),
                "hs_hits": self.hs_hits.get((mid, steam), 0),
                "best_streak": self.streaks.get((mid, steam), 0),
                "prone_seconds": prone_sec,
                "prone_events": prone_ev,
                "club": self.teams.get(steam),
            })
            row["kd"] = row["kills"] / row["deaths"] if row["deaths"] else float(row["kills"])
            out[(mid, steam)] = row
        return out


# ---------------------------------------------------------------- formatting

def fmt_value(fmt, value, row=None):
    if value is None:
        return ""
    if fmt == FMT_INT:
        return "{:,}".format(int(round(value)))
    if fmt == FMT_RATE:
        return "%.2f / half" % value
    if fmt == FMT_KTPR:
        return "%.3f KTPR" % value
    if fmt == FMT_CLOCK:
        total = int(round(value))
        return "%d:%02d" % (total // 60, total % 60)
    if fmt == FMT_RATIO:
        # The pair the ratio came from is still printed -- a ratio nobody can
        # sanity-check by eye is worth less -- but it rides the context line
        # rather than the value. `.val` is nowrap in a narrow card, and
        # "0.66 K/D (441-670)" squeezed the winner's name into its ellipsis.
        return "%.2f K/D" % value
    return str(value)


def ratio_context(row, where):
    """The kills-deaths pair, folded into the context line ahead of the match."""
    if not row or row.get("kills") is None or row.get("deaths") is None:
        return where
    pair = "%d-%d" % (row["kills"], row["deaths"])
    return "%s · %s" % (pair, where) if where else pair


# ------------------------------------------------------------------ ranking

def rank_rows(entries, direction, limit=TOP_N):
    """Competition rank, cut at `limit` rows but never mid-tie.

    Rows come back already ordered so rank 1 is the winner whichever way the
    award points, which is what lets the API compute decisiveness without
    knowing the direction.
    """
    entries = sorted(entries, key=lambda e: (-e["value"] if direction == "high"
                                             else e["value"], e["who"].lower()))
    out, rank, prev = [], 0, object()
    for i, e in enumerate(entries, 1):
        if e["value"] != prev:
            rank, prev = i, e["value"]
        if len(out) >= limit and rank != out[-1]["rank_pos"]:
            break
        out.append(dict(e, rank_pos=rank))
    return out


def eligible(rows, floor, event_halves):
    """Apply the two floor shapes. A low award without one is won by an absentee."""
    if not floor:
        return rows
    min_share = floor.get("min_share")
    min_key, min_stat = floor.get("min_stat_key"), floor.get("min_stat")
    keep = []
    for r in rows:
        if min_share is not None and event_halves:
            if (r["source"].get("halves") or 0) < min_share * event_halves:
                continue
        if min_key is not None and (r["source"].get(min_key) or 0) < min_stat:
            continue
        keep.append(r)
    return keep


# --------------------------------------------------------------- definitions

def definitions():
    """The catalogue, with the two shapes it cannot express folded in.

    `day` becomes one type per day ORDINAL rather than per date: ordinals recur
    at the next event, so an operator rename is inherited; a date-keyed slug
    would not recur and the rename would be lost.
    """
    out = []
    for d in award_catalog.iter_definitions():
        if d["scope"] != "day":
            out.append(dict(d, floor=FLOORS.get(d["slug"])))
            continue
        for n, (day, face) in enumerate(DAYS, 1):
            out.append(dict(
                d,
                slug="day%d-%s-%s" % (n, d["stat_key"].replace("_", "-"), d["direction"]),
                default_title="%s · Day %s" % (d["default_title"],
                                                    ("One", "Two", "Three")[n - 1]),
                default_sting=d["default_sting"],
                day=day, day_face=face, floor=None))
    for d in out:
        if d.get("floor") is None and d["direction"] == "low" and d["scope"] == "weekend":
            d["floor"] = {"min_share": DEFAULT_LOW_MIN_SHARE}
    return out


# ------------------------------------------------------------------ builders

def sting_with_source(d):
    """The catalogue sting plus where the number came from, as the live cards do.

    The default sting is what an operator reads before deciding to rename, so the
    provenance has to live on the card rather than in a build log nobody opens.
    """
    tag = PROVENANCE.get(d["stat_key"])
    if not tag:
        return d["default_sting"][:255]
    return ("%s %s" % (d["default_sting"], tag))[:255]


def weekend_player_rows(facts, d, weekend):
    entries = []
    for steam, a in weekend.items():
        if d["source"] == "frags":
            continue
        value = a.get(d["stat_key"])
        if value is None:
            return None
        entries.append({"who": facts.names.canon(steam, a["name"]),
                        "alias": facts.names.alias(steam, a["name"]),
                        "value": float(value), "where": None, "source": a,
                        "steam": steam})
    return entries


def weekend_frag_rows(facts, d, weekend):
    """Weekend awards counted off the frag log rather than a stats column."""
    entries = []
    if d["stat_key"] == "nemesis_pair":
        for steam, victims in facts.nemesis.items():
            if steam not in weekend or not victims:
                continue
            victim, n = max(victims.items(), key=lambda kv: (kv[1], kv[0]))
            club = facts.teams.get(steam)
            target = facts.names.canon(victim, facts.player_name.get(victim))
            entries.append({
                "who": facts.names.canon(steam, weekend[steam]["name"]),
                "alias": facts.names.alias(steam, weekend[steam]["name"]),
                "value": float(n),
                "where": "%s · v %s" % (club, target) if club else "v " + target,
                "source": weekend[steam], "steam": steam})
        return entries

    for steam, a in weekend.items():
        value = a.get(d["stat_key"])
        if value is None:
            return None
        entries.append({"who": facts.names.canon(steam, a["name"]),
                        "alias": facts.names.alias(steam, a["name"]),
                        "value": float(value),
                        "where": facts.teams.get(steam),
                        "source": a, "steam": steam})
    return entries


def day_rows(facts, d):
    day = facts.stats["days"].get(d["day"])
    if not day:
        return []
    entries = []
    for p in day["players"]:
        value = p.get(d["stat_key"])
        if value is None:
            continue
        club = facts.teams.get(p["steam_id"])
        entries.append({
            "who": facts.names.canon(p["steam_id"], p["name"]),
            "alias": facts.names.alias(p["steam_id"], p["name"]),
            "value": float(value),
            "where": "%s · %s" % (d["day_face"], club) if club else d["day_face"],
            "source": p, "steam": p["steam_id"]})
    return entries


def team_rows(facts, d, weekend):
    clubs = defaultdict(lambda: Counter())
    for steam, a in weekend.items():
        club = a.get("club")
        if not club:
            continue
        for f in ("kills", "deaths", "flags", "halves"):
            clubs[club][f] += a.get(f) or 0
    for (mid, steam), rec in facts.record.items():
        club = facts.teams.get(steam)
        if club:
            clubs[club]["teamkills"] += rec["teamkills"]

    entries = []
    for club, c in clubs.items():
        if d["stat_key"] == "kd":
            value = c["kills"] / c["deaths"] if c["deaths"] else float(c["kills"])
        else:
            value = c.get(d["stat_key"])
            if value is None:
                return None
        entries.append({"who": club, "alias": None, "value": float(value),
                        "where": None, "source": dict(c), "steam": None})
    return entries


def match_entries(facts, d, per_match, match_ids):
    """Rows for a match-scope award, restricted to `match_ids`."""
    entries = []
    for (mid, steam), row in per_match.items():
        if mid not in match_ids:
            continue
        value = row.get(d["stat_key"])
        if value is None:
            return None
        entries.append({
            "who": facts.names.canon(steam, row["name"]),
            "alias": facts.names.alias(steam, row["name"]),
            "value": float(value),
            "where": facts.where_match(mid, steam),
            "source": row, "steam": steam, "match": mid})
    return entries


def best_per_player(entries, direction):
    """One entry per player — their best match, the convention the lists follow.

    Ties on a player's own best are broken by the earliest match, so the card
    names the first time they did it rather than an arbitrary one.
    """
    best = {}
    for e in entries:
        cur = best.get(e["steam"])
        better = (cur is None
                  or (e["value"] > cur["value"] if direction == "high"
                      else e["value"] < cur["value"])
                  or (e["value"] == cur["value"] and e["match"] < cur["match"]))
        if better:
            best[e["steam"]] = e
    return list(best.values())


def positions_rows(facts):
    """Best six by position, one award, six role slots in display order.

    Each slot must go to a DIFFERENT player, keyed on steam_id: a player has a
    Saturday and a Sunday rating, and 18 of them played the two days under
    different names, so a name-keyed guard would silently not apply to those.
    """
    ranked = defaultdict(list)
    for day, face in DAYS:
        view = facts.board["views"].get(day)
        if not view:
            continue
        for r in view["players"]:
            ranked[r["position"]].append(
                (r["ktpr"], r["steam_id"], r["name"], r["team"], face))
    for pos in ranked:
        ranked[pos].sort(key=lambda x: (-x[0], x[1]))

    taken, rows = set(), []
    for display, (role, slot) in enumerate(POSITION_SLOTS, 1):
        pick = next((x for x in ranked.get(role, []) if x[1] not in taken), None)
        if pick is None:
            raise SystemExit("no candidate left for %s #%d" % (role, slot))
        ktpr, steam, name, club, face = pick
        taken.add(steam)
        rows.append({
            "rank_pos": display, "role": role, "slot": slot,
            "who": facts.names.canon(steam, name),
            "alias": facts.names.alias(steam, name),
            "value_num": round(ktpr, 4),
            "value_text": fmt_value(FMT_KTPR, ktpr),
            "where_text": "%s · %s" % (face, club),
            "match_key": "",
        })
    return rows


# -------------------------------------------------------------------- build

def build(facts):
    weekend = facts.weekend_players()
    per_match = facts.match_players()
    event_halves = max((a["halves"] for a in weekend.values()), default=0)
    match_ids = set(facts.matches)

    types, candidates, skipped = [], [], []

    def emit(d, entries, match_key):
        rows = []
        for e in entries or []:
            rows.append(dict(e))
        rows = eligible(rows, d.get("floor"), event_halves)
        ranked = rank_rows(rows, d["direction"])
        for r in ranked:
            candidates.append({
                "edition": EDITION, "award_slug": d["slug"], "match_key": match_key,
                "rank_pos": r["rank_pos"], "who": r["who"],
                "who_alias": r["alias"], "role": None, "slot": None,
                "value_num": round(r["value"], 4),
                "value_text": fmt_value(d["fmt"], r["value"], r["source"]),
                "where_text": (ratio_context(r["source"], r["where"])
                               if d["fmt"] == FMT_RATIO else r["where"]),
            })
        return len(ranked)

    for order, d in enumerate(definitions(), 1):
        floor = d.get("floor") or {}
        types.append({
            "slug": d["slug"], "scope": d["scope"], "kind": d["kind"],
            "stat_key": d["stat_key"], "direction": d["direction"],
            "default_title": d["default_title"],
            "default_sting": sting_with_source(d),
            "min_share": floor.get("min_share"),
            "min_stat_key": floor.get("min_stat_key"),
            "min_stat": floor.get("min_stat"),
            "sort_order": order,
        })

        if d["scope"] == "weekend" and d["kind"] == "player":
            entries = (weekend_frag_rows(facts, d, weekend) if d["source"] == "frags"
                       else weekend_player_rows(facts, d, weekend))
        elif d["scope"] == "weekend" and d["kind"] == "team":
            entries = team_rows(facts, d, weekend)
        elif d["scope"] == "day":
            entries = day_rows(facts, d)
        elif d["scope"] == "match":
            entries = match_entries(facts, d, per_match, match_ids)
        else:
            entries = None

        if entries is None:
            skipped.append((d["slug"], "no source for stat %r" % d["stat_key"]))
            continue

        if d["scope"] == "match":
            # The weekend card is the best single match ANYONE had, at the empty
            # match key. Writing only per-match rows leaves the awards page with
            # no single-match section, and the API cannot tell that from an award
            # nobody won.
            emit(d, best_per_player(entries, d["direction"]), "")
            for mid in sorted(match_ids):
                emit(d, [e for e in entries if e["match"] == mid], mid)
        else:
            emit(d, entries, "")

    types.append({
        "slug": POSITIONS_SLUG, "scope": "weekend", "kind": "player",
        "stat_key": "ktpr", "direction": "high",
        "default_title": POSITIONS_TITLE, "default_sting": POSITIONS_STING,
        "min_share": None, "min_stat_key": None, "min_stat": None,
        "sort_order": 0,
    })
    for r in positions_rows(facts):
        candidates.append({
            "edition": EDITION, "award_slug": POSITIONS_SLUG,
            "match_key": r["match_key"], "rank_pos": r["rank_pos"], "who": r["who"],
            "who_alias": r["alias"], "role": r["role"], "slot": r["slot"],
            "value_num": r["value_num"], "value_text": r["value_text"],
            "where_text": r["where_text"],
        })

    return {"edition": EDITION, "event_halves": event_halves,
            "types": types, "candidates": candidates, "skipped": skipped,
            "caveats": CAVEATS}


# Awards whose number is defensible but does not match what was published, kept
# in the output so an operator ticking a card sees the same warning the build log
# printed. Each says what moved, not merely that something did.
CAVEATS = [
    ("match-prone-seconds-high",
     "Prone intervals run to the player's next death or next stance change, "
     "whichever comes first, and never across a tick reset. That reproduces the "
     "published single-match list name for name, match for match, with every "
     "figure within a second — see --prone-audit, where the whole field now "
     "differs from the stats board by under two minutes in total. The residual "
     "is sub-second rounding on each interval, so a card can read a second off "
     "what was published."),
    ("weekend-nemesis-pair-high",
     "Counted inside the 56 curated matches only. The published figure was "
     "higher because it counted every frag logged over the weekend, warmup and "
     "side games included."),
]


# --------------------------------------------------------------------- emit

def esc(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("\\", "\\\\").replace("'", "''") + "'"


def to_sql(out):
    lines = [
        "-- Generated by build_awards.py. Types are upserted on their DEFAULTS only;",
        "-- title and sting are operator overrides and are never in this file.",
        "START TRANSACTION;",
    ]
    for t in out["types"]:
        lines.append(
            "INSERT INTO lan_award_types (slug, scope, kind, stat_key, direction, "
            "default_title, default_sting, min_share, min_stat_key, min_stat, sort_order) "
            "VALUES (%s) ON DUPLICATE KEY UPDATE scope=VALUES(scope), kind=VALUES(kind), "
            "stat_key=VALUES(stat_key), direction=VALUES(direction), "
            "default_title=VALUES(default_title), default_sting=VALUES(default_sting), "
            "min_share=VALUES(min_share), min_stat_key=VALUES(min_stat_key), "
            "min_stat=VALUES(min_stat), sort_order=VALUES(sort_order);"
            % ", ".join(esc(t[k]) for k in (
                "slug", "scope", "kind", "stat_key", "direction", "default_title",
                "default_sting", "min_share", "min_stat_key", "min_stat", "sort_order")))
    lines.append("DELETE FROM lan_award_candidates WHERE edition = %s;" % esc(out["edition"]))
    for c in out["candidates"]:
        lines.append(
            "INSERT INTO lan_award_candidates (edition, award_slug, match_key, "
            "rank_pos, who, who_alias, role, slot, value_num, value_text, where_text) "
            "VALUES (%s);" % ", ".join(esc(c[k]) for k in (
                "edition", "award_slug", "match_key", "rank_pos", "who", "who_alias",
                "role", "slot", "value_num", "value_text", "where_text")))
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def print_prone_audit(facts):
    """Recomputed prone against the stats board, per player, worst delta first.

    Exists because the single-match prone award is the one card whose number
    cannot be checked against anything published — the script that produced the
    published figure was never committed — so the only available evidence is
    whether the same rule reproduces the weekend board it also feeds.
    """
    board = {}
    for day in facts.stats["days"].values():
        for p in day["players"]:
            board[p["steam_id"]] = (board.get(p["steam_id"], 0.0)
                                    + (p.get("prone_seconds") or 0))
    mine = Counter()
    for (_mid, steam), (seconds, _events) in facts.prone.items():
        mine[steam] += seconds

    rows = []
    for steam, published in board.items():
        got = mine.get(steam, 0.0)
        delta = got - published
        pct = (100.0 * delta / published) if published else 0.0
        rows.append((delta, pct, steam, got, published))
    rows.sort(key=lambda r: -abs(r[0]))

    agree = [r for r in rows if abs(r[0]) <= 1.0]
    print("prone audit — recomputed against lan-stats.json, worst delta first")
    print("  %-20s %10s %10s %9s %8s  %s"
          % ("player", "recomputed", "board", "delta", "pct", ""))
    for delta, pct, steam, got, published in rows:
        ok = "reconciles" if abs(delta) <= 1.0 else ""
        print("  %-20s %10.1f %10.1f %+9.1f %+7.1f%%  %s"
              % (facts.names.canon(steam, facts.player_name.get(steam))[:20],
                 got, published, delta, pct, ok))
    print("\n  reconciling: %d of %d players; total absolute delta %.1fs"
          % (len(agree), len(rows), sum(abs(r[0]) for r in rows)))

    print("\n  longest credited interval for each player that does not reconcile:")
    for delta, _pct, steam, _got, _published in rows:
        if abs(delta) <= 1.0:
            continue
        intervals = facts.prone_intervals.get(steam) or []
        if not intervals:
            print("    %-20s no credited interval" % facts.names.canon(steam))
            continue
        dur, mid, half, start, end, bound = max(intervals)
        m = facts.matches.get(mid, {})
        print("    %-20s %7.1fs  %s h%d  tick %.1f..%s  bounded by %s"
              % (facts.names.canon(steam, facts.player_name.get(steam))[:20],
                 dur, m.get("map", mid), half, start,
                 ("%.1f" % end) if end is not None else "-", bound))


def print_sources(facts):
    """Both sources side by side, and the weapon buckets the kill split rests on."""
    hl, hud = facts.totals.get("hlstatsx", {}), facts.totals.get("hud", {})
    print("event totals — HLStatsX decides, the HUD column is the one it beat:")
    print("  %-12s %10s %10s %9s" % ("stat", "hlstatsx", "hud", "gap"))
    for k in sorted(hl):
        a, b = hl[k], hud.get(k, 0)
        gap = "%+.1f%%" % (100.0 * (b - a) / a) if a else "-"
        print("  %-12s %10d %10d %9s" % (k, a, b, gap))

    weapons = facts.totals.get("weapons", {})
    buckets = {w: ("grenade" if w in GRENADES else "melee" if w in MELEE
                   else "pistol" if w in PISTOLS else "gun") for w in weapons}
    print("\nweapon buckets (pistols count as guns; only thrown and swung come off).")
    print("`gun` is the residual — read it, because a weapon that belongs in "
          "another bucket lands there silently:")
    for bucket in ("grenade", "melee", "pistol", "gun"):
        names = sorted(w for w, b in buckets.items() if b == bucket)
        print("  %-8s %5d  %s" % (bucket, sum(weapons[w] for w in names),
                                  ", ".join(names)))
    print("  frag total %d against match-record kills %d"
          % (sum(weapons.values()), hl.get("kills", 0)))


def summarise(out):
    by_slug = defaultdict(list)
    for c in out["candidates"]:
        if c["match_key"] == "":
            by_slug[c["award_slug"]].append(c)
    print("edition %s — %d award types, %d candidate rows (%d on weekend cards)"
          % (out["edition"], len(out["types"]), len(out["candidates"]),
             sum(len(v) for v in by_slug.values())))
    print("event halves (fullest attendance): %d" % out["event_halves"])
    empty = [t["slug"] for t in out["types"] if not by_slug.get(t["slug"])]
    for t in out["types"]:
        rows = by_slug.get(t["slug"]) or []
        if not rows:
            continue
        winners = [r for r in rows if r["rank_pos"] == 1]
        head = ", ".join("%s %s" % (w["who"], w["value_text"]) for w in winners[:3])
        if len(winners) > 3:
            head += " (+%d)" % (len(winners) - 3)
        print("  %-28s %-30s %s" % (t["slug"], t["default_title"][:30], head))
    if empty:
        print("\nno candidates: %s" % ", ".join(empty))
    for slug, why in out["skipped"]:
        print("  SKIPPED %-26s %s" % (slug, why))
    for slug, why in out["caveats"]:
        print("\n  CAVEAT %s\n    %s" % (slug, why))


# ------------------------------------------------------------------ anchors

# Published figures, kept as the regression floor. `current` is set only where
# the difference was traced to a source that moved after publication and was
# confirmed against a second one; the published number stays as the record of
# what the community was shown, and `--anchors published` re-checks it.
#
# Values compare as sets within a rank: order inside a tie group is arbitrary,
# and an anchor that fails on it tests the sort, not the figure.
ANCHORS = [
    {"name": "Difficulty: Tourist", "slug": "match-kd-high",
     "published": {1: [("hildebrand?", "5.15 K/D")]},
     "current": {1: [("hildebrand?", "5.14 K/D")]},
     "why": "ktp_match_stats was re-imported after publication — mostly half 1, "
            "over a quarter of the tournament set. The frag log agrees with the "
            "new figures kill for kill, so the repair is the better data. "
            "The kills-deaths pair moved to the context line, so it is no "
            "longer part of the value this anchor compares — 67-13 and 72-14 "
            "are the two readings behind these ratios."},
    {"name": "Sidearm Specialist", "slug": "match-pistol-kills-high",
     "published": {1: [("patten", "9")],
                   2: [("nomistizzle", "6"), ("LaNGoNdd", "6")]},
     "current": {1: [("patten", "9")],
                 2: [("nomistizzle", "6"), ("LaNGoNdd", "6"), ("NoName^", "6")]},
     "why": "the frag log gained a backfilled block spanning the whole event; "
            "NoName^'s sixth pistol kill is one of those rows."},
    {"name": "One Man Army", "slug": "match-kills-high",
     "published": {1: [("sTarK_ x_0", "86")]},
     "where": "saints2_b3e · Sun · v Uncle Rico's Time Machine"},
    {"name": "Own Worst Enemy", "slug": "match-suicides-high",
     "published_tie": (4, 28), "current_tie": (4, 29),
     "why": "the published list used the 55 matches that logged a ktp_match_end; "
            "this uses the 56 curated ones, and Seanality's only two-suicide "
            "match is the one that separates the two sets."},
    {"name": "Welcome to Philly", "slug": "weekend-melee-kills-high",
     "melee_total": 68},
    # The one award with no committed derivation behind its published figure, so
    # this is the check that the recovered rule is the same rule. Ranks 2 and 3
    # land on the second; rank 1 is a second out, as is every remaining
    # disagreement in --prone-audit.
    {"name": "Professional Horizontal", "slug": "match-prone-seconds-high",
     "published": {2: [("jules", "3:23")], 3: [("bR0M", "3:11")]},
     "where": "harrington · Sat · v Price is Right"},
]


def check_anchors(facts, out, use_published):
    rows = defaultdict(list)
    for c in out["candidates"]:
        if c["match_key"] == "":
            rows[c["award_slug"]].append(c)
    failures = []

    def report(name, ok, detail):
        print("  %-4s %-24s %s" % ("PASS" if ok else "FAIL", name, detail))
        if not ok:
            failures.append(name)

    for a in ANCHORS:
        got = rows.get(a["slug"], [])
        note = ""
        expect = a.get("published")
        if not use_published and a.get("current"):
            expect, note = a["current"], "  [re-derived: %s]" % a["why"]
        if expect:
            for rank, want in sorted(expect.items()):
                have = sorted((r["who"], r["value_text"])
                              for r in got if r["rank_pos"] == rank)
                report("%s · rank %d" % (a["name"], rank), have == sorted(want),
                       "%s, expected %s%s" % (have, sorted(want), note))

        if a.get("where"):
            where = next((r["where_text"] for r in got if r["rank_pos"] == 1), None)
            report(a["name"] + " · where", where == a["where"],
                   "%s, expected %s" % (where, a["where"]))

        tie = a.get("published_tie" if use_published else "current_tie") or a.get("published_tie")
        if tie:
            rank, width = tie
            n = sum(1 for r in got if r["rank_pos"] == rank)
            note = "" if use_published or not a.get("current_tie") else "  [re-derived: %s]" % a["why"]
            report(a["name"] + " · tie", n == width,
                   "%d players at rank %d, expected %d%s" % (n, rank, width, note))

        if a.get("melee_total"):
            n = sum(sum(c[w] for w in MELEE) for c in facts.frags.values())
            report(a["name"] + " · event total", n == a["melee_total"],
                   "%d melee kills across the event, expected %d"
                   % (n, a["melee_total"]))

    return failures


# ---------------------------------------------------------------------- main

def apply_to_db(c, out):
    """The only writing path. Types keep their operator title/sting untouched."""
    # Refuse rather than let MySQL report the same thing as a syntax error inside
    # a transaction, which reads like a bad statement rather than a missing
    # migration. `role`/`slot` arrive in a separate file, so both are checked.
    have = {r[0] for r in sql(c, "SHOW TABLES LIKE 'lan_award_%'", db=AWARD_DB)}
    for table in ("lan_award_types", "lan_award_candidates"):
        if table not in have:
            raise SystemExit("%s does not exist in %s — apply migration 0015 there first"
                             % (table, AWARD_DB))
    cols = {r[0] for r in sql(c, "SHOW COLUMNS FROM lan_award_candidates", db=AWARD_DB)}
    if not {"role", "slot"} <= cols:
        raise SystemExit("lan_award_candidates has no role/slot — apply "
                         "migration 0016 first, or the positions panel is lost")

    statements = to_sql(out)
    cmd = "mysql %s 2>&1" % AWARD_DB
    stdin, stdout, _ = c.exec_command(cmd, timeout=900)
    stdin.write(statements)
    stdin.channel.shutdown_write()
    err = stdout.read().decode("utf-8", "replace").strip()
    if err:
        raise SystemExit("apply failed: " + err[:600])
    print("applied %d types and %d candidates to %s"
          % (len(out["types"]), len(out["candidates"]), DB))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="write to MySQL; without it nothing leaves this directory")
    ap.add_argument("--check-anchors", action="store_true",
                    help="verify the published regression figures, non-zero on drift")
    ap.add_argument("--anchors", choices=("current", "published"), default="current",
                    help="'published' re-checks the figures as originally released")
    ap.add_argument("--sources", action="store_true",
                    help="print HLStatsX against the HUD for every stat both hold")
    ap.add_argument("--prone-audit", action="store_true",
                    help="recomputed prone against the stats board, per player")
    args = ap.parse_args()

    facts = Facts()
    c = connect()
    try:
        facts.fetch(c)
        out = build(facts)
        if args.apply:
            apply_to_db(c, out)
    finally:
        c.close()

    if args.prone_audit:
        print_prone_audit(facts)
        return 0

    if args.sources:
        print_sources(facts)
        return 0

    if args.check_anchors:
        print("anchors (%s):" % args.anchors)
        failures = check_anchors(facts, out, args.anchors == "published")
        if failures:
            print("\n%d anchor(s) failed: %s" % (len(failures), ", ".join(failures)))
            return 1
        print("\nall anchors hold")
        return 0

    with open(os.path.join(HERE, "awards_candidates.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(HERE, "awards_candidates.sql"), "w", encoding="utf-8") as fh:
        fh.write(to_sql(out))
    summarise(out)
    if not args.apply:
        print("\ndry run — wrote awards_candidates.json and awards_candidates.sql")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
