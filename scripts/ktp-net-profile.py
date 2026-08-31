#!/usr/bin/env python3
"""Read the netcode telemetry the 2026-08-27 03:00 wave added -- BOTH halves.

  server side: `[KTP_PROFILE] net:`  from engine 3.22.0.976   -> dod/logs/
  client side: `event=LAGCOMP_*`     from KTPCvarChecker 7.33 -> dod/addons/ktpamx/logs/

They live in DIFFERENT log trees and neither contains the other. Reading one
and concluding about the other returns a clean, wrong zero.

    python scripts/ktp-net-profile.py                 # today, populated samples only
    python scripts/ktp-net-profile.py --date 08/27/2026
    python scripts/ktp-net-profile.py --min-clients 6 # match-sized servers only
    python scripts/ktp-net-profile.py --all           # include idle samples (see below)
    python scripts/ktp-net-profile.py --raw --limit 40

WHY THE DEFAULT IS `--min-clients 1`
------------------------------------
Every counter on an empty server reads zero, so an idle fleet and a healthy one
are indistinguishable. `lagcomp_off=0` on a server with nobody connected is not
evidence of anything. This tool therefore DISCARDS `clients=0` rows by default
and tells you how many it discarded -- a run that reports "0 populated samples"
is the honest answer, not an empty table.

That trap has already produced one false finding on this fleet: 577-807 ms
"stalls" that were map changes on idle instances.

WHERE THE LINES LIVE
--------------------
`dod/logs/` ONLY. Instances keep a second tree at
`dod/addons/ktpamx/logs/`, and it carries ZERO `KTP_PROFILE` files -- a sweep
pointed there returns a clean, wrong zero. Measured 2026-08-27: 598 log files
matched under `dod/logs`, 0 under the amxx tree.

THE LAGCOMP HEARTBEAT IS A CONTROL, NOT NOISE
---------------------------------------------
`LAGCOMP_SAMPLER_OK` fires once per map load. The plugin emits it because an
exceptions-only feature that silently breaks reads IDENTICALLY to a fleet with
no exceptions -- so `LAGCOMP_OFF: 0` means nothing without a heartbeat beside it.
This tool refuses to report the zero as clean when the heartbeat is absent.

cl_lc/cl_lw are OBSERVED, NEVER ENFORCED. v7.25 removed them from enforcement
after an engine-source audit found no exploit; v7.33 re-added observation only.

`net_detail:` IS CONDITIONAL, NOT BROKEN
---------------------------------------
The format string is present in `engine_i486.so` but had emitted 0 lines as of
2026-08-27. Its absence is not a fault; this tool counts it separately so you
can see when it starts firing rather than inferring from silence.

CREDENTIALS -- this repo is PUBLIC, so nothing is hardcoded:
  $KTP_FLEET_SSH_PASSWORD, else ~/.ktp_fleet_ssh_password, else a local
  ktp_hosts.py if one is importable (workstation convenience only).
"""

from __future__ import annotations

import argparse
import os
import re
import statistics
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

try:
    import paramiko
except ImportError:
    raise SystemExit("paramiko is required:  pip install paramiko")

FLEET = {
    "atlanta": "74.91.121.9",
    "dallas": "74.91.126.55",
    "denver": "66.163.114.109",
    "newyork": "74.91.123.64",
    "chicago": "172.238.176.101",
}
SSH_USER = "dodserver"

# clients=0 unlag=1 lagcomp_off=0 ignorecmd_hits=0 drops=0 latzero=0
# choke_peak=0 loss_worst=0 latency_worst=0.0ms jitter_worst=0.0ms
FIELD = re.compile(r"(\w+)=([0-9.]+)")
STAMP = re.compile(r"^L (\d{2}/\d{2}/\d{4}) - (\d{2}:\d{2}:\d{2})")
# Where the actual DoD log line starts within a grep -H `path:L MM/DD/YYYY -
# HH:MM:SS: ...` match. Anchoring on this (not a colon split) is deliberate:
# the path itself can contain colon-adjacent slashes, and the date in the
# stamp ("08/27/2026") contains slashes too, so neither ":" nor "/" alone can
# tell path from content apart -- only the stamp's own shape can.
LOG_START = re.compile(r"L \d{2}/\d{2}/\d{4} - \d{2}:\d{2}:\d{2}")
# grep -H prefixes each match with its source path, e.g.
# /home/dodserver/dod-27017/serverfiles/dod/logs/L082721.log:L 08/27/... --
# this is how a merged per-host stream gets split back into per-instance rows.
INSTANCE = re.compile(r"/dod-(\d+)/")


