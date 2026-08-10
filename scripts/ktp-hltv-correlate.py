#!/usr/bin/env python3
"""Forensic correlation: HLTV connection attempts against known player IPs.

Answers "who might have been watching, and how much should I believe it" for a
time window. It reports CO-OCCURRENCE, never identification -- the caveat block
it prints is part of the output on purpose.

THIS is where automation gets separated from people, deliberately. The firewall
captures broadly and does not judge. Two earlier designs tried to judge in the
kernel and both were structurally wrong in ways only production exposed: one
matched connbytes per-flow-lifetime (a poller reusing a 4-tuple accumulates past
any packet threshold and then matches forever), the other matched packet length
on the inbound hook (viewer->proxy traffic is command/ack, measured max 25 bytes;
the large packets go the other way and never cross that chain). Doing it here
means the rule can be re-tuned with a query instead of a kernel change nobody
can test.

Signals, none of which is by itself a verdict:
  players_behind_ip  how many distinct players have ever connected from this IP.
  ports_swept        distinct proxy ports this source touched within +/-1h.
                     A person watches one; automation sweeps the range.
  days_active        distinct days this source appears at all. A poller is
                     present every day; a one-off visit is not.
  nearest_connect    closest game-server connect from the same IP within +/-24h.

Aggregates for the 45k-row hlstats_Events_Connects live in a derived table keyed
on IP, NOT correlated subqueries in the SELECT -- those run after the join
fan-out, so ~1,900 joined rows each triggered a full scan and the query never
returned. The two subqueries that DO remain scan only ktp_hltv_connections,
which is small and carries idx_ip + idx_time; that exemption is deliberate.
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
  FROM ktp_hltv_connections h
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
       (SELECT COUNT(DISTINCT h2.dst_port) FROM ktp_hltv_connections h2
         WHERE h2.src_ip = m.src_ip
           AND h2.hit_time BETWEEN m.hit_time - INTERVAL 1 HOUR
                               AND m.hit_time + INTERVAL 1 HOUR) AS ports_swept,
       (SELECT COUNT(DISTINCT DATE(h3.hit_time)) FROM ktp_hltv_connections h3
         WHERE h3.src_ip = m.src_ip) AS days_active,
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
These are CONNECTION ATTEMPTS. The firewall captures everything reaching the
proxies and does not decide what is a person -- these columns are how you do
that, and none of them is a verdict on its own.

ports_swept  > 1  suggests automation: a person watches one proxy, a scanner
                  sweeps the range. Window is +/-1h around the row. Weigh it
                  against the other columns -- someone watching two matches in
                  two hours also scores 2.
days_active  high suggests automation: pollers are present every day, a one-off
                  visit is not.
players_behind_ip
             == 1 the IP has only ever carried this one player. The strongest
                  co-occurrence signal available here.
             >  1 shared IP (VPN, household, venue NAT, CGNAT). NOT an
                  identification. One IP in this DB carries 48 distinct players.
nearest_connect   closest game-server connect from that IP within +/-24h.
                  Proximity is evidence; distance is not proof of absence.
no rows for a person
                  proves NOTHING. Players average 5.3 IPs each (max 69), and any
                  VPN or phone hotspot breaks the join silently.

A match is co-occurrence, not intent, and not an accusation."""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--ip")
    a = ap.parse_args()

    # Validate rather than sanitise. An unrecognised argument that silently
    # returns zero rows is a false-negative generator in a forensic tool: the
    # output is indistinguishable from "nobody connected".
    if a.days <= 0:
        ap.error("--days must be positive (a negative interval yields a future "
                 "window, which is always empty)")
    where = "h.hit_time >= NOW() - INTERVAL %d DAY" % a.days
    if a.ip:
        try:
            ip = ipaddress.ip_address(a.ip)
        except ValueError:
            ap.error("--ip %r is not a valid IP address" % a.ip)
        # IPv4 only, and rejected rather than accepted-and-empty: src_ip is
        # populated solely from an IPv4 regex fed by an IPv4-only firewall rule,
        # so a v6 argument can never match and would print the same reassuring
        # "no hits" as a genuine quiet window.
        if ip.version != 4:
            ap.error("--ip %s is IPv6; this pipeline only ever records IPv4 "
                     "(the rule lives in before.rules, not before6.rules)" % ip)
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
        print("No HLTV connections %sin the last %d day(s). Confirm the pipeline "
              "is actually running before reading that as 'nobody connected' -- "
              "see /var/log/ktp-hltv-connection-ingest.log and the rule counter in "
              "`iptables -L ufw-before-input -n -v -x`." % (scope, a.days))
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
