"""Shared timeout constants for the Tier 2 integration suite.

All test files import from here rather than redefining inline
`DISCORD_POST_TIMEOUT = 5.0` etc. The constants are scaled at import
time by `KTP_TEST_TIMEOUT_MULTIPLIER` (env var, default 1.0) so a CI
runner with slower I/O can dial all timeouts up uniformly without each
test file needing per-call multiplier args.

Why a multiplier vs per-test override:
  - The flake source is consistent across the suite (curl async round-trip,
    log file flush latency, hlds rcon command processing) — every test's
    polling loop is hitting the same kind of variance. One knob covers all.
  - Per-test overrides would multiply the maintenance surface (each new
    test author has to remember to plumb timeout args through). Module-
    level constants keep the call sites uniform.
  - 1.0 = local dev (sub-second polling, deterministic timing). 2.0-3.0 =
    busy CI runner. >3.0 implies an actual hang, not slow I/O — investigate.

Default values match the constants previously inlined across test files
(verified 2026-05-05 via grep). Changing a default here changes ALL
tests' tolerances; do that only when a class of regressions establishes
a new floor.
"""
from __future__ import annotations

import os
import warnings


def _multiplier() -> float:
    """Read KTP_TEST_TIMEOUT_MULTIPLIER from env. Clamp to [0.1, 100.0] —
    sub-0.1 makes everything timeout instantly (debugging artifact); >100x
    is a misconfig (typo or CI runner is so slow the test surface is
    pointless).

    Emits a warning on bad input or out-of-range values so a typo in repo
    settings (e.g., `vars.KTP_TEST_TIMEOUT_MULTIPLIER` set to "3,0" with a
    comma instead of a dot) doesn't silently fall back to 1.0 and produce
    confusing flakes. The warning shows in pytest's stderr output.
    """
    raw = os.environ.get("KTP_TEST_TIMEOUT_MULTIPLIER", "1.0")
    try:
        m = float(raw)
    except (TypeError, ValueError):
        warnings.warn(
            f"KTP_TEST_TIMEOUT_MULTIPLIER={raw!r} is not a valid float; "
            "defaulting to 1.0",
            stacklevel=2,
        )
        return 1.0
    if m < 0.1 or m > 100.0:
        warnings.warn(
            f"KTP_TEST_TIMEOUT_MULTIPLIER={raw!r} is out of range [0.1, 100.0]; "
            "defaulting to 1.0",
            stacklevel=2,
        )
        return 1.0
    return m


_M = _multiplier()

# Polling cadence — used uniformly by every poll-until-deadline loop.
# 0.1s gives us up to 10 sample-points per second of timeout, which is
# fine-grained enough for tests asserting on Discord-relay round-trips
# (~50-200ms typical) without burning CPU on tight loops.
#
# NOT scaled by the multiplier — a slow runner benefits from a LONGER
# DEADLINE, not a slower poll cadence. Scaling the poll cadence would
# reduce sample resolution on high multipliers (3.0× would give 0.3s
# polls = only 16 samples per 5s timeout instead of 50). Cadence stays
# fixed; only the deadlines below scale.
POLL_INTERVAL = 0.1

# Discord-relay POST round-trip timeout. Production uses
# task_deferred_discord_fwd at +0.2s after the rcon, plus curl's async
# callback latency. 5s is generous for any single POST.
DISCORD_POST_TIMEOUT = 5.0 * _M

# Same as POLL_INTERVAL — kept distinct so a future test class needing a
# tighter poll cadence specifically for Discord can override here without
# touching the rest of the suite. Also unscaled (see POLL_INTERVAL note).
DISCORD_POLL_INTERVAL = POLL_INTERVAL

# Log-tail polling timeout for `wait_for_log_event` / `wait_for_log_substring`.
# AMXX log_amx writes to L*.log on a per-line flush cadence; 5s catches
# any line emitted in response to an rcon, including deferred tasks
# scheduled at +0.2s.
LOG_POLL_TIMEOUT = 5.0 * _M

# Witness-event timeout for `wait_for_witness_event`. Forward dispatches
# from the test rcons fire on the next frame; 10s tolerates a slow CI
# runner where a single frame might span ~1s under load.
WITNESS_TIMEOUT = 10.0 * _M

# Hot-path forward timeout — for tests that wait on bot-driven events
# (combat, grenade-throw) where the timing is bot-AI-dependent. Mostly
# unused after Phase 3b switched to deterministic-dispatch primitives;
# kept for the bot-stress harness path if it's ever wired.
WITNESS_HOT_PATH_TIMEOUT = 60.0 * _M


def scaled(seconds: float) -> float:
    """Scale an arbitrary timeout by the current multiplier. Use sparingly
    — prefer the named constants above. Useful for one-off `time.sleep`
    calls that need the multiplier applied (e.g., "wait the full
    DISCORD_POST_TIMEOUT for any spurious POST that shouldn't fire" in
    the SCRIM no-Discord test)."""
    return seconds * _M
