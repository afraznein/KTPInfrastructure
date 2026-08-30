#!/usr/bin/env python3
"""Watch the HLStatsX ingest path for the failures that are otherwise silent.

Written after the Philadelphia 2026 LAN, where three separate defects each cost
real data and none of them raised anything at the time:

  * 982 kill events never reached the daemon. GoldSrc `logaddress` is
    fire-and-forget UDP with no retry, so there is nothing to detect per-event --
    but the kernel counts the drops, and that counter was never read.
  * Every objective capture of the weekend was parsed and discarded because
    `hlstats_Actions` was unseeded. The daemon now warns; this reads that warning.
  * The Grand Final's second half produced events but no summary rows, because a
    plugin bug emitted an empty match id. Nothing compared the two.

Each check below is one of those, turned into something that fires on the day.
Exits non-zero when anything is found, so a systemd OnFailure can carry it to
Discord through the existing ktp-systemd-alert wiring.

Runs on the data server as root; MySQL is reached over the local socket so this
file carries no credentials (the repository is public).

    hlstatsx-ingest-monitor.py [--db hlstatsx] [--since 90]
                               [--logs /path/to/dod/logs] [--quiet]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

STATE = "/var/lib/ktp/hlstatsx-ingest-monitor.json"
SNMP = "/proc/net/snmp"
# The schema is two families with different collations: the upstream
# hlstats_Events_* tables are utf8mb4_unicode_ci, the KTP ktp_* tables are
# utf8mb4_0900_ai_ci. Joining match_id across them raises "Illegal mix of
# collations" and the query returns nothing at all -- which reads exactly like
# a clean result. Every join below pins the collation explicitly.
COLL = "COLLATE utf8mb4_unicode_ci"
# A half that records under this share of its own first half is not a quiet half,
# it is a lossy one. Real halves at the LAN sat at 0.83 and above; the defective
# ones came in at 0.44, 0.59 and 0.63.
HALF_RATIO_FLOOR = 0.70
# ...but only for halves that actually ran. A half far shorter than a real one is
# an abandoned or restarted match, not a lossy ingest, and comparing it on kills
# pages every time. Measured on the 2026-08-28 false alarm: h1 ran 1214s for 311
# kills, h2 ran 71s for 9, and a fresh match started 76s later. The two healthy
# matches in the same window both ran h2 for ~1214s and did not fire.
#
# A rate comparison alone does NOT rescue that case -- 0.256 k/s against 0.127
# k/s is half, not proportionate, because the opening seconds of any half are
# spawn and approach with nobody dying yet. Short halves are cheap to exclude and
# expensive to model, so exclude them: the floor is the mechanism, the rate is
# the refinement for everything above it.
HALF_MIN_SECONDS = 300
# Re-measured on the fleet over a 7-day window, above the floor: the LOWEST rate
# ratio among healthy matches was 0.82, so 0.70 has real headroom and the
# defective ones stay well under it. A 914s match sits in that set at 0.95 --
# shorter than a standard half and correctly kept, which is what the duration
# floor has to allow.
# ktp_match_stats is written by doEvent_KTPMatchEnd -- once, at MATCH end, for
# every half at the same time. A half therefore has no summary rows for as long
# as its match is still being played, and that is correct, not a defect. Both
# checks below are scoped to finished matches for that reason; keying them on the
# half instead makes the monitor fire on every live match it sees.
SETTLE_MINUTES = 10
# A match sitting at HALFTIME has exactly one row, h1, and it has an end_time --
# so COUNT(*) = COUNT(end_time) is satisfied and the match reads as finished
# while it is still being played. Its absent h2 summary then looks like an ingest
# gap. Requiring an h2 row outright would hide a genuinely abandoned first half,
# so single-half matches get a longer settle instead: long enough that a real
# halftime would have started h2, short enough to still report the abandoned one.
SINGLE_HALF_SETTLE_MINUTES = 45
# A match is finished when every half has an end_time and the last one has
# settled -- and, if only one half exists, when that longer settle has passed.
FINISHED = """
  m.match_id IN (
    SELECT match_id FROM ktp_matches GROUP BY match_id
    HAVING COUNT(*) = COUNT(end_time)
       AND MAX(end_time) < NOW() - INTERVAL {settle} MINUTE
       AND (MAX(half) >= 2
            OR MAX(end_time) < NOW() - INTERVAL {single} MINUTE)
  )
