### `monitoring`: the weekly outlier report reads the engine's per-client counters (2026-10-11)

`ktp_net_intervals` keeps only the server's worst client per 10 s window, so until now a
player's connection in the weekly report was a "was worst" share. `hlstatsx.ktp_net_sessions`
(KTP-ReHLDS `net_session`, ingested since 09-21) holds the engine's own per-client counters for
the connection that ended in each match — latency avg/max, jitter_avg, loss, drops per packet.
The report now joins them to every player-half (the longest session per player per match; the
figures repeat on both halves because they are per connection) as `sess_jitter`, `sess_lat_max`,
`sess_loss_max`, `sess_drop_pct`, and uses them in the chronic ranking, the short-term movers and
the per-half z columns.

First run: 24% of player-halves carry a session (only connections that ended in-match, only since
09-21). The engine columns already name what the share hid — a player at 1.3% packet drop with a
6% drops-worst share because a noisier neighbour always held the slot — and separate "worst on
the box" from "bad connection": kroD- reads 76% jitter-worst and 4–5 ms engine jitter at once.

Also: `match_analytics.build_connection` rounds its floats to three decimals (MySQL FLOAT noise
such as `127.0999984741211` was reaching the report). Runtime of the all-types run is ~4 min.
