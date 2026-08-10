#!/usr/bin/env python3
"""Ingest HLTV viewer-session LOG lines into hlstatsx.ktp_hltv_viewer_hits.

The ufw rule (see /etc/ufw/before.rules) logs one line per (source IP, proxy
port) per hour for flows that exceeded 200 packets -- i.e. genuine viewing
sessions, not the server-browser scrapes that sweep all 24 ports.

Re-reads the whole (small) log every run and relies on INSERT IGNORE against a
unique key rather than tracking a file offset: an offset file is one more thing
that can desync, and this log is a few lines a day.

Reads the rotated sibling too, so a run landing just after logrotate does not
skip the tail of the previous week.
"""
import glob, gzip, re, subprocess, sys
from datetime import datetime

LOG_GLOB = "/var/log/ktp-hltv-viewers.log*"
LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?[+-]\d{2}:\d{2})\s+.*?"
    r"KTP_HLTV_VIEW.*?\bSRC=(?P<src>\d+\.\d+\.\d+\.\d+).*?\bDPT=(?P<dpt>\d+)"
)


def rows(stats):
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
    stats = {"read": 0, "errors": [], "files": len(glob.glob(LOG_GLOB))}
    batch = list(rows(stats))
    for err in stats["errors"]:
        sys.stderr.write("WARNING: unreadable log file -- %s\n" % err)
    if not batch:
        if not stats["files"]:
            print("no log file matching %s -- is the rsyslog drop-in installed?"
                  % LOG_GLOB)
            return 1
        if stats["read"]:
            print("%d line(s) read, 0 matched the KTP_HLTV_VIEW pattern -- "
                  "check the rsyslog template still emits RFC3339 + the LOG prefix"
                  % stats["read"])
            return 1
        print("log present but empty: no viewer sessions since last rotation")
        return 1 if stats["errors"] else 0
    values = ",".join(
        "('%s','%s',%d)" % (t.strftime("%Y-%m-%d %H:%M:%S"), ip, port)
        for t, ip, port in batch
    )
    sql = ("INSERT IGNORE INTO ktp_hltv_viewer_hits (hit_time, src_ip, dst_port) "
           "VALUES %s; SELECT ROW_COUNT();" % values)
    out = subprocess.run(["mysql", "-N", "-B", "hlstatsx"], input=sql,
                         capture_output=True, text=True)
    if out.returncode != 0:
        sys.stderr.write("mysql failed: %s\n" % out.stderr.strip())
        return 1
    print("read %d line(s), parsed %d, inserted %s new"
          % (stats["read"], len(batch), out.stdout.strip()))
    return 1 if stats["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
