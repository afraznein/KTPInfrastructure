#!/usr/bin/env python3
"""KTP scheduled-verification framework.

A reusable harness for cron-driven status checks that post to Discord ONLY
when something needs operator attention. Add new verification suites by
defining a list of `Check` callables in a function and wiring it up via
the `--suite` CLI argument.

Conventions inherited from existing KTP cron scripts:
  - /etc/ktp/discord-relay.conf provides RELAY_URL + AUTH_SECRET
  - Default alert channel = scheduled-report channel (1498813261263405097)
  - State files (when needed) live in /var/lib/ktp-soak-verify/
  - Logs go to /var/log/ktp-soak-verify-<suite>.log

Aggregation rules:
  - Any RED       → red embed, post
  - Any YELLOW    → orange embed, post (unless --quiet-yellow)
  - All GREEN/SKIP → silent exit (--always-post overrides for testing)

Usage:
  ktp-soak-verify --suite post-matchday
  ktp-soak-verify --suite post-matchday --dry-run    # print embed, don't POST
  ktp-soak-verify --suite post-matchday --always-post # green also posts
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable, List, Optional


# ──────────────────────────────────────────────────────────────────────────
# Status + Check primitives
# ──────────────────────────────────────────────────────────────────────────

class Status:
    GREEN  = "green"
    YELLOW = "yellow"
    RED    = "red"
    SKIP   = "skip"


@dataclass
class CheckResult:
    name: str
    status: str  # Status.*
    summary: str  # short one-line for the embed field
    detail: Optional[str] = None  # longer text, included in detail block


@dataclass
class SuiteResult:
    suite: str
    checks: List[CheckResult] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def overall(self) -> str:
        if any(c.status == Status.RED for c in self.checks):
            return Status.RED
        if any(c.status == Status.YELLOW for c in self.checks):
            return Status.YELLOW
        return Status.GREEN


def sh(cmd: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run a shell command; return (returncode, stdout, stderr)."""
    try:
        p = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout after {timeout}s"


# ──────────────────────────────────────────────────────────────────────────
# Discord posting
# ──────────────────────────────────────────────────────────────────────────

DEFAULT_ALERT_CHANNEL = "1498813261263405097"  # scheduled-report

# KTP embed color palette (matches KTPMatchHandler conventions)
COLORS = {
    Status.GREEN:  5763719,   # #57F287
    Status.YELLOW: 15844367,  # #F1C40F
    Status.RED:    15548997,  # #ED4245
}


def load_relay_conf(path: str = "/etc/ktp/discord-relay.conf") -> dict[str, str]:
    """Parse the simple KEY=VALUE lines used by existing KTP scripts."""
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
                conf[k.strip()] = v.strip()
    return conf


def build_embed(suite: SuiteResult) -> dict:
    """Render a SuiteResult as a Discord embed payload."""
    color = COLORS.get(suite.overall, COLORS[Status.GREEN])
    emoji = {Status.GREEN: "✅", Status.YELLOW: "⚠", Status.RED: "🔴", Status.SKIP: "⏭"}

    title_status = {
        Status.RED:    "FAIL",
        Status.YELLOW: "WARN",
        Status.GREEN:  "OK",
    }[suite.overall]

    fields = []
    for c in suite.checks:
        glyph = emoji.get(c.status, "❓")
        fields.append({
            "name": f"{glyph} {c.name}",
            "value": c.summary[:1024],
            "inline": False,
        })

    embed = {
        "title": f"KTP soak verify — {suite.suite} — {title_status}",
        "color": color,
        "timestamp": suite.started_at.isoformat(),
        "footer": {"text": f"ktp-soak-verify · {suite.overall.upper()}"},
        "fields": fields[:25],  # Discord cap
    }

    # Concatenate all "detail" fields into the description if any exist.
    detail_lines = [f"**{c.name}**\n{c.detail}" for c in suite.checks if c.detail]
    if detail_lines:
        desc = "\n\n".join(detail_lines)
        embed["description"] = desc[:4000]  # Discord cap

    return embed


def post_to_discord(embed: dict, channel_id: str, relay_url: str, auth_secret: str) -> tuple[bool, str]:
    """POST a Discord embed via the KTP relay. Returns (success, response_text).

    Relay expects camelCase `channelId` field, NOT snake_case. Source-of-truth
    is /usr/local/bin/ktp-report-core's `post_to_discord` on game hosts. See
    memory `scheduled_report_channel.md` for the canonical POST shape.
    """
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
        with urllib.request.urlopen(req, timeout=15) as resp:
            return (200 <= resp.status < 300), resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ──────────────────────────────────────────────────────────────────────────