def _safe_print(*args, **kwargs) -> None:
    """print() that never raises UnicodeEncodeError on a narrow console codec.

    Player names are arbitrary client input; one outside cp1252 used to crash
    the whole report on a Windows console instead of just that row.
    """
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe = tuple(
            a.encode(enc, errors="replace").decode(enc) if isinstance(a, str) else a
            for a in args
        )
        print(*safe, **kwargs)

COUNTERS = ["drops", "latzero", "choke_peak", "loss_worst", "lagcomp_off", "ignorecmd_hits"]
GAUGES = ["latency_worst", "jitter_worst"]


def ssh_password() -> str:
    pw = os.environ.get("KTP_FLEET_SSH_PASSWORD")
    if pw:
        return pw.strip()
    dotfile = os.path.expanduser("~/.ktp_fleet_ssh_password")
    if os.path.exists(dotfile):
        with open(dotfile) as fh:
            return fh.read().strip()
    try:  # workstation convenience; never required, never committed here
        sys.path.insert(0, os.getcwd())
        import ktp_hosts  # type: ignore

        return ktp_hosts.FLEET_SSH_PASSWORD
    except Exception:
        raise SystemExit(
            "No fleet credential. Set $KTP_FLEET_SSH_PASSWORD or write "
            "~/.ktp_fleet_ssh_password."
        )


def harvest(host: str, password: str, date: str, want_detail: bool, timeout: int):
    """Return (net_lines, detail_count, files_scanned, lagcomp_lines, error).

    TWO LOG TREES, and each holds exactly one half of the picture:
      dod/logs/                  -> engine `[KTP_PROFILE] net:`  (server side)
      dod/addons/ktpamx/logs/    -> plugin  `event=LAGCOMP_*`    (client side)
    Neither tree contains the other's lines. A sweep pointed at one and asked
    about the other returns a clean, wrong zero.
    """
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        cli.connect(host, username=SSH_USER, password=password,
                    timeout=timeout, banner_timeout=timeout, auth_timeout=timeout)

        # Log filenames are Lyymmdd.log; the in-line stamp is MM/DD/YYYY. Match
        # on the stamp so a rolled-over file cannot silently drop the tail.
        base = "~/dod-*/serverfiles/dod/logs/*.log"
        amxx = "~/dod-*/serverfiles/dod/addons/ktpamx/logs/*.log"
        # -H (not just omitting -h): GNU grep only prefixes matches with the
        # filename automatically when 2+ files are given, so a night where a
        # host's glob happens to match exactly one file would silently regress
        # to unattributed rows without forcing it. The prefix is what lets a
        # merged per-host stream be split back into per-instance (dod-27015 vs
        # dod-27016, ...) rows downstream -- see INSTANCE / parse().
        cmd = (
            f"grep -H '\\[KTP_PROFILE\\] net:' {base} 2>/dev/null "
            f"| grep -F '{date}' || true"
        )
        out = cli.exec_command(cmd, timeout=timeout * 4)[1].read().decode(errors="replace")

        # Positive control: a zero above must be distinguishable from a bad path.
        files = cli.exec_command(
            f"ls {base} 2>/dev/null | wc -l", timeout=timeout
        )[1].read().decode().strip()

        detail = "0"
        if want_detail:
            # Scoped to --date like `out` above -- unscoped, this was a
            # lifetime-across-retention figure, not a count for this run's date.
            detail = cli.exec_command(
                f"grep -h 'net_detail:' {base} 2>/dev/null | grep -F '{date}' | wc -l || echo 0",
                timeout=timeout * 2,
            )[1].read().decode().strip() or "0"

        # KTPCvarChecker v7.33: cl_lc / cl_lw observation, log-only, never enforced.
        lag = cli.exec_command(
            f"grep -h 'event=LAGCOMP_' {amxx} 2>/dev/null | grep -F '{date}' || true",
            timeout=timeout * 4,
        )[1].read().decode(errors="replace")

        return out.splitlines(), int(detail or 0), int(files or 0), lag.splitlines(), None
    except Exception as exc:  # noqa: BLE001 - reported per host, never swallowed
        return [], 0, 0, [], f"{type(exc).__name__}: {exc}"
    finally:
        cli.close()


