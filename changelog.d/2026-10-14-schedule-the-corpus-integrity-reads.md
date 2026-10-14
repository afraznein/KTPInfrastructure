### `scripts`: the two corpus-integrity definitions now run on a schedule (2026-10-14)

`#646` and `#649` each pinned a re-runnable definition for one of the two position-corpus
defects — an epoch-zero `event_time` and an orphan `match_id` — over all five producer
streams. **Nothing ran either one.** No cron entry, no timer, no CI leg and no runbook
referenced them, so they answered *has the source stopped?* only when a human remembered
the command, and *stopped* is exactly the state that regresses quietly.

**The SQL stays the definition.** The new wrapper issues no `SELECT` of its own; it adds a
schedule, a log and a watermark. Every count, control and threshold stays in the committed
`.sql` files, so changing what "defect" means is still a change there, where the controls
live and where a reviewer looks for them.

- **`scripts/ktp-corpus-integrity-guard.sh`**, installed extensionless as the review guard
  is, run from **`scripts/cron.d/ktp-corpus-integrity-guard`** at 06:35 ET — after the
  06:15 review-integrity guard and clear of the install-freshness window (06:20 plus up to
  5 minutes of jitter), so two readers are not scanning the position corpus at once.
- **Scoped, not whole-corpus.** Both files honour `@since_id` and default it to 0. Unscoped
  they scan everything, which is the right shape for a baseline and the wrong shape for a
  daily. Scoped above the previous reading's `rows_max_id` they answer the only question a
  daily can: did a **new** defective row appear? The files say it themselves — *"orphan_max_id
  against the previous reading's rows_max_id answers accrual"*.
- **Alerting copied from `ktp-review-integrity-guard`**, because those rules are what keep a
  daily readable: a clean run posts **nothing**, accrual posts once naming the stream and
  scope, and **exit 2 always posts** — "could not look" reading as "nothing there" is the
  defect this whole effort exists to kill.
- **`SET SESSION TRANSACTION READ ONLY`** on every read. Both files are already pure
  `SELECT`; this is the belt to that braces, so the server refuses a write even if one is
  ever added to a definition.

⛔ **It alerts on the watermark, never on the run.** A wedged read reports success, and the
population this watches is currently **closed** — 326,429 position rows plus 2,771
`flag_state` rows, every one inserted 2026-08-27..08-31, nothing in six weeks. A guard that
alerted on "it ran" would say nothing on the day that changes.

**Coverage lands in the same change**, which is `dpl-af3a`'s rule and the reason that row
exists: `ktp-data-server-health.sh` gains a work-done check on the log's mtime, beside the
AC-retention one and for the same structural reason — a `cron.d` job is invisible to
`CRITICAL_TIMERS`, which is checked against `systemctl list-timers`. What makes this one
necessary is that a clean run is **silent by design**, so without the log "quiet" and
"stopped running" are the same observation.

**Verification, and the two things worth keeping from it.**

- 18 new tests pass; 476 pass across the health/retention/liveness selection. The 8
  failures there are the pre-existing `ac_retention_*` ones, unchanged from the morning's
  baseline and in no file this touches.
- **Mutation-checked, and one mutation was mine to fix rather than the test's.** Deleting
  the stale token and shrinking the window below a daily interval were both caught at once.
  The third — "an absent metric returns 0" — appeared to survive, but the mutation was
  **inert**: it changed a branch guarded by `if (col …)`, which an absent metric never
  reaches. Re-aimed at the real path (`END { if (!col) print 0 }`) it was caught. That
  assertion matters more than the others: if an absent metric read as `0`, a renamed column
  would report *no defects*.
- ⚠️ **The health leg went in with an opening marker and no closing one**, and the test
  helper tolerated that — returning everything to EOF, so the extracted "leg" executed the
  rest of the health script. `bash -n` caught the stray `fi`; the helper now **requires both
  markers**, because tolerating a missing one is an assertion that cannot fail.
