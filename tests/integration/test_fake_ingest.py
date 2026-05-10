"""Mock-side smoke for fake_ingest — exercises the contract independently
of any hlds boot.

Mirrors `test_fake_relay.py`: same shape, same stdlib-only POST helper,
same separation between the mock-side smoke (this file, no hlds needed)
and the integration-side contract test (`test_hud_observer_contract.py`,
needs hlds + KTPHudObserver loaded).

These tests give us confidence the mock matches the production-backend
contract before we wire up the integration tests that depend on it.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from .fake_ingest import FakeIngest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ingest():
    """Start a FakeIngest on a fresh ephemeral port; tear down after."""
    i = FakeIngest(expected_auth_key="test-hud-key-Mq8Xp7tNkBz")
    i.start()
    try:
        yield i
    finally:
        i.stop()


def _post(
    url: str,
    body: dict,
    auth_key: str | None = "test-hud-key-Mq8Xp7tNkBz",
    server_hostname: str | None = None,
    plugin_sent_at: str | None = None,
    timeout: float = 2.0,
) -> tuple[int, dict]:
    """Helper: POST JSON, return (status, parsed-response-body). Headers
    mirror what KTPHudObserver's `post_event` actually sends in production
    (auth + optional server hostname + optional sent-at)."""
    headers = {"Content-Type": "application/json"}
    if auth_key is not None:
        headers["X-Auth-Key"] = auth_key
    if server_hostname is not None:
        headers["X-Server-Hostname"] = server_hostname
    if plugin_sent_at is not None:
        headers["X-Plugin-Sent-At"] = plugin_sent_at
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

def test_ingest_starts_and_url_is_loopback(ingest: FakeIngest):
    """`url` returns a 127.0.0.1:<port>/ingest URL with a kernel-picked
    port."""
    assert ingest.url.startswith("http://127.0.0.1:"), (
        f"ingest should bind loopback only, got {ingest.url}"
    )
    assert ingest.url.endswith("/ingest")
    assert ingest.base_url + "/ingest" == ingest.url


def test_authenticated_post_captured_with_envelope_fields(ingest: FakeIngest):
    """Happy path: a properly-authed POST with the production envelope
    shape lands in `received` with all fields parsed."""
    status, body = _post(
        ingest.url,
        {
            "event": "ktp_match_start",
            "tick": 12.34,
            "match_id": "1777999999-TEST",
            "map": "dod_anzio",
            "match_type": 0,
            "half": 1,
            "plugin_sent_at": 1714992000000,
        },
        server_hostname="DEN5-27015",
        plugin_sent_at="1714992000000",
    )
    assert status == 200
    assert body == {"ok": True}

    ingest.assert_post_count(1)
    post = ingest.latest()
    assert post.auth_ok is True
    assert post.event == "ktp_match_start"
    assert post.match_id == "1777999999-TEST"
    assert post.tick == 12.34
    assert post.plugin_sent_at == 1714992000000
    assert post.server_hostname == "DEN5-27015"
    assert post.plugin_sent_at_header == "1714992000000"
    # raw_body preserves the original payload for richer assertions
    assert post.raw_body["map"] == "dod_anzio"
    assert post.raw_body["half"] == 1


def test_post_without_match_envelope_still_captured(ingest: FakeIngest):
    """Plugin's `post_event` omits match_id/map/match_type/half when
    g_matchActive=false (KTPHudObserver.sma:266-274). Mock should accept
    these and leave match_id=None on the captured post."""
    status, _ = _post(
        ingest.url,
        {"event": "player_disconnect", "tick": 5.0,
         "plugin_sent_at": 1714992000000, "user_id": "STEAM_0:0:123"},
    )
    assert status == 200
    ingest.assert_post_count(1)
    post = ingest.latest()
    assert post.event == "player_disconnect"
    assert post.match_id is None
    assert post.tick == 5.0


def test_bad_auth_key_yields_401_and_excluded_from_received(ingest: FakeIngest):
    """Wrong X-Auth-Key → 401, NOT in `received`, IS in `auth_failures`.
    Same convention as fake_relay's auth_failures bucket."""
    status, body = _post(
        ingest.url, {"event": "kill", "tick": 1.0},
        auth_key="wrong-key",
    )
    assert status == 401
    assert body == {"error": "unauthorized"}
    ingest.assert_post_count(0)
    assert len(ingest.auth_failures) == 1
    assert ingest.auth_failures[0].auth_ok is False
    assert ingest.auth_failures[0].event == "<auth-rejected>"


def test_missing_auth_header_yields_401(ingest: FakeIngest):
    """No X-Auth-Key header at all → 401."""
    status, _ = _post(ingest.url, {"event": "kill"}, auth_key=None)
    assert status == 401
    ingest.assert_post_count(0)