def report_lagcomp(lag_by_host: dict) -> None:
    """cl_lc/cl_lw observation from KTPCvarChecker >= 7.33.

    THE HEARTBEAT IS THE CONTROL, and the plugin's own source says why: an
    exceptions-only feature that silently breaks reads IDENTICALLY to a fleet
    with no exceptions. `LAGCOMP_SAMPLER_OK` fires once per map load, so its
    presence is what makes "no LAGCOMP_OFF" mean something.
    """
    ok = off = changed = 0
    offenders: dict[str, dict] = {}
    maps_seen = set()
    for host, lines in lag_by_host.items():
        for ln in lines:
            ev = re.search(r"event=(LAGCOMP_\w+)", ln)
            if not ev:
                continue
            kind = ev.group(1)
            if kind == "LAGCOMP_SAMPLER_OK":
                ok += 1
                m = re.search(r"map=(\S+)", ln)
                if m:
                    maps_seen.add(m.group(1))
                continue
            sid = re.search(r"sid=(\S+)", ln)
            nm = re.search(r"name=(.*?)\s+ip=", ln)
            lc = re.search(r"\blc=(\d)", ln)
            lw = re.search(r"\blw=(\d)", ln)
            key = sid.group(1) if sid else "?"
            rec = offenders.setdefault(key, {"name": nm.group(1) if nm else "?",
                                             "host": host, "n": 0, "lc": lc.group(1) if lc else "?",
                                             "lw": lw.group(1) if lw else "?"})
            rec["n"] += 1
            if kind == "LAGCOMP_OFF":
                off += 1
            elif kind == "LAGCOMP_CHANGED":
                changed += 1

    _safe_print("\ncl_lc / cl_lw observation  (KTPCvarChecker >= 7.33, log-only, never enforced)")
    _safe_print(f"  SAMPLER_OK heartbeats: {ok}   across {len(maps_seen)} distinct map load(s)")
    _safe_print(f"  LAGCOMP_OFF: {off}    LAGCOMP_CHANGED: {changed}")

    if ok == 0:
        _safe_print("  !! NO HEARTBEAT. The zero above is UNMEASURED, not clean --")
        _safe_print("      a broken sampler and a fleet with no offenders look identical.")
        _safe_print("      The heartbeat fires on the first sampled player per map load,")
        _safe_print("      so this is expected until someone actually connects.")
        return
    if not offenders:
        _safe_print("  OK: sampler is alive and found no client with a lag-comp flag off.")
        return
    _safe_print(f"\n  {'steamid':<22} {'name':<18} {'host':<10} lc lw  hits")
    for sid, r in sorted(offenders.items(), key=lambda kv: -kv[1]["n"]):
        # Player names are arbitrary client input -- never assume a console codec.
        _safe_print(f"  {sid:<22} {r['name'][:18]:<18} {r['host']:<10} "
                     f"{r['lc']}  {r['lw']}  {r['n']}")
    _safe_print("  NOTE: log-only by design -- v7.25 removed cl_lc/cl_lw from ENFORCEMENT after an")
    _safe_print("     engine-source audit found no exploit. Do not re-enforce off the back of this.")


def parse(line: str):
    """line is `<source-path>:<log-line>` -- harvest() keeps grep's filename
    prefix specifically so the instance can be recovered here (see INSTANCE).

    Split on where the log line's own stamp starts (LOG_START), not on the
    first colon or "/" -- the path can contain either, and the stamp's date
    ("08/27/2026") contains a "/" too, so those characters alone don't tell
    path from content apart.
    """
    m_start = LOG_START.search(line)
    if m_start:
        path, content = line[: m_start.start()].rstrip(":"), line[m_start.start():]
    else:
        path, content = "", line
    vals = {k: float(v) for k, v in FIELD.findall(content)}
    if "clients" not in vals:
        return None
    m = STAMP.match(content)
    vals["_time"] = m.group(2) if m else "?"
    inst = INSTANCE.search(path)
    vals["_instance"] = inst.group(1) if inst else "?"
    return vals


