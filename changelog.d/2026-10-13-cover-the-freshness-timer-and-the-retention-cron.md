### `scripts`: health covers the install-freshness timer and the AC retention cron (2026-10-13)

Two jobs whose silence read as health. `#585`'s install-freshness units cannot be installed without
this, because the runbook requires the timer and its `CRITICAL_TIMERS` entry in one change.

- **`ktp-install-freshness.timer` joins `CRITICAL_TIMERS`.** `OnFailure=` fires when a unit runs and
  fails; nothing fires when a timer stops scheduling it. And the drift this job exists to find is
  itself silent, so **a stopped timer and a clean estate produce the same output: nothing.**
- **The AC retention sweep gets a work-done check, because it can never be a timer entry.** It is a
  `cron.d` job at 04:40 daily, and `CRITICAL_TIMERS` is checked against `systemctl list-timers`,
  which is structurally blind to cron. Measured 2026-10-13, the deployed health script named
  `ac-retention` exactly once — in a comment, with no check behind it. Its only durable artifact is
  `/var/log/ktp-ac-retention.log`, so the mtime is the signal, on the same reasoning as the
  renamer's `state.json`: a hung process reads `active`, so the question has to be whether work
  happened. The window is two days, which tolerates one missed daily run.
- **This sweep is the one that enforces the ruled 105-day token window.** If it stops, nothing
  deletes and nothing says so — the absence of a delete looks exactly like a quiet night.

`absent` and `stale` are separate tokens: *never ran* and *stopped running* are different facts.
Both are fixed strings rather than ages, because the report is a set-diff and a ticking value would
read as a fresh failure on every hourly run.

**Verification, and two findings from it worth keeping.**

- 250 health tests pass. The new leg is extracted from the shipped script **by marker**, so renaming
  or deleting it fails the test rather than testing a copy that no longer ships.
- ⚠️ **The first cut of the test passed while the check could not fire at all.** The extracted leg
  does not carry its own constant, so `AC_RETENTION_STALE_SEC` was empty, `[ N -gt "" ]` errored to
  stderr, and the `if` read false — a broken comparison presenting as "quiet". The harness now
  supplies the shipped default and **asserts stderr is empty**, because without that a quiet result
  proves nothing.
- ⚠️ **Deleting the `CRITICAL_TIMERS` entry passed the entire health suite silently** until a
  mutation test looked. That is the same shape as the gap being closed, so it now has an assertion
  naming it. Both additions are mutation-checked in both directions.
