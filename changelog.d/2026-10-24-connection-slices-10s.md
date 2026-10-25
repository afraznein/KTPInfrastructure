### `analytics`: `halves[].minutes` becomes `halves[].slices` -- the plugin flushes every 10 s (schema 36, DTO v1.17.0) (2026-10-24)

KTPCvarChecker 7.45 flushes the per-client net slice every 10 s instead of 60 (drew, 2026-10-24),
so each `ktp_net_clients` row is one 10 s slice, aligned to the server's own `net:` windows and
about one respawn wave long. The per-half array is renamed from `minutes[]` to `slices[]` so its
name matches what it holds; every field per row is unchanged, and the half totals are computed as
before. v1.16.0 was merged but never served (the report box is at schema 34), so no consumer read
the old name -- the same reason v1.14.0 removed `players[]` as a minor bump.
Coordination workstream `netcode-player-settings`.
