#!/usr/bin/env python3
"""Re-sync the Tier-2 runner's stack from a live fleet instance.

This is the tool behind the one deploy-flow step that never had one. The
runner is a declared must-match-fleet environment -- its value is entirely
that a green suite certifies the stack production actually runs -- and the
only thing enforcing that was a checklist line reading

    - Re-sync the Tier-2 runner stack (above).

which pointed at no section, in a document whose only other mention of
Tier 2 is that line. The detector was built (ktp-tier2-stack-drift.py, in
the 6h heartbeat) and it works: it alerted `ok -> drift` within hours of
the 2026-08-26 ABI wave. Nothing existed to act on the alert, so the
runner sat on the pre-wave engine, core, dodx and reapi while the fleet
moved -- a green run then certifies a DIFFERENT ABI than production, which
is worse than no run at all, because it reads as evidence.

WHAT IT SYNCS. Exactly the file set ktp-tier2-stack-drift.py alerts on,
imported from that module rather than restated here. A second copy of the
list is a second thing to forget: the runner already carries three lists
of test-mode plugins that must be kept in step by hand.

WHAT IT REFUSES TO TOUCH, and this is the point of the tool rather than an
`rsync` one-liner:

  - KTPMatchHandler / KTPPracticeMode are KTP_TEST_MODE builds. Byte-equal
    to the fleet is WRONG for them; md5 says nothing.
  - KTPHudObserver is rebuilt from upstream by the workflow on every run.
  - Configs are runner-specific. `hud_observer.cfg` is absent ON PURPOSE --
    it carries the live ingest URL and a production key, and restoring it
    points the test harness at the real HUD ingest.

GUARDS, each of which is a way a hand-run `scp` has gone wrong here:

  1. DRY RUN BY DEFAULT. Writing to the runner needs --apply. The runner
     lives on the production data server, beside MySQL, HLStatsX ingest and
     the HLTV proxies; a re-sync is a production change.
  2. NOT DURING A RUN. Swapping the engine under a live hlds_linux gives a
     result nobody can interpret afterwards.
  3. PENDING-WAVE ACKNOWLEDGEMENT. If the reference instance is holding
     staged `.new` files, the fleet moves again at the next 03:00 and this
     sync is stale hours after it finishes. That is sometimes fine and must
     never be accidental, so it needs --ack-pending-wave.
  4. BACKUP FIRST. The fleet has no rollback copies and neither does the
     runner; the drifted files are copied aside before anything is written.
  5. VERIFY AT BOTH HOPS. md5 is re-read after the pull and again after the
     push. A transfer that "succeeded" but landed short is a green suite
     certifying a binary nobody built.

ORDERING. Run this AFTER a wave has activated and post-activation verify
passes -- the runner mirrors the LIVE fleet, so syncing from an instance
whose state is not yet verified just moves an unverified stack somewhere
else. The one deliberate exception is a pre-activation gate, where the
runner is meant to LEAD the fleet; that is a stage-runner.py job, not this
one.

Usage:
  # what would change, no connection to the runner is written to
  sync-runner-stack.py

  # do it
  sync-runner-stack.py --apply

  # the fleet is holding a staged wave and you want to sync to what is
  # live right now anyway
  sync-runner-stack.py --apply --ack-pending-wave

Env: KTP_TIER2_SSH_HOST (required)   KTP_TIER2_SSH_USER (default root)
     KTP_TIER2_SSH_PASSWORD / KTP_TIER2_SSH_KEY
     KTP_TIER2_TREE (default /opt/ktp-tier2-runner/serverfiles)
     KTP_DRIFT_REF_HOST (required)   KTP_DRIFT_REF_TREE (default dod-27015/serverfiles)
     GAME_SSH_USER (default dodserver)  GAME_SSH_PASSWORD
No default hosts: this tool holds no IPs, and syncing a production runner
from a guessed reference is worse than failing.
"""

import argparse
import getpass
import hashlib
import importlib.util
import json
import os
import posixpath
import stat as statmod
import sys
import tempfile
import time

try:
    import paramiko
except ImportError:
    sys.exit("ERROR: paramiko not installed. Run: pip install paramiko")