def test_invalid_json_yields_400(ingest: FakeIngest):
    """Bad JSON body → 400. Auth was valid; the request just couldn't
    be parsed. NOT recorded (parse-fail is a caller bug bucket)."""
    req = urllib.request.Request(
        ingest.url,
        data=b"this is not json",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Auth-Key": "test-hud-key-Mq8Xp7tNkBz",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=2.0)
        pytest.fail("expected HTTPError for malformed JSON")
    except urllib.error.HTTPError as e:
        assert e.code == 400
    ingest.assert_post_count(0)


def test_missing_event_field_yields_400(ingest: FakeIngest):
    """Body parsed but no `event` key → 400 (matches production
    backend/src/handler/ingest.ts:328-331)."""
    status, body = _post(ingest.url, {"tick": 1.0, "user_id": "STEAM_0:0:1"})
    assert status == 400
    assert body == {"error": "missing event field"}
    ingest.assert_post_count(0)


def test_any_path_accepted_path_recorded(ingest: FakeIngest):
    """The `dod_hud_url` cvar carries the full URL. Production servers
    might point at `/ingest`, `/`, or `/hud` — the mock accepts any
    path and records it on the captured post for routing assertions."""
    status, _ = _post(ingest.base_url + "/", {"event": "x", "tick": 0.0})
    assert status == 200
    status, _ = _post(ingest.base_url + "/some-other", {"event": "y", "tick": 0.0})
    assert status == 200
    ingest.assert_post_count(2)
    assert ingest.received[0].path == "/"
    assert ingest.received[1].path == "/some-other"


def test_multiple_posts_accumulate_in_order(ingest: FakeIngest):
    """Three sequential POSTs → three captured posts in send order.
    Tier 2 contract tests rely on this for "first ktp_match_start, then
    half_start, then team_score" ordering assertions on the match-start
    burst (KTPHudObserver.sma:380-401)."""
    for i, ev in enumerate(["ktp_match_start", "half_start", "team_score"]):
        status, _ = _post(ingest.url, {"event": ev, "tick": float(i)})
        assert status == 200
    ingest.assert_post_count(3)
    assert [p.event for p in ingest.received] == [
        "ktp_match_start", "half_start", "team_score",
    ]


def test_events_of_type_filters_correctly(ingest: FakeIngest):
    """`events_of_type` returns posts of one event in send order; other
    events are not filtered into the result."""
    _post(ingest.url, {"event": "kill", "tick": 1.0, "victim_id": "A"})
    _post(ingest.url, {"event": "player_spawn", "tick": 2.0, "user_id": "B"})
    _post(ingest.url, {"event": "kill", "tick": 3.0, "victim_id": "C"})

    kills = ingest.events_of_type("kill")
    assert len(kills) == 2
    assert kills[0].raw_body["victim_id"] == "A"
    assert kills[1].raw_body["victim_id"] == "C"

    assert len(ingest.events_of_type("player_spawn")) == 1
    assert ingest.events_of_type("nonexistent") == []


def test_latest_of_type_raises_helpful_when_missing(ingest: FakeIngest):
    """`latest_of_type` raises with seen-events list when the requested
    type was never POSTed — helps test authors debug a wrong assumption
    about what the plugin emits."""
    _post(ingest.url, {"event": "player_spawn", "tick": 1.0})
    _post(ingest.url, {"event": "kill", "tick": 2.0})

    with pytest.raises(AssertionError, match=r"event='nope'.*received events.*kill.*player_spawn"):
        ingest.latest_of_type("nope")


def test_reset_clears_state(ingest: FakeIngest):
    """`ingest.reset()` clears both received + auth_failures. Tests
    reusing a session-scoped ingest across subtests can call reset()
    to start fresh."""
    _post(ingest.url, {"event": "x", "tick": 1.0})
    _post(ingest.url, {"event": "y", "tick": 2.0}, auth_key="bad")
    assert len(ingest.received) == 1
    assert len(ingest.auth_failures) == 1

    ingest.reset()
    assert ingest.received == []
    assert ingest.auth_failures == []

    # Mock still works after reset
    _post(ingest.url, {"event": "z", "tick": 3.0})
    ingest.assert_post_count(1)


def test_context_manager_starts_and_stops():
    """`FakeIngest` supports `with` for one-shot use within a test
    body — alternative to the fixture for tests that want stricter
    scoping or multiple ingest instances."""
    with FakeIngest(expected_auth_key="alt") as ad_hoc:
        assert ad_hoc.url.startswith("http://127.0.0.1:")
        status, _ = _post(ad_hoc.url, {"event": "x", "tick": 0.0}, auth_key="alt")
        assert status == 200
        ad_hoc.assert_post_count(1)
    # After __exit__, the listener is closed — calls to .url raise
    with pytest.raises(RuntimeError, match="not started"):
        _ = ad_hoc.url


def test_assert_post_count_raises_with_helpful_message(ingest: FakeIngest):
    """`assert_post_count` raises AssertionError with the captured
    event names — test authors get something useful on count mismatch."""
    _post(ingest.url, {"event": "ktp_match_start", "tick": 1.0})
    _post(ingest.url, {"event": "half_start", "tick": 2.0})
    with pytest.raises(AssertionError, match=r"expected 5 POSTs.*got 2.*ktp_match_start.*half_start"):
        ingest.assert_post_count(5)