def main() -> int:
    ap = argparse.ArgumentParser(description="Read [KTP_PROFILE] net: telemetry from the fleet.")
    ap.add_argument("--date", default=datetime.now().strftime("%m/%d/%Y"),
                    help="log date as MM/DD/YYYY (default: today, LOCAL time)")
    ap.add_argument("--min-clients", type=int, default=1,
                    help="discard samples below this client count (default 1)")
    ap.add_argument("--all", action="store_true",
                    help="include idle (clients=0) samples -- they measure nothing")
    ap.add_argument("--raw", action="store_true", help="print matching lines")
    ap.add_argument("--limit", type=int, default=20, help="rows to print with --raw")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--hosts", default="", help="comma-separated subset of fleet hosts")
    args = ap.parse_args()

    floor = 0 if args.all else args.min_clients
    targets = {k: v for k, v in FLEET.items()
               if not args.hosts or k in args.hosts.split(",")}
    password = ssh_password()

    results, errors = {}, {}
    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        futs = {pool.submit(harvest, ip, password, args.date, True, args.timeout): name
                for name, ip in targets.items()}
        for fut in as_completed(futs):
            name = futs[fut]
            lines, detail, files, lag, err = fut.result()
            if err:
                errors[name] = err
            else:
                results[name] = (lines, detail, files, lag)

    # Reached-count first. Without it, a total connection failure renders as a
    # clean fleet -- which has happened on this fleet more than once.
    print(f"hosts reached: {len(results)}/{len(targets)}   date: {args.date}")
    for name, err in errors.items():
        print(f"  !! {name}: {err}")
    if not results:
        print("\nNo hosts reached -- every number below would be a false zero. Aborting.")
        return 2

    total_seen = total_kept = total_files = total_detail = 0
    # Keyed by (host, instance) -- a host runs 4-5 instances, and grep -h used
    # to merge them into one number nobody could split back apart (e.g.
    # "dallas: 719" could not tell DAL4 apart from DAL1).
    per_host, per_instance, samples = {}, defaultdict(lambda: [0, 0]), []
    for name, (lines, detail, files, _lag) in sorted(results.items()):
        kept = []
        for ln in lines:
            v = parse(ln)
            if v is None:
                continue
            total_seen += 1
            inst_counts = per_instance[(name, v["_instance"])]
            inst_counts[0] += 1
            if v["clients"] >= floor:
                kept.append(v)
                inst_counts[1] += 1
                samples.append((name, ln, v))
        per_host[name] = (len(lines), len(kept))
        total_kept += len(kept)
        total_files += files
        total_detail += detail

    print(f"log files scanned: {total_files}   net: lines matched: {total_seen}   "
          f"net_detail: lines: {total_detail}")
    print(f"samples with clients >= {floor}: {total_kept}"
          f"   discarded as idle: {total_seen - total_kept}")

    if total_files == 0:
        print("\n0 log files matched -- that is a PATH failure, not an empty fleet.")
        return 2

    if not total_kept:
        print("\nNO POPULATED SAMPLES.")
        print("Every net: line on this date was from a server with fewer than "
              f"{floor} client(s), so nothing here measures netcode.")
        print("This is an honest empty result, not a healthy fleet. Re-run during "
              "a match, or pass --all to inspect the idle rows.")
        if total_detail == 0:
            print("net_detail: is also silent -- expected; it is conditional, and "
                  "its format string IS present in the engine binary.")
        # Independent of net: -- the client-side half can be informative even
        # when the server-side half has no populated samples. Reported on the
        # populated path too; keep BOTH calls or the section vanishes on exactly
        # one of the two exits.
        report_lagcomp({n: v[3] for n, v in results.items()})
        return 1

    print("\nper host           net: lines   populated")
    for name, (seen, kept) in sorted(per_host.items()):
        print(f"  {name:<16} {seen:>9}   {kept:>9}")
        insts = sorted((k[1], c) for k, c in per_instance.items() if k[0] == name)
        for inst, (iseen, ikept) in insts:
            label = f"dod-{inst}" if inst != "?" else "dod-? (unattributed)"
            print(f"    {label:<14} {iseen:>9}   {ikept:>9}")

    print(f"\naggregate over {total_kept} populated samples")
    print(f"  {'field':<16} {'sum':>10} {'max':>10} {'p50':>10} {'p95':>10}")
    for f in COUNTERS + GAUGES:
        vals = [s[2][f] for s in samples if f in s[2]]
        if not vals:
            continue
        vals_sorted = sorted(vals)
        p95 = vals_sorted[min(len(vals_sorted) - 1, int(len(vals_sorted) * 0.95))]
        agg = sum(vals) if f in COUNTERS else max(vals)
        label = f + ("" if f in COUNTERS else " (ms)")
        print(f"  {label:<16} {agg:>10.1f} {max(vals):>10.1f} "
              f"{statistics.median(vals):>10.1f} {p95:>10.1f}")

    worst = sorted(samples, key=lambda s: s[2].get("latency_worst", 0), reverse=True)[:5]
    print("\nworst 5 by latency_worst")
    for name, _, v in worst:
        print(f"  {name:<10} {v['_time']}  clients={int(v['clients'])} "
              f"lat={v['latency_worst']}ms jit={v['jitter_worst']}ms "
              f"lagcomp_off={int(v['lagcomp_off'])} ignorecmd={int(v['ignorecmd_hits'])}")

    if args.raw:
        print(f"\nraw (first {args.limit})")
        for name, ln, _ in samples[: args.limit]:
            print(f"  [{name}] {ln}")

    # sv_unlagsamples is the open netcode question; surface it rather than
    # making the reader cross-reference a card.
    unlag = {int(s[2]["unlag"]) for s in samples if "unlag" in s[2]}
    if unlag:
        print(f"\nsv_unlagsamples observed: {sorted(unlag)}"
              + ("   (1 = one packet's RTT, no averaging)" if unlag == {1} else ""))

    # The client-side half does not depend on net:, so it belongs on BOTH exits.
    # It used to live only in the no-populated-samples branch, which meant it
    # disappeared on exactly the nights that HAD data -- the ones worth reading.
    # A section that is absent and one that is empty look identical downstream.
    report_lagcomp({n: v[3] for n, v in results.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
