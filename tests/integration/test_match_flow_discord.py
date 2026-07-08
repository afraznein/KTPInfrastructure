"""Match-flow Session 3 — test 9: Discord embed POSTs during match-flow events.

Asserts that KTPMatchHandler emits the expected Discord embed via the
relay path when the match-flow state machine transitions through key
events. The fixture machinery in `conftest.py` (`discord_relay` +
`_discord_ini_setup`) writes a test `discord.ini` pointing at a loopback
FakeRelay before hlds boots; this file's tests drive the state machine
via MatchDriver and assert against `discord_relay.received`.

## Header status (2026-07-07): tests RUN — only 9c remains skipped
##
## The Session-3 audit below concluded; the emission surface was pinned and
## tests 9/9b/13-16b were un-skipped. The original blocker analysis is kept
## for context:
##
## Why these tests were skip-marked originally

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

from ._timing import DISCORD_POLL_INTERVAL, DISCORD_POST_TIMEOUT
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

# Timeout constants imported from `_timing` — scaled by
# KTP_TEST_TIMEOUT_MULTIPLIER for slow CI runners.


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


# ---------------------------------------------------------------------------
# Helper for tests 13/14/15 — drive create+wait-for-msgID, return match_id
# ---------------------------------------------------------------------------

def _drive_to_live_with_msgid(driver: MatchDriver, relay) -> str:
    """Setup a competitive match, drive to LIVE for half 1, and wait for
    the msgID round-trip so subsequent /edit POSTs land cleanly. Returns
    the match_id assigned by the rcon so tests can use it in assertions.

    Why this is factored out: tests 13/14/15 all need the same setup
    sequence (test 9b/9c-style). Inlining four times accumulates errors
    in the timing logic; one helper captures the contract.
    """
    match_id = driver.setup_match(MatchType.COMPETITIVE)
    driver.advance_pending()
    driver.advance_live(half=1)

    # Wait for the CREATE POST that fires from task_deferred_discord_fwd
    # ~200ms after advance_live (KTPMatchHandler.sma:7414).
    actual = _wait_for_post_count(relay, expected_min=1)
    assert actual >= 1, (
        f"setup: CREATE POST never arrived; got {actual}. Auth_failures="
        f"{len(relay.auth_failures)}"
    )

    # Wait for the msgID capture round-trip (curl response → callback →
    # localinfo mirror). Up to 2s for a loopback round-trip.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if driver.get_localinfo("_ktp_dmsg"):
            break
        time.sleep(DISCORD_POLL_INTERVAL)
    else:
        raise AssertionError(
            "setup: msgID round-trip never completed within 2s — subsequent "
            "/edit POSTs would no-op with DISCORD_EDIT_SKIP reason=no_msg_id"
        )
    return match_id


# ---------------------------------------------------------------------------
# Test 13 — Half-1 end emits "1st Half Complete - Score: X-Y" embed update
# ---------------------------------------------------------------------------

def test_13_half1_end_emits_score_embed_update(hlds, discord_relay):
    """`handle_first_half_end()` (KTPMatchHandler.sma:939-1023) emits a
    Discord embed update with a status string formatted as "1st Half
    Complete - Score: %d-%d" (line 1010). Test drives via the new
    `amx_ktp_test_end_first_half` rcon (KTPMatchHandler 0.10.125+).

    Wire-shape:
      - advance_live(1)        → POST /reply (CREATE) → received[0]
      - end_first_half(3, 1)   → POST /edit  (UPDATE) → received_edits[0]

    Asserts the /edit POST has the literal "1st Half Complete" status and
    the score round-trips. Independent of test 14 — half-1-end is a
    discrete event that emits ONE embed update before any half-2 advance.
    """
    discord_relay.reset()
    driver = MatchDriver(hlds)

    _drive_to_live_with_msgid(driver, discord_relay)

    edits_baseline = len(discord_relay.received_edits)
    driver.end_first_half(score_team1=3, score_team2=1)

    deadline = time.monotonic() + DISCORD_POST_TIMEOUT
    while time.monotonic() < deadline:
        if len(discord_relay.received_edits) > edits_baseline:
            break
        time.sleep(DISCORD_POLL_INTERVAL)

    assert len(discord_relay.received_edits) > edits_baseline, (
        f"expected ≥1 /edit POST after end_first_half; got "
        f"{len(discord_relay.received_edits)} (baseline={edits_baseline})"
    )

    edit = discord_relay.received_edits[edits_baseline]
    assert edit.auth_ok is True, "/edit POST had bad X-Relay-Auth"
    assert edit.message_id == "fake-relay-msg-1", (
        f"/edit messageId should be the CREATE POST's id; got {edit.message_id!r}"
    )
    embed = edit.embeds[0] if edit.embeds else {}
    embed_text = (
        str(embed.get("title", "")) + " "
        + str(embed.get("description", "")) + " "
        + " ".join(str(f.get("value", "")) for f in embed.get("fields", []))
    )
    assert "1st Half Complete" in embed_text, (
        f"/edit embed missing '1st Half Complete' status: text={embed_text!r}"
    )
    # Score round-trip — the production format is "Score: 3-1"
    assert "3" in embed_text and "1" in embed_text, (
        f"/edit embed didn't reference half-1 scores 3-1: text={embed_text!r}"
    )


# ---------------------------------------------------------------------------
# Test 14 — Advance-live(half=2) emits "2nd Half - Match Live" embed update
# ---------------------------------------------------------------------------

def test_14_half2_advance_live_emits_match_live_embed_update(hlds, discord_relay):
    """`task_deferred_discord_fwd()` (KTPMatchHandler.sma:7395-7419)
    distinguishes h1 vs h2/OT: for h1 it fires `send_match_embed_create`
    (the initial persistent embed POST), for h2 it fires
    `send_match_embed_update("2nd Half - Match Live")` against the existing
    msgID (line 7416).

    Wire-shape after the full setup → live(1) → end_first_half(2-1) → live(2):
      - received[0]        — CREATE from advance_live(half=1)
      - received_edits[0]  — UPDATE from end_first_half ("1st Half Complete")
      - received_edits[1]  — UPDATE from advance_live(half=2) ("2nd Half - Match Live")

    Asserts the second /edit POST has the "2nd Half - Match Live" status.
    """
    discord_relay.reset()
    driver = MatchDriver(hlds)

    _drive_to_live_with_msgid(driver, discord_relay)
    driver.end_first_half(score_team1=2, score_team2=1)

    # Wait for the half-1-end embed update to land (test 13 covers it
    # explicitly; here we just need it sequenced before the half-2 update)
    deadline = time.monotonic() + DISCORD_POST_TIMEOUT
    while time.monotonic() < deadline:
        if len(discord_relay.received_edits) >= 1:
            break
        time.sleep(DISCORD_POLL_INTERVAL)
    h1_edit_count = len(discord_relay.received_edits)
    assert h1_edit_count >= 1, "half-1-end edit didn't arrive — test 13 sequencing prereq"

    # Trigger the h2 advance_live → expect another /edit POST shortly after
    driver.advance_live(half=2)

    deadline = time.monotonic() + DISCORD_POST_TIMEOUT
    while time.monotonic() < deadline:
        if len(discord_relay.received_edits) > h1_edit_count:
            break
        time.sleep(DISCORD_POLL_INTERVAL)

    assert len(discord_relay.received_edits) > h1_edit_count, (
        f"expected ≥1 additional /edit POST after advance_live(half=2); "
        f"got {len(discord_relay.received_edits)} (h1-edit count was {h1_edit_count})"
    )

    h2_edit = discord_relay.received_edits[h1_edit_count]
    assert h2_edit.auth_ok is True
    embed = h2_edit.embeds[0] if h2_edit.embeds else {}
    embed_text = (
        str(embed.get("title", "")) + " "
        + str(embed.get("description", "")) + " "
        + " ".join(str(f.get("value", "")) for f in embed.get("fields", []))
    )
    assert "2nd Half" in embed_text and "Match Live" in embed_text, (
        f"h2 /edit embed missing '2nd Half - Match Live' status: text={embed_text!r}"
    )


# ---------------------------------------------------------------------------
# Test 15 — Tied-result match-end emits "Match tied!" winner phrasing
# ---------------------------------------------------------------------------

def test_15_tied_match_end_emits_tied_winner(hlds, discord_relay):
    """Match-end with equal scores produces the tied-result winner string.
    `cmd_test_end_match` constructs the status as "MATCH COMPLETE - Final:
    %d-%d - %s" where the winner string is "Match tied!" when s1 == s2
    (KTPMatchHandler.sma:7817).

    Distinct from test 9b (which uses 100-50, asserts a non-tied winner).
    Asserts the literal "Match tied!" phrasing surfaces in the embed,
    which catches a regression where the equality branch is taken but the
    winner string is built wrong.
    """
    discord_relay.reset()
    driver = MatchDriver(hlds)

    _drive_to_live_with_msgid(driver, discord_relay)

    # Equal scores → tied-result branch
    edits_baseline = len(discord_relay.received_edits)
    driver.end_match(score_team1=42, score_team2=42)

    deadline = time.monotonic() + DISCORD_POST_TIMEOUT
    while time.monotonic() < deadline:
        if len(discord_relay.received_edits) > edits_baseline:
            break
        time.sleep(DISCORD_POLL_INTERVAL)

    assert len(discord_relay.received_edits) > edits_baseline, (
        f"expected ≥1 /edit POST after end_match(42, 42); got "
        f"{len(discord_relay.received_edits)} (baseline={edits_baseline})"
    )

    edit = discord_relay.received_edits[edits_baseline]
    embed = edit.embeds[0] if edit.embeds else {}
    embed_text = (
        str(embed.get("title", "")) + " "
        + str(embed.get("description", "")) + " "
        + " ".join(str(f.get("value", "")) for f in embed.get("fields", []))
    )
    assert "Match tied" in embed_text, (
        f"tied-result /edit embed missing 'Match tied' phrasing: "
        f"text={embed_text!r}"
    )
    # Score round-trip
    assert "42" in embed_text, (
        f"tied-result /edit didn't reference tied score 42: text={embed_text!r}"
    )


# ---------------------------------------------------------------------------
# Test 16 — 2nd-half-abandon emits "MATCH ENDED (2nd half)" embed update
# ---------------------------------------------------------------------------

def test_16_abandon_match_emits_match_ended_embed_update(hlds, discord_relay):
    """The 2nd-half-abandon path emits a Discord embed update with
    "MATCH ENDED (2nd half) - 1st half: %s %d - %d %s" status
    (KTPMatchHandler.sma:4284-4288). KTPMatchHandler 0.10.126's
    `amx_ktp_test_abandon_match` rcon emits this exact production-shape
    string using the currently-set team names + half-1 scores.

    Test sequence:
      1. setup_match → advance_pending → advance_live(half=1) → wait msgID
      2. end_first_half(7, 4) — populates `g_firstHalfScore[1/2]` so the
         abandon embed has meaningful scores
      3. abandon_match() — emits the MATCH ENDED embed update
      4. Assert /edit POST has the abandon-shape status string + scores

    What this test does NOT cover (deferred per Phase 2a notes):
      - The localinfo-driven abandon-detection path itself (production
        runs this from plugin_cfg on map load, not via rcon)
      - HLStatsX KTP_MATCH_END "abandoned_2nd_half" log emission
      - dodx_flush_all_stats() type=abandoned_2nd_half flushing

    Those gaps are operator-checked manually during real matchday recovery
    drills; the embed-update side-effect — which is the player-visible
    Discord notification — is what this test pins.
    """
    discord_relay.reset()
    driver = MatchDriver(hlds)

    _drive_to_live_with_msgid(driver, discord_relay)

    # Half-1-end populates g_firstHalfScore so the abandon embed has
    # meaningful scores. Wait for its /edit POST to land before triggering
    # the abandon (so the assertion can target the abandon edit cleanly).
    driver.end_first_half(score_team1=7, score_team2=4)

    deadline = time.monotonic() + DISCORD_POST_TIMEOUT
    while time.monotonic() < deadline:
        if len(discord_relay.received_edits) >= 1:
            break
        time.sleep(DISCORD_POLL_INTERVAL)
    half1_edit_count = len(discord_relay.received_edits)
    assert half1_edit_count >= 1, "half-1-end edit prereq didn't land"

    # Trigger the abandon-shape embed update
    driver.abandon_match()

    deadline = time.monotonic() + DISCORD_POST_TIMEOUT
    while time.monotonic() < deadline:
        if len(discord_relay.received_edits) > half1_edit_count:
            break
        time.sleep(DISCORD_POLL_INTERVAL)

    assert len(discord_relay.received_edits) > half1_edit_count, (
        f"expected ≥1 additional /edit POST after abandon_match; got "
        f"{len(discord_relay.received_edits)} (half1-edit count was {half1_edit_count})"
    )

    abandon_edit = discord_relay.received_edits[half1_edit_count]
    assert abandon_edit.auth_ok is True
    embed = abandon_edit.embeds[0] if abandon_edit.embeds else {}
    embed_text = (
        str(embed.get("title", "")) + " "
        + str(embed.get("description", "")) + " "
        + " ".join(str(f.get("value", "")) for f in embed.get("fields", []))
    )
    # Production format: "MATCH ENDED (2nd half) - 1st half: <team1> 7 - 4 <team2>"
    assert "MATCH ENDED" in embed_text, (
        f"abandon /edit missing 'MATCH ENDED' phrasing: text={embed_text!r}"
    )
    assert "2nd half" in embed_text, (
        f"abandon /edit missing '2nd half' qualifier: text={embed_text!r}"
    )
    # Half-1 scores round-trip
    assert "7" in embed_text and "4" in embed_text, (
        f"abandon /edit didn't reference half-1 scores 7-4: text={embed_text!r}"
    )


# ---------------------------------------------------------------------------
# Test 16b — OT-abandon emits "MATCH ENDED (OT%d)" embed update
# ---------------------------------------------------------------------------

def test_16b_ot_abandon_match_emits_match_ended_ot_embed_update(hlds, discord_relay):
    """The OT-abandon path emits a Discord embed update with
    "MATCH ENDED (OT%d) - Regulation: %s %d - %d %s (tied)" status
    (KTPMatchHandler.sma:4599-4603). KTPMatchHandler 0.10.136's extended
    `amx_ktp_test_abandon_match ot1 <reg_s1> <reg_s2>` rcon shape drives
    this production code path.

    Test sequence:
      1. setup_match → advance_pending → advance_live(half=1) → wait msgID
      2. abandon_match(mode="ot1", regulation_scores=(12, 12)) — emits
         the OT-abandon shape with the supplied regulation totals
      3. Assert /edit POST has "MATCH ENDED (OT1)" + regulation scores

    Companion to test 16 (which covers the 2nd-half-abandon shape). Together
    they pin both branches of the abandon-detection path's embed-emit logic.

    What this test does NOT cover (same scope-limits as test 16):
      - The localinfo-driven abandon-detection path itself (production
        runs this from plugin_cfg on map load with LOCALINFO_REG_SCORES
        already set; the rcon accepts regulation scores as args instead)
      - HLStatsX KTP_MATCH_END "abandoned_ot%d" log emission
      - dodx_flush_all_stats() type=abandoned_ot flushing

    Those gaps are operator-checked manually during real matchday recovery
    drills.
    """
    discord_relay.reset()
    driver = MatchDriver(hlds)

    _drive_to_live_with_msgid(driver, discord_relay)

    create_count = len(discord_relay.received)
    edits_baseline = len(discord_relay.received_edits)

    # Drive OT-abandon with regulation tied at 12-12 (canonical OT-trigger
    # scenario — regulation ended tied, OT1 starts, then OT was abandoned)
    driver.abandon_match(mode="ot1", regulation_scores=(12, 12))

    deadline = time.monotonic() + DISCORD_POST_TIMEOUT
    while time.monotonic() < deadline:
        if len(discord_relay.received_edits) > edits_baseline:
            break
        time.sleep(DISCORD_POLL_INTERVAL)

    assert len(discord_relay.received_edits) > edits_baseline, (
        f"expected ≥1 additional /edit POST after abandon_match(ot1); got "
        f"{len(discord_relay.received_edits)} (baseline was {edits_baseline})"
    )
    # Verify no extra /reply (create) POSTs landed — OT-abandon should only
    # /edit the existing embed, never create a new one.
    assert len(discord_relay.received) == create_count, (
        f"abandon_match(ot1) caused unexpected /reply POST: baseline="
        f"{create_count}, now={len(discord_relay.received)}"
    )

    abandon_edit = discord_relay.received_edits[edits_baseline]
    assert abandon_edit.auth_ok is True
    embed = abandon_edit.embeds[0] if abandon_edit.embeds else {}
    embed_text = (
        str(embed.get("title", "")) + " "
        + str(embed.get("description", "")) + " "
        + " ".join(str(f.get("value", "")) for f in embed.get("fields", []))
    )
    # Production format: "MATCH ENDED (OT1) - Regulation: <team1> 12 - 12 <team2> (tied)"
    assert "MATCH ENDED" in embed_text, (
        f"OT-abandon /edit missing 'MATCH ENDED' phrasing: text={embed_text!r}"
    )
    assert "OT1" in embed_text, (
        f"OT-abandon /edit missing 'OT1' qualifier: text={embed_text!r}"
    )
    assert "Regulation" in embed_text, (
        f"OT-abandon /edit missing 'Regulation' label: text={embed_text!r}"
    )
    # Regulation scores round-trip
    assert "12" in embed_text, (
        f"OT-abandon /edit didn't reference regulation score 12: text={embed_text!r}"
    )
    assert "tied" in embed_text, (
        f"OT-abandon /edit missing '(tied)' qualifier (production shape): "
        f"text={embed_text!r}"
    )
