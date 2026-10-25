# ktp-nettest — per-region connection test node

The node behind "Test my connection" on ktpleague.gg. A signed-in player runs it from their own
page; the results land on their profile with their notes ("on ExitLag", "at the in-laws"), and
feed the netcode settings matrix as the player's measured upload and stall figures.

Design and rulings: `research/netcode-player-settings/DESIGN_connection-test_20261025.md` in the
coordination repo.

## What it measures

| Part | How |
|---|---|
| **Stall test** (first) | 60 s of 100 packets/s over a WebRTC data channel, unordered and no retransmits (UDP-like). The node echoes each packet; the browser computes loss, jitter, and every gap > 250 ms. TCP tests hide exactly the short stalls that cost a player the round. |
| Ping, jitter | 20 `GET /ping` round trips (first dropped: connection setup) |
| Download / upload | streamed `GET /down` and 1 MB `POST /up`s, each capped at 25 MB or 8 s |

## Routes

| Route | Ticket | Answer |
|---|---|---|
| `GET /busy` | no | `{"region", "busy"}`, for the page's region list |
| `GET /client.js` | no | the browser client, so the site always runs the build this node speaks |
| `GET /ping` | yes | 204 |
| `GET /down?mb=N` | yes | N MB (1–25) of random bytes |
| `POST /up` | yes | `{"bytes"}`, body discarded, refused past 25 MB |
| `POST /stall/offer` | yes | `{"sdp"}`: the WebRTC answer to the browser's offer (body = offer SDP) |

Refusals: `409 {"busy": true}` while a match is live on this host (checked before the ticket, so a
refusal does not use up the player's run), `401` for a missing, forged, expired or other-region
ticket, `429` for a second run by the same player inside 10 minutes, `503` when the node is at
its concurrency cap (4 stall sessions, 2 transfers by default).

## Signed-in players only: run tickets

The website mints a ticket for the signed-in player and the browser passes it as `?t=` on every
test request (a query parameter keeps the GETs simple CORS requests, so no preflight lands inside
a ping):

```
base64url(JSON {"jti", "pid", "region", "exp"}) + "." + base64url(HMAC-SHA256(secret, first part))
```

`exp` is epoch seconds, 5 minutes out. `jti` is unique per run; one ticket covers every request
of its run. `pid` is the website's player id. `lib/ticket.js` `mint()` is the reference
implementation; the secret is `KTP_NETTEST_TICKET_SECRET`, shared by the website server and every
node and nobody else. The results row is posted to the website, never to the node, so the stored
`player_id` comes from the session, not the browser.

## Live-match block

The node reads the two newest logs of each local game instance (`KTP_NETTEST_LOG_DIRS`) and treats
an instance as live from its last `KTP_MATCH_START` until a later `KTP_MATCH_END`, or 2 hours
after the start if no end arrives. Two logs, not one: each half is its own map, so during the
map change and the second-half warmup the first half's open START sits in the previous log.
Unreadable logs, or no log dirs configured, count as busy. Cached 15 s. A run already past its
stall test when the host turns busy skips the rest and says so (`busy_skipped: true`).

## Using the client

```html
<script src="https://<node>:8790/client.js"></script>
<script>
  const r = await KtpNettest.runTest({ base: 'https://<node>:8790', ticket, onProgress: (p) => … });
  // r: stall_seconds, stall_sent, stall_loss_pct, stall_rtt_ms, stall_jitter_ms, stall_gaps_250,
  //    stall_worst_gap_ms, ping_ms, jitter_ms, down_mbps, up_mbps, busy_skipped, client_version
</script>
```

The page adds the player's picks (`said_connection`, `said_routing`, `said_where`, `said_note`)
and posts the row to the website.

## Running it

```
npm ci --omit=dev
KTP_NETTEST_REGION=NY KTP_NETTEST_TICKET_SECRET=… \
KTP_NETTEST_LOG_DIRS=/home/dodserver/dod-27015/serverfiles/dod/logs:… \
KTP_NETTEST_UDP_PORTS=40000-40100 node server.js
```

| Env | Default | |
|---|---|---|
| `KTP_NETTEST_REGION` | — (required) | must match the ticket's `region` |
| `KTP_NETTEST_TICKET_SECRET` | — (required) | |
| `KTP_NETTEST_LOG_DIRS` | empty → always busy | `:`-separated `dod/logs` dirs on this host |
| `KTP_NETTEST_UDP_PORTS` | OS-chosen | `min-max` range for WebRTC; open it in the host firewall |
| `KTP_NETTEST_PORT` / `_BIND` | `8790` / `0.0.0.0` | HTTP; put TLS in front (the site is https, so the browser refuses a plain-http node) |
| `KTP_NETTEST_ORIGIN` | `https://ktpleague.gg` | CORS origin |
| `KTP_NETTEST_MAX_STALLS` / `_MAX_TRANSFERS` | `4` / `2` | |

`deploy/ktp-nettest.service` is the systemd unit. Load on a game host: a stall session is
~100 bytes on the wire × 100/s each way ≈ 80 kbit/s; a transfer is bounded by the player's line for ≤ 8 s.

## Tests

`npm test` — ticket and busy-gate units, stall arithmetic, and an end-to-end run against a real
server with werift standing in for the browser's WebRTC (about 15 s).
