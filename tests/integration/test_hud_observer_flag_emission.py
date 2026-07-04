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
    on cap maps); the plugin POSTs a player_stats_summary carrying capout_team.

    ## Why this drives the flags ONE AT A TIME, waiting for each emit

    Do NOT collapse this into `for cp in range(n): cap(cp)`. A tight loop of the
    five dispatch rcons drops the fifth flag_captured and the capout entirely
    (this was the original failure: "4 flag_captured, no capout"). The cause is
    NOT in the HUD plugin or this test — it's a KTPAMXX-core interaction proven
    by local repro (see the PR thread / the KTPAMXX SP-forward-dedup issue):

      Each cap arms a per-CP deferred one-shot via
      `set_task(DEFER_DELAY, "deferred_emit_cap", TASK_ID_DEFER_BASE+cp)`
      (KTPHudObserver.sma:1631). KTPAMXX's set_task registers the callback with
      registerSPForwardByName, and the KTP extension-mode dedup
      (CForward.cpp:553-563) hands two tasks with the SAME callback name a
      SHARED SP-forward handle whenever the second is armed while the first is
      still pending. CTask::clear() unconditionally unregisterSPForwards that
      handle on completion (CTask.cpp:58-62) with no refcount
      (CForward.cpp:689-706) — so when an earlier per-CP task fires+clears, it
      frees the shared forward out from under the LAST still-pending task, whose
      fire then silently no-ops (CSPForward::execute bails on isFree,
      CForward.cpp:290). Middle tasks survive because the next set_task recycles
      the freed slot; the final task in an overlap chain has no successor to
      recycle it. Result: the capout-carrying (last) flag's deferred emit is
      lost. Confirmed by a minimal probe: 5 overlapping same-callback set_tasks
      drop the 5th; 5 DISTINCT callbacks all fire.

    Real play never triggers this — captures land seconds apart (verified against
    live match 1782677636-NY1, dod_anzio, 2026-06-28: flags 0-4
    [LAUNDRY/BRIDGE/STREET/PLAZA/HILL] all start NEUTRAL and flip seconds apart;
    the allies capout summary lands in the SAME tick as the final HILL flip).
    So we serialize: dispatch a flag, then WAIT for its deferred flag_captured
    POST before dispatching the next. That guarantees each per-CP task has fired
    AND cleared before the next arms — no two ever overlap, so no shared-forward
    free. This mirrors production timing and is deterministic (no reliance on a
    fixed sleep exceeding DEFER_DELAY). If KTPAMXX core gets a refcounted
    unregister, the tight loop would also pass and this serialization becomes
    belt-and-suspenders.

    Per-player CREDIT is still NOT asserted (captor_ids stays [] clientless — see
    the module docstring). This asserts the capout DETECTION + summary-emission
    wiring on the real all-neutral anzio layout, derived from flags_init rather
    than assumed, so a map/CP-ordering change can't silently invalidate it.
    """
    if _serverfiles() is None:
        pytest.skip("requires KTP_HLDS_SERVERFILES (dod/server.cfg cvar overrides)")

    _go_live(hlds)
    # Learn the flag count + authored owners from the flags_init the plugin posts
    # at match start (it re-emits on ktp_match_start, KTPHudObserver.sma:561). The
    # capout verdict reads g_flag_owner, seeded straight from these owners
    # (do_flags_init, KTPHudObserver.sma:1477-1478) — so derive expectations from
    # this, never from a hardcoded all-neutral assumption.
    flags_init = _wait_for_ingest_event(fake_ingest, "flags_init")
    flags = flags_init.raw_body.get("flags") or []
    flag_count = len(flags)
    assert flag_count > 0, "flags_init carried no flags — cannot drive a capout"

    owners = {f.get("flag_id"): f.get("owner") for f in flags}
    # A flag emits a deferred flag_captured only if driving it to allies is an
    # owner CHANGE — an already-allies flag is suppressed by the same-owner guard
    # (KTPHudObserver.sma:1580-1583). On dod_anzio all five start neutral.
    expect_emit = {fid for fid, own in owners.items() if own != "allies"}
    assert expect_emit, (
        f"every flag already allies-owned at match start ({owners}) — no "
        f"owner-change dispatch to carry the is_capout recompute; this map "
        f"cannot drive a clean allies capout via dispatch (needs a "
        f"dodx_test_set_cp_owner native to force neutral first)"
    )

    baseline = len(fake_ingest.received)
    # Serialize: cap a flag, then wait for ITS deferred flag_captured before the
    # next, so no two per-CP deferred one-shots are ever pending simultaneously
    # (see the docstring — that overlap is what drops the final flag). Keyed by
    # flag_id, so DODX CP-index reordering (KTPAMXX issue #5) can't mismatch.
    # If flag_captured stops emitting, this fails loudly — the structural value
    # the module docstring claims (lines 26-28).
    for cp in range(flag_count):
        _capture(hlds, cp, ALLIES)
        if cp in expect_emit:
            _wait_for_ingest_event(
                fake_ingest, "flag_captured", after_count=baseline,
                where=lambda b, _cp=cp: b.get("flag_id") == _cp
                                        and b.get("new_owner") == "allies",
            )

    # After every flag is allies-owned, the final owner-change flip's deferred
    # task computes is_capout true and POSTs the round-end summary carrying
    # capout_team=allies (KTPHudObserver.sma:1613-1619, 1661-1666).
    post = _wait_for_ingest_event(
        fake_ingest, "player_stats_summary", after_count=baseline,
        where=lambda b: b.get("capout_team") == "allies",
    )
    assert post.raw_body.get("capout_team") == "allies"
    assert post.raw_body.get("reason") == "round_end"
    # players[] is empty by construction (no connected on-team players); the
    # summary POSTs unconditionally regardless (KTPHudObserver.sma:1119-1120).
    assert isinstance(post.raw_body.get("players"), list)
