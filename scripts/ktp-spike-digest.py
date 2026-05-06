#!/usr/bin/env python3
"""ktp-spike-digest — daily summary of [KTP_SPIKE] umbrella signatures.

Tier 3 Project 3 phase 3 (the alert hook in aggregator is phase 2 — see
KTPProfileAggregator/aggregator.py:post_new_fingerprint_alerts). The
hook fires inline on never-seen fingerprints (high-signal, immediate);
this digest fires daily to roll up steady-state activity that the hook
deliberately doesn't touch (already-known fingerprints).

## What the embed shows

  - **Top fingerprints by daily count** — top 5 most-frequent fingerprints
    in the last 24h. Operators see at-a-glance which spike categories
    are dominating yesterday's noise.
  - **New fingerprints first seen yesterday** — fingerprints whose
    first_seen timestamp lands inside yesterday's window. Cross-checks
    the alert hook (any fingerprint listed here SHOULD have already
    fired an alert in #ktp-crashes; if not, posted_alert was suppressed
    or a relay glitch lost the alert).
  - **Daily totals by phase** — read/phys/steam/send/post/misc1
    occurrence counts across all fingerprints. Operators see the phase
    distribution shifting over time (e.g., a STEAM regression bump).

## CLI

    ktp-spike-digest [--day YYYY-MM-DD]   default: yesterday (server-local)
                     [--dry-run]          compute + log + print embed JSON; do NOT POST
                     [--config /etc/ktp/discord-relay.conf]

## Channel

Default `1497957091107668070` (#ktp-crashes — same as PERF_ALERT_CHANNEL
+ aggregator's SPIKE_ALERT_CHANNEL). Override via SPIKE_DIGEST_CHANNEL
in /etc/ktp/discord-relay.conf if a dedicated channel is preferred.

## Cron

Fires daily at 05:00 ET (after perf-rollup at 04:30 ET, so digest sees
yesterday's complete data). See cron.d/ktp-spike-digest-daily.
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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pymysql
from pymysql.cursors import DictCursor

DEFAULT_CONFIG = Path("/etc/ktp/discord-relay.conf")
DEFAULT_DIGEST_CHANNEL = "1497957091107668070"  # #ktp-crashes

KTP_GREEN = 5763719
KTP_YELLOW = 16763904
KTP_RED = 15548997
KTP_EMOJI = "<:ktp:1105490705188659272>"

TOP_FINGERPRINTS_LIMIT = 5
NEW_FINGERPRINTS_LIMIT = 10


# ──────────────────────────────────────────────────────────────────────────
# Config loading (same convention as ktp-perf-rollup + post-tier2-result)
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
# Database queries
# ──────────────────────────────────────────────────────────────────────────

def open_mysql(password: str) -> pymysql.connections.Connection:
    # TZ note: MySQL session inherits `time_zone = SYSTEM` from the data
    # server (TZ=America/New_York per CLAUDE.md). pymysql does NOT override
    # session TZ, so naive ET datetimes passed as query params compare
    # correctly against TIMESTAMP columns. Verified live 2026-05-06 — a
    # full-day count for "2026-05-06" returned 11 rows whether queried via
    # `mysql` CLI or pymysql with naive datetime(2026,5,6) params, and the
    # earliest captured fingerprint at 11:45 EDT was correctly inside the
    # window. Don't add `SET time_zone = 'America/New_York'` defensively —
    # would mask any future drift to an OS-side UTC convention.
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "localhost"),
        user=os.environ.get("MYSQL_USER", "ktp_telemetry"),
        password=password,
        database=os.environ.get("MYSQL_DB", "hlstatsx"),
        charset="utf8mb4",
        autocommit=True,
        cursorclass=DictCursor,
    )


def fetch_top_fingerprints(cnx, day: date, limit: int) -> list[dict]:
    """Top fingerprints by occurrence count over the target day window.

    `count` in ktp_spike_signatures is an all-time tally — to get a
    DAILY count we'd need a separate per-day rollup. For the v1 digest,
    we approximate with "fingerprints whose last_seen falls in the
    target day, ordered by total count" — biases toward chronically-
    active patterns rather than one-off spikes. Good enough for daily
    "what's noisy lately" — not a precision metric.
    """
    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)
    with cnx.cursor() as cur:
        cur.execute(
            """SELECT fingerprint, phase, magnitude_bucket, count,
                      sample_endpoint, first_seen, last_seen
               FROM ktp_spike_signatures
               WHERE last_seen >= %s AND last_seen < %s
               ORDER BY count DESC
               LIMIT %s""",
            (start, end, limit),
        )
        return list(cur.fetchall())


def fetch_new_fingerprints(cnx, day: date, limit: int) -> list[dict]:
    """Fingerprints first_seen inside the target day window — i.e.,
    never-before-seen patterns that surfaced yesterday. Cross-checks
    the per-fingerprint alert hook in the aggregator."""
    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)
    with cnx.cursor() as cur:
        cur.execute(
            """SELECT fingerprint, phase, magnitude_bucket, count,
                      sample_endpoint, posted_alert
               FROM ktp_spike_signatures
               WHERE first_seen >= %s AND first_seen < %s
               ORDER BY first_seen ASC
               LIMIT %s""",
            (start, end, limit),
        )
        return list(cur.fetchall())


def fetch_phase_totals(cnx, day: date) -> dict[str, int]:
    """Sum of `count` per phase for fingerprints active during the day.
    Same window basis as fetch_top_fingerprints."""
    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)
    with cnx.cursor() as cur:
        cur.execute(
            """SELECT phase, SUM(count) AS total
               FROM ktp_spike_signatures
               WHERE last_seen >= %s AND last_seen < %s
               GROUP BY phase
               ORDER BY total DESC""",
            (start, end),
        )
        return {row["phase"]: int(row["total"]) for row in cur.fetchall()}


# ──────────────────────────────────────────────────────────────────────────
# Embed construction
# ──────────────────────────────────────────────────────────────────────────

def build_embed(day: date, top: list[dict], new: list[dict],
                phase_totals: dict[str, int]) -> Optional[dict]:
    """Daily digest embed. Returns None if there's nothing to report
    (empty fleet day — daemon down, or genuinely zero spikes)."""
    if not top and not new and not phase_totals:
        return None

    # Color: yellow if any new fingerprints today (heads-up), green if
    # only steady-state activity, red if a known fingerprint count
    # exploded (heuristic: any fingerprint count > 1000 in one day —
    # adjust threshold once we have a feel for steady-state magnitudes).
    color = KTP_GREEN
    if new:
        color = KTP_YELLOW
    if any(row["count"] > 1000 for row in top):
        color = KTP_RED

    fields = []

    if top:
        lines = []
        for row in top:
            lines.append(
                f"`{row['fingerprint']:25s}` count **{row['count']:>5d}** "
                f"(sample: {row['sample_endpoint']})"
            )
        fields.append({
            "name": f"Top {len(top)} fingerprints (by all-time count, last_seen yesterday)",
            "value": "\n".join(lines),
            "inline": False,
        })

    if new:
        lines = []
        for row in new:
            posted_marker = "" if row["posted_alert"] else "  ⚠️ alert NOT posted"
            lines.append(
                f"`{row['fingerprint']:25s}` count **{row['count']:>5d}** "
                f"on {row['sample_endpoint']}{posted_marker}"
            )
        body = "\n".join(lines)
        if len(body) > 1020:
            body = body[:1016] + "\n…(truncated)"
        fields.append({
            "name": f"New fingerprints first seen yesterday ({len(new)})",
            "value": body,
            "inline": False,
        })

    if phase_totals:
        order = ["READ", "PHYS", "STEAM", "SEND", "POST", "MISC1"]
        # Show in canonical order so operators always read the same layout
        rows = []
        for phase in order:
            if phase in phase_totals:
                rows.append(f"`{phase:6s}`  {phase_totals[phase]:>6d}")
        # Any phases not in the canonical order (defensive — engine could add
        # a new phase someday) get appended at the end
        for phase, n in phase_totals.items():
            if phase not in order:
                rows.append(f"`{phase:6s}`  {n:>6d}")
        fields.append({
            "name": "Daily totals by phase",
            "value": "\n".join(rows),
            "inline": False,
        })

    return {
        "title": f"{KTP_EMOJI}  KTP Spike Digest — {day.isoformat()}",
        "description": (
            f"Daily summary of `[KTP_SPIKE]` umbrella-line signatures. "
            f"`{len(top)}` top fingerprints, `{len(new)}` new fingerprints, "
            f"`{sum(phase_totals.values())}` total spike occurrences across "
            f"`{len(phase_totals)}` phases."
        ),
        "color": color,
        "fields": fields,
        "footer": {
            "text": f"ktp-spike-digest · {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        },
    }


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
    ap.add_argument("--day", help="YYYY-MM-DD; default = yesterday (server-local)")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute + log + print embed JSON; do NOT POST")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = ap.parse_args()

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    file_cfg = load_config(Path(args.config))
    relay_url = resolve("RELAY_URL", file_cfg)
    auth_secret = resolve("AUTH_SECRET", file_cfg)
    channel = resolve("SPIKE_DIGEST_CHANNEL", file_cfg, DEFAULT_DIGEST_CHANNEL)
    mysql_password = resolve("MYSQL_PASSWORD", file_cfg)

    if not mysql_password:
        logging.error("MYSQL_PASSWORD missing (env or %s)", args.config)
        return 2

    if args.day:
        target_day = date.fromisoformat(args.day)
    else:
        target_day = date.today() - timedelta(days=1)

    cnx = open_mysql(mysql_password)
    try:
        top = fetch_top_fingerprints(cnx, target_day, TOP_FINGERPRINTS_LIMIT)
        new = fetch_new_fingerprints(cnx, target_day, NEW_FINGERPRINTS_LIMIT)
        phase_totals = fetch_phase_totals(cnx, target_day)
        logging.info(
            "target_day=%s top=%d new=%d phases=%s total_count=%d",
            target_day, len(top), len(new), list(phase_totals.keys()),
            sum(phase_totals.values()),
        )
    finally:
        cnx.close()

    embed = build_embed(target_day, top, new, phase_totals)
    if embed is None:
        logging.info("no signature activity for %s — skipping post", target_day)
        return 0

    print(json.dumps(embed))
    if args.dry_run:
        logging.info("dry-run — would POST embed (suppressed)")
        return 0

    if not (relay_url and auth_secret and channel):
        logging.error("relay creds missing (RELAY_URL/AUTH_SECRET/channel); not posting")
        return 2

    status, body = post_embed(relay_url, auth_secret, channel, embed)
    if 200 <= status < 300:
        logging.info("relay OK (%d)", status)
        return 0
    logging.error("relay non-2xx: %d body=%s", status, body)
    return 3


if __name__ == "__main__":
    sys.exit(main())
