#!/usr/bin/env python3
"""ktp-spike-digest — daily summary of [KTP_SPIKE] umbrella signatures.

Tier 3 Project 3 phase 3 (the alert hook in aggregator is phase 2 — see
KTPProfileAggregator/aggregator.py:post_new_fingerprint_alerts). The
hook fires inline on never-seen fingerprints (high-signal, immediate);
this digest fires daily to roll up steady-state activity that the hook
deliberately doesn't touch (already-known fingerprints).

## Data model (1.5.31 rewrite)

Reads REAL per-day counts from `ktp_spike_daily` (populated by the
aggregator per cycle, keyed day + fingerprint + server_endpoint). The v1
digest read the cumulative `ktp_spike_signatures.count` and filtered on
`last_seen` inside the target day — which mislabeled all-time counts as
daily AND systematically hid the busiest fingerprints (their last_seen
had already advanced past the target day by digest time).

A spike = one server frame that blew past the engine's spike threshold
(~3ms; frame budget at 1000fps is 1ms). The fingerprint names the
dominant cost inside the slow frame and the frame's total duration:
READ = inbound net, PHYS = game sim, STEAM = Steam API, SEND = outbound
net, POST/MISC1 = end-of-frame/other.

## What the embed shows

  - **Spikes ≥10ms** — yesterday's count per fingerprint vs its
    trailing-7-day average, with the worst-hit instance. This is the
    player-relevant tier; sub-10ms frames are imperceptible.
  - **New fingerprints first seen yesterday** — cross-checks the
    aggregator alert hook (each SHOULD already have alerted in
    #ktp-crashes; ⚠️ marks any that didn't).
  - **Noise floor (<10ms)** — one-line total so volume drift is visible
    without burying the signal.
  - **Gone quiet** — historically-active fingerprints (≥500 lifetime)
    that stopped firing in the last 10 days: deploy-validation signal
    (e.g. the PHYS:* stall classes dying with the 2.7.19/2.7.20 async-log
    deploy on 2026-07-06).

## Severity

  - RED    — a ≥25ms fingerprint fired ≥20 times yesterday AND above its
             trailing mean + 2.5σ (warmup fallback while <4 days of daily
             history: ≥50 occurrences).
  - YELLOW — new fingerprints; or a 10-25ms fingerprint breaching the
             same rule; or any ≥100ms fingerprint with ≥5 occurrences.
  - GREEN  — steady state.

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
import math
import os
import re
import statistics
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

NEW_FINGERPRINTS_LIMIT = 10
MATERIAL_LINES_LIMIT = 12       # embed-field sanity cap; fleet has ~30 fingerprints total

# Magnitude tiers (bucket labels from spike_signatures._BUCKETS). Sub-10ms
# frames are imperceptible at 1000fps — reported as one noise-floor line.
NOISE_BUCKETS = {"0-5ms", "5-10ms"}
SEVERE_BUCKETS = {"100-250ms", "250-500ms", "500ms-1s", "1s+"}   # ≥100ms
RED_ELIGIBLE_BUCKETS = SEVERE_BUCKETS | {"25-50ms", "50-100ms"}  # ≥25ms
# Canonical bucket order for severity sorting (worst first).
BUCKET_ORDER = ["1s+", "500ms-1s", "250-500ms", "100-250ms", "50-100ms",
                "25-50ms", "10-25ms", "5-10ms", "0-5ms"]

BASELINE_WINDOW_DAYS = 7
MIN_BASELINE_DAYS = 4           # same warmup discipline as ktp-perf-rollup
BREACH_SIGMA = 2.5              # Poisson-tail tolerance, matches rollup spikes
BREACH_FLOOR = 20               # occurrences/day below which no breach fires
WARMUP_RED_FLOOR = 50           # absolute red floor while daily history <4 days
SEVERE_YELLOW_FLOOR = 5         # ≥100ms fingerprints at this count are never green
GONE_QUIET_LIFETIME_MIN = 500   # only historically-significant classes
GONE_QUIET_WINDOW_DAYS = 10     # show for ~a week after a class dies, then drop


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


def fetch_day_rows(cnx, day: date) -> list[dict]:
    """Per-(fingerprint, endpoint) occurrence counts for the target day.
    ktp_spike_daily's `day` column is a DATE stamped from log-line ET
    timestamps by the aggregator — no window math needed."""
    with cnx.cursor() as cur:
        cur.execute(
            """SELECT fingerprint, phase, magnitude_bucket, server_endpoint,
                      SUM(count) AS n
               FROM ktp_spike_daily
               WHERE day = %s
               GROUP BY fingerprint, phase, magnitude_bucket, server_endpoint""",
            (day,),
        )
        return list(cur.fetchall())


def fetch_history(cnx, day: date) -> tuple[dict[tuple[str, date], int], set[date]]:
    """Trailing-window per-(fingerprint, day) fleet totals + the set of days
    that have ANY data. The day-set matters: a fingerprint absent on an
    observed day counts as 0, but days before the table existed must not be
    zero-filled (σ=0 baselines would fire on the first real occurrence)."""
    start = day - timedelta(days=BASELINE_WINDOW_DAYS)
    end = day - timedelta(days=1)
    counts: dict[tuple[str, date], int] = {}
    days: set[date] = set()
    with cnx.cursor() as cur:
        cur.execute(
            """SELECT day, fingerprint, SUM(count) AS n
               FROM ktp_spike_daily
               WHERE day BETWEEN %s AND %s
               GROUP BY day, fingerprint""",
            (start, end),
        )
        for row in cur.fetchall():
            d = row["day"]
            days.add(d)
            counts[(row["fingerprint"], d)] = int(row["n"])
    return counts, days


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


def fetch_gone_quiet(cnx, day: date) -> list[dict]:
    """Historically-active fingerprints that stopped firing recently —
    last_seen before the target day but within the lookback window.
    Anything that fired ON the target day is excluded by the < bound."""
    start = datetime.combine(day - timedelta(days=GONE_QUIET_WINDOW_DAYS),
                             datetime.min.time())
    end = datetime.combine(day, datetime.min.time())
    with cnx.cursor() as cur:
        cur.execute(
            """SELECT fingerprint, count, last_seen
               FROM ktp_spike_signatures
               WHERE count >= %s AND last_seen >= %s AND last_seen < %s
               ORDER BY count DESC""",
            (GONE_QUIET_LIFETIME_MIN, start, end),
        )
        return list(cur.fetchall())


# ──────────────────────────────────────────────────────────────────────────
# Analysis
# ──────────────────────────────────────────────────────────────────────────

def bucket_rank(bucket: str) -> int:
    """Lower = more severe. Unknown buckets sort mid-pack rather than last
    so a future engine-side bucket addition stays visible."""
    try:
        return BUCKET_ORDER.index(bucket)
    except ValueError:
        return len(SEVERE_BUCKETS)


def summarize_day(day_rows: list[dict]) -> list[dict]:
    """Collapse per-endpoint rows into one summary per fingerprint:
    {fingerprint, phase, bucket, total, worst_endpoint, worst_n}."""
    by_fp: dict[str, dict] = {}
    for row in day_rows:
        fp = row["fingerprint"]
        n = int(row["n"])
        s = by_fp.get(fp)
        if s is None:
            by_fp[fp] = {
                "fingerprint": fp,
                "phase": row["phase"],
                "bucket": row["magnitude_bucket"],
                "total": n,
                "worst_endpoint": row["server_endpoint"],
                "worst_n": n,
            }
        else:
            s["total"] += n
            if n > s["worst_n"]:
                s["worst_endpoint"], s["worst_n"] = row["server_endpoint"], n
    return sorted(by_fp.values(),
                  key=lambda s: (bucket_rank(s["bucket"]), -s["total"]))


def norm_for(fp: str, history: dict[tuple[str, date], int],
             history_days: set[date]) -> tuple[Optional[float], Optional[float]]:
    """(mean, stddev) of the fingerprint's daily fleet total across observed
    history days (absent = 0). None-pair while history is in warmup."""
    if len(history_days) < MIN_BASELINE_DAYS:
        return None, None
    series = [history.get((fp, d), 0) for d in sorted(history_days)]
    return statistics.mean(series), statistics.stdev(series)


def breaches(total: int, mean: Optional[float], sd: Optional[float]) -> bool:
    """Did yesterday's count materially exceed the trailing norm?"""
    if total < BREACH_FLOOR:
        return False
    if mean is None:
        return total >= WARMUP_RED_FLOOR
    # Counts are Poisson-ish: a constant history (sd=0) must not make a
    # +1 excursion breach. Floor σ at sqrt(mean).
    sd_eff = max(sd, math.sqrt(mean))
    return total > mean + BREACH_SIGMA * sd_eff


