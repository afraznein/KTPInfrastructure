### `ops`: every oneshot bounds its start, and the wedge detector was one of the unbounded ones (2026-10-09)

`TimeoutStartSec=` defaults to disabled for `Type=oneshot`, so a wedged run stays in
`activating` forever. The part that matters is not that a unit can hang — it is that the
alerting reads *covered* while it does. `activating` is not `failed`, so the
`failed-unit:` producer in `ktp-data-server-health.sh` cannot see it; the TIMER stays
`active`/`enabled` while declining to re-trigger a job that never finished, so the
`CRITICAL_TIMERS` leg cannot either; and `OnFailure=` needs an exit. Three legs green,
unit dead.

- **`ktp-hltv-liveness.service` is the sharp end and now bounds at `4min`.** It is the
  watcher built after the 9h48m `Proxy::Init` outage, where a dead HLTV binary under a
  live wrapper left systemd reporting `active` all day. Its alert path posts through
  `curl` calls carrying no `--max-time`, reached only once something is already wrong, and
  its timer fires every 5 minutes — so the bound sits inside one cadence and the next run
  is never blocked by more than one skipped trigger.
- **`ktp-match-retention.service` bounds at `30min`**: one `mysql(1)` running unbatched
  `DELETE`s once a day. A wedge bound, not a performance budget.
- **`ktp-kernel-reboot.service` deliberately has none**, and now says so in a
  `# no-start-timeout:` line. The script disables its own timer and enables the
  post-reboot verifier before calling `systemctl reboot`; a SIGTERM inside that window
  leaves the one-shot permanently disarmed on the old kernel with a verifier armed for
  someone else's boot. Its real unbounded waits are the two `mysql` idle-gate queries, and
  the place to bound those is the script's own abort path, which already posts and exits 0.
- 🔑 **Three more were outside the directory the 2026-10-07 sweep measured, which is why
  the fix for that sweep could not reach them.** It counted `scripts/systemd/`;
  `scripts/ktp-systemd-alert@.service` (`180` — and it deliberately carries no
  `OnFailure=`, so a start timeout is the only thing that can ever end a wedged alert),
  `scripts/ktp-map-coefficients.service` (`30min` — unbounded `git fetch`, `git push` and
  `gh pr create`) and `scripts/ktp-hlstatsx-ingest-monitor.service` (`15min`) all sat
  above it. The last of those is a pre-move duplicate of the `scripts/systemd/` unit the
  install runbook actually copies, so it kept the default the twin had already lost.
- **`tests/unit/test_oneshot_start_timeouts.py` is the class check that was missing.**
  `test_reports_unit_timeout.py` pins one unit's value by literal path and is structurally
  blind to every other unit, including a new one. The new check sweeps every tracked
  `*.service`, parses section-scoped so a `[Unit]` `Type=` is not read as the service's,
  resolves a `TimeoutStartSec=` supplied by a repo drop-in, and accepts
  `# no-start-timeout: <reason>` as the other valid answer — a reason is required, so the
  exemption is reviewable rather than indistinguishable from the omission.
