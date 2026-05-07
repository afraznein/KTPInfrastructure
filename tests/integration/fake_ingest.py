"""fake_ingest — stdlib HTTP mock of the DoD-hud-observer Node ingest.

Replaces the production data-server backend
(`http://data:8088/ingest`) during integration tests. Captures POSTed
event envelopes into an in-memory list so tests can assert what
KTPHudObserver would have shipped to the HUD backend, without booting
the Node + React stack.

Sister mock to `fake_relay.py` — same stdlib http.server + threading
shape. Kept as a separate file (vs adding another route to FakeRelay)
because Discord-relay and HUD-ingest are unrelated downstream systems
with different auth headers, different envelope shapes, and different
maintainers; co-locating them would tangle two unrelated test surfaces.

## Contract this mock implements

The production ingest accepts (verified against
`DoD-hud-observer/backend/src/handler/ingest.ts:319-392`):

  POST <any path>
    Headers:  X-Auth-Key:           <secret>          (required)
              X-Server-Hostname:    <hostname>?       (optional, used for
                                                       per-server state cache)
              X-Plugin-Sent-At:     <unix-ms-string>? (optional, used for
                                                       latency metrics)
              Content-Type:         application/json
    Body:     {"event": "<name>", ...arbitrary other fields}

              Top-level envelope fields the plugin's `post_event` helper
              prepends to every event (see KTPHudObserver.sma:257-274):
                tick            float, get_gametime() at send
                plugin_sent_at  unix ms (server-local)
                match_id        present iff a match is active
                map             present iff a match is active
                match_type      present iff a match is active
                half            present iff a match is active

  Returns:    200 {"ok": true}        on success
              401 {"error": "unauthorized"}      auth-header mismatch
              400 {"error": "missing event field"}   body parsed but no `event` key
              400 {"error": "invalid JSON: ..."}     body unparseable

The path component of the URL is NOT validated — production ingest is
mounted on `/ingest`, but the plugin's `dod_hud_url` cvar carries the
full URL, so a test fixture pointing the cvar at `http://127.0.0.1:N/`
(no `/ingest` suffix) works just as well. We accept any POST path and
record the full path on each captured event for tests that want to
assert routing.

## Why separate from fake_relay (which already routes 3 paths)

  1. Auth-header schema differs: ingest uses `X-Auth-Key`, relay uses
     `X-Relay-Auth` (Discord) / `X-Server-Secret` (KTPAntiCheat). Mixing
     them in one mock multiplies the dispatch logic with no payoff.
  2. Envelope contract differs: relay POSTs `{channelId, embeds, ...}`
     (multi-embed Discord shape); ingest POSTs single-event
     `{event, tick, match_id, ...}`. The captured-list dataclass shapes
     are unrelated.
  3. Failure-mode boundaries: a bug in the relay-mock should not
     mass-skip the HUD-contract suite, and vice versa. Separate
     listeners give independent stop/start lifecycle and independent
     reset() semantics.
  4. Ownership: the HUD test surface is owned by DoD-hud-observer; the
     relay surface is owned by KTPMatchHandler / Tony. A future split
     of integration-test ownership is cleaner if the mocks are already
     decoupled.

## Usage

    from .fake_ingest import FakeIngest

    ingest = FakeIngest(expected_auth_key="test-hud-key-123")
    ingest.start()
    try:
        # KTPHudObserver would POST to ingest.url with the test cvar value
        # ... drive the system under test ...
        assert len(ingest.received) == 1
        assert ingest.received[0].event == "ktp_match_start"
    finally:
        ingest.stop()

Or as a pytest fixture (see `conftest.py:fake_ingest`).
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


@dataclass
class CapturedIngest:
    """One recorded HUD-ingest POST. Tests assert against these.

    Field accessors mirror the named envelope fields the plugin always
    injects (`post_event` in KTPHudObserver.sma:257-274) so test code
    reads naturally:

        post.event              # always present (validated by the mock)
        post.match_id           # None if posted while no match active
        post.tick               # float, plugin's get_gametime() at send
        post.plugin_sent_at     # int, plugin's get_systime() * 1000 at send
        post.server_hostname    # from X-Server-Hostname header (or None)
        post.raw_body           # full parsed JSON for richer assertions

    `auth_ok` follows fake_relay's convention — auth-failed posts are
    rejected with 401 and recorded into `auth_failures` (separate list)
    rather than polluting `received`.
    """
    event: str
    match_id: str | None = None
    tick: float | None = None
    plugin_sent_at: int | None = None
    server_hostname: str | None = None
    plugin_sent_at_header: str | None = None
    path: str = "/"
    raw_body: dict[str, Any] = field(default_factory=dict)
    auth_ok: bool = True


class _IngestHandler(BaseHTTPRequestHandler):
    """Per-request handler. Routes any POST path; reaches into
    `self.server.ingest` (set by FakeIngest.start) for state."""

    def log_message(self, format: str, *args: Any) -> None:
        # Quiet by default — mirrors fake_relay.log_message.
        if getattr(self.server, "ingest", None) and self.server.ingest.verbose:
            super().log_message(format, *args)

    def do_POST(self) -> None:
        ingest: FakeIngest = self.server.ingest  # type: ignore[attr-defined]

        # Read body up to Content-Length. Refuse unbounded reads (same
        # 1 MB ceiling fake_relay uses; HUD events fit in <10 KB easily).
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 1_000_000:
            self._respond(400, {"error": "missing or oversized Content-Length"})
            return
        raw = self.rfile.read(length)

        # Auth check — production backend reads `X-Auth-Key` (case-
        # insensitive per HTTP) and rejects mismatches with 401.
        # `BaseHTTPRequestHandler.headers` is a Message instance with
        # case-insensitive lookup, so this matches production behavior.
        auth = self.headers.get("X-Auth-Key", "")
        if auth != ingest.expected_auth_key:
            ingest.auth_failures.append(CapturedIngest(
                event="<auth-rejected>",
                path=self.path,
                raw_body={"_unparsed": raw.decode("utf-8", errors="replace")},
                auth_ok=False,
            ))
            self._respond(401, {"error": "unauthorized"})
            return

        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as ex:
            self._respond(400, {"error": f"invalid JSON: {ex}"})
            return
        if not isinstance(body, dict):
            self._respond(400, {"error": "body must be a JSON object"})
            return

        event_name = body.get("event")
        if not event_name or not isinstance(event_name, str):
            self._respond(400, {"error": "missing event field"})
            return

        sent_at_header = self.headers.get("X-Plugin-Sent-At")
        post = CapturedIngest(
            event=event_name,
            match_id=body.get("match_id"),
            tick=body.get("tick"),
            plugin_sent_at=body.get("plugin_sent_at"),
            server_hostname=self.headers.get("X-Server-Hostname"),
            plugin_sent_at_header=sent_at_header,
            path=self.path,
            raw_body=body,
            auth_ok=True,
        )
        ingest.received.append(post)
        self._respond(200, {"ok": True})

    def _respond(self, status: int, body: dict[str, Any]) -> None:
        # Compact JSON. The plugin's `on_post_complete` callback only
        # checks the HTTP status code; the body shape is informational.
        # Keeping it compact mirrors the Node Express default.
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class FakeIngest:
    """Standalone HTTP mock for the HUD ingest endpoint. Loopback-only;
    daemon thread; ephemeral kernel-assigned port."""

    def __init__(
        self,
        expected_auth_key: str = "test-hud-auth",
        verbose: bool = False,
    ) -> None:
        self.expected_auth_key = expected_auth_key
        self.verbose = verbose
        self.received: list[CapturedIngest] = []
        self.auth_failures: list[CapturedIngest] = []
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("ingest mock not started — call .start() first")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/ingest"

    @property
    def base_url(self) -> str:
        """URL without the `/ingest` path suffix. Useful for tests that
        want to verify the plugin tolerates trailing-slash variations."""
        if self._server is None:
            raise RuntimeError("ingest mock not started — call .start() first")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("ingest mock already started")
        # Bind 127.0.0.1:0 — kernel picks port; loopback only.
        server = HTTPServer(("127.0.0.1", 0), _IngestHandler)
        server.ingest = self  # type: ignore[attr-defined]
        thread = threading.Thread(
            target=server.serve_forever,
            name="fake-ingest",
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
        """Clear captured posts + auth failures. Use between subtests
        when sharing a session-scoped FakeIngest across multiple test
        functions."""
        self.received.clear()
        self.auth_failures.clear()

    # -- Convenience filters / assertions --------------------------------

    def events_of_type(self, event_name: str) -> list[CapturedIngest]:
        """All captured posts where `event` matches event_name. Order-
        preserving, matches the order the plugin sent them."""
        return [p for p in self.received if p.event == event_name]

    def latest_of_type(self, event_name: str) -> CapturedIngest:
        """Most recent post of the given event type. Raises with a
        helpful message if no such post exists."""
        matches = self.events_of_type(event_name)
        if not matches:
            seen = sorted({p.event for p in self.received})
            raise AssertionError(
                f"no captured POST with event={event_name!r}; "
                f"received events: {seen}"
            )
        return matches[-1]

    def assert_post_count(self, n: int) -> None:
        if len(self.received) != n:
            raise AssertionError(
                f"expected {n} POSTs to fake_ingest, got {len(self.received)}: "
                f"events={[p.event for p in self.received]}"
            )

    def latest(self) -> CapturedIngest:
        if not self.received:
            raise AssertionError("no POSTs received by fake_ingest")
        return self.received[-1]

    def __enter__(self) -> "FakeIngest":
        self.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.stop()
