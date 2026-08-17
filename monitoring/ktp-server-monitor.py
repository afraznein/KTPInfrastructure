#!/usr/bin/env python3
"""KTP Server Monitor — logs game server FPS, players, CPU, RAM, steal.

Queries each HLDS instance via RCON 'stats' command and combines with
system-level metrics. Designed to run every minute via cron.

Log format (TSV):
  timestamp  server  fps  players  sv_cpu  sys_cpu_steal  ram_used_mb  ram_total_mb  load_1m
"""

import socket
import subprocess
import datetime
import os
import sys

# ============================================
# Configuration
# ============================================
SERVERS = [
    (27015, "chi1"),
    (27016, "chi2"),
    (27017, "chi3"),
    (27018, "chi4"),
    (27019, "chi5"),
]

SERVER_IP = "172.238.176.101"
LOG_DIR = "/home/dodserver/log"
LOG_FILE = os.path.join(LOG_DIR, "server-monitor.log")
RCON_TIMEOUT = 3
HEADER = b'\xff\xff\xff\xff'


def _resolve_secret(env_var: str, dotfile: str, label: str) -> str:
    """Env var, then ~ dotfile — never hardcoded. This file is TRACKED in a
    public repo; the deployed copy carried the pre-2026-05-31 rcon password
    inline, so the committed artifact could not authenticate at all."""
    val = os.environ.get(env_var, "")
    if not val:
        p = os.path.expanduser(dotfile)
        if os.path.exists(p):
            val = open(p).read().strip()
    if not val:
        sys.exit(f"{label} not configured — set ${env_var} or write it to {dotfile}")
    return val


# Fail at import, not per-query: rcon_stats() swallows every exception into
# "DOWN", which is exactly how a stale credential hid for ten weeks.
RCON_PASSWORD = _resolve_secret("KTP_RCON_PASSWORD", "~/.ktp_rcon_password", "rcon password")


def rcon_stats(port):
    """Query HLDS 'stats' via RCON. Returns (fps, players, sv_cpu) or Nones."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(RCON_TIMEOUT)
    try:
        # GoldSrc challenge RCON: get challenge first
        sock.sendto(HEADER + b'challenge rcon\n', (SERVER_IP, port))
        data = sock.recv(4096)
        resp = data[4:].decode('utf-8', errors='replace').replace('\x00', '').strip()
        challenge = resp.split()[-1] if 'challenge' in resp.lower() else None

        if challenge:
            rcon_cmd = f'rcon {challenge} {RCON_PASSWORD} stats\n'.encode('ascii')
        else:
            rcon_cmd = f'rcon {RCON_PASSWORD} stats\n'.encode('ascii')

        sock.sendto(HEADER + rcon_cmd, (SERVER_IP, port))
        data = sock.recv(4096)
        response = data[5:].decode('utf-8', errors='replace').replace('\x00', '').strip()

        return parse_stats(response)
    except Exception:
        return None, None, None
    finally:
        sock.close()


def parse_stats(response):
    """Parse HLDS 'stats' output.

    Format:
    CPU   In    Out   Uptime  Users   FPS    Players
    0.00  0.00  0.00  3       0       999.97 0
    """
    for line in response.split('\n'):
        parts = line.split()
        if len(parts) >= 7:
            try:
                sv_cpu = float(parts[0])
                fps = float(parts[5])
                players = int(parts[6])
                return fps, players, sv_cpu
            except (ValueError, IndexError):
                continue
    return None, None, None


def get_system_stats():
    """Get CPU steal%, RAM used/total MB, load average."""
    # CPU steal from /proc/stat (cumulative, but we snapshot for simplicity)
    # Use vmstat 1 2 for a 1-second sample
    try:
        result = subprocess.run(
            ['vmstat', '1', '2'],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().split('\n')
        if len(lines) >= 3:
            vals = lines[2].split()
            # vmstat columns: r b swpd free buff cache si so bi bo in cs us sy id wa st gu
            # steal is index 16 (st), or -2 if 'gu' column present
            steal = vals[16] if len(vals) > 16 else "0"
        else:
            steal = "?"
    except Exception:
        steal = "?"

    # RAM from /proc/meminfo
    try:
        with open('/proc/meminfo', 'r') as f:
            meminfo = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    meminfo[parts[0].rstrip(':')] = int(parts[1])
        total_mb = meminfo.get('MemTotal', 0) // 1024
        avail_mb = meminfo.get('MemAvailable', 0) // 1024
        used_mb = total_mb - avail_mb
    except Exception:
        total_mb = used_mb = 0

    # Load average
    try:
        load_1m = os.getloadavg()[0]
    except Exception:
        load_1m = 0.0

    return steal, used_mb, total_mb, load_1m


def main():
    os.makedirs(LOG_DIR, exist_ok=True)

    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    steal, ram_used, ram_total, load_1m = get_system_stats()

    # Write header if log file is new/empty
    write_header = not os.path.exists(LOG_FILE) or os.path.getsize(LOG_FILE) == 0

    lines = []
    for port, name in SERVERS:
        fps, players, sv_cpu = rcon_stats(port)
        fps_str = f"{fps:.1f}" if fps is not None else "DOWN"
        players_str = str(players) if players is not None else "-"
        sv_cpu_str = f"{sv_cpu:.1f}" if sv_cpu is not None else "-"

        lines.append(
            f"{now}\t{name}\t{fps_str}\t{players_str}\t{sv_cpu_str}\t"
            f"{steal}\t{ram_used}\t{ram_total}\t{load_1m:.2f}"
        )

    with open(LOG_FILE, 'a') as f:
        if write_header:
            f.write("timestamp\tserver\tfps\tplayers\tsv_cpu\tsteal%\tram_used_mb\tram_total_mb\tload_1m\n")
        for line in lines:
            f.write(line + '\n')


if __name__ == '__main__':
    main()
