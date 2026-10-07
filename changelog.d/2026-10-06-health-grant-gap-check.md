### `health`: a new `ktp_*` table without a SELECT grant now pages (2026-10-06)

A missing per-table grant does not read as "denied" anywhere a consumer looks.
`information_schema` hides what the asking account cannot see, so a capability probe
reports the table **absent** and the caller concludes the migration never ran.

That mistake has now been made three times, always from the same trigger — a new table
lands and nobody grants it:

- **2026-09-22:** `ktp_hitreg_quality` read as "migration 036 is not applied". It was
  applied; `SELECT` returned `ERROR 1142` and `information_schema` showed nothing.
- **2026-09-22 → 09-27:** the hitreg monitor's own output was unreadable for five days
  behind `dpl-1c9f`, a single `GRANT` that sat waiting on the wrong person.
- **2026-10-05:** `ktp_move_census` blocked `dpl-1089`'s verification. `ktp_aim_vis` was
  created the same day and arrived ungranted too.

`ktp-data-server-health.sh` now runs the authoritative check hourly — a `LEFT JOIN`
against `information_schema.TABLE_PRIVILEGES`, which is the only reliable way to ask
(diffing root-visible tables against unprivileged-visible ones with `comm` mis-sorts
silently and reported 23–24 where the real number is 19).

**It alerts rather than logging.** A log line would not have helped: this file is
`root:root 0640` and nobody reads it. Alerting is only affordable because the reducer
filters the tables that are ungranted *on purpose* — the four credential stores,
`ktp_ac_players` (which carries `password_hash`), and the dated `_bak_`/`_snap_` copies.
A deliberately locked table that is not matched there will page once; add it to the
reducer with a reason rather than widening the pattern.

Two tables are filtered as a **holding position, not a ruling**:
`ktp_ac_detector_review_notes` (contains detection `predicate`s — the published-evasion
-recipe concern) and `ktp_ac_identity_review_notes` (free text about named players). If
those are ruled readable, grant them and drop them from the reducer.

`tests/unit/test_health_grants.py` extracts the reducer from the shipped script by marker
and pins the current box state silent, a new table loud, and `ktp_foo_bak` — backup-shaped
but undated, so a live table — loud. The policy is testable without a database or any
privilege; the query was verified separately against the box and returns the expected 19.
