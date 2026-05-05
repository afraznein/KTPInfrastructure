"""Match-flow Session 3 — test 9: Discord embed POSTs during match-flow events.

Asserts that KTPMatchHandler emits the expected Discord embed via the
relay path when the match-flow state machine transitions through key
events. The fixture machinery in `conftest.py` (`discord_relay` +
`_discord_ini_setup`) writes a test `discord.ini` pointing at a loopback
FakeRelay before hlds boots; this file's tests drive the state machine
via MatchDriver and assert against `discord_relay.received`.

## Why these tests are skip-marked today

KTPMatchHandler reads `discord.ini` ONCE at `plugin_init` and caches the
parsed values into globals (`g_disableDiscord` etc., per
`KTPMatchHandler.sma:6070,6089`). The fixture writes the test discord.ini
before hlds boots, so plugin_init does see the test config — that part
works. The blocker is something different:

KTPMatchHandler's emission paths for Discord embeds during match-flow
events are still being audited as part of Session 3 fill-out. Specifically:

  - `ktp_match_start` may or may not directly POST to Discord; the
    notification could be coming from a forward consumer (KTPHLTVRecorder
    posts at match start in some configurations), from the tech-pause
    handler, or from a delayed task. Need to grep through the full
    Discord-emission surface and pin which event MUST produce a POST.

  - Some emission paths gate on additional cvars or ini keys (e.g.
    `discord_channel_id_12man`, `discord_channel_id_draft`). The current
    fixture writes only the base `discord_channel_id` which may not
    cover every match type.

  - The deferred-Discord-fwd pattern (`task_deferred_discord_fwd` per
    memory) means a POST may not appear until ~200ms after the rcon
    that triggered it. Tests need a polling loop with a sane timeout,
    not a synchronous assertion.

Rather than ship a flaky test that asserts the wrong thing, this file
lands the FIXTURE WIRING + the TEST BODIES (so the contract is clear)
but skip-marks each test with the specific blocker. Removing the skip
mark is a one-line change once the auditing work in Session 3 fill-out
identifies the exact emission path being asserted.

## Cross-references

  - `conftest.py:discord_relay` / `:_discord_ini_setup` — fixture impls
  - `tests/integration/fake_relay.py` — FakeRelay class
  - `tests/integration/test_fake_relay.py` — mock-side smoke (11 PASS)
  - `KTPMatchHandler.sma:3386` — discord.ini read site
  - `KTPMatchHandler.sma:6070,6089` — Discord-enable globals
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from .fake_relay import FakeRelay
from .match_flow import MatchDriver, MatchType


SKIP_REASON = (
    "Session 3 fill-out: KTPMatchHandler's Discord-emission surface still "
    "being audited — see file docstring + DODX_FORWARD_FIRING_DESIGN.md "
    "siblings for the pattern. Remove this skip when the emission path "
    "for the asserted event is confirmed."
)

# How long to poll for relay POSTs after a state-machine transition.
# KTPMatchHandler uses task_deferred_discord_fwd for some posts (fires
# ~200ms post-trigger); 5s is generous for any single event's POST.
DISCORD_POST_TIMEOUT = 5.0
DISCORD_POLL_INTERVAL = 0.1


def _wait_for_post_count(relay: FakeRelay, expected_min: int,
                         timeout: float = DISCORD_POST_TIMEOUT) -> int:
    """Poll until `relay.received` has at least `expected_min` posts, or
    timeout. Returns the actual count seen (may be > expected_min if a
    flurry of posts arrives). Lets tests assert on the timeout path with
    `actual = _wait_for_post_count(...); assert actual >= N`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(relay.received) >= expected_min:
            return len(relay.received)
        time.sleep(DISCORD_POLL_INTERVAL)
    return len(relay.received)


# ---------------------------------------------------------------------------
# Test 9 — Discord embed POSTs during ktp_match_start
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason=SKIP_REASON)
def test_9_discord_embed_posts_on_match_start(hlds, discord_relay):
    """KTPMatchHandler should POST a Discord embed when the match goes
    LIVE (ktp_match_start fires). Asserts:

      - At least 1 POST arrived at the loopback relay within 5s of
        `amx_ktp_test_advance_live`
      - The auth header was correct (would have been a 401 otherwise,
        captured in `relay.auth_failures` rather than `relay.received`)
      - The channel_id matches what's in the test discord.ini
      - The embed has *some* identifying content (title or description
        non-empty) — exact text format is operator-tunable so we don't
        pin specific words
    """
    discord_relay.reset()  # clear any pre-test posts

    driver = MatchDriver(hlds)
    match_id = driver.setup_match(MatchType.COMPETITIVE)
    driver.advance_pending()
    driver.advance_live(half=1)

    actual = _wait_for_post_count(discord_relay, expected_min=1)
    assert actual >= 1, (
        f"expected ≥1 Discord POST within {DISCORD_POST_TIMEOUT}s of "
        f"advance_live, got {actual}. relay.auth_failures="
        f"{len(discord_relay.auth_failures)} (auth mismatch would land here)"
    )

    post = discord_relay.received[0]
    assert post.auth_ok is True, (
        "Discord POST had bad X-Relay-Auth — fixture wrote the wrong secret "
        "into discord.ini, or KTPMatchHandler is reading a stale config"
    )
    assert post.channel_id == "1234567890123456789", (
        f"channel_id mismatch: discord.ini wrote 1234567890123456789, "
        f"plugin POSTed {post.channel_id!r}"
    )
    assert post.embeds, "POST had no embeds[]"
    embed = post.embeds[0]
    has_content = bool(embed.get("title") or embed.get("description")
                       or embed.get("fields"))
    assert has_content, f"embed had no title/description/fields: {embed!r}"


