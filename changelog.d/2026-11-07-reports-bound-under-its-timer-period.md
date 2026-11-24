### `systemd`: `ktp-reports.service` bounded under its own timer period (2026-11-07)

`TimeoutStartSec` was 5400 on a timer that fires every 900 s. Every step in the job is bounded —
`mysql()` in `report_service.py` and `sql()` in `report_sync.py` each run their query as a
subprocess with `timeout=600`, on top of `READ_RETRY_DELAYS = (5, 15, 45)` — and the job as a
whole was bounded by nothing but that 90 minutes, so a slow-database period ran past the unit
timeout without any single query tripping its own.

**The 90 minutes is also why the failures came in pairs.** 5400 is exactly 6× the 900 s period and
the timer fires at `:04,19,34,49`, so the kill landed *on* a trigger minute and started a successor
that wedged the same way. Six start timeouts between 2026-10-23 and 2026-10-25 arrived as three
pairs — 17:04/18:34, 22:34/00:04, 16:49/18:19 — and the alert that reported it read two. One slow
period cost 180 minutes, not 90.

- **`TimeoutStartSec=600`**, which is the per-query subprocess timeout already in the code: the job
  can no longer outlive its own slowest permitted step, and it leaves 300 s before the next trigger.
  A run cut short is continued rather than lost — `cmd_generate` persists per match and
  `pending_match_ids` re-derives what is left, and the timer is `Persistent=true`.
- **`tests/unit/test_oneshot_bound_under_calendar_period.py`** is the class check:
  for every `Type=oneshot` with a fixed-phase `OnCalendar=`, the bound must be under the shortest
  gap between firings. Scoped to `OnCalendar=` deliberately — `OnUnitActiveSec=` measures from the
  last activation, so it has no phase to alias with, which is why `ktp-render-banlist` (300 s on
  60 s) and `support-poller` (45 s on 60 s) are out of scope rather than failures. The period parser
  is **fail-closed**: a shape it does not model fails with the spec quoted, because a parser that
  skips what it cannot read reports a clean pass for a timer it never looked at.
  Mutation-checked both ways — restoring 5400 turns it red, and an unmodelled `OnCalendar=` is
  named rather than ignored.
- **`test_reports_unit_timeout.py`** pinned the literal 5400 with the comment *"production raised
  this with a drop-in"*. It now pins 600 and asserts the `timeout=600` it is derived from, so the
  unit value and the step value cannot drift apart silently.
- Top-level **`systemd/` added to the Tier 1 change filter.** Both start-timeout guards rglob every
  `*.service`; most units live under `scripts/systemd/`, so a PR touching only the three in
  `systemd/` would have skipped the job that runs them. Same defect as the `ALERT_COVERAGE.md`
  entry already in that filter, one directory over.

⚠️ **Nothing changes on the box when this merges.** `/etc/systemd/system/ktp-reports.service.d/10-timeout.conf`
sets `TimeoutStartSec=5400` and a drop-in outranks the unit, so the effective value stays 90 minutes
(`systemctl show ktp-reports.service -p TimeoutStartUSec --value` → `1h 30min`, read 2026-11-07).
That file is untracked here. The removal and the `daemon-reload` are an operator act, written out in
`docs/runbooks/REPORT_PIPELINE_INSTALL.md` § 4.

⚠️ **The journal can no longer corroborate the six wedges.** journald on that box holds about a week
against this unit: the oldest `ktp-reports` entry on 2026-11-07 is 2026-10-29T08:19:04, so 10-23
through 10-25 has rotated out. Since 10-29 the unit is clean — 835 `Starting` and 835 `Finished`
over 3,341 journal lines, 0 `timed out`, 0 `Failed with result`.
