#!/usr/bin/env python3
"""Composite score v2: normalized damage, flag captures, deaths-as-efficiency.

Ad-hoc exploration script (not part of the test suite). Combines the
persisted match-1 fixture DB with the raw game log (flag captures aren't
in the DB yet -- confirmed empty ktp_match_stats/ktp_match_players in this
fixture -- so they're parsed straight from the log for this draft).

Usage (inside ktp-lane-b:dev, tests/ and scripts/ mounted):
    scripts/composite_v2.py <fixture.sql> <raw_log_path>
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.e2e_stats.ephemeral_mysql import EphemeralMysql  # noqa: E402


LOG_PREFIX = r'^L \d\d/\d\d/\d{4} - \d\d:\d\d:\d\d:\s*'
CAP_LINE = re.compile(
    LOG_PREFIX + r'"(?P<name>[^<]+)<\d+><[^>]*><(?P<team>Axis|Allies)>" '
    r'triggered a "dod_capture_area" - "(?P<flag>[^"]+)"'
)
TEAM_CAP_LINE = re.compile(
    LOG_PREFIX + r'Team "(?P<team>Axis|Allies)" triggered a "dod_capture_area" - "(?P<flag>[^"]+)"'
)
HALF_END = re.compile(r"KTP_HALF_END")
# The bare top-level marker only -- "[KTPMatchHandler.amxx] KTP_MATCH_START
# ... [test-mode mirror]" is a second, later line for the SAME half
# transition, and matching it too would double-increment the half counter.
MATCH_START = re.compile(LOG_PREFIX + r"KTP_MATCH_START")


def parse_captures(log_text: str):
    """Returns (half_boundaries, team_cap_counts[half][team], player_caps[half][name][flag])."""
    lines = log_text.splitlines()
    half = 1
    team_counts = defaultdict(lambda: defaultdict(int))
    flag_counts = defaultdict(int)
    player_caps = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    seen_first_start = False
    for line in lines:
        if MATCH_START.search(line):
            if seen_first_start:
                half += 1
            seen_first_start = True
            continue
        m = TEAM_CAP_LINE.match(line)
        if m:
            team_counts[half][m.group("team")] += 1
            flag_counts[m.group("flag")] += 1
            continue
        m = CAP_LINE.match(line)
        if m:
            player_caps[half][m.group("name")][m.group("flag")] += 1
    return team_counts, flag_counts, player_caps


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
    log_path = Path(sys.argv[2])
    if log_path.suffix == ".gz":
        import gzip
        log_text = gzip.decompress(log_path.read_bytes()).decode("utf-8", errors="replace")
    else:
        log_text = log_path.read_text(encoding="utf-8", errors="replace")

    team_counts, flag_counts, player_caps = parse_captures(log_text)
    winners = half_winners(team_counts)
    fweights = flag_weights(flag_counts)

    print("=== capture events by half/team ===")
    for half in sorted(team_counts):
        print(f"  half {half}: {dict(team_counts[half])}  winner={winners[half] or 'TIE'}")
    print("=== flag weights (inverse frequency, mean=1.0 across CONTESTED flags only) ===")
    for f, w in sorted(fweights.items()):
        print(f"  {f}: captured {flag_counts[f]}x -> weight {w}")
    if len(fweights) < 3:
        print("  NOTE: only", len(fweights), "of 5 flags were ever contested this match "
              "(others are presumably home flags, pre-owned, never captured). With only "
              f"{len(fweights)} data points this weighting is not a confident signal -- "
              "flat/tied weights here reflect the data, not a claim that these flags are "
              "equally important on the map. Real differentiation needs either map-topology "
              "input or more matches.")
    print()

    with EphemeralMysql.start(keep=False) as db:
        argv = [db.client, "--no-defaults", f"--socket={db.socket_path}",
                "-u", "root", db.database]
        with fixture.open("rb") as fh:
            subprocess.run(argv, stdin=fh, check=True)

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
    # flag_captures: parsed from the raw log, each capture credited in full
    # to every participating player (a 2-person cap is not split -- both
    # contributed presence), weighted by that flag's inverse-frequency value.
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
