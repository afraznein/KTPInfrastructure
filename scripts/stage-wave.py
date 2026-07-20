#!/usr/bin/env python3
"""stage-wave.py -- one command to stage a deploy wave with the safety gates the
manual process relies on but no tool enforced.

It wraps the proven `deploy-to-fleet.py` push (per-instance isolation + the
FS-01 coverage backstop) and adds the two gates that made the ad-hoc wave
staging safe:

  1. PRE-STAGE ATTRIBUTION GATE. Refuses to stage if ANY `.new` already exists
     in the fleet swap globs (serverfiles + ktpamx dlls/modules/plugins). The
     nightly 03:00 auto-swap is indiscriminate -- a leftover `.new` from another
     change would activate alongside yours and you'd be bisecting a live fleet
     in the morning. This is the "one wave per nightly, never stacked" rule made
     mechanical. Override with --allow-existing-new only for a deliberate stack.

  2. EXPECTED-MD5 ASSERTION. `--expect <basename>=<md5>` refuses to stage an
     artifact whose local md5 doesn't match what you reviewed. KTPAMXX and
     KTPMatchHandler bake a per-minute build timestamp, so an accidental rebuild
     silently changes the shipped md5 -- this catches it before it reaches 24
     instances. ("Verify by md5, not banner.")

Then it stages every artifact as `<name>.new` to all active instances,
mode-matches each `.new` to the live file it will replace (so the post-swap
permissions are correct), re-verifies md5 24/24, and prints the exact
morning-after verification command.

It NEVER restarts a server. `.new` files activate at the next 03:00 ET nightly
swap (`ktp-scheduled-restart.sh`). Reuses `deploy-to-fleet.py`'s SERVERS
topology and password-from-env, so there is one source of truth for the fleet
list and no secret/IP is duplicated here.

Usage:
  # a plugin wave (basename=md5 pins each artifact to its reviewed build)
  stage-wave.py -f compiled/KTPMatchHandler.amxx --expect KTPMatchHandler.amxx=0d3a174eb96e638579125a8f1a4cd23c \
                -f compiled/ktp_cvar.amxx        --expect ktp_cvar.amxx=6e55811b716a03e294941ab03ddd85c1
  # a module wave
  stage-wave.py -f dodx_ktp_i386.so --expect dodx_ktp_i386.so=<md5>
  # just check attribution is clean, stage nothing
  stage-wave.py --preflight-only
  # inspect intent without connecting
  stage-wave.py -f foo.amxx --dry-run

Env: KTP_FLEET_SSH_PASSWORD (or ~/.ktp_fleet_ssh_password), same as deploy-to-fleet.py.
"""

import argparse
import importlib.util
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import paramiko
except ImportError:
    print("ERROR: paramiko not installed. Run: pip install paramiko")
    sys.exit(1)

# Import the sibling deploy-to-fleet.py (hyphens => load by path). We reuse its
# SERVERS (the 24-instance topology), the FS-01-hardened push, and the
# password helper -- so this tool holds no IPs, no creds, and no fleet list of
# its own to drift.
_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("deploy_to_fleet", os.path.join(_HERE, "deploy-to-fleet.py"))
d2f = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(d2f)

# The four swap globs the nightly restart script activates (explicit, not
# recursive -- mirrors ktp-scheduled-restart.sh). Any .new here activates.
SWAP_GLOBS = [
    "serverfiles/*.new",
    "serverfiles/dod/addons/ktpamx/dlls/*.new",
    "serverfiles/dod/addons/ktpamx/modules/*.new",
    "serverfiles/dod/addons/ktpamx/plugins/*.new",
]


def _connect(host_info):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host_info["host"], username=host_info["user"],
                password=d2f._fleet_ssh_password(), timeout=30)
    return ssh


def _target_instances(host_keys):
    """(host_key, port) for every ACTIVE instance -- CHI has no 27019."""
    return [(hk, p) for hk in host_keys for p in d2f.SERVERS[hk].get("ports", d2f.PORTS)]