HERE = os.path.dirname(os.path.abspath(__file__))

RUNNER_HOST = os.environ.get("KTP_TIER2_SSH_HOST", "")
RUNNER_USER = os.environ.get("KTP_TIER2_SSH_USER", "root")
RUNNER_TREE = os.environ.get("KTP_TIER2_TREE", "/opt/ktp-tier2-runner/serverfiles")
REF_HOST = os.environ.get("KTP_DRIFT_REF_HOST", "")
REF_TREE = os.environ.get("KTP_DRIFT_REF_TREE", "dod-27015/serverfiles")
REF_USER = os.environ.get("GAME_SSH_USER", "dodserver")
REF_PASSWORD = os.environ.get("GAME_SSH_PASSWORD", "")

RECORD = posixpath.join(posixpath.dirname(RUNNER_TREE), "stack-sync.json")


def _load_drift_module():
    """The synced file set is the alerted file set, by construction.

    Imported by path because the module's name is not an identifier. Its
    top level only reads env, so importing it has no side effect beyond
    binding the same defaults this script already reads.
    """
    path = os.path.join(HERE, "ktp-tier2-stack-drift.py")
    spec = importlib.util.spec_from_file_location("ktp_tier2_stack_drift", path)
    if spec is None or spec.loader is None:
        sys.exit(f"FATAL: cannot load the drift checker at {path} -- the two must stay in step.")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sync_set():
    """Paths to mirror, and the ones deliberately left alone.

    Returns (paths, excluded). `excluded` is asserted against `paths` rather
    than merely documented: a plugin promoted out of PLUGINS_TESTMODE into
    PLUGINS_STRICT upstream would otherwise start being overwritten here
    silently, and a test-mode build overwritten with the fleet's is a suite
    that cannot drive itself.
    """
    drift = _load_drift_module()
    paths = list(drift.STACK_FILES) + list(drift.PLUGINS_STRICT)
    excluded = set(drift.PLUGINS_TESTMODE) | {
        "dod/addons/ktpamx/plugins/KTPHudObserver.amxx",
    }
    clash = sorted(excluded.intersection(paths))
    if clash:
        sys.exit("FATAL: the drift checker now lists a build-locally artifact as fleet-strict: "
                 + ", ".join(clash) + "\nRefusing to overwrite it. Reconcile the lists first.")
    return paths, excluded


def connect(host, user, password=None, key=None, label=""):
    if not host:
        sys.exit(f"FATAL: no host for {label}. This tool ships no default hosts -- set the env var.")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    auth = {"key_filename": key} if key else {"password": password or None}
    try:
        client.connect(host, username=user, timeout=30, banner_timeout=30, auth_timeout=30,
                       allow_agent=False, look_for_keys=False, **auth)
    except paramiko.AuthenticationException as ex:
        raise SystemExit(
            f"FATAL: SSH auth rejected for {label} ({user}@{host}). This is a CREDENTIAL problem, "
            "not a network one -- the configured secret is stale or that host rotated separately."
        ) from ex
    return client


def run(ssh, cmd, timeout=120):
    _, out, err = ssh.exec_command(cmd, timeout=timeout)
    return (out.read().decode(errors="replace").strip(),
            err.read().decode(errors="replace").strip())


def remote_md5s(ssh, root, paths, label):
    """md5 every path, and treat a missing line as an ERROR, never as drift.

    A file that vanished and a file that changed are different problems with
    the same shape in a naive diff, and the wrong one gets acted on: the tool
    would happily "restore" a path the fleet deliberately dropped.
    """
    quoted = " ".join(f"'{root}/{p}'" for p in paths)
    out, _ = run(ssh, f"md5sum {quoted} 2>/dev/null", timeout=180)
    got = {}
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        name = parts[1].strip()
        for p in paths:
            if name.endswith(p):
                got[p] = parts[0].lower()
    missing = [p for p in paths if p not in got]
    if missing:
        sys.exit(f"FATAL: {label} did not return an md5 for: {', '.join(missing)}\n"
                 "       Aborting -- a missing artifact is not drift and must not be 'fixed' by a copy.")
    return got


