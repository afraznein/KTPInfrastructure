"""Mock-side smoke for fake_relay — exercises the contract independently
of any hlds boot.

Why a separate test file: the full Match-flow Session 3 test #9 (Discord
embed POST during ktp_match_start) requires the test-mode KTPMatchHandler
to be aimed at the mock's URL via the Discord-config-file in serverfiles
(fixture-injected). That's a Session 3 fill-out item. THIS file proves
the mock itself behaves per the relay contract — auth, JSON shape, status
codes — so a future Session-3 author can rely on it without re-deriving.

Stdlib-only: posts are made via `urllib.request`. Keeps the test pinned
on the same exec path that production callers (ktp-soak-verify, ktp-perf-
rollup, crashreporter) use to talk to the real relay.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from .fake_relay import FakeRelay


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def relay():
    """Start a FakeRelay on a fresh ephemeral port; tear down after the test."""
    r = FakeRelay(expected_secret="test-secret-Vp3kU2xNm")
    r.start()
    try:
        yield r
    finally:
        r.stop()


def _post(url: str, body: dict, secret: str | None = "test-secret-Vp3kU2xNm",
          timeout: float = 2.0) -> tuple[int, dict]:
    """Helper: POST JSON, return (status, parsed-response-body). Includes
    the X-Relay-Auth header by default; pass secret=None to skip it."""
    headers = {"Content-Type": "application/json"}
    if secret is not None:
        headers["X-Relay-Auth"] = secret
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        method="POST", headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_relay_starts_and_url_is_loopback(relay: FakeRelay):
    """`url` returns a 127.0.0.1:<port> URL with a kernel-picked port. Tests
    that the listener is bound + accessible."""
    assert relay.url.startswith("http://127.0.0.1:"), (
        f"relay should bind loopback only, got {relay.url}"
    )
    # `reply_url` is just `url + "/reply"`.
    assert relay.reply_url == relay.url + "/reply"


def test_authenticated_post_is_captured(relay: FakeRelay):
    """Happy path: a properly-authed POST with a valid embed payload lands
    in `relay.received` with channel + embeds parsed."""
    status, body = _post(relay.reply_url, {
        "channelId": "1234567890",
        "embeds": [{"title": "match started", "color": 5763719}],
    })
    assert status == 200
    assert body["ok"] is True
    assert body["channel_id"] == "1234567890"

    relay.assert_post_count(1)
    post = relay.latest()
    assert post.auth_ok is True
    assert post.channel_id == "1234567890"
    assert len(post.embeds) == 1
    assert post.embeds[0]["title"] == "match started"
    assert post.allowed_mentions is None  # not provided in this payload
    # raw_body preserves the original payload for richer assertions
    assert post.raw_body["channelId"] == "1234567890"


def test_post_with_role_ping_preserves_allowed_mentions(relay: FakeRelay):
    """KTPMatchHandler/perf-rollup post `allowed_mentions={"roles":[...]}` to
    actually trigger role pings. Mock should preserve this through to the
    captured post for downstream assertions."""
    payload = {
        "channelId": "9999",
        "embeds": [{"title": "CRITICAL"}],
        "allowed_mentions": {"roles": ["1002394466700767332"]},
    }
    status, _ = _post(relay.reply_url, payload)
    assert status == 200
    relay.assert_post_count(1)
    post = relay.latest()
    assert post.allowed_mentions == {"roles": ["1002394466700767332"]}


def test_bad_secret_yields_401_and_excluded_from_received(relay: FakeRelay):
    """Wrong X-Relay-Auth header → 401, does NOT land in `relay.received`,
    DOES land in `relay.auth_failures` for tests that want to verify
    auth-rejection behavior."""
    status, body = _post(relay.reply_url, {"channelId": "1"}, secret="wrong-secret")
    assert status == 401
    assert body == {"error": "Unauthorized"}
    relay.assert_post_count(0)
    assert len(relay.auth_failures) == 1
    assert relay.auth_failures[0].auth_ok is False


def test_missing_auth_header_yields_401(relay: FakeRelay):
    """No X-Relay-Auth header at all → 401."""
    status, _ = _post(relay.reply_url, {"channelId": "1"}, secret=None)
    assert status == 401
    relay.assert_post_count(0)


def test_invalid_json_yields_400(relay: FakeRelay):
    """Bad JSON body → 400. Auth was valid; the request just couldn't be
    parsed. NOT recorded in either list (parse-fail is a caller bug,
    different bucket from auth-fail)."""
    req = urllib.request.Request(
        relay.reply_url,
        data=b"this is not json",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Relay-Auth": "test-secret-Vp3kU2xNm",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=2.0)
        pytest.fail("expected HTTPError for malformed JSON")
    except urllib.error.HTTPError as e:
        assert e.code == 400
    relay.assert_post_count(0)


def test_unknown_path_yields_404(relay: FakeRelay):
    """Mock only routes /reply; everything else 404."""
    req = urllib.request.Request(
        relay.url + "/some-other-path",
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json", "X-Relay-Auth": "test-secret-Vp3kU2xNm"},
    )
    try:
        urllib.request.urlopen(req, timeout=2.0)
        pytest.fail("expected HTTPError for unknown path")
    except urllib.error.HTTPError as e:
        assert e.code == 404
    relay.assert_post_count(0)


def test_multiple_posts_accumulate_in_order(relay: FakeRelay):
    """Three sequential POSTs → three captured posts in send order. Verifies
    ordering for tests that need to assert "first the match-start embed,
    then the match-end embed"."""
    for i, channel in enumerate(["chan-A", "chan-B", "chan-C"]):
        status, _ = _post(relay.reply_url, {
            "channelId": channel, "embeds": [{"title": f"event-{i}"}],
        })
        assert status == 200
    relay.assert_post_count(3)
    assert [p.channel_id for p in relay.received] == ["chan-A", "chan-B", "chan-C"]
    assert [p.embeds[0]["title"] for p in relay.received] == ["event-0", "event-1", "event-2"]


