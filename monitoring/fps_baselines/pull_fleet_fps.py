#!/usr/bin/env python3
"""Pull a fleet-wide [KTP_PROFILE] FPS snapshot.

SSHes to each game server and greps ~/dod-<port>/log/console/ for
`[KTP_PROFILE] frames=N fps=X.Y` lines. Aggregates fleet / per-host /
per-instance stats and writes a JSON snapshot matching the format used
by fleet_fps_2026-04-23_pre-jit.json.

Usage:
    python pull_fleet_fps.py <output-name-suffix> [--label <label>] [--description <text>]

Example:
    python pull_fleet_fps.py 2026-04-25_post-jit --label post-jit \
        --description "Post-JIT activation. Fleet-wide debug-flag strip..."
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import re
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

import paramiko

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


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


SERVERS = {
    'atlanta': {'host': '74.91.121.9',     'user': 'dodserver'},
    'dallas':  {'host': '74.91.126.55',    'user': 'dodserver'},
    'denver':  {'host': '66.163.114.109',  'user': 'dodserver'},
    'newyork': {'host': '74.91.123.64',    'user': 'dodserver'},
    'chicago': {'host': '172.238.176.101', 'user': 'dodserver'},
}
PORTS = [27015, 27016, 27017, 27018, 27019]

FPS_RE = re.compile(r'\[KTP_PROFILE\][^\n]*\bfps=([0-9]+(?:\.[0-9]+)?)')
NFO_LO, NFO_HI = 998.0, 1002.0
W10_LO, W10_HI = 990.0, 1010.0


def ssh_pull(host_label: str, host_cfg: dict, ports: Iterable[int]) -> dict[str, list[float]]:
    """Returns {f'{host_label}:{port}': [fps_floats]}."""
    out: dict[str, list[float]] = {}
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host_cfg['host'], username=host_cfg['user'],
                       password=_fleet_ssh_password(), timeout=15,
                       allow_agent=False, look_for_keys=False)
    except Exception as e:
        print(f'  [{host_label}] connect failed: {e}', file=sys.stderr)
        for p in ports:
            out[f'{host_label}:{p}'] = []
        return out

    try:
        # One ssh, all 5 ports, today + current rotated logs.
        # zgrep handles compressed rotations; plain grep handles current.
        cmd_parts = []
        for p in ports:
            cmd_parts.append(
                f'(grep -h "\\[KTP_PROFILE\\]" ~/dod-{p}/log/console/*-console.log 2>/dev/null | '
                f'awk -v port={p} \'{{print port "\\t" $0}}\')'
            )
        full = ' ; '.join(cmd_parts)
        stdin, stdout, stderr = client.exec_command(full, timeout=120)
        data = stdout.read().decode('utf-8', errors='replace')
    finally:
        client.close()

    by_port: dict[int, list[float]] = {p: [] for p in ports}
    for line in data.splitlines():
        if '\t' not in line:
            continue
        port_str, rest = line.split('\t', 1)
        try:
            port = int(port_str)
        except ValueError:
            continue
        m = FPS_RE.search(rest)
        if m:
            try:
                by_port[port].append(float(m.group(1)))
            except ValueError:
                pass
    for p, vals in by_port.items():
        out[f'{host_label}:{p}'] = vals
    return out


def stats_for(values: list[float]) -> dict:
    n = len(values)
    if n == 0:
        return {'n': 0, 'p50': None, 'p99': None, 'min': None, 'max': None,
                'mean': None, 'stdev': None,
                'pct_in_nfo_window': None, 'pct_within_10': None}
    s = sorted(values)
    p50 = s[int(n * 0.50)] if n > 1 else s[0]
    p99 = s[min(n - 1, int(n * 0.99))]
    in_nfo = sum(1 for v in values if NFO_LO <= v <= NFO_HI)
    in_w10 = sum(1 for v in values if W10_LO <= v <= W10_HI)
    return {
        'n': n,
        'p50': p50,
        'p99': p99,
        'min': min(values),
        'max': max(values),
        'mean': statistics.fmean(values),
        'stdev': statistics.pstdev(values) if n > 1 else 0.0,
        'pct_in_nfo_window': in_nfo / n,
        'pct_within_10': in_w10 / n,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('suffix', help='filename suffix, e.g. 2026-04-25_post-jit')
    ap.add_argument('--label', default=None)
    ap.add_argument('--description', default='')
    ap.add_argument('--out-dir', default=str(Path(__file__).parent))
    args = ap.parse_args()

    print(f'Pulling [KTP_PROFILE] data from {len(SERVERS)} hosts × {len(PORTS)} ports...',
          file=sys.stderr)
    start = dt.datetime.now(dt.timezone.utc)

    per_instance: dict[str, list[float]] = {}
    with ThreadPoolExecutor(max_workers=len(SERVERS)) as ex:
        futures = {ex.submit(ssh_pull, lbl, cfg, PORTS): lbl
                   for lbl, cfg in SERVERS.items()}
        for fut in as_completed(futures):
            lbl = futures[fut]
            try:
                got = fut.result()
            except Exception as e:
                print(f'  [{lbl}] task failed: {e}', file=sys.stderr)
                got = {f'{lbl}:{p}': [] for p in PORTS}
            per_instance.update(got)
            total = sum(len(v) for v in got.values())
            print(f'  [{lbl}] collected {total} samples across {len(PORTS)} ports',
                  file=sys.stderr)

    fleet: list[float] = []
    per_host: dict[str, list[float]] = {h: [] for h in SERVERS}
    for inst, vals in per_instance.items():
        host = inst.split(':', 1)[0]
        per_host[host].extend(vals)
        fleet.extend(vals)

    snapshot = {
        'label': args.label or args.suffix.split('_', 1)[-1],
        'captured_at_utc': start.isoformat().replace('+00:00', 'Z'),
        'description': args.description,
        'context': {},
        'fleet_stats': stats_for(fleet),
        'per_host_stats': {h: stats_for(v) for h, v in per_host.items()},
        'per_instance_stats': {k: stats_for(v) for k, v in sorted(per_instance.items())},
    }

    out_path = Path(args.out_dir) / f'fleet_fps_{args.suffix}.json'
    with out_path.open('w', encoding='utf-8') as f:
        json.dump(snapshot, f, indent=2)
    print(f'Wrote {out_path} ({snapshot["fleet_stats"]["n"]} fleet samples)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
