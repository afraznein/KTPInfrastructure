"""Read the engine's `[KTP_PROFILE]` netcode records out of a Lane B log.

The contract under test is that a candidate engine still EMITS these records,
at the configured cadence, carrying the field set the fleet's readers expect --
`scripts/ktp-net-profile.py` parses the same lines off production, and a field
that silently disappears breaks it with no error anywhere.

⚠️ The counters in these records are structurally zero under Lane B and that is
not a fault. `SV_ParseMove` calls `SV_SetupMove` only for a non-fakeclient, and
the per-packet sampler skips fakeclients outright, so bots reach neither the
clamp counters nor the rewind counters. Read them as recorded, never asserted;
a nonzero value here would mean a real client was connected.
"""

from __future__ import annotations

import re

NET_MARKER = "[KTP_PROFILE] net:"
REWIND_MARKER = "[KTP_PROFILE] rewind:"

# `net_detail:` carries several of the same keys, so the marker must keep its
# colon -- a prefix match on "net" collects the detail rows as if they were net
# rows and the field-set check then passes on the wrong line.
FIELD = re.compile(r"(\w+)=(-?[0-9]+(?:\.[0-9]+)?)")

NET_FIELDS = (
    "clients", "unlag", "lagcomp_off", "ignorecmd_hits", "drops", "latzero",
    "choke_peak", "loss_worst", "latency_worst", "jitter_worst",
    "maxunlag", "maxunlag_hits", "maxunlag_excess_worst",
    "shadow", "shadow_hits", "shadow_worst",
)
REWIND_FIELDS = ("attempts", "miss", "skip", "depth_worst", "dist_worst")

# Recorded rather than asserted -- see the module docstring.
OBSERVED_ONLY = (
    "clients", "maxunlag_hits", "maxunlag_excess_worst",
    "shadow_hits", "shadow_worst",
)


def parse(log_text: str, marker: str) -> list[dict[str, float]]:
    records = []
    for line in log_text.splitlines():
        head, sep, tail = line.partition(marker)
        if not sep:
            continue
        records.append({k: float(v) for k, v in FIELD.findall(tail)})
    return records


def _missing(records: list[dict[str, float]], expected: tuple[str, ...]) -> list[str]:
    seen = set().union(*records) if records else set()
    return [name for name in expected if name not in seen]


def summarise(log_text: str, *, expect_maxunlag_ms: float | None = None,
              tolerance_ms: float = 0.5) -> dict:
    """Evidence dict in the harness's usual `status`/`detail` shape."""
    net = parse(log_text, NET_MARKER)
    rewind = parse(log_text, REWIND_MARKER)
    evidence: dict = {
        "net_records": len(net),
        "rewind_records": len(rewind),
        "observed": {},
    }

    problems = []
    if not net:
        problems.append(
            f"no {NET_MARKER!r} records; ktp_profile_frame and ktp_profile_net "
            "must both be on and logging enabled")
    if not rewind:
        problems.append(f"no {REWIND_MARKER!r} records")

    missing_net = _missing(net, NET_FIELDS)
    if net and missing_net:
        problems.append("net record is missing " + ", ".join(missing_net))
    missing_rewind = _missing(rewind, REWIND_FIELDS)
    if rewind and missing_rewind:
        problems.append("rewind record is missing " + ", ".join(missing_rewind))
    evidence["missing_fields"] = missing_net + missing_rewind

    # The one net field that must track live server state. Without it a record
    # of constants would satisfy every other check here.
    if net and expect_maxunlag_ms is not None:
        matched = [r for r in net
                   if abs(r.get("maxunlag", -1.0) - expect_maxunlag_ms) <= tolerance_ms]
        evidence["maxunlag_ms_echoed"] = bool(matched)
        if not matched:
            seen = sorted({r.get("maxunlag") for r in net})
            problems.append(
                f"no net record reports maxunlag={expect_maxunlag_ms}ms; saw {seen}")

    for name in OBSERVED_ONLY:
        evidence["observed"][name] = max((r.get(name, 0.0) for r in net), default=0.0)
    evidence["observed"]["rewind_attempts"] = max(
        (r.get("attempts", 0.0) for r in rewind), default=0.0)

    evidence["status"] = "failed" if problems else "ok"
    evidence["detail"] = (
        "; ".join(problems) if problems else
        f"engine telemetry intact: {len(net)} net and {len(rewind)} rewind "
        "records carrying the full field set")
    return evidence
