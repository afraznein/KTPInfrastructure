#!/usr/bin/env python3
"""Forensic correlation: HLTV viewer IPs against known player IPs.

Answers "who might have been watching, and how much should I believe it" for a
time window. It reports CO-OCCURRENCE, never identification -- read the caveat
block it prints, it is part of the output on purpose.

Why the hedging is structural and not politeness. Measured on this database:
  * Most IPs map to exactly one player, so most hits are informative.
  * But a handful carry 36-48 distinct players (VPN / shared / venue NAT), and
    one infrastructure IP alone accounts for 13,885 connects from a single bot.
  * Players average 5.3 distinct IPs each (max 69), so a NON-match proves
    nothing at all -- a viewer on mobile or a VPN simply will not join.
So: a match on a single-occupant IP is real evidence; a match on a shared IP is
noise wearing the same shape. The tool labels which one you are looking at
rather than leaving that to the reader.

ports_swept exists because the upstream firewall rule is a filter, not a proof.
A monitoring service that polls every HLTV port looks like a viewer to any
per-flow byte threshold once its conntrack entry has accumulated; it does not
look like a viewer once you count how many DIFFERENT proxies it touched in the
same hour. A human watches one. Treat a high count as "this is infrastructure",
not as a person.

Aggregates live in derived tables keyed on IP, NOT correlated subqueries in the
SELECT: those run after the join fan-out, so ~1,900 joined rows each triggered a
45k-row scan and the query never returned. Same answer, bounded work.
The join is direct equality -- ipAddress carries no port (0 of 45,076 rows).
NOTE hlstats_Events_Connects has no index on ipAddress, so this is O(connects)
by design; it is a vendor table and an added index could be dropped by an
HLStatsX schema upgrade.
"""
import argparse
import ipaddress
import subprocess
import sys

ROW_LIMIT = 500

# ktp_ac_sessions is utf8mb4_0900_ai_ci while this table and hlstats_* are
# utf8mb4_unicode_ci -- joining THAT needs an explicit COLLATE or it errors 1267.
SQL = """
WITH matches AS (
  SELECT h.id AS hit_id, h.hit_time, h.src_ip, h.dst_port,
         p.lastName AS candidate, u.uniqueId AS steam_id, c.eventTime,
         ROW_NUMBER() OVER (
           PARTITION BY h.id, c.playerId
           ORDER BY ABS(TIMESTAMPDIFF(SECOND, h.hit_time, c.eventTime))
         ) AS rn
  FROM ktp_hltv_viewer_hits h
  LEFT JOIN hlstats_Events_Connects c
         ON c.ipAddress = h.src_ip
        AND c.eventTime BETWEEN h.hit_time - INTERVAL 24 HOUR
                            AND h.hit_time + INTERVAL 24 HOUR
  LEFT JOIN hlstats_Players p         ON p.playerId = c.playerId
  LEFT JOIN hlstats_PlayerUniqueIds u ON u.playerId = c.playerId
  WHERE {where}
)
SELECT m.hit_time, m.src_ip, m.dst_port,
       COALESCE(s.players_behind_ip, 0) AS players_behind_ip,
       (SELECT COUNT(DISTINCT h2.dst_port) FROM ktp_hltv_viewer_hits h2
         WHERE h2.src_ip = m.src_ip
           AND h2.hit_time BETWEEN m.hit_time - INTERVAL 1 HOUR
                               AND m.hit_time + INTERVAL 1 HOUR) AS ports_swept,
       COALESCE(m.candidate, '(no player on this IP within +/-24h)') AS candidate,
       COALESCE(m.steam_id, '') AS steam_id,
       m.eventTime AS nearest_connect
FROM matches m
LEFT JOIN (SELECT ipAddress AS ip, COUNT(DISTINCT playerId) AS players_behind_ip
             FROM hlstats_Events_Connects GROUP BY ipAddress) s
       ON s.ip = m.src_ip
WHERE m.rn = 1
ORDER BY m.hit_time DESC, candidate
LIMIT {limit};
"""

CAVEAT = """\
==============================================================================
READ THIS BEFORE ACTING ON A ROW ABOVE
==============================================================================
players_behind_ip == 1  -> the IP has only ever carried this one player.
                           Real evidence of co-occurrence.
players_behind_ip >  1  -> shared IP (VPN, household, venue NAT, CGNAT).
                           NOT an identification. One IP in this DB
                           carries 48 distinct players.
ports_swept >  1        -> this source touched several proxies in the same
                           hour. A person watches ONE. Treat as monitoring
                           infrastructure, not a viewer, regardless of the
                           players_behind_ip value.
no rows for a person    -> proves NOTHING. Players average 5.3 IPs each,
                           and any VPN or phone hotspot breaks the join.
nearest_connect         -> closest game-server connect from the same IP within
                           +/-24h. Proximity is evidence; distance is not proof
                           of absence.
A match is co-occurrence, not intent, and not an accusation."""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--ip")
    a = ap.parse_args()

    # Validate rather than sanitise. An unrecognised argument that silently
    # returns zero rows is a false-negative generator in a forensic tool: the
    # output is indistinguishable from "nobody watched".
    if a.days <= 0:
        ap.error("--days must be positive (a negative interval yields a future "
                 "window, which is always empty)")
    where = "h.hit_time >= NOW() - INTERVAL %d DAY" % a.days
    if a.ip:
        try:
            ip = ipaddress.ip_address(a.ip)
        except ValueError:
            ap.error("--ip %r is not a valid IP address" % a.ip)
        where += " AND h.src_ip = '%s'" % ip

    sql = SQL.format(where=where, limit=ROW_LIMIT)
    out = subprocess.run(["mysql", "-B", "hlstatsx", "-e", sql],
                         capture_output=True, text=True)
    if out.returncode != 0:
        sys.stderr.write(out.stderr)
        return 1

    lines = out.stdout.strip().split("\n")
    if len(lines) <= 1:
        scope = "for %s " % a.ip if a.ip else ""
        print("No HLTV viewer hits %sin the last %d day(s). That is the expected "
              "state most days -- but see ktp-hltv-viewer-ingest.log to confirm "
              "the pipeline is actually running." % (scope, a.days))
        return 0

    print(out.stdout)
    if len(lines) - 1 >= ROW_LIMIT:
        print("WARNING: output truncated at %d rows (ORDER BY hit_time DESC, so "
              "the OLDEST rows in the window were dropped). Narrow --days."
              % ROW_LIMIT)
    print(CAVEAT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
