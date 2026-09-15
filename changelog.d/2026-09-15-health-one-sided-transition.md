### `monitoring`: the data-server health check could only speak when a failure and a recovery landed in the same hour (2026-09-15)

`ktp-data-server-health.sh` built its report with
`printf '%s\n' "${arr[@]}" | grep -v '^$' | paste -sd, -`. An **empty** array makes `printf`
emit one blank line, `grep` match nothing and exit 1, and under the script's own
`set -e -o pipefail` that assignment ends the run — before the `TRANSITIONS` log line,
before the Discord POST, and before the state file is written. Since #207 added those two
lines on 2026-08-31 the check has therefore alerted **only** on runs that carried at least
one new failure *and* at least one recovery.

Measured on the data server: `/var/log/ktp-data-server-health.log` (2026-09-01 → 09-15)
holds **0** transitions with `new_down=0` and **0** with `recovered=0`, out of 42.
`.log.1`, the month before the regression, holds **130** and **127** out of 283. A first
mysql failure, a wedged `hltv-demo-renamer`, a stopped `ktp-render-banlist.timer` — each
arriving alone, as they do — produced no alert anywhere. The state file was left stale by
the same exit, so the next alert's "All currently down" footer described the past.

- `join_keys` replaces the pipeline. An empty array yields an empty string and exit 0.
- A control test asserts the shipped spelling **would** have died, and a source scan keeps
  the idiom from returning to any of the three sites that used it.

### `monitoring`: stop reporting HLTV proxies that are mid-restart

The hourly cron fired at `:00`, the same minute as `hltv-restart.timer` (`OnCalendar`
03:00 and 11:00 ET), so it sampled the 24 proxies while the restart it schedules was
walking through them and reported whichever one it caught as `deactivating`, plus
`hltv-instance-count=23/24`. **252 of the 325 alerts logged over 2026-04-20..09-15 fall in
hours 03, 04, 11 and 12**; in the last seven days, 13 of 20 name an `hltv@` port and none
was a real fault. The fleet reads 24/24 active on any sample taken between restarts, which
is why the admin bot's 09:08 ET digest and this check disagreed every day.

- `settled_state` re-reads a unit reporting a transitional systemd state
  (`activating`/`deactivating`/`reloading`/`refreshing`) after `SETTLE_SECONDS` (20).
  A unit still not active then is genuinely stuck and still alerts; `failed` is terminal
  and is never given the grace period. One sleep per run, not one per unit — it answers in
  `$SETTLED` rather than on stdout, because a `$(...)` caller would discard the latch.
- The cron moved to `:17`, so a sample never coincides with a restart we schedule
  ourselves, and off the top-of-hour pile-up.

⚠️ **Installing this is a cron change as well as a script change** — copy
`scripts/ktp-data-server-health.cron` to `/etc/cron.d/ktp-data-server-health`, or the
script fix lands while the sample stays on the restart minute.
