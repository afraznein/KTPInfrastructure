#!/usr/bin/env python3
"""Composite score v2: normalized damage, flag captures, deaths-as-efficiency.

Ad-hoc exploration script (not part of the test suite). Combines the
persisted fixture DB with itself -- flag captures now come straight from
ktp_flag_captures (KTPHLStatsX migrate_009_flag_captures.sql,
doEvent_KTPFlagCapture), not from a separate raw-log regex parse. That
retires two real bugs this script used to carry on its own: double-counting
half boundaries (KTP_MATCH_START appearing twice per transition) and a
colon-anchoring regex bug, both artifacts of reimplementing parsing the
daemon already does correctly and tags with match_id/half itself.

A fixture captured before migrate_009 existed (e.g. the original match-1
recovery) has no ktp_flag_captures table at all -- CREATE_FLAG_CAPTURES
below is applied right after loading the fixture, idempotently, so this
script runs against either an old or a current fixture; it just reports
zero captures against an old one rather than erroring.

Usage (inside ktp-lane-b:dev, tests/ and scripts/ mounted):
    scripts/composite_v2.py <fixture.sql>
"""

from __future__ import annotations

import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.e2e_stats.ephemeral_mysql import EphemeralMysql  # noqa: E402


# Mirrors KTPHLStatsX's sql/migrate_009_flag_captures.sql -- not read from
# that file directly to keep this exploration script self-contained and
# runnable from just this one repo. Keep the two in sync by hand if the
# schema changes; CREATE TABLE IF NOT EXISTS makes an out-of-date copy here
# merely redundant against a fixture that already has the real table, not
# wrong.
CREATE_FLAG_CAPTURES = """
CREATE TABLE IF NOT EXISTS ktp_flag_captures (
    id INT AUTO_INCREMENT,
    server_id INT UNSIGNED NOT NULL,
    match_id VARCHAR(64) DEFAULT NULL,
    half TINYINT NOT NULL DEFAULT 0,
    player_id INT NOT NULL,
    team VARCHAR(16) DEFAULT NULL,
    flag_name VARCHAR(64) DEFAULT NULL,
    event_time DATETIME NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_server (server_id),
    KEY idx_match (match_id),
    KEY idx_player (player_id),
    KEY idx_event_time (event_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def query_captures(db):
    """Returns (team_cap_counts[half][team], flag_counts[flag], player_caps[half][name][flag]).

    A single capture completion can emit multiple ktp_flag_captures rows --
    one per capping player, DoD 1.3's own multi-capper mechanic -- so the
    two event-level counts (team_counts, flag_counts) dedup by distinct
    (team-or-flag, event_time) rather than counting rows, matching what the
    old TEAM_CAP_LINE regex counted (one hit per completion, not per
    capper). player_caps is deliberately row-level: each participating
    player earns their own credit for a shared capture.
    """
    team_counts = defaultdict(lambda: defaultdict(int))
    flag_counts = defaultdict(int)
    player_caps = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

    team_rows = db.sql("""
        SELECT half, team, COUNT(DISTINCT CONCAT(flag_name, '|', event_time)) AS n
        FROM ktp_flag_captures
        WHERE team IS NOT NULL AND flag_name IS NOT NULL
        GROUP BY half, team
    """)
    for half, team, n in _tsv_rows(team_rows):
        team_counts[int(half)][team] = int(n)

    flag_rows = db.sql("""
        SELECT flag_name, COUNT(DISTINCT CONCAT(team, '|', event_time)) AS n
        FROM ktp_flag_captures
        WHERE flag_name IS NOT NULL
        GROUP BY flag_name
    """)
    for flag, n in _tsv_rows(flag_rows):
        flag_counts[flag] = int(n)

    player_rows = db.sql("""
        SELECT pn.name, fc.half, fc.flag_name, COUNT(*) AS n
        FROM ktp_flag_captures fc
        JOIN hlstats_PlayerNames pn ON pn.playerId = fc.player_id
        WHERE fc.flag_name IS NOT NULL
        GROUP BY pn.name, fc.half, fc.flag_name
    """)
    for name, half, flag, n in _tsv_rows(player_rows):
        player_caps[int(half)][name][flag] = int(n)

    return team_counts, flag_counts, player_caps


def _tsv_rows(s: str):
    if not s.strip():
        return
    lines = s.strip("\n").split("\n")
    for line in lines[1:]:  # skip header
        yield line.split("\t")


def half_winners(team_counts) -> dict[int, str | None]:
    winners = {}
    for half, counts in team_counts.items():
        a, l = counts.get("Axis", 0), counts.get("Allies", 0)
        if a > l:
            winners[half] = "Axis"
        elif l > a:
            winners[half] = "Allies"
        else:
            winners[half] = None  # tie -- neutral multiplier
    return winners


def flag_weights(flag_counts: dict[str, int]) -> dict[str, float]:
    """Inverse-frequency weight, mean 1.0 across flags that were ever contested.

    Flags never captured in this match (home flags, presumably start
    pre-owned) get no weight entry -- there's no capture event to weight.
    """
    if not flag_counts:
        return {}
    total = sum(flag_counts.values())
    n = len(flag_counts)
    avg = total / n
    return {f: round(avg / c, 3) for f, c in flag_counts.items()}


def main() -> int:
    fixture = Path(sys.argv[1])

    with EphemeralMysql.start(keep=False) as db:
        argv = [db.client, "--no-defaults", f"--socket={db.socket_path}",
                "-u", "root", db.database]
        with fixture.open("rb") as fh:
            subprocess.run(argv, stdin=fh, check=True)

        # Idempotent against a fixture that already has the real table --
        # only matters for a pre-migrate_009 fixture, where this creates it
        # empty so the queries below return zero rows instead of erroring.
        db.sql(CREATE_FLAG_CAPTURES)

        team_counts, flag_counts, player_caps = query_captures(db)
        winners = half_winners(team_counts)
        fweights = flag_weights(flag_counts)

        print("=== capture events by half/team ===")
        for half in sorted(team_counts):
            print(f"  half {half}: {dict(team_counts[half])}  winner={winners[half] or 'TIE'}")
        print("=== flag weights (inverse frequency, mean=1.0 across CONTESTED flags only) ===")
        for f, w in sorted(fweights.items()):
            print(f"  {f}: captured {flag_counts[f]}x -> weight {w}")
        if 0 < len(fweights) < 3:
            print("  NOTE: only", len(fweights), "of 5 flags were ever contested this match "
                  "(others are presumably home flags, pre-owned, never captured). With only "
                  f"{len(fweights)} data points this weighting is not a confident signal -- "
                  "flat/tied weights here reflect the data, not a claim that these flags are "
                  "equally important on the map. Real differentiation needs either map-topology "
                  "input or more matches.")
        elif not fweights:
            print("  NOTE: zero captures found -- either this fixture predates "
                  "migrate_009_flag_captures.sql (captures weren't recorded when it was "
                  "taken) or the match genuinely had none.")
        print()

        # Per-player, per-half team (majority vote of killerRole this half --
        # ktp_match_players/ktp_match_stats are both empty in this fixture,
        # so there's no stored team column to read from instead).
        team_by_half = db.sql("""
            SELECT pn.name, f.half,
              SUM(f.killerRole LIKE '%axis%') AS axis_kills,
              SUM(f.killerRole LIKE '%allied%') AS allied_kills
            FROM hlstats_Events_Frags f
            JOIN hlstats_PlayerNames pn ON pn.playerId = f.killerId
            GROUP BY pn.name, f.half
        """)

        core = db.sql("""
            SELECT pn.playerId, pn.name, pn.kills, pn.deaths
            FROM hlstats_PlayerNames pn ORDER BY pn.name
        """)
        assists = db.sql("""
            SELECT pn.name, COUNT(*) n FROM hlstats_Events_PlayerPlayerActions ppa
            JOIN hlstats_PlayerNames pn ON pn.playerId=ppa.playerId GROUP BY pn.name
        """)
        headshots = db.sql("""
            SELECT pn.name, SUM(f.headshot) n FROM hlstats_Events_Frags f
            JOIN hlstats_PlayerNames pn ON pn.playerId=f.killerId GROUP BY pn.name
        """)
        lfd = db.sql("""
            SELECT pn.name, SUM(f.is_last_flag_defense) n FROM hlstats_Events_Frags f
            JOIN hlstats_PlayerNames pn ON pn.playerId=f.killerId GROUP BY pn.name
        """)
        breaks = db.sql("""
            SELECT pn.name, COUNT(*) n FROM hlstats_Events_PlayerActions pa
            JOIN hlstats_PlayerNames pn ON pn.playerId=pa.playerId GROUP BY pn.name
        """)
        # Per-player, per-half team + damage dealt, for win/loss normalization.
        dmg_by_half = db.sql("""
            SELECT pn.name, de.half, pn.playerId,
              SUM(de.damage_capped) dmg,
              (SELECT killerRole FROM hlstats_Events_Frags f2
               WHERE f2.killerId = pn.playerId AND f2.half = de.half
               GROUP BY killerRole ORDER BY COUNT(*) DESC LIMIT 1) AS role
            FROM ktp_damage_events de
            JOIN hlstats_PlayerNames pn ON pn.playerId = de.attacker_id
            GROUP BY pn.name, de.half, pn.playerId
        """)

    def tsv(s):
        rows = [r.split("\t") for r in s.strip("\n").split("\n")]
        return rows[0], rows[1:]

    _, core_rows = tsv(core)
    assist_map = {r[0]: int(r[1]) for r in tsv(assists)[1]} if assists.strip() else {}
    hs_map = {r[0]: int(r[1] or 0) for r in tsv(headshots)[1]} if headshots.strip() else {}
    lfd_map = {r[0]: int(r[1] or 0) for r in tsv(lfd)[1]} if lfd.strip() else {}
    break_map = {r[0]: int(r[1]) for r in tsv(breaks)[1]} if breaks.strip() else {}

    dmg_rows = tsv(dmg_by_half)[1] if dmg_by_half.strip() else []
    # name -> {half: (dmg, role)}
    dmg_map: dict[str, dict[int, tuple[int, str]]] = defaultdict(dict)
    for name, half, _pid, dmg, role in dmg_rows:
        dmg_map[name][int(half)] = (int(dmg), role)

    def role_to_team(role: str) -> str | None:
        if not role:
            return None
        r = role.lower()
        if "axis" in r:
            return "Axis"
        if "allied" in r:
            return "Allies"
        return None

    # --- Composite v2 ---
    # normalized_damage: capped damage from ktp_damage_events, scaled by a
    # win/loss multiplier per half (1.2 if that half's team won, 0.8 if lost,
    # 1.0 on a tie or indeterminate team).
    # flag_captures: read from ktp_flag_captures, each capture credited in
    # full to every participating player (a 2-person cap is not split --
    # both contributed presence), weighted by that flag's inverse-frequency
    # value.
    # efficiency_bonus: kills/(deaths+1) -- additive, never subtracts,
    # rewards a high kill:death ratio as a separate differentiator from
    # raw kill volume. Deaths otherwise play NO role in the score.
    W = dict(kill=1.0, assist=0.5, headshot=0.25, lfd=1.0, cap_break=2.0,
             dmg_per_100=0.5, flag_cap=1.5, efficiency=3.0)

    results = []
    for pid, name, kills, deaths in core_rows:
        kills, deaths = int(kills), int(deaths)

        norm_dmg = 0.0
        for half, (dmg, role) in dmg_map.get(name, {}).items():
            team = role_to_team(role)
            winner = winners.get(half)
            mult = 1.0
            if team and winner:
                mult = 1.2 if team == winner else 0.8
            norm_dmg += dmg * mult

        flag_cap_score = 0.0
        flag_cap_count = 0
        for half, flags in player_caps.items():
            for flag, n in flags.get(name, {}).items():
                w = fweights.get(flag, 1.0)
                flag_cap_score += n * w
                flag_cap_count += n

        efficiency = kills / (deaths + 1)

        score = (
            kills * W["kill"]
            + assist_map.get(name, 0) * W["assist"]
            + hs_map.get(name, 0) * W["headshot"]
            + lfd_map.get(name, 0) * W["lfd"]
            + break_map.get(name, 0) * W["cap_break"]
            + (norm_dmg / 100.0) * W["dmg_per_100"]
            + flag_cap_score * W["flag_cap"]
            + efficiency * W["efficiency"]
        )
        results.append({
            "name": name, "kills": kills, "deaths": deaths,
            "assists": assist_map.get(name, 0), "headshots": hs_map.get(name, 0),
            "lfd": lfd_map.get(name, 0), "breaks": break_map.get(name, 0),
            "flag_caps": flag_cap_count, "norm_dmg": round(norm_dmg, 1),
            "efficiency": round(efficiency, 2), "score": round(score, 2),
        })

    results.sort(key=lambda r: -r["score"])
    hdr = ["name", "kills", "deaths", "assists", "headshots", "lfd", "breaks",
           "flag_caps", "norm_dmg", "efficiency", "score"]
    print("\t".join(hdr))
    for r in results:
        print("\t".join(str(r[h]) for h in hdr))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