def test_reset_clears_state(relay: FakeRelay):
    """`relay.reset()` clears both received + auth_failures. Tests reusing
    a session-scoped relay across subtests can call reset() to start fresh."""
    _post(relay.reply_url, {"channelId": "1"})
    _post(relay.reply_url, {"channelId": "2"}, secret="bad")
    assert len(relay.received) == 1
    assert len(relay.auth_failures) == 1

    relay.reset()
    assert relay.received == []
    assert relay.auth_failures == []

    # Mock still works after reset
    _post(relay.reply_url, {"channelId": "3"})
    relay.assert_post_count(1)


def test_context_manager_starts_and_stops(relay: FakeRelay):
    """`FakeRelay` supports `with` statement for one-shot use within a test
    body — alternative to the fixture for tests that want stricter scoping
    or multiple relay instances."""
    # The fixture-provided `relay` is used here only to anchor the test in
    # the fixture's lifecycle; the actual context-manager exercise is on a
    # fresh relay below.
    with FakeRelay(expected_secret="alt") as ad_hoc:
        assert ad_hoc.url.startswith("http://127.0.0.1:")
        status, _ = _post(ad_hoc.reply_url, {"channelId": "X"}, secret="alt")
        assert status == 200
        ad_hoc.assert_post_count(1)
    # After __exit__, the listener is closed — calls to .url raise
    with pytest.raises(RuntimeError, match="not started"):
        _ = ad_hoc.url


def test_assert_post_count_raises_with_helpful_message(relay: FakeRelay):
    """`assert_post_count` raises AssertionError with a payload-revealing
    message — gives test authors something useful when their assumption
    about how many embeds got POSTed is wrong."""
    _post(relay.reply_url, {"channelId": "channel-a"})
    _post(relay.reply_url, {"channelId": "channel-b"})
    with pytest.raises(AssertionError, match="expected 5 POSTs.*got 2.*channel-a.*channel-b"):
        relay.assert_post_count(5)