def local_md5(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_runner_idle(ssh):
    """Is a test server live in the runner tree? Reported, not enforced here.

    Every check reports and returns; refusal happens once, at the write
    boundary. A guard that exits early makes the dry run -- the thing an
    operator reaches for precisely when the estate is in an odd state --
    print nothing about the drift it was asked to describe.
    """
    out, _ = run(ssh, f"pgrep -af '{RUNNER_TREE}' | grep -v pgrep")
    busy = [ln for ln in out.splitlines() if "hlds_linux" in ln]
    if not busy:
        return None
    print("A test server is running out of the runner tree:")
    for ln in busy:
        print("  " + ln)
    return ("a Tier-2 run is in flight -- swapping the stack under a live hlds_linux "
            "gives a result nobody can interpret afterwards", "--ignore-running")


def ref_root(ssh):
    """Absolute path to the reference tree.

    Resolved rather than spelled `~/...`: sftp does not expand a tilde at
    all, and a tilde inside the single quotes md5sum needs is a literal
    directory name -- so both halves of this tool would look at a path that
    does not exist, and the md5 half would report it as missing.
    """
    home, _ = run(ssh, "echo $HOME")
    home = home.strip()
    if not home.startswith("/"):
        sys.exit(f"FATAL: could not resolve the reference user's home directory (got {home!r}).")
    return posixpath.join(home, REF_TREE)


def check_pending_wave(ssh, root):
    """A staged `.new` on the reference means the fleet moves again at 03:00.

    The globs mirror the nightly auto-swap, which is explicit rather than
    recursive -- a recursive find here would report `.new` files the restart
    script would never activate.
    """
    globs = " ".join(f"{root}/{g}" for g in (
        "*.new", "dod/addons/ktpamx/dlls/*.new",
        "dod/addons/ktpamx/modules/*.new", "dod/addons/ktpamx/plugins/*.new"))
    out, _ = run(ssh, f"ls -1 {globs} 2>/dev/null")
    pending = [ln for ln in out.splitlines() if ln.strip()]
    if not pending:
        return None
    print("The reference instance is holding a STAGED WAVE:")
    for path in pending:
        print("  " + path)
    print("Those activate at the next 03:00 restart, so a sync now goes stale tonight.")
    print("")
    return ("the fleet is holding a staged wave, so this sync is stale at the next 03:00",
            "--ack-pending-wave")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="Actually write to the runner. Without it, nothing is modified.")
    ap.add_argument("--ack-pending-wave", action="store_true",
                    help="Proceed although the reference instance is holding staged .new files.")
    ap.add_argument("--ignore-running", action="store_true",
                    help="Proceed although a test server is live in the runner tree.")
    args = ap.parse_args()

    paths, excluded = sync_set()

    ref = connect(REF_HOST, REF_USER, password=REF_PASSWORD, label="the fleet reference")
    try:
        ref_tree = ref_root(ref)
        blockers = [b for b in (check_pending_wave(ref, ref_tree),) if b]
        fleet = remote_md5s(ref, ref_tree, paths, f"the reference {REF_USER}@{REF_HOST}")
    except SystemExit:
        ref.close()
        raise

    runner = connect(RUNNER_HOST, RUNNER_USER,
                     password=os.environ.get("KTP_TIER2_SSH_PASSWORD"),
                     key=os.environ.get("KTP_TIER2_SSH_KEY"), label="the Tier-2 runner")
    try:
        blockers += [b for b in (check_runner_idle(runner),) if b]
        held = remote_md5s(runner, RUNNER_TREE, paths, f"the runner {RUNNER_USER}@{RUNNER_HOST}")

        drifted = [p for p in paths if held[p] != fleet[p]]
        print(f"Reference {REF_USER}@{REF_HOST}:{ref_tree}")
        print(f"Runner    {RUNNER_USER}@{RUNNER_HOST}:{RUNNER_TREE}\n")
        for p in paths:
            mark = "DRIFT" if p in drifted else "ok   "
            detail = f"  runner {held[p][:8]}… vs fleet {fleet[p][:8]}…" if p in drifted else ""
            print(f"  [{mark}] {p}{detail}")
        print("\nLeft alone by design (test-mode or built per run): "
              + ", ".join(posixpath.basename(p) for p in sorted(excluded)))

        if not drifted:
            print("\nRunner stack already matches the reference. Nothing to do.")
            return 0
        print(f"\n{len(drifted)} file(s) would be replaced.")
        acked = {"--ack-pending-wave": args.ack_pending_wave,
                 "--ignore-running": args.ignore_running}
        unacked = [(why, flag) for why, flag in blockers if not acked[flag]]
        for why, flag in blockers:
            state = "acknowledged" if acked[flag] else "needs " + flag
            print(f"BLOCKER ({state}): {why}")
        if not args.apply:
            print("DRY RUN: nothing written. Re-run with --apply to sync.")
            return 0
        if unacked:
            sys.exit("FATAL: refusing to write to the runner while a blocker above is "
                     "unacknowledged. Nothing was changed.")

        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = f"{posixpath.dirname(RUNNER_TREE)}/stack-bak-pre-resync-{stamp}"
        sftp_ref = ref.open_sftp()
        sftp_run = runner.open_sftp()
        synced = {}
        try:
            for p in drifted:
                out, err = run(runner, f"mkdir -p '{backup}/{posixpath.dirname(p)}' && "
                                       f"cp -p '{RUNNER_TREE}/{p}' '{backup}/{p}' && echo OK")
                if out != "OK":
                    sys.exit(f"FATAL: could not back up {p} to {backup}: {err or out}\n"
                             "       Nothing further was written.")

                tmp = tempfile.NamedTemporaryFile(delete=False)
                tmp.close()
                try:
                    remote_src = f"{ref_tree}/{p}"
                    sftp_ref.get(remote_src, tmp.name)
                    if local_md5(tmp.name) != fleet[p]:
                        sys.exit(f"FATAL: {p} changed or landed short during the pull from the "
                                 "reference. Nothing was written to the runner for this file; "
                                 f"earlier files are backed up at {backup}.")
                    mode = statmod.S_IMODE(sftp_ref.stat(remote_src).st_mode)
                    sftp_run.put(tmp.name, f"{RUNNER_TREE}/{p}")
                    sftp_run.chmod(f"{RUNNER_TREE}/{p}", mode)
                finally:
                    os.unlink(tmp.name)

                back, _ = run(runner, f"md5sum '{RUNNER_TREE}/{p}' | cut -d' ' -f1")
                if back.lower() != fleet[p]:
                    sys.exit(f"FATAL: post-transfer md5 mismatch on {p}: runner has "
                             f"{back or 'NOTHING'}, expected {fleet[p]}.\n"
                             f"       Restore from {backup}/{p} before running the suite.")
                synced[p] = fleet[p]
                print(f"  synced {p}  {fleet[p]}")
        finally:
            sftp_ref.close()
            sftp_run.close()

        record = {
            "synced_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "synced_by": f"{getpass.getuser()} via sync-runner-stack.py",
            "reference": f"{REF_USER}@{REF_HOST}:{ref_tree}",
            "backup": backup,
            "files": synced,
        }
        payload = json.dumps(record, indent=2, sort_keys=True)
        tmp_remote = f"{RECORD}.tmp.{stamp}"
        sftp_run = runner.open_sftp()
        try:
            with sftp_run.file(tmp_remote, "w") as fh:
                fh.write(payload)
            run(runner, f"mv -f '{tmp_remote}' '{RECORD}'")
        finally:
            sftp_run.close()
    finally:
        runner.close()
        ref.close()

    print("\n" + "=" * 70)
    print(f"RUNNER STACK SYNCED from {REF_HOST}  ({len(synced)} file(s))")
    print(f"  backup   {backup}")
    print(f"  record   {RECORD}")
    print("\nConfirm the tripwire agrees, from the data server:")
    print("  /usr/local/bin/ktp-tier2-heartbeat.sh")
    print("\nThe test-mode plugins are a separate question this tool does not answer:")
    print("  stage-runner.py --show")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
