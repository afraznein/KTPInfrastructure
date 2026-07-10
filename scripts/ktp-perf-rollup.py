#!/usr/bin/env python3
"""ktp-perf-rollup — daily fleet performance threshold-alert script.

Fires daily 04:30 ET via cron (after the 03:00 game-server restart and the
04:00 demo-organizer cron). Computes per-host trailing-7-day baselines from
hlstatsx.ktp_telemetry_metrics (populated every 5 min by ktp-profile-aggregator)
and alerts on hosts deviating ≥2σ from their own baseline.

Three-tier severity model per `TODO.md` Tier 3 Project 1 follow-up spec:

  WARN      yellow embed, no role-ping
              per-host fps_p50 < (host_baseline_mean - 2σ), gated by a
              ≥5fps / ≥0.5% magnitude floor (retuned 1.5.31 — the fleet
              runs saturated at ~999.5 fps, sub-5fps daily-median drift is
              player-imperceptible)
              OR per-host daily ≥10ms spike count > (host_baseline_mean + 2.5σ)
              (source switched to ktp_spike_daily material frames in 1.5.31 —
              the old per-phase spike_total was magnitude-blind, dominated by
              imperceptible 0-10ms frames; 2.5σ retained from the 2026-05-05
              Poisson-tail tune, see CHANGELOG 1.5.17)

  CRITICAL  red embed, no role-ping
              ≥3 hosts WARN on the same day
              (catches partial-fleet regressions, e.g. one region's kernel
              update batch hitting 3+ hosts)

  CRITICAL  red embed, role-ping @KTP Admin
              fleet daily median fps_p50 < FLEET_CRITICAL_FPS_THRESHOLD
              (catches fleet-wide regressions: kernel, plugin deploy)

Daily aggregates, NOT per-window — per-window 2σ would fire on every nightly
03:00 ET restart artifact (server fresh = warm-up jitter). Daily smoothing
absorbs 1-2 anomalous 5-min windows in 288/day.

No hosts excluded from WARN evaluation by default. (NY:27019 was excluded
while it ran as the pingboost-4 canary; retired 2026-05-13 when it reverted
to fleet config, default cleared 2026-07-10.) Configurable via
PERF_EXCLUDED_HOSTS in /etc/ktp/discord-relay.conf (comma-separated
host:port endpoints).

48-hour suppression on first deploy: --dry-run flag computes alerts but
does not POST to Discord — use to eyeball output before unleashing.

Usage:
  ktp-perf-rollup [--day YYYY-MM-DD]   default: yesterday (UTC-4 ET interp)
                  [--dry-run]          compute + log, do not POST
                  [--config PATH]      default: /etc/ktp/discord-relay.conf

Required env (or in --config file as KEY="value" lines):
  RELAY_URL                Cloud Run discord relay endpoint
  AUTH_SECRET              X-Relay-Auth header value
  PERF_ALERT_CHANNEL       Discord channel ID for embed delivery
  MYSQL_PASSWORD           hlstatsx user password
Optional:
  MYSQL_USER               default ktp_telemetry (matches aggregator)
  MYSQL_HOST               default localhost
  MYSQL_DB                 default hlstatsx
  PERF_EXCLUDED_HOSTS      comma-separated host:port (default: none)
  KTP_ADMIN_ROLE_ID        Discord role ID for @KTP Admin pings (default 1002394466700767332)
  FLEET_CRITICAL_FPS       Threshold for fleet-median CRITICAL (default 995)

Cross-references:
  - hlstatsx.ktp_telemetry_metrics  fps source data, populated every 5 min
  - hlstatsx.ktp_spike_daily        ≥10ms spike counts (aggregator, 1.5.31)
  - hlstatsx.ktp_telemetry_baselines forensic cache (this script writes)
  - /opt/ktp-profile-aggregator/aggregator.py  upstream collector
  - TEST_INFRASTRUCTURE_PLAN.md § Tier 3 Project 1
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shlex
import statistics
import sys
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pymysql
from pymysql.cursors import DictCursor


# ──────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = Path("/etc/ktp/discord-relay.conf")
# σ thresholds split per metric. fps stays at 2σ — Gaussian-ish distribution,
# 2σ catches real regressions cleanly. Spike count is heavily Poisson on the
# tail (per the design doc and the 2026-05-05 first-fire data: DAL3 spikes
# 333 vs threshold 332, just 1 over — textbook 2σ-on-Poisson false-positive)
# so spikes use 2.5σ to widen the band by ~25%. Same DAL3 example with 2.5σ
# would give threshold 365 — DAL3's 333 sits comfortably below, while real
# anomalies like DAL5 (378 vs 343 threshold at 2.5σ) still flag.
FPS_SIGMA_THRESHOLD = 2.0
SPIKE_SIGMA_THRESHOLD = 2.5

# FPS-side absolute-drop floor (1.5.21; retuned 1.5.31 for the 1000fps fleet).
# 2σ alone fires for any drop ≥ 2σ regardless of magnitude — with the fleet
# saturated at ~999.5 fps and per-host σ of 0.3-0.7 (post async-log-writer,
# 2026-07 data), the old ≥1fps floor made WARN fire on 0.5-2 fps daily-median
# drift: 12 host-WARNs in the first 9 days of July, several days reaching the
# ≥3-host CRITICAL rule, all player-imperceptible. At the cap, daily-median
# fps is a saturated metric — a drop only matters when it's large. Floor
# raised to ≥5 fps absolute OR ≥0.5% relative (lenient OR keeps lower-fps
# hosts responsive if one ever rejoins the fleet).
FPS_MIN_DROP_FPS = 5.0
FPS_MIN_DROP_PCT = 0.005  # 0.5%
BASELINE_WINDOW_DAYS = 7
CRITICAL_HOST_COUNT = 3
# Fleet-median CRITICAL is the boiled-frog backstop: the trailing baseline
# self-adjusts to slow sags, this absolute floor doesn't. Re-derived 1.5.31:
# worst fleet-median day on the post-.927 stack is 999.08 (2026-07-07, heavy
# deploy day; day-to-day σ ≈ 0.3), and map changes never reach the daily
# median (idle self-cycles are already in the 999.5 steady state). 995 has
# >4 fps of margin below any observed day yet would have caught the May-era
# 975-979 regression state. Prior value 963 = 976.5 - 2*6.83 (2026-05-03
# baseline, pre async-log-writer) — allowed a ~36 fps silent fleet sag.
DEFAULT_FLEET_CRITICAL_FPS = 995.0
DEFAULT_EXCLUDED = ""  # NY:27019 canary exclusion retired 2026-05-13 (reverted to fleet config)
DEFAULT_ADMIN_ROLE = "1002394466700767332"  # @KTP Admin

KTP_GREEN = 5763719
KTP_YELLOW = 16763904
KTP_RED = 15548997

# Schema for the per-day baseline cache. Idempotent on (server_endpoint, day):
# rerunning for the same day overwrites the row (script is intentionally
# replayable so an operator can fix a config issue and rerun).
# spike_total_* semantics changed 1.5.31: rows before 2026-07-10 hold
# all-phase per-phase-line counts (~200/day); rows after hold ≥10ms
# umbrella-frame counts (~0-20/day). Don't compare across the boundary.
DDL_BASELINES = """
CREATE TABLE IF NOT EXISTS ktp_telemetry_baselines (
    server_endpoint VARCHAR(48) NOT NULL,
    day DATE NOT NULL,
    fps_p50_today FLOAT NOT NULL,
    fps_p50_mean FLOAT,
    fps_p50_stddev FLOAT,
    fps_p50_baseline FLOAT,
    spike_total_today INT NOT NULL,
    spike_total_mean FLOAT,
    spike_total_stddev FLOAT,
    spike_total_baseline FLOAT,
    warn_fps TINYINT NOT NULL DEFAULT 0,
    warn_spikes TINYINT NOT NULL DEFAULT 0,
    posted_to_discord TINYINT NOT NULL DEFAULT 0,
    computed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (server_endpoint, day),
    KEY idx_day (day)
)
""".strip()


# ──────────────────────────────────────────────────────────────────────────
# Config loading
# ──────────────────────────────────────────────────────────────────────────

def load_config(config_path: Path) -> dict[str, str]:
    """Load shell-style KEY="value" lines from a config file. Comments + blank
    lines tolerated. Quotes optional; leading whitespace stripped per line.
    Existing env vars take precedence so callers can override interactively."""
    out: dict[str, str] = {}
    if not config_path.exists():
        logging.warning("config %s not found — relying on env-only", config_path)
        return out
    line_re = re.compile(r'^\s*([A-Z_][A-Z_0-9]*)\s*=\s*(.+?)\s*$')
    for line in config_path.read_text().splitlines():
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("#"):
            continue
        m = line_re.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        # Strip matching outer quotes (single or double); shlex.split handles
        # the corner cases without us needing to.
        try:
            tokens = shlex.split(val)
            val = tokens[0] if tokens else ""
        except ValueError:
            pass
        out[key] = val
    return out


def resolve(env_key: str, file_cfg: dict[str, str], default: Optional[str] = None) -> Optional[str]:
    # `or`-chaining means a KEY="" in the config falls through to the default —
    # an explicitly-empty value cannot override a non-empty default (bit us on
    # PERF_EXCLUDED_HOSTS 2026-05-13→07-10; keep defaults empty where "" is valid).
    return os.environ.get(env_key) or file_cfg.get(env_key) or default


# ──────────────────────────────────────────────────────────────────────────
# Database
# ──────────────────────────────────────────────────────────────────────────

def open_mysql(password: str) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "localhost"),
        user=os.environ.get("MYSQL_USER", "ktp_telemetry"),
        password=password,
        database=os.environ.get("MYSQL_DB", "hlstatsx"),
        cursorclass=DictCursor,
        autocommit=True,
        connect_timeout=10,
        charset="utf8mb4",
    )


def ensure_baseline_schema(cnx: pymysql.connections.Connection) -> None:
    """Ensure the ktp_telemetry_baselines table exists. Runs DDL only if the
    table is missing — `CREATE TABLE IF NOT EXISTS` itself still requires
    CREATE privilege to evaluate (MySQL behavior), so unconditional execution
    fails under the ktp_telemetry user that lacks DDL rights. The probe-then-
    create pattern below keeps the steady-state path SELECT-only on
    information_schema, which ktp_telemetry has by default.
    """
    with cnx.cursor() as cur:
        cur.execute("SHOW TABLES LIKE 'ktp_telemetry_baselines'")
        if cur.fetchone():
            return
        cur.execute(DDL_BASELINES)


def fetch_daily_aggregates(
    cnx: pymysql.connections.Connection, start: date, end: date,
) -> dict[tuple[str, date], dict[str, float]]:
    """Return {(server_endpoint, day): {fps_p50_mean}} over the inclusive
    [start, end] day range. Day key is `DATE(window_end)` per row.
    Empty windows (no rows for a host on a day) → key absent.

    Spike counts intentionally NOT sourced here anymore (1.5.31): the
    per-phase spike_* columns are magnitude-blind — dominated by 0-10ms
    frames that are imperceptible at 1000fps, while a handful of 100ms
    stalls hide inside their σ. Material spikes come from ktp_spike_daily
    via fetch_material_spikes below."""
    sql = """
    SELECT
        server_endpoint,
        DATE(window_end) AS day,
        AVG(fps_p50) AS fps_p50_mean
    FROM ktp_telemetry_metrics
    WHERE DATE(window_end) BETWEEN %s AND %s
    GROUP BY server_endpoint, DATE(window_end)
    """
    out: dict[tuple[str, date], dict[str, float]] = {}
    with cnx.cursor() as cur:
        cur.execute(sql, (start.isoformat(), end.isoformat()))
        for row in cur.fetchall():
            key = (row["server_endpoint"], row["day"])
            out[key] = {
                "fps_p50_mean": float(row["fps_p50_mean"]),
            }
    return out


# Buckets below this are imperceptible at 1000fps; matches the digest's
# noise-floor tier (spike_signatures._BUCKETS labels).
SPIKE_NOISE_BUCKETS = ("0-5ms", "5-10ms")


def fetch_material_spikes(
    cnx: pymysql.connections.Connection, start: date, end: date,
) -> tuple[dict[tuple[str, date], int], set[date]]:
    """Per-(endpoint, day) counts of ≥10ms [KTP_SPIKE] umbrella frames from
    ktp_spike_daily, plus the set of days that have ANY fleet data.

    The day-set drives zero-filling: an endpoint absent on an observed day
    genuinely had zero material spikes, but days before the table existed
    (or with the aggregator down) must be EXCLUDED from baselines, not
    zero-filled — a [0,0,0,0] baseline has σ=0 and would WARN on the first
    real occurrence."""
    counts: dict[tuple[str, date], int] = {}
    days: set[date] = set()
    sql = """
    SELECT day, server_endpoint,
           SUM(CASE WHEN magnitude_bucket NOT IN %s THEN count ELSE 0 END) AS material
    FROM ktp_spike_daily
    WHERE day BETWEEN %s AND %s
    GROUP BY day, server_endpoint
    """
    with cnx.cursor() as cur:
        cur.execute(sql, (SPIKE_NOISE_BUCKETS, start.isoformat(), end.isoformat()))
        for row in cur.fetchall():
            days.add(row["day"])
            counts[(row["server_endpoint"], row["day"])] = int(row["material"] or 0)
    return counts, days


def upsert_baseline_row(cnx: pymysql.connections.Connection, row: dict) -> None:
    sql = """
    INSERT INTO ktp_telemetry_baselines
      (server_endpoint, day,
       fps_p50_today, fps_p50_mean, fps_p50_stddev, fps_p50_baseline,
       spike_total_today, spike_total_mean, spike_total_stddev, spike_total_baseline,
       warn_fps, warn_spikes, posted_to_discord)
    VALUES
      (%(server_endpoint)s, %(day)s,
       %(fps_p50_today)s, %(fps_p50_mean)s, %(fps_p50_stddev)s, %(fps_p50_baseline)s,
       %(spike_total_today)s, %(spike_total_mean)s, %(spike_total_stddev)s, %(spike_total_baseline)s,
       %(warn_fps)s, %(warn_spikes)s, %(posted_to_discord)s)
    ON DUPLICATE KEY UPDATE
       fps_p50_today=VALUES(fps_p50_today),
       fps_p50_mean=VALUES(fps_p50_mean),
       fps_p50_stddev=VALUES(fps_p50_stddev),
       fps_p50_baseline=VALUES(fps_p50_baseline),
       spike_total_today=VALUES(spike_total_today),
       spike_total_mean=VALUES(spike_total_mean),
       spike_total_stddev=VALUES(spike_total_stddev),
       spike_total_baseline=VALUES(spike_total_baseline),
       warn_fps=VALUES(warn_fps),
       warn_spikes=VALUES(warn_spikes),
       posted_to_discord=VALUES(posted_to_discord),
       computed_at=CURRENT_TIMESTAMP
    """
    with cnx.cursor() as cur:
        cur.execute(sql, row)


# ──────────────────────────────────────────────────────────────────────────
# Rollup logic
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class HostFinding:
    server_endpoint: str
    fps_p50_today: float
    fps_p50_mean: Optional[float]
    fps_p50_stddev: Optional[float]
    fps_p50_baseline: Optional[float]   # mean - 2σ; threshold for WARN
    spike_total_today: int                 # ≥10ms umbrella frames (1.5.31; was all-phase count)
    spike_total_mean: Optional[float]
    spike_total_stddev: Optional[float]
    spike_total_baseline: Optional[float]  # mean + 2.5σ (Poisson-tail tolerance)
    warn_fps: bool = False
    warn_spikes: bool = False

    @property
    def warn(self) -> bool:
        return self.warn_fps or self.warn_spikes


def compute_findings(
    target_day: date,
    aggregates: dict[tuple[str, date], dict[str, float]],
    material_spikes: dict[tuple[str, date], int],
    spike_days: set[date],
    excluded: set[str],
) -> list[HostFinding]:
    """Build per-host findings for `target_day` using the prior 7-day window
    (target_day - 7 .. target_day - 1) as the baseline. Excluded hosts get
    a row but never trigger WARN (data still recorded for forensics).

    Spike counts are ≥10ms umbrella frames from ktp_spike_daily (1.5.31);
    zero-filled per endpoint but only across days the table actually
    observed, so the ≥4-day warmup gate below stays honest while the new
    table accumulates history."""
    baseline_window = [
        target_day - timedelta(days=i) for i in range(1, BASELINE_WINDOW_DAYS + 1)
    ]
    today_keys = [k for k in aggregates if k[1] == target_day]
    findings: list[HostFinding] = []

    for endpoint, _day in sorted(today_keys):
        today = aggregates[(endpoint, target_day)]
        baseline_fps = [
            aggregates[(endpoint, d)]["fps_p50_mean"]
            for d in baseline_window
            if (endpoint, d) in aggregates
        ]
        baseline_spikes = [
            material_spikes.get((endpoint, d), 0)
            for d in baseline_window
            if d in spike_days
        ]
        spikes_today = (
            material_spikes.get((endpoint, target_day), 0)
            if target_day in spike_days else 0
        )

        f = HostFinding(
            server_endpoint=endpoint,
            fps_p50_today=today["fps_p50_mean"],
            fps_p50_mean=None,
            fps_p50_stddev=None,
            fps_p50_baseline=None,
            spike_total_today=spikes_today,
            spike_total_mean=None,
            spike_total_stddev=None,
            spike_total_baseline=None,
        )

        # Need ≥4 baseline data points for σ to stabilize. With only 2 points
        # `statistics.stdev` returns `abs(a-b)` (sample stddev, n-1 denom),
        # which gives random thresholds during the first few days of a fresh
        # deploy: tight-σ hosts fire on sub-fps noise, wide-σ hosts go silent
        # through real regressions. ≥4 means 4 silent days of warmup; that's
        # the cost of a reliable σ estimate. Baseline rows still get persisted
        # with NULL σ during warmup so the operator sees the data accumulate.
        if len(baseline_fps) >= 4:
            f.fps_p50_mean = statistics.mean(baseline_fps)
            f.fps_p50_stddev = statistics.stdev(baseline_fps)
            f.fps_p50_baseline = f.fps_p50_mean - FPS_SIGMA_THRESHOLD * f.fps_p50_stddev
            # Two-condition gate (1.5.21, floors retuned 1.5.31): 2σ test must
            # pass AND the drop must be meaningfully large (≥5 fps absolute OR
            # ≥0.5% relative). Either magnitude condition satisfies the floor —
            # the lenient OR keeps any future lower-fps host responsive while
            # suppressing tight-σ drift on the saturated ~999.5 fps fleet.
            sigma_breach = f.fps_p50_today < f.fps_p50_baseline
            drop_fps = f.fps_p50_mean - f.fps_p50_today
            drop_pct = drop_fps / f.fps_p50_mean if f.fps_p50_mean > 0 else 0.0
            magnitude_meaningful = (
                drop_fps >= FPS_MIN_DROP_FPS or drop_pct >= FPS_MIN_DROP_PCT
            )
            if endpoint not in excluded and sigma_breach and magnitude_meaningful:
                f.warn_fps = True
        if len(baseline_spikes) >= 4:
            f.spike_total_mean = statistics.mean(baseline_spikes)
            f.spike_total_stddev = statistics.stdev(baseline_spikes)
            f.spike_total_baseline = (
                f.spike_total_mean + SPIKE_SIGMA_THRESHOLD * f.spike_total_stddev
            )
            if endpoint not in excluded and f.spike_total_today > f.spike_total_baseline:
                f.warn_spikes = True
        findings.append(f)
    return findings


# ──────────────────────────────────────────────────────────────────────────
# Discord embed
# ──────────────────────────────────────────────────────────────────────────

def fleet_label(endpoint: str) -> str:
    """Map a host:port endpoint to its fleet alias (ATL1..CHI5). Falls back
    to the raw endpoint if the host is unknown — keeps the embed readable
    even for new hosts not yet in the alias table."""
    REGION_BY_HOST = {
        "74.91.121.9":     "ATL",
        "74.91.126.55":    "DAL",
        "66.163.114.109":  "DEN",
        "74.91.123.64":    "NY",
        "172.238.176.101": "CHI",
    }
    try:
        host, port = endpoint.split(":")
        port = int(port)
        region = REGION_BY_HOST.get(host)
        if region and 27015 <= port <= 27019:
            return f"{region}{port - 27014}"
    except (ValueError, KeyError):
        pass
    return endpoint


def build_embed(
    target_day: date,
    findings: list[HostFinding],
    fleet_median_fps: Optional[float],
    fleet_critical_fps: float,
    role_id: str,
) -> Optional[dict]:
    """Returns an embed payload dict if any alert should fire, None if all-clear.
    Severity escalates: any WARN host → YELLOW; ≥3 → RED no-ping; fleet median
    below threshold → RED with @KTP Admin ping."""
    warn_hosts = [f for f in findings if f.warn]
    fleet_critical = (
        fleet_median_fps is not None and fleet_median_fps < fleet_critical_fps
    )
    partial_fleet_critical = len(warn_hosts) >= CRITICAL_HOST_COUNT

    if not warn_hosts and not fleet_critical:
        return None

    severity = "WARN"
    color = KTP_YELLOW
    role_ping = ""
    if fleet_critical:
        severity = "CRITICAL (fleet)"
        color = KTP_RED
        role_ping = f"<@&{role_id}>"
    elif partial_fleet_critical:
        severity = "CRITICAL (partial fleet)"
        color = KTP_RED

    fields = []

    # Per-host detail. Discord field-value cap = 1024 chars. With ~75 chars
    # per host line, a fleet-wide bad day with 14+ hosts WARNing overflows
    # the cap. Truncate with an explicit sentinel so the operator sees that
    # the field was clipped, rather than a silent mid-line cut.
    if warn_hosts:
        lines = []
        for f in warn_hosts:
            label = fleet_label(f.server_endpoint)
            tags = []
            if f.warn_fps:
                tags.append(
                    f"fps {f.fps_p50_today:.1f} < {f.fps_p50_baseline:.1f} "
                    f"(μ {f.fps_p50_mean:.1f} σ {f.fps_p50_stddev:.1f})"
                )
            if f.warn_spikes:
                tags.append(
                    f"≥10ms spikes {f.spike_total_today} > {f.spike_total_baseline:.0f} "
                    f"(μ {f.spike_total_mean:.0f} σ {f.spike_total_stddev:.0f})"
                )
            lines.append(f"**{label}** ({f.server_endpoint}) — " + "; ".join(tags))
        joined = "\n".join(lines)
        if len(joined) > 1020:
            # Trim to the last whole line that fits, leaving room for the
            # marker: 1010 + len("\n…(truncated)")=13 → 1023, under the 1024
            # field cap (the old cap of 1016 overflowed to 1029 and 400'd
            # the whole embed on ≥14-host WARN days).
            cap = 1010
            cut = joined.rfind("\n", 0, cap)
            joined = (joined[:cut] if cut > 0 else joined[:cap]) + "\n…(truncated)"
        fields.append({"name": f"Hosts in WARN ({len(warn_hosts)})",
                       "value": joined, "inline": False})

    if fleet_critical:
        fields.append({
            "name": "Fleet median",
            "value": (f"daily fps_p50 median = **{fleet_median_fps:.1f}** "
                      f"< CRITICAL threshold {fleet_critical_fps:.1f} "
                      f"— possible fleet-wide regression (kernel, plugin deploy)"),
            "inline": False,
        })

    fields.append({
        "name": "Source",
        "value": ("`ktp_telemetry_metrics` fps daily aggregates + `ktp_spike_daily` "
                  "≥10ms spike counts · trailing-7-day baseline · "
                  "fps 2σ + ≥5 fps floor / spike 2.5σ thresholds."),
        "inline": False,
    })

    embed = {
        "title": f"KTP perf rollup — {severity} — {target_day.isoformat()}",
        "description": role_ping if role_ping else None,
        "color": color,
        "fields": fields,
        "footer": {"text": f"ktp-perf-rollup · {datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}"},
    }
    if not embed["description"]:
        del embed["description"]
    return embed


def post_embed(relay_url: str, auth_secret: str, channel_id: str,
               embed: dict, role_id: str) -> tuple[int, str]:
    """POST embed to the relay. Returns (http_status, response_body[:500])."""
    payload = {
        "channelId": channel_id,
        "embeds": [embed],
    }
    if "<@&" in (embed.get("description") or ""):
        # Allow the role mention to actually ping when severity warrants it.
        payload["allowed_mentions"] = {"roles": [role_id]}
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
        # Relay fully down (refused/DNS/timeout) — the likely state when the
        # NO DATA path matters; return a synthetic status instead of a traceback.
        return 0, f"relay unreachable: {e.reason}"


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--day", help="YYYY-MM-DD; default = yesterday (server-local)")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute + log + write baseline rows; do NOT POST to Discord")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = ap.parse_args()

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    file_cfg = load_config(Path(args.config))
    relay_url = resolve("RELAY_URL", file_cfg)
    auth_secret = resolve("AUTH_SECRET", file_cfg)
    channel = resolve("PERF_ALERT_CHANNEL", file_cfg)
    mysql_password = resolve("MYSQL_PASSWORD", file_cfg)
    excluded_raw = resolve("PERF_EXCLUDED_HOSTS", file_cfg, DEFAULT_EXCLUDED)
    role_id = resolve("KTP_ADMIN_ROLE_ID", file_cfg, DEFAULT_ADMIN_ROLE)
    fleet_critical_fps = float(
        resolve("FLEET_CRITICAL_FPS", file_cfg, str(DEFAULT_FLEET_CRITICAL_FPS))
    )

    if not mysql_password:
        logging.error("MYSQL_PASSWORD missing (env or %s)", args.config)
        return 2

    if args.day:
        target_day = date.fromisoformat(args.day)
    else:
        target_day = date.today() - timedelta(days=1)

    excluded = {ep.strip() for ep in (excluded_raw or "").split(",") if ep.strip()}
    logging.info("target_day=%s excluded=%s", target_day, sorted(excluded))

    cnx = open_mysql(mysql_password)
    try:
        ensure_baseline_schema(cnx)
        start = target_day - timedelta(days=BASELINE_WINDOW_DAYS)
        aggregates = fetch_daily_aggregates(cnx, start, target_day)
        if not any(k[1] == target_day for k in aggregates):
            # An empty day means the whole perf-alert tier is blind (usually a
            # dead ktp-profile-aggregator). Exiting 0 silently made a dead
            # aggregator invisible; post a YELLOW heads-up instead. The
            # aggregator is also in ktp-data-server-health's CRITICAL_SERVICES
            # (added 2026-07-07), so this is the belt to that suspenders.
            logging.warning("no telemetry rows for %s — aggregator down?", target_day)
            if relay_url and auth_secret and channel and not args.dry_run:
                empty_embed = {
                    "title": "<:ktp:1105490705188659272> KTP Perf Rollup — NO DATA",
                    "description": (
                        f"Zero telemetry rows for **{target_day}** — the perf-alert "
                        "tier is blind. Check `ktp-profile-aggregator.service` on "
                        "the data server."
                    ),
                    "color": KTP_YELLOW,
                }
                status, body = post_embed(relay_url, auth_secret, channel, empty_embed, "")
                if not (200 <= status < 300):
                    logging.error("no-data alert post failed http=%d body=%s", status, body)
            return 1

        material_spikes, spike_days = fetch_material_spikes(cnx, start, target_day)
        if target_day not in spike_days:
            # Non-fatal: fps evaluation proceeds; spike WARN just stays silent
            # for the day (aggregator not writing ktp_spike_daily yet, or a
            # genuinely zero-spike day — implausible but harmless).
            logging.warning("no ktp_spike_daily rows for %s — spike WARN inactive", target_day)

        findings = compute_findings(target_day, aggregates, material_spikes,
                                    spike_days, excluded)
        if not findings:
            logging.warning("no findings produced — skipping")
            return 0

        # Roll up + persist baseline rows.
        for f in findings:
            row = {
                "server_endpoint": f.server_endpoint,
                "day": target_day.isoformat(),
                "fps_p50_today": f.fps_p50_today,
                "fps_p50_mean": f.fps_p50_mean,
                "fps_p50_stddev": f.fps_p50_stddev,
                "fps_p50_baseline": f.fps_p50_baseline,
                "spike_total_today": f.spike_total_today,
                "spike_total_mean": f.spike_total_mean,
                "spike_total_stddev": f.spike_total_stddev,
                "spike_total_baseline": f.spike_total_baseline,
                "warn_fps": int(f.warn_fps),
                "warn_spikes": int(f.warn_spikes),
                "posted_to_discord": 0,
            }
            upsert_baseline_row(cnx, row)

        # Fleet median over non-excluded hosts.
        included_fps = [
            f.fps_p50_today for f in findings if f.server_endpoint not in excluded
        ]
        fleet_median_fps = statistics.median(included_fps) if included_fps else None
        warn_count = sum(1 for f in findings if f.warn)
        logging.info("findings: %d hosts; warn=%d; fleet_median_fps=%s",
                     len(findings), warn_count, fleet_median_fps)

        embed = build_embed(target_day, findings, fleet_median_fps,
                            fleet_critical_fps, role_id)
        if embed is None:
            logging.info("all-clear — no embed to post")
            return 0

        # Print the embed JSON regardless (operator-eyeball value during the
        # 48h suppression window + general operability). One line, compact.
        print(json.dumps(embed))

        if args.dry_run:
            logging.info("dry-run — would POST embed (suppressed)")
            return 0

        if not (relay_url and auth_secret and channel):
            logging.error("relay creds missing (RELAY_URL/AUTH_SECRET/PERF_ALERT_CHANNEL); not posting")
            return 2

        status, body = post_embed(relay_url, auth_secret, channel, embed, role_id)
        if 200 <= status < 300:
            logging.info("relay OK (%d)", status)
            with cnx.cursor() as cur:
                cur.execute(
                    "UPDATE ktp_telemetry_baselines SET posted_to_discord=1 "
                    "WHERE day=%s",
                    (target_day.isoformat(),),
                )
            return 0
        else:
            logging.error("relay failed http=%d body=%s", status, body)
            return 1

    finally:
        cnx.close()


if __name__ == "__main__":
    sys.exit(main())
