#!/usr/bin/env python3
"""
Deploy one or more local artifacts to all (or a subset of) game-server instances
as `.new` files. The next nightly 03:00 ET scheduled restart picks `.new` files
up via the auto-swap glob in `ktp-scheduled-restart.sh` and atomically moves
them into place during the stop-start gap.

Fills the missing local->fleet push step that nothing in the existing toolchain
covered before. Auto-swap on the game-host side has been live since `e0d571c`
(2026-04-21); the plugin glob landed 2026-04-29; engine globs predate both.

Usage:
    deploy-to-fleet.py -f path/to/file.amxx [-f path/to/file.so ...] \\
                       [--hosts atlanta,dallas | --all] \\
                       [--remote-path serverfiles/dod/addons/ktpamx/modules] \\
                       [--dry-run]

Artifact auto-routing (when --remote-path not given), matched on basename:
    ktpamx_i386.so       -> serverfiles/dod/addons/ktpamx/dlls/
    *_ktp_i386.so        -> serverfiles/dod/addons/ktpamx/modules/   (dodx/reapi/amxxcurl)
    *.amxx               -> serverfiles/dod/addons/ktpamx/plugins/
    engine_i486.so       -> serverfiles/
    hlds_linux           -> serverfiles/
    libsteam_api.so      -> serverfiles/

Behavior:
    - Per (host, port) instance: SCP file -> ~/dod-{port}/<remote_path>/<basename>.new
    - md5 verify after each upload; mark failed if mismatch
    - Per-instance failures isolated (one host down doesn't abort the others)
    - Summary table at end: OK / FAIL counts per artifact per host
    - --dry-run prints intent without connecting

Activation: NO automatic restart. The `.new` files sit on disk until the next
nightly restart (`ktp-scheduled-restart.sh`, 03:00 ET) auto-swaps + restarts.
This is intentional: never restart production servers without explicit operator
permission. If immediate activation is required, schedule a manual restart
window with the operator.

Authored 2026-05-21 to close the fleet-deploy gap discovered 2026-05-20.
"""

import argparse
import hashlib
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

try:
    import paramiko
except ImportError:
    print("ERROR: paramiko not installed. Run: pip install paramiko")
    sys.exit(1)


def _fleet_ssh_password():
    """dodserver SSH password — from $KTP_FLEET_SSH_PASSWORD or ~/.ktp_fleet_ssh_password.
    Never hardcoded: the prior value leaked in this public repo and was rotated 2026-05-31."""
    import os
    pw = os.environ.get('KTP_FLEET_SSH_PASSWORD')
    if not pw:
        p = os.path.expanduser('~/.ktp_fleet_ssh_password')
        if os.path.exists(p):
            pw = open(p).read().strip()
    if not pw:
        raise SystemExit('dodserver SSH password not configured — set $KTP_FLEET_SSH_PASSWORD '
                         'or write it to ~/.ktp_fleet_ssh_password')
    return pw


# All five active fleet hosts.  Per CLAUDE.md root creds, but we use the
# dodserver user since all deploy paths land under ~dodserver/.
# Per-host port lists (mirrors ktp-verify-deploy.py): Chicago 27019 is
# DISABLED — staging a .new there was a landmine: the restart script skips
# .ktp-disabled instances so the file never swapped, verify-deploy never
# checked it, and a months-stale binary would silently activate if 27019
# were ever re-enabled.
SERVERS = {
    'atlanta': {'host': '74.91.121.9',   'user': 'dodserver', 'description': 'Atlanta Baremetal',
                'ports': [27015, 27016, 27017, 27018, 27019]},
    'dallas':  {'host': '74.91.126.55',  'user': 'dodserver', 'description': 'Dallas Baremetal',
                'ports': [27015, 27016, 27017, 27018, 27019]},
    'denver':  {'host': '66.163.114.109','user': 'dodserver', 'description': 'Denver Baremetal',
                'ports': [27015, 27016, 27017, 27018, 27019]},
    'newyork': {'host': '74.91.123.64',  'user': 'dodserver', 'description': 'New York Baremetal',
                'ports': [27015, 27016, 27017, 27018, 27019]},
    'chicago': {'host': '172.238.176.101','user': 'dodserver', 'description': 'Chicago VPS (27019 disabled)',
                'ports': [27015, 27016, 27017, 27018]},
}

PORTS = [27015, 27016, 27017, 27018, 27019]   # default; per-host 'ports' wins

# Auto-routing rules. Pattern is matched on the basename's tail; first match wins.
ROUTING = [
    ('ktpamx_i386.so',  'serverfiles/dod/addons/ktpamx/dlls'),
    ('_ktp_i386.so',    'serverfiles/dod/addons/ktpamx/modules'),
    ('.amxx',           'serverfiles/dod/addons/ktpamx/plugins'),
    ('engine_i486.so',  'serverfiles'),
    ('hlds_linux',      'serverfiles'),
    ('libsteam_api.so', 'serverfiles'),
]