# ──────────────────────────────────────────────────────────────────────────
# Embed construction
# ──────────────────────────────────────────────────────────────────────────

def _cap_field(body: str) -> str:
    """Discord field-value cap is 1024. 1010 + len('\\n…(truncated)')=13 → 1023."""
    if len(body) > 1020:
        cut = body.rfind("\n", 0, 1010)
        body = (body[:cut] if cut > 0 else body[:1010]) + "\n…(truncated)"
    return body


def build_embed(day: date, summaries: list[dict],
                history: dict[tuple[str, date], int], history_days: set[date],
                new: list[dict], gone_quiet: list[dict]) -> Optional[dict]:
    """Daily digest embed. Returns None if there's nothing to report
    (empty fleet day — daemon down, or daily table not yet populated)."""
    if not summaries and not new and not gone_quiet:
        return None

    material = [s for s in summaries if s["bucket"] not in NOISE_BUCKETS]
    noise = [s for s in summaries if s["bucket"] in NOISE_BUCKETS]
    total_all = sum(s["total"] for s in summaries)
    total_material = sum(s["total"] for s in material)
    total_severe = sum(s["total"] for s in material if s["bucket"] in SEVERE_BUCKETS)
    warming_up = len(history_days) < MIN_BASELINE_DAYS

    # Severity: evaluate every material fingerprint against its trailing norm.
    color = KTP_GREEN
    red_hits, yellow_hits = [], []
    for s in material:
        mean, sd = norm_for(s["fingerprint"], history, history_days)
        s["mean7"] = mean
        if breaches(s["total"], mean, sd):
            (red_hits if s["bucket"] in RED_ELIGIBLE_BUCKETS else yellow_hits).append(s)
        elif s["bucket"] in SEVERE_BUCKETS and s["total"] >= SEVERE_YELLOW_FLOOR:
            yellow_hits.append(s)
    if red_hits:
        color = KTP_RED
        logging.warning("RED: %s", [(s["fingerprint"], s["total"]) for s in red_hits])
    elif yellow_hits or new:
        color = KTP_YELLOW

    fields = []

    if material:
        lines = []
        for s in material[:MATERIAL_LINES_LIMIT]:
            avg = (f"7d avg {s['mean7']:.0f}/day" if s.get("mean7") is not None
                   else "no baseline yet")
            marker = " 🔴" if s in red_hits else (" 🟡" if s in yellow_hits else "")
            lines.append(
                f"`{s['fingerprint']:16s}` **{s['total']}** yesterday · {avg} · "
                f"worst: `{s['worst_endpoint']}` ({s['worst_n']}){marker}"
            )
        if len(material) > MATERIAL_LINES_LIMIT:
            lines.append(f"… +{len(material) - MATERIAL_LINES_LIMIT} more")
        fields.append({
            "name": f"Spikes ≥10ms — {total_material} yesterday ({total_severe} were ≥100ms)",
            "value": _cap_field("\n".join(lines)),
            "inline": False,
        })
    else:
        fields.append({
            "name": "Spikes ≥10ms",
            "value": "none — every slow frame yesterday stayed under 10ms 🎉",
            "inline": False,
        })

    if new:
        lines = []
        for row in new:
            posted_marker = "" if row["posted_alert"] else "  ⚠️ alert NOT posted"
            lines.append(
                f"`{row['fingerprint']:16s}` ×{row['count']} since first seen "
                f"on {row['sample_endpoint']}{posted_marker}"
            )
        fields.append({
            "name": f"New fingerprints first seen yesterday ({len(new)})",
            "value": _cap_field("\n".join(lines)),
            "inline": False,
        })

    if noise:
        noise_total = sum(s["total"] for s in noise)
        noise_avg = None
        if not warming_up:
            noise_fps = {s["fingerprint"] for s in noise} | {
                fp for (fp, _d) in history if fp.split(":", 1)[-1] in NOISE_BUCKETS
            }
            per_day = [
                sum(history.get((fp, d), 0) for fp in noise_fps)
                for d in sorted(history_days)
            ]
            noise_avg = statistics.mean(per_day) if per_day else None
        avg_txt = f" · 7d avg {noise_avg:.0f}/day" if noise_avg is not None else ""
        fields.append({
            "name": "Noise floor (<10ms frames — imperceptible at 1000fps)",
            "value": f"{noise_total} occurrences{avg_txt} · "
                     + " · ".join(f"`{s['fingerprint']}` {s['total']}" for s in noise[:6]),
            "inline": False,
        })

    if gone_quiet:
        lines = [
            f"`{row['fingerprint']:16s}` last {row['last_seen']:%Y-%m-%d %H:%M} · "
            f"{row['count']:,} lifetime"
            for row in gone_quiet[:6]
        ]
        fields.append({
            "name": "Gone quiet (historically active, stopped firing)",
            "value": _cap_field("\n".join(lines)),
            "inline": False,
        })

    footer = ("ktp-spike-digest · counts from ktp_spike_daily · "
              f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}")
    if warming_up:
        footer += f" · baselines warming up ({len(history_days)}/{MIN_BASELINE_DAYS} days)"

    return {
        "title": f"{KTP_EMOJI}  KTP Spike Digest — {day.isoformat()}",
        "description": (
            f"**{total_all}** slow frames fleet-wide yesterday: **{total_material}** ≥10ms, "
            f"**{total_severe}** ≥100ms. A spike = one frame over the ~3ms engine threshold "
            f"(budget 1ms at 1000fps); fingerprint = dominant cost + frame duration "
            f"(READ inbound net · PHYS game sim · STEAM Steam API · SEND outbound net)."
        ),
        "color": color,
        "fields": fields,
        "footer": {"text": footer},
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
    except urllib.error.URLError as e:
        # Relay fully down (refused/DNS/timeout) — synthetic status instead
        # of a traceback, same pattern as ktp-perf-rollup.
        return 0, f"relay unreachable: {e.reason}"


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
        day_rows = fetch_day_rows(cnx, target_day)
        history, history_days = fetch_history(cnx, target_day)
        new = fetch_new_fingerprints(cnx, target_day, NEW_FINGERPRINTS_LIMIT)
        gone_quiet = fetch_gone_quiet(cnx, target_day)
        summaries = summarize_day(day_rows)
        logging.info(
            "target_day=%s fingerprints=%d total=%d new=%d gone_quiet=%d history_days=%d",
            target_day, len(summaries), sum(s["total"] for s in summaries),
            len(new), len(gone_quiet), len(history_days),
        )
    finally:
        cnx.close()

    embed = build_embed(target_day, summaries, history, history_days, new, gone_quiet)
    if embed is None:
        logging.info("no signature activity for %s — skipping post "
                     "(daily table empty for the day: aggregator down, or "
                     "pre-ktp_spike_daily deploy)", target_day)
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
