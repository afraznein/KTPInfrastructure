### `scripts`: the health sweep also ages the identity reconciler's reports (2026-11-12)

The run-record ageing leg covered the units wrapped by `ktp-run-record.sh`, which
left out `ktp-identity-reconcile`: the one weekly unit that had already lost two
failing runs to the journal. Its own runner, `reconcile-identities-run.sh` in
`keep-the-prac`, keeps the same shape (a dated `reports/<UTC>.txt` promoted from a
`.part`), so nothing new is written on the box; this only reads it.

- `scripts/ktp-data-server-health.sh`: `RUN_RECORD_UNITS` rows take an optional
  records subdirectory and `ExecStart=` runner pattern. `ktp-identity-reconcile` is aged
  on `reports/` with an 8-day ceiling and a 30-minute `.part` ceiling, opted in by
  `reconcile-identities-run` on its `ExecStart=` line. Symlinks are skipped when
  finding the newest record, so the runner's `latest.txt` cannot stand in for a run.
- `tests/unit/test_health_run_record_age.py`: both directions for the reconciler, an
  unfinished `.part`, a fresh `runs/` file that must not vouch for it, the two gate
  negative controls, and the symlink case. The reconciler's cadence and timeout are
  pinned as `FOREIGN` because its unit file lives in `keep-the-prac`.
- `docs/runbooks/UNIT_RUN_RECORDS.md`: the row, why it is shaped differently, and a
  correction to the "journald holds about two days" premise, which no longer holds.
- `docs/runbooks/ALERT_COVERAGE.md`: names the reconciler in the fourth leg.

Deploy: reinstall `scripts/ktp-data-server-health.sh` to `/usr/local/bin/`. No unit,
timer or service change.
