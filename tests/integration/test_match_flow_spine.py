"""Match-flow integration tests — the spine.

Four tests covering the four state-machine transitions match-flow has to
produce correctly (anything more is a downstream concern of Sessions 3-5):

  Test 1 — plugin load + version pin (rcon `amx_ktp_versions`)
  Test 3 — `amx_ktp_test_setup_match` enters PRESTART with synthetic captains
  Test 4 — `amx_ktp_test_advance_pending` fires PENDING_BEGIN log line
  Test 6 — `amx_ktp_test_advance_live` fires `ktp_match_start` forward
            (witness.jsonl proof) + sets matchLive

(Tests 2 + 5 from the original v1 list are chat-layer tests we dropped
when the design pivoted away from fakemeta; see KTPMatchHandler/CHANGELOG
0.10.122 and memory `extension_mode_no_fakemeta.md`.)

Tests assume the conftest `hlds` fixture has booted hlds with the test-
mode KTPMatchHandler.amxx + KTPWitness.amxx loaded. See README.md for
environment setup; tests skip cleanly if neither boot mode is available.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from ._timing import LOG_POLL_TIMEOUT, WITNESS_TIMEOUT
from .log_tail import (
    current_log_size,
    wait_for_log_event,
    wait_for_witness_event,
    witness_count,
)
from .match_flow import MatchDriver, MatchType


# Pinned version: KTPMatchHandler 0.10.122 added the test-mode build flag;
# 0.10.123 routed test rcons through the production deferred-fwd path. When
# the source PLUGIN_VERSION bumps, this test pin updates in lockstep
# (memory `feedback_commit_hygiene.md`).
EXPECTED_KTPMATCHHANDLER_VERSION = "0.10.123"


def _serverfiles() -> Path | None:
    """Resolve the serverfiles dir for log/witness tail. Tests skip the
    file-system assertions if it's not set (rcon-only assertions still run)."""
    p = os.environ.get("KTP_HLDS_SERVERFILES")
    return Path(p).resolve() if p else None


# ---------------------------------------------------------------------------
# Test 1 — plugin load + version pin
# ---------------------------------------------------------------------------

def test_1_plugin_load_and_version_pin(hlds):
    """`amx_ktp_versions` rcon (KTPAMXX 2.7.15+) lists every plugin that
    registers via `ktp_version_reporter.inc`. Smoke that KTPMatchHandler is
    loaded AND its CHANGELOG version matches what's deployed.

    Catches the 0.10.121-vs-0.10.122 confusion class: source bumped but
    test-mode build never ran, so the deployed binary is stale.
    """
    output = hlds.rcon("amx_ktp_versions")
    # Output shape (per memory `amxx_rcon_output_format.md` + verified against
    # KTPAMXX 2.7.13 against KTPMatchHandler 0.10.123):
    #   `KTP Match Handler                0.10.123       9f573af-dirty  2026-05-05T05:43Z`
    # The plugin registers via `register_plugin("KTP Match Handler", ...)` and
    # `KTP_RegisterVersion(PLUGIN_NAME, ...)` — both use the human-readable name
    # with spaces. Older versions of this regex looked for `KTPMatchHandler`
    # (no spaces) and silently miss-matched.
    m = re.search(r"KTP Match Handler\s+(\S+)", output)
    assert m, (
        f"KTPMatchHandler not in `amx_ktp_versions` output. Either the plugin "
        f"didn't load or it doesn't register via ktp_version_reporter.inc:\n{output}"
    )
    actual_version = m.group(1)
    assert actual_version == EXPECTED_KTPMATCHHANDLER_VERSION, (
        f"KTPMatchHandler version drift: expected {EXPECTED_KTPMATCHHANDLER_VERSION}, "
        f"got {actual_version}. Either CHANGELOG.md head bumped without rebuild, "
        f"or this test pin is stale."
    )


# ---------------------------------------------------------------------------
# Test 3 — setup_match enters PRESTART
# ---------------------------------------------------------------------------

