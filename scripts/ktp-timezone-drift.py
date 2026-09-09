#!/usr/bin/env python3
"""Read-only fleet timezone-uniformity check.

WHY THIS EXISTS. `hlstats.pl:2542` computes `$ev_remotetime = timelocal(...)`
unconditionally: it reads a game server's naked wall-clock log stamp and
interprets it in the DAEMON's timezone. That value already drives the
`last_team_change + 2 s` grace that suppresses a team-kill after a team switch
(`HLstats_EventHandlers.plib:792, 877, 1145`). A game host provisioned in UTC
would therefore mis-attribute team kills today, silently, with no flag enabled
and nothing reporting it. The fleet agrees on America/New_York by convention
only -- no runtime assertion, no provisioning pin, no check. A rebuilt or newly
provisioned host is the arrival path.

THE LOAD-BEARING PROBE IS NOT `timedatectl`. That reads a host's CONFIG; the
daemon consumes what the ENGINE STAMPS INTO THE LOG LINE. A host can satisfy
timedatectl and still write a wrong stamp. So the discriminating measurement,
run per instance, is: take the last log line's naked reading, interpret it the
way the daemon does -- in the expected zone -- and compare the result against
the log file's mtime, which is absolute. A host stamping in the wrong zone
lands whole hours away. timedatectl, /etc/localtime and NTP are kept as
secondary config checks and are labelled as such in the output.

The two probes are complementary and neither subsumes the other:
  * stamp-vs-mtime catches a wrong ZONE (both readings come off the same host,
    so a host whose clock is simply wrong shifts them together and passes);
  * host-clock-vs-auditor catches a wrong CLOCK (a host in the right zone with
    dead NTP writes internally-consistent stamps that are hours from reality).

Read-only. It reads clocks, a config line and a log tail. It writes nothing
anywhere, restarts nothing, and never touches a game server.

Usage:
    python3 ktp-timezone-drift.py [--verbose] [--game-hosts-only]

Host addressing and credentials come from the same JSON the fleet audit uses:
/etc/ktp/audit-fleet.json, or KTP_AUDIT_FLEET_CONFIG. The data server is read
from that file's optional "data_server" object. See
scripts/audit-fleet.json.example for the schema. Nothing is hardcoded here.

Exit: 0 = every host reached, every check clean
      1 = the check itself could not be trusted (host unreachable, control
          failed, probe truncated, tz database missing) -- NOT a clean fleet
      2 = timezone drift found

An unreachable host, a failed control and a truncated probe are all exit 1
rather than a skip. A sweep that silently drops a host renders as a clean
fleet, which is the failure this script exists to close rather than reproduce.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    import paramiko
except ImportError:
    sys.exit("ERROR: paramiko not installed (pip3 install paramiko)")

# The zone the daemon's timelocal() resolves in. Every game host must agree
# with it or $ev_remotetime is wrong for that host's events.
EXPECTED_TZ = "America/New_York"
STATS_SCHEMA = os.environ.get("KTP_STATS_SCHEMA", "hlstatsx")

# A log line's stamp is formatted when the event fires; the file's mtime lands
# on the write that carried it. The audit measured these equal to the second,
# so a couple of seconds absorbs a second-boundary straddle while staying four
# orders of magnitude below the smallest zone error worth catching.
DEFAULT_STAMP_TOLERANCE = 2
# Host clock vs this machine's, over SSH. Wide enough for round-trip and a lazy
# scheduler, far below anything NTP would leave standing.
DEFAULT_CLOCK_TOLERANCE = 5

LOG_STAMP_RE = re.compile(r"^L (\d{2})/(\d{2})/(\d{4}) - (\d{2}):(\d{2}):(\d{2}):")

# `instance=` opens a per-instance block; everything before the first one is
# host scope.
_KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")

GAME_HOST_PROBE = r"""
echo "PROBE_BEGIN"
echo "clock_epoch=$(date +%s)"
echo "clock_offset=$(date +%z)"
echo "clock_abbrev=$(date +%Z)"
echo "localtime_target=$(readlink -f /etc/localtime)"
timedatectl show -p Timezone -p NTP -p NTPSynchronized 2>/dev/null | sed 's/^/timedatectl_/'
ls -d "$HOME"/dod-NOSUCHPORT-zzz >/dev/null 2>&1; echo "negative_control_rc=$?"
for d in "$HOME"/dod-[0-9][0-9][0-9][0-9][0-9]; do
  [ -d "$d" ] || continue
  echo "instance=${d##*/dod-}"
  cfg="$d/serverfiles/dod/dodserver.cfg"
  if [ -f "$cfg" ]; then
    echo "hostname_lines=$(grep -c hostname "$cfg")"
  else
    echo "hostname_lines=NOFILE"
  fi
  f=$(ls -1t "$d"/serverfiles/dod/logs/L*.log 2>/dev/null | head -1)
  if [ -n "$f" ]; then
    echo "logfile=$f"
    echo "log_mtime=$(stat -c %Y "$f")"
    echo "log_lastline=$(tail -c 65536 "$f" | grep -a '^L [0-9]' | tail -1)"
    echo "probe_epoch=$(date +%s)"
  else
    echo "logfile=NONE"
  fi
