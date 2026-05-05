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


# Wire format reference (KTPMatchHandler 0.10.123 + FakeRelay 2026-05-05):
#
# CREATE: send_match_embed_create() → POST {relay}/reply with `channelId` +
#   `embeds`. FakeRelay returns `{"id":"fake-relay-msg-N","ok":true,...}` and
#   KTPMatchHandler captures the `id` into `g_discordMatchMsgId` via
#   `discord_embed_callback` (ktp_matchhandler_discord.inc:625-655).
#
# UPDATE: send_match_embed_update() → POST {relay-with-/reply-replaced-by-
#   /edit} with `channelId` + `messageId` + `embeds`. URL surgery happens
#   in ktp_matchhandler_discord.inc:781-784. Lands in FakeRelay's
#   `received_edits` list, not `received`.

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

    Path confirmed by SESSION_3_DISCORD_EMISSION_AUDIT.md:
    `task_deferred_discord_fwd()` at `KTPMatchHandler.sma:7395-7419` fires
    ~200ms after match-live for COMPETITIVE/KTP_OT, calls
    `send_match_embed_create()` (line 7414) which POSTs the initial
    persistent match embed. Fixture writes `discord_channel_id` (base
    key, used by COMPETITIVE per `get_discord_channel_id()` switch);
    auth_secret matches `discord_relay.expected_secret`.

    Test still skips cleanly when no env vars are set (fixture chain
    `hlds → _discord_ini_setup → _serverfiles_path()` returns None and
    hlds skips).
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

def test_9b_discord_embed_posts_on_match_end(hlds, discord_relay):
    """Match-end fires a Discord embed UPDATE (POST /edit) referencing the
    final score. Production path: `KTPMatchHandler.sma:776` →
    `send_match_embed_update("MATCH COMPLETE - Final: %d-%d - %s")`. The
    test-mode `cmd_test_end_match` mirrors that emission since 0.10.123.

    Wire-shape:
      - advance_live → POST /reply (CREATE) → received[0]
      - end_match    → POST /edit  (UPDATE) → received_edits[0]

    Asserts both halves of the create+update pair, plus that the update
    references the score the test passed in.
    """
    discord_relay.reset()

    driver = MatchDriver(hlds)
    driver.setup_match(MatchType.COMPETITIVE)
    driver.advance_pending()
    driver.advance_live(half=1)

    # Wait for CREATE POST + the async msg-ID capture round-trip:
    #   1. Plugin POSTs /reply (curl async)
    #   2. FakeRelay records into received[] + responds with `{"id":"..."}`
    #   3. Curl response callback `discord_embed_callback` runs on next frame
    #      → parses id, sets `g_discordMatchMsgId`, mirrors to localinfo
    #      `_ktp_dmsg`. Until step 3 completes, send_match_embed_update
    #      no-ops with `event=DISCORD_EDIT_SKIP reason=no_msg_id`.
    actual_creates = _wait_for_post_count(discord_relay, expected_min=1)
    assert actual_creates >= 1, (
        f"CREATE POST never arrived; got {actual_creates}. Auth_failures="
        f"{len(discord_relay.auth_failures)}"
    )

    # Poll for the localinfo mirror — guarantees the plugin's globals are
    # populated before we trigger the edit. 2s is generous for a loopback
    # curl round-trip.
    deadline = time.monotonic() + 2.0
    captured_id = ""
    while time.monotonic() < deadline:
        captured_id = driver.get_localinfo("_ktp_dmsg")
        if captured_id:
            break
        time.sleep(DISCORD_POLL_INTERVAL)
    assert captured_id, (
        "Plugin never captured a Discord message ID from the /reply "
        "response within 2s — discord_embed_callback may not be firing, "
        "or the response body shape changed and the parser at "
        "ktp_matchhandler_discord.inc:625-655 no longer matches."
    )

    driver.end_match(score_team1=100, score_team2=50)

    # Poll for the /edit POST. Reuse _wait_for_post_count semantics on the
    # edits list — same shape, different attribute.
    deadline = time.monotonic() + DISCORD_POST_TIMEOUT
    while time.monotonic() < deadline:
        if discord_relay.received_edits:
            break
        time.sleep(DISCORD_POLL_INTERVAL)

    assert len(discord_relay.received_edits) >= 1, (
        f"expected ≥1 /edit POST after end_match; got "
        f"{len(discord_relay.received_edits)}. /reply count="
        f"{len(discord_relay.received)}, auth_failures="
        f"{len(discord_relay.auth_failures)}"
    )

    edit = discord_relay.received_edits[0]
    assert edit.auth_ok is True, "/edit POST had bad X-Relay-Auth"
    assert edit.message_id, (
        "/edit POST had no messageId field — fixture or plugin sent the "
        "wrong shape, or msg ID capture from /reply response failed"
    )
    assert edit.message_id == "fake-relay-msg-1", (
        f"/edit POST messageId mismatch: expected fake-relay-msg-1 (the "
        f"FakeRelay's id for the first /reply post), got {edit.message_id!r}"
    )
    # Score must surface in the embed. Production format:
    # "MATCH COMPLETE - Final: 100-50 - Team1 wins!"
    embed = edit.embeds[0] if edit.embeds else {}
    embed_text = (
        str(embed.get("title", "")) + " "
        + str(embed.get("description", "")) + " "
        + " ".join(str(f.get("value", "")) for f in embed.get("fields", []))
    )
    assert "100" in embed_text and "50" in embed_text, (
        f"/edit embed didn't reference final score 100-50: text={embed_text!r}"
    )


