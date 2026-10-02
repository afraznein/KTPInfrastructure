#!/usr/bin/env python3
"""Which config KEY on the fleet is not mirrored into the distributed source?

WHY THIS EXISTS, AND WHY THE FILE-LEVEL CHECK WAS NOT ENOUGH

On 2026-08-19 a seven-month-old copy of addons/ktpamx/configs/discord.ini was
pushed to /home/dod/distribute with only its auth secret changed. The push
reverted `discord_channel_id` to a dead channel and deleted
`discord_channel_id_default` outright, on all 24 instances, in about fifteen
seconds. Both had been set directly on the instances months earlier and never
mirrored back into the source. Nothing reported it. Match-start embeds stopped
posting, on exactly three Sundays, and it surfaced six weeks later -- because
the failing path is reachable only by competitive `.ktp` play and none ran
between June and September.

⚠️ The alert that was supposed to catch it was a COUNT OF FAILURES, and it was
zero. Not because the code was healthy, but because the code never ran. That is
the lesson this check is built around: an absence of failures is not evidence of
health, so every number printed below is WORK DONE -- instances compared, paths
compared, keys compared -- and the exit code distinguishes "agrees" from "never
compared". There is no output of this script that reads as clean without saying
how much it actually looked at.

⚠️ And the real defect is not the channel id. It is that ANY per-instance config
edit not mirrored into the distributed source is on a timer: the next time
anyone touches that file at the source, the distributor reverts it fleet-wide.
`audit-distribute-drift.py` already guards the file-level form of that invariant
and is the first line of defence. This check is the key-level form, and it is
additive in three ways that the 2026-08-19 incident specifically needed:

  1. IT NAMES THE KEY. The file-level check says `discord.ini differs`, and the
     standing report currently carries 39 paths in that state -- long-standing,
     triaged, and exactly the kind of list a human skims. A new key appearing
     inside an already-drifted file is invisible in it. `discord_channel_id` and
     `discord_channel_id_default` are two findings here, not one row.
  2. IT SEPARATES "value changed" FROM "key deleted". md5 cannot: both are
     `differs`. The deleted routing key was the half that actually broke the
     embeds and the half nobody noticed, because a missing key is not an error
     anywhere in the stack -- KTPMatchHandler reads a missing key as "feature
     disabled" and posts nothing, successfully.
  3. IT REPORTS THE DIRECTION PER KEY. A key the fleet has and the source does
     not is one finding kind (`source-missing`); a key the source has and the
     fleet does not is another (`instance-missing`). They mean opposite things
     and need opposite fixes.

SCOPE COMES FROM THE DISTRIBUTOR, NEVER FROM A LIST HERE

Which paths and which targets are read out of the distributor's own two config
files -- `WatchPatterns` in appsettings.json, `includePatterns` /
`excludePatterns` per target in servers.json -- by importing
`audit-distribute-drift.py` rather than reimplementing the match. A second
matcher would be a second source of truth free to disagree with the one that
decides what really ships, and narrowing scope to look quiet is how an unscanned
path gets reported clean.

The ONE list in this file, `REQUIRED_PARSABLE`, is not a scope allow-list and
cannot make anything pass: a path named there which is absent, unparsable, or
not fully covered forces exit 2. It only ever makes the check louder. The
estate's rule that an allow-list gate is blind to removals is about gates that
grant a pass; this one grants nothing.

NO VALUE IS EVER PRINTED. NOT EVEN A DIGEST.

discord.ini mixes a fleet-wide secret with per-instance routing, users.ini
carries admin passwords, ktp.ini carries the live season match password -- and
the weekly audit publishes its artifacts to a PUBLIC repository. So the report
carries key NAMES, directions, shapes and counts, and nothing else. Values are
compared in memory by digest and the digests are not printed either: a digest of
a 19-digit channel id or a short password is a brute-forceable oracle, and there
is no finding here that needs one. The operator reads the value on the box.
Key names themselves are redacted by shape where a name can BE identity or a
credential (a SteamID, a 17-digit id, a quoted admin name in users.ini), and the
whole report then goes through audit_redact.redact_diagnostic as a backstop.

READ-ONLY, AND SPECIFICALLY READ-ONLY IN THE DEPLOY TREE

/home/dod/distribute is a live deploy path: the distributor pushes any created
or changed file to all 24 instances within ~15s and syncs deletions, so a
scratch file written there would be a fleet-wide deploy and a `*.bak-*` would
reach FastDL. This script opens the tree for reading and nothing else. On the
instance side it runs one `cat` loop under ionice/nice, writes no scratch file,
and restarts nothing.

EXIT CODES -- the estate's contract
    0  every expected instance compared, and every key agrees
    1  findings: at least one key differs, or is missing from either side
    2  THE CHECK DID NOT RUN. Fewer instances covered than expected, a host
       unreachable, a required path unparsable, a zero-length key set, no
       credential source. A 2 is never clean; it means the question was not
       answered.

Usage
    python3 audit-config-key-drift.py [--out report.md] [--state FILE]
                                      [--path REL]... [--expect-instances 24]
                                      [--verbose]
    python3 audit-config-key-drift.py --selftest    # no fleet, no credentials

Credentials come from /etc/ktp/audit-fleet.json (or $KTP_AUDIT_FLEET_CONFIG),
the same file the rest of the fleet audit uses, so none is stored in GitHub.
Off the data server, point $KTP_HOSTS_MODULE at a local ktp_hosts.py instead;
either source is read for addresses and auth only, and neither is printed.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

EXIT_OK, EXIT_FINDINGS, EXIT_CANNOT_RUN = 0, 1, 2

# Paths whose key loss disables a feature with no error anywhere, so a run that
# could not compare them has answered nothing. Absent, unparsable, or short of
# full instance coverage here is exit 2. See the header: this list can only make
# the check fail.
REQUIRED_PARSABLE = ("addons/ktpamx/configs/discord.ini",)

# Only a text config can carry a key. Everything else the distributor ships
# (.bsp/.wad/.spr/...) is out of scope by construction rather than by omission.
KEYED_SUFFIXES = (".ini", ".cfg")

# Key names that can themselves BE identity or a credential. Shape, not a
# denylist: users.ini keys the admin by quoted name or SteamID, and the weekly
# audit publishes to a public repository.
_IDENTITY_KEY_RE = re.compile(
    r"""(?ix) ^ (?: ["'].* | STEAM_\d+:\d+:\d+ | \d{15,} ) $ """
)

ISO = "%Y-%m-%dT%H:%M:%SZ"


def now_iso():
    return datetime.now(timezone.utc).strftime(ISO)


def age_text(stamp):
    """How long a finding has been standing, from the state file."""
    try:
        then = datetime.strptime(stamp, ISO).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return "age unknown"
    hours = (datetime.now(timezone.utc) - then).total_seconds() / 3600.0
    if hours < 48:
        return "%dh" % int(hours)
    return "%dd" % int(hours / 24)


# ------------------------------------------------------------------ one matcher
def _load_sibling(filename, module_name):
    """Import a sibling script by path. A dashed filename is not importable."""
    spec = importlib.util.spec_from_file_location(module_name, HERE / filename)
    if spec is None or spec.loader is None:
        return None
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 -- any load failure is "cannot check"
        return None
    return module


# The pattern matcher, the distributor-config reader and the SSH helpers all come
# from the file-level check so the two can never disagree about what the
# distributor would send. A failure to load is exit 2, not a local reimplementation.
DIST = _load_sibling("audit-distribute-drift.py", "_ktp_distribute_drift")

try:
    from audit_redact import redact_diagnostic
except ImportError:  # pragma: no cover - environment guard
    redact_diagnostic = None

try:
    from ktp_config_kv import CVAR, EMPTY, KV, LIST, MIXED, parse_text
except ImportError:  # pragma: no cover - environment guard
    parse_text = None


# ------------------------------------------------------------------ credentials
def load_credentials():
    """{host: {host,user,password|key_filename}} from whichever source exists.

    Two sources because the check runs in two places. On the data server the
    fleet audit's own /etc/ktp/audit-fleet.json is already present and is the
    only thing that should ever hold these. From a workstation, $KTP_HOSTS_MODULE
    names a local ktp_hosts.py. Nothing here is committed and nothing is printed.
    """
    config = Path(os.environ.get("KTP_AUDIT_FLEET_CONFIG", "/etc/ktp/audit-fleet.json"))
    if config.exists():
        try:
            hosts = json.loads(config.read_text(encoding="utf-8")).get("hosts")
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("cannot parse %s: %s" % (config, exc))
        if not isinstance(hosts, list) or not hosts:
            raise RuntimeError("%s has no non-empty hosts array" % config)
        return dict((h["host"], h) for h in hosts if h.get("host"))

    module_path = os.environ.get("KTP_HOSTS_MODULE")
    if module_path and Path(module_path).exists():
        spec = importlib.util.spec_from_file_location("_ktp_hosts", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        out = {}
        # SERVERS is the module's own export; FLEET names the game hosts. Read
        # both rather than assuming either shape -- there is no HOSTS symbol.
        # `key` is renamed to `key_filename` because ssh_connect, which is the
        # fleet audit's, speaks audit-fleet.json's spelling.
        def normalise(entry, name):
            out_entry = dict(entry, name=name)
            if out_entry.pop("key", None):
                out_entry["key_filename"] = entry["key"]
            return out_entry

        servers = getattr(module, "SERVERS", {})
        for name in list(getattr(module, "FLEET", ())) + ["data"]:
            entry = servers.get(name)
            if entry:
                out[entry["host"]] = normalise(entry, name)
        if out:
            return out
        raise RuntimeError("%s exported no usable FLEET/SERVERS entries" % module_path)

    raise RuntimeError(
        "no credential source: %s does not exist and $KTP_HOSTS_MODULE is unset "
        "or missing. Nothing was checked." % config
    )


# ------------------------------------------------------------- source-side read
class LocalSource:
    """The distribute tree on this machine. Opened read-only; never written."""

    def __init__(self, root):
        self.root = Path(root)

    def listing(self):
        out = []
        for path in self.root.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            out.append(path.relative_to(self.root).as_posix())
        return out

    def read(self, rel):
        try:
            return (self.root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None


class RemoteSource:
    """The distribute tree on the data server, over SFTP. Read-only by API use.

    Exists so the check runs from a workstation without a copy of the tree, and
    so a reviewer can reproduce a finding without logging into the box. `open`
    for read and `listdir` are the only two calls made.
    """

    def __init__(self, client, root):
        self.sftp = client.open_sftp()
        self.root = root.rstrip("/")

    def listing(self):
        out = []

        def walk(prefix):
            try:
                entries = self.sftp.listdir_attr(prefix or self.root)
            except IOError:
                return
            for entry in entries:
                full = "%s/%s" % (prefix or self.root, entry.filename)
                rel = full[len(self.root) + 1:]
                if entry.st_mode is not None and (entry.st_mode & 0o040000):
                    walk(full)
                else:
                    out.append(rel)

        walk("")
        return out

    def read(self, rel):
        try:
            with self.sftp.open("%s/%s" % (self.root, rel), "r") as handle:
                return handle.read().decode("utf-8", "replace")
        except IOError:
            return None


# ----------------------------------------------------------- instance-side read
#: One command per instance. A `cat` loop, nothing written, nothing executed on
#: the remote beyond coreutils. The marker is long and improbable because a
#: config file is free to contain any short string.
MARKER = "===KTP-CFG-KEY-DRIFT==="


def build_read_command(base, paths):
    quoted = " ".join("'%s'" % p.replace("'", "") for p in paths)
    return (
        "cd %s 2>/dev/null || { echo __NOBASE__; exit 0; }; "
        "for f in %s; do printf '%%s %%s\\n' '%s' \"$f\"; "
        "if [ -f \"$f\" ]; then ionice -c3 nice -n19 cat -- \"$f\"; "
        "else printf '__ABSENT__\\n'; fi; done" % (base, quoted, MARKER)
    )


def split_instance_output(text):
    """{rel: text or None}. None means the file is not on that instance.

    Returns None for the whole instance when the base path is absent, which is
    a could-not-check and never an empty-but-fine listing.
    """
    if "__NOBASE__" in text.split(MARKER, 1)[0]:
        return None
    out = {}
    chunks = text.split(MARKER + " ")
    for chunk in chunks[1:]:
        head, _, body = chunk.partition("\n")
        rel = head.strip()
        out[rel] = None if body.startswith("__ABSENT__\n") or body.strip() == "__ABSENT__" else body
    return out


# -------------------------------------------------------------------- reporting
def redact_key(name):
    return "<key redacted: identity shape>" if _IDENTITY_KEY_RE.match(name) else name


def digest(value):
    """In-memory only. Never printed -- see the header."""
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()


def shape_of(per_instance, covered):
    """uniform / per-instance / partial, the file-level check's vocabulary.

    `uniform` is the 2026-08-19 shape and the one on a timer: every instance
    agrees with every other and none agrees with the source, so the fleet is
    right and the source is stale. `per-instance` means the key legitimately
    varies and the file needs an excludePatterns entry -- or does not, and is one
    touch from being flattened to a single copy.
    """
    present = [d for d in per_instance.values() if d is not None]
    distinct = set(present)
    if not present:
        return "absent"
    if len(per_instance) != covered:
        return "partial"
    if len(distinct) == 1:
        return "uniform"
    if len(distinct) == len(present):
        return "per-instance"
    return "partial"


KIND_MEANING = {
    "source-missing": "on the fleet, NOT in the source -- the next touch of this "
                      "file deletes it on all 24",
    "instance-missing": "in the source, NOT on the fleet -- a push that never "
                        "landed, or landed and was overwritten",
    "differs": "set on both sides to different values -- the next touch of this "
               "file reverts the fleet to the source value",
    "file-missing-instance": "the whole file is absent on at least one instance",
}


def build_report(findings, stats, inconclusive, unreachable, previous, verbose):
    """The markdown report, the gate's stable lines, and the headline."""
    lines = [
        "# Config key drift: fleet vs `%s`" % stats["source_root"],
        "",
        "Key-level comparison of every watched `.ini`/`.cfg` the distributor "
        "would send, against what each instance holds. No value is printed; see "
        "the script header.",
        "",
    ]
    stable = []

    if findings:
        lines += ["| path | key | kind | shape | instances | standing |",
                  "|---|---|---|---|---|---|"]
    for (rel, key, kind) in sorted(findings):
        detail = findings[(rel, key, kind)]
        shape = detail["shape"]
        first_seen = previous.get("%s|%s|%s" % (rel, key, kind), {}).get("first_seen_utc")
        lines.append("| `%s` | `%s` | %s | %s | %d/%d | %s |" % (
            rel, redact_key(key), kind, shape, detail["count"],
            stats["instances_compared"],
            age_text(first_seen) if first_seen else "new this run"))
        stable.append("KEYDRIFT: %s key=%s kind=%s shape=%s instances=%d"
                      % (rel, redact_key(key), kind, shape, detail["count"]))
        if verbose:
            for name in sorted(detail["instances"]):
                lines.append("|   | | | | `%s` | |" % name)

    if not findings:
        lines.append("No key drift: every compared key agrees with the source "
                     "on every instance compared.")
    lines.append("")

    kinds = sorted(set(k for _, _, k in findings))
    if kinds:
        lines.append("### What each kind means")
        lines.append("")
        for kind in kinds:
            lines.append("- **`%s`** -- %s" % (kind, KIND_MEANING.get(kind, "")))
        lines.append("")

    if inconclusive:
        lines.append("### Could not compare (%d) -- these are NOT clean" % len(inconclusive))
        lines.append("")
        lines.append("| path | why |")
        lines.append("|---|---|")
        for rel, why in sorted(inconclusive.items()):
            lines.append("| `%s` | %s |" % (rel, why))
            stable.append("KEYDRIFT-INCONCLUSIVE: %s %s" % (rel, why))
        lines.append("")

    if unreachable:
        lines.append("Unreachable: %s" % ", ".join(sorted(unreachable)))
        lines.append("")
        for item in sorted(unreachable):
            stable.append("KEYDRIFT-UNREACHABLE: %s" % item)

    # The headline is WORK DONE, in the order a reader needs it. "findings: 0"
    # alone was the 2026-08-19 alert, and it was zero because nothing ran.
    headline = ("instances compared: %d/%d  paths compared: %d/%d  "
                "keys compared: %d  findings: %d  inconclusive: %d  "
                "nothing-to-compare: %d"
                % (stats["instances_compared"], stats["instances_expected"],
                   stats["paths_compared"], stats["paths_in_scope"],
                   stats["keys_compared"], len(findings), len(inconclusive),
                   stats["paths_with_nothing_to_compare"]))
    lines.append(headline)
    return "\n".join(lines) + "\n", stable, headline


# ------------------------------------------------------------------- comparison
def compare(source_keys, instance_keys, covered_names, total=None):
    """{(path, key, kind): detail} for one path across every instance that has it.

    Both directions, deliberately. `source-missing` -- a key the fleet has and
    the source does not -- is the half that deleted discord_channel_id_default,
    and it is the half an md5 comparison cannot name and a source-driven loop
    cannot see at all: iterating the source's keys would never visit it.

    `total` is the number of instances the SWEEP reached, which is not always the
    number that held this file. Shape is judged against the sweep so a key found
    on 20 of 24 reads `partial` rather than `uniform` -- `uniform` is read as
    "the whole fleet agrees", and letting it mean "the part of the fleet that
    happened to have the file agrees" is the vacuous reading this check exists
    to refuse.
    """
    if total is None:
        total = len(covered_names)
    out = {}
    comparisons = 0

    union = set(source_keys)
    for keys in instance_keys.values():
        union |= set(keys)

    for key in sorted(union):
        in_source = key in source_keys
        # kind -> {instance name: digest of the instance's value}. A digest so
        # shape_of can tell the 24 apart; never printed, never stored.
        by_kind = {}
        for name in covered_names:
            keys = instance_keys.get(name)
            if keys is None:
                continue
            comparisons += 1
            if key not in keys:
                if in_source:
                    by_kind.setdefault("instance-missing", {})[name] = None
            elif not in_source:
                by_kind.setdefault("source-missing", {})[name] = digest(keys[key])
            elif keys[key] != source_keys[key]:
                by_kind.setdefault("differs", {})[name] = digest(keys[key])

        for kind, per_instance in by_kind.items():
            out[(key, kind)] = {
                "count": len(per_instance),
                "instances": sorted(per_instance),
                # An `instance-missing` key has no value on either side to group
                # by, so shape is about WHERE it is missing, not what it holds.
                "shape": ("partial" if len(per_instance) < total
                          else "uniform") if kind == "instance-missing"
                         else shape_of(per_instance, total),
            }
    return out, comparisons


# ------------------------------------------------------------------------- main
def run(args):
    if DIST is None:
        print("ERROR: cannot load audit-distribute-drift.py beside this script; "
              "its pattern matcher is the only definition of what the "
              "distributor would send. Nothing was checked.", file=sys.stderr)
        return EXIT_CANNOT_RUN
    if parse_text is None or redact_diagnostic is None:
        print("ERROR: ktp_config_kv.py / audit_redact.py must sit beside this "
              "script. Nothing was checked.", file=sys.stderr)
        return EXIT_CANNOT_RUN

    try:
        import paramiko  # noqa: F401
    except ImportError:
        print("ERROR: paramiko not installed. Nothing was checked.", file=sys.stderr)
        return EXIT_CANNOT_RUN

    try:
        fleet = load_credentials()
    except RuntimeError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return EXIT_CANNOT_RUN

    # --- the distributor's own config, local if present, else over SSH.
    dist_dir = Path(args.distributor_dir)
    data_client = None
    if (dist_dir / "servers.json").exists():
        try:
            watch_dir, watch_patterns, servers = DIST.load_distributor_config(dist_dir)
        except SystemExit as exc:
            print("ERROR: %s" % exc, file=sys.stderr)
            return EXIT_CANNOT_RUN
        source = LocalSource(watch_dir)
        if not Path(watch_dir).is_dir():
            print("ERROR: %s is not a directory here. Nothing was checked."
                  % watch_dir, file=sys.stderr)
            return EXIT_CANNOT_RUN
    else:
        host = args.source_host
        if not host:
            print("ERROR: the distributor config is not readable at %s, and no "
                  "--source-host / $KTP_SOURCE_HOST was given to read it over "
                  "SFTP. Nothing was checked." % dist_dir, file=sys.stderr)
            return EXIT_CANNOT_RUN
        if host not in fleet:
            print("ERROR: source host %s is not in the credential source, so "
                  "the distribute tree cannot be read. Nothing was checked."
                  % host, file=sys.stderr)
            return EXIT_CANNOT_RUN
        try:
            data_client = DIST.ssh_connect(fleet[host])
            sftp = data_client.open_sftp()
            settings = json.loads(sftp.open("%s/appsettings.json" % dist_dir.as_posix())
                                  .read().decode("utf-8")).get("AppSettings") or {}
            raw_servers = json.loads(sftp.open("%s/servers.json" % dist_dir.as_posix())
                                     .read().decode("utf-8"))
            sftp.close()
        except Exception as exc:  # noqa: BLE001
            print("ERROR: cannot read the distributor config on %s: %s. Nothing "
                  "was checked." % (host, type(exc).__name__), file=sys.stderr)
            return EXIT_CANNOT_RUN
        watch_dir = settings.get("WatchDirectory") or "/home/dod/distribute"
        watch_patterns = list(settings.get("WatchPatterns") or [])
        keep = ("name", "host", "port", "remoteBasePath", "enabled",
                "includePatterns", "excludePatterns")
        servers = [dict((k, s.get(k)) for k in keep if k in s) for s in raw_servers]
        source = RemoteSource(data_client, str(watch_dir))

    # --- targets: enabled servers.json entries that resolve to a fleet host.
    targets = [s for s in servers if s.get("enabled", True)
               and s.get("host") in fleet and s.get("remoteBasePath")]
    if not targets:
        print("ERROR: no enabled servers.json target resolves to a credentialled "
              "host. Nothing was checked.", file=sys.stderr)
        return EXIT_CANNOT_RUN

    # A partial sweep reported as clean IS the 2026-08-19 incident, so the
    # expected count is asserted before anything is compared. A servers.json
    # short of 24 game entries is itself the bug class -- an instance the
    # distributor does not know about receives nothing and drifts forever.
    if len(targets) != args.expect_instances:
        print("ERROR: %d game target(s) in servers.json, expected %d. Either an "
              "instance was added without an entry or an entry was lost; both "
              "mean this check cannot speak for the fleet."
              % (len(targets), args.expect_instances), file=sys.stderr)
        return EXIT_CANNOT_RUN

    # --- scope: watched, keyed, and not narrowed by anything in this file.
    try:
        listing = source.listing()
    except Exception as exc:  # noqa: BLE001
        print("ERROR: cannot list %s: %s. Nothing was checked."
              % (watch_dir, type(exc).__name__), file=sys.stderr)
        return EXIT_CANNOT_RUN

    scope = sorted(set(
        rel for rel in listing
        if rel.lower().endswith(KEYED_SUFFIXES)
        and DIST.matches_watch_patterns(rel, watch_patterns)
    ) | set(REQUIRED_PARSABLE))
    if args.path:
        wanted = set(args.path)
        unknown = sorted(wanted - set(scope))
        scope = [rel for rel in scope if rel in wanted]
        if unknown:
            print("ERROR: --path named %s, which is not in the distributor's "
                  "scope. A narrowed run that silently drops a path reports it "
                  "clean." % ", ".join(unknown), file=sys.stderr)
            return EXIT_CANNOT_RUN
    if not scope:
        print("ERROR: no watched .ini/.cfg in scope. An empty key list is the "
              "vacuous pass this check exists to avoid.", file=sys.stderr)
        return EXIT_CANNOT_RUN

    # --- source side.
    source_parsed, inconclusive = {}, {}
    for rel in scope:
        text = source.read(rel)
        if text is None:
            inconclusive[rel] = "absent from the source tree"
            continue
        flavour, keys = parse_text(text, rel)
        if keys is None:
            inconclusive[rel] = ("source lines disagree about the flavour "
                                 "(`key = value` and bare-token lines in one "
                                 "file); no reader can be chosen without "
                                 "inventing keys")
            continue
        # An EMPTY source is kept, not skipped. Against a populated instance
        # every key there becomes `source-missing`, which is the 2026-08-19
        # revert taken to its limit -- skipping it would be a silent pass in the
        # one direction that matters.
        source_parsed[rel] = (flavour, keys)

    # --- instance side: one SSH session per host, one command per instance.
    by_host = {}
    for target in targets:
        by_host.setdefault(target["host"], []).append(target)

    def sweep(host):
        out = {}
        client = DIST.ssh_connect(fleet[host])
        try:
            for target in by_host[host]:
                wanted = [rel for rel in scope if DIST.accepts(target, rel)]
                if not wanted:
                    out[target["name"]] = {}
                    continue
                text = DIST.run_remote(
                    client, build_read_command(target["remoteBasePath"], wanted))
                out[target["name"]] = split_instance_output(text)
        finally:
            client.close()
        return out

    results, unreachable = {}, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(by_host))) as pool:
        futures = dict((pool.submit(sweep, h), h) for h in by_host)
        for future in concurrent.futures.as_completed(futures):
            host = futures[future]
            try:
                results.update(future.result())
            except Exception as exc:  # noqa: BLE001
                for target in by_host[host]:
                    unreachable.append("%s (%s)" % (target["name"], type(exc).__name__))
    if data_client is not None:
        data_client.close()

    covered = []
    for name, listing_ in sorted(results.items()):
        if listing_ is None:
            unreachable.append("%s (remote base path absent)" % name)
        else:
            covered.append(name)

    # --- compare, per path, across every covered instance.
    findings, keys_compared, paths_compared = {}, 0, 0
    empty_both = []
    for rel, (flavour, source_keys) in sorted(source_parsed.items()):
        instance_keys, bad = {}, []
        for name in covered:
            target = next(t for t in targets if t["name"] == name)
            if not DIST.accepts(target, rel):
                continue
            text = (results[name] or {}).get(rel)
            if text is None:
                bad.append(name)
                continue
            _, keys = parse_text(text, rel)
            if keys is None:
                bad.append(name)
                continue
            instance_keys[name] = keys

        if bad:
            findings[(rel, "<whole file>", "file-missing-instance")] = {
                "count": len(bad), "instances": sorted(bad),
                "shape": "partial" if len(bad) < len(covered) else "absent"}
        if not instance_keys:
            inconclusive[rel] = ("on no covered instance, or unparsable on all "
                                 "%d" % len(covered))
            continue
        path_findings, comparisons = compare(source_keys, instance_keys,
                                             sorted(instance_keys),
                                             total=len(covered))
        if comparisons == 0:
            # Both sides hold zero keys. Nothing was compared, so this path is
            # not evidence of agreement -- it is the vacuous pass by another
            # name, and it says so instead of adding to `paths compared`.
            empty_both.append(rel)
        paths_compared += 1
        keys_compared += comparisons
        for (key, kind), detail in path_findings.items():
            findings[(rel, key, kind)] = detail

    stats = {
        "source_root": str(watch_dir),
        "instances_expected": args.expect_instances,
        "instances_compared": len(covered),
        "paths_in_scope": len(scope),
        "paths_compared": paths_compared,
        "keys_compared": keys_compared,
        # Both sides empty: compared, agreeing, and carrying no evidence. Kept
        # as its own number so "paths compared" can never be read as "paths that
        # actually had something to say".
        "paths_with_nothing_to_compare": len(empty_both),
    }

    # --- state: the durable timeline. Its mtime is the proof the check ran, and
    # journald has logged nothing on days a unit provably worked.
    previous = {}
    state_path = Path(args.state) if args.state else None
    if state_path:
        try:
            previous = json.loads(state_path.read_text(encoding="utf-8")).get("findings") or {}
        except Exception:  # noqa: BLE001
            previous = {}

    report, stable, headline = build_report(findings, stats, inconclusive,
                                            unreachable, previous, args.verbose)
    report = redact_diagnostic(report)
    sys.stdout.write(report)
    for line in stable:
        print(redact_diagnostic(line), file=sys.stderr)
    print(headline, file=sys.stderr)

    if args.out:
        Path(args.out).write_text(report, encoding="utf-8", newline="\n")

    # A required path that could not be compared answers nothing about the file
    # whose key loss started this.
    required_broken = [rel for rel in REQUIRED_PARSABLE if rel in inconclusive]
    for rel in REQUIRED_PARSABLE:
        key = (rel, "<whole file>", "file-missing-instance")
        if key in findings:
            required_broken.append(rel)
    short = len(covered) != args.expect_instances

    if state_path:
        current = {}
        for (rel, key, kind) in findings:
            ident = "%s|%s|%s" % (rel, key, kind)
            current[ident] = {"first_seen_utc": previous.get(ident, {})
                              .get("first_seen_utc") or now_iso()}
        print("Config-key-drift delta vs last run: +%d new, -%d resolved"
              % (len(set(current) - set(previous)), len(set(previous) - set(current))),
              file=sys.stderr)
        payload = {
            "schema": 1,
            "last_run_utc": now_iso(),
            # Recorded separately from `findings` so a reader can tell "agrees"
            # from "never compared" long after the run.
            "coverage": stats,
            "inconclusive": sorted(inconclusive),
            "unreachable": sorted(unreachable),
            "findings": current,
        }
        if not findings and not inconclusive and not unreachable and not short:
            payload["last_clean_utc"] = now_iso()
        else:
            try:
                payload["last_clean_utc"] = json.loads(
                    state_path.read_text(encoding="utf-8")).get("last_clean_utc")
            except Exception:  # noqa: BLE001
                payload["last_clean_utc"] = None
        try:
            state_path.write_text(json.dumps(payload, indent=1), encoding="utf-8",
                                  newline="\n")
        except OSError:
            pass  # a read-only checkout must not fail the check

    # THE EXIT RULE. 0 is reserved for a run that compared everything it set out
    # to compare and found it all in agreement. Anything less is not clean:
    #   * short coverage, an unreachable target, or a REQUIRED path not compared
    #     means the sweep cannot speak for the fleet -> 2, whatever else it found.
    #   * an unparsable path leaves a real question open. With findings present,
    #     1 already demands attention and the inconclusive table rides along;
    #     with none, 2 -- because the alternative is returning 0 on a run that
    #     did not answer, which is this incident's own failure mode.
    reasons = []
    if short:
        reasons.append("compared %d of %d instances" % (len(covered), args.expect_instances))
    if unreachable:
        reasons.append("%d target(s) unreachable" % len(unreachable))
    if required_broken:
        reasons.append("required path(s) not compared: %s"
                       % ", ".join(sorted(set(required_broken))))
    if reasons:
        print("CHECK DID NOT RUN: %s. This is not a clean result."
              % "; ".join(reasons), file=sys.stderr)
        return EXIT_CANNOT_RUN
    if findings:
        return EXIT_FINDINGS
    if inconclusive:
        print("CHECK INCOMPLETE: no drift among the %d path(s) compared, but %d "
              "could not be parsed and were never compared. Not a clean result."
              % (paths_compared, len(inconclusive)), file=sys.stderr)
        return EXIT_CANNOT_RUN
    return EXIT_OK


# --------------------------------------------------------------------- selftest
def selftest():
    """Reproduce 2026-08-19 offline and assert the check fires on it.

    A guard that cannot be shown to fire on the case that motivated it is not a
    guard, so this runs in CI with no fleet, no credentials and no network. The
    January source below is the real shape of what was pushed: the channel id
    reverted, `discord_channel_id_default` gone, the auth secret the only thing
    that was meant to change. Placeholder values throughout -- no real id or
    secret appears in this repository.
    """
    september_on_the_fleet = (
        "; live config as the instances held it\n"
        "discord_relay_url = https://relay.example/reply\n"
        "discord_auth_secret = NEW_SECRET_PLACEHOLDER\n"
        "discord_channel_id = LIVE_CHANNEL_PLACEHOLDER\n"
        "discord_channel_id_default = DEFAULT_CHANNEL_PLACEHOLDER\n"
        "discord_channel_id_draft = DRAFT_CHANNEL_PLACEHOLDER\n"
    )
    january_source_pushed_on_0819 = (
        "; January copy, auth secret refreshed and nothing else\n"
        "discord_relay_url = https://relay.example/reply\n"
        "discord_auth_secret = NEW_SECRET_PLACEHOLDER\n"
        "discord_channel_id = DEAD_CHANNEL_PLACEHOLDER\n"
        "discord_channel_id_draft = DRAFT_CHANNEL_PLACEHOLDER\n"
    )

    failures = []

    def check(label, condition):
        print("%-4s %s" % ("ok" if condition else "FAIL", label))
        if not condition:
            failures.append(label)

    _, source_keys = parse_text(january_source_pushed_on_0819, "source")
    _, fleet_keys = parse_text(september_on_the_fleet, "fleet")
    names = ["KTP - Atlanta %d" % n for n in range(1, 25)]
    findings, comparisons = compare(source_keys,
                                    dict((n, fleet_keys) for n in names), names)

    check("the reverted channel id is a `differs` finding",
          ("discord_channel_id", "differs") in findings)
    check("the DELETED routing key is a `source-missing` finding -- the "
          "direction an md5 comparison cannot name",
          ("discord_channel_id_default", "source-missing") in findings)
    check("both findings are `uniform`: the fleet agrees with itself and not "
          "with the source, which is the shape on a timer",
          all(findings[k]["shape"] == "uniform"
              for k in (("discord_channel_id", "differs"),
                        ("discord_channel_id_default", "source-missing"))
              if k in findings))
    check("the key that was supposed to change is NOT a finding",
          ("discord_auth_secret", "differs") not in findings)
    check("the untouched keys are not findings", len(findings) == 2)
    check("all 24 instances carry each finding",
          all(d["count"] == 24 for d in findings.values()))
    check("comparisons were actually made (work done, not failures counted)",
          comparisons > 0)

    # The opposite direction: a key the source adds that never landed.
    _, added = parse_text(january_source_pushed_on_0819
                          + "discord_channel_id_12man = NEW_PLACEHOLDER\n", "source2")
    f2, _ = compare(added, dict((n, source_keys) for n in names), names)
    check("a source key absent on the fleet is `instance-missing`",
          ("discord_channel_id_12man", "instance-missing") in f2)

    # Vacuity guards.
    check("a file whose lines disagree about the flavour yields NO key set "
          "(-> could not check, never clean)",
          parse_text("discord_channel_id = 1\nmp_timelimit 30\n", "mixed")[1] is None)
    check("a comment-only file parses to an EMPTY key set, not to None -- so "
          "an emptied source is still compared",
          parse_text("; nothing here\n\n", "empty")[1] == {})
    f4, c4 = compare({}, dict((n, fleet_keys) for n in names), names, total=24)
    check("an EMPTIED source against a populated fleet reports every key as "
          "`source-missing` rather than skipping the path",
          len(f4) == len(fleet_keys)
          and all(kind == "source-missing" for _, kind in f4))
    check("comparing two empty sides makes zero comparisons, which the caller "
          "counts as nothing-to-compare rather than as agreement",
          compare({}, {"a": {}}, ["a"], total=1)[1] == 0)

    # Comment handling. The first live run reported `;` and `#` as drifting keys.
    check("a trailing `;` comment is not a value",
          parse_text("admin.amxx\t; admin base\n", "p")[1] == {"admin.amxx": ""})
    check("a full-line `#` comment is not a key",
          "#" not in (parse_text("# note\nmp_timelimit 30\n", "c")[1] or {}))
    check("`//` inside a URL survives",
          parse_text("discord_relay_url = https://relay.example/reply\n", "d")[1]
          ["discord_relay_url"] == "https://relay.example/reply")
    check("a `;` inside a quoted value survives",
          parse_text('hostname "KTP;1"\n', "c")[1]["hostname"] == "KTP;1")

    # Repeated cvars are positional, so a deleted exec line is a named finding.
    _, three = parse_text("exec a.cfg\nexec b.cfg\nexec c.cfg\n", "s")
    _, two = parse_text("exec a.cfg\nexec b.cfg\n", "i")
    f5, _ = compare(three, {"i": two}, ["i"], total=1)
    check("a dropped third `exec` line is a named finding (`exec#3`), which a "
          "last-wins collapse would lose",
          ("exec#3", "instance-missing") in f5)

    # Partial coverage must not read as agreement.
    partial = dict((n, fleet_keys) for n in names[:20])
    f3, _ = compare(source_keys, partial, sorted(partial), total=24)
    check("a key found on 20 of 24 reports shape `partial`, never `uniform`",
          f3[("discord_channel_id", "differs")]["shape"] == "partial")

    print()
    if failures:
        print("SELFTEST FAILED: %d assertion(s)" % len(failures))
        return EXIT_FINDINGS
    print("SELFTEST PASSED: the 2026-08-19 revert fires in both directions.")
    return EXIT_OK


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", help="write the markdown report here too")
    parser.add_argument("--state", help="JSON state file; the durable timeline")
    parser.add_argument("--distributor-dir", default=os.environ.get(
        "KTP_DISTRIBUTOR_DIR", "/opt/ktp-file-distributor"))
    # No baked address. On the data server the distributor config is local and
    # this is never needed; off the box the caller names the host. One fewer
    # copy of an address to go stale, in a PUBLIC repository.
    parser.add_argument("--source-host", default=os.environ.get("KTP_SOURCE_HOST"),
                        help="read the distribute tree over SFTP from this host "
                             "when the distributor config is not local")
    parser.add_argument("--path", action="append", default=[],
                        help="narrow to this relative path (repeatable)")
    parser.add_argument("--expect-instances", type=int, default=int(
        os.environ.get("KTP_EXPECTED_INSTANCES", "24")))
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--selftest", action="store_true",
                        help="replay 2026-08-19 offline; no fleet, no credentials")
    args = parser.parse_args()

    if args.selftest:
        if parse_text is None:
            print("ERROR: ktp_config_kv.py must sit beside this script.", file=sys.stderr)
            return EXIT_CANNOT_RUN
        return selftest()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