"""


def q(db: str, sql: str) -> list[list[str]]:
    out = subprocess.run(
        ["mysql", "--default-character-set=utf8mb4", "--batch", "--raw", "-N", db, "-e", sql],
        capture_output=True, text=True, errors="replace")
    if out.returncode:
        raise SystemExit("mysql failed: %s" % out.stderr.strip()[:400])
    return [ln.split("\t") for ln in out.stdout.splitlines() if ln]


def udp_counters() -> dict[str, int]:
    """RcvbufErrors is the only evidence that log lines were dropped in transit."""
    try:
        with open(SNMP) as fh:
            lines = fh.read().splitlines()
    except OSError:
        return {}
    for i, ln in enumerate(lines):
        if ln.startswith("Udp:") and not ln.startswith("UdpLite:") and "InDatagrams" in ln:
            keys = ln.split()[1:]
            vals = lines[i + 1].split()[1:]
            return {k: int(v) for k, v in zip(keys, vals)}
    return {}


def load_state() -> dict:
    try:
        with open(STATE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=1)
    os.replace(tmp, STATE)          # never leave a half-written state file behind


def check_udp_drops(findings: list[str], info: list[str]) -> None:
    now = udp_counters()
    if not now:
        return
    state = load_state()
    prev = state.get("udp", {})
    save_state({**state, "udp": now, "udp_at": int(time.time())})

    total = now.get("RcvbufErrors", 0)
    info.append("udp RcvbufErrors total=%d InErrors=%d" % (total, now.get("InErrors", 0)))
    if not prev:
        info.append("udp: first run, no delta yet")
        return
    delta = total - prev.get("RcvbufErrors", 0)
    if delta > 0:
        findings.append(
            "UDP receive buffer overflowed %d times since the last check -- log lines "
            "were dropped before the daemon saw them. Raise net.core.rmem_max, or move "
            "the daemon off a box that is also running game servers." % delta)


def check_missing_halves(db: str, since: int, findings: list[str]) -> None:
    """A half that played but produced no summary rows -- the empty-matchid shape."""
    rows = q(db, """
        SELECT m.match_id, m.half, m.start_time
        FROM ktp_matches m
        LEFT JOIN (SELECT DISTINCT match_id, half FROM ktp_match_stats) s
          ON s.match_id {c} = m.match_id {c} AND s.half = m.half
        WHERE m.end_time IS NOT NULL
          AND m.start_time > NOW() - INTERVAL {since} MINUTE
          AND s.match_id IS NULL
          AND TIMESTAMPDIFF(SECOND, m.start_time, m.end_time) > 60
          AND {finished}
        ORDER BY m.start_time
    """.format(c=COLL, since=int(since), finished=FINISHED.format(settle=SETTLE_MINUTES, single=SINGLE_HALF_SETTLE_MINUTES)))
    for mid, half, started in rows:
        findings.append("half with no stats rows at all: %s h%s (started %s)" % (mid, half, started))


def check_aggregate_vs_events(db: str, since: int, findings: list[str],
                              info_only: list[str]) -> None:
    """The summary and the events it summarises should agree. When they do not,
    one of the two pipelines stopped and only this comparison can tell."""
    rows = q(db, """
        SELECT f.match_id, f.half, f.frags, IFNULL(s.kills, 0)
        FROM (SELECT match_id, half, COUNT(*) frags FROM hlstats_Events_Frags
              WHERE match_id IS NOT NULL AND half > 0
                AND eventTime > NOW() - INTERVAL %d MINUTE
              GROUP BY match_id, half) f
        LEFT JOIN (SELECT match_id, half, SUM(kills) kills FROM ktp_match_stats
                   WHERE half > 0 GROUP BY match_id, half) s
          ON s.match_id {c} = f.match_id {c} AND s.half = f.half
        JOIN ktp_matches m
          ON m.match_id {c} = f.match_id {c} AND m.half = f.half
        WHERE f.frags <> IFNULL(s.kills, 0)
          AND {finished}
    """.format(c=COLL, finished=FINISHED.format(settle=SETTLE_MINUTES, single=SINGLE_HALF_SETTLE_MINUTES)) % since)
    for mid, half, frags, kills in rows:
        frags, kills = int(frags), int(kills)
        if frags > kills:
            findings.append("summary is SHORT of its events: %s h%s -- %d frags but only "
                            "%d kills recorded" % (mid, half, frags, kills))
        else:
            # recordEvent only stamps match_id while the round is live, so freeze-time
            # kills land untagged and the summary legitimately runs ahead of the tagged
            # frag rows. Report it, but it is not the failure this monitor is for.
            info_only.append("summary ahead of tagged events (freeze-time kills are "
                             "untagged): %s h%s -- %d frags, %d kills" % (mid, half, frags, kills))


def check_half_ratio(db: str, since: int, findings: list[str]) -> None:
    """Second halves that came in far under their own first half. Catches partial
    ingest loss, which leaves plausible-looking rows rather than an obvious gap."""
    rows = q(db, """
        SELECT h1.match_id, h1.k, h2.k, d1.secs, d2.secs
        FROM (SELECT match_id, SUM(kills) k FROM ktp_match_stats WHERE half = 1 GROUP BY match_id) h1
        JOIN (SELECT match_id, SUM(kills) k FROM ktp_match_stats WHERE half = 2 GROUP BY match_id) h2
          ON h2.match_id COLLATE utf8mb4_unicode_ci = h1.match_id COLLATE utf8mb4_unicode_ci
        JOIN (SELECT match_id, MAX(TIMESTAMPDIFF(SECOND, start_time, end_time)) secs
                FROM ktp_matches WHERE half = 1 AND end_time IS NOT NULL GROUP BY match_id) d1
          ON d1.match_id COLLATE utf8mb4_unicode_ci = h1.match_id COLLATE utf8mb4_unicode_ci
        JOIN (SELECT match_id, MAX(TIMESTAMPDIFF(SECOND, start_time, end_time)) secs
                FROM ktp_matches WHERE half = 2 AND end_time IS NOT NULL GROUP BY match_id) d2
          ON d2.match_id COLLATE utf8mb4_unicode_ci = h1.match_id COLLATE utf8mb4_unicode_ci
        JOIN (SELECT match_id, MAX(start_time) st FROM ktp_matches GROUP BY match_id) m
          ON m.match_id COLLATE utf8mb4_unicode_ci = h1.match_id COLLATE utf8mb4_unicode_ci
        WHERE m.st > NOW() - INTERVAL %d MINUTE
          AND h1.k > 60
          AND d1.secs >= %d
          AND d2.secs >= %d
          AND (h2.k / d2.secs) < (h1.k / d1.secs) * %s
    """ % (since, HALF_MIN_SECONDS, HALF_MIN_SECONDS, HALF_RATIO_FLOOR))
    for mid, k1, k2, s1, s2 in rows:
        r1 = int(k1) / int(s1)
        r2 = int(k2) / int(s2)
        findings.append(
            "half 2 rate far under half 1: %s -- %s kills in %ss (%.3f/s) then "
            "%s kills in %ss (%.3f/s), %.0f%% of the rate"
            % (mid, k1, s1, r1, k2, s2, r2, 100.0 * r2 / r1))


def check_unresolved_actions(findings: list[str], info: list[str]) -> None:
    """Read the daemon's own health line. Silent unless it has something to say."""
    out = subprocess.run(
        ["journalctl", "-u", "hlstatsx", "--since", "-30min", "--no-pager", "-o", "cat"],
        capture_output=True, text=True, errors="replace")
    if out.returncode:
        return
    last = None
    for ln in out.stdout.splitlines():
        if "KTP_HEALTH" in ln:
            last = ln
    if not last:
        return
    info.append("daemon health: " + last.strip()[-120:])
    m = re.search(r"unresolved_actions=(\d+)", last)
    if m and int(m.group(1)) > 0:
        findings.append(
            "daemon reports %s unresolved action(s) -- events are being parsed and "
            "discarded because hlstats_Actions has no matching row. Seed the table."
            % m.group(1))
    m = re.search(r"sql_failed=(\d+)", last)
    if m:
        total = int(m.group(1))
        state = load_state()
        prev = state.get("sql_failed")
        save_state({**state, "sql_failed": total, "sql_failed_at": int(time.time())})
        info.append("daemon sql_failed lifetime=%d" % total)
        if prev is None:
            info.append("sql_failed: first run, no delta yet")
        elif total < prev:
            # Cumulative, and only ever zeroed at daemon startup.
            info.append("sql_failed: counter reset, daemon restarted")
        elif total > prev:
            findings.append(
                "daemon failed %d SQL write(s) since the last check (lifetime %d) -- "
                "writes are being lost after retry. journalctl -u hlstatsx | grep "
                "SQL_ERROR names the table." % (total - prev, total))


