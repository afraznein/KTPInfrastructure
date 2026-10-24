### `analytics`: a half is the sum of its 60 s client slices, and the slices are published as `minutes[]` (schema 35, DTO v1.16.0) (2026-10-24)

KTPCvarChecker 7.44 flushes the engine's per-client net slice every 60 s while a half is live,
so `ktp_net_clients` holds several rows per player per half. `connection.players[].halves[]`
(private tier) now sums them -- `span_s`, `drops`, `interp_floor`, `interp_cap`, `stale_delta`
exact; `pps` and `cmds_pkt` recomputed from the summed packets and commands; `msec`/`arr_ms`
`max` exact; p50/p95 the weighted median of the minutes' own percentiles (an exact half
percentile needs histogram buckets from the engine). Each half also carries `minutes[]`, so a
chat complaint (coordination FINDING_chat-anchors_20261024.md) can be read against that player's
own minute. A half that arrived as one row reads exactly as before and has `minutes: null`.
Public block unchanged. Coordination workstream `netcode-player-settings`.
