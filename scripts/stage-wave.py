#!/usr/bin/env python3
"""stage-wave.py -- one command to stage a deploy wave with the safety gates the
manual process relies on but no tool enforced.

It wraps the proven `deploy-to-fleet.py` push (per-instance isolation + the
FS-01 coverage backstop) and adds the gates that made the ad-hoc wave staging
safe (it said "the two gates" while listing five; a count in prose has no test
holding it true):

  1. PRE-STAGE ATTRIBUTION GATE. Refuses to stage if ANY `.new` already exists
     in the fleet swap globs (serverfiles + ktpamx dlls/modules/plugins). The
     nightly 03:00 auto-swap is indiscriminate -- a leftover `.new` from another
     change would activate alongside yours and you'd be bisecting a live fleet
     in the morning. This is the "one wave per nightly, never stacked" rule made
     mechanical. Override with --allow-existing-new only for a deliberate stack.
     NOTE: this gate runs ONCE, before anything is staged -- a multi-artifact
     wave staged one -f at a time will trip it on the second call, which is a
     usage trap, not the gate misfiring. -f and --expect are both repeatable:
     pass every artifact's pair in ONE invocation (see Usage below) and the
     gate never sees a partial stage to object to.

  2. EXPECTED-MD5 ASSERTION. `--expect <basename>=<md5>` refuses to stage an
     artifact whose local md5 doesn't match what you reviewed. KTPAMXX and
     KTPMatchHandler bake a per-minute build timestamp, so an accidental rebuild
     silently changes the shipped md5 -- this catches it before it reaches 24
     instances. ("Verify by md5, not banner.")

  3. WAVE-TIME RUNNER GATE. `--expect-runner <basename>=<md5>` refuses to stage
     unless the Tier-2 runner already holds the matching KTP_TEST_MODE build.
     That is a different binary from the one being staged, so its md5 must be
     supplied -- the version cannot be read back out of a compiled `.amxx`
     (XXMA+zlib). This answers a question the drift checker structurally cannot:
     it compares the runner against the FLEET, so on 2026-08-03 it saw a runner
     that was newer than the fleet by mtime and still two versions behind the
     artifact being waved. Staging a test-mode plugin without this flag warns.

  4. SINGLE-INSTANCE TARGETING. `--ports` narrows the wave to named instances --
     `--hosts denver --ports 27018` stages one instance and nothing else. The
     attribution gate, mode-match and md5 verify all scope to the SAME set, so a
     narrowed stage can neither be blocked by an unrelated `.new` elsewhere nor
     report "clean" on the strength of instances it never writes to. A port that
     is not an active instance is fatal, never silently dropped (Chicago has no
     27019). Output says NOT A FLEET WAVE so a soak cannot be misread as one.

  5. ROLLBACK PRESERVATION. `--pull-live DIR` downloads each artifact's LIVE
     counterpart from every target instance BEFORE staging, verifies the md5 of
     the copy that landed, and names it `<basename>.<host>-<port>.<md5>` so the
     file carries its own provenance. The fleet keeps no rollback copies and the
     swap is `mv -f`, so the running build is the only copy of itself that
     exists. Any failure -- including a live file that is ABSENT -- is fatal and
     nothing stages: "nothing to back up" and "the probe looked in the wrong
     place" must not be indistinguishable.

  6. ROW-FLIP GATE. Refuses to stage while an EARLIER wave has already activated
     and the root `CLAUDE.md` version row still names the build it replaced. The
     bump checklist puts that flip after activation, so it depended on someone
     coming back the next morning -- on 2026-09-01 two rows were skipped out of
     one wave and nothing noticed for a day, with the table reading as
     authoritative the whole time. The intent is recorded here at stage time
     (see ktp-wave-ledger.py) and checked on the next stage, which is the action
     that was going to happen anyway; flipping the row clears the gate by
     itself. --allow-unreconciled overrides.

Then it stages every artifact as `<name>.new` to all selected instances,
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
  # a single-instance soak, preserving the live build first
  stage-wave.py --hosts denver --ports 27018 --pull-live local/rollback/soak-20260824 \
                -f dodx_ktp_i386.so --expect dodx_ktp_i386.so=<md5>
  # just check attribution is clean, stage nothing
  stage-wave.py --preflight-only
  # inspect intent without connecting
  stage-wave.py -f foo.amxx --dry-run
  # a plugin wave gated on the runner holding the matching TEST-mode build
  stage-wave.py -f compiled/KTPMatchHandler.amxx \
                --expect        KTPMatchHandler.amxx=<production md5> \
                --expect-runner KTPMatchHandler.amxx=<TEST-mode md5>

Env: KTP_FLEET_SSH_PASSWORD (or ~/.ktp_fleet_ssh_password), same as deploy-to-fleet.py.
     KTP_TIER2_SSH_HOST / _USER / _PASSWORD / KTP_TIER2_TREE for --expect-runner.
     No default host: an --expect-runner that cannot reach the runner is FATAL,
     never skipped -- an unverifiable gate is not a passed gate.
     KTP_CLAUDE_MD / KTP_WAVE_LEDGER_DIR for the row-flip gate (ktp-wave-ledger.py).
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


def _load_sibling(mod_name, filename):
    spec = importlib.util.spec_from_file_location(mod_name, os.path.join(_HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    # Registered before exec: dataclasses resolve annotations through
    # sys.modules, and a module missing from it raises during class creation.
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


d2f = _load_sibling("deploy_to_fleet", "deploy-to-fleet.py")
ledger = _load_sibling("ktp_wave_ledger", "ktp-wave-ledger.py")

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


def _ports_for(hk, port_filter=None):
    """ACTIVE ports on a host, narrowed by --ports. CHI has no 27019."""
    ports = d2f.SERVERS[hk].get("ports", d2f.PORTS)
    if port_filter is None:
        return list(ports)
    return [p for p in ports if p in port_filter]


def _target_instances(host_keys, port_filter=None):
    """(host_key, port) for every selected ACTIVE instance."""
    return [(hk, p) for hk in host_keys for p in _ports_for(hk, port_filter)]


def preflight_attribution(host_keys, port_filter=None):
    """Return {(*host*): [existing .new paths]} across the swap globs. Empty = clean.

    Scoped to the SELECTED instances. A soak stage to one instance must not be
    blocked by an unrelated `.new` on an instance it is not touching -- and,
    more importantly, must not report "clean" on the strength of instances it
    never intends to write to.
    """
    def scan(hk):
        info = d2f.SERVERS[hk]
        ports = _ports_for(hk, port_filter)
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


# Plugins the Tier-2 runner holds as KTP_TEST_MODE builds. Staging one of these
# to the fleet without the runner holding the matching test build means the next
# suite run certifies a build nobody is about to ship. Mirrors PLUGINS_TESTMODE
# in ktp-tier2-stack-drift.py -- keep the two in step.
# KTPHudObserver is externally maintained -- never staged or waved from here.
RUNNER_TESTMODE_PLUGINS = {
    "KTPMatchHandler.amxx",
    "KTPPracticeMode.amxx",
}

# Runner location. No default host: this tool deliberately holds no IPs, and a
# gate that silently skips when unconfigured is worse than no gate, so an
# --expect-runner with no host configured is fatal rather than skipped.
RUNNER_HOST = os.environ.get("KTP_TIER2_SSH_HOST", "")
RUNNER_USER = os.environ.get("KTP_TIER2_SSH_USER", "root")
RUNNER_TREE = os.environ.get("KTP_TIER2_TREE", "/opt/ktp-tier2-runner/serverfiles")
RUNNER_PLUGIN_DIR = "dod/addons/ktpamx/plugins"


def runner_md5s(basenames):
    """{basename: md5-or-None} for the runner's copy of each plugin. Raises on connect failure."""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    pw = os.environ.get("KTP_TIER2_SSH_PASSWORD") or None
    ssh.connect(RUNNER_HOST, username=RUNNER_USER, password=pw, timeout=30)
    try:
        paths = " ".join(f"'{RUNNER_TREE}/{RUNNER_PLUGIN_DIR}/{b}'" for b in basenames)
        _, so, _ = ssh.exec_command(f"md5sum {paths} 2>/dev/null", timeout=60)
        got = {}
        for ln in so.read().decode().splitlines():
            parts = ln.split()
            if len(parts) == 2:
                got[os.path.basename(parts[1])] = parts[0].lower()
        return {b: got.get(b) for b in basenames}
    finally:
        ssh.close()