def check_logs_against_db(db: str, logdir: str, since: int, findings: list[str]) -> None:
    """LAN only: when the game servers share a box with the daemon, their own logs
    are the ground truth and the comparison that would have caught everything.
    Counts kill lines per half window and holds them against the frag rows."""
    if not os.path.isdir(logdir):
        findings.append("log directory not found: %s" % logdir)
        return
    halves = q(db, """
        SELECT match_id, half, start_time, end_time FROM ktp_matches
        WHERE end_time IS NOT NULL AND start_time > NOW() - INTERVAL %d MINUTE
    """ % since)
    if not halves:
        return
    kills: list[str] = []
    for name in sorted(os.listdir(logdir)):
        if not name.startswith("L") or not name.endswith(".log"):
            continue
        try:
            with open(os.path.join(logdir, name), errors="replace") as fh:
                kills.extend(ln for ln in fh if '" killed "' in ln)
        except OSError:
            continue
    stamp = re.compile(r"^L (\d{2})/(\d{2})/(\d{4}) - (\d{2}:\d{2}:\d{2}):")
    stamped = []
    for ln in kills:
        m = stamp.match(ln)
        if m:
            stamped.append("%s-%s-%s %s" % (m.group(3), m.group(1), m.group(2), m.group(4)))
    for mid, half, st, en in halves:
        n = sum(1 for t in stamped if st <= t <= en)
        if not n:
            continue
        got = q(db, "SELECT COUNT(*) FROM hlstats_Events_Frags "
                    "WHERE match_id='%s' AND half=%s" % (mid, half))
        have = int(got[0][0]) if got else 0
        if n - have > max(3, n * 0.02):
            findings.append("log vs database: %s h%s -- %d kills in the log, %d in the "
                            "database (%d missing)" % (mid, half, n, have, n - have))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="hlstatsx")
    ap.add_argument("--since", type=int, default=90, help="minutes to look back (default 90)")
    ap.add_argument("--logs", help="game log directory; enables log-vs-database checking "
                                   "(LAN deploys, where servers and daemon share a host)")
    ap.add_argument("--quiet", action="store_true", help="print only findings")
    args = ap.parse_args()

    findings: list[str] = []
    info: list[str] = []

    check_udp_drops(findings, info)
    check_missing_halves(args.db, args.since, findings)
    check_aggregate_vs_events(args.db, args.since, findings, info)
    check_half_ratio(args.db, args.since, findings)
    check_unresolved_actions(findings, info)
    if args.logs:
        check_logs_against_db(args.db, args.logs, args.since, findings)

    if not args.quiet:
        for line in info:
            print("  %s" % line)
    if findings:
        print("HLStatsX ingest: %d finding(s) in the last %d minutes" % (len(findings), args.since))
        for f in findings:
            print("  !! %s" % f)
        return 1
    if not args.quiet:
        print("HLStatsX ingest: clean over the last %d minutes" % args.since)
    return 0


if __name__ == "__main__":
    sys.exit(main())