# ---------------------------------------------------------------------------
# Test 9c — Auth mismatch should land in auth_failures, not received
# ---------------------------------------------------------------------------

SKIP_REASON_9C = (
    "Discovered 2026-05-05: rotating the auth secret at runtime is blocked "
    "by KTPMatchHandler's persistent g_curlHeaders slist (KTPMatchHandler.sma:"
    "3728-3730 — built once at plugin_init, never freed for UAF safety per "
    "memory `amxxcurl_shutdown_race_2026-05-04` + `KTPAmxxCurl Async Gotcha`). "
    "load_discord_config() updates g_discordAuthSecret but the slist holding "
    "the X-Relay-Auth header is frozen, so all subsequent curl POSTs send "
    "the boot-time secret. This is intentional production design, not a "
    "bug. Auth-rejection routing is covered by the 11 FakeRelay mock-side "
    "smokes in tests/integration/test_fake_relay.py — that validates the "
    "401-into-auth_failures path without requiring runtime secret rotation."
)


@pytest.mark.skip(reason=SKIP_REASON_9C)
def test_9c_bad_auth_routes_to_auth_failures(hlds, discord_relay):
    """Negative-path sanity: if KTPMatchHandler reads the WRONG secret,
    every POST lands in `relay.auth_failures` not `relay.received`.

    Currently un-runnable end-to-end — see SKIP_REASON_9C. The mock-side
    smokes in test_fake_relay.py cover this path structurally."""
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
        hlds.rcon("amx_ktp_test_reload_discord_config")
        # The reload is synchronous in plugin land but the rcon round-trip
        # plus the test_advance_live deferred-fwd timing means we still
        # need to drive a match and let the deferred POST drain.

        driver = MatchDriver(hlds)
        driver.reset()  # clears g_discordMatchMsgId — important: a stale ID
                        # from a prior test would route the next POST as
                        # an /edit (auth still wrong, still routes to
                        # auth_failures, but cleaner to start clean)
        driver.setup_match(MatchType.COMPETITIVE)
        driver.advance_pending()
        driver.advance_live(half=1)

        time.sleep(DISCORD_POST_TIMEOUT)  # let the deferred POST drain

        assert len(discord_relay.received) == 0, (
            "wrong-secret POSTs landed in `received` — fixture is leaking "
            "auth-failed posts into the happy-path bucket"
        )
        assert len(discord_relay.auth_failures) >= 1, (
            "wrong-secret POSTs vanished entirely — KTPMatchHandler may "
            "have refused to send (e.g., empty discord_channel_id), or "
            "the reload-config rcon didn't re-read the swapped file"
        )
    finally:
        config_path.write_bytes(original)
        # Restore the plugin's view too, so subsequent tests see the
        # correct config without a fixture-level reset.
        try:
            hlds.rcon("amx_ktp_test_reload_discord_config")
            hlds.rcon("amx_ktp_test_reset")
        except Exception:
            pass  # Best-effort restore