# ---------------------------------------------------------------------------
# Test 9b — Discord embed POSTs on match end (paired-event sanity)
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason=SKIP_REASON)
def test_9b_discord_embed_posts_on_match_end(hlds, discord_relay):
    """Match-end is a known Discord-emission point (per memory + the
    KTPMatchHandler match-end-digest BackgroundService work in
    KTPAntiCheat 0.4.3). Drives setup → live → end via test-mode rcons,
    polls the relay for the close-paired POST.
    """
    discord_relay.reset()

    driver = MatchDriver(hlds)
    driver.setup_match(MatchType.COMPETITIVE)
    driver.advance_pending()
    driver.advance_live(half=1)
    # Fake a 100-50 score; plugin's match-end embed should reference it
    driver.end_match(score_team1=100, score_team2=50)

    # Plugin posts both match-start AND match-end embeds in this flow,
    # so we expect ≥2 (start + end). Relaxed lower bound.
    actual = _wait_for_post_count(discord_relay, expected_min=2)
    assert actual >= 2, (
        f"expected ≥2 Discord POSTs (start + end) within "
        f"{DISCORD_POST_TIMEOUT}s, got {actual}"
    )

    end_posts = [p for p in discord_relay.received
                 if any("100" in str(e) or "50" in str(e)
                        for e in p.embeds)]
    assert end_posts, (
        f"none of {actual} POSTs referenced the match-end score 100-50 — "
        f"either match-end doesn't post a Discord embed, or it doesn't "
        f"include the score, or the score format differs from raw integer."
    )


# ---------------------------------------------------------------------------
# Test 9c — Auth mismatch should land in auth_failures, not received
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason=SKIP_REASON + " (negative-path test; deferred until 9 + 9b green)")
def test_9c_bad_auth_routes_to_auth_failures(hlds, discord_relay):
    """Negative-path sanity: if KTPMatchHandler somehow reads the WRONG
    secret (e.g., production secret while pointed at test relay), every
    POST should land in `relay.auth_failures` not `relay.received`.

    This test deliberately writes a temporary discord.ini with the wrong
    secret + drives a match-start. Asserts `auth_failures` accumulates,
    `received` stays empty. Ensures the test infrastructure correctly
    distinguishes auth-rejected from happy-path posts.
    """
    sf = os.environ.get("KTP_HLDS_SERVERFILES")
    if not sf:
        pytest.skip("test 9c needs writable serverfiles to swap discord.ini")

    config_path = Path(sf) / "dod" / "addons" / "ktpamx" / "configs" / "discord.ini"
    original = config_path.read_bytes()
    bad_config = (
        f"discord_relay_url={discord_relay.reply_url}\n"
        "discord_channel_id=1234567890123456789\n"
        "discord_auth_secret=this-is-the-wrong-secret-on-purpose\n"
    )

    discord_relay.reset()
    try:
        config_path.write_bytes(bad_config.encode("utf-8"))
        # Force plugin_init re-fire to pick up the bad config —
        # changelevel is the production-supported way; an
        # `amx_ktp_test_reload_discord` rcon would be cleaner if we ever
        # add it.
        hlds.rcon("changelevel dod_anzio")
        time.sleep(15.0)  # let map reload + plugin_init re-fire

        driver = MatchDriver(hlds)
        driver.setup_match(MatchType.COMPETITIVE)
        driver.advance_pending()
        driver.advance_live(half=1)

        time.sleep(DISCORD_POST_TIMEOUT)  # let any deferred POST drain

        assert len(discord_relay.received) == 0, (
            "wrong-secret POSTs landed in `received` — fixture is leaking "
            "auth-failed posts into the happy-path bucket"
        )
        assert len(discord_relay.auth_failures) >= 1, (
            "wrong-secret POSTs vanished entirely — KTPMatchHandler may "
            "have refused to send (e.g., empty discord_channel_id), or "
            "plugin_init didn't re-read the swapped config"
        )
    finally:
        config_path.write_bytes(original)