def mode_match(host_keys, artifacts, port_filter=None):
    """chmod each staged .new to match the live file it will replace (else 644)."""
    def fix(hk):
        info = d2f.SERVERS[hk]
        ports = _ports_for(hk, port_filter)
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


def pull_live(host_keys, artifacts, dest, port_filter=None):
    """Download the LIVE counterpart of every artifact from every target instance.

    The fleet keeps no rollback copies and the nightly swap is `mv -f`, so the
    running build is the only copy of itself that exists anywhere. Staging over
    it without pulling it first makes the change one-way.

    Saved as `<basename>.<host>-<port>.<md5>` so the filename carries its own
    provenance -- a rollback copy whose identity rests on a sidecar note is one
    lost note away from being unusable.

    Returns (saved, errors). An instance whose live file is ABSENT is recorded
    as an error, not skipped: "there was nothing to back up" and "the probe
    looked in the wrong place" are indistinguishable from a silent skip.
    """
    os.makedirs(dest, exist_ok=True)
    saved, errors = [], []

    def worker(hk):
        info = d2f.SERVERS[hk]
        got, errs = [], []
        try:
            ssh = _connect(info)
            sftp = ssh.open_sftp()
        except Exception as e:
            return [], [(hk, None, None, f"connect: {e!r}")]
        for p in _ports_for(hk, port_filter):
            for a in artifacts:
                remote = f"/home/{info['user']}/dod-{p}/{a.remote_dir}/{a.basename}"
                try:
                    _, so, _ = ssh.exec_command(f"md5sum '{remote}'", timeout=30)
                    out = so.read().decode().split()
                    if not out:
                        errs.append((hk, p, a.basename, "live file ABSENT (nothing to roll back to)"))
                        continue
                    md5 = out[0]
                    local = os.path.join(dest, f"{a.basename}.{hk}-{p}.{md5}")
                    sftp.get(remote, local)
                    # Verify the copy that landed, not the one we asked for.
                    import hashlib
                    h = hashlib.md5()
                    with open(local, "rb") as fh:
                        for chunk in iter(lambda: fh.read(1 << 20), b""):
                            h.update(chunk)
                    if h.hexdigest() != md5:
                        errs.append((hk, p, a.basename, f"md5 mismatch after download: {h.hexdigest()} != {md5}"))
                        continue
                    got.append((hk, p, a.basename, md5, local))
                except Exception as e:
                    errs.append((hk, p, a.basename, repr(e)))
        sftp.close()
        ssh.close()
        return got, errs

    with ThreadPoolExecutor(max_workers=max(1, len(host_keys))) as pool:
        for got, errs in pool.map(worker, host_keys):
            saved.extend(got)
            errors.extend(errs)
    return saved, errors


