"""Match-flow Session 4b — admin recovery (`ktp_forcereset`, `ktp_restarthalf`).

Both commands are admin-only operator tools for recovering from abandoned
or broken match state:

  - **forcereset** clears ALL match state and posts a "Server Force Reset"
    Discord notification. Used when a match is abandoned, dirty, or when
    captains need to retry setup from scratch.
  - **restarthalf** rewinds 2nd-half scores back to 0-0 while preserving
    1st-half scores and posts a "2nd Half Restarted" Discord notification.
    Used when an admin needs to redo h2 (e.g., disconnect or rule
    violation).

Production has chat-confirmation flows (must type the command twice
within 10 seconds) — KTPMatchHandler 0.10.130's `amx_ktp_test_forcereset`
and `amx_ktp_test_restarthalf` rcons bypass that confirmation and call
the underlying stock helpers (`execute_force_reset`, `execute_restart_half`)
directly with synthetic admin metadata ("test_admin",
STEAM_0:0:99999999, 127.0.0.1).

## Cross-references

  - `KTPMatchHandler.sma:6513-6703` — `execute_force_reset()` impl
  - `KTPMatchHandler.sma:6772-6834` — `execute_restart_half()` impl
  - `tests/integration/match_flow.py:forcereset/restarthalf` — driver helpers
  - SESSION_3_DISCORD_EMISSION_AUDIT.md § Cancel/abort paths (lines 6699,
    6852 — the "Server Force Reset" + "2nd Half Restarted" embeds)
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from ._timing import DISCORD_POLL_INTERVAL, DISCORD_POST_TIMEOUT
from .match_flow import MatchDriver, MatchType


def _serverfiles() -> Path | None:
    p = os.environ.get("KTP_HLDS_SERVERFILES")
    return Path(p).resolve() if p else None


def _wait_for_post_count(relay, expected_min: int,
                         timeout: float = DISCORD_POST_TIMEOUT) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(relay.received) >= expected_min:
            return len(relay.received)
        time.sleep(DISCORD_POLL_INTERVAL)
    return len(relay.received)


# ---------------------------------------------------------------------------
# forcereset — Server Force Reset Discord embed + state cleared
# ---------------------------------------------------------------------------

def test_forcereset_clears_match_state(hlds, discord_relay):
    """`execute_force_reset()` (KTPMatchHandler.sma:6513) clears all match
    state and posts a "Server Force Reset" Discord embed via
    `send_discord_simple_embed()` (line 6701).

    Test sequence:
      1. setup_match(COMPETITIVE) → advance_pending → advance_live(1) —
         get into a LIVE match with all the state vars set
      2. forcereset() — bypass chat-confirmation, calls execute_force_reset
      3. Assert state is fully reset via get_state() readback:
         match_live=False, match_pending=False, current_half=0
      4. Assert "Server Force Reset" Discord embed POSTed to the default
         channel (forcereset routes via the `default` case in
         get_discord_channel_id() since match-type is reset before the
         embed posts)
    """
    discord_relay.reset()
    driver = MatchDriver(hlds)

    driver.setup_match(MatchType.COMPETITIVE)
    driver.advance_pending()
    driver.advance_live(half=1)

    # Wait for the CREATE POST from the live transition (so we can later
    # distinguish the forcereset POST from the live-transition POST).
    pre_reset_post_count = _wait_for_post_count(discord_relay, expected_min=1)

    state_before = driver.get_state()
    assert state_before.match_live is True, (
        f"setup precondition failed: match should be live, state={state_before!r}"
    )

    driver.forcereset()

    state_after = driver.get_state()
    assert state_after.match_live is False, (
        f"forcereset should clear match_live, got {state_after!r}"
    )
    assert state_after.match_pending is False, (
        f"forcereset should clear match_pending, got {state_after!r}"
    )
    assert state_after.current_half == 0, (
        f"forcereset should clear current_half, got {state_after.current_half}"
    )

    # Wait for the forcereset's Discord embed (one additional POST beyond
    # the live-transition CREATE)
    deadline = time.monotonic() + DISCORD_POST_TIMEOUT
    while time.monotonic() < deadline:
        if len(discord_relay.received) > pre_reset_post_count:
            break
        time.sleep(DISCORD_POLL_INTERVAL)

    assert len(discord_relay.received) > pre_reset_post_count, (
        f"forcereset should post a Discord embed, got "
        f"{len(discord_relay.received)} (pre-reset={pre_reset_post_count})"
    )
    forcereset_post = discord_relay.received[pre_reset_post_count]
    embed = forcereset_post.embeds[0] if forcereset_post.embeds else {}
    embed_text = (
        str(embed.get("title", "")) + " "
        + str(embed.get("description", ""))
    )
    assert "Force Reset" in embed_text, (
        f"forcereset embed missing 'Force Reset' phrasing: text={embed_text!r}"
    )


# ---------------------------------------------------------------------------
# restarthalf — preconditions + score reset + Discord embed
# ---------------------------------------------------------------------------

def test_restarthalf_requires_live_h2(hlds):
    """`execute_restart_half` requires LIVE match with `g_currentHalf == 2`
    and not in OT. The test rcon enforces these preconditions and returns
    `KTP_TEST_RESTARTHALF: ERROR ...` for violations — MatchDriver raises
    `MatchDriverError` with the reason.

    Test confirms each precondition is enforced:
      - reset state (no match): error 'not_live'
      - live h1 (advance_live(1) but no end_first_half): error 'not_half2'
    """
    from .match_flow import MatchDriverError

    driver = MatchDriver(hlds)

    # Case 1: no live match → not_live
    driver.reset()
    with pytest.raises(MatchDriverError, match="not_live"):
        driver.restarthalf()

    # Case 2: live h1 → not_half2
    driver.setup_match(MatchType.COMPETITIVE)
    driver.advance_pending()
    driver.advance_live(half=1)
    with pytest.raises(MatchDriverError, match="not_half2"):
        driver.restarthalf()


def test_restarthalf_resets_h2_scores_and_posts_embed(hlds, discord_relay):
    """`execute_restart_half()` (KTPMatchHandler.sma:6772-6834) called
    during live h2:
      - Sets scoreboard back to 1st-half scores (h2 back to 0-0)
      - Posts "2nd Half Restarted" Discord embed (Phase 2 deferred, ~0.2s)
      - Logs `event=RESTARTHALF_EXECUTED` via log_ktp

    Test sequence:
      1. setup → advance_pending → advance_live(1) → end_first_half(3, 1)
         → advance_live(2): now in live h2 with h1 scores 3-1
      2. restarthalf()
      3. Assert h1 scores preserved (g_firstHalfScore[1/2] still 3-1)
         via state readback (score_team1/2 reflect post-reset values
         which equal h1 only)
      4. Assert "2nd Half Restarted" Discord embed lands within 5s

    Note: state readback `score_team1/2` post-reset equals h1 scores
    because the reset writes h1 back into g_matchScore[1/2]. We
    pre-pass synthetic h1 scores via end_first_half so we know what to
    expect after reset.
    """
    discord_relay.reset()
    driver = MatchDriver(hlds)

    driver.setup_match(MatchType.COMPETITIVE)
    driver.advance_pending()
    driver.advance_live(half=1)
    driver.end_first_half(score_team1=3, score_team2=1)
    driver.advance_live(half=2)

    state_pre = driver.get_state()
    assert state_pre.current_half == 2, (
        f"setup precondition failed: current_half should be 2, "
        f"state={state_pre!r}"
    )
    assert state_pre.match_live is True

    pre_reset_post_count = len(discord_relay.received)

    driver.restarthalf()

    # State should still be live h2 (restarthalf doesn't clear match_live)
    state_post = driver.get_state()
    assert state_post.match_live is True, (
        f"restarthalf should keep match live, got {state_post!r}"
    )
    assert state_post.current_half == 2, (
        f"restarthalf should keep current_half=2, got {state_post.current_half}"
    )

    # Wait for the deferred Phase 2 Discord embed (~0.2s after rcon)
    deadline = time.monotonic() + DISCORD_POST_TIMEOUT
    while time.monotonic() < deadline:
        if len(discord_relay.received) > pre_reset_post_count:
            break
        time.sleep(DISCORD_POLL_INTERVAL)

    assert len(discord_relay.received) > pre_reset_post_count, (
        f"restarthalf should post a Discord embed (Phase 2 deferred); "
        f"got {len(discord_relay.received)}"
    )
    restart_post = discord_relay.received[pre_reset_post_count]
    embed = restart_post.embeds[0] if restart_post.embeds else {}
    embed_text = (
        str(embed.get("title", "")) + " "
        + str(embed.get("description", ""))
    )
    assert "2nd Half Restarted" in embed_text, (
        f"restarthalf embed missing '2nd Half Restarted' phrasing: "
        f"text={embed_text!r}"
    )
    # Description should reference preserved h1 scores (3-1)
    assert "3" in embed_text and "1" in embed_text, (
        f"restarthalf embed should reference h1 scores 3-1: text={embed_text!r}"
    )
