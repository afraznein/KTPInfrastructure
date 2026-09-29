#!/usr/bin/env python3
"""One place that decides a KTP alert's channel, glyph and colour.

Every producer used to carry its own colour constants and its own channel
default, so the estate drifted in both: `hltv-restart-all.sh` renders pure
`0x00FF00` where `ktp-perf-rollup.py` renders the KTP green, and `#ktp-crashes`
became the crash, health, perf, spike-digest *and* ops-digest channel because a
channel default is easier to copy than to decide.

This module is not a sixth alerting implementation — it owns no state file, no
fail-streak and no cooldown, and it never posts. `OBSERVABILITY_PLAN.md` §2.1
still stands: new checks become producers for an existing one. What this owns is
the two decisions every producer was making privately and differently.

Three rules it exists to make mechanical:

  1. Silence means healthy. `should_post` returns False for a green run unless
     the run before it was not green, which is the recovery a page owes.
  2. A confirmation that scheduled work succeeded is not an alert. Green
     scheduled work takes `Lane.OPS_DAILY` and, if it has anything to say at
     all, a digest line rather than a post.
  3. One glyph set, set here.

Channel IDs are deliberately NOT in this file. `resolve_channel` reads a lane's
id from the environment or the relay conf and falls back to whatever the caller
was already using, so merging this changes no routing until an operator maps
lanes to ids in `/etc/ktp/discord-relay.conf`. A lane with no mapping and no
legacy channel raises — it must never guess an id.

The bash twin `ktp-alert-routing.sh` carries the same constants for the shell
producers; `tests/unit/test_alert_routing.py` fails if the two disagree.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from enum import Enum
from pathlib import Path
from typing import NamedTuple, Optional


# ──────────────────────────────────────────────────────────────────────────
# Canon
# ──────────────────────────────────────────────────────────────────────────

# Discord's own palette, which is what perf-rollup, spike-digest, soak-verify,
# crashreporter and data-server-health already render. The raw-hex values some
# producers still carry (65280 / 16711680 / 16750848 / 15158332 / 16776960)
# are the drift this replaces, not an alternative.
KTP_GREEN = 5763719    # #57F287
KTP_YELLOW = 16763904  # #FFCC00
KTP_RED = 15548997     # #ED4245
KTP_GREY = 9807270     # #95A5A6 — the one new value, for ⚪ informational


class Severity(Enum):
    """What the reader is being asked to do, not how bad the number is."""

    PAGE = "page"          # wake someone; something is down or lost
    WARN = "warn"          # look today; a trend crossed a line
    INFO = "info"          # a record, not a request
    RECOVERY = "recovery"  # the page above it is over


class Lane(Enum):
    """Where it lands. Named by role so the ids live in config, not in code."""

    PAGE = "page"
    OPS_DAILY = "ops-daily"
    OPS_WEEKLY = "ops-weekly"
    COMMUNITY = "community"


GLYPHS: dict[Severity, str] = {
    Severity.PAGE: "🔴",
    Severity.WARN: "🟠",
    Severity.INFO: "⚪",
    Severity.RECOVERY: "🟢",
}

COLORS: dict[Severity, int] = {
    Severity.PAGE: KTP_RED,
    Severity.WARN: KTP_YELLOW,
    Severity.INFO: KTP_GREY,
    Severity.RECOVERY: KTP_GREEN,
}

# A recovery lands where its page landed, or nobody sees the all-clear.
DEFAULT_LANE: dict[Severity, Lane] = {
    Severity.PAGE: Lane.PAGE,
    Severity.WARN: Lane.OPS_DAILY,
    Severity.INFO: Lane.OPS_DAILY,
    Severity.RECOVERY: Lane.PAGE,
}

# Config/env key a lane's channel id is read from.
LANE_ENV_KEY: dict[Lane, str] = {
    Lane.PAGE: "KTP_CHANNEL_PAGE",
    Lane.OPS_DAILY: "KTP_CHANNEL_OPS_DAILY",
    Lane.OPS_WEEKLY: "KTP_CHANNEL_OPS_WEEKLY",
    Lane.COMMUNITY: "KTP_CHANNEL_COMMUNITY",
}

# Every producer that posts, and the lane its output belongs in. This is the
# table an operator maps to channel ids; it is here so "which producers feed
# this channel" is answerable without grepping nine scripts.
PRODUCER_LANE: dict[str, Lane] = {
    "crashreporter": Lane.PAGE,
    "ktp-systemd-alert": Lane.PAGE,
    "ktp-data-server-health": Lane.PAGE,
    "ktp-hltv-liveness": Lane.PAGE,
    "ktp-backup-watchdog": Lane.PAGE,
    "ktp-fleet-audit": Lane.OPS_DAILY,
    "ktp-perf-rollup": Lane.OPS_DAILY,
    "ktp-post-reboot-verify": Lane.OPS_DAILY,
    "ktp-scheduled-kernel-reboot": Lane.OPS_DAILY,
    "ktp-scheduled-restart": Lane.OPS_DAILY,
    "hltv-restart-all": Lane.OPS_DAILY,
    "ktp-demo-retention": Lane.COMMUNITY,
    "ktp-spike-digest": Lane.OPS_WEEKLY,
    "ktp-soak-verify": Lane.OPS_WEEKLY,
    "ktp-tier2-heartbeat": Lane.OPS_WEEKLY,
    "post-tier2-result": Lane.OPS_WEEKLY,
    "precache-audit": Lane.OPS_WEEKLY,
    "ktp-install-freshness": Lane.OPS_DAILY,
}


class Route(NamedTuple):
    severity: Severity
    lane: Lane
    glyph: str
    color: int


def route(severity: Severity, lane: Optional[Lane] = None) -> Route:
    """Glyph and colour from severity; lane from severity unless overridden."""
    return Route(
        severity=severity,
        lane=lane or DEFAULT_LANE[severity],
        glyph=GLYPHS[severity],
        color=COLORS[severity],
    )


def route_for(producer: str, severity: Severity) -> Route:
    """Route by producer name, so a producer's lane is stated once, here.

    A RECOVERY keeps its producer's lane rather than being forced to PAGE: a
    weekly producer's all-clear belongs next to the thing it clears.
    """
    lane = PRODUCER_LANE.get(producer)
    return route(severity) if lane is None else route(severity, lane)


# ──────────────────────────────────────────────────────────────────────────
# Channel resolution — reads ids, never invents one
# ──────────────────────────────────────────────────────────────────────────

_CONF_LINE = re.compile(r'^\s*([A-Z_][A-Z_0-9]*)\s*=\s*(.+?)\s*$')
_CHANNEL_ID = re.compile(r"^\d{17,20}$")


def load_conf(path: str | os.PathLike[str] = "/etc/ktp/discord-relay.conf") -> dict[str, str]:
    """Same KEY=VALUE shape every producer already parses, quotes stripped.

    A missing file is not an error: the env alone is a complete configuration.
    """
    out: dict[str, str] = {}
    p = Path(path)
    if not p.is_file():
        return out
    for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _CONF_LINE.match(line)
        if not m:
            continue
        val = m.group(2)
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        out[m.group(1)] = val
    return out


class ChannelChoice(NamedTuple):
    channel_id: str
    source: str  # "env" | "conf" | "legacy" — log it; routing bugs are silent


def resolve_channel(lane: Lane,
                    conf: Optional[dict[str, str]] = None,
                    legacy: Optional[str] = None) -> ChannelChoice:
    """env → relay conf → the caller's existing channel.

    The legacy fallback is what makes this safe to merge ahead of the config
    change: until an operator sets the lane keys, every producer posts exactly
    where it posts today. A lane with neither a mapping nor a legacy channel
    raises rather than returning a plausible id.
    """
    key = LANE_ENV_KEY[lane]
    conf = conf or {}
    for source, value in (("env", os.environ.get(key)), ("conf", conf.get(key))):
        if value:
            value = value.strip()
            if not _CHANNEL_ID.match(value):
                raise ValueError(f"{key} from {source} is not a Discord channel id: {value!r}")
            return ChannelChoice(value, source)
    if legacy:
        return ChannelChoice(legacy, "legacy")
    raise LookupError(
        f"no channel for lane {lane.value}: set {key} in the environment or "
        f"/etc/ktp/discord-relay.conf, or pass the producer's existing channel "
        f"as legacy=. This never guesses an id."
    )


# ──────────────────────────────────────────────────────────────────────────
# Silence means healthy
# ──────────────────────────────────────────────────────────────────────────

def should_post(severity: Severity,
                previous: Optional[Severity] = None,
                *,
                allow_recovery: bool = True) -> bool:
    """A green run is silent unless it is the first green after a bad one.

    `previous` is the last severity this producer decided, from its own state
    file — this function keeps no state. Passing None (no history, e.g. a first
    run or a lost state file) treats a green as routine and stays quiet, which
    is the safe direction: a lost state file must not manufacture an all-clear
    for a page nobody saw.
    """
    if severity in (Severity.PAGE, Severity.WARN):
        return True
    if severity is Severity.RECOVERY:
        return allow_recovery
    # INFO: a confirmation that scheduled work succeeded is not an alert.
    if previous in (Severity.PAGE, Severity.WARN) and allow_recovery:
        return True
    return False


def recovery_of(severity: Severity, previous: Optional[Severity]) -> Severity:
    """Promote a routine green to RECOVERY when it follows a page or a warn."""
    if severity is Severity.INFO and previous in (Severity.PAGE, Severity.WARN):
        return Severity.RECOVERY
    return severity


# ──────────────────────────────────────────────────────────────────────────
# Digest spool — a line, not a post
# ──────────────────────────────────────────────────────────────────────────

DEFAULT_SPOOL_DIR = "/var/lib/ktp-alerts"


def spool_path(lane: Lane, spool_dir: Optional[str] = None) -> Path:
    base = spool_dir or os.environ.get("KTP_ALERT_SPOOL_DIR") or DEFAULT_SPOOL_DIR
    return Path(base) / f"{lane.value}.jsonl"


def record_digest_line(producer: str, text: str,
                       severity: Severity = Severity.INFO,
                       lane: Lane = Lane.OPS_DAILY,
                       spool_dir: Optional[str] = None) -> Path:
    """Append one line for the digest to drain. Never posts.

    Appended with a single `write` of one line so two producers racing on the
    spool interleave whole lines rather than fragments.
    """
    path = spool_path(lane, spool_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": int(time.time()),
        "producer": producer,
        "severity": severity.value,
        "glyph": GLYPHS[severity],
        "text": text,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def drain_digest_lines(lane: Lane = Lane.OPS_DAILY,
                       spool_dir: Optional[str] = None) -> list[dict]:
    """Read and clear the spool. A malformed line is dropped, not fatal — the
    digest posting nothing because one producer wrote junk is the failure this
    is meant to prevent."""
    path = spool_path(lane, spool_dir)
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    path.write_text("", encoding="utf-8")
    out: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


# ──────────────────────────────────────────────────────────────────────────
# Embed shape
# ──────────────────────────────────────────────────────────────────────────

def title(route_: Route, text: str) -> str:
    return f"{route_.glyph} {text}"


def embed(route_: Route, text: str, description: str,
          footer: Optional[str] = None) -> dict:
    """The embed every producer already builds, with the colour decided here."""
    out: dict = {
        "title": title(route_, text),
        "description": description,
        "color": route_.color,
    }
    if footer:
        out["footer"] = {"text": footer}
    return out


# ──────────────────────────────────────────────────────────────────────────
# CLI — so a shell producer can ask without a second implementation
# ──────────────────────────────────────────────────────────────────────────

def _cli(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Print the routing decision for a severity.")
    ap.add_argument("severity", choices=[s.value for s in Severity])
    ap.add_argument("--producer", help="resolve the lane from the producer table")
    ap.add_argument("--lane", choices=[l.value for l in Lane])
    ap.add_argument("--legacy-channel", help="channel to fall back to when the lane is unmapped")
    ap.add_argument("--conf", default="/etc/ktp/discord-relay.conf")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    sev = Severity(args.severity)
    if args.lane:
        r = route(sev, Lane(args.lane))
    elif args.producer:
        r = route_for(args.producer, sev)
    else:
        r = route(sev)

    try:
        choice = resolve_channel(r.lane, load_conf(args.conf), args.legacy_channel)
    except LookupError as exc:
        print(f"ktp_alert_routing: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({
            "severity": r.severity.value, "lane": r.lane.value,
            "glyph": r.glyph, "color": r.color,
            "channel": choice.channel_id, "channel_source": choice.source,
        }))
    else:
        # KEY=VALUE so a caller can `eval` it.
        print(f"KTP_ALERT_GLYPH={r.glyph}")
        print(f"KTP_ALERT_COLOR={r.color}")
        print(f"KTP_ALERT_LANE={r.lane.value}")
        print(f"KTP_ALERT_CHANNEL={choice.channel_id}")
        print(f"KTP_ALERT_CHANNEL_SOURCE={choice.source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
