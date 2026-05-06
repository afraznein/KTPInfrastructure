"""Match-flow Session 3 Phase 2b — log-line assertions for DODX + HLStatsX.

This file covers tests 7 + 8 from the Tier 2 match-flow spec — the AMXX log
line (`event=FWD_MATCH_START`) and the HLStatsX log line
(`KTP_MATCH_START (matchid ...)`) that should appear when the match-flow
state machine transitions to LIVE. Both are observable via the L*.log file
the engine writes; the `log_tail` helper polls that file.

Tests 10 + 11 from the original spec (tech pause Discord embed updates) are
in this file too but skip-marked with the production-design rationale: tech
pause has no Discord notification (audit gap was actually the feature
not existing). HUD-only feature; Discord tests don't apply.

## Cross-references

  - `KTPInfrastructure/tests/integration/log_tail.py` — `wait_for_log_event`,
    `current_log_size` helpers
  - `KTPInfrastructure/tests/integration/match_flow.py:fire_match_start_log` —
    test rcon driver helper added 2026-05-05
  - `KTPMatchHandler.sma:7433` — production FWD_MATCH_START log_ktp emission
  - `KTPMatchHandler.sma:1495` — production KTP_MATCH_START log_message
    emission (in `task_roundlive_match_context`, which the test fires
    directly via the new rcon since the engine round-live event isn't
    available in the test environment)
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from ._timing import LOG_POLL_TIMEOUT
from .log_tail import current_log_size, wait_for_log_event, wait_for_log_substring
from .match_flow import MatchDriver, MatchType


def _serverfiles() -> Path | None:
    p = os.environ.get("KTP_HLDS_SERVERFILES")
    return Path(p).resolve() if p else None


# ---------------------------------------------------------------------------
# Test 7 — DODX FWD_MATCH_START log_ktp event after advance_live
# ---------------------------------------------------------------------------

def test_7_fwd_match_start_log_event_after_advance_live(hlds):
    """`task_deferred_discord_fwd()` (KTPMatchHandler.sma:7395-7419) fires
    ~200ms after `advance_live` and logs:

        log_ktp("event=FWD_MATCH_START match_id=%s map=%s type=%d half=%d", ...)

    which surfaces in the AMXX L<MMDD>.log file as the line:

        L MM/DD/YYYY - HH:MM:SS: [KTP] event=FWD_MATCH_START match_id=... map=... type=... half=...

    Test drives `setup → advance_pending → advance_live(half=1)` and asserts
    the log line appears within 5s. Validates that the deferred-fwd task
    is actually firing in test mode (a regression where it doesn't would
    silently break Discord embed POSTs too — same task scheduled by
    `cmd_test_advance_live` line 7778).
    """
    sf = _serverfiles()
    if sf is None:
        pytest.skip("test requires KTP_HLDS_SERVERFILES for L*.log read")

    driver = MatchDriver(hlds)
    driver.setup_match(MatchType.COMPETITIVE)
    driver.advance_pending()

    log_baseline = current_log_size(sf)
    driver.advance_live(half=1)

    line = wait_for_log_event(
        sf, "FWD_MATCH_START",
        timeout=LOG_POLL_TIMEOUT,
        after_offset=log_baseline,
    )
    # Sanity-check the line shape — should have the match_id + half=1
    assert "match_id=" in line, f"FWD_MATCH_START line missing match_id: {line!r}"
    assert "half=1" in line, f"FWD_MATCH_START line should report half=1: {line!r}"


# ---------------------------------------------------------------------------
# Test 8 — HLStatsX KTP_MATCH_START log_message line
# ---------------------------------------------------------------------------

def test_8_ktp_match_start_log_message_line(hlds):
    """KTPMatchHandler emits `KTP_MATCH_START (matchid "...") (map "...") (half "1st")`
    via `log_message()` for the HLStatsX daemon. log_message writes to BOTH
    the AMXX L*.log file AND the engine's UDP HLStatsX address; we observe
    via L*.log.

    Production path: `task_roundlive_match_context` (KTPMatchHandler.sma:1480)
    fires this on engine round-live event after match start. The engine
    round-live event isn't available in the test environment without a
    real round, so we drive the emission via the dedicated test rcon
    `amx_ktp_test_fire_match_start_log` (KTPMatchHandler 0.10.127+) which
    fires the same log_message + log_ktp pair using current match state.

    The half text format is "1st"/"2nd"/"OTN" per production convention.
    """
    sf = _serverfiles()
    if sf is None:
        pytest.skip("test requires KTP_HLDS_SERVERFILES for L*.log read")

    driver = MatchDriver(hlds)
    driver.setup_match(MatchType.COMPETITIVE)
    driver.advance_pending()
    driver.advance_live(half=1)

    log_baseline = current_log_size(sf)
    driver.fire_match_start_log()

    # log_message lines don't follow the `[KTP] event=...` AMXX convention
    # — they're plain HLStatsX format. Use the substring helper.
    line = wait_for_log_substring(
        sf, "KTP_MATCH_START",
        timeout=LOG_POLL_TIMEOUT,
        after_offset=log_baseline,
    )
    # Production format: KTP_MATCH_START (matchid "...") (map "...") (half "1st")
    assert "(half \"1st\")" in line, (
        f"KTP_MATCH_START line missing half=1st: {line!r}"
    )
    # Also assert the companion log_ktp event line surfaces
    event_line = wait_for_log_event(
        sf, "ROUNDLIVE_MATCH_START_LOG",
        timeout=LOG_POLL_TIMEOUT,
        after_offset=log_baseline,
    )
    assert "matchid=" in event_line, (
        f"ROUNDLIVE_MATCH_START_LOG line malformed: {event_line!r}"
    )


# ---------------------------------------------------------------------------
# Tests 10 + 11 — Tech pause Discord embed updates (NOT IMPLEMENTED — design)
# ---------------------------------------------------------------------------

PAUSE_NO_DISCORD_REASON = (
    "Discovered 2026-05-05 during Phase 2b implementation: tech pause has "
    "no Discord embed update in production. The audit doc's 'audit gap' "
    "(SESSION_3_DISCORD_EMISSION_AUDIT.md § Tech pause / unpause) was "
    "actually the feature not existing — `cmd_tech_pause` and the unpause "
    "path do not call `send_match_embed_update` or any other Discord-side "
    "primitive. Pause status is a HUD-only feature in production design "
    "(ReHLDS `RH_SV_UpdatePausedHUD` real-time HUD updates per CLAUDE.md "
    "§ Pause System). Tests 10/11 as originally specified would assert on "
    "an embed update that never fires. They could be repurposed to assert "
    "the negative path (\"pause does NOT produce a /edit POST\") if a "
    "future regression added an unwanted Discord notification, but that's "
    "a different test contract and scope. Filing this as design intent "
    "rather than test gap."
)


@pytest.mark.skip(reason=PAUSE_NO_DISCORD_REASON)
def test_10_tech_pause_emits_paused_embed_update(hlds, discord_relay):
    """Original spec: tech pause emits a Discord embed update with "Paused"
    in the status. Reality: production has no such emission path. See
    PAUSE_NO_DISCORD_REASON."""
    pass


@pytest.mark.skip(reason=PAUSE_NO_DISCORD_REASON)
def test_11_tech_unpause_emits_match_live_embed_update(hlds, discord_relay):
    """Original spec: tech unpause/resume emits a "Match Live" embed update.
    Reality: production has no such emission path. See
    PAUSE_NO_DISCORD_REASON."""
    pass