def route_for(filename: str) -> str | None:
    base = os.path.basename(filename)
    for suffix, path in ROUTING:
        if base.endswith(suffix):
            return path
    return None


def local_md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Artifact:
    local_path: str
    remote_dir: str          # relative to ~/dod-{port}/
    basename: str            # filename
    md5: str
    size: int


@dataclass
class Outcome:
    host_key: str
    port: int
    artifact: str
    status: str              # 'ok' | 'md5_mismatch' | 'ssh_fail' | 'sftp_fail' | 'dry_run'
    detail: str = ''
    elapsed_ms: int = 0


def build_artifacts(files: list[str], override_remote: str | None) -> list[Artifact]:
    out = []
    for f in files:
        if not os.path.isfile(f):
            print(f"FATAL: local file not found: {f}", file=sys.stderr)
            sys.exit(1)
        remote_dir = override_remote
        if not remote_dir:
            remote_dir = route_for(f)
            if not remote_dir:
                print(f"FATAL: cannot auto-route artifact (provide --remote-path): {f}", file=sys.stderr)
                sys.exit(1)
        out.append(Artifact(
            local_path=f,
            remote_dir=remote_dir,
            basename=os.path.basename(f),
            md5=local_md5(f),
            size=os.path.getsize(f),
        ))
    return out


def deploy_to_instance(host_key: str, host_info: dict, port: int, artifacts: list[Artifact],
                       dry_run: bool, timeout: int = 30) -> list[Outcome]:
    results = []
    if dry_run:
        for a in artifacts:
            results.append(Outcome(host_key, port, a.basename, 'dry_run',
                                   f"would push to ~/dod-{port}/{a.remote_dir}/{a.basename}.new"))
        return results

    t0 = time.time()
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(host_info['host'], username=host_info['user'],
                    password=_fleet_ssh_password(), timeout=timeout)
    except Exception as e:
        for a in artifacts:
            results.append(Outcome(host_key, port, a.basename, 'ssh_fail', str(e)[:80]))
        return results

    try:
        sftp = ssh.open_sftp()
        for a in artifacts:
            t_a = time.time()
            remote_target = f'/home/{host_info["user"]}/dod-{port}/{a.remote_dir}/{a.basename}.new'
            try:
                sftp.put(a.local_path, remote_target)
            except Exception as e:
                results.append(Outcome(host_key, port, a.basename, 'sftp_fail', str(e)[:80]))
                continue

            # md5 verify post-upload
            stdin, stdout, stderr = ssh.exec_command(f"md5sum '{remote_target}'", timeout=15)
            out = stdout.read().decode('utf-8', errors='replace').strip()
            remote_md5 = out.split()[0] if out else ''
            elapsed_ms = int((time.time() - t_a) * 1000)
            if remote_md5 == a.md5:
                results.append(Outcome(host_key, port, a.basename, 'ok',
                                       f"{a.size}B, md5 {a.md5[:8]}, {elapsed_ms}ms",
                                       elapsed_ms=elapsed_ms))
            else:
                results.append(Outcome(host_key, port, a.basename, 'md5_mismatch',
                                       f"local={a.md5[:12]} remote={remote_md5[:12]}",
                                       elapsed_ms=elapsed_ms))
        sftp.close()
    finally:
        ssh.close()

    return results


def print_summary(outcomes: list[Outcome], artifacts: list[Artifact], dry_run: bool):
    print()
    print("=" * 78)
    print(f"DEPLOY SUMMARY  ({'DRY-RUN' if dry_run else 'LIVE'})")
    print("=" * 78)

    # Per-artifact totals
    for a in artifacts:
        relevant = [o for o in outcomes if o.artifact == a.basename]
        oks = sum(1 for o in relevant if o.status in ('ok', 'dry_run'))
        fails = sum(1 for o in relevant if o.status in ('md5_mismatch', 'ssh_fail', 'sftp_fail'))
        total = len(relevant)
        print(f"  {a.basename}  ({a.remote_dir}/<name>.new)")
        print(f"    {oks}/{total} OK, {fails} FAIL  [md5 {a.md5}, {a.size} bytes]")

    # Failures detail
    failures = [o for o in outcomes if o.status in ('md5_mismatch', 'ssh_fail', 'sftp_fail')]
    if failures:
        print()
        print(f"FAILURES ({len(failures)}):")
        for o in failures:
            print(f"  {o.host_key}:{o.port}  {o.artifact}  {o.status}  {o.detail}")
    else:
        print()
        print("All instances OK." if not dry_run else "All instances would receive artifacts (dry-run).")

    # Next steps hint
    if not dry_run:
        print()
        print("NEXT: .new files are staged on disk. They auto-swap at the next nightly")
        print("      3:00 AM ET restart cycle via ktp-scheduled-restart.sh. To activate")
        print("      sooner, schedule a manual restart window with the operator.")


