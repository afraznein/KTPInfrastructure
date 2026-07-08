"""spike_signatures — parse [KTP_SPIKE] umbrella lines + compute fingerprints.

Tier 3 Project 3 wedge: ktp-profile-aggregator currently only COUNTS spike
events by phase (`spike_phys`, `spike_read`, `spike_steam`, `spike_send`
columns in `ktp_telemetry_metrics`). Project 3 wants signature bucketing —
which spikes are recurring patterns vs one-off outliers, what's the trend
over time, and an alert path on never-seen-before signatures.

This module is the bottom layer: a pure-Python parser that turns one log
line into a structured `ParsedSpike` and computes a stable `fingerprint`
(`<DOMINANT_PHASE>:<MAGNITUDE_BUCKET>`). No I/O, no MySQL — designed to be
import-safe + unit-tested in isolation. The future categorizer daemon will:

    1. Tail console logs (same as ktp-profile-aggregator does today)
    2. For each `[KTP_SPIKE] …` umbrella line: call `parse_spike_line`
    3. INSERT/UPDATE `hlstatsx.ktp_spike_signatures` keyed on `fingerprint`
       (incrementing `count`, refreshing `last_seen` + `sample_*`)
    4. On a never-before-seen fingerprint, fire an immediate Discord alert

The table schema is INLINED below (see the DDL constant) — deliberately
not a separate .sql file. The aggregator-side wiring is a separate
follow-up commit.

## Why only the umbrella `[KTP_SPIKE]` line, not `[KTP_SPIKE_<phase>]`?

Production logs (sampled 2026-05-04 across all 5 ATL ports):

  L … [KTP_SPIKE] full=3.055ms read=3.039ms phys=0.007ms misc1=0.000ms
       send=0.008ms post=0.000ms steam=0.000ms gap=0.000ms
  L … [KTP_SPIKE_PHYS] startframe=0.001ms entloop=0.006ms …
  L … [KTP_SPIKE_READ] pkts=1(cl=1,conn=0,frag=0) recv=0.005ms proc=3.039ms …

The umbrella line is the only one guaranteed to fire on every spike (the
per-phase lines are sub-threshold-gated). It also has all phases at once,
so dominant-phase identification is stable per line. Per-phase detail
lines remain useful for forensic drill-down — a future commit can add a
separate parser for those — but they're NOT the categorization signal.

A specifically observed gotcha (line at 14:13:48 today):
  full=7.054ms read=0.001ms steam=7.044ms — clearly STEAM-dominant, but
  no `[KTP_SPIKE_STEAM]` line followed (suggests STEAM-side per-phase
  alert is sub-threshold-gated higher than the umbrella, or not yet
  implemented for STEAM/SEND). Categorizer reading umbrella-only catches
  this; categorizer reading per-phase-only would miss it entirely.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# Sample line:
#   L 05/04/2026 - 13:45:58: [KTP_SPIKE] full=3.055ms read=3.039ms phys=0.007ms
#     misc1=0.000ms send=0.008ms post=0.000ms steam=0.000ms gap=0.000ms
#
# All eight ms-suffixed fields are required (no optional phases); engine
# always emits all of them. `gap` can be negative on rounding artifacts —
# the parser accepts +/- on every field. Anchored at start with `^L ` so
# we don't accidentally match a substring deep inside another line.
_RE_UMBRELLA = re.compile(
    r"^L (?P<date>\d{2}/\d{2}/\d{4}) - (?P<time>\d{2}:\d{2}:\d{2}):.*"
    r"\[KTP_SPIKE\]\s+"
    r"full=(?P<full>-?\d+(?:\.\d+)?)ms\s+"
    r"read=(?P<read>-?\d+(?:\.\d+)?)ms\s+"
    r"phys=(?P<phys>-?\d+(?:\.\d+)?)ms\s+"
    r"misc1=(?P<misc1>-?\d+(?:\.\d+)?)ms\s+"
    r"send=(?P<send>-?\d+(?:\.\d+)?)ms\s+"
    r"post=(?P<post>-?\d+(?:\.\d+)?)ms\s+"
    r"steam=(?P<steam>-?\d+(?:\.\d+)?)ms\s+"
    r"gap=(?P<gap>-?\d+(?:\.\d+)?)ms"
)

# Phase names in the order they appear in the umbrella line.
# `gap` is computed (full - sum of phases) and is informational, not a
# phase the spike can be "dominated by" — excluded from dominant-phase
# selection.
PHASES: tuple[str, ...] = ("read", "phys", "misc1", "send", "post", "steam")


# DDL for the categorizer table. Inlined here (same pattern as
# ktp-perf-rollup's DDL_BASELINES) rather than a separate .sql file so
# the schema travels with the parser that defines its key shape, and so
# scripts/.gitignore's blanket `*.sql` rule (keeps ad-hoc SQL out) doesn't
# need a carve-out. Future categorizer daemon will run this once at startup
# (probe-then-create, same pattern as ktp-perf-rollup's ensure_schema).
#
# Operator setup (one-time as MySQL root):
#   USE hlstatsx;
#   <paste DDL_SIGNATURES contents>
#   GRANT SELECT, INSERT, UPDATE ON hlstatsx.ktp_spike_signatures
#     TO 'ktp_telemetry'@'localhost';
#   FLUSH PRIVILEGES;
DDL_SIGNATURES = """
CREATE TABLE IF NOT EXISTS ktp_spike_signatures (
    fingerprint      VARCHAR(64) NOT NULL,
    phase            VARCHAR(16) NOT NULL,
    magnitude_bucket VARCHAR(16) NOT NULL,
    first_seen       TIMESTAMP   NOT NULL,
    last_seen        TIMESTAMP   NOT NULL,
    count            INT         NOT NULL DEFAULT 0,
    sample_endpoint  VARCHAR(48) NOT NULL,
    sample_line      TEXT        NOT NULL,
    posted_alert     TINYINT(1)  NOT NULL DEFAULT 0,
    PRIMARY KEY (fingerprint),
    KEY idx_last_seen (last_seen),
    KEY idx_phase_bucket (phase, magnitude_bucket),
    KEY idx_posted_alert (posted_alert)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
""".strip()

# Magnitude buckets indexed by `full_ms`. Lower bound inclusive, upper
# exclusive. Anything <5ms is below the engine's [KTP_SPIKE] alarm
# threshold (per `KTP_SPIKE` instrumentation in KTP-ReHLDS), so 0-5ms
# is included only for graceful degradation if a sub-threshold line
# slips through. Buckets coarsen as severity climbs — operator only
# needs broad strokes once spikes are >100ms.
_BUCKETS: list[tuple[float, float, str]] = [
    (0,     5,            "0-5ms"),
    (5,     10,           "5-10ms"),
    (10,    25,           "10-25ms"),
    (25,    50,           "25-50ms"),
    (50,    100,          "50-100ms"),
    (100,   250,          "100-250ms"),
    (250,   500,          "250-500ms"),
    (500,   1000,         "500ms-1s"),
    (1000,  float("inf"), "1s+"),
]


@dataclass(frozen=True)
class ParsedSpike:
    """Structured form of one [KTP_SPIKE] umbrella line.

    `fingerprint` is the stable categorization key: `<PHASE>:<BUCKET>`
    (uppercased phase). Two spikes with the same fingerprint represent
    the same kind of regression — same dominant-phase, same magnitude
    range. The categorizer table (ktp_spike_signatures) is keyed on
    this string.
    """
    full_ms: float
    phases: dict[str, float]   # phase name → ms (lowercase keys)
    dominant_phase: str        # uppercase phase name (e.g. "READ", "STEAM")
    magnitude_bucket: str

    @property
    def fingerprint(self) -> str:
        return f"{self.dominant_phase}:{self.magnitude_bucket}"


def magnitude_bucket(full_ms: float) -> str:
    """Map an absolute ms value to its bucket label. Negative inputs (which
    shouldn't appear in `full` but might in noisy edge cases) bucket as
    `0-5ms` since the magnitude scale is one-sided."""
    val = max(0.0, full_ms)
    for lo, hi, label in _BUCKETS:
        if lo <= val < hi:
            return label
    return "unknown"  # pragmatically unreachable given the [1000, ∞) bucket


def parse_spike_line(line: str) -> Optional[ParsedSpike]:
    """Parse one log line. Returns `None` if the line is not a `[KTP_SPIKE]`
    umbrella line — caller should iterate all lines and discard `None`s.

    Per-phase lines (`[KTP_SPIKE_PHYS]` etc.) intentionally return `None`
    here. They have a different shape (per-phase sub-fields like `entloop`
    / `recv` / `proc`) and aren't the categorization signal — see module
    docstring for the rationale.
    """
    m = _RE_UMBRELLA.match(line)
    if not m:
        return None
    try:
        full = float(m.group("full"))
        phases = {p: float(m.group(p)) for p in PHASES}
    except (ValueError, TypeError):
        # Regex matched but a numeric field is malformed — defensive fallback.
        return None
    # Dominant phase = largest absolute value across the named phases.
    # Using abs() because while engine instrumentation theoretically
    # produces non-negative phase times, rounding artifacts have produced
    # tiny negative gaps in production; treat as same direction.
    dominant_name = max(phases, key=lambda k: abs(phases[k]))
    return ParsedSpike(
        full_ms=full,
        phases=phases,
        dominant_phase=dominant_name.upper(),
        magnitude_bucket=magnitude_bucket(full),
    )
