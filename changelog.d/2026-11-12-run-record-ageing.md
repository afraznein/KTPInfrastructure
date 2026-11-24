### `scripts`: the health sweep ages unit run records (2026-11-12)

`ktp-run-record.sh` gave every wrapped unit a dated file per run, but nothing read
them, so a run killed past its timeout or a unit that stopped being run left no alert.
The ageing leg is the producer `docs/runbooks/UNIT_RUN_RECORDS.md` and
`OBSERVABILITY_PLAN.md` section 2.1 already ruled it should be.

- `scripts/ktp-data-server-health.sh`: new `ktp-run-record-age` block. For seven
  wrapped units it reports `<unit>-run-record=stale` when the newest `runs/*.txt` is
  older than the unit's cadence plus room for one late run, `=unfinished` when the
  newest file is a `.part` older than its start timeout plus the stop window, and
  `=none` when an installed, wrapped unit has written nothing within one ceiling. Fixed
  tokens; the age goes in the alert note. `ktp-render-banlist` and
  `ktp-migrations-applied-check` are left to their existing legs.
- `tests/unit/test_health_run_record_age.py` (new): fires on back-dated fixtures, stays
  silent on fresh ones, and fails when a wrapped unit in `scripts/systemd/` is neither
  aged nor exempted, or when a ceiling falls outside its timer's cadence or below its
  `TimeoutStartSec=`.
- `docs/runbooks/UNIT_RUN_RECORDS.md`, `docs/runbooks/ALERT_COVERAGE.md`,
  `OBSERVABILITY_PLAN.md`: the leg, its tokens, and the fact that for
  `ktp-telemetry-export` (not in `CRITICAL_TIMERS`) it is the only stopped-running leg.

Deploy: reinstall `scripts/ktp-data-server-health.sh` to `/usr/local/bin/`. No unit,
timer or service change.
