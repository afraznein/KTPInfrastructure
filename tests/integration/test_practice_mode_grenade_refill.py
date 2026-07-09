"""KTPPracticeMode grenade auto-refill contract tests.

Regression net for the refill state machine (TODO.md "KTPPracticeMode —
grenade auto-refill regression" follow-up). The production handler
(`dod_grenade_explosion` in KTPPracticeMode.sma) has two gates before the
refill natives run:

    gate 1: g_bPracticeMode          (practice mode active)
    gate 2: is_user_connected(id) && is_user_alive(id)

Coverage matrix vs the four failure classes in TODO.md:

    class 1 (DODX dispatch bug)      — covered indirectly: the dispatch
        primitive path is pinned by test_dodx_forward_firing.py's
        grenade-explosion test; the natural engine chain has no bot-free
        driver.
    class 2 (player state desync)    — COVERED here: dispatch against a
        disconnected slot with practice mode forced on -> entry diagnostic
        shows connected=0 and no refill attempt.
    class 3 (refill native failing)  — NOT coverable without a connected
        player (the natives never run when gate 2 fails); the production
        1.4.3+ failure-only `refill FAILED` log is the organic-repro net.
    class 4 (game-DLL/client desync) — NOT coverable in Tier 2 (needs a
        real client).

Test environment requires:
    - KTPPracticeMode.amxx TEST-MODE build (1.4.4+, KTP_TEST_MODE=1):
      adds `amx_ktp_prac_test_enable <0|1>` rcon + an entry-state
      diagnostic in dod_grenade_explosion (both compiled out of the
      production binary).
    - dodx_ktp_i386.so with dodx_test_dispatch_grenade_explosion
      (KTPAMXX 2.7.19+ tree; the native itself shipped earlier).
    - KTPWitness 1.5.0+ for the dispatch rcon.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from ._timing import WITNESS_TIMEOUT, scaled
from .log_tail import current_log_size, wait_for_log_substring

EXPECTED_KTPPRACTICEMODE_VERSION = "1.4.6"

# Grenade ids from KTPPracticeMode.sma / dodx weapon table
DODW_HANDGRENADE = 13


def _serverfiles() -> Path | None:
    p = os.environ.get("KTP_HLDS_SERVERFILES")
    return Path(p).resolve() if p else None


@pytest.fixture()
def practice_mode_off_after(hlds):
    """Always force the practice flag back off so a failed test can't leak
    practice mode into subsequent match-flow tests."""
    yield
    hlds.rcon("amx_ktp_prac_test_enable 0")


def test_practice_mode_loaded_and_version_pin(hlds):
    """`amx_ktp_versions` lists KTP Practice Mode at the pinned version —
    catches the stale-binary class (source bumped, runner tree not
    restaged). Same shape as the KTPMatchHandler/HudObserver pins.
    """
    output = hlds.rcon("amx_ktp_versions")
    m = re.search(r"KTP Practice Mode\s+(\S+)", output)
    assert m, (
        f"KTPPracticeMode not in `amx_ktp_versions` output. Either the plugin "
        f"didn't load or its register_plugin name changed:\n{output}"
    )
    assert m.group(1) == EXPECTED_KTPPRACTICEMODE_VERSION, (
        f"KTPPracticeMode version drift: expected "
        f"{EXPECTED_KTPPRACTICEMODE_VERSION}, got {m.group(1)}. Restage the "
        f"test-mode build on the runner or update this pin."
    )


def test_refill_gate_practice_mode_off(hlds, practice_mode_off_after):
    """With practice mode OFF (default), a grenade explosion reaches the
    handler but stops at gate 1: entry diagnostic logs practice=0 and no
    `refill FAILED` line appears (the natives never run).
    """
    sf = _serverfiles()
    if sf is None:
        pytest.skip("test requires KTP_HLDS_SERVERFILES for AMXX log read")

    SLOT = 3
    hlds.rcon("amx_ktp_prac_test_enable 0")

    baseline = current_log_size(sf)
    hlds.rcon(f"amx_witness_dispatch_grenade {SLOT} 100.0 200.0 50.0 {DODW_HANDGRENADE}")

    line = wait_for_log_substring(
        sf, "TEST explosion_entry:",
        timeout=WITNESS_TIMEOUT, after_offset=baseline,
    )
    assert f"id={SLOT}" in line and "practice=0" in line, (
        f"entry diagnostic shape unexpected: {line!r}"
    )
    # Gate 1 short-circuits before the refill natives — a FAILED line here
    # would mean the practice gate regressed.
    with pytest.raises(TimeoutError):
        wait_for_log_substring(
            sf, "refill FAILED", timeout=scaled(2.0), after_offset=baseline,
        )


def test_refill_gate_disconnected_slot(hlds, practice_mode_off_after):
    """Failure class 2 (state desync): practice mode ON but the exploding
    slot is not a connected player -> gate 2 skips the refill. Entry
    diagnostic shows practice=1 connected=0, and no `refill FAILED` line
    (the natives are never attempted, which is the designed skip path —
    NOT a native failure).
    """
    sf = _serverfiles()
    if sf is None:
        pytest.skip("test requires KTP_HLDS_SERVERFILES for AMXX log read")

    SLOT = 3  # no client connected in the Tier 2 environment
    hlds.rcon("amx_ktp_prac_test_enable 1")

    baseline = current_log_size(sf)
    hlds.rcon(f"amx_witness_dispatch_grenade {SLOT} 100.0 200.0 50.0 {DODW_HANDGRENADE}")

    line = wait_for_log_substring(
        sf, "TEST explosion_entry:",
        timeout=WITNESS_TIMEOUT, after_offset=baseline,
    )
    assert f"id={SLOT}" in line and "practice=1" in line and "connected=0" in line, (
        f"entry diagnostic shape unexpected: {line!r}"
    )
    with pytest.raises(TimeoutError):
        wait_for_log_substring(
            sf, "refill FAILED", timeout=scaled(2.0), after_offset=baseline,
        )