# Suite: post-matchday
# ──────────────────────────────────────────────────────────────────────────

def suite_post_matchday() -> SuiteResult:
    """Verify HLTV F+A architecture is healthy after Sunday matchday.

    Runs Monday morning. Sunday matchday window is "Sunday 12:00 ET" through
    "Monday 00:00 ET" (rough envelope; actual matches typically 19:00-23:00).
    """
    result = SuiteResult(suite="post-matchday")

    # The "since" anchor is Sunday 12:00 ET (16:00 UTC) of the most recent
    # Sunday before now. Computed dynamically so the script works whether
    # it fires Monday morning OR is run manually mid-week.
    now = datetime.now(timezone.utc)
    days_back = (now.weekday() - 6) % 7  # 0 if today IS Sunday, else days since Sunday
    if days_back == 0 and now.hour < 16:  # Sunday before noon ET → use last Sunday
        days_back = 7
    sunday = (now - timedelta(days=days_back)).replace(hour=16, minute=0, second=0, microsecond=0)
    since_iso_local = (sunday - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S")  # journalctl wants local
    since_label = sunday.strftime("%Y-%m-%d 12:00 ET")

    # ── 1. Renamer service ──
    rc, out, _ = sh("systemctl is-active hltv-demo-renamer 2>/dev/null")
    result.checks.append(CheckResult(
        name="Renamer service active",
        status=Status.GREEN if out == "active" else Status.RED,
        summary=f"systemctl is-active = `{out}`",
    ))

    # ── 2. state.json open_windows ──
    state_path = "/var/lib/hltv-demo-renamer/state.json"
    try:
        with open(state_path) as f:
            state = json.load(f)
        ow = len(state.get("open_windows", []))
        lo = len(state.get("log_offsets", {}))
        if ow == 0 and lo > 0:
            result.checks.append(CheckResult(
                name="No abandoned windows",
                status=Status.GREEN,
                summary=f"open_windows=0 · log_offsets={lo}",
            ))
        elif ow > 0:
            result.checks.append(CheckResult(
                name="No abandoned windows",
                status=Status.YELLOW,
                summary=f"⚠ {ow} abandoned windows · log_offsets={lo}",
                detail=json.dumps(state.get("open_windows", [])[:5], indent=2),
            ))
        else:
            result.checks.append(CheckResult(
                name="No abandoned windows",
                status=Status.YELLOW,
                summary=f"log_offsets=0 — renamer not tracking any HLTV logs",
            ))
    except Exception as e:
        result.checks.append(CheckResult(
            name="No abandoned windows",
            status=Status.RED,
            summary=f"failed to read state.json: {e}",
        ))

    # ── 3. Renames since Sunday matchday ──
    rc, out, _ = sh(
        f'journalctl -u hltv-demo-renamer --since "{since_iso_local}" --no-pager 2>&1 | grep "Renamed:" | wc -l'
    )
    rename_count = int(out) if out.isdigit() else 0
    if rename_count > 0:
        # Get a sample of canonical names to verify single-friendly format
        _, sample, _ = sh(
            f'journalctl -u hltv-demo-renamer --since "{since_iso_local}" --no-pager 2>&1 | grep "Renamed:" | tail -3'
        )
        result.checks.append(CheckResult(
            name=f"Renames since {since_label}",
            status=Status.GREEN,
            summary=f"{rename_count} successful renames",
            detail=sample[:1000] if sample else None,
        ))
    else:
        # Zero renames could mean: (a) no matches played Sunday (unusual but possible),
        # (b) renamer is broken. Differentiate by checking whether any auto-* files
        # were created during the window.
        rc, n_auto, _ = sh(
            f"find /home/hltvserver/hlds/dod -maxdepth 1 -name 'auto_*.dem' -newermt '{sunday.strftime('%Y-%m-%d %H:%M:%S')}' 2>/dev/null | wc -l"
        )
        n_auto = int(n_auto) if n_auto.isdigit() else 0
        if n_auto == 0:
            result.checks.append(CheckResult(
                name=f"Renames since {since_label}",
                status=Status.YELLOW,
                summary=f"0 renames AND 0 new auto-*.dem since Sunday — unusual; was matchday cancelled?",
            ))
        else:
            result.checks.append(CheckResult(
                name=f"Renames since {since_label}",
                status=Status.RED,
                summary=f"⚠ {n_auto} auto-*.dem produced but 0 renamed — renamer not seeing match windows",
            ))

    # ── 4. "no matching auto-*" warnings since Sunday ──
    rc, out, _ = sh(
        f'journalctl -u hltv-demo-renamer --since "{since_iso_local}" --no-pager 2>&1 | grep "no matching auto-\\*" | wc -l'
    )
    no_match_count = int(out) if out.isdigit() else 0
    if no_match_count == 0:
        result.checks.append(CheckResult(
            name="Recording-loss warnings",
            status=Status.GREEN,
            summary=f"0 'no matching auto-*' warnings since {since_label}",
        ))
    else:
        _, detail, _ = sh(
            f'journalctl -u hltv-demo-renamer --since "{since_iso_local}" --no-pager 2>&1 | grep "no matching auto-\\*" | head -10'
        )
        result.checks.append(CheckResult(
            name="Recording-loss warnings",
            status=Status.YELLOW,
            summary=f"⚠ {no_match_count} 'no matching auto-*' warnings — possible h2 recording loss; investigate per match_id+port",
            detail=detail[:1500] if detail else None,
        ))

    # ── 5. Errors / exceptions ──
    rc, out, _ = sh(
        f'journalctl -u hltv-demo-renamer --since "{since_iso_local}" --no-pager 2>&1 | grep -iE "error|fail|exception|traceback" | wc -l'
    )
    err_count = int(out) if out.isdigit() else 0
    if err_count == 0:
        result.checks.append(CheckResult(
            name="No errors in journal",
            status=Status.GREEN,
            summary=f"0 error/fail/exception/traceback lines",
        ))
    else:
        _, detail, _ = sh(
            f'journalctl -u hltv-demo-renamer --since "{since_iso_local}" --no-pager 2>&1 | grep -iE "error|fail|exception|traceback" | head -10'
        )
        result.checks.append(CheckResult(
            name="No errors in journal",
            status=Status.RED,
            summary=f"🔴 {err_count} error lines",
            detail=detail[:1500] if detail else None,
        ))

    # ── 6. Portal populated since Sunday ──
    rc, out, _ = sh(
        f'find /home/hltvserver/hlds/dod/demos -name "*.dem" -newermt "{sunday.strftime("%Y-%m-%d %H:%M:%S")}" 2>/dev/null | wc -l'
    )
    portal_count = int(out) if out.isdigit() else 0
    if portal_count > 0:
        result.checks.append(CheckResult(
            name=f"Portal populated since {since_label}",
            status=Status.GREEN,
            summary=f"{portal_count} new .dem files in /demos/",
        ))
    elif rename_count == 0:
        # Consistent with a no-matchday-played weekend — skip rather than alarm
        result.checks.append(CheckResult(
            name=f"Portal populated since {since_label}",
            status=Status.SKIP,
            summary=f"0 new demos (matches the 0-renames signal — likely no matchday)",
        ))
    else:
        result.checks.append(CheckResult(
            name=f"Portal populated since {since_label}",
            status=Status.YELLOW,
            summary=f"⚠ {rename_count} renames but 0 new portal demos — organizer may have failed",
        ))

    # ── 7. Double-friendly sanity check (regression guard for the 1.5.11 fix) ──
    rc, out, _ = sh(
        r'find /home/hltvserver/hlds/dod/demos -name "*.dem" -mmin -2880 2>/dev/null | xargs -I{} basename {} 2>/dev/null | grep -E "\-([A-Z]+[0-9]+)-\1" | wc -l'
    )
    dbl_friendly = int(out) if out.isdigit() else 0
    if dbl_friendly == 0:
        result.checks.append(CheckResult(
            name="No double-friendly demos (1.5.11 regression check)",
            status=Status.GREEN,
            summary="0 demos with `-HOST-HOST` pattern in last 48h",
        ))
    else:
        _, detail, _ = sh(
            r'find /home/hltvserver/hlds/dod/demos -name "*.dem" -mmin -2880 2>/dev/null | xargs -I{} basename {} 2>/dev/null | grep -E "\-([A-Z]+[0-9]+)-\1" | head -5'
        )
        result.checks.append(CheckResult(
            name="No double-friendly demos (1.5.11 regression check)",
            status=Status.RED,
            summary=f"🔴 {dbl_friendly} double-friendly demos in last 48h — KTPInfrastructure 1.5.11 fix regressed",
            detail=detail[:1500] if detail else None,
        ))

    # ── 8. Organizer cron last run ──
    rc, out, _ = sh("tail -3 /var/log/ktp-demo-organize.log 2>/dev/null | grep -E 'Moved|Errors' | tail -1")
    if "Errors: 0" in out:
        result.checks.append(CheckResult(
            name="Organizer cron",
            status=Status.GREEN,
            summary=out[:200],
        ))
    elif "Errors:" in out:
        result.checks.append(CheckResult(
            name="Organizer cron",
            status=Status.YELLOW,
            summary=out[:200],
        ))
    else:
        result.checks.append(CheckResult(
            name="Organizer cron",
            status=Status.YELLOW,
            summary=f"unexpected log shape: {out[:200]}",
        ))

    # ── 9. HLTV restart timer last run ──
    # The timer fires twice daily (03:00 + 11:00 ET) and logs to systemd
    # journal, not a flat file. We want to confirm the most recent fire
    # produced a "restart complete" line and didn't error out.
    rc, completion, _ = sh(
        f'journalctl -u hltv-restart --since "{since_iso_local}" --no-pager 2>/dev/null '
        '| grep -iE "scheduled restart complete|restart complete" | tail -1'
    )
    rc, errors, _ = sh(
        f'journalctl -u hltv-restart --since "{since_iso_local}" --no-pager 2>/dev/null '
        '| grep -iE "error|failed|fatal" | wc -l'
    )
    err_count_restart = int(errors) if errors.isdigit() else 0
    if completion and err_count_restart == 0:
        # Strip systemd journal prefix (date/host/unit) for readability
        m = re.search(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[^]]*)\]\s*(.*)', completion)
        if m:
            line = f"{m.group(1)} — {m.group(2)}"
        else:
            line = completion[-200:]
        result.checks.append(CheckResult(
            name="HLTV restart timer",
            status=Status.GREEN,
            summary=line[:200],
        ))
    elif completion and err_count_restart > 0:
        result.checks.append(CheckResult(
            name="HLTV restart timer",
            status=Status.YELLOW,
            summary=f"⚠ completion seen but {err_count_restart} error/fail line(s) in journal",
            detail=completion[-500:] if completion else None,
        ))
    else:
        result.checks.append(CheckResult(
            name="HLTV restart timer",
            status=Status.YELLOW,
            summary=f"no 'restart complete' line in journal since {since_label}",
        ))

    # ── 10. KTPAntiCheat 0.4.x adoption ──
    rc, out, err = sh(
        "mysql hlstatsx -B -N -e \""
        "SELECT DATE(created_at), COUNT(DISTINCT steam_id) "
        "FROM ktp_ac_sessions WHERE created_at >= '2026-05-01' "
        "GROUP BY DATE(created_at) ORDER BY DATE(created_at);\" 2>/dev/null"
    )
    if rc == 0 and out:
        lines = out.strip().splitlines()
        summary = f"{len(lines)} day(s): " + ", ".join(
            l.replace("\t", "=") for l in lines
        )
        result.checks.append(CheckResult(
            name="0.4.x adoption (distinct steam_ids/day)",
            status=Status.GREEN,
            summary=summary[:500],
        ))
    else:
        result.checks.append(CheckResult(
            name="0.4.x adoption (distinct steam_ids/day)",
            status=Status.YELLOW,
            summary=f"mysql query failed: {err[:200] if err else 'no output'}",
        ))

    return result