done
echo "PROBE_END"
"""

DATA_SERVER_PROBE = r"""
echo "PROBE_BEGIN"
echo "clock_epoch=$(date +%s)"
echo "clock_offset=$(date +%z)"
echo "clock_abbrev=$(date +%Z)"
echo "localtime_target=$(readlink -f /etc/localtime)"
timedatectl show -p Timezone -p NTP -p NTPSynchronized 2>/dev/null | sed 's/^/timedatectl_/'
pid=$(systemctl show hlstatsx -p MainPID --value 2>/dev/null)
echo "daemon_mainpid=${pid:-NONE}"
if [ -n "$pid" ] && [ "$pid" != "0" ] && [ -r "/proc/$pid/environ" ]; then
  echo "daemon_env_vars=$(tr '\0' '\n' < /proc/$pid/environ | grep -c .)"
  echo "daemon_tz_vars=$(tr '\0' '\n' < /proc/$pid/environ | grep -c '^TZ=')"
else
  echo "daemon_env_vars=UNREADABLE"
fi
mysql_out=$(mysql -N -B -e "SELECT CONCAT_WS('|', @@system_time_zone, @@global.time_zone, @@session.time_zone, TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), NOW()), (SELECT COUNT(*) FROM mysql.time_zone_name), (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='__SCHEMA__'));" 2>&1)
echo "mysql_rc=$?"
echo "mysql_row=$(printf '%s' "$mysql_out" | tail -1)"
echo "PROBE_END"
"""


class Finding:
    """One line of the report. ERROR means the sweep is untrustworthy, DRIFT
    means the fleet is, INFO is neither."""

    __slots__ = ("level", "host", "subject", "message")

    def __init__(self, level, host, subject, message):
        self.level = level
        self.host = host
        self.subject = subject
        self.message = message

    def __str__(self):
        where = self.host if not self.subject else "%s %s" % (self.host, self.subject)
        return "%-5s %s: %s" % (self.level, where, self.message)


def zone_reference(tz_name, at_epoch):
    """Offset and abbreviation the expected zone is in at a given instant.

    Derived rather than written down so the check does not need editing twice
    a year, and so a DST transition cannot read as fleet drift.
    """
    try:
        zone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        sys.exit("ERROR: no tz database on this machine, so %s cannot be "
                 "resolved and every comparison below would be vacuous. "
                 "Install tzdata (pip install tzdata, or the OS package)."
                 % tz_name)
    aware = datetime.fromtimestamp(at_epoch, zone)
    total = int(aware.utcoffset().total_seconds())
    sign = "-" if total < 0 else "+"
    return {
        "zone": zone,
        "name": tz_name,
        "offset_seconds": total,
        "offset": "%s%02d%02d" % (sign, abs(total) // 3600, (abs(total) % 3600) // 60),
        "abbrev": aware.tzname(),
    }


def log_stamp_epoch(line, zone):
    """Epoch the daemon would derive from a log line, or None if unparseable.

    Both DST folds are tried and the nearer taken: during the fall-back hour a
    local reading names two instants, and picking the wrong one would report an
    hour of legitimate lines as drift every November.
    """
    m = LOG_STAMP_RE.match(line.strip())
    if not m:
        return None
    month, day, year, hour, minute, second = (int(g) for g in m.groups())
    try:
        naive = datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None
    return [int(naive.replace(tzinfo=zone, fold=f).timestamp()) for f in (0, 1)]


def nearest_stamp_delta(candidates, reference):
    """Signed delta of whichever fold lands closer to the reference."""
    return min((c - reference for c in candidates), key=abs)


def parse_probe(raw):
    """Split a probe's key=value stream into host scope and instance blocks.

    Returns {"host": {...}, "instances": {port: {...}}, "complete": bool}. The
    completeness flag is the whole point of the BEGIN/END markers: a probe
    killed halfway emits a prefix that parses perfectly and reads as a host
    with fewer instances.
    """
    host, instances, current = {}, {}, None
    saw_begin = saw_end = False
    for line in raw.splitlines():
        line = line.strip()
        if line == "PROBE_BEGIN":
            saw_begin = True
            continue
        if line == "PROBE_END":
            saw_end = True
            continue
        m = _KV_RE.match(line)
        if not m:
            continue
        key, value = m.group(1), m.group(2)
        if key == "instance":
            current = {}
            instances[value] = current
        elif current is not None:
            current[key] = value
        else:
            host[key] = value
    return {"host": host, "instances": instances,
            "complete": saw_begin and saw_end}


def evaluate_clock(name, probe, ref, clock_tolerance, auditor_epoch, findings):
    """Host-level zone, NTP and absolute-clock checks."""
    host = probe["host"]

    if not probe["complete"]:
        findings.append(Finding("ERROR", name, "", "probe did not reach its end "
                                "marker -- output truncated, treat every result "
                                "from this host as unmeasured"))
        return

    epoch = host.get("clock_epoch", "")
    if not epoch.isdigit():
        findings.append(Finding("ERROR", name, "", "host clock unreadable"))
    else:
        skew = int(epoch) - auditor_epoch
        if abs(skew) > clock_tolerance:
            findings.append(Finding("DRIFT", name, "clock",
                                    "host clock is %+ds from the auditing "
                                    "machine's (tolerance %ds). If every host "
                                    "reports this, suspect the auditor."
                                    % (skew, clock_tolerance)))

    offset = host.get("clock_offset")
    if offset != ref["offset"]:
        findings.append(Finding("DRIFT", name, "offset",
                                "date reports %s (%s); %s is %s (%s) right now"
                                % (offset, host.get("clock_abbrev"), ref["name"],
                                   ref["offset"], ref["abbrev"])))

    target = host.get("localtime_target", "")
    if not target.endswith("/" + ref["name"]):
        findings.append(Finding("DRIFT", name, "/etc/localtime",
                                "resolves to %r, not .../%s -- this is what the "
                                "engine and the daemon read"
                                % (target, ref["name"])))

    # Config-level, deliberately secondary: a host can satisfy all of this and
    # still stamp a wrong reading into the log line.
    tz = host.get("timedatectl_Timezone")
    if tz != ref["name"]:
        findings.append(Finding("DRIFT", name, "timedatectl[config]",
                                "Timezone=%r, expected %r" % (tz, ref["name"])))
    if host.get("timedatectl_NTPSynchronized") != "yes":
        findings.append(Finding("DRIFT", name, "timedatectl[config]",
                                "NTPSynchronized=%r (NTP=%r) -- an unsynchronised "
                                "clock writes its error into every log stamp"
                                % (host.get("timedatectl_NTPSynchronized"),
                                   host.get("timedatectl_NTP"))))


def evaluate_instances(name, probe, ref, tolerance, findings):
    """The load-bearing per-instance check, plus its two controls."""
    host, instances = probe["host"], probe["instances"]

    if host.get("negative_control_rc") == "0":
        findings.append(Finding("ERROR", name, "control",
                                "a listing of a directory that does not exist "
                                "SUCCEEDED -- this probe cannot tell absence "
                                "from success, so no result from it counts"))
    if not instances:
        findings.append(Finding("ERROR", name, "control",
                                "no dod-<port> instance directories found; a "
                                "denied or empty listing renders identically to "
                                "a host with nothing to check"))
        return

    for port in sorted(instances):
        inst = instances[port]
        label = "dod-%s" % port

        if inst.get("hostname_lines") != "1":
            findings.append(Finding("ERROR", name, label,
                                    "positive control failed: dodserver.cfg "
                                    "hostname lines = %r"
                                    % inst.get("hostname_lines")))
            continue

        logfile = inst.get("logfile", "NONE")
        if logfile == "NONE":
            findings.append(Finding("ERROR", name, label,
                                    "no L*.log to read -- unmeasured, not clean"))
            continue

        mtime, lastline = inst.get("log_mtime", ""), inst.get("log_lastline", "")
        if not mtime.isdigit():
            findings.append(Finding("ERROR", name, label,
                                    "log mtime unreadable for %s" % logfile))
            continue
        candidates = log_stamp_epoch(lastline, ref["zone"])
        if candidates is None:
            findings.append(Finding("ERROR", name, label,
                                    "last log line does not carry a parseable "
                                    "stamp: %r" % lastline[:120]))
            continue

        delta = nearest_stamp_delta(candidates, int(mtime))
        if abs(delta) > tolerance:
            findings.append(Finding("DRIFT", name, label,
                                    "log stamp read as %s lands %+ds (%+.2f h) "
                                    "from the file's mtime -- the engine is not "
                                    "stamping in %s, so every event from this "
                                    "instance is mis-timed by the daemon"
                                    % (ref["name"], delta, delta / 3600.0,
                                       ref["name"])))

        probe_epoch = inst.get("probe_epoch", "")
        if probe_epoch.isdigit() and int(mtime) - int(probe_epoch) > tolerance:
            findings.append(Finding("DRIFT", name, label,
                                    "log mtime is %ds in the future of the host's "
                                    "own clock" % (int(mtime) - int(probe_epoch))))


def evaluate_data_server(name, probe, ref, findings):
    """Daemon environment and MySQL's view of the clock."""
    host = probe["host"]

    pid = host.get("daemon_mainpid", "NONE")
    env_vars = host.get("daemon_env_vars", "UNREADABLE")
    if pid in ("NONE", "0") or not env_vars.isdigit() or env_vars == "0":
        findings.append(Finding("ERROR", name, "hlstatsx",
                                "daemon environment unreadable (MainPID=%r, "
                                "env vars=%r) -- the TZ result below would be a "
                                "zero from a failed read" % (pid, env_vars)))
    elif host.get("daemon_tz_vars") != "0":
        findings.append(Finding("DRIFT", name, "hlstatsx",
                                "the daemon has TZ set explicitly in its "
                                "environment; it is supposed to resolve through "
                                "/etc/localtime, which is what this check "
                                "asserts everywhere else"))

    if host.get("mysql_rc") != "0":
        findings.append(Finding("ERROR", name, "mysql",
                                "the timezone query failed (rc=%r, %r). Run as a "
                                "user that can reach MySQL, or give it a "
                                "~/.my.cnf." % (host.get("mysql_rc"),
                                                host.get("mysql_row", "")[:120])))
        return

    parts = host.get("mysql_row", "").split("|")
    if len(parts) != 6:
        findings.append(Finding("ERROR", name, "mysql",
                                "unexpected query result %r"
                                % host.get("mysql_row", "")[:120]))
        return
    system_tz, global_tz, session_tz, offset, tz_names, schema_tables = parts

    if not schema_tables.isdigit() or schema_tables == "0":
        findings.append(Finding("ERROR", name, "mysql",
                                "control failed: schema %s reports %r tables, so "
                                "the row above is not a measurement"
                                % (STATS_SCHEMA, schema_tables)))
        return

    if system_tz != ref["abbrev"]:
        findings.append(Finding("DRIFT", name, "mysql",
                                "@@system_time_zone=%r; %s is %r right now"
                                % (system_tz, ref["name"], ref["abbrev"])))
    if global_tz != "SYSTEM":
        findings.append(Finding("DRIFT", name, "mysql",
                                "@@global.time_zone=%r rather than SYSTEM -- the "
                                "database has stopped following the host's zone"
                                % global_tz))
    if session_tz != "SYSTEM":
        findings.append(Finding("DRIFT", name, "mysql",
                                "@@session.time_zone=%r rather than SYSTEM"
                                % session_tz))
    try:
        measured = int(offset)
    except ValueError:
        findings.append(Finding("ERROR", name, "mysql",
                                "NOW()-UTC_TIMESTAMP() unreadable: %r" % offset))
    else:
        if measured != ref["offset_seconds"]:
            findings.append(Finding("DRIFT", name, "mysql",
                                    "NOW() is %+ds from UTC_TIMESTAMP(); %s is "
                                    "%+ds right now" % (measured, ref["name"],
                                                        ref["offset_seconds"])))

    if tz_names == "0":
        findings.append(Finding("INFO", name, "mysql",
                                "mysql.time_zone_name is empty, so CONVERT_TZ() "
                                "with a named zone returns NULL instead of "
                                "erroring. Nothing reads it today. Reported, not "
                                "failed -- this does not affect the exit code."))