def preflight_attribution(host_keys):
    """Return {(*host*): [existing .new paths]} across the swap globs. Empty = clean."""
    def scan(hk):
        info = d2f.SERVERS[hk]
        ports = info.get("ports", d2f.PORTS)
        globs = " ".join(f"~/dod-{p}/{g}" for p in ports for g in SWAP_GLOBS)
        try:
            ssh = _connect(info)
            _, so, _ = ssh.exec_command(f"ls {globs} 2>/dev/null", timeout=40)
            found = [ln for ln in so.read().decode().splitlines() if ln.strip()]
            ssh.close()
            return hk, found, None
        except Exception as e:
            return hk, None, repr(e)

    out = {}
    with ThreadPoolExecutor(max_workers=len(host_keys)) as pool:
        for hk, found, err in pool.map(scan, host_keys):
            out[hk] = {"found": found, "err": err}
    return out


def mode_match(host_keys, artifacts):
    """chmod each staged .new to match the live file it will replace (else 644)."""
    def fix(hk):
        info = d2f.SERVERS[hk]
        ports = info.get("ports", d2f.PORTS)
        cmds = []
        for p in ports:
            for a in artifacts:
                base = f"/home/{info['user']}/dod-{p}/{a.remote_dir}/{a.basename}"
                cmds.append(f"( [ -f '{base}' ] && chmod --reference='{base}' '{base}.new' "
                            f"|| chmod 644 '{base}.new' )")
        try:
            ssh = _connect(info)
            ssh.exec_command(" ; ".join(cmds), timeout=60)[1].read()
            ssh.close()
            return hk, None
        except Exception as e:
            return hk, repr(e)

    errs = {}
    with ThreadPoolExecutor(max_workers=len(host_keys)) as pool:
        for hk, err in pool.map(fix, host_keys):
            if err:
                errs[hk] = err
    return errs


