### `services`: ktp-nettest, the per-region connection test node (2026-10-25)

`services/ktp-nettest/` is the node behind the planned "Test my connection" button on a
player's own page. drew ruled it 2026-10-25: self-hosted per region (Ookla measures the route to
Ookla, not to our boxes), signed-in players only, blocked while any match is live on that host,
and every run carries the player's own notes ("on ExitLag", "at the in-laws").

- **Stall test first**: 60 s of 100 packets/s over an unordered, no-retransmit WebRTC data
  channel, echoed by the node. Loss, jitter, and every gap over 250 ms — the 1.2–1.5 s stalls
  baron's match reports showed, which a TCP speed test retransmits away. Then ping/jitter and
  download/upload, each capped at 25 MB or 8 s.
- **Signed-in only, enforced at the node**: every test request carries an HMAC-SHA256 run ticket
  minted by the website (`KTP_NETTEST_TICKET_SECRET`); one run per player per 10 minutes.
- **Live-match block from the host's own logs**: `KTP_MATCH_START` without a later
  `KTP_MATCH_END` (2 h cap) in either of each instance's two newest logs — two, so the map change
  between halves does not open a window. Unreadable logs count as busy. A busy refusal does not
  spend the player's run.
- `client.js` is served by the node and is the whole browser side: the website calls
  `KtpNettest.runTest()` and posts the row (with the player's `said_*` picks) to its own table.

Not deployed. Hosting, the UDP range, TLS in front of the node, the website route, ticket
minting and the `ktp.connection_test` table are afraznein's (coordination workstream
`netcode-player-settings`).
