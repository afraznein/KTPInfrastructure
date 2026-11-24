### `ops`: a daily timer for the AC migrations-applied check (2026-11-11)

`KTPAntiCheat`'s `check-migrations-applied.py` ran in no workflow and cannot, because it needs the
data server. This adds `ktp-migrations-applied-check.{service,timer}` with its `OnFailure=`
drop-in, plus `scripts/ktp-migrations-applied-check.sh`, which fetches that repo's
`origin/main`, snapshots the schema over the local socket, and runs the checker. A finding or
a could-not-check fails the unit. A success stamp, written only on a verdict, is aged by a new
`ktp-data-server-health.sh` leg that stays silent until the timer is installed. Not installed:
that is an operator `dpl-` act. Runbook: `docs/runbooks/MIGRATIONS_APPLIED_CHECK.md`.