def exit_code(findings):
    """ERROR outranks DRIFT: a sweep you cannot trust is worse news than one
    that measured something wrong."""
    if any(f.level == "ERROR" for f in findings):
        return 1
    if any(f.level == "DRIFT" for f in findings):
        return 2
    return 0


def load_config():
    path = Path(os.environ.get("KTP_AUDIT_FLEET_CONFIG", "/etc/ktp/audit-fleet.json"))
    if not path.exists():
        sys.exit("ERROR: fleet config not found at %s\n"
                 "Copy scripts/audit-fleet.json.example there, or set "
                 "KTP_AUDIT_FLEET_CONFIG." % path)
    data = json.loads(path.read_text())
    hosts = data.get("hosts")
    if not isinstance(hosts, list) or not hosts:
        sys.exit('ERROR: %s has no non-empty "hosts" array' % path)
    return hosts, data.get("data_server"), path


def connect(entry):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    auth = {}
    if entry.get("key_filename"):
        auth["key_filename"] = entry["key_filename"]
    elif entry.get("password"):
        auth["password"] = entry["password"]
    client.connect(entry["host"], username=entry.get("user", "dodserver"),
                   timeout=45, banner_timeout=45, auth_timeout=45,
                   allow_agent=False, look_for_keys=False, **auth)
    return client


