#!/usr/bin/env python3
"""
Deploy the canonical ktp-scheduled-restart.sh to every game host.

Safety model:
  - The canonical script is gitignored (it embeds the relay AUTH_SECRET), so
    there is no git baseline. Instead: fetch every host's deployed copy FIRST
    and require fleet consensus (all identical). The consensus md5 becomes the
    drift baseline; a host that disagrees with consensus is SKIPPED unless
    --force — never silently clobber an out-of-band-edited production script.
    A unified diff of consensus vs the new canonical is printed up front for
    eyeball review.
  - Timestamped backup (~/ktp-scheduled-restart.sh.bak-YYYYMMDD-HHMMSS) before
    every overwrite; a failed backup skips the host.
  - The live script is never written in place (cron executes it at 03:00 ET):
    upload goes to a .tmp sibling, ALL verification runs against the .tmp, and
    only a passing .tmp is atomically posix_rename()d over the target. A failed
    post-swap re-check auto-restores the backup. Still: avoid running within
    ~10 minutes of 03:00 ET.
  - Verification: remote md5 == local md5, `bash -n` passes on the
    host, and the known tripwire greps (from root CLAUDE.md) still hit:
      'Checking for staged .new files'  == 1
      'addons/ktpamx/modules/\\*.new'    >= 2
      'created missing.*monitoring.lock' >= 1
      'ktp_extension_loaded'             >= 3   (R8 assert, added 2026-07-07)

Usage:
    deploy-restart-script.py [--hosts atlanta,dallas] [--force] [--dry-run]

Password: $KTP_FLEET_SSH_PASSWORD or ~/.ktp_fleet_ssh_password (never hardcoded).
"""

import argparse
import hashlib
import os
import sys
import time

# Windows consoles default to a legacy codepage; the script body contains
# UTF-8 punctuation that must survive diff printing.
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

try:
    import paramiko
except ImportError:
    print("ERROR: paramiko not installed. Run: pip install paramiko")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CANONICAL = os.path.join(SCRIPT_DIR, "ktp-scheduled-restart.sh")
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
REMOTE_PATH = "ktp-scheduled-restart.sh"  # relative to ~dodserver

SERVERS = {
    'atlanta': '74.91.121.9',
    'dallas':  '74.91.126.55',
    'denver':  '66.163.114.109',
    'newyork': '74.91.123.64',
    'chicago': '172.238.176.101',
}

# Formatted with the path under test (the .tmp during pre-swap verification).
TRIPWIRES = [
    ("grep -c 'Checking for staged .new files' {path}", 1, "=="),
    ("grep -c 'addons/ktpamx/modules/\\*.new' {path}", 2, ">="),
    ("grep -c 'created missing.*monitoring.lock' {path}", 1, ">="),
    ("grep -c 'ktp_extension_loaded' {path}", 3, ">="),
]


def fleet_password():
    pw = os.environ.get('KTP_FLEET_SSH_PASSWORD')
    if not pw:
        p = os.path.expanduser('~/.ktp_fleet_ssh_password')
        if os.path.exists(p):
            pw = open(p).read().strip()
    if not pw:
        raise SystemExit('SSH password not configured — set $KTP_FLEET_SSH_PASSWORD '
                         'or write it to ~/.ktp_fleet_ssh_password')
    return pw


