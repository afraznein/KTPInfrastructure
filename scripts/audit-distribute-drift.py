#!/usr/bin/env python3
"""Does every game instance still hold what /home/dod/distribute would send it?

WHY THIS EXISTS. ktp-file-distributor.service pushes a created or changed file
under /home/dod/distribute to all 24 instances within ~15s, and it is purely
event-driven: there is no startup sync and no reconciliation, ever. So a config
set directly on the instances and never mirrored into the source survives until
the next time anyone touches that file at the source -- and is then silently
overwritten, fleet-wide, with no error anywhere.

That is not hypothetical. On 2026-08-19 a January copy of
addons/ktpamx/configs/discord.ini was pushed with only its auth secret changed.
The push reverted discord_channel_id to a dead value and deleted
discord_channel_id_default outright on all 24, because both had been set on the
instances months earlier and never mirrored back. Nothing detected it; it
surfaced six weeks later because the affected path is reachable only by
competitive play. ktp_maps.ini went two generations stale the same way, and
users.ini one, both found by hand.

THE INVARIANT, AND WHY IT IS THIS ONE
    For every path the distributor WOULD send to a given instance, that
    instance's bytes equal the source's bytes.

"Would send" is read out of the distributor's own two config files --
WatchPatterns in appsettings.json, includePatterns/excludePatterns in
servers.json -- and never restated here. That matters more than it looks:

  * A file that is legitimately per-instance (configs/servernamedefault.cfg
    carries this instance's hostname) is declared by adding it to
    excludePatterns in servers.json. That one edit both silences this check AND
    stops the distributor pushing the file, which is the actual fix -- the file
    is otherwise one touch away from giving 23 servers the 24th's name. An
    allow-list kept HERE would have documented the hazard while leaving it
    armed, and would be a second source of truth free to disagree with the one
    that decides what really ships.
  * Plain md5 equality source-to-instance is wrong for exactly those files and
    right for every other one. Uniformity across the 24 -- what
    ktp-verify-deploy.py asserts -- is the wrong axis on its own: in the
    discord.ini case all 24 agreed with each other and disagreed with the
    source, which is precisely the state that was about to be destroyed.

Read-only. It writes nothing to the distribute tree, nothing to any instance,
and does not restart anything. Instance-side it runs one find|xargs md5sum under
ionice/nice and does not even need a scratch file.

Usage:
    python3 audit-distribute-drift.py [--out report.md] [--state FILE]
                                      [--distributor-dir DIR] [--verbose]

Exit: 0 = every reached target matches on every path AND every target reached
      1 = drift found, or a target could not be reached
      2 = the check could not run (missing/unparsable config, no credentials)

A target that could not be reached is a FAILURE, not a skip -- the same rule
ktp-restart-drift.py follows, and for the same reason: a sweep that quietly
drops a connection renders as a clean fleet.

Host addressing and credentials come from the same JSON the rest of the fleet
audit uses (/etc/ktp/audit-fleet.json, or KTP_AUDIT_FLEET_CONFIG). Auth fields
in servers.json are never read and never printed; targets are named by their
servers.json name, never by address.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import sys
from pathlib import Path

try:
    import paramiko
except ImportError:  # pragma: no cover - environment guard
    sys.exit("ERROR: paramiko not installed (pip3 install paramiko)")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_redact import redact_diagnostic  # noqa: E402

DEFAULT_DISTRIBUTOR_DIR = "/opt/ktp-file-distributor"
# Short enough that audit_redact's 32-hex rule leaves it alone, which is the
# same reason the fleet snapshot prints 16-char binary md5 prefixes.
HASH_CHARS = 16

EXIT_OK, EXIT_DRIFT, EXIT_BROKEN = 0, 1, 2


# --------------------------------------------------------------- pattern rules
# Mirrors KTPFileDistributor/Services/PatternMatcher.cs. Kept deliberately
# literal rather than "improved": a matcher cleverer than the one that actually
# ships would audit a fleet nobody deploys to.
def matches_any(relative_path, patterns):
    for pattern in patterns or ():
        if pattern is None:
            continue
        if pattern == "*.*":
            return True
        if pattern.startswith("*."):
            if relative_path.lower().endswith(pattern[1:].lower()):
                return True
        elif pattern.lower() == relative_path.lower():
            return True
    return False


def matches_watch_patterns(relative_path, watch_patterns):
    """An empty WatchPatterns list watches everything, as the service does."""
    return not watch_patterns or matches_any(relative_path, watch_patterns)


def accepts(server, relative_path):
    include = server.get("includePatterns") or []
    exclude = server.get("excludePatterns") or []
    if include and not matches_any(relative_path, include):
        return False
    return not matches_any(relative_path, exclude)


def extension_of(pattern):
    """The extension a *.ext watch pattern selects, else None.

    "*.*" and every other wildcard shape return None. The caller refuses to run
    on a None it cannot express as a find predicate rather than scanning less
    than the distributor ships -- a narrowed scan reports a clean fleet for the
    paths it never looked at, which is the failure this whole check exists to
    stop reproducing.
    """
    if pattern.startswith("*.") and "*" not in pattern[2:] and len(pattern) > 2:
        return pattern[2:]
    return None


# ------------------------------------------------------------------- config io
def load_distributor_config(directory):
    """WatchDirectory, WatchPatterns and the target list, from the live config.

    Auth fields are dropped on the way in: nothing downstream can print a
    credential it was never handed, and this report is published to a PUBLIC
    repository as a GitHub issue and a run artifact.
    """
    app = directory / "appsettings.json"
    srv = directory / "servers.json"
    try:
        settings = json.loads(app.read_text(encoding="utf-8")).get("AppSettings") or {}
    except Exception as exc:
        raise SystemExit("ERROR: cannot read %s: %s" % (app, exc))
    try:
        raw_servers = json.loads(srv.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit("ERROR: cannot read %s: %s" % (srv, exc))
    if not isinstance(raw_servers, list) or not raw_servers:
        raise SystemExit("ERROR: %s is not a non-empty array" % srv)

    watch_dir = Path(settings.get("WatchDirectory") or "/home/dod/distribute")
    watch_patterns = list(settings.get("WatchPatterns") or [])

    keep = ("name", "host", "port", "remoteBasePath", "enabled",
            "includePatterns", "excludePatterns")
    servers = [dict((k, s.get(k)) for k in keep if k in s) for s in raw_servers]
    return watch_dir, watch_patterns, servers


def load_fleet_config():
    path = Path(os.environ.get("KTP_AUDIT_FLEET_CONFIG", "/etc/ktp/audit-fleet.json"))
    if not path.exists():
        raise SystemExit("ERROR: fleet config not found at %s "
                         "(see scripts/audit-fleet.json.example)" % path)
    try:
        hosts = json.loads(path.read_text(encoding="utf-8")).get("hosts")
    except Exception as exc:
        raise SystemExit("ERROR: parsing %s: %s" % (path, exc))
    if not isinstance(hosts, list) or not hosts:
        raise SystemExit("ERROR: %s has no non-empty hosts array" % path)
    return hosts


# ---------------------------------------------------------------- source side
def source_inventory(watch_dir, watch_patterns):
    """relative path -> (md5, mtime) for every watched file under the tree."""
    inventory = {}
    for path in watch_dir.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(watch_dir).as_posix()
        if not matches_watch_patterns(rel, watch_patterns):
            continue
        digest = hashlib.md5()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        inventory[rel] = (digest.hexdigest(), int(path.stat().st_mtime))
    return inventory


# -------------------------------------------------------------- instance side
def build_find_command(base, extensions, watch_everything):
    """One read-only command per target. Writes nothing on the remote host."""
    if watch_everything:
        predicate = ""
    else:
        names = " -o ".join("-iname '*.%s'" % e.replace("'", "") for e in extensions)
        predicate = " \\( " + names + " \\)"
    return ("cd %s 2>/dev/null || { echo __NOBASE__; exit 0; }; "
            "find .%s -type f -print0 | ionice -c3 nice -n19 xargs -0 md5sum"
            % (base, predicate))


def parse_md5_output(text):
    if "__NOBASE__" in text:
        return None
    out = {}
    for line in text.splitlines():
        if "  " not in line:
            continue
        digest, rel = line.split("  ", 1)
        out[rel[2:] if rel.startswith("./") else rel] = digest
    return out


def ssh_connect(host_cfg, timeout=45):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs = dict(hostname=host_cfg["host"], username=host_cfg["user"],
                  timeout=timeout, allow_agent=False, look_for_keys=False)
    if host_cfg.get("key_filename"):
        kwargs["key_filename"] = host_cfg["key_filename"]
    else:
        kwargs["password"] = host_cfg.get("password")
    client.connect(**kwargs)
    return client


def run_remote(client, command, timeout=900):
    _, stdout, _ = client.exec_command(command, timeout=timeout)
    return stdout.read().decode("utf-8", "replace")


# ------------------------------------------------------------------ comparison
def classify(per_target, source_hash, total):
    """The SHAPE of a divergence, which is what decides what to do about it.

    per-instance  every target holds a different hash -> the file carries
                  per-instance data and is missing an excludePatterns entry.
                  A standing hazard: one touch of the source overwrites all of
                  it with a single copy.
    uniform       every target agrees with every other and none with the source
                  -> a fleet-wide edit that was never mirrored back. This is the
                  discord.ini shape, and the one on a timer.
    absent        no target has the file at all -> usually a file that predates
                  the distributor and has not changed since, so no event has
                  ever fired for it. Kept apart from `partial` because the two
                  read the same in a count and mean opposite things: `partial`
                  is a delivery that went wrong, `absent` is one that never
                  started.
    partial       some targets match the source and some do not -> a push that
                  reached part of the fleet, or reached it once and not since.
    """
    present = [h for h in per_target.values() if h is not None]
    distinct = set(present)
    if not present:
        return "absent" if len(per_target) == total else "partial"
    if len(per_target) == total and len(present) > 1 and len(distinct) == len(present):
        return "per-instance"
    if len(per_target) == total and len(distinct) == 1 and source_hash not in distinct:
        return "uniform"
    return "partial"


def build_report(watch_dir, source, findings, reached, targets, unreachable, verbose):
    """The markdown report, the gate's stable lines, and the hazard count."""
    lines = ["# Distribute-tree drift", "",
             "Source: `%s` (%d watched file(s))." % (watch_dir, len(source)), ""]
    stable = []
    hazards = 0
    if findings:
        lines.append("| path | shape | targets | direction |")
        lines.append("|---|---|---|---|")
    for rel in sorted(findings):
        per_target = findings[rel]
        source_hash = source[rel][0]
        shape = classify(per_target, source_hash, len(reached))
        missing = [n for n, h in per_target.items() if h is None]
        if len(missing) == len(per_target):
            direction = "never delivered"
        elif missing:
            direction = "source-newer (delivery incomplete)"
        else:
            direction = "differs"
        if shape == "per-instance":
            hazards += 1
        lines.append("| `%s` | %s | %d/%d | %s |"
                     % (rel, shape, len(per_target), len(reached), direction))
        stable.append("DRIFT: %s shape=%s targets=%d src=%s"
                      % (rel, shape, len(per_target), source_hash[:HASH_CHARS]))
        if verbose:
            for name, actual in sorted(per_target.items()):
                lines.append("|   | | `%s` | %s |"
                             % (name, "absent" if actual is None else actual[:HASH_CHARS]))
    if not findings:
        lines.append("No divergence: every watched path matches on every target.")
    lines.append("")
    if hazards:
        lines.append("**%d path(s) carry per-instance data and are in no "
                     "`excludePatterns`.** The distributor would overwrite all of "
                     "it with one copy on the next touch of the source. The fix is "
                     "an `excludePatterns` entry on the game entries in "
                     "`servers.json`, which both stops the push and closes this "
                     "finding." % hazards)
        lines.append("")
    if unreachable:
        lines.append("Unreachable: %s" % ", ".join(sorted(unreachable)))
        lines.append("")
    lines.append("targets reached: %d/%d  paths with drift: %d  per-instance hazards: %d"
                 % (len(reached), len(targets), len(findings), hazards))
    return "\n".join(lines) + "\n", stable, hazards


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", help="write the markdown report here as well as stdout")
    parser.add_argument("--state", help="JSON state file; enables the +new/-resolved line")
    parser.add_argument("--distributor-dir", default=os.environ.get(
        "KTP_DISTRIBUTOR_DIR", DEFAULT_DISTRIBUTOR_DIR))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    dist_dir = Path(args.distributor_dir)
    watch_dir, watch_patterns, servers = load_distributor_config(dist_dir)
    if not watch_dir.is_dir():
        print("ERROR: watch directory %s does not exist -- run this on the data "
              "server" % watch_dir, file=sys.stderr)
        return EXIT_BROKEN

    watch_everything = not watch_patterns or "*.*" in watch_patterns
    extensions = []
    if not watch_everything:
        for pattern in watch_patterns:
            ext = extension_of(pattern)
            if ext is None:
                print("ERROR: WatchPatterns contains %r, which this check cannot "
                      "express as a find predicate. Scanning less than the "
                      "distributor ships would report the unscanned paths clean."
                      % pattern, file=sys.stderr)
                return EXIT_BROKEN
            extensions.append(ext)

    fleet = dict((h["host"], h) for h in load_fleet_config())
    targets = [s for s in servers if s.get("enabled", True)
               and s.get("host") in fleet and s.get("remoteBasePath")]
    if not targets:
        print("ERROR: no enabled target in servers.json resolves to a host in the "
              "fleet config. Nothing was checked.", file=sys.stderr)
        return EXIT_BROKEN

    source = source_inventory(watch_dir, watch_patterns)
    print("source: %d watched file(s) under %s" % (len(source), watch_dir), file=sys.stderr)
    print("targets: %d of %d servers.json entries (entries on hosts outside the "
          "fleet config, such as FastDL, are not game instances and are out of "
          "scope here)" % (len(targets), len(servers)), file=sys.stderr)

    by_host = {}
    for target in targets:
        by_host.setdefault(target["host"], []).append(target)

    def sweep_host(host):
        out = {}
        client = ssh_connect(fleet[host])
        try:
            for target in by_host[host]:
                command = build_find_command(target["remoteBasePath"], extensions,
                                             watch_everything)
                out[target["name"]] = parse_md5_output(run_remote(client, command))
        finally:
            client.close()
        return out

    results = {}
    unreachable = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(by_host)) as pool:
        futures = dict((pool.submit(sweep_host, h), h) for h in by_host)
        for future in concurrent.futures.as_completed(futures):
            host = futures[future]
            try:
                results.update(future.result())
            except Exception as exc:
                for target in by_host[host]:
                    unreachable.append("%s (%s)" % (target["name"], type(exc).__name__))

    findings = {}
    for name, listing in sorted(results.items()):
        if listing is None:
            unreachable.append("%s (remote base path absent)" % name)
            continue
        target = next(t for t in targets if t["name"] == name)
        for rel, (source_hash, _mtime) in source.items():
            if not accepts(target, rel):
                continue
            actual = listing.get(rel)
            if actual != source_hash:
                findings.setdefault(rel, {})[name] = actual

    reached = [n for n, v in results.items() if v is not None]
    report, stable, hazards = build_report(watch_dir, source, findings, reached,
                                           targets, unreachable, args.verbose)
    report = redact_diagnostic(report)
    sys.stdout.write(report)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8", newline="\n")

    for line in stable:
        print(redact_diagnostic(line), file=sys.stderr)
    print("hazards: %d" % hazards, file=sys.stderr)
    print("targets reached: %d/%d" % (len(reached), len(targets)), file=sys.stderr)

    if args.state:
        state_path = Path(args.state)
        try:
            previous = set(json.loads(state_path.read_text(encoding="utf-8")).get("paths", []))
        except Exception:
            previous = set()
        current = set(findings)
        print("Distribute-drift delta vs last run: +%d new, -%d resolved"
              % (len(current - previous), len(previous - current)), file=sys.stderr)
        try:
            state_path.write_text(json.dumps({"paths": sorted(current)}, indent=1),
                                  encoding="utf-8", newline="\n")
        except OSError:
            pass  # a read-only checkout must not fail the check

    return EXIT_DRIFT if (findings or unreachable) else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
