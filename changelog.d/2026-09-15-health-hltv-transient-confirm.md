### `monitoring`: stop the health check calling a scheduled restart an outage — and fix the abort that was eating the real alerts (2026-09-15)

Two defects in `ktp-data-server-health.sh`, in the same alert path.

**1. `hltv@<port>=deactivating` was the restart, not a fault.** The hourly cron fires at
`0 * * * *`; `hltv-restart.timer` fires at 03:00 and 11:00 ET. The check's 24-port
`systemctl is-active` sweep therefore runs inside `hltv-restart-all.sh`'s own sequential
restart loop. Most proxies stop in under a second, but on one or two per pass the wrapper's
`( sleep 3; kill -KILL … )` subshell survives the cgroup SIGTERM and holds the unit
`deactivating` for exactly three seconds — measured on 2026-09-15, where `hltv@27028` was
`Stopping` at 03:00:02 and not `Stopped` until 03:00:05, and the check posted
`hltv@27028=deactivating` at 03:00:02.

Every `hltv@` token this check has ever written to its log — 62 occurrences, 14 ports —
reads `deactivating`. Not one was `failed` or `inactive`. Of the 325 alerting runs since
2026-04-30, **252 sit on a restart hour (03:00/11:00) or the hour after it**.

- A transitional reading (`activating`, `deactivating`, `reloading`, `refreshing`,
  `maintenance`) is now confirmed by a second sample after one shared pause
  (`HLTV_CONFIRM_SLEEP`, 15s — longer than the unit's `RestartSec=10`). One pause for the
  whole sweep, not one per port. A terminal state is never re-sampled, so nothing that is
  genuinely down gets suppressed. `hltv@.service` carries `TimeoutStopUSec=90s` with
  `SendSIGKILL=yes`, so systemd is *guaranteed* to leave `deactivating` — a stop that
  outlives the pause is a proxy ignoring SIGTERM, and that still alerts.
- **New leg — `hltv@<port>=crash-looping`.** `Restart=always` with `RestartSec=10` outruns
  systemd's default start-rate limit, so a crash-looping proxy never reaches `failed`: it
  flaps active↔activating forever and `is-active` reads `active` most of the time. That is
  the same shape as the renamer wedge of 2026-08-25. `NRestarts` sees it; unit state cannot.
- `hltv-instance-count=23/24` put the measured count inside the alert key, so 23/24 → 22/24
  read to the set comparison as one recovery plus one new failure — the defect deadbanded out
  of the disk keys the same day. The key is now `hltv-instance-coverage` and the count rides
  in the alert body.

**2. Building the log line was killing the run before the Discord POST.** Under
`set -euo pipefail`, `printf '%s\n' "${arr[@]}" | grep -v '^$' | paste -sd, -` exits 1 when
the array is empty, and the assignment aborted the script — no `TRANSITIONS` line, no POST,
and no `save_state`, so the same diff aborted again the next hour. Only a run with something
on **both** sides ever reached the alert.

Measured in `/var/log/ktp-data-server-health.log`: **675 of 675 runs wrote a verdict line
before that spelling shipped on 2026-08-31, and 99 of 373 after** — 274 silent runs. Not one
of the 44 surviving `TRANSITIONS` lines carries a zero on either side. Names are now joined in
bash, which cannot fail.

⚠️ **This is why the disk deadband had to land with it.** The oscillating `disk-growth` key was
supplying the non-empty recovery side that kept the script alive; removing the oscillation
would have made pure-failure runs the norm, and every one of them would have aborted.

⚠️ **One migration alert on the first run after install**, as the state file still holds
`hltv-instance-count=…` if a restart-hour run last wrote it.
