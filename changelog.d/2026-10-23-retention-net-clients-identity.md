### `scripts`: `ktp-ac-retention.sh` blanks identity in `ktp_net_clients` and `ktp_client_settings` past 90 days (2026-10-23)

KTPProfileAggregator `sql/2026-10-19-001-net-client-slice.sql` adds two per-player tables
(coordination workstream `netcode-player-settings`): the per-client net slice the engine closes
at each match boundary, and the five net cvars the client declared. Both carry `name` and
`steam_id`, and both take the horizon ruled for `ktp_net_sessions` on 2026-10-08: metrics
forever, identity for `NET_IDENTITY_RETENTION_DAYS`, blank rather than delete.

- A sixth sweep runs sweep 4's statement against each table — `name = ''`, `steam_id = ''`,
  same predicate, same `steam_id <> ''` completeness guard, same batching.
- **Each table is probed before it is touched.** The migration is operator-applied in another
  repo and this cron runs daily before it lands; an absent table is logged as
  `ac-retention: <table> identity blanking skipped (table absent)` and the run still reaches
  `done` with rc 0. The probe is `SELECT 1 FROM <t> LIMIT 1`, not `information_schema`, so the
  sqlite-backed test harness can answer it.
- `NET_IDENTITY_RETENTION_DAYS=0` turns both off with the sessions sweep; `DRY_RUN=1` prints the
  count from the sweep's own predicate, or the skip line for an absent table.
- `tests/unit/test_ac_retention_net_clients_identity.py` runs the shipped script against the
  shared fake `mysql` in three states — neither table, one table, both — plus the mutations for
  a table left off the list and a dropped presence guard. The harness gains an `extra_seed`
  hook so a test can create tables the shared seed does not know about.
