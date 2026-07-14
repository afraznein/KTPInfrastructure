"""KTPAmxxCurl connection-reuse regression test (guards the 1.3.14 fix).

## What this covers, and why it did not exist before

`fake_relay` used to default to HTTP/1.0, so the mock closed the TCP connection
after every response and libcurl never cached one. That meant tier-2 exercised
amxxcurl's *request* path end-to-end but never its *connection-reuse* path —
which is where every crash in this module's history lives.

The bug 1.3.14 fixed: `CurlSocketCallback` treated `CURL_POLL_REMOVE` as "this
fd is dead" and erased it from `socket_map_`, which owns the asio socket and so
CLOSED the fd. But `CURL_POLL_REMOVE` only means "stop polling this fd" —
libcurl keeps the connection in its keep-alive cache and signals real fd death
exclusively through `CURLOPT_CLOSESOCKETFUNCTION`. So we closed live sockets
underneath libcurl. On reuse, libcurl issued a socket callback for an fd we no
longer had, the code misread it as a c-ares socket, and `WrapTcpSocket` ran on a
closed fd -> EBADF. That is the crash class 1.3.11 had to catch at the
C-callback boundary to stop it reaching `std::terminate()`.

So this test's job is narrow and specific: drive >=2 sequential Discord POSTs
through one server so libcurl reuses a cached connection, and assert the module
handled the reuse silently.

## Why the reuse assertion is load-bearing

`assert_connection_reused()` is not decoration. If libcurl opens a fresh
connection per POST, the reuse path is never entered and "no EBADF appeared"
proves nothing — the test would pass green on the very build it is meant to
catch. The relay counts TCP connections (one handler instance per connection)
separately from requests, so we can prove reuse happened before believing the
silence.

## Expected behavior across builds

  - amxxcurl <= 1.3.13: NO reuse. The module closed the cached connection's fd
    at CURL_POLL_REMOVE, so on the next request libcurl's pre-reuse liveness
    check (extract_if_dead/SocketIsDead, url.c 7.63) finds the fd dead,
    discards the connection SILENTLY, and dials fresh — one TCP connection per
    request. The red condition is `assert_connection_reused()`, not a console
    line: the EBADF/`WrapTcpSocket assign failed` marker needs the racier
    variant (fd number reissued to another transfer between events, i.e.
    concurrency), which this sequential flow does not force.
  - amxxcurl >= 1.3.14: reuse. The socket stays in `socket_map_` after
    CURL_POLL_REMOVE with its asio waits cancelled, only
    CurlCloseSocketCallback ever closes an fd, and match-end requests arrive
    on the connections opened at go-live (verified via strace + fake_relay
    connection counts, 2026-07-13).

Run this against a 1.3.13 stack to confirm it actually goes red — a regression
test nobody has seen fail is a test nobody should trust.

NOTE (2026-07-13): this test originally reported "no reuse" on 1.3.14 too.
That was fake_relay's fault, twice over: (1) it 404'd unknown AC paths
without draining the request body, so the next request on the (correctly)
reused connection was parsed against leftover JSON -> 501 + Connection:
close; (2) `request_count` ignored 404/501 requests while connection_count
counted their accepts, so the reuse arithmetic compared the wrong numbers.
Both fixed in fake_relay.py (body drain before routing, do_GET /health,
raw_request_count as the reuse denominator).

Cross-references:
  - KTPAmxxCurl CHANGELOG 1.3.14-ktp (full root-cause writeup)
  - `src/curl_multi_class.cc:CurlSocketCallback` (the REMOVE branch)
  - conftest.py:discord_relay (session FakeRelay, keep_alive=True)
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from .conftest import _serverfiles_path
from .match_flow import MatchDriver, MatchType


# Console lines that mean the socket lifecycle went wrong. These are
# MF_PrintSrvConsole output (Con_Printf), so they land in qconsole.log, NOT in
# the AMXX logs that log_tail.py reads — hence the local console reader below.
_EBADF_MARKER = "WrapTcpSocket assign failed"

# 1.3.14's own tripwire. Firing means libcurl closed a connection without
# routing it through CLOSESOCKETFUNCTION — i.e. the contract this fix relies on
# was violated. Should never appear; if it does we want to know immediately.
_STALE_ENTRY_MARKER = "stale socket_map_ entry"

# Any other curl-side complaint worth failing on if it shows up during reuse.
_CURL_ERROR_MARKERS = (
    _EBADF_MARKER,
    _STALE_ENTRY_MARKER,
    "FATAL ERROR caught at C-callback boundary",
)


def _console_path(serverfiles: Path) -> Path:
    return serverfiles / "dod" / "qconsole.log"


def _console_size(serverfiles: Path) -> int:
    p = _console_path(serverfiles)
    return p.stat().st_size if p.exists() else 0


def _console_since(serverfiles: Path, offset: int) -> str:
    """Read console output appended since `offset`.

    Byte-offset (not rotation-aware) is fine here: qconsole.log is truncated
    only at server start, and this test never restarts the server.
    """
    p = _console_path(serverfiles)
    if not p.exists():
        return ""
    with p.open("r", encoding="utf-8", errors="replace") as fh:
        fh.seek(offset)
        return fh.read()


def _wait_for_request_count(relay, expected_min: int, timeout: float = 20.0) -> int:
    """Poll until the relay has served >= expected_min requests.

    Discord emission is deferred (a task fires ~200ms after the triggering
    rcon), so a synchronous assertion right after the driver call races the
    plugin.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if relay.request_count >= expected_min:
            return relay.request_count
        time.sleep(0.25)
    return relay.request_count


