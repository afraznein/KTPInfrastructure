### `docs`: `ALERT_COVERAGE.md` gains the four live timers it never listed (2026-10-12)

The runbook's own rule is that adding a timer means adding a row to its timer table in the
same change. Four live timers on the data server had none, so a reader checking coverage
there was told about twelve of the box's sixteen and had no way to notice the other four.

Measured read-only 2026-10-12, with controls in both directions (`ktp-render-banlist` as the
positive, a nonsense unit name as the negative, and `systemctl cat` rather than `show` —
`show` on a nonexistent unit answers exactly like a stopped one):

- `ktp-reports.timer` and `ktp-telemetry-export.timer` — not in `CRITICAL_TIMERS`, so a
  stopped timer is silent, but both services carry `OnFailure=`, so a failing run alerts.
- `ktp-ac-flagged-payload-retention.timer` — not in `CRITICAL_TIMERS` and **no
  `OnFailure=`**. A failing run is caught only by the hourly sweep's generic `failed-unit:`
  leg, and only because the timer is weekly, so the oneshot sits `failed` long enough to be
  seen. Its stop direction over-retains evidence rather than losing it, which makes it the
  least urgent of the four.
- `support-poller.timer` — not in `CRITICAL_TIMERS`, **no `OnFailure=`**, and
  `OnUnitActiveSec=60s`. An intermittent failure is re-run and clears itself long before the
  hourly `failed-unit:` sweep looks, so the one mechanism that could catch it is the one this
  timer outruns. This is the `/servers` freshness push — the same silent staleness that the
  poller's exit code 8 names from the other side — and of the four it is the gap worth
  closing first.

Also corrected:

- The line stating `CRITICAL_TIMERS` *"covers ten timers as of 2026-09-16"* is replaced by the
  three commands that derive it, the deployed count and the live timer list, because the list
  had moved twice since that sentence was written and a figure in prose rots silently.
- *"Only `ktp-monday-reminder.timer` is deliberately left out"* was false and load-bearing:
  four other live timers are out of `CRITICAL_TIMERS` and nothing about them is deliberate.
  **Deliberately excluded and merely absent are different facts, and that sentence was the
  only place the difference was recorded.** The reminder keeps its deliberate exclusion; the
  claim of exclusivity goes.
- A third mechanism is now named where the rows depend on it: the hourly sweep's generic
  `failed-unit:` leg catches a unit whose failure **persists**, which is why a weekly oneshot
  is covered and a 60-second one is not.
- A probe note: a board note had this as *three* timers and missed `ktp-reports.timer`, which
  is discussed in the service table and still had no row in the timer table. And
  `ktp-telemetry-export` resolved once in this file — a prose mention 140 lines below the
  table, which reads exactly like a row. Scope the grep to the table.

No behaviour change and nothing deployed: this is the coverage document catching up with the
box. Closing any of the four gaps is a separate change, and `support-poller` is the one to
take first.
