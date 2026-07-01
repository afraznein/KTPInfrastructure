"""KTPHudObserver — Tier 2 flag-capture EMISSION / SUPPRESSION contract.

Drives `dod_control_point_captured` at the real compiled KTPHudObserver.amxx via
the KTPWitness dispatch rcon and asserts the JSON it POSTs to the FakeIngest
endpoint. Companion to test_hud_observer_contract.py (which covers the
match-lifecycle envelopes).

## Scope — read this before adding assertions

This validates the EMISSION + SUPPRESSION wiring of the cap path:
  - dod_control_point_captured(allies) arms a deferred one-shot that POSTs
    `flag_captured` ~0.5s later (DEFER_DELAY) — so the test waits for the POST,
    it does NOT assume synchronous emission.
  - round-restart (new_owner=neutral) and same-owner repeats are SUPPRESSED.
  - a full capout POSTs a `player_stats_summary` carrying `capout_team`.

This deliberately does NOT assert per-player cap CREDIT (obj_score / caps).
The plugin only credits when `is_user_connected(id) && get_user_team(id) ==
capping_team`, and this harness cannot connect an on-team player — `addbot`
never spawns onto a team in extension mode and CreateFakeClient is unavailable
(see test_dodx_forward_firing.py BOT_AI_REQUIRED_REASON). With no connected
player, dod_score_event bails at is_user_connected, so the captor batch stays
empty and `captor_ids` is `[]` here by construction. Per-player credit is
covered downstream by the backend event-stream invariant gate
(DoD-hud-observer backend/src/invariants/eventInvariants.ts — cap-credit-objscore)
on real captures. What THIS test adds that the invariant gate structurally
cannot: if `flag_captured` stops being emitted entirely, the invariant gate goes
silent (no caps seen → no violation); this test fails loudly.

To upgrade this to a real credit test, add a dodx test-only native that marks a
fake client connected + on a team, then assert obj_score/caps + non-empty
captor_ids here.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Optional

import pytest

from ._timing import scaled
from .match_flow import MatchDriver, MatchType

# Owner ints passed to amx_witness_dispatch_cp_captured (dodx team space).
NEUTRAL, ALLIES, AXIS = 0, 1, 2

# Plugin POSTs via amxxcurl async after a 0.5s deferred one-shot (DEFER_DELAY);
# 5s positive budget mirrors the contract test. The negative (suppression)
# settle must comfortably exceed DEFER_DELAY so a deferred emit would have landed.
INGEST_POST_TIMEOUT = scaled(5.0)
INGEST_SETTLE = scaled(2.0)
INGEST_POLL_INTERVAL = 0.1


def _serverfiles() -> Path | None:
    p = os.environ.get("KTP_HLDS_SERVERFILES")
    return Path(p).resolve() if p else None


def _wait_for_ingest_event(
    ingest,
    event_name: str,
    *,
    after_count: int = 0,
    timeout: float = INGEST_POST_TIMEOUT,
    where: Optional[Callable[[dict], bool]] = None,
):
    """Poll FakeIngest for the next POST of event_name (after after_count) that
    also satisfies the optional `where(raw_body)` predicate."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for post in ingest.received[after_count:]:
            if post.event == event_name and (where is None or where(post.raw_body)):
                return post
        time.sleep(INGEST_POLL_INTERVAL)
    seen = [p.event for p in ingest.received[after_count:]]
    raise AssertionError(
        f"timed out after {timeout:.1f}s waiting for ingest {event_name!r}; saw {seen}"
    )


def _assert_no_ingest_event(
    ingest,
    event_name: str,
    *,
    after_count: int = 0,
    settle: float = INGEST_SETTLE,
    where: Optional[Callable[[dict], bool]] = None,
):
    """Wait `settle` seconds and assert NO matching POST appeared (used to prove
    suppression — settle > DEFER_DELAY so a deferred emit would have fired)."""
    deadline = time.monotonic() + settle
    while time.monotonic() < deadline:
        for post in ingest.received[after_count:]:
            if post.event == event_name and (where is None or where(post.raw_body)):
                raise AssertionError(
                    f"expected NO {event_name!r} but plugin POSTed one: {post.raw_body}"
                )
        time.sleep(INGEST_POLL_INTERVAL)


