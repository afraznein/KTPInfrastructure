#!/usr/bin/env python3
"""Load a persisted fixture dump and print candidate KTPR stat values.

Ad-hoc exploration tool, not part of the test suite: loads a mysqldump
produced by replay_and_dump.py / lane_b_match_series.py into a throwaway
mysqld and runs a handful of derived-stat queries against it, per the
scoring-idea catalog (K:D, headshot rate, damage efficiency, break/assist
contribution, last-flag-defense weighting).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.e2e_stats.ephemeral_mysql import EphemeralMysql  # noqa: E402


def main() -> int:
    dump = Path(sys.argv[1])
    with EphemeralMysql.start(keep=False) as db:
        argv = [db.client, "--no-defaults", f"--socket={db.socket_path}",
                "-u", "root", db.database]
        with dump.open("rb") as fh:
            r = subprocess.run(argv, stdin=fh, stderr=subprocess.PIPE)
        if r.returncode != 0:
            raise SystemExit(f"load failed: {r.stderr.decode(errors='replace')}")
        print(f"loaded {dump}\n")

        queries = {
            "per-player core": """
                SELECT pn.name, pn.kills, pn.deaths, pn.suicides,
                  ROUND(pn.kills / GREATEST(pn.deaths,1), 2) AS kd
                FROM hlstats_PlayerNames pn ORDER BY pn.kills DESC
            """,
            "assists per player": """
                SELECT pn.name, COUNT(*) AS assists
                FROM hlstats_Events_PlayerPlayerActions ppa
                JOIN hlstats_PlayerNames pn ON pn.playerId = ppa.playerId
                GROUP BY pn.name ORDER BY assists DESC
            """,
            "damage dealt/taken (capped) per player": """
                SELECT pn.name,
                  COALESCE(SUM(CASE WHEN de.attacker_id=pn.playerId THEN de.damage_capped END),0) AS dmg_dealt,
                  COALESCE(SUM(CASE WHEN de.victim_id=pn.playerId THEN de.damage_capped END),0) AS dmg_taken
                FROM hlstats_PlayerNames pn
                LEFT JOIN ktp_damage_events de
                  ON de.attacker_id=pn.playerId OR de.victim_id=pn.playerId
                GROUP BY pn.name ORDER BY dmg_dealt DESC
            """,
            "headshot rate per player": """
                SELECT pn.name, SUM(f.headshot) AS hs, COUNT(*) AS kills,
                  ROUND(100*SUM(f.headshot)/COUNT(*),1) AS hs_pct
                FROM hlstats_Events_Frags f
                JOIN hlstats_PlayerNames pn ON pn.playerId=f.killerId
                GROUP BY pn.name HAVING kills>0 ORDER BY hs_pct DESC
            """,
            "last-flag-defense kills per player": """
                SELECT pn.name, SUM(f.is_last_flag_defense) AS lfd_kills
                FROM hlstats_Events_Frags f
                JOIN hlstats_PlayerNames pn ON pn.playerId=f.killerId
                GROUP BY pn.name HAVING lfd_kills>0 ORDER BY lfd_kills DESC
            """,
            "cap breaks per player": """
                SELECT pn.name, pa.contester_count, pa.time_remaining, pa.is_capout
                FROM hlstats_Events_PlayerActions pa
                JOIN hlstats_PlayerNames pn ON pn.playerId=pa.playerId
            """,
            "candidate composite score (draft weights)": """
                -- draft only: kills(1) + assists(0.5) + headshot bonus(0.25 each)
                -- + last_flag_defense bonus(1 each) + cap_break bonus(2 each)
                -- - deaths(0.5) ; damage NOT yet weighted (needs team-share normalization)
                SELECT pn.name,
                  pn.kills, pn.deaths,
                  COALESCE(a.assists,0) AS assists,
                  COALESCE(hs.hs,0) AS headshots,
                  COALESCE(lfd.lfd,0) AS lfd_kills,
                  COALESCE(cb.breaks,0) AS cap_breaks,
                  ROUND(
                    pn.kills*1.0 + COALESCE(a.assists,0)*0.5
                    + COALESCE(hs.hs,0)*0.25 + COALESCE(lfd.lfd,0)*1.0
                    + COALESCE(cb.breaks,0)*2.0 - pn.deaths*0.5
                  , 2) AS draft_score
                FROM hlstats_PlayerNames pn
                LEFT JOIN (SELECT playerId, COUNT(*) assists FROM hlstats_Events_PlayerPlayerActions GROUP BY playerId) a
                  ON a.playerId=pn.playerId
                LEFT JOIN (SELECT killerId, SUM(headshot) hs FROM hlstats_Events_Frags GROUP BY killerId) hs
                  ON hs.killerId=pn.playerId
                LEFT JOIN (SELECT killerId, SUM(is_last_flag_defense) lfd FROM hlstats_Events_Frags GROUP BY killerId) lfd
                  ON lfd.killerId=pn.playerId
                LEFT JOIN (SELECT playerId, COUNT(*) breaks FROM hlstats_Events_PlayerActions GROUP BY playerId) cb
                  ON cb.playerId=pn.playerId
                ORDER BY draft_score DESC
            """,
        }
        for title, q in queries.items():
            print(f"=== {title} ===")
            r = db.sql(q)
            print(r)
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