def collect(client, script):
    """Run a probe, returning (rc, text). Both are needed: an empty stdout and
    a non-zero status are separate ways for this to have measured nothing."""
    _, out, err = client.exec_command(script, timeout=120)
    text = out.read().decode("utf-8", "replace")
    rc = out.channel.recv_exit_status()
    return rc, text + err.read().decode("utf-8", "replace")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true",
                    help="print what each instance measured, not only failures")
    ap.add_argument("--game-hosts-only", action="store_true",
                    help="skip the data server (daemon + MySQL go unchecked)")
    ap.add_argument("--timezone", default=EXPECTED_TZ)
    ap.add_argument("--tolerance-seconds", type=int, default=DEFAULT_STAMP_TOLERANCE)
    ap.add_argument("--clock-tolerance-seconds", type=int,
                    default=DEFAULT_CLOCK_TOLERANCE)
    args = ap.parse_args()

    hosts, data_entry, config_path = load_config()
    ref = zone_reference(args.timezone, int(time.time()))

    print("Expected zone %s -- %s (%s) at this instant, derived from the tz "
          "database, not written down." % (ref["name"], ref["offset"], ref["abbrev"]))
    print("Load-bearing check: the last log line's stamp, read as %s, against "
          "the log file's mtime." % ref["name"])
    print("timedatectl / /etc/localtime / NTP are secondary config checks.\n")

    findings, reached, instances_measured = [], 0, 0
    targets = [(h, GAME_HOST_PROBE, False) for h in hosts]
    if args.game_hosts_only:
        print("NOTE: --game-hosts-only, so the daemon and MySQL are UNCHECKED.\n")
    elif data_entry:
        targets.append((data_entry, DATA_SERVER_PROBE.replace("__SCHEMA__",
                                                              STATS_SCHEMA), True))
    else:
        findings.append(Finding("ERROR", "data server", "",
                                'no "data_server" object in %s -- the daemon and '
                                "MySQL are where the log stamp is finally "
                                "interpreted, so leaving them out is not a "
                                "narrower pass. See "
                                "scripts/audit-fleet.json.example."
                                % config_path))

    for entry, script, is_data in targets:
        name = entry.get("name", entry.get("host", "?"))
        try:
            client = connect(entry)
        except Exception as ex:
            findings.append(Finding("ERROR", name, "",
                                    "UNREACHABLE (%s) %s"
                                    % (type(ex).__name__, str(ex)[:120])))
            continue
        reached += 1
        try:
            # Sampled per host, not once for the run: the sweep takes tens of
            # seconds and a single reference turns its own elapsed time into
            # clock skew that grows down the host list.
            auditor_epoch = int(time.time())
            rc, raw = collect(client, script)
        finally:
            client.close()
        if rc != 0 or not raw.strip():
            findings.append(Finding("ERROR", name, "",
                                    "probe exited %d with %d bytes of output"
                                    % (rc, len(raw.strip()))))
            continue

        probe = parse_probe(raw)
        evaluate_clock(name, probe, ref, args.clock_tolerance_seconds,
                       auditor_epoch, findings)
        if is_data:
            evaluate_data_server(name, probe, ref, findings)
        else:
            evaluate_instances(name, probe, ref, args.tolerance_seconds, findings)
            instances_measured += len(probe["instances"])
            if args.verbose:
                for port in sorted(probe["instances"]):
                    inst = probe["instances"][port]
                    stamps = log_stamp_epoch(inst.get("log_lastline", ""),
                                             ref["zone"])
                    mtime = inst.get("log_mtime", "")
                    delta = (nearest_stamp_delta(stamps, int(mtime))
                             if stamps and mtime.isdigit() else None)
                    print("  %s dod-%s: stamp-vs-mtime %s"
                          % (name, port,
                             "%+ds" % delta if delta is not None else "UNREAD"))

    for level in ("ERROR", "DRIFT", "INFO"):
        for f in findings:
            if f.level == level:
                print(f)

    print("\nhosts reached: %d/%d   instances measured: %d   errors: %d   "
          "drift: %d   informational: %d"
          % (reached, len(targets), instances_measured,
             sum(1 for f in findings if f.level == "ERROR"),
             sum(1 for f in findings if f.level == "DRIFT"),
             sum(1 for f in findings if f.level == "INFO")))
    rc = exit_code(findings)
    print({0: "CLEAN", 1: "CHECK FAILED -- this is not a clean fleet",
           2: "TIMEZONE DRIFT"}[rc])
    return rc


if __name__ == "__main__":
    sys.exit(main())
