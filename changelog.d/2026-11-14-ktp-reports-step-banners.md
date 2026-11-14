### `systemd`: `ktp-reports` writes a timestamped start and end line per step (2026-11-14)

When `TimeoutStartSec` fires, the journal records `code=killed` and nothing else, and the log at
`/var/log/ktp-report-service.log` had no timestamps or step names, so a timeout could not be pinned
on generate, aggregate or sync.

- **`scripts/report_step.sh`** wraps each `ExecStart`. It writes
  `<UTC> ktp-reports step=<name> start` before the step and `... end rc=<n> elapsed=<s>s` after,
  passes the step's exit code through unchanged (systemd still stops at the first failure), and on
  SIGTERM writes `... killed signal=TERM` and forwards the signal. A `start` with no `end` is the
  step a timeout took.
- **`Environment=PYTHONUNBUFFERED=1`**, so a killed step's last progress line reaches the log
  instead of dying in Python's buffer.
- `report_regen_guard.unit_floor` still reads the season floor through the wrapped line, and
  `verify_report_pipeline.py`'s anchored generate head/tail patterns do not match the new lines.
- **`tests/unit/test_report_step.py`**: clean run, failing run, TERM, a mutation without the trap,
  and that all three unit steps go through the wrapper.

⚠️ **Nothing changes on the box until the serving checkout is brought to `main` and the unit is
reinstalled** (`docs/runbooks/REPORT_PIPELINE_INSTALL.md` § 4).