def main():
    parser = argparse.ArgumentParser(
        description='Deploy artifacts as .new files to fleet instances (auto-swap activates at nightly restart).',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-f', '--file', action='append', required=True, dest='files',
                        help='Local artifact path. Repeatable for multi-file pushes.')
    parser.add_argument('--remote-path', default=None,
                        help='Override remote subdir (relative to ~/dod-{port}/). Default: auto-route by filename.')
    parser.add_argument('--hosts', default='all',
                        help=f'Comma-separated host list (or "all"). Choices: {",".join(SERVERS.keys())} (default: all)')
    parser.add_argument('--ports', default='all',
                        help=f'Comma-separated port list (or "all"). Choices: {",".join(map(str, PORTS))} (default: all)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print intent without connecting.')
    parser.add_argument('--parallel', type=int, default=5,
                        help='Max parallel host connections (default: 5 = one per host)')
    args = parser.parse_args()

    # Validate + build target list
    if args.hosts == 'all':
        host_keys = list(SERVERS.keys())
    else:
        host_keys = [h.strip() for h in args.hosts.split(',')]
        for k in host_keys:
            if k not in SERVERS:
                print(f"FATAL: unknown host '{k}' (choices: {','.join(SERVERS.keys())})", file=sys.stderr)
                sys.exit(1)

    if args.ports == 'all':
        ports = PORTS
    else:
        try:
            ports = [int(p.strip()) for p in args.ports.split(',')]
        except ValueError:
            print(f"FATAL: --ports must be comma-separated integers", file=sys.stderr)
            sys.exit(1)
        for p in ports:
            if p not in PORTS:
                print(f"FATAL: unknown port {p} (choices: {','.join(map(str, PORTS))})", file=sys.stderr)
                sys.exit(1)

    artifacts = build_artifacts(args.files, args.remote_path)

    print(f"Local artifacts ({len(artifacts)}):")
    for a in artifacts:
        print(f"  {a.local_path}")
        print(f"    -> dod-*/{a.remote_dir}/{a.basename}.new  ({a.size} bytes, md5 {a.md5})")

    # Intersect the requested ports with each host's active list — CHI 27019
    # is disabled and must never receive a staged .new (see SERVERS comment).
    target_instances = [
        (hk, p) for hk in host_keys for p in ports
        if p in SERVERS[hk].get('ports', PORTS)
    ]
    skipped = [(hk, p) for hk in host_keys for p in ports
               if p not in SERVERS[hk].get('ports', PORTS)]
    for hk, p in skipped:
        print(f"NOTE: skipping {hk}:{p} — disabled instance (per-host port list)")
    if not target_instances:
        print("FATAL: nothing to do — every requested (host, port) pair is disabled",
              file=sys.stderr)
        sys.exit(1)
    print(f"\nTarget instances ({len(target_instances)}): "
          f"{', '.join(f'{hk}:{p}' for hk, p in target_instances[:6])}"
          + (f', ... ({len(target_instances)-6} more)' if len(target_instances) > 6 else ''))
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print()

    outcomes: list[Outcome] = []
    t0 = time.time()

    # One connection per HOST, deploy all that host's ports sequentially through
    # the same SSH session. Hosts run in parallel.
    def host_worker(host_key: str) -> list[Outcome]:
        host_info = SERVERS[host_key]
        host_ports = [p for hk, p in target_instances if hk == host_key]
        host_outcomes: list[Outcome] = []
        for port in host_ports:
            host_outcomes.extend(deploy_to_instance(host_key, host_info, port, artifacts, args.dry_run))
        return host_outcomes

    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {pool.submit(host_worker, hk): hk for hk in host_keys}
        for fut in as_completed(futures):
            hk = futures[fut]
            try:
                result = fut.result()
                outcomes.extend(result)
                ok = sum(1 for o in result if o.status in ('ok', 'dry_run'))
                fail = len(result) - ok
                n_ports = sum(1 for h, _ in target_instances if h == hk)
                print(f"  [{hk}] {ok} OK, {fail} FAIL  ({len(result)} total: "
                      f"{n_ports} ports x {len(artifacts)} artifacts)")
            except Exception as e:
                print(f"  [{hk}] worker crashed: {e}")

    print(f"\nTotal elapsed: {time.time()-t0:.1f}s")
    print_summary(outcomes, artifacts, args.dry_run)

    # Exit nonzero on any failure
    fails = sum(1 for o in outcomes if o.status in ('md5_mismatch', 'ssh_fail', 'sftp_fail'))
    sys.exit(0 if fails == 0 else 1)


if __name__ == '__main__':
    main()
