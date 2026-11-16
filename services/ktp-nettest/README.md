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
| `GET /frame` | no | the page the website embeds in a sandboxed iframe; loads `client.js` and `frame.js` in this node's origin |
| `GET /frame.js` | no | the `postMessage` bridge between that page and the website |
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
Unreadable logs, or no log dirs configured, count as busy. So does a log too large for the
16 MB read window: a tail that may have cut off a START proves nothing by not containing one.
A log read whole with no START is a real measurement and stays not-busy, which matters because
most logs on this fleet are pub and warmup logs that carry no match markers at all. Cached
15 s. A run already past its stall test when the host turns busy skips the rest and says so
(`busy_skipped: true`).

## Using the client

The website never loads `client.js` into its own origin. It embeds `GET /frame` in a sandboxed
iframe, so the measuring code runs in this node's origin and a wrong or compromised node can reach
nothing of the site's (its cookies, storage, DOM, or server actions):

```html
<iframe sandbox="allow-scripts allow-same-origin" src="https://<node>/frame"></iframe>
```

`allow-same-origin` keeps the frame in the node's own origin, which is what lets its requests to
the node stay same-origin; it does not give it the site's. The frame and the site talk only by
`postMessage`, each side checking the other's exact origin (`KTP_NETTEST_ORIGIN` here, the node's
origin on the site):

| Direction | Message |
|---|---|
| node → site | `{type: "ktp-nettest:ready", version}` once loaded |
| site → node | `{type: "ktp-nettest:run", ticket}` |
| node → site | `{type: "ktp-nettest:progress", phase, done}` |
| node → site | `{type: "ktp-nettest:result", result}` — result as below |
| node → site | `{type: "ktp-nettest:error", busy, message}` — `busy` when a match went live |

`/frame` answers with its own CSP: only this node's scripts, requests only to this node, and
`frame-ancestors` set to `KTP_NETTEST_ORIGIN`, so no other site can embed it.

The result carries `stall_seconds, stall_sent, stall_loss_pct, stall_rtt_ms, stall_jitter_ms,
stall_gaps_250, stall_worst_gap_ms, ping_ms, jitter_ms, down_mbps, up_mbps, busy_skipped,
client_version`. The page adds the player's picks (`said_connection`, `said_routing`,
`said_where`, `said_note`) and posts the row to the website. `client.js` can still be
`require()`d in Node, which is how the tests drive it.

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
| `KTP_NETTEST_PORT` / `_BIND` | `8790` / `0.0.0.0` | HTTP; put TLS in front (the site is https, so the browser refuses a plain-http node). The deploy kit sets `127.0.0.1`, so nginx is the only way in |
| `KTP_NETTEST_ORIGIN` | `https://ktpleague.gg` | CORS origin, and the only site that may embed `/frame` |
| `KTP_NETTEST_MAX_STALLS` / `_MAX_TRANSFERS` | `4` / `2` | |

Load on a game host: a stall session is
~100 bytes on the wire × 100/s each way ≈ 80 kbit/s; a transfer is bounded by the player's line for ≤ 8 s.

## Deploy

The kit is in `deploy/`:

| File | Installed as |
|---|---|
| `install.sh` | run from a checkout: `sudo bash deploy/install.sh` |
| `ktp-nettest.service` | `/etc/systemd/system/ktp-nettest.service` |
| `ktp-nettest.service.d/logdirs.conf.example` | `/etc/systemd/system/ktp-nettest.service.d/logdirs.conf`, edited per host |
| `nettest.env.example` | `/etc/ktp/nettest.env`, root-owned, mode 600 |
| `nginx-ktp-nettest.conf.example` | the node's nginx vhost |

`install.sh` creates the `ktpnettest` system user, copies the app to `/opt/ktp-nettest`, runs
`npm ci --omit=dev`, installs the unit, and installs the env file and the drop-in only when they
do not exist yet. It reloads systemd when the unit changed. It never enables, starts or restarts
the service, and it is safe to re-run after a pull.

The unit runs with `ProtectHome=tmpfs`: `/home` is empty inside the sandbox, so the game trees and
the rcon password in every `dodserver.cfg` are out of reach. The drop-in mounts back each
instance's `dod/logs`, read-only, and nothing else. Keep it in step with `KTP_NETTEST_LOG_DIRS`.
A dir in the env but not in the drop-in is unreadable, and unreadable logs count as busy.

`RestrictAddressFamilies` must include `AF_NETLINK`. werift gathers its host candidates with
`os.networkInterfaces()`, which is `getifaddrs` over a netlink socket; without it every
`POST /stall/offer` fails with `uv_interface_addresses returned Unknown system error 97`
(EAFNOSUPPORT). `systemd-analyze verify` cannot catch this, because the unit is valid either way;
only a real offer exercises it. To check the sandbox as the service user:

```
systemd-run --wait --pipe -p User=ktpnettest \
  -p RestrictAddressFamilies="AF_INET AF_INET6 AF_UNIX AF_NETLINK" \
  /usr/bin/node -e 'console.log(Object.keys(require("os").networkInterfaces()).join())'
```