def test_curl_reuses_cached_connection_without_ebadf(hlds, discord_relay):
    """>=2 sequential POSTs must reuse one TCP connection, silently.

    This is the tier-2 regression guard for KTPAmxxCurl 1.3.14. It fails on
    1.3.13 (EBADF on the reused socket) and passes on 1.3.14.
    """
    serverfiles = _serverfiles_path()
    if serverfiles is None:
        pytest.skip("serverfiles path unavailable — cannot read qconsole.log")

    assert discord_relay.keep_alive, (
        "this test is meaningless without keep-alive: libcurl only reuses a "
        "connection the server holds open. If the session FakeRelay was flipped "
        "back to HTTP/1.0, the reuse path is unreachable and this test would "
        "pass vacuously."
    )

    discord_relay.reset()
    console_start = _console_size(serverfiles)

    # Going live POSTs the persistent match embed (/reply); ending the match
    # PATCHes it (/edit). Two requests to the same host — which is exactly the
    # shape that makes libcurl reach into its connection cache for the second.
    # (The cache lives in the MULTI handle, so a fresh easy still reuses it.)
    driver = MatchDriver(hlds)
    driver.setup_match(MatchType.COMPETITIVE)
    driver.advance_pending()
    driver.advance_live(half=1)
    _wait_for_request_count(discord_relay, expected_min=1)

    driver.end_match(score_team1=3, score_team2=1)

    served = _wait_for_request_count(discord_relay, expected_min=2)

    assert served >= 2, (
        f"expected >=2 relay requests to exercise connection reuse, got "
        f"{served} (/reply={len(discord_relay.received)}, "
        f"/edit={len(discord_relay.received_edits)}, "
        f"auth_failures={len(discord_relay.auth_failures)}). Without a second "
        f"request there is no cached connection to reuse and this test proves "
        f"nothing."
    )

    # Load-bearing: proves the reuse path was actually entered. Without this the
    # silence assertion below is worthless.
    discord_relay.assert_connection_reused()

    console = _console_since(serverfiles, console_start)
    hits = [m for m in _CURL_ERROR_MARKERS if m in console]

    assert not hits, (
        f"amxxcurl errored while reusing a cached connection: {hits}\n"
        f"{discord_relay.raw_request_count} requests arrived on "
        f"{discord_relay.connection_count} connection(s), so reuse definitely "
        f"happened.\n"
        f"'{_EBADF_MARKER}' means the module closed the keep-alive socket "
        f"underneath libcurl (the pre-1.3.14 CURL_POLL_REMOVE bug).\n"
        f"'{_STALE_ENTRY_MARKER}' means libcurl dropped a connection WITHOUT "
        f"calling CLOSESOCKETFUNCTION, breaking the contract 1.3.14 relies on "
        f"— investigate immediately.\n"
        f"--- console tail ---\n{console[-3000:]}"
    )

    # All POSTs must have actually landed, not just failed quietly. A closed-fd
    # reuse can also manifest as a dropped request rather than a console line.
    assert len(discord_relay.received) >= 1, (
        "no /reply POST landed — a reused-but-broken socket can drop the "
        "request silently as well as log EBADF"
    )


def test_relay_keepalive_actually_persists_connections(discord_relay):
    """Mock-side guard: the relay must genuinely hold connections open.

    If this fails, `test_curl_reuses_cached_connection_without_ebadf` is
    vacuous — it would report "no EBADF" simply because no reuse ever occurred.
    Kept separate from the hlds test so a mock regression is diagnosable
    without booting a server.
    """
    import json
    import urllib.request

    assert discord_relay.keep_alive
    discord_relay.reset()

    # urllib keeps the connection alive within a single HTTPConnection.
    from http.client import HTTPConnection

    host, port = discord_relay._server.server_address[:2]  # type: ignore[union-attr]
    conn = HTTPConnection(host, port, timeout=5)
    try:
        for _ in range(3):
            body = json.dumps({"channelId": "123", "embeds": [{"title": "t"}]})
            conn.request(
                "POST", "/reply", body=body,
                headers={
                    "X-Relay-Auth": discord_relay.expected_secret,
                    "Content-Type": "application/json",
                },
            )
            resp = conn.getresponse()
            assert resp.status == 200
            resp.read()  # must drain, or the next request on this conn stalls
    finally:
        conn.close()

    assert discord_relay.request_count == 3
    assert discord_relay.connection_count == 1, (
        f"relay did not persist the connection: 3 requests arrived on "
        f"{discord_relay.connection_count} connections. HTTP/1.1 + "
        f"Content-Length should keep exactly one open."
    )
