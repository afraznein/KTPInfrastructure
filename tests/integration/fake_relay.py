"""fake_relay — stdlib HTTP mock of the KTP Discord relay.

Replaces the production Cloud Run relay (`https://discord-relay-…run.app/reply`)
during integration tests. Captures POSTed embeds into an in-memory list so
tests can assert on what KTPMatchHandler / KTPHLTVRecorder / etc. would have
sent to Discord, without actually hitting Discord (or even the network beyond
loopback).

## Contract this mock implements

The production relay accepts:

  POST /reply
    Headers:  X-Relay-Auth: <secret>
              Content-Type: application/json
    Body:     {"channelId": "<id>", "embeds": [<embed>, ...],
               "allowed_mentions": {...}?,  ...}
  Returns:    HTTP 200 with `{"id": "<fake-id>", "ok": true, "channel_id": ...}`.
              KTPMatchHandler parses the `id` field and stores it in
              `g_discordMatchMsgId` (`ktp_matchhandler_discord.inc:625-655`)
              so subsequent edits know which message to PATCH.
              HTTP 401 on auth mismatch.
              HTTP 400 on JSON parse failure.

  POST /edit
    Headers:  X-Relay-Auth: <secret>
              Content-Type: application/json
    Body:     {"channelId": "<id>", "messageId": "<id>",
               "embeds": [<embed>, ...]}
              KTPMatchHandler builds this URL by string-replacing `/reply`
              with `/edit` in `g_discordRelayUrl`
              (`ktp_matchhandler_discord.inc:781-784`); the test fixture's
              `discord_relay.reply_url` ends in `/reply` so the swap works.
  Returns:    HTTP 200 (plugin doesn't capture an ID from edit responses).
              HTTP 401 / 400 same as /reply.

`received_edits` is the captured-list for /edit; `received` stays /reply-only
so create-vs-update test assertions don't have to filter by route.

## Why stdlib http.server + threading instead of aiohttp

Earlier README drafts said "aiohttp mock". Switched to stdlib because:

  1. KTPInfrastructure's test runtime doesn't currently pull aiohttp;
     stdlib means no `pip install` step in the CI runner setup.
  2. The relay contract is one route, three response shapes — no async
     fan-out, no upgrade paths, no streaming. http.server in a thread
     is sufficient and keeps the test stack one Python.
  3. KTPAdminBot (the production relay caller for /ops commands) does
     ship aiohttp via its own venv. Reusing aiohttp here would require
     mirroring that venv setup in the integration-test runner; not worth
     it for a single mock.

If a future test needs websockets or chunked streaming from the relay,
revisit — those would push us to aiohttp.

## Usage

    from .fake_relay import FakeRelay

    relay = FakeRelay(expected_secret="test-secret-123")
    relay.start()
    try:
        # KTPMatchHandler etc. would POST to relay.url + "/reply"
        # ... drive the system under test ...
        assert len(relay.received) == 1
        assert relay.received[0]["channel_id"] == "1234567890"
    finally:
        relay.stop()

Or as a pytest fixture (see `conftest.py:fake_relay`).
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


@dataclass
class CapturedPost:
    """One recorded Discord-relay POST (POST /reply or POST /edit). Tests
    assert against these.

    `auth_ok` is whether the X-Relay-Auth header matched the expected secret;
    auth-failed posts are NOT routed into FakeRelay.received (they're
    rejected with 401 and recorded into FakeRelay.auth_failures separately
    so a test can verify auth-rejection behavior without polluting the
    happy-path list).

    `message_id` is populated for /edit captures (the `messageId` field the
    plugin sent); None for /reply captures.
    """
    channel_id: str | None
    embeds: list[dict[str, Any]] = field(default_factory=list)
    allowed_mentions: dict[str, Any] | None = None
    raw_body: dict[str, Any] = field(default_factory=dict)
    auth_ok: bool = True
    message_id: str | None = None


@dataclass
class CapturedAcPost:
    """One recorded KTPAntiCheat-API POST (POST /api/match/end and friends).

    Distinct from `CapturedPost` because the AC API:
      - Uses a different auth header (`X-Server-Secret` vs `X-Relay-Auth`)
      - Has a different payload shape (`matchId`/`serverEndpoint`) — no
        embeds, no channel_id

    Match-end is the only AC endpoint test 17 covers; future Phase 2c
    extensions can add `/api/match/announce` etc. by following the same
    pattern (new captured-list, route the POST in _RelayHandler.do_POST).
    """
    match_id: str | None
    server_endpoint: str | None
    raw_body: dict[str, Any] = field(default_factory=dict)
    auth_ok: bool = True


class _RelayHandler(BaseHTTPRequestHandler):
    """Per-request handler. Routes POST /reply (creates) and POST /edit
    (in-place embed updates); everything else 404.
    Reaches into `self.server.relay` (set by FakeRelay.start) for state."""

    def log_message(self, format: str, *args: Any) -> None:
        # Quiet by default — pytest -v already captures stderr/stdout per test.
        # Tests that want to debug can flip self.server.relay.verbose = True.
        if getattr(self.server, "relay", None) and self.server.relay.verbose:
            super().log_message(format, *args)

    def do_POST(self) -> None:
        relay: FakeRelay = self.server.relay  # type: ignore[attr-defined]

        # Three known routes: Discord /reply, /edit, and AC /api/match/end.
        # Anything else 404s.
        is_ac_match_end = (self.path == "/api/match/end")
        is_discord = self.path in ("/reply", "/edit")
        if not (is_ac_match_end or is_discord):
            self._respond(404, {"error": f"unknown path: {self.path}"})
            return

        # Read body up to Content-Length. Refuse unbounded reads.
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 1_000_000:
            self._respond(400, {"error": "missing or oversized Content-Length"})
            return
        raw = self.rfile.read(length)

        # Auth check — different routes use different headers + secrets.
        # Discord routes use X-Relay-Auth + relay.expected_secret;
        # AC route uses X-Server-Secret + relay.expected_ac_secret.
        if is_ac_match_end:
            auth = self.headers.get("X-Server-Secret", "")
            if auth != relay.expected_ac_secret:
                relay.ac_auth_failures.append(CapturedAcPost(
                    match_id=None, server_endpoint=None,
                    raw_body={"_unparsed": raw.decode("utf-8", errors="replace")},
                    auth_ok=False,
                ))
                self._respond(401, {"error": "Unauthorized (AC)"})
                return
        else:
            auth = self.headers.get("X-Relay-Auth", "")
            if auth != relay.expected_secret:
                relay.auth_failures.append(CapturedPost(
                    channel_id=None, raw_body={"_unparsed": raw.decode("utf-8", errors="replace")},
                    auth_ok=False,
                ))
                self._respond(401, {"error": "Unauthorized"})
                return

        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as ex:
            self._respond(400, {"error": f"invalid JSON: {ex}"})
            return
        if not isinstance(body, dict):
            self._respond(400, {"error": "body must be a JSON object"})
            return

        if is_ac_match_end:
            ac_post = CapturedAcPost(
                match_id=body.get("matchId"),
                server_endpoint=body.get("serverEndpoint"),
                raw_body=body,
                auth_ok=True,
            )
            relay.received_ac_match_end.append(ac_post)
            # Production API returns 200 with no body (or empty {}); we
            # mirror that. The plugin's ac_callback only checks
            # CURLINFO_RESPONSE_CODE 2xx, doesn't parse the body.
            self._respond(200, {"ok": True})
            return

        post = CapturedPost(
            channel_id=body.get("channelId"),
            embeds=list(body.get("embeds", [])),
            allowed_mentions=body.get("allowed_mentions"),
            raw_body=body,
            auth_ok=True,
            message_id=body.get("messageId"),
        )
        if self.path == "/reply":
            relay.received.append(post)
            self._respond(200, {
                "id": f"fake-relay-msg-{len(relay.received)}",
                "ok": True,
                "channel_id": post.channel_id,
            })
        else:  # /edit
            relay.received_edits.append(post)
            self._respond(200, {
                "ok": True,
                "channel_id": post.channel_id,
                "id": post.message_id,
            })

    def _respond(self, status: int, body: dict[str, Any]) -> None:
        # Compact JSON (no whitespace between key/value) — KTPMatchHandler's
        # response parser at `ktp_matchhandler_discord.inc:630` looks for the
        # literal substring `"id":"<digits>"` to extract g_discordMatchMsgId.
        # `json.dumps` defaults to `"id": "..."` (with the space after colon),
        # which silently breaks msg-ID capture and the entire create→edit
        # flow. The production Cloud Run relay returns compact JSON, so
        # mirroring that here is correct.
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class FakeRelay:
    """Standalone HTTP mock. Bind to 127.0.0.1:0 (kernel-assigned port);
    `url` exposes the listening base URL. Start in a daemon thread so a
    crashing test doesn't leak the listener."""

    def __init__(
        self,
        expected_secret: str = "test-secret",
        expected_ac_secret: str = "test-ac-secret",
        verbose: bool = False,
    ) -> None:
        self.expected_secret = expected_secret
        self.expected_ac_secret = expected_ac_secret
        self.verbose = verbose
        self.received: list[CapturedPost] = []  # POST /reply (creates)
        self.received_edits: list[CapturedPost] = []  # POST /edit (in-place updates)
        self.received_ac_match_end: list[CapturedAcPost] = []  # POST /api/match/end
        self.auth_failures: list[CapturedPost] = []
        self.ac_auth_failures: list[CapturedAcPost] = []
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("relay not started — call .start() first")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def reply_url(self) -> str:
        return self.url + "/reply"

    @property
    def ac_api_base_url(self) -> str:
        """Base URL for the AC API path. KTPMatchHandler appends
        `/api/match/end` etc. to this; FakeRelay routes `/api/match/end`
        into `received_ac_match_end`."""
        return self.url

    def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("relay already started")
        # Port 0 lets the kernel pick a free ephemeral. Bind 127.0.0.1 only —
        # we never want this listener exposed beyond loopback.
        server = HTTPServer(("127.0.0.1", 0), _RelayHandler)
        server.relay = self  # type: ignore[attr-defined]
        thread = threading.Thread(
            target=server.serve_forever,
            name="fake-relay",
            daemon=True,
        )
        thread.start()
        self._server = server
        self._thread = thread

    def stop(self, timeout: float = 2.0) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._server = None
        self._thread = None

    def reset(self) -> None:
        """Clear all captured posts + auth failures across every route
        (Discord /reply, Discord /edit, AC /api/match/end). Use between
        subtests when a fixture is shared across multiple test functions."""
        self.received.clear()
        self.received_edits.clear()
        self.received_ac_match_end.clear()
        self.auth_failures.clear()
        self.ac_auth_failures.clear()

    # Convenience assertions — keep tests one-line where possible.

    def assert_post_count(self, n: int) -> None:
        if len(self.received) != n:
            raise AssertionError(
                f"expected {n} POSTs to relay, got {len(self.received)}: "
                f"channels={[p.channel_id for p in self.received]}"
            )

    def latest(self) -> CapturedPost:
        if not self.received:
            raise AssertionError("no POSTs received by fake_relay")
        return self.received[-1]

    def __enter__(self) -> "FakeRelay":
        self.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.stop()
