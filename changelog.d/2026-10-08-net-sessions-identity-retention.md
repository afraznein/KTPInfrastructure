### `scripts`: ktp_net_sessions keeps its metrics and loses its identity at 90 days (2026-10-08)

Ruled by the operator 2026-10-08. `hlstatsx.ktp_net_sessions` carried `name` and `steam_id`
on 100% of its rows with nothing in that schema pruning anything — `SHOW EVENTS` in `hlstatsx`
returns nothing at all — and the table is 1 MB, so storage was never the question. The ruling
is that the per-connection netcode measurements are worth keeping indefinitely and the identity
is not, which makes this the one sweep that is an `UPDATE`.

- **`scripts/ktp-ac-retention.sh`** gains a fourth sweep:
  `UPDATE ktp_net_sessions SET name = '', steam_id = '' WHERE ts < NOW() - INTERVAL
  NET_IDENTITY_RETENTION_DAYS DAY AND steam_id <> ''`, batched through the same helper as the
  three deletes and logging `net_sessions identity blanked N row(s)` on every run, including
  the nights it blanks nothing. It is the existing cron (04:40 ET, after `ktp-backup`), not a
  new unit — the same blank-rather-than-delete shape the script already uses for `zip_path`.
- `NET_IDENTITY_RETENTION_DAYS` defaults to **90**, and **0 means keep identity forever**.
  The zero guard sits at the sweep as well as in the default, for the reason
  `UPLOAD_RETENTION_DAYS` carries one: `INTERVAL 0 DAY` resolves to `NOW()`, so an unguarded
  0 blanks the whole table instead of none of it.
- The `steam_id <> ''` guard is load-bearing twice. It makes a re-run a no-op, and it is what
  makes the batched loop **complete**: `ROW_COUNT()` on an `UPDATE` counts rows *changed*, so
  without it a second batch can re-select rows it already blanked, report 0, and stop with
  identities still on every row past the first batch.
- `DRY_RUN=1` reports `net_sessions identities past 90d: N` from the same predicate string the
  sweep uses, so the preview and the sweep cannot describe different rows, and says so plainly
  when blanking is off.
- `batched_delete` is now `batched_write(label, sql, verb)` — one batching path for deletes and
  the blanking rather than two. Every table the script touches is InnoDB (measured in
  `KTPAntiCheat` `sql/schema.sql`: 24 `ENGINE=InnoDB`, 0 MyISAM), so a batch takes row locks
  and readers are never blocked; what batching bounds here is undo size, not lock scope. At
  ~97 rows/day the blanking will never approach one batch, and it inherits the bound anyway.
- **`tests/unit/test_ac_retention_net_identity.py`** runs the shipped script whole under bash
  with a fake `mysql` first on `PATH`, backed by stdlib sqlite3 and translating exactly
  `NOW() - INTERVAL n DAY` and `UPDATE/DELETE … LIMIT n` while emulating MySQL's changed-rows
  `ROW_COUNT()`. The fake exits non-zero on a statement shape it does not recognise rather
  than returning a plausible zero. Rows are seeded on **both** sides of the boundary, a test
  asserts that straddle so the suite cannot pass on a vacuous fixture, and six mutations of the
  shipped script — inverted comparison, no horizon, dropped `<> ''` guard, dropped zero gate,
  removed log line, removed dry-run count — each redden a named leg.
- Known skew, immaterial at this horizon and worth knowing before anyone tightens it:
  `ktp_net_sessions.ts` is log-local ET while `NOW()` is the database clock, so the effective
  horizon is 90 days ± the offset between them.