def stage(host_keys, artifacts, parallel, port_filter=None):
    """Reuse deploy-to-fleet's push + coverage backstop. Returns (outcomes, missing)."""
    targets = _target_instances(host_keys, port_filter)
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
    ap.add_argument("--ports", default="all",
                    help='Comma-separated instance ports, or "all". Narrows the wave to specific '
                         'instances -- e.g. --hosts denver --ports 27018 for a single-instance soak. '
                         'The attribution gate, mode-match and md5 verify all scope to the same set.')
    ap.add_argument("--pull-live", metavar="DIR",
                    help="Before staging, download each artifact's LIVE counterpart from every target "
                         "instance into DIR. The fleet keeps no rollback copies and the swap is `mv -f`, "
                         "so the running build is the only copy that exists. Any download failure is "
                         "FATAL and nothing is staged.")
    ap.add_argument("--allow-existing-new", action="store_true",
                    help="Skip the attribution gate (deliberate stacked activation only). For a "
                         "multi-artifact wave staged one -f at a time, this is the WRONG fix -- pass "
                         "every -f/--expect pair in ONE invocation instead; the gate never blocks that.")
    ap.add_argument("--expect-runner", action="append", default=[], metavar="BASENAME=MD5",
                    help="Assert the Tier-2 runner holds this md5 (the TEST-mode build, which is a "
                         "different binary from the one being staged). Repeatable.")
    ap.add_argument("--no-runner-check", action="store_true",
                    help="Silence the missing --expect-runner warning (you have decided the runner "
                         "does not need to match this wave).")
    ap.add_argument("--row-version", action="append", default=[], metavar="BASENAME=VERSION",
                    help="The version this artifact's CLAUDE.md row should read after activation. "
                         "Recorded in the wave ledger and quoted back if the row goes stale. "
                         "Repeatable; optional (the md5 is the identity either way).")
    ap.add_argument("--allow-unreconciled", action="store_true",
                    help="Skip the row-flip gate (a previous wave activated and its CLAUDE.md row "
                         "is still stale). Fix the row instead -- that clears the gate by itself.")
    ap.add_argument("--preflight-only", action="store_true", help="Run the attribution gate and exit.")
    ap.add_argument("--dry-run", action="store_true", help="Print intent, do not connect to stage.")
    ap.add_argument("--parallel", type=int, default=5)
    args = ap.parse_args()

    host_keys = list(d2f.SERVERS) if args.hosts == "all" else [h.strip() for h in args.hosts.split(",")]
    for hk in host_keys:
        if hk not in d2f.SERVERS:
            sys.exit(f"FATAL: unknown host '{hk}' (choices: {','.join(d2f.SERVERS)})")

    port_filter = None
    if args.ports != "all":
        try:
            port_filter = {int(p.strip()) for p in args.ports.split(",") if p.strip()}
        except ValueError:
            sys.exit(f"FATAL: --ports must be integers or 'all', got '{args.ports}'")
        selected = _target_instances(host_keys, port_filter)
        if not selected:
            sys.exit(f"FATAL: --ports {args.ports} selects ZERO active instances on "
                     f"{','.join(host_keys)}. Nothing staged.")
        # A filter that silently drops a port the operator asked for is the same
        # class of defect as a wave that silently stages fewer than 24.
        unmatched = sorted(port_filter - {p for _, p in selected})
        if unmatched:
            sys.exit(f"FATAL: --ports names {unmatched}, which is not an active instance on "
                     f"{','.join(host_keys)}. Nothing staged.")

    # ---- Row-flip gate (before anything touches the fleet) ----
    # The bump checklist's row flip runs AFTER activation, so it depends on
    # someone returning the next morning; on 2026-09-01 two rows were skipped in
    # one wave and nothing noticed for a day. Sitting the gate on the next stage
    # is what removes the dependency on remembering: the wave you are about to
    # push cannot go out until the last one's row agrees, and flipping the row
    # clears it with no second command to run.
    if not args.allow_unreconciled:
        gate = ledger.gate()
        stream = sys.stderr if gate.status != "clear" else sys.stdout
        for ln in gate.lines:
            print(ln, file=stream)
        if gate.status == "inconclusive":
            sys.exit("FATAL: cannot verify the previous wave's row flip. (Nothing staged.)")
        if gate.status == "blocked":
            for ln in ledger.format_block(gate):
                print(ln, file=sys.stderr)
            sys.exit("Aborting -- nothing staged.")
        print()

    # ---- Attribution gate (always runs; the whole point of the tool) ----
    if not args.allow_existing_new:
        print("Preflight: checking fleet for existing .new (clean-attribution gate)...")
        pf = preflight_attribution(host_keys, port_filter)
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
            print("If these are earlier artifacts of THIS SAME wave (staged one -f at a time), that is", file=sys.stderr)
            print("the trap, not a second wave: -f and --expect are both repeatable, so re-run with every", file=sys.stderr)
            print("artifact's -f/--expect pair TOGETHER in one invocation -- the gate runs once, before", file=sys.stderr)
            print("anything is staged, so a single call for the whole wave never blocks itself. See the", file=sys.stderr)
            print("multi-artifact example in this script's own --help.", file=sys.stderr)
            sys.exit("Otherwise clear these by hand, or pass --allow-existing-new for a genuinely deliberate stack, and re-run.")
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
    row_versions = {}
    for e in args.row_version:
        if "=" not in e:
            sys.exit(f"FATAL: --row-version must be BASENAME=VERSION, got '{e}'")
        k, v = e.split("=", 1)
        row_versions[k.strip()] = v.strip()
    unpinned = [a.basename for a in artifacts if a.basename not in expect]
    if unpinned:
        print(f"WARNING: not md5-pinned (no --expect): {', '.join(unpinned)}")

    print(f"Artifacts ({len(artifacts)}):")
    for a in artifacts:
        pin = " [pinned]" if a.basename in expect else ""
        print(f"  {a.basename} -> dod-*/{a.remote_dir}/  ({a.size}B, md5 {a.md5}){pin}")
    targets = _target_instances(host_keys, port_filter)
    if port_filter is None:
        print(f"Targets: {len(targets)} active instances across {len(host_keys)} host(s).\n")
    else:
        listed = ", ".join(f"{hk}:{p}" for hk, p in targets)
        print(f"Targets: {len(targets)} instance(s) -- NARROWED by --ports: {listed}")
        print("  ** This is NOT a fleet wave. The other instances keep their current build. **\n")

    # ---- Wave-time runner gate ----
    # The drift checker answers "has the runner fallen behind the FLEET". It
    # cannot answer "is the runner holding the build I am about to wave" -- on
    # 2026-08-03 the runner was newer than the fleet by mtime and still two
    # versions behind the reviewed artifact. That question only exists here.
    expect_runner = {}
    for e in args.expect_runner:
        if "=" not in e:
            sys.exit(f"FATAL: --expect-runner must be BASENAME=MD5, got '{e}'")
        k, v = e.split("=", 1)
        expect_runner[k.strip()] = v.strip().lower()

    staged_testmode = [a.basename for a in artifacts if a.basename in RUNNER_TESTMODE_PLUGINS]
    unchecked = [b for b in staged_testmode if b not in expect_runner]

    if expect_runner and args.dry_run:
        print("Runner gate: WOULD check the Tier-2 runner for:")
        for name, want in sorted(expect_runner.items()):
            print(f"  {name} == {want}")
        print(f"  (host {RUNNER_USER}@{RUNNER_HOST or '<KTP_TIER2_SSH_HOST unset -- would be FATAL>'})\n")
    elif expect_runner:
        if not RUNNER_HOST:
            sys.exit("FATAL: --expect-runner given but KTP_TIER2_SSH_HOST is unset -- the gate "
                     "cannot run. Set it, or drop --expect-runner. (Nothing staged.)")
        print("Runner gate: checking the Tier-2 runner holds the matching TEST-mode build(s)...")
        try:
            got = runner_md5s(sorted(expect_runner))
        except Exception as ex:
            sys.exit(f"FATAL: could not read the Tier-2 runner ({RUNNER_USER}@{RUNNER_HOST}): {ex!r}\n"
                     "Aborting -- an unverifiable gate is not a passed gate. (Nothing staged.)")
        bad = []
        for name, want in sorted(expect_runner.items()):
            have = got.get(name)
            if have is None:
                bad.append((name, "ABSENT", want))
            elif have != want:
                bad.append((name, have, want))
            else:
                print(f"  {name}: {have} OK")
        if bad:
            print("FATAL: the Tier-2 runner does not hold the expected TEST-mode build:", file=sys.stderr)
            for name, have, want in bad:
                print(f"  {name}: runner has {have}, expected {want}", file=sys.stderr)
            sys.exit("Restage the runner's test build first, then re-run. (Nothing staged.)")
        print("  runner matches.\n")
    elif staged_testmode and not args.no_runner_check:
        print("WARNING: staging a plugin with a KTP_TEST_MODE runner build and no --expect-runner:")
        for b in staged_testmode:
            print(f"  {b}")
        print("  The next Tier-2 run would certify a build that is not the one being waved.")
        print("  Pass --expect-runner NAME=<test-mode md5>, or --no-runner-check to accept.\n")
    if unchecked and expect_runner and not args.no_runner_check:
        print(f"WARNING: staged but not runner-checked: {', '.join(unchecked)}\n")

    if args.dry_run:
        print("DRY-RUN: no connection made. Above is what would stage.")
        return

    # ---- Pull the live artifacts before overwriting them ----
    # The fleet has no rollback copies. This is the last moment they exist.
    if args.pull_live:
        print(f"Pulling LIVE artifacts to {args.pull_live} before staging...")
        saved, pull_errs = pull_live(host_keys, artifacts, args.pull_live, port_filter)
        for hk, p, base, md5, local in saved:
            print(f"  [{hk}:{p}] {base} md5 {md5} -> {os.path.basename(local)}")
        if pull_errs:
            print("FATAL: could not preserve every live artifact:", file=sys.stderr)
            for hk, p, base, err in pull_errs:
                print(f"  [{hk}:{p or '-'}] {base or '-'}: {err}", file=sys.stderr)
            sys.exit("Aborting -- NOTHING STAGED. A stage with no rollback copy is one-way.")
        distinct = sorted({m for _, _, _, m, _ in saved})
        print(f"  preserved {len(saved)} file(s), {len(distinct)} distinct md5(s).")
        if len(distinct) > len(artifacts):
            print("  ** The target instances are NOT uniform -- more distinct md5s than artifacts. **")
        print()

    # ---- Stage + mode-match ----
    outcomes, missing = stage(host_keys, artifacts, args.parallel, port_filter)
    fails = sum(1 for o in outcomes if o.status in d2f.FAIL_STATUSES)
    if fails or missing:
        sys.exit("\n*** STAGING FAILED -- see summary above. Do NOT assume the wave is staged. ***")

    print("\nMode-matching .new permissions to the live files...")
    mm_err = mode_match(host_keys, artifacts, port_filter)
    if mm_err:
        for hk, e in mm_err.items():
            print(f"  [{hk}] mode-match error: {e}", file=sys.stderr)
        print("  (files ARE staged + md5-correct; only the chmod pass hit an error -- verify perms.)")
    else:
        print("  done.")

    # ---- Record the intent, so the row flip has something to be gated against ----
    # Written after the stage succeeds: a wave that did not land has no row to
    # flip, and a ledger entry for it would block the next stage over nothing.
    try:
        ledger_path = ledger.record_wave(
            [{"basename": a.basename, "md5": a.md5, "remote_dir": a.remote_dir,
              "version": row_versions.get(a.basename)} for a in artifacts],
            hosts=host_keys, targets=len(targets), narrowed=port_filter is not None)
        print(f"\nWave recorded: {ledger_path}")
    except Exception as ex:
        print(f"\nWARNING: could not record the wave for the row-flip gate: {ex!r}", file=sys.stderr)
        print("  The stage is fine; only the morning-after gate is unarmed. Record it by hand:",
              file=sys.stderr)
        pairs = " ".join(f"-a {a.basename}={a.md5}:{a.remote_dir}" for a in artifacts)
        print(f"  ktp-wave-ledger.py record {pairs} --hosts {','.join(host_keys)} "
              f"--targets {len(targets)}", file=sys.stderr)

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
    print("  ktp-wave-ledger.py reconcile   <- re-reads the fleet, then FAILS if the")
    print("                                    CLAUDE.md version row still disagrees.")
    print("    Not optional in practice: until that row agrees, the next stage-wave is blocked.")
    if is_module or is_engine:
        print("  + re-sync the tier-2 runner STACK (module/engine changed) -- see the runner note in CLAUDE.md.")
    if is_plugin:
        print("  + if this wave includes a plugin with a KTP_TEST_MODE runner build (KTPMatchHandler;")
        print("    also KTPPracticeMode / KTPHudObserver), restage that plugin's TEST-mode binary to")
        print("    the tier-2 runner + bump its pin (e.g. EXPECTED_KTPMATCHHANDLER_VERSION). Others need nothing.")
    print("=" * 70)


if __name__ == "__main__":
    main()
