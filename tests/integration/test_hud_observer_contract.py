"""KTPHudObserver — Tier 2 contract tests (DRAFT — first cut).

Asserts that KTPHudObserver.amxx, when loaded into the test serverfiles
tree alongside KTPMatchHandler test-mode + KTPWitness, POSTs the
expected event envelopes to the HUD ingest endpoint when KTPMatchHandler
fires `ktp_match_start` / `ktp_match_end` forwards.

The forwards themselves are already exercised by `test_match_flow_spine.py`
(witness.jsonl proof of dispatch). This file adds a SECOND downstream
consumer assertion: HUD Observer's hook handler ran AND the JSON envelope
it shipped matches the contract the data-server backend expects (see
`DoD-hud-observer/backend/src/handler/ingest.ts`).

## Why this layer of testing

Tier 1 (smoke) catches "plugin doesn't load."

Tier 2 spine + DODX-firing (KTPWitness as observer) catches "Tony's
forward refactor changed the dispatch path."

This file catches "Tony's forward refactor changed the args, AND HUD
Observer's hook handler still compiles + still POSTs, BUT the envelope
shape downstream consumers expected is wrong" — the silent-data-loss
class similar to the DODX `pdata` origin offset incident
(`feedback_dodx_pdata_origin.md`).

## First-cut scope (what's in / what's out)

IN:
  - Plugin-load assertion (`amx_ktp_versions` lists KTPHudObserver)
  - `ktp_match_start` envelope shape on advance_live → first-half boot
  - `ktp_match_end` envelope shape on end_match

OUT (deferred to follow-up PRs):
  - DODX forward consumption (dod_client_spawn / changeclass / death etc.)
  - Match-type variants (SCRIM / DRAFT / 12MAN)
  - Half-2 transition + score carryover envelope
  - Flag events (flags_init / flag_captured / flag_cap_started)
  - Roster dump events
  - Auth-rejected POST behavior (covered in test_fake_ingest.py
    mock-side; an end-to-end "wrong cvar key" test would need a separate
    fixture path)

The first-cut intent is to land the architecture (FakeIngest mock,
fixture wiring, version pinning, envelope shape assertions) so review
can focus on those load-bearing pieces. Test-surface expansion is
mechanical follow-up work once the shape is approved.

## Version pin

Pinned to a recent KTPHudObserver version. When the source PLUGIN_VERSION
bumps, this constant updates in lockstep (same convention as
test_match_flow_spine.py's EXPECTED_KTPMATCHHANDLER_VERSION). A drift
here means either:
  - Source bumped + binary not rebuilt → rebuild
  - Binary swapped on the runner without test pin update → bump pin
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from ._timing import scaled
from .fake_ingest import FakeIngest
from .match_flow import MatchDriver, MatchType


# Expected version: the HUD refresh step in tier2-integration.yml compiles the
# plugin from current source each run and exports its VERSION here, so the suite
# asserts loaded==built with no hardcoded pin to maintain. The literal is only a
# fallback for local/external-server runs where the refresh step didn't set it.
EXPECTED_KTPHUDOBSERVER_VERSION = os.environ.get(
    "KTP_EXPECTED_HUDOBSERVER_VERSION", "2.0.0"
)


# Plugin emits POSTs via amxxcurl async; round-trip is typically
# <100ms but a busy CI runner can stretch that. Match the shape of
# DISCORD_POST_TIMEOUT (5s) — same async curl path, same flake budget.
INGEST_POST_TIMEOUT = scaled(5.0)
INGEST_POLL_INTERVAL = 0.1


def _serverfiles() -> Path | None:
    p = os.environ.get("KTP_HLDS_SERVERFILES")
    return Path(p).resolve() if p else None


def _wait_for_ingest_event(
    ingest: FakeIngest,
    event_name: str,
    after_count: int = 0,
    timeout: float = INGEST_POST_TIMEOUT,
):
    """Poll the FakeIngest captured-list for the next post of the given
    event type after `after_count` total captures. Mirrors the shape of
    `wait_for_witness_event` in log_tail.py — caller baselines the count
    before the action that should produce the event, then waits for any
    new event of the expected type.

    Returns the captured post on success; raises AssertionError with the
    observed-event list on timeout (so a regression that POSTed a
    different event type is debuggable from the failure message).
    """
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for post in ingest.received[after_count:]:
            if post.event == event_name:
                return post
        time.sleep(INGEST_POLL_INTERVAL)
    seen = [p.event for p in ingest.received[after_count:]]
    raise AssertionError(
        f"timed out after {timeout}s waiting for ingest event "
        f"{event_name!r} (after_count={after_count}); "
        f"new events seen: {seen}"
    )


# ---------------------------------------------------------------------------
# Test 1 — plugin load + version pin
# ---------------------------------------------------------------------------

def test_hud_observer_loaded_and_version_pin(hlds):
    """`amx_ktp_versions` rcon lists KTPHudObserver at the pinned version.
    Same shape as test_match_flow_spine.py:test_1 — catches the source-
    bumped-but-binary-stale class on the HUD Observer side too.
    """
    output = hlds.rcon("amx_ktp_versions")
    # Plugin registers via `register_plugin("KTP HUD Observer", ...)` in
    # KTPHudObserver.sma — match on the human-readable name (with spaces),
    # mirroring the convention test_1_plugin_load_and_version_pin uses
    # for KTPMatchHandler.
    m = re.search(r"KTP HUD Observer\s+(\S+)", output)
    assert m, (
        f"KTPHudObserver not in `amx_ktp_versions` output. Either the plugin "
        f"didn't load or its register_plugin name doesn't match this pattern:\n{output}"
    )
    actual_version = m.group(1)
    assert actual_version == EXPECTED_KTPHUDOBSERVER_VERSION, (
        f"KTPHudObserver version drift: expected {EXPECTED_KTPHUDOBSERVER_VERSION}, "
        f"got {actual_version}. Either the source bumped without rebuild, "
        f"or this test pin is stale."
    )


# ---------------------------------------------------------------------------
# Test 2 — ktp_match_start envelope shape
# ---------------------------------------------------------------------------

def test_ktp_match_start_envelope_shape(hlds, fake_ingest):
    """When KTPMatchHandler fires `ktp_match_start`, KTPHudObserver's
    handler (KTPHudObserver.sma:360-406) POSTs an envelope to
    `dod_hud_url`. The envelope shape is the contract the data-server
    backend reads from (`recorder.startMatch` keys off
    match_id/map/match_type/half).

    Asserted envelope fields (per `post_event` in KTPHudObserver.sma:267):
      event           always "ktp_match_start"
      tick            float, plugin's get_gametime() at send (>= 0)
      plugin_sent_at  int, plugin's get_systime()*1000 (positive)
      match_id        the test match_id from setup_match
      map             the test map name
      match_type      0 for COMPETITIVE
      half            1 for first half

    NOT asserted (deferred to follow-up tests):
      - X-Server-Hostname header (set per-server in production; test
        env may not set hostname cvar so it's None or "unknown")
      - X-Plugin-Sent-At header (currently sent via curl headers but
        the value is the same as plugin_sent_at body field; covered
        by inspecting plugin_sent_at)
    """
    if _serverfiles() is None:
        pytest.skip(
            "test requires KTP_HLDS_SERVERFILES to apply the dod/server.cfg "
            "cvar overrides _hud_cvars_setup writes. External-server mode "
            "would need its own dod_hud_url override path; not yet wired."
        )

    driver = MatchDriver(hlds)
    match_id = driver.setup_match(MatchType.COMPETITIVE)
    driver.advance_pending()

    baseline = len(fake_ingest.received)
    driver.advance_live(half=1)

    post = _wait_for_ingest_event(
        fake_ingest, "ktp_match_start",
        after_count=baseline,
    )

    # Envelope-injection fields (post_event prepends these for any event
    # fired while g_matchActive=true)
    assert post.match_id == match_id, (
        f"envelope match_id mismatch: state {match_id!r} vs ingest {post.match_id!r}. "
        f"KTPHudObserver's g_matchId may not have been populated by the time "
        f"post_event ran — check the order of operations in ktp_match_start "
        f"handler (KTPHudObserver.sma:361-383)."
    )
    assert post.raw_body.get("map") in ("dod_anzio", "dod_flash"), (
        f"envelope map should be the active test map; got {post.raw_body.get('map')!r}"
    )
    assert post.raw_body.get("match_type") == int(MatchType.COMPETITIVE), (
        f"envelope match_type {post.raw_body.get('match_type')!r} != "
        f"COMPETITIVE ({int(MatchType.COMPETITIVE)})"
    )
    assert post.raw_body.get("half") == 1, (
        f"envelope half {post.raw_body.get('half')!r} != 1"
    )
    assert isinstance(post.tick, (int, float)) and post.tick >= 0, (
        f"envelope tick should be a non-negative float: {post.tick!r}"
    )
    assert isinstance(post.plugin_sent_at, int) and post.plugin_sent_at > 0, (
        f"envelope plugin_sent_at should be a positive int: {post.plugin_sent_at!r}"
    )


# ---------------------------------------------------------------------------
# Test 3 — ktp_match_end envelope shape
# ---------------------------------------------------------------------------

def test_ktp_match_end_envelope_shape(hlds, fake_ingest):
    """`ktp_match_end` fires `recorder.endMatch` on the backend, which
    closes events.jsonl. Plugin's handler (KTPHudObserver.sma:408-422)
    POSTs the envelope BEFORE clearing g_matchActive so match_id/map are
    still injected.

    Asserted envelope fields:
      event           "ktp_match_end"
      match_id        same as the test match_id
      allies_score    score we passed into end_match
      axis_score      score we passed into end_match
      tick            float, get_gametime() at send
      plugin_sent_at  positive int

    Specific score values: 3-1 (deliberately asymmetric so a swap bug
    would surface as a mismatched assertion). KTPMatchHandler's
    `end_match(score_team1, score_team2)` maps team1→Allies, team2→Axis
    in the COMPETITIVE first-half default sides.
    """
    if _serverfiles() is None:
        pytest.skip("test requires KTP_HLDS_SERVERFILES (see test_2 docstring)")

    driver = MatchDriver(hlds)
    match_id = driver.setup_match(MatchType.COMPETITIVE)
    driver.advance_pending()
    driver.advance_live(half=1)

    baseline = len(fake_ingest.received)
    driver.end_match(score_team1=3, score_team2=1)

    post = _wait_for_ingest_event(
        fake_ingest, "ktp_match_end",
        after_count=baseline,
    )

    assert post.match_id == match_id, (
        f"envelope match_id should still be set on match_end "
        f"(handler emits before clearing g_matchActive); "
        f"state {match_id!r} vs ingest {post.match_id!r}"
    )
    assert post.raw_body.get("allies_score") == 3, (
        f"envelope allies_score {post.raw_body.get('allies_score')!r} != 3"
    )
    assert post.raw_body.get("axis_score") == 1, (
        f"envelope axis_score {post.raw_body.get('axis_score')!r} != 1"
    )
    assert isinstance(post.tick, (int, float)) and post.tick >= 0
    assert isinstance(post.plugin_sent_at, int) and post.plugin_sent_at > 0
