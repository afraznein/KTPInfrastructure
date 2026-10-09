### `scripts`: `ktp-ac-retention.sh` blanks the player names in `ktp_net_intervals` past 90 days (2026-10-09)

Operator ruling, 2026-10-09: the interval metrics stay indefinitely and the names age out,
the same shape ruled for `ktp_net_sessions`.

- A fifth sweep sets the twelve `*_worst_name` / `lagcomp_first_name` columns to NULL on rows
  older than `NET_IDENTITY_RETENTION_DAYS`. The metrics and the `*_slot` columns are untouched.
- Rows are selected only while some name is still set, so a re-run is a no-op and the batched
  loop completes (`ROW_COUNT()` counts changed rows, not matched ones).
- `NET_IDENTITY_RETENTION_DAYS=0` turns it off alongside the sessions sweep, and `DRY_RUN=1`
  prints the count from the same predicate the sweep uses.
- Every run logs `ac-retention: net_intervals identity blanked N row(s)`, including N=0.
- `tests/unit/test_ac_retention_net_intervals_identity.py` runs the shipped script against the
  existing sqlite-backed fake `mysql`, with mutations for the dropped guard, a column missing
  from the list and the dropped zero guard.
- Not run here: the statement against MySQL, or the live column list. The list is from the
  table migrations; the script's header says to recheck it against `information_schema`.