def _go_live(hlds) -> MatchDriver:
    """Drive KTPMatchHandler to a live first half so KTPHudObserver is in normal
    match state with freshly-initialised (neutral) flags."""
    driver = MatchDriver(hlds)
    driver.setup_match(MatchType.COMPETITIVE)
    driver.advance_pending()
    driver.advance_live(half=1)
    return driver


def _capture(hlds, cp: int, new_owner: int, old_owner: int = NEUTRAL) -> None:
    hlds.rcon(f"amx_witness_dispatch_cp_captured {cp} {new_owner} {old_owner}")


def test_real_capture_emits_flag_captured(hlds, fake_ingest):
    """A real (neutral→allies) capture POSTs a deferred `flag_captured` with the
    correct owner + flag_id. captor_ids is [] here (no connected players)."""
    if _serverfiles() is None:
        pytest.skip("requires KTP_HLDS_SERVERFILES (dod/server.cfg cvar overrides)")

    _go_live(hlds)
    baseline = len(fake_ingest.received)
    _capture(hlds, 0, ALLIES)

    post = _wait_for_ingest_event(
        fake_ingest, "flag_captured", after_count=baseline,
        where=lambda b: b.get("flag_id") == 0,
    )
    assert post.raw_body.get("new_owner") == "allies"
    assert post.raw_body.get("flag_id") == 0
    # Empty by construction — see module docstring. Asserted explicitly so a
    # future on-team-player capability flips this to a real captor assertion.
    assert post.raw_body.get("captor_ids") == []


def test_round_restart_neutral_is_suppressed(hlds, fake_ingest):
    """new_owner=neutral (the engine's round-restart cascade) must NOT emit a
    flag_captured — it's a phantom, not a real cap."""
    if _serverfiles() is None:
        pytest.skip("requires KTP_HLDS_SERVERFILES (dod/server.cfg cvar overrides)")

    _go_live(hlds)
    # First take the flag to allies (so the next event is a genuine owner change).
    _capture(hlds, 0, ALLIES)
    _wait_for_ingest_event(fake_ingest, "flag_captured", where=lambda b: b.get("flag_id") == 0)

    baseline = len(fake_ingest.received)
    _capture(hlds, 0, NEUTRAL, old_owner=ALLIES)
    _assert_no_ingest_event(
        fake_ingest, "flag_captured", after_count=baseline,
        where=lambda b: b.get("flag_id") == 0,
    )


def test_same_owner_repeat_is_suppressed(hlds, fake_ingest):
    """A duplicate capture for the team that already owns the flag must NOT
    re-emit (DODX's owner-change guard doesn't always hold; the plugin dedupes)."""
    if _serverfiles() is None:
        pytest.skip("requires KTP_HLDS_SERVERFILES (dod/server.cfg cvar overrides)")

    _go_live(hlds)
    _capture(hlds, 0, ALLIES)
    _wait_for_ingest_event(fake_ingest, "flag_captured", where=lambda b: b.get("flag_id") == 0)

    baseline = len(fake_ingest.received)
    _capture(hlds, 0, ALLIES, old_owner=ALLIES)
    _assert_no_ingest_event(
        fake_ingest, "flag_captured", after_count=baseline,
        where=lambda b: b.get("flag_id") == 0,
    )


def test_capout_emits_stats_summary(hlds, fake_ingest):
    """Capturing every flag for one team is a capout (the only reliable round-end
    on cap maps); the plugin POSTs a player_stats_summary carrying capout_team."""
    if _serverfiles() is None:
        pytest.skip("requires KTP_HLDS_SERVERFILES (dod/server.cfg cvar overrides)")

    _go_live(hlds)
    # Learn the flag count from the flags_init the plugin posts at match start.
    flags_init = _wait_for_ingest_event(fake_ingest, "flags_init")
    flag_count = len(flags_init.raw_body.get("flags") or [])
    assert flag_count > 0, "flags_init carried no flags — cannot drive a capout"

    baseline = len(fake_ingest.received)
    for cp in range(flag_count):
        _capture(hlds, cp, ALLIES)

    post = _wait_for_ingest_event(
        fake_ingest, "player_stats_summary", after_count=baseline,
        where=lambda b: b.get("capout_team") == "allies",
    )
    assert post.raw_body.get("capout_team") == "allies"