def test_3_setup_match_enters_prestart(hlds):
    """`amx_ktp_test_setup_match 0` sets PRESTART with synthetic captains
    + production-shape match_id (`<systime>-TEST`). Asserts both the
    state-readback rcon (in-memory state) AND a TEST_SETUP log line
    (write-through to the audit log).
    """
    sf = _serverfiles()
    log_baseline = current_log_size(sf) if sf else 0

    driver = MatchDriver(hlds)
    match_id = driver.setup_match(MatchType.COMPETITIVE)

    # Match ID shape: `<systime>-TEST` per the test-mode setup_match impl.
    assert re.fullmatch(r"\d{10}-TEST", match_id), (
        f"setup_match returned non-canonical match_id: {match_id!r}. "
        f"Expected `<10-digit-systime>-TEST`."
    )

    state = driver.get_state()
    assert state.match_type == MatchType.COMPETITIVE
    assert state.match_id == match_id
    assert state.match_live is False, "matchLive should be 0 in PRESTART"
    assert state.match_pending is False, "matchPending should be 0 in PRESTART (only true after advance_pending)"
    assert state.captain1.startswith("test_captain_allies|STEAM_"), (
        f"captain1 should be the synthetic placeholder; got {state.captain1!r}"
    )
    assert state.captain2.startswith("test_captain_axis|STEAM_"), (
        f"captain2 should be the synthetic placeholder; got {state.captain2!r}"
    )

    # Log-side assertion — only if we have file-system access. The TEST_SETUP
    # event is emitted by cmd_test_setup_match BEFORE returning, so it lands
    # before the rcon round-trip ends.
    if sf is not None:
        line = wait_for_log_event(sf, "TEST_SETUP", timeout=LOG_POLL_TIMEOUT, after_offset=log_baseline)
        assert f"match_id={match_id}" in line, (
            f"TEST_SETUP log line should reference the same match_id {match_id!r}: {line!r}"
        )
        assert "matchType=0" in line


# ---------------------------------------------------------------------------
# Test 4 — advance_pending fires PENDING_BEGIN
# ---------------------------------------------------------------------------

def test_4_advance_pending_enters_pending(hlds):
    """`amx_ktp_test_advance_pending` calls the production
    `enter_pending_phase()` helper, which emits the PENDING_BEGIN log line
    that production code emits on .confirm-completion. Setup → advance:
    state.match_pending should flip 0 → 1.
    """
    sf = _serverfiles()

    driver = MatchDriver(hlds)
    driver.setup_match(MatchType.COMPETITIVE)

    log_baseline = current_log_size(sf) if sf else 0

    driver.advance_pending()

    state = driver.get_state()
    assert state.match_pending is True, (
        f"matchPending should be 1 after advance_pending; got state={state!r}"
    )
    assert state.match_live is False, "matchLive should still be 0 in PENDING (only true after advance_live)"

    if sf is not None:
        # Two log lines emitted: TEST_ADVANCE_PENDING from the test rcon
        # itself, then PENDING_BEGIN from enter_pending_phase. Asserting on
        # PENDING_BEGIN — that's the production-shaped event downstream
        # plugins / log scrapers gate on.
        wait_for_log_event(sf, "PENDING_BEGIN", timeout=LOG_POLL_TIMEOUT, after_offset=log_baseline)


# ---------------------------------------------------------------------------
# Test 6 — advance_live fires ktp_match_start forward
# ---------------------------------------------------------------------------

def test_6_advance_live_fires_match_start_forward(hlds):
    """`amx_ktp_test_advance_live <half>` fires the `ktp_match_start`
    multi-forward via `ExecuteForward(g_fwdMatchStart, ...)` — the same
    dispatch path KTPHLTVRecorder consumes in production. KTPWitness.amxx
    records the fire to `addons/ktpamx/logs/witness.jsonl` as proof that
    at least one consumer's handler ran.

    This is the load-bearing assertion of the entire spine: state-machine
    transitions are observable via state-readback, but FORWARD FIRING is
    only observable via a witness. Tests 1/3/4 prove the state machine
    moves; this proves cross-plugin dispatch reaches consumers.
    """
    sf = _serverfiles()
    if sf is None:
        pytest.skip(
            "Test 6 requires KTP_HLDS_SERVERFILES to read witness.jsonl. "
            "(Sessions 3+ may add a docker-exec read path so external-server "
            "mode can run this test too.)"
        )

    driver = MatchDriver(hlds)
    match_id = driver.setup_match(MatchType.COMPETITIVE)
    driver.advance_pending()

    witness_baseline = witness_count(sf)
    log_baseline = current_log_size(sf)

    driver.advance_live(half=1)

    # State-machine assertion
    state = driver.get_state()
    assert state.match_live is True, f"matchLive should be 1 after advance_live; state={state!r}"
    assert state.current_half == 1, f"currentHalf should be 1; state={state!r}"
    assert state.match_pending is False, "matchPending should clear when going LIVE"

    # Forward-fire assertion via witness JSONL
    row = wait_for_witness_event(sf, "ktp_match_start", timeout=WITNESS_TIMEOUT, after_count=witness_baseline)
    assert row["matchId"] == match_id, (
        f"witness ktp_match_start matchId mismatch: state {match_id!r} vs witness {row.get('matchId')!r}"
    )
    assert row["matchType"] == int(MatchType.COMPETITIVE), (
        f"witness matchType {row.get('matchType')!r} != COMPETITIVE (0)"
    )
    assert row["half"] == 1, f"witness half {row.get('half')!r} != 1"

    # Log-side double-check — TEST_ADVANCE_LIVE event from the test rcon.
    wait_for_log_event(sf, "TEST_ADVANCE_LIVE", timeout=LOG_POLL_TIMEOUT, after_offset=log_baseline)
