"""
KTP fleet drift audit.

Runs scripts/fleet-drift-snapshot.sh on every fleet host in parallel,
groups facts by (section, key), flags any key where hosts disagree, and
produces a markdown report. Intended to be run weekly or after any
production-tuning session to catch silent drift between the live fleet
and the documented state.

Usage:
    python3 audit-fleet-drift.py [--out report.md] [--include-ignored]
                                 [--state FILE] [--alert-discord]

Dependencies: paramiko.

Design notes:
- A "fact" is (section, key, value) where key is "line content before =" for
  key=value sections, or the line itself for list-only sections (GRUB cmdline,
  CPU idle states, etc.).
- IGNORED_KEYS covers things expected to differ per-host (IP, UUID, iface name).
- Chicago VPS is flagged separately because its topology differs from baremetals
  (no isolcpus, different kernel params, etc.) — drift within the baremetal
  group is the high-signal comparison.

Deployment (as weekly audit):
- Target host: data server (74.91.112.242) — always up, already runs other
  fleet ops, has Python + SSH keys for dodserver.
- Clone KTPInfrastructure to /opt/ktp-infra (or wherever).
- Install paramiko: `pip3 install paramiko` (or apt).
- Add crontab entry on data server, e.g.:
    0 5 * * MON cd /opt/ktp-infra && python3 scripts/audit-fleet-drift.py \\
        --out /var/log/ktp-audit-$(date +\%Y\%m\%d).md \\
        --state /var/lib/ktp-audit-state.json \\
        --alert-discord 2>&1 | tail -20 | mail -s 'KTP fleet drift' admin@ktp
- State file persists repo-drift items between runs; --alert-discord posts
  only the NEW items vs last run (not the full report) to the KTP Discord
  channel so silent drift creeping in triggers a notification.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import fnmatch
import io
import json
import os
import re
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import paramiko

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SNAPSHOT_SCRIPT = Path(__file__).with_name('fleet-drift-snapshot.sh')
EXPECTED_SYSCTLS = Path(__file__).resolve().parent.parent / 'provision' / 'expected-sysctls.conf'
EXPECTED_BINARIES = Path(__file__).resolve().parent.parent / 'provision' / 'expected-binaries.conf'
EXPECTED_CMDLINE = Path(__file__).resolve().parent.parent / 'provision' / 'expected-cmdline.conf'
EXPECTED_TIMERS = Path(__file__).resolve().parent.parent / 'provision' / 'expected-timers.conf'
EXPECTED_RC_LOCAL = Path(__file__).resolve().parent.parent / 'provision' / 'expected-rc-local.conf'

# Fleet config is loaded from an external JSON file at runtime (never
# committed — see `scripts/audit-fleet.json.example` for the schema).
#
# Default path: /etc/ktp/audit-fleet.json (mode 600, root-owned).
# Override via env var KTP_AUDIT_FLEET_CONFIG.
#
# Each entry:
#   name         — human-readable host label (used in reports + state keys)
#   host         — IP or DNS name for SSH
#   user         — SSH user
#   password     — SSH password (or null if using key-based auth; see `key_filename`)
#   key_filename — optional path to SSH private key (used instead of password)
#   group        — 'baremetal' or 'vps' (scopes expected-*.conf overrides)
#   sample_port  — dod-NNNNN instance used for per-port checks (default 27015;
#                  override per-host to sidestep a canary occupying 27015)
def load_fleet_config():
    config_path = Path(os.environ.get('KTP_AUDIT_FLEET_CONFIG',
                                      '/etc/ktp/audit-fleet.json'))
    if not config_path.exists():
        print(f'ERROR: fleet config not found at {config_path}', file=sys.stderr)
        print(f'Copy scripts/audit-fleet.json.example to {config_path} (or set',
              file=sys.stderr)
        print(f'KTP_AUDIT_FLEET_CONFIG) and fill in real credentials.',
              file=sys.stderr)
        sys.exit(1)
    try:
        data = json.loads(config_path.read_text())
    except Exception as e:
        print(f'ERROR: parsing fleet config {config_path}: {e}', file=sys.stderr)
        sys.exit(1)
    hosts = data.get('hosts')
    if not isinstance(hosts, list) or not hosts:
        print(f'ERROR: {config_path} missing non-empty "hosts" array', file=sys.stderr)
        sys.exit(1)
    for h in hosts:
        h.setdefault('sample_port', 27015)
    return hosts


HOSTS = load_fleet_config()

# Keys we expect to differ per host — suppress from drift report.
IGNORED_KEYS = {
    'HOST > hostname',
    'HOST > boot-time',
    'HOST > cpu-cores',          # Chicago 4 vs baremetal 8 expected
    'HOST > mem-total-kb',       # Denver 16GB vs others 32GB expected
    'HOST > cpu-model',          # Denver has older Xeon E3-1240 V2
    'SYSCTL (KTP-relevant) > net.ipv4.udp_mem',  # auto-scales with RAM
    'SYSCTL (KTP-relevant) > net.netfilter.nf_conntrack_max',  # auto-scales with RAM
    'KTP SAMPLE PORT > port',    # per-host override to dodge canary ports
}

# Sections where every line is a standalone fact (no key=value split).
LIST_SECTIONS = {
    'GRUB CMDLINE',
    'CPU GOVERNOR (distinct values)',
    'CPU IDLE STATE DISABLES',
    'KTP SYSTEMD TIMERS',
    'DODSERVER CRONTAB (non-comment, sorted)',
    '/etc/rc.local (non-comment, sorted)',
    '/etc/sysctl.conf (non-comment, sorted)',
}


def run_snapshot(host_info):
    """Run the snapshot script on one host, return (name, snapshot_text, error)."""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        connect_kwargs = {
            'hostname': host_info['host'],
            'username': host_info['user'],
            'timeout': 15,
        }
        if host_info.get('key_filename'):
            connect_kwargs['key_filename'] = host_info['key_filename']
        elif host_info.get('password'):
            connect_kwargs['password'] = host_info['password']
        # else: paramiko falls back to agent + ~/.ssh/id_* discovery
        ssh.connect(**connect_kwargs)
        sftp = ssh.open_sftp()
        sftp.put(str(SNAPSHOT_SCRIPT), '/tmp/_fleet_snapshot.sh')
        sftp.close()
        # Normalize line endings in case SFTP introduced CRLF
        ssh.exec_command('sed -i "s/\\r$//" /tmp/_fleet_snapshot.sh', timeout=15)
        # Pass the sample port via env var — snapshot script uses it for
        # per-port binary checks. Default matches the script's own default.
        port = host_info.get('sample_port', 27015)
        _, stdout, stderr = ssh.exec_command(
            f'KTP_SAMPLE_PORT={port} bash /tmp/_fleet_snapshot.sh', timeout=120)
        out = stdout.read().decode(errors='replace')
        err = stderr.read().decode(errors='replace').strip()
        ssh.close()
        return host_info['name'], out, err or None
    except Exception as e:
        try:
            ssh.close()
        except Exception:
            pass
        return host_info['name'], '', f'SSH/snapshot failed: {e}'


def parse_snapshot(text):
    """Parse snapshot text → {section: [(key, value)]}.

    For list-only sections, value is None and key is the line verbatim.
    For key=value sections, key and value are split on the first '=' (or ':').
    """
    sections = {}
    current = None
    buf = []

    def flush():
        if current is None:
            return
        facts = []
        for line in buf:
            line = line.rstrip()
            if not line:
                continue
            if current in LIST_SECTIONS:
                facts.append((line, None))
            else:
                # key=value or key: value
                m = re.match(r'^([^=:]+?)\s*[=:]\s*(.*)$', line)
                if m:
                    facts.append((m.group(1).strip(), m.group(2).strip()))
                else:
                    facts.append((line, None))
        sections[current] = facts

    for line in text.splitlines():
        m = re.match(r'^=== (.+?) ===$', line)
        if m:
            flush()
            current = m.group(1).strip()
            buf = []
        else:
            if current is not None:
                buf.append(line)
    flush()
    return sections


def compute_drift(host_snapshots, hosts_subset=None):
    """Build a nested dict: {section: {key: {value: [hosts]}}}.

    For list sections, key IS the line and value is None (so we're measuring
    presence/absence). For key=value, we group values across hosts per key.

    If hosts_subset is provided, only facts from those hosts contribute.
    """
    drift = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    if hosts_subset is None:
        all_hosts = list(host_snapshots.keys())
    else:
        all_hosts = [h for h in hosts_subset if h in host_snapshots]

    # Collect union of all sections across hosts in subset
    sections_seen = set()
    for host in all_hosts:
        sections_seen.update(host_snapshots.get(host, {}).keys())

    for section in sorted(sections_seen):
        # Union of keys in this section across subset
        keys_seen = set()
        for host in all_hosts:
            for k, v in host_snapshots.get(host, {}).get(section, []):
                keys_seen.add(k)

        for key in keys_seen:
            for host in all_hosts:
                facts = host_snapshots.get(host, {}).get(section, [])
                value = None
                present = False
                for k, v in facts:
                    if k == key:
                        present = True
                        value = v if v is not None else '<present>'
                        break
                if not present:
                    value = '<absent>'
                drift[section][key][value].append(host)

    return drift


def load_expected_sysctls(path):
    """Parse `provision/expected-sysctls.conf` into {group: {key: value}}.

    Returns a dict keyed by section name ('default', 'baremetal', 'vps').
    Missing sections are returned as empty dicts. Keys not specified in a
    group section fall back to 'default'.
    """
    groups = {'default': {}, 'baremetal': {}, 'vps': {}}
    if not path.exists():
        return groups

    current = 'default'
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('[') and line.endswith(']'):
            current = line[1:-1].strip()
            if current not in groups:
                groups[current] = {}
            continue
        m = re.match(r'^([^=]+?)\s*=\s*(.*)$', line)
        if m:
            groups[current][m.group(1).strip()] = m.group(2).strip()
    return groups


def load_expected_list(path):
    """Parse a list-style expected-state file (one fact per line, [group] sections).

    Returns {group: [line, ...]}. Used for sections where each line IS the fact
    (GRUB CMDLINE flags, systemd timer names, rc.local content) — as opposed
    to key=value sysctl/binary configs.

    Lines starting with # are comments. `[group]` headers switch scope.
    """
    groups = {'default': [], 'baremetal': [], 'vps': []}
    if not path.exists():
        return groups

    current = 'default'
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('[') and line.endswith(']'):
            current = line[1:-1].strip()
            if current not in groups:
                groups[current] = []
            continue
        groups[current].append(line)
    return groups


def compute_repo_list_drift(host_snapshots, host_groups, expected_by_group, section_name):
    """For list-section snapshots (GRUB CMDLINE, KTP SYSTEMD TIMERS, etc.),
    check each expected line is present on each host of the matching group.

    Returns list of (host, expected_line, '<present>', actual) where actual is
    '<absent>' if missing. Extra lines on the host that aren't in expected are
    ignored — we only enforce presence of the expected set, not exclusivity.
    """
    drift = []
    for host, snap in host_snapshots.items():
        group = host_groups.get(host, 'default')
        expected_lines = list(expected_by_group.get('default', []))
        expected_lines.extend(expected_by_group.get(group, []))

        # Live facts: list-section stores (line, None) per line
        live = {k for k, v in snap.get(section_name, [])}

        for exp_line in expected_lines:
            if exp_line not in live:
                drift.append((host, exp_line, '<present>', '<absent>'))

    return drift


def compute_repo_glob_drift(host_snapshots, host_groups, expected_by_group, section_name):
    """Like compute_repo_list_drift, but each expected "line" is a fnmatch
    glob pattern. Drift = no live line matches the pattern.

    Used for /etc/rc.local where legitimate per-host variation (NIC names,
    shell-style differences) makes literal-line matching too strict. Patterns
    encode the *intent* (e.g. `*ethtool -G*rx 4096 tx 4096*`) so a match is
    independent of NIC name or exact wrapping.
    """
    drift = []
    for host, snap in host_snapshots.items():
        group = host_groups.get(host, 'default')
        patterns = list(expected_by_group.get('default', []))
        patterns.extend(expected_by_group.get(group, []))

        live_lines = [k for k, v in snap.get(section_name, [])]

        for pat in patterns:
            matched = any(fnmatch.fnmatchcase(line, pat) for line in live_lines)
            if not matched:
                drift.append((host, pat, '<any line matching>', '<no match>'))

    return drift


def compute_repo_drift(host_snapshots, host_groups, expected_by_group, section_name):
    """Compare each host's live values (from one snapshot section) against
    the expected-state file. Returns a list of (host, key, expected, actual).

    Used for both sysctl and binary md5 comparisons — the format is identical
    (sectioned key=value file + per-section fact list in the snapshot).
    """
    drift = []
    for host, snap in host_snapshots.items():
        group = host_groups.get(host, 'default')
        # Merge default + group-specific, group wins
        expected = dict(expected_by_group.get('default', {}))
        expected.update(expected_by_group.get(group, {}))

        live = {}
        for k, v in snap.get(section_name, []):
            if v is not None:
                live[k] = v

        for key, exp_val in expected.items():
            actual = live.get(key)
            if actual is None:
                drift.append((host, key, exp_val, '<absent>'))
            elif actual.strip() != exp_val.strip():
                drift.append((host, key, exp_val, actual))

    return drift


def render_repo_drift_section(title, intro, drift_items, expected_by_group, expected_path):
    out = [f'## {title}']
    out.append(intro)
    out.append('')

    n_expected = sum(len(v) for v in expected_by_group.values())
    if n_expected == 0:
        out.append(f'_No expected-state file loaded (expected: `{expected_path}`)._')
        out.append('')
        return out

    if not drift_items:
        out.append(f'_All live fleet values match `{expected_path.name}` ({n_expected} keys checked)._')
        out.append('')
        return out

    out.append(f'**{len(drift_items)} drift items:**')
    out.append('')
    by_key = defaultdict(list)
    for host, key, exp, actual in drift_items:
        by_key[key].append((host, exp, actual))

    out.append('| Key | Host | Expected | Actual |')
    out.append('|-----|------|----------|--------|')
    for key in sorted(by_key):
        for host, exp, actual in sorted(by_key[key]):
            out.append(f'| `{key}` | {host} | `{exp}` | `{actual}` |')
    out.append('')
    return out


def render_drift_section(title, drift, intro=None):
    """Render a markdown section for one drift computation."""
    out = [f'## {title}']
    if intro:
        out.append(intro)
    out.append('')

    drift_items = []
    ignored_items = []
    for section, key_map in drift.items():
        for key, value_map in key_map.items():
            if len(value_map) > 1:
                qualified_key = f'{section} > {key}'
                if qualified_key in IGNORED_KEYS:
                    ignored_items.append((section, key, value_map))
                else:
                    drift_items.append((section, key, value_map))

    if not drift_items:
        out.append('_No unexpected drift._')
        out.append('')
    else:
        out.append(f'**{len(drift_items)} drift items:**')
        out.append('')
        for section, key, value_map in sorted(drift_items):
            out.append(f'### {section} > `{key}`')
            sorted_values = sorted(value_map.items(), key=lambda x: -len(x[1]))
            out.append('')
            out.append('| Value | Hosts |')
            out.append('|-------|-------|')
            for val, hosts in sorted_values:
                hosts_fmt = ', '.join(hosts)
                out.append(f'| `{val}` | {hosts_fmt} |')
            out.append('')

    total_keys = sum(len(key_map) for key_map in drift.values())
    matching = total_keys - len(drift_items) - len(ignored_items)
    out.append(f'_Matching: {matching} / {total_keys}. Ignored-by-rule: {len(ignored_items)}._')
    out.append('')

    return out, drift_items


def render_report(host_snapshots, errors, include_ignored=False):
    """Render group-aware markdown report.

    Comparing baremetals against the Chicago VPS is mostly noise (different
    topology: no isolcpus, different kernel params, eth0 vs enp1s0f0 etc.).
    So we split drift into:
      1. Baremetals vs each other (high signal)
      2. All hosts together (also shows baremetal-vs-VPS divergence for completeness)
    """
    out = []
    out.append(f'# KTP Fleet Drift Audit — {datetime.now().strftime("%Y-%m-%d %H:%M ET")}')
    out.append('')
    for h in HOSTS:
        out.append(f'- **{h["name"]}** ({h["host"]}) [{h["group"]}]')
    out.append('')

    if errors:
        out.append('## ⚠ Snapshot failures')
        for name, err in errors.items():
            out.append(f'- **{name}**: {err}')
        out.append('')

    # 1. Baremetal-only drift — the high-signal comparison
    baremetals = [h['name'] for h in HOSTS if h['group'] == 'baremetal']
    bm_drift = compute_drift(host_snapshots, baremetals)
    bm_lines, bm_items = render_drift_section(
        f'Baremetal-only drift ({len(baremetals)} hosts)',
        bm_drift,
        intro=f'Comparing baremetals only: {", ".join(baremetals)}. This is the primary signal — baremetals should be tuned identically.'
    )
    out.extend(bm_lines)

    # 2. Fleet-wide drift (baremetals + VPS) — informational, lots of expected VPS differences
    fleet_drift = compute_drift(host_snapshots)
    fleet_lines, fleet_items = render_drift_section(
        'Fleet-wide drift (includes VPS vs baremetal topology differences)',
        fleet_drift,
        intro='Includes Chicago VPS, which has expected topology differences from the baremetals (no isolcpus, different kernel params, eth0 vs enpNsNfN NIC naming, etc). Useful for completeness but most items here are not actionable.'
    )
    out.extend(fleet_lines)

    # 3. Repo-vs-fleet sysctl drift
    host_groups = {h['name']: h['group'] for h in HOSTS}
    expected_sysctls = load_expected_sysctls(EXPECTED_SYSCTLS)
    sysctl_drift = compute_repo_drift(
        host_snapshots, host_groups, expected_sysctls,
        section_name='SYSCTL (KTP-relevant)'
    )
    sysctl_lines = render_repo_drift_section(
        'Repo-vs-fleet sysctl drift',
        'Compares live fleet sysctl values against `provision/expected-sysctls.conf` (declarative source of truth). If the fleet agreed internally but all hosts drifted from the repo, this is the section that catches it.',
        sysctl_drift, expected_sysctls, EXPECTED_SYSCTLS,
    )
    out.extend(sysctl_lines)

    # 4. Repo-vs-fleet binary md5 drift
    #    Section header is port-agnostic; the port each host was sampled at
    #    lives in the `KTP SAMPLE PORT` section (configurable per-host in
    #    the orchestrator, so canary-occupied ports can be skipped).
    expected_binaries = load_expected_sysctls(EXPECTED_BINARIES)
    binary_drift = compute_repo_drift(
        host_snapshots, host_groups, expected_binaries,
        section_name='KTP BINARIES md5'
    )
    binary_lines = render_repo_drift_section(
        'Repo-vs-fleet binary md5 drift',
        'Compares live KTP binary md5s against `provision/expected-binaries.conf`. Each host is sampled at its configured `sample_port` (default 27015, overridable per-host when a canary occupies 27015).',
        binary_drift, expected_binaries, EXPECTED_BINARIES,
    )
    out.extend(binary_lines)

    # 5. Repo-vs-fleet GRUB cmdline drift
    expected_cmdline = load_expected_list(EXPECTED_CMDLINE)
    cmdline_drift = compute_repo_list_drift(
        host_snapshots, host_groups, expected_cmdline,
        section_name='GRUB CMDLINE'
    )
    cmdline_lines = render_repo_drift_section(
        'Repo-vs-fleet GRUB cmdline drift',
        'Compares live `/proc/cmdline` against `provision/expected-cmdline.conf`. Only checks for presence of the expected KTP-relevant flags — per-host flags (BOOT_IMAGE, root=UUID, legacy console tweaks) are ignored. Missing an expected flag means the host is running with different CPU-isolation / c-state / mitigations settings than the repo declares.',
        cmdline_drift, expected_cmdline, EXPECTED_CMDLINE,
    )
    out.extend(cmdline_lines)

    # 6. Repo-vs-fleet systemd timer drift
    expected_timers = load_expected_list(EXPECTED_TIMERS)
    timer_drift = compute_repo_list_drift(
        host_snapshots, host_groups, expected_timers,
        section_name='KTP SYSTEMD TIMERS'
    )
    timer_lines = render_repo_drift_section(
        'Repo-vs-fleet systemd timer drift',
        'Compares live `systemctl list-timers ktp-*` against `provision/expected-timers.conf`. If a host is missing a required KTP timer (e.g. `ktp-chrt.timer`), game-server pinning + SCHED_FIFO may silently stop being reapplied at 5-min intervals.',
        timer_drift, expected_timers, EXPECTED_TIMERS,
    )
    out.extend(timer_lines)

    # 7. Repo-vs-fleet /etc/rc.local drift (glob-pattern presence check)
    expected_rclocal = load_expected_list(EXPECTED_RC_LOCAL)
    rclocal_drift = compute_repo_glob_drift(
        host_snapshots, host_groups, expected_rclocal,
        section_name='/etc/rc.local (non-comment, sorted)'
    )
    rclocal_lines = render_repo_drift_section(
        'Repo-vs-fleet /etc/rc.local drift',
        'Compares live `/etc/rc.local` against `provision/expected-rc-local.conf` using glob patterns (so per-host NIC names and shell-style differences don\'t false-positive). Drift means the host is missing a KTP tuning line (CPU governor, THP, NIC offloads, conntrack NOTRACK, ring buffer, queue discipline, etc.).',
        rclocal_drift, expected_rclocal, EXPECTED_RC_LOCAL,
    )
    out.extend(rclocal_lines)

    repo_drift_by_category = {
        'sysctl': list(sysctl_drift),
        'binary': list(binary_drift),
        'cmdline': list(cmdline_drift),
        'timer': list(timer_drift),
        'rc.local': list(rclocal_drift),
    }
    return '\n'.join(out), bm_items, fleet_items, repo_drift_by_category


def drift_item_key(item, category):
    """Canonical string for a drift tuple (host, key, expected, actual) scoped
    by category (sysctl / binary / cmdline / timer / rc.local). Category prefix
    lets the Discord alert group drift by type for readability.

    State-file format change 2026-04-20: was `host|key|exp|actual`, now
    `category|host|key|exp|actual`. State files predating this change will
    see every drift item as "new" on first post-upgrade run — that's a one-
    time cost, acceptable for the readability win.
    """
    host, key, expected, actual = item
    return f'{category}|{host}|{key}|{expected}|{actual}'


def parse_drift_key(key):
    """Inverse of drift_item_key. Returns (category, host, key, expected, actual)."""
    parts = key.split('|', 4)
    if len(parts) != 5:
        return None
    return tuple(parts)


def load_state(path):
    if not path or not Path(path).exists():
        return set()
    try:
        data = json.loads(Path(path).read_text())
        return set(data.get('repo_drift', []))
    except Exception as e:
        print(f'WARN: could not load state file {path}: {e}', file=sys.stderr)
        return set()


def save_state(path, repo_drift_keys):
    if not path:
        return
    try:
        Path(path).write_text(json.dumps({
            'updated_at': datetime.now().isoformat(timespec='seconds'),
            'repo_drift': sorted(repo_drift_keys),
        }, indent=2))
    except Exception as e:
        print(f'WARN: could not save state file {path}: {e}', file=sys.stderr)


def post_discord(relay_url, auth_secret, channel_id, title, description, color=16753920):
    """Post an embed to the KTP Discord relay. Mirrors send_discord_embed from
    ktp-scheduled-restart.sh. Silent on failure (we don't want a broken relay
    to fail the audit run)."""
    payload = {
        'channelId': channel_id,
        'embeds': [{
            'title': title,
            'description': description[:4000],
            'color': color,
            'footer': {'text': f'ktp-audit @ {datetime.now().strftime("%m/%d/%Y %I:%M %p EST")}'},
        }],
    }
    try:
        req = urllib.request.Request(
            relay_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'X-Relay-Auth': auth_secret,
                'Content-Type': 'application/json',
            },
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        return True
    except Exception as e:
        print(f'WARN: Discord post failed: {e}', file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=str, help='Output path for markdown report (default: stdout)')
    parser.add_argument('--include-ignored', action='store_true',
                        help='Include per-host-expected-to-differ keys in the report')
    parser.add_argument('--state', type=str,
                        help='Path to state file persisting last-run repo-drift set. Enables diff-based alerting.')
    parser.add_argument('--alert-discord', action='store_true',
                        help='If drift changed vs --state file, POST the diff to the KTP Discord relay. '
                             'Uses env vars KTP_RELAY_URL, KTP_RELAY_SECRET, KTP_ALERT_CHANNEL.')
    args = parser.parse_args()

    if not SNAPSHOT_SCRIPT.exists():
        print(f'ERROR: snapshot script not found at {SNAPSHOT_SCRIPT}', file=sys.stderr)
        sys.exit(1)

    print(f'Snapshotting {len(HOSTS)} hosts in parallel...', file=sys.stderr)
    host_snapshots = {}
    errors = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(HOSTS)) as ex:
        futures = {ex.submit(run_snapshot, h): h for h in HOSTS}
        for fut in concurrent.futures.as_completed(futures):
            name, text, err = fut.result()
            if err:
                errors[name] = err
                print(f'  {name}: FAILED ({err})', file=sys.stderr)
            else:
                host_snapshots[name] = parse_snapshot(text)
                print(f'  {name}: OK ({len(text)} chars)', file=sys.stderr)

    if not host_snapshots:
        print('ERROR: no successful snapshots', file=sys.stderr)
        sys.exit(1)

    report, bm_items, fleet_items, repo_by_category = render_report(
        host_snapshots, errors, include_ignored=args.include_ignored
    )

    if args.out:
        Path(args.out).write_text(report, encoding='utf-8')
        print(f'Report: {args.out}', file=sys.stderr)
    else:
        print(report)

    total_repo = sum(len(v) for v in repo_by_category.values())
    print(f'\nBaremetal drift items: {len(bm_items)}', file=sys.stderr)
    print(f'Fleet-wide drift items: {len(fleet_items)}', file=sys.stderr)
    print(f'Repo-vs-fleet drift items: {total_repo}', file=sys.stderr)
    for cat, items in repo_by_category.items():
        print(f'  {cat}: {len(items)}', file=sys.stderr)

    # State-file diff + Discord alert — keys are category-prefixed
    current_keys = set()
    for cat, items in repo_by_category.items():
        for item in items:
            current_keys.add(drift_item_key(item, cat))
    previous_keys = load_state(args.state) if args.state else set()
    new_keys = current_keys - previous_keys
    resolved_keys = previous_keys - current_keys

    if args.state and previous_keys:
        print(f'Repo-drift delta vs last run: +{len(new_keys)} new, -{len(resolved_keys)} resolved',
              file=sys.stderr)

    if args.alert_discord and (new_keys or resolved_keys):
        relay_url = os.environ.get('KTP_RELAY_URL')
        auth_secret = os.environ.get('KTP_RELAY_SECRET')
        channel_id = os.environ.get('KTP_ALERT_CHANNEL')
        if not (relay_url and auth_secret and channel_id):
            print('WARN: --alert-discord set but KTP_RELAY_URL/KTP_RELAY_SECRET/KTP_ALERT_CHANNEL not all in env — skipping',
                  file=sys.stderr)
        else:
            lines = [f'**+{len(new_keys)} new, -{len(resolved_keys)} resolved**', '']

            def render_group(label, keys):
                """Render one new-or-resolved group, nested by category."""
                if not keys:
                    return []
                out = [f'**{label}:**']
                by_cat = defaultdict(list)
                for k in keys:
                    parsed = parse_drift_key(k)
                    if parsed:
                        by_cat[parsed[0]].append(parsed)
                for cat in ('sysctl', 'binary', 'cmdline', 'timer', 'rc.local'):
                    if cat not in by_cat:
                        continue
                    out.append(f'__{cat}__ ({len(by_cat[cat])})')
                    for _, host, key, expected, actual in sorted(by_cat[cat]):
                        # Compact one-line format: host · key · exp → act
                        out.append(f'• `{host}` · `{key}` · `{expected}` → `{actual}`')
                    out.append('')
                return out

            if new_keys:
                lines.extend(render_group('⚠️ New drift', new_keys))
            if resolved_keys:
                lines.extend(render_group('✅ Resolved', resolved_keys))

            # KTP red on new drift, green on pure-resolution
            color = 16711680 if new_keys else 65280
            post_discord(
                relay_url, auth_secret, channel_id,
                title='<:KTP:1002382703020212245> KTP Fleet Drift Δ',
                description='\n'.join(lines),
                color=color,
            )

    if args.state:
        save_state(args.state, current_keys)

    # Exit code: non-zero if either baremetal or repo drift exists (CI-friendly)
    sys.exit(0 if (len(bm_items) == 0 and total_repo == 0) else 2)


if __name__ == '__main__':
    main()