def stage(host_keys, artifacts, parallel):
    """Reuse deploy-to-fleet's push + coverage backstop. Returns (outcomes, missing)."""
    targets = _target_instances(host_keys)
    outcomes = []

    def host_worker(hk):
        info = d2f.SERVERS[hk]
        res = []
        for p in [pp for h, pp in targets if h == hk]:
            try:
                res.extend(d2f.deploy_to_instance(hk, info, p, artifacts, dry_run=False))
            except Exception as e:
                for a in artifacts:
                    res.append(d2f.Outcome(hk, p, a.basename, "deploy_error", str(e)[:80]))
        return res

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futs = {pool.submit(host_worker, hk): hk for hk in host_keys}
        for fut in as_completed(futs):
            hk = futs[fut]
            try:
                outcomes.extend(fut.result())
            except Exception as e:
                for _hk, p in targets:
                    if _hk == hk:
                        for a in artifacts:
                            outcomes.append(d2f.Outcome(hk, p, a.basename, "worker_crash", str(e)[:80]))

    missing = d2f.print_summary(outcomes, artifacts, dry_run=False, expected_instances=targets)
    return outcomes, missing


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-f", "--file", action="append", default=[], dest="files",
                    help="Local artifact path. Repeatable.")
    ap.add_argument("--expect", action="append", default=[], metavar="BASENAME=MD5",
                    help="Pin an artifact's local md5 to its reviewed build. Repeatable.")
    ap.add_argument("--hosts", default="all",
                    help=f'Comma-separated (or "all"). Choices: {",".join(d2f.SERVERS)}')
    ap.add_argument("--allow-existing-new", action="store_true",
                    help="Skip the attribution gate (deliberate stacked activation only).")
    ap.add_argument("--preflight-only", action="store_true", help="Run the attribution gate and exit.")
    ap.add_argument("--dry-run", action="store_true", help="Print intent, do not connect to stage.")
    ap.add_argument("--parallel", type=int, default=5)
    args = ap.parse_args()

    host_keys = list(d2f.SERVERS) if args.hosts == "all" else [h.strip() for h in args.hosts.split(",")]
    for hk in host_keys:
        if hk not in d2f.SERVERS:
            sys.exit(f"FATAL: unknown host '{hk}' (choices: {','.join(d2f.SERVERS)})")

    # ---- Attribution gate (always runs; the whole point of the tool) ----
    if not args.allow_existing_new:
        print("Preflight: checking fleet for existing .new (clean-attribution gate)...")
        pf = preflight_attribution(host_keys)
        dirty, errored = [], []
        for hk, r in pf.items():
            if r["err"]:
                errored.append((hk, r["err"]))
            elif r["found"]:
                dirty.append((hk, r["found"]))
        if errored:
            for hk, e in errored:
                print(f"  [{hk}] PREFLIGHT ERROR: {e}", file=sys.stderr)
            sys.exit("FATAL: could not verify attribution on every host -- aborting (nothing staged).")
        if dirty:
            print("FATAL: existing .new on the fleet -- staging now would stack activations:", file=sys.stderr)
            for hk, files in dirty:
                for f in files:
                    print(f"  [{hk}] {f}", file=sys.stderr)
            sys.exit("Clear these (or pass --allow-existing-new for a deliberate stack) and re-run.")
        print(f"  clean -- zero .new across {len(host_keys)} host(s). Attribution safe.\n")
    else:
        print("Preflight: SKIPPED (--allow-existing-new).\n")

    if args.preflight_only:
        print("Preflight-only: done."); return

    if not args.files:
        sys.exit("FATAL: no artifacts given (-f). Use --preflight-only to just check attribution.")

    # ---- Build + md5-pin ----
    artifacts = d2f.build_artifacts(args.files, override_remote=None)
    expect = {}
    for e in args.expect:
        if "=" not in e:
            sys.exit(f"FATAL: --expect must be BASENAME=MD5, got '{e}'")
        k, v = e.split("=", 1)
        expect[k.strip()] = v.strip().lower()
    mismatches = [(a.basename, a.md5, expect[a.basename])
                  for a in artifacts if a.basename in expect and a.md5 != expect[a.basename]]
    if mismatches:
        print("FATAL: local md5 does not match --expect (accidental rebuild?):", file=sys.stderr)
        for name, got, want in mismatches:
            print(f"  {name}: got {got}  expected {want}", file=sys.stderr)
        sys.exit("Aborting (nothing staged). Rebuild churns md5 -- ship the reviewed artifact.")
    unpinned = [a.basename for a in artifacts if a.basename not in expect]
    if unpinned:
        print(f"WARNING: not md5-pinned (no --expect): {', '.join(unpinned)}")

    print(f"Artifacts ({len(artifacts)}):")
    for a in artifacts:
        pin = " [pinned]" if a.basename in expect else ""
        print(f"  {a.basename} -> dod-*/{a.remote_dir}/  ({a.size}B, md5 {a.md5}){pin}")
    targets = _target_instances(host_keys)
    print(f"Targets: {len(targets)} active instances across {len(host_keys)} host(s).\n")

    if args.dry_run:
        print("DRY-RUN: no connection made. Above is what would stage.")
        return

    # ---- Stage + mode-match ----
    outcomes, missing = stage(host_keys, artifacts, args.parallel)
    fails = sum(1 for o in outcomes if o.status in d2f.FAIL_STATUSES)
    if fails or missing:
        sys.exit("\n*** STAGING FAILED -- see summary above. Do NOT assume the wave is staged. ***")

    print("\nMode-matching .new permissions to the live files...")
    mm_err = mode_match(host_keys, artifacts)
    if mm_err:
        for hk, e in mm_err.items():
            print(f"  [{hk}] mode-match error: {e}", file=sys.stderr)
        print("  (files ARE staged + md5-correct; only the chmod pass hit an error -- verify perms.)")
    else:
        print("  done.")

    # ---- Next-step hint ----
    is_module = any(a.remote_dir.endswith(("dlls", "modules")) for a in artifacts)
    is_engine = any(a.remote_dir == "serverfiles" for a in artifacts)
    is_plugin = any(a.remote_dir.endswith("plugins") for a in artifacts)
    print("\n" + "=" * 70)
    print(f"WAVE STAGED: {len(artifacts)} artifact(s) x {len(targets)} instances, md5-verified, attribution clean.")
    print("Activates at the next 03:00 ET nightly swap. No restart performed.")
    print("\nMorning-after (AFTER activation + this verify passes -- the runner mirrors the")
    print("LIVE fleet, so update it only once the fleet is confirmed on the new build):")
    vc = "  ktp-verify-deploy.py --check-runtime"
    if is_engine:
        vc += " --include-engine"
    print(vc)
    if is_module or is_engine:
        print("  + re-sync the tier-2 runner STACK (module/engine changed) -- see the runner note in CLAUDE.md.")
    if is_plugin:
        print("  + if this wave includes a plugin with a KTP_TEST_MODE runner build (KTPMatchHandler;")
        print("    also KTPPracticeMode / KTPHudObserver), restage that plugin's TEST-mode binary to")
        print("    the tier-2 runner + bump its pin (e.g. EXPECTED_KTPMATCHHANDLER_VERSION). Others need nothing.")
    print("=" * 70)


if __name__ == "__main__":
    main()
