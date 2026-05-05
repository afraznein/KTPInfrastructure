"""Match-flow Session 3 Phase 2c — KTPAntiCheat API match-end POST.

Test 17 from the Tier 2 match-flow spec: KTPMatchHandler's match-end
flow calls `send_ac_match_end(matchId)` (KTPMatchHandler.sma:2327-2351)
which POSTs to `<api_base_url>/api/match/end` with payload
`{"matchId": "...", "serverEndpoint": "..."}` and `X-Server-Secret`
header. FakeRelay's `/api/match/end` route (added 2026-05-05) captures
these into `received_ac_match_end`.

Distinct from the Discord-relay POSTs (test 9b's `/edit`) — different
endpoint, different auth header (`X-Server-Secret` vs `X-Relay-Auth`),
different payload shape (no embeds, just match_id + server_endpoint).

## Cross-references

  - `KTPMatchHandler.sma:2327-2351` — `send_ac_match_end()` impl
  - `KTPMatchHandler.sma:2219-2273` — `load_ac_config()` (reads ac.ini)
  - `tests/integration/conftest.py:_ac_ini_setup` — writes test ac.ini
    pointing at FakeRelay
  - `tests/integration/fake_relay.py:CapturedAcPost` — wire shape
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from ._timing import POLL_INTERVAL as AC_POLL_INTERVAL
from ._timing import scaled
from .match_flow import MatchDriver, MatchType


def _serverfiles() -> Path | None:
    p = os.environ.get("KTP_HLDS_SERVERFILES")
    return Path(p).resolve() if p else None


# ---------------------------------------------------------------------------
# Test 17 — AC match/end API POST after end_match
# ---------------------------------------------------------------------------

# Same shape as DISCORD_POST_TIMEOUT but kept distinct so a future test
# class needing a tighter AC-specific timeout can override here.
AC_POST_TIMEOUT = scaled(5.0)


def test_17_ac_match_end_post_after_end_match(hlds, discord_relay):
    """KTPMatchHandler's match-end fires `send_ac_match_end(g_matchId)`
    which POSTs to `<api_base_url>/api/match/end` with:

        Headers: X-Server-Secret: <server_secret from ac.ini>
                 Content-Type: application/json
        Body:    {"matchId": "<id>", "serverEndpoint": "<endpoint>"}

    Test sequence:
      1. setup_match → advance_pending → advance_live(half=1) — establishes
         match_id in plugin globals.
      2. end_match(s1, s2) — production match-end calls send_ac_match_end
         (line 785). The test rcon `cmd_test_end_match` matches production
         shape since 0.10.124 (calls dodx_flush_all_stats + the same
         post-end cleanup), but it doesn't currently call
         send_ac_match_end. Verify whether it does in the deployed
         test-mode build.
      3. Wait up to 5s for `received_ac_match_end` to populate.
      4. Assert payload shape: matchId matches the setup-assigned id,
         serverEndpoint is non-empty (any real value works).

    NOTE: If `cmd_test_end_match` (KTPMatchHandler.sma:7791-7835) doesn't
    invoke `send_ac_match_end`, this test will need a separate test rcon
    or extension. The audit doc § Phase 2c notes this is the case in
    0.10.123, requiring either:
      (a) Adding `send_ac_match_end(g_matchId);` to `cmd_test_end_match`,
          mirroring production line 785's behavior, OR
      (b) Adding a dedicated `amx_ktp_test_send_ac_match_end` rcon.

    Going with (a) — same approach as 0.10.124's `dodx_flush_all_stats()`
    addition (mirror production at match-end). Bumps KTPMatchHandler
    minor version since it adds an outbound HTTP POST in the test-mode
    end-match path.
    """
    sf = _serverfiles()
    if sf is None:
        pytest.skip("test requires KTP_HLDS_SERVERFILES for ac.ini fixture")

    discord_relay.reset()
    driver = MatchDriver(hlds)

    match_id = driver.setup_match(MatchType.COMPETITIVE)
    driver.advance_pending()
    driver.advance_live(half=1)

    # Drive end-match — production fires send_ac_match_end as part of the
    # cmd_end_match flow at KTPMatchHandler.sma:785.
    driver.end_match(score_team1=11, score_team2=7)

    # Poll for the AC POST to land. Curl is async (aslib via amxxcurl);
    # 5s is generous for a loopback round-trip.
    deadline = time.monotonic() + AC_POST_TIMEOUT
    while time.monotonic() < deadline:
        if discord_relay.received_ac_match_end:
            break
        time.sleep(AC_POLL_INTERVAL)

    assert len(discord_relay.received_ac_match_end) >= 1, (
        f"expected ≥1 /api/match/end POST after end_match; got "
        f"{len(discord_relay.received_ac_match_end)}. "
        f"ac_auth_failures={len(discord_relay.ac_auth_failures)} "
        f"(auth mismatch — wrong server_secret in ac.ini, or plugin "
        f"didn't read the test config)"
    )

    ac_post = discord_relay.received_ac_match_end[0]
    assert ac_post.auth_ok is True, "/api/match/end POST had bad X-Server-Secret"
    assert ac_post.match_id == match_id, (
        f"matchId mismatch: setup assigned {match_id!r}, AC POST sent {ac_post.match_id!r}"
    )
    assert ac_post.server_endpoint, (
        f"serverEndpoint must be non-empty: {ac_post!r}"
    )
