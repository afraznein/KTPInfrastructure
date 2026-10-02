### `fleet-audit`: a run whose reporting fails no longer spends the drift delta (2026-10-01)

Every check in the `collect` job wrote its "since last run" baseline into
`/var/lib` as it ran: the audit's `ktp-audit-state-ci.json`, the distribute
check's `ktp-distribute-drift-ci.json`, and the gate's two transition baselines.
`triage` and `notify` come after, so a run whose triage or Discord notice failed
had already consumed the delta, and the next Monday compared against the state
the failed run left behind and reported nothing.

`scripts/fleet-audit-state.sh` splits that into two phases. `collect` seeds a
per-run candidate directory (`/var/lib/ktp-fleet-audit-ci-pending/<run_id>/`)
from the committed files and points every check at it. A new last job,
`promote`, copies the candidates back, and runs only when `collect` succeeded
and either nothing needed triage or both `triage` and `notify` succeeded. A
manual dry run posts nothing, so it no longer spends anything either.

Promotion is idempotent, so re-running a failed notify and then `promote` is
safe. It refuses, and writes nothing, when a committed file has moved since the
run seeded it, so re-running an old run cannot roll a newer baseline back.
Tested in `tests/unit/test_fleet_audit_state.py`, including a control showing the
in-place shape loses an unreported change and that the wiring check rejects the
previous workflow.
