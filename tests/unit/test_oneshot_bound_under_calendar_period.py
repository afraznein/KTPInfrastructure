"""A fixed-phase oneshot bounds its start UNDER its own trigger period.

`test_oneshot_start_timeouts.py` asks whether a oneshot is bounded at all. This
asks whether the bound is small enough to mean anything, which is a different
question and the one `ktp-reports.service` failed: `TimeoutStartSec=5400` on a
timer that fires every 900 s. One slow-database period then cost two 90-minute
wedges instead of one failed run -- 5400 is exactly 6x the period, so the kill
landed on a trigger minute and immediately started a successor that wedged the
same way. Six start timeouts between 2026-10-23 and 2026-10-25 came in three
such pairs, and the alert read them as three.

⚠️ Scoped to `OnCalendar=` on purpose. `OnUnitActiveSec=` has no fixed phase --
it measures from the last activation, so a long run does not line up with a
trigger and cannot alias. `ktp-render-banlist` (300 s bound, 60 s period) and
`support-poller` (45 s / 60 s) are that shape and are deliberately not failures
here; asserting over them would force a change to two units for a hazard they
do not have.

🔑 Fail-closed on a spec this does not understand. A parser that returns
"unknown" and skips reports a clean pass for a timer it never read, which is
the shape of every silent zero in this repo -- so an unparsed `OnCalendar=`
fails with the spec quoted rather than being ignored.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_PARTS = {".git", "node_modules", ".next", "bin", "obj", "__pycache__"}

UNITS = {"s": 1, "sec": 1, "m": 60, "min": 60, "h": 3600, "hr": 3600,
         "d": 86400, "w": 604800}


def directives(text):
    """-> {section: {key: [values]}}. systemd allows indentation and ';' comments."""
    out = {}
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section is None or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out.setdefault(section, {}).setdefault(key.strip(), []).append(value.strip())
    return out


def files(suffix):
    return sorted(
        p for p in ROOT.rglob("*" + suffix)
        if not SKIP_PARTS & set(p.relative_to(ROOT).parts)
    )


def timespan_seconds(value):
    """systemd time span -> seconds. None when the shape is not understood."""
    value = value.strip()
    if re.fullmatch(r"\d+", value):
        return int(value)
    total = 0
    parts = re.findall(r"(\d+)\s*([a-z]+)", value)
    if not parts:
        return None
    for num, unit in parts:
        if unit not in UNITS:
            return None
        total += int(num) * UNITS[unit]
    return total or None


def calendar_period(spec):
    """Shortest gap between two consecutive firings of one OnCalendar=, in seconds.

    Returns None only for a shape this does not model; callers must treat that
    as a failure, never as a pass.
    """
    spec = spec.strip()
    spec = re.sub(r"\s+(?:UTC|[A-Za-z]+/[A-Za-z_]+)$", "", spec)
    if spec in ("minutely",):
        return 60
    if spec in ("hourly",):
        return 3600
    if spec in ("daily",):
        return 86400
    if spec in ("weekly", "monthly", "yearly", "annually"):
        return 604800 if spec == "weekly" else 28 * 86400
    # *:0/10  -- every 10 minutes past every hour
    m = re.fullmatch(r"\*:0/(\d+)", spec)
    if m:
        return int(m.group(1)) * 60
    # *:40  -- one minute of every hour
    if re.fullmatch(r"\*:\d{1,2}", spec):
        return 3600
    # *-*-* *:MM[,MM...]:SS  -- a minute list in every hour
    m = re.fullmatch(r"\*-\*-\* \*:([\d,]+):\d{2}", spec)
    if m:
        mins = sorted(int(x) for x in m.group(1).split(","))
        gaps = [b - a for a, b in zip(mins, mins[1:])] + [60 - mins[-1] + mins[0]]
        return min(gaps) * 60
    # *-*-* HH:MM:SS  -- once a day
    if re.fullmatch(r"\*-\*-\* \d{2}:\d{2}:\d{2}", spec):
        return 86400
    # Dow *-*-* HH:MM:SS  -- once a week
    if re.fullmatch(r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) \*-\*-\* \d{2}:\d{2}:\d{2}", spec):
        return 604800
    return None


def oneshot_services():
    out = {}
    for path in files(".service"):
        text = path.read_text(encoding="utf-8")
        svc = directives(text).get("Service", {})
        if "oneshot" not in svc.get("Type", []):
            continue
        out[path.stem] = (path, svc)
    return out


def calendar_timers():
    out = {}
    for path in files(".timer"):
        timer = directives(path.read_text(encoding="utf-8")).get("Timer", {})
        specs = timer.get("OnCalendar", [])
        if specs:
            out.setdefault(path.stem, []).append((path, specs))
    return out


def pairs():
    """(unit name, service path, bound seconds, shortest period, spec) per pair."""
    services = oneshot_services()
    out = []
    for stem, entries in sorted(calendar_timers().items()):
        if stem not in services:
            continue
        spath, svc = services[stem]
        bound = svc.get("TimeoutStartSec", [])
        if not bound:
            continue  # test_oneshot_start_timeouts.py owns the unbounded case
        seconds = timespan_seconds(bound[0])
        for tpath, specs in entries:
            for spec in specs:
                out.append((stem, spath, bound[0], seconds, calendar_period(spec), spec))
    return out


def test_period_parser_models_the_shapes_in_this_repo():
    assert calendar_period("*-*-* *:04,19,34,49:00") == 900
    assert calendar_period("*-*-* *:10:00") == 3600
    assert calendar_period("*:0/10") == 600
    assert calendar_period("*:40") == 3600
    assert calendar_period("hourly") == 3600
    assert calendar_period("*-*-* 05:20:00 UTC") == 86400
    assert calendar_period("*-*-* 06:20:00 America/New_York") == 86400
    assert calendar_period("Mon *-*-* 14:00:00 UTC") == 604800
    # Fail-closed, not skip: an unmodelled shape must be reportable.
    assert calendar_period("*-*-* 1,2,3:00:00") is None
    assert calendar_period("qqz-no-such-calendar-4471") is None
    assert timespan_seconds("5min") == 300
    assert timespan_seconds("5400") == 5400
    assert timespan_seconds("qqz4471") is None


def test_sweep_is_not_vacuous():
    found = pairs()
    assert len(found) >= 8, [f[0] for f in found]
    # Both a sub-hourly and a daily period, or the parser is collapsing shapes.
    periods = {f[4] for f in found}
    assert 900 in periods, sorted(p for p in periods if p)
    assert 86400 in periods, sorted(p for p in periods if p)
    # ktp-reports is the unit this guard was written for: if it stops appearing,
    # the sweep has lost its way rather than the repo having improved.
    assert any(f[0] == "ktp-reports" for f in found), [f[0] for f in found]
    # The OnUnitActiveSec units must be OUT of scope, not silently passing.
    assert not any(f[0] in ("ktp-render-banlist", "support-poller") for f in found)


def test_every_calendar_spec_is_understood():
    unknown = [
        "%s (%s): OnCalendar=%s" % (stem, spath.relative_to(ROOT).as_posix(), spec)
        for stem, spath, _raw, _sec, period, spec in pairs() if period is None
    ]
    assert not unknown, (
        "calendar_period() does not model these, so they were never checked: "
        + "; ".join(unknown)
    )


def test_every_bound_is_understood():
    unknown = [
        "%s: TimeoutStartSec=%s" % (stem, raw)
        for stem, _spath, raw, sec, _period, _spec in pairs() if sec is None
    ]
    assert not unknown, "timespan_seconds() does not model these: " + "; ".join(unknown)


def test_bound_is_under_the_trigger_period():
    offenders = []
    for stem, _spath, raw, sec, period, spec in pairs():
        if sec is None or period is None:
            continue  # named by the two tests above
        if sec >= period:
            offenders.append(
                "%s: TimeoutStartSec=%s (%ds) >= %ds between firings of "
                "OnCalendar=%s%s" % (
                    stem, raw, sec, period, spec,
                    " -- and an exact multiple, so the kill lands on a trigger"
                    if period and sec % period == 0 else "",
                )
            )
    assert not offenders, (
        "a start timeout at or above the trigger period lets one slow run "
        "swallow its successors: " + "; ".join(offenders)
    )