def md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def fetch_deployed(host, pw):
    """Return (md5, content) of the deployed script on a host, or (None, None)."""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username='dodserver', password=pw, timeout=20)
    try:
        sftp = ssh.open_sftp()
        try:
            data = sftp.open(REMOTE_PATH, 'rb').read()
        except IOError:
            return None, None
        return md5_bytes(data), data
    finally:
        ssh.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hosts', help='comma-separated subset (default: all)')
    ap.add_argument('--force', action='store_true',
                    help='overwrite even when a host drifted from the fleet consensus '
                         '(the canonical is gitignored — consensus IS the baseline)')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    targets = list(SERVERS) if not args.hosts else [h.strip() for h in args.hosts.split(',')]
    for t in targets:
        if t not in SERVERS:
            raise SystemExit(f"unknown host '{t}' (know: {', '.join(SERVERS)})")

    local = open(CANONICAL, 'rb').read()
    if b'\r' in local:
        raise SystemExit("canonical script contains CR bytes — fix line endings first")
    local_md5 = md5_bytes(local)
    print(f"canonical (working tree): {local_md5}  ({len(local)} bytes)")

    pw = fleet_password()

    # Phase 1: fleet-consensus drift baseline
    print("\nPhase 1: fetching deployed copies for consensus check...")
    deployed_md5 = {}
    sample_content = None
    for name in targets:
        try:
            m, data = fetch_deployed(SERVERS[name], pw)
            deployed_md5[name] = m
            if sample_content is None and data is not None:
                sample_content = data
            print(f"  {name}: {m or 'ABSENT'}")
        except Exception as e:
            print(f"  {name}: FETCH ERROR {e}")
            deployed_md5[name] = 'ERROR'
    fetched = {m for m in deployed_md5.values() if m not in (None, 'ERROR')}
    distinct = set(fetched)
    consensus = next(iter(distinct)) if len(distinct) == 1 else None
    if consensus is None and not args.force:
        raise SystemExit(f"No fleet consensus (distinct deployed md5s: {len(distinct)}; "
                         f"absent/errored hosts excluded) — inspect by hand or rerun with --force")
    # "Nothing to deploy" requires EVERY targeted host to already match — an
    # absent or fetch-errored host must not be silently skipped just because
    # the reachable ones form a matching consensus (its cron would run a stale
    # or missing script at 03:00 while this tool reports green).
    if all(m == local_md5 for m in deployed_md5.values()):
        print("\nFleet already matches the canonical — nothing to deploy.")
        return
    if sample_content is not None:
        import difflib
        diff = list(difflib.unified_diff(
            sample_content.decode(errors='replace').splitlines(),
            local.decode(errors='replace').splitlines(),
            fromfile='deployed(consensus)', tofile='canonical(new)', lineterm=''))
        adds = sum(1 for l in diff if l.startswith('+') and not l.startswith('+++'))
        dels = sum(1 for l in diff if l.startswith('-') and not l.startswith('---'))
        print(f"\nConsensus -> new canonical: +{adds} / -{dels} lines")
        for l in diff[:120]:
            print("  " + l)
        if len(diff) > 120:
            print(f"  ... ({len(diff) - 120} more diff lines)")

    if args.dry_run:
        print("\ndry-run: stopping before deploy phase")
        return

    # Phase 2: deploy + verify
    ok = fail = skip = 0
    for name in targets:
        host = SERVERS[name]
        print(f"\n===== {name} ({host}) =====")
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(host, username='dodserver', password=pw, timeout=20)
            sftp = ssh.open_sftp()

            dep_md5 = deployed_md5.get(name)
            if dep_md5 == local_md5:
                print("  already current — nothing to do")
                ok += 1
                ssh.close()
                continue
            if dep_md5 not in (consensus, None) and not args.force:
                print(f"  DRIFT: deployed {dep_md5} != consensus {consensus} — SKIPPING")
                skip += 1
                ssh.close()
                continue
            backup = None
            if dep_md5 is not None:
                stamp = time.strftime('%Y%m%d-%H%M%S')
                backup = f"{REMOTE_PATH}.bak-{stamp}"
                _, out, _ = ssh.exec_command(f"cp ~/{REMOTE_PATH} ~/{backup}", timeout=30)
                if out.channel.recv_exit_status() != 0:
                    print(f"  BACKUP FAILED (cp -> ~/{backup}) — SKIPPING host")
                    skip += 1
                    ssh.close()
                    continue
                print(f"  backed up -> ~/{backup}")

            # Upload to a sibling .tmp and verify THERE — the live script (which
            # cron executes at 03:00) is only replaced by an atomic rename of a
            # fully-verified file.
            tmp = f"{REMOTE_PATH}.tmp"
            with sftp.open(tmp, 'wb') as f:
                f.write(local)
            sftp.chmod(tmp, 0o755)

            # Verify: md5, bash -n, tripwires — all against the .tmp
            _, out, _ = ssh.exec_command(f"md5sum ~/{tmp}", timeout=30)
            rmd5 = out.read().decode().split()[0]
            _, out, err = ssh.exec_command(f"bash -n ~/{tmp} && echo SYNTAX_OK", timeout=30)
            syntax = 'SYNTAX_OK' in out.read().decode()
            trip_fail = []
            for tmpl, want, op in TRIPWIRES:
                cmd = tmpl.format(path=f"~/{tmp}")
                _, o, _ = ssh.exec_command(cmd, timeout=30)
                got = int((o.read().decode().strip() or '0'))
                good = (got == want) if op == '==' else (got >= want)
                if not good:
                    trip_fail.append(f"{cmd} -> {got} (want {op}{want})")

            if rmd5 != local_md5 or not syntax or trip_fail:
                print(f"  FAIL (pre-swap, live script untouched): md5={rmd5} "
                      f"(want {local_md5}) syntax={syntax}")
                for t in trip_fail:
                    print(f"    tripwire: {t}")
                try:
                    sftp.remove(tmp)
                except IOError:
                    pass
                fail += 1
                ssh.close()
                continue

            # Atomic swap, then a cheap post-swap re-check; auto-restore on mismatch.
            sftp.posix_rename(tmp, REMOTE_PATH)
            _, out, _ = ssh.exec_command(f"md5sum ~/{REMOTE_PATH}", timeout=30)
            live_md5 = out.read().decode().split()[0]
            if live_md5 == local_md5:
                print(f"  OK: md5 {live_md5}, syntax OK, tripwires pass (atomic swap)")
                ok += 1
            elif backup:
                _, out, _ = ssh.exec_command(
                    f"cp ~/{backup} ~/{REMOTE_PATH} && chmod 755 ~/{REMOTE_PATH}", timeout=30)
                restored = out.channel.recv_exit_status() == 0
                print(f"  FAIL post-swap: live md5={live_md5} (want {local_md5}) — "
                      f"backup restore {'OK' if restored else 'FAILED — FIX BY HAND NOW'}")
                fail += 1
            else:
                print(f"  FAIL post-swap: live md5={live_md5} (want {local_md5}) — "
                      "no backup existed (file was absent) — FIX BY HAND")
                fail += 1
            ssh.close()
        except Exception as e:
            print(f"  ERROR: {e}")
            fail += 1

    print(f"\nSummary: {ok} OK, {skip} skipped (drift), {fail} failed")
    sys.exit(0 if fail == 0 and skip == 0 else 1)


if __name__ == '__main__':
    main()
