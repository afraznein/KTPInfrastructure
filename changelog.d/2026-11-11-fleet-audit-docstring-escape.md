### `scripts`: the fleet audit stops printing a SyntaxWarning on every run (2026-11-11)

`scripts/audit-fleet-drift.py` had a `\%` in its module docstring, inside a crontab
example for the retired `/opt/ktp-infra` cron. Python 3.12 prints a SyntaxWarning for
it at the top of every run, so it showed up in each weekly audit log and the triage
kept having to explain it away. The deployment notes now point at
`.github/workflows/fleet-audit.yml` instead of the old cron line.

A new unit test compiles every `scripts/**/*.py` and fails on any SyntaxWarning. It
fails on the old file and passes now. Later Python releases turn these escapes into
SyntaxErrors, and then the script would not start at all.

### `ci`: the fleet-audit triage gets a turn cap it can finish inside (2026-11-11)

The triage step's `--max-turns 45` failed run 42955296706 after Claude had already
finished, at 47 turns, so the publish step was skipped and nothing was posted. This
is the second time; run 34990174564 failed the same way. The cap is 100 now. That
run averaged about 11 seconds a turn, so 100 turns still fits inside the job's
20-minute timeout, which is the limit that actually matters.
