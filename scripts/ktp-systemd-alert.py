#!/usr/bin/env python3
"""KTP systemd unit-failure alert.

Invoked by `OnFailure=ktp-systemd-alert@%n.service` on critical-path units.
Reads the failed unit's recent journal lines + status, posts a red Discord
embed to #ktp-updates so a service flap is visible immediately rather than
waiting for the periodic ktp-data-server-health.sh sweep.

Companion to ktp-data-server-health.sh:
  - data-server-health: periodic (hourly cadence), state-transition tracking,
    catches services that go down AND stay down across multiple checks.
  - this script: immediate (fires on the failure event itself), captures
    the full journalctl tail at the moment of failure for diagnostic info.

Both can fire for the same incident (cascading failure) — that's a feature,
not a bug; multiple signals confirm the failure shape.

The alert script itself MUST NOT depend on any of the units it monitors.
Only stdlib + /etc/ktp/discord-relay.conf + journalctl + systemctl.

Usage (via systemd template):
  ktp-systemd-alert <unit_name>

Manual test:
  /usr/local/bin/ktp-systemd-alert hltv-restart.service --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone


DEFAULT_ALERT_CHANNEL = "1498813261263405097"  # #ktp-updates


def sh(cmd: str, timeout: int = 15) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout after {timeout}s"


def load_relay_conf(path: str = "/etc/ktp/discord-relay.conf") -> dict[str, str]:
    """Parse bash-sourceable KEY=VALUE conf. Strips surrounding shell quotes
    on values — `RELAY_URL="https://..."` and `RELAY_URL='https://...'` both
    yield `https://...`. Without this, urllib treats `"https` as a literal
    URL scheme and fails with `unknown url type`."""
    conf: dict[str, str] = {}
    if not os.path.exists(path):
        return conf
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                v = v.strip()
                # Strip matching surrounding quotes (single or double).
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                    v = v[1:-1]
                conf[k.strip()] = v
    return conf


def collect_unit_state(unit: str) -> dict:
    """Pull current state + recent journal for the failed unit."""
    state = {}
    _, active, _ = sh(f"systemctl is-active {unit} 2>/dev/null")
    state["is_active"] = active
    _, sub, _ = sh(f"systemctl show {unit} --property=SubState --value 2>/dev/null")
    state["sub_state"] = sub
    _, exec_status, _ = sh(f"systemctl show {unit} --property=ExecMainStatus --value 2>/dev/null")
    state["exec_main_status"] = exec_status
    _, n_restarts, _ = sh(f"systemctl show {unit} --property=NRestarts --value 2>/dev/null")
    state["n_restarts"] = n_restarts
    _, result, _ = sh(f"systemctl show {unit} --property=Result --value 2>/dev/null")
    state["result"] = result
    _, journal_tail, _ = sh(
        f'journalctl -u {unit} --no-pager -n 25 --output=short 2>/dev/null'
    )
    # Strip the per-line journal prefix (timestamp + host + unit) for readability;
    # keep just the message portion.
    lines = []
    for line in journal_tail.splitlines():
        # "May 02 13:45:01 hostname unit[pid]: message"
        parts = line.split(": ", 1)
        if len(parts) == 2:
            ts_host = parts[0].split()
            if len(ts_host) >= 3:
                lines.append(f"{ts_host[0]} {ts_host[1]} {ts_host[2]}: {parts[1]}")
                continue
        lines.append(line)
    state["journal_tail"] = "\n".join(lines[-25:])
    return state


def build_embed(unit: str, state: dict) -> dict:
    hostname = socket.gethostname()
    # Truncate journal for the description (Discord cap is 4096 chars on description)
    journal = state["journal_tail"]
    if len(journal) > 3500:
        journal = "...(truncated)...\n" + journal[-3500:]

    fields = [
        {"name": "Result", "value": f"`{state['result'] or 'unknown'}`", "inline": True},
        {"name": "Sub-state", "value": f"`{state['sub_state'] or 'unknown'}`", "inline": True},
        {"name": "Exit code", "value": f"`{state['exec_main_status'] or '?'}`", "inline": True},
        {"name": "Restarts", "value": f"`{state['n_restarts'] or '?'}`", "inline": True},
        {"name": "is-active", "value": f"`{state['is_active'] or '?'}`", "inline": True},
        {"name": "Host", "value": f"`{hostname}`", "inline": True},
    ]

    return {
        "title": f"🔴 systemd unit failure — {unit}",
        "description": f"```\n{journal}\n```" if journal else "(no journal output captured)",
        "color": 15548997,  # red
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": fields,
        "footer": {"text": f"ktp-systemd-alert · {hostname}"},
    }


def post_to_discord(embed: dict, channel_id: str, relay_url: str, auth_secret: str) -> tuple[bool, str]:
    """POST to Discord via the KTP relay. Same shape as ktp-soak-verify (camelCase channelId)."""
    payload = json.dumps({
        "channelId": channel_id,
        "embeds": [embed],
    }).encode("utf-8")
    req = urllib.request.Request(
        relay_url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Relay-Auth": auth_secret,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return (200 <= resp.status < 300), resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("unit", help="Failed unit name (e.g., hltv-restart.service)")
    ap.add_argument("--channel", default=DEFAULT_ALERT_CHANNEL,
                    help=f"Discord channel ID (default: {DEFAULT_ALERT_CHANNEL} = #ktp-updates)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print embed JSON to stdout instead of POSTing")
    args = ap.parse_args()

    state = collect_unit_state(args.unit)
    embed = build_embed(args.unit, state)

    if args.dry_run:
        print(json.dumps(embed, indent=2))
        return 0

    conf = load_relay_conf()
    relay_url = conf.get("RELAY_URL", "")
    auth_secret = conf.get("AUTH_SECRET", "")
    if not relay_url or not auth_secret:
        print("ERROR: /etc/ktp/discord-relay.conf missing RELAY_URL or AUTH_SECRET", file=sys.stderr)
        return 2

    ok, resp = post_to_discord(embed, args.channel, relay_url, auth_secret)
    if ok:
        print(f"Posted alert for {args.unit}")
        return 0
    else:
        # If the relay POST failed, write a sentinel to /var/log so the next
        # ktp-data-server-health run can flag it. We don't retry here — the
        # alert is best-effort and the periodic health check is the safety net.
        print(f"Discord POST failed for {args.unit}: {resp}", file=sys.stderr)
        try:
            with open("/var/log/ktp-systemd-alert-failed.log", "a") as f:
                f.write(f"{datetime.now(timezone.utc).isoformat()} {args.unit} {resp}\n")
        except Exception:
            pass
        return 3


if __name__ == "__main__":
    sys.exit(main())
