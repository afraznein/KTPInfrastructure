#!/usr/bin/env python3
"""Grep [KTP_OPCODE] cmd_ready/_cmd_ready_* spike lines fleet-wide
post-JIT (since 2026-04-24 03 AM ET activation)."""
import io, sys, paramiko
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SERVERS = {
    'atlanta': '74.91.121.9',
    'dallas':  '74.91.126.55',
    'denver':  '66.163.114.109',
    'newyork': '74.91.123.64',
    'chicago': '172.238.176.101',
}
PORTS = [27015, 27016, 27017, 27018, 27019]

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


def grep_one(label, host):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username='dodserver', password=_fleet_ssh_password(), timeout=15,
              allow_agent=False, look_for_keys=False)
    parts = []
    for p in PORTS:
        # Match either engine-level [KTP_OPCODE] cmd_ready warning or
        # AMXX-level "Function _cmd_ready_*" performance issue. Both
        # need the live console log; rotated logs don't help today.
        parts.append(
            f'(grep -hE "(\\[KTP_OPCODE\\][^\\n]*cmd_ready|Function _cmd_ready_)" '
            f'~/dod-{p}/log/console/*-console.log 2>/dev/null | '
            f'awk -v port={p} \'{{print port "\\t" $0}}\')'
        )
    cmd = ' ; '.join(parts)
    _, out, _ = c.exec_command(cmd, timeout=60)
    data = out.read().decode('utf-8', errors='replace')
    c.close()
    return label, data

results = {}
with ThreadPoolExecutor(max_workers=5) as ex:
    futs = {ex.submit(grep_one, lbl, h): lbl for lbl, h in SERVERS.items()}
    for fut in as_completed(futs):
        lbl, data = fut.result()
        results[lbl] = data
        n = sum(1 for line in data.splitlines() if line.strip())
        print(f'{lbl}: {n} matches', file=sys.stderr)

print()
total = 0
for lbl in SERVERS:
    data = results[lbl]
    lines = [l for l in data.splitlines() if l.strip()]
    if not lines:
        continue
    print(f'\n=== {lbl} ({len(lines)} lines) ===')
    for line in lines[:30]:
        print(f'  {line}')
    if len(lines) > 30:
        print(f'  ... +{len(lines)-30} more')
    total += len(lines)
print(f'\nTotal fleet matches: {total}')
