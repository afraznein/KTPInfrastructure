### `monitoring`: the LinuxGSM monitor cron no longer restarts into a host network outage (2026-10-03)

On 2026-09-29 Dallas lost carrier for about four minutes. The static address went
with the link, the per-minute `dodserver monitor` saw five failed queries and
restarted all five instances into a network they could not bind
(`Cannot assign requested address` → `Sys_Error` → five cores), then restarted all
five again once the link came back.

- New `monitoring/monitor-guard/ktp-monitor-guard.sh`. The cron line calls it with
  the control script and `monitor` as arguments. It skips that tick, logging one
  `HOLD` line, when the instance's configured bind address is on no interface, that
  interface has no carrier, or there is no IPv4 default route; otherwise it execs the
  monitor unchanged. Anything it cannot evaluate runs the monitor.
- `provision/install-linuxgsm.sh` installs the guard to `~/ktp-monitor-guard.sh` and
  writes wrapped monitor lines (warmup included) when the guard source is beside it.
- The wrapped line still matches `ktp-scheduled-restart.sh`'s `dodserver.*monitor`
  pause and `ktp-fleet-health.sh`'s monitor-line count; a test reads both patterns
  from those scripts.
- `tests/unit/test_monitor_guard.py`.

⚠️ Deploy is the operator's: copy the guard to each game host and rewrite the
monitor lines in the `dodserver` crontab. Nothing restarts. Steps are in the PR.
Keeping the static address across a carrier flap (netplan) is a separate change.
