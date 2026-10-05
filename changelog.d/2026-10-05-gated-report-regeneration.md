### `ci`: report regeneration is a dispatched workflow behind the operator's approval (2026-10-05)

`.github/workflows/report-regeneration.yml` regenerates match reports on the
tier-2 runner (root on the data server) when someone with write access
dispatches it and the operator approves the `report-regeneration` environment.
`dry_run` defaults to on. `scope=pending` starts `ktp-reports.service`, the same
unit the timer runs, so it cannot overlap a tick; `scope=match_ids` writes a new
revision for named matches first and refuses when the next tick is too close.

`scripts/report_regen_guard.py` refuses a dirty serving checkout, one that is not
at the fetched `origin/main`, and a dispatch from any other commit. It fetches
one ref with `--refmap=` and never moves the tree. `scripts/report_regen_summary.py`
turns the pipeline's output into counts for the public job summary; the output
itself stays in a root-only log on the box. `report_service generate` gains
`--dry-run`.

Tests: `tests/unit/test_report_regeneration.py`. Against `origin/main`'s
`report_service.py` the dry-run test fails (`unrecognized arguments: --dry-run`).
