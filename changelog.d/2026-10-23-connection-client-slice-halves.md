### `analytics`: `connection.players[].halves` — the per-half client slice beside the settings it ran with (schema 34, DTO v1.15.0) (2026-10-23)

Coordination workstream `netcode-player-settings`. A player's "very jittery" → "fine" cmdrate
change moved nothing the fleet recorded, because what changed was client frame pacing and
per-command `usercmd.msec` was persisted nowhere. KTP-ReHLDS #48 now emits a per-client slice
at every match boundary (`net_client:`), KTPCvarChecker 7.43 logs the five net cvars the client
declared (`NETOBS_SNAPSHOT`), and KTPProfileAggregator #14 writes both to `ktp_net_clients` and
`ktp_client_settings`. This is the report side.

- `build_connection` takes two more row sets and adds `halves[]` to each private player row:
  per half, `msec.{p50,p95,max}` (the client's own frame time, 1000/fps), `arr_ms.{p50,p95,max}`
  (gap between its move packets), `pps`, `cmds_pkt`, `fps_est = pps × cmds_pkt`, `drops`,
  `interp_floor`, `interp_cap`, `stale_delta`, and `settings` — the `why: start` snapshot of
  that half, else the latest at or before the flush. The warmup `prelive` slice is dropped.
- Two new instruments, `client_slice` and `settings`, with the same
  available / not-recorded / unavailable vocabulary; two new `source_capabilities` probes;
  two new fact queries under `sql/analytics/`; two grants in the install runbook.
- **Public DTO shape is unchanged apart from the two instrument flags.** `players[]` stays out
  of the public block (own-row-only ruling, 2026-10-11); the contract documents `halves[]` for
  the private tier. `CONTRACT_VERSION` → v1.15.0, `SCHEMA_VERSION` → 34, so every report
  regenerates and picks the block up as the tables fill (~15 min on the data server, the
  usual cost of a bump).
- Rows exist only for matches after the 2026-10-24 wave; earlier matches read
  `halves: null` with `instruments.client_slice: not-recorded`.