### Order

Each step is checked before the next one starts.

1. **DNS.** An A record for the node's hostname, pointing at the host. Check that it resolves.
2. **Packages.** Node.js 20 or newer at `/usr/bin/node` (Ubuntu 24.04's own `nodejs` is 18, too
   old), nginx and certbot. `install.sh` refuses an older or missing node.
3. **Firewall.** Open HTTP, HTTPS and exactly the WebRTC range in `KTP_NETTEST_UDP_PORTS` (UFW
   writes a range with `:`, the env var with `-`):

   ```
   ufw allow 80/tcp comment "ktp-nettest ACME and redirect"
   ufw allow 443/tcp comment "ktp-nettest"
   ufw allow 40000:40100/udp comment "ktp-nettest WebRTC"
   ```

   Never open 8790. The node binds `127.0.0.1` and nginx is the only way in.
4. **Install.** `sudo bash deploy/install.sh`, then set `KTP_NETTEST_REGION` and
   `KTP_NETTEST_TICKET_SECRET` in `/etc/ktp/nettest.env` and fix `logdirs.conf` for this host.
   The node refuses to start (exit 2, reason in the journal, no restart loop) while the secret is
   missing, still the example placeholder, or shorter than 32 characters. The secret is the one
   the site holds, the same for every node; compare the two ends by sha256, never by printing.
5. **Start and check locally.** `systemctl enable --now ktp-nettest` is a separate, deliberate
   step. Then `curl -s http://127.0.0.1:8790/busy` must say `"busy":false` on a host with no live
   match. `"busy":true` on an idle host means the logs are unreadable inside the sandbox (a dir
   missing from the drop-in, or permissions that deny `ktpnettest`), and from the site that looks
   exactly like a match in progress. To check one dir the way the service sees it:

   ```
   systemd-run --wait --pipe -p User=ktpnettest -p ProtectHome=tmpfs \
     -p BindReadOnlyPaths=/home/dodserver/dod-27015/serverfiles/dod/logs \
     ls /home/dodserver/dod-27015/serverfiles/dod/logs
   ```
6. **TLS.** Install the vhost's port-80 server alone, issue the certificate with
   `certbot certonly --webroot -w /var/www/letsencrypt -d <host>`, then add the 443 server,
   `nginx -t` and reload. Check from outside the host: `https://<host>/busy` returns JSON, and
   `https://<host>/frame` carries a `content-security-policy` ending in
   `frame-ancestors https://ktpleague.gg`. The vhost turns off proxy buffering in both directions
   (otherwise the bandwidth test measures nginx, not the player's line) and allows 26 MB bodies so
   that the node, not nginx, refuses an upload past 25 MB.

   A webroot renewal does not reload nginx, so nginx keeps serving the old certificate until it
   expires. Install a deploy hook, `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh`
   (mode 755):

   ```
   #!/bin/sh
   systemctl reload nginx
   ```

   A plain `certbot renew --dry-run` skips deploy hooks, so a green dry run does not prove the hook.
7. **Only now, the site.** Add the node to `KTP_NETTEST_NODES` in Vercel Production, e.g.
   `{"NY":"https://<host>"}`, with the key equal to `KTP_NETTEST_REGION`, and deploy production.
   TLS comes first because the site accepts only `https://` node URLs and drops any other, and
   because a listed node that cannot answer over https offers players a region that fails every
   run. The redeploy is needed because the site's CSP `frame-src` is computed at build, so setting
   the variable alone changes nothing.
8. **End to end on production.** Run the test signed in on ktpleague.gg.

### Previews cannot run the test

The node answers CORS for exactly one origin and lets exactly that origin frame `/frame`:
`KTP_NETTEST_ORIGIN`, `https://ktpleague.gg` by default. A Vercel preview is a different origin, so
the browser refuses the frame there and the test can only be exercised on production. Do not
widen `KTP_NETTEST_ORIGIN` to make a preview work: `frame-ancestors` is what stops any other site
from embedding the node.

### CPU placement

On the four baremetals the game instances pin to cpu2-7 under `isolcpus`, and cpu0 and cpu1 are
the housekeeping cores that also take the NIC interrupts. The drop-in pins the node to those two
(`CPUAffinity=0 1`, with the unit's `Nice=10`), so it never runs on a game core. They are still
hyperthread siblings of cpu4 (27017) and cpu5 (27016), so a test during a pub shares a physical
core with those two instances; the live-match block keeps tests off a host while any match on it
is live. Chicago has no `isolcpus` and its instances are pinned across its vCPUs including cpu0,
so delete the `CPUAffinity` line there.

## Tests

`npm test` — ticket and busy-gate units, stall arithmetic, and an end-to-end run against a real
server with werift standing in for the browser's WebRTC (about 15 s). `test/mdns.test.js` drives
an offer whose candidates are all mDNS `.local` names, as a real browser sends, and one with the
interface lookup refused.
