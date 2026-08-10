#!/usr/bin/env python3
"""Ingest HLTV connection LOG lines into hlstatsx.ktp_hltv_connections.

The ufw rule (see /etc/ufw/before.rules) logs one line per (source IP, proxy
port) per hour for every new connection reaching the proxies. It deliberately
does NOT filter to "real viewers" -- that judgement lives in
ktp-hltv-correlate.py, because two attempts to make the kernel decide were both
structurally wrong in production. So these rows are connection ATTEMPTS.

Relies on INSERT IGNORE against a unique key rather than tracking a file offset:
an offset file is one more thing that can desync. Reads the rotated sibling too,
so a run landing just after logrotate does not skip the tail of the previous
week.

VOLUME -- measured, because this file previously assumed "a few lines a day" and
every sizing decision downstream inherited that: the live rule captures
~22,300 lines/day from ~212 distinct source IPs, almost all server-browser
scrapers sweeping the published proxy range. So:

  * Only rows NEWER than what the table already holds are sent, with an overlap
    window for safety. Re-inserting the whole retained log every 15 minutes was
    ~1 MB of INSERT per run climbing with retention, and it hit the 16 MB CLIENT
    max_allowed_packet at roughly two weeks -- after which every run aborted the
    entire batch and ingest stopped permanently, silently.
  * Inserts are chunked. One statement per run is what made the packet ceiling a
    cliff rather than a slope.
  * Rows older than RETENTION_DAYS are deleted here, because nothing else does it
    and an unbounded table makes the correlate query worse every day.
"""
import glob, gzip, re, subprocess, sys
from datetime import datetime, timedelta

LOG_GLOB = "/var/log/ktp-hltv-connections.log*"
CHUNK_ROWS = 1000
# Re-read this far back past the newest stored row. Covers a clock skew or a late
# rotation without re-sending the whole table; INSERT IGNORE absorbs the overlap.
OVERLAP_HOURS = 6
RETENTION_DAYS = 180  # matches the 26-week logrotate window
LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?[+-]\d{2}:\d{2})\s+.*?"
    r"KTP_HLTV_CONN.*?\bSRC=(?P<src>\d+\.\d+\.\d+\.\d+).*?\bDPT=(?P<dpt>\d+)"
)


def mysql(sql):
    """Run SQL, return (ok, stdout). Kept tiny so every caller checks returncode."""
    out = subprocess.run(["mysql", "-N", "-B", "hlstatsx"], input=sql,
                         capture_output=True, text=True)
    return out.returncode == 0, (out.stdout.strip() if out.returncode == 0
                                 else out.stderr.strip())


def watermark():
    """Newest hit_time already stored, minus the overlap. None if the table is
    empty or unreadable -- both mean 'ingest everything', which is correct for a
    first run and harmless (INSERT IGNORE) for a transient error."""
    ok, out = mysql("SELECT IFNULL(MAX(hit_time),'') FROM ktp_hltv_connections;")
    if not ok or not out:
        return None
    try:
        return datetime.strptime(out, "%Y-%m-%d %H:%M:%S") - timedelta(hours=OVERLAP_HOURS)
    except ValueError:
        return None


def rows(stats, since):
    seen = set()
    for path in sorted(glob.glob(LOG_GLOB)):
        opener = gzip.open if path.endswith(".gz") else open
        try:
            with opener(path, "rt", errors="replace") as fh:
                for line in fh:
                    stats["read"] += 1
                    m = LINE.search(line)
                    if not m:
                        continue
                    # Store server-local (ET) to match hlstats_Events_Connects.eventTime.
                    # Keeping the offset would make every time-window join a conversion.
                    ts = datetime.fromisoformat(m.group("ts")).replace(tzinfo=None)
                    stats["parsed"] += 1
                    # Bounded by the watermark so both `seen` and the INSERT stay
                    # proportional to NEW traffic, not to retained traffic.
                    if since is not None and ts < since:
                        stats["skipped"] += 1
                        continue
                    key = (ts, m.group("src"), int(m.group("dpt")))
                    if key not in seen:
                        seen.add(key)
                        yield key
        except OSError as exc:
            # Was a bare `continue`, which made an unreadable or truncated file
            # indistinguishable from an empty one -- and gzip.BadGzipFile
            # subclasses OSError, so a bad rotation was swallowed too.
            stats["errors"].append("%s: %s" % (path, exc))


def main():
    # Distinguishable outcomes. Three different failures used to print the same
    # "no viewer lines to ingest" and exit 0, while the correlate tool told the
    # reader that empty was expected -- so a dead pipeline read exactly like a
    # quiet week. Nothing watches this log, so it has to say which case it is.
    stats = {"read": 0, "parsed": 0, "skipped": 0, "errors": [],
             "files": len(glob.glob(LOG_GLOB))}
    since = watermark()
    batch = list(rows(stats, since))
    for err in stats["errors"]:
        sys.stderr.write("WARNING: unreadable log file -- %s\n" % err)
    if not batch:
        if not stats["files"]:
            print("no log file matching %s -- is the rsyslog drop-in installed?"
                  % LOG_GLOB)
            return 1
        if stats["parsed"]:
            # Everything in the log is already stored. Distinct from "nothing
            # matched", which means the log FORMAT changed and is a real fault.
            print("%d read, %d matched, all already ingested (watermark %s)"
                  % (stats["read"], stats["parsed"], since))
            return 0
        if stats["read"]:
            print("%d line(s) read, 0 matched the KTP_HLTV_CONN pattern -- "
                  "check the rsyslog template still emits RFC3339 + the LOG prefix"
                  % stats["read"])
            return 1
        print("log present but empty: no viewer sessions since last rotation")
        return 1 if stats["errors"] else 0
    inserted = 0
    for i in range(0, len(batch), CHUNK_ROWS):
        chunk = batch[i:i + CHUNK_ROWS]
        values = ",".join(
            "('%s','%s',%d)" % (t.strftime("%Y-%m-%d %H:%M:%S"), ip, port)
            for t, ip, port in chunk
        )
        ok, out = mysql("INSERT IGNORE INTO ktp_hltv_connections "
                        "(hit_time, src_ip, dst_port) VALUES %s; "
                        "SELECT ROW_COUNT();" % values)
        if not ok:
            # Report what DID land. A mid-batch failure printing only the error
            # reads as "nothing was ingested", which is the wrong recovery.
            sys.stderr.write("mysql failed after %d row(s) inserted: %s\n"
                             % (inserted, out))
            return 1
        try:
            inserted += int(out.splitlines()[-1])
        except (ValueError, IndexError):
            pass

    ok, pruned = mysql("DELETE FROM ktp_hltv_connections WHERE hit_time < "
                       "NOW() - INTERVAL %d DAY; SELECT ROW_COUNT();" % RETENTION_DAYS)
    if not ok:
        sys.stderr.write("retention prune failed: %s\n" % pruned)
        return 1

    print("read %d, matched %d, %d already ingested, %d candidate(s), "
          "inserted %d new, pruned %s older than %d days"
          % (stats["read"], stats["parsed"], stats["skipped"], len(batch),
             inserted, pruned.splitlines()[-1] if pruned else "0", RETENTION_DAYS))
    return 1 if stats["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