# ──────────────────────────────────────────────────────────────────────────
# Suite registry — add new suites here
# ──────────────────────────────────────────────────────────────────────────

SUITES: dict[str, Callable[[], SuiteResult]] = {
    "post-matchday": suite_post_matchday,
}


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--suite", required=True, choices=list(SUITES.keys()))
    ap.add_argument("--channel", default=DEFAULT_ALERT_CHANNEL,
                    help=f"Discord channel ID (default: {DEFAULT_ALERT_CHANNEL})")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the embed JSON to stdout instead of POSTing")
    ap.add_argument("--always-post", action="store_true",
                    help="Post even if all checks are GREEN (default: silent on GREEN)")
    ap.add_argument("--quiet-yellow", action="store_true",
                    help="Don't post on YELLOW (only RED triggers a post)")
    args = ap.parse_args()

    suite_fn = SUITES[args.suite]
    result = suite_fn()

    # Always print human summary to stdout (cron captures to log)
    print(f"=== Suite: {result.suite} — {result.overall.upper()} ===")
    for c in result.checks:
        print(f"  [{c.status.upper():<6}] {c.name}: {c.summary}")
    print()

    # Decide whether to post
    should_post = (
        result.overall == Status.RED
        or (result.overall == Status.YELLOW and not args.quiet_yellow)
        or args.always_post
    )

    if not should_post:
        print(f"All checks {result.overall.upper()} — no Discord post needed (use --always-post to override).")
        return 0

    embed = build_embed(result)

    if args.dry_run:
        print("=== Embed (dry-run, would POST) ===")
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
        print(f"Posted to Discord ({result.overall.upper()}).")
        return 0
    else:
        print(f"Discord POST failed: {resp}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
