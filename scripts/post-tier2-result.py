#!/usr/bin/env python3
"""post-tier2-result — POST a Tier 2 integration-test result embed to Discord.

Reads a session-summary JSON written by the pytest conftest hook (added in
1.5.22 alongside this script), formats a Discord embed with pass/fail/skip
counts + duration + run URL + recent failures, and POSTs via the relay
configured in /etc/ktp/discord-relay.conf. Intended to run from the
`tier2-integration.yml` workflow's post-pytest step (with `if: always()`).

## Why a separate helper vs inline workflow YAML

The embed-building logic is non-trivial (color ladder + truncation rules +
recent-failures formatting) and benefits from being unit-testable. Inline
Python in workflow YAML would also have to handle relay credential loading,
URL building, error handling — all of which already exist in
`ktp-perf-rollup.py` as patterns to mirror. Putting the script in the same
shape (file-config + relay POST + idempotent in `--dry-run`) keeps the two
post-result patterns consistent.

## CLI

    post-tier2-result --report tier2-report.json
                      [--config /etc/ktp/discord-relay.conf]
                      [--dry-run]
                      [--run-url URL]            # GH Actions $RUN_URL
                      [--branch ref/heads/foo]   # GH Actions $GITHUB_REF
                      [--commit-sha 7-char-sha]  # GH Actions short SHA

## Required config keys (in /etc/ktp/discord-relay.conf or env)

    RELAY_URL                 — Cloud Run discord relay endpoint
    AUTH_SECRET               — relay X-Relay-Auth header value
    TIER2_REPORT_CHANNEL      — Discord channel ID for Tier 2 results
                                (defaults to scheduled-report channel
                                1498813261263405097 — see memory
                                `scheduled_report_channel.md`)

## Exit codes

    0 — embed posted (or --dry-run)
    1 — invalid input (bad JSON, missing required field)
    2 — relay creds missing in steady-state mode (not --dry-run)
    3 — relay returned non-2xx
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

DEFAULT_CONFIG = Path("/etc/ktp/discord-relay.conf")
DEFAULT_REPORT_CHANNEL = "1498813261263405097"  # scheduled-report channel

KTP_GREEN = 5763719
KTP_RED = 15548997
KTP_YELLOW = 16763904
KTP_EMOJI = "<:ktp:1105490705188659272>"


# ──────────────────────────────────────────────────────────────────────────
# Config loading (cribbed from ktp-perf-rollup.py — keeps the two scripts'
# config conventions aligned)
# ──────────────────────────────────────────────────────────────────────────

def load_config(config_path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not config_path.exists():
        logging.warning("config %s not found — relying on env-only", config_path)
        return out
    line_re = re.compile(r'^\s*([A-Z_][A-Z_0-9]*)\s*=\s*(.+?)\s*$')
    for raw in config_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = line_re.match(line)
        if not m:
            continue
        val = m.group(2)
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        out[m.group(1)] = val
    return out


def resolve(env_key: str, file_cfg: dict[str, str], default: Optional[str] = None) -> Optional[str]:
    return os.environ.get(env_key) or file_cfg.get(env_key) or default


# ──────────────────────────────────────────────────────────────────────────
# Embed shape — pure functions, unit-testable in isolation
# ──────────────────────────────────────────────────────────────────────────

def color_for(report: dict) -> int:
    """Color ladder:
        all-pass (failed=0, errors=0)         → green
        partial-skip-only (e.g. env-less mode) → green
        any failure or error                  → red
        unknown shape                         → yellow (catch-all)
    """
    failed = int(report.get("failed", 0))
    errors = int(report.get("errors", 0))
    if failed > 0 or errors > 0:
        return KTP_RED
    if "passed" in report:
        return KTP_GREEN
    return KTP_YELLOW


def title_for(report: dict) -> str:
    p = int(report.get("passed", 0))
    f = int(report.get("failed", 0))
    s = int(report.get("skipped", 0))
    e = int(report.get("errors", 0))
    label = "GREEN" if (f == 0 and e == 0) else "RED"
    parts = [f"{p}p", f"{f}f", f"{s}s"]
    if e:
        parts.append(f"{e}err")
    return f"{KTP_EMOJI}  KTP Tier 2 Integration — {label} ({' / '.join(parts)})"


def description_for(report: dict, run_url: Optional[str], branch: Optional[str],
                    commit_sha: Optional[str]) -> str:
    duration = float(report.get("duration_sec", 0.0))
    total = int(report.get("total", 0))
    parts = [f"**{total}** tests collected, **{duration:.1f}s** runtime."]
    if branch:
        # Strip refs/heads/ prefix per GH Actions convention
        ref = branch.replace("refs/heads/", "").replace("refs/pull/", "PR#")
        if commit_sha:
            parts.append(f"Branch `{ref}` @ `{commit_sha[:7]}`")
        else:
            parts.append(f"Branch `{ref}`")
    if run_url:
        parts.append(f"[Run details]({run_url})")
    return " · ".join(parts)


def failures_field(report: dict, max_lines: int = 5) -> Optional[dict]:
    """Build a Discord embed field listing the first N failed test IDs,
    or None if no failures. Truncates with a sentinel so operators see
    the field was clipped vs a silent mid-line cut.

    Truncation order: hard char-cap applied BEFORE the "…and N more"
    sentinel is added. Earlier ordering (cap-then-add-sentinel) had a
    theoretical hole where 5 long node IDs (>200 chars each, e.g. deeply
    parameterized fixtures) could exceed the 1024 Discord field cap before
    the cap check ran. New order: format the line block, char-cap that,
    THEN append the count sentinel — which itself has a tiny budget."""
    failures = report.get("failures") or []
    errors = report.get("error_tests") or []
    items = list(failures) + list(errors)
    if not items:
        return None
    shown = items[:max_lines]
    extra = len(items) - len(shown)

    # Format + cap the per-line body first. Reserve ~30 chars for the
    # "…and N more" trailer (max realistic: "…and 9999 more" = 14 chars
    # plus the leading "\n" = 15; reserving 30 leaves headroom).
    BODY_BUDGET = 990
    body = "\n".join(f"• `{x}`" for x in shown)
    if len(body) > BODY_BUDGET:
        body = body[:BODY_BUDGET - 4] + "\n…"

    if extra > 0:
        body += f"\n…and {extra} more"

    # Belt-and-suspenders absolute cap (Discord field-value limit is 1024).
    if len(body) > 1020:
        body = body[:1016] + "\n…(truncated)"
    return {
        "name": f"Failed tests ({len(items)})",
        "value": body,
        "inline": False,
    }


def build_embed(report: dict, run_url: Optional[str], branch: Optional[str],
                commit_sha: Optional[str]) -> dict:
    embed = {
        "title": title_for(report),
        "description": description_for(report, run_url, branch, commit_sha),
        "color": color_for(report),
        "fields": [],
    }
    fail_field = failures_field(report)
    if fail_field is not None:
        embed["fields"].append(fail_field)
    embed["footer"] = {
        "text": f"tier2-integration · {report.get('exitstatus', '?')} exit · "
                f"{report.get('rerun', 0)} rerun(s)"
    }
    return embed


# ──────────────────────────────────────────────────────────────────────────
# Relay POST
# ──────────────────────────────────────────────────────────────────────────

def post_embed(relay_url: str, auth_secret: str, channel_id: str, embed: dict) -> tuple[int, str]:
    payload = {"channelId": channel_id, "embeds": [embed]}
    req = urllib.request.Request(
        relay_url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Relay-Auth": auth_secret,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")[:500]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")[:500]


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--report", required=True,
                    help="Path to session-summary JSON written by pytest conftest hook")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--dry-run", action="store_true",
                    help="Build embed + log; do NOT POST. Prints embed JSON to stdout.")
    ap.add_argument("--run-url", default=os.environ.get("KTP_TIER2_RUN_URL"),
                    help="CI run URL (e.g. https://github.com/org/repo/actions/runs/123)")
    ap.add_argument("--branch", default=os.environ.get("KTP_TIER2_BRANCH"),
                    help="Git ref (e.g. refs/heads/main)")
    ap.add_argument("--commit-sha", default=os.environ.get("KTP_TIER2_COMMIT_SHA"),
                    help="Commit short or full SHA")
    args = ap.parse_args()

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    report_path = Path(args.report)
    if not report_path.exists():
        logging.error("report file not found: %s", report_path)
        return 1
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        logging.error("report JSON malformed: %s", e)
        return 1

    embed = build_embed(report, args.run_url, args.branch, args.commit_sha)
    print(json.dumps(embed))

    if args.dry_run:
        logging.info("dry-run — would POST embed (suppressed)")
        return 0

    file_cfg = load_config(Path(args.config))
    relay_url = resolve("RELAY_URL", file_cfg)
    auth_secret = resolve("AUTH_SECRET", file_cfg)
    channel = resolve("TIER2_REPORT_CHANNEL", file_cfg, DEFAULT_REPORT_CHANNEL)

    if not (relay_url and auth_secret and channel):
        logging.error("relay creds missing (RELAY_URL/AUTH_SECRET); not posting")
        return 2

    status, body = post_embed(relay_url, auth_secret, channel, embed)
    if 200 <= status < 300:
        logging.info("relay OK (%d)", status)
        return 0
    logging.error("relay non-2xx: %d body=%s", status, body)
    return 3


if __name__ == "__main__":
    sys.exit(main())
