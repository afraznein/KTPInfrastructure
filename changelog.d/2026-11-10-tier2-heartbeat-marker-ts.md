### `scripts`: the tier-2 heartbeat treats the run marker as data, and counts only its own runner (2026-11-10)

`ktp-tier2-heartbeat.sh` runs from root's cron and read the marker's `ts` straight into
`$(( now - m_ts ))`. Bash evaluates a string operand there as an expression, array
subscripts included, so a `ts` of `now[$(cmd)]` ran `cmd` as root and then read as a
healthy run. Root writes the marker today, so nothing was exposed, but moving the tier-2
runner off root hands the marker to the runner user and would have turned this into a
path from any tier-2 job to root. `ts` must now be a plain decimal integer of at most 12
digits with no leading zero; anything else reports the leg as not running and says the
marker's `ts` is invalid. A leading zero is rejected rather than read as octal, which used
to abort the script under `set -e`.

The listener count also matched the bare name `Runner.Listener`, so every other runner on
the box (the `ktp-ops` runner the de-rooting plan adds, and the `ktp-ci` install runner)
would have read as a `DUPLICATE runner listener`. The default pattern and the cron file now
name the tier-2 runner's own binary path.

Two new cases in `scripts/test-tier2-heartbeat.sh`. One writes a marker whose `ts` would
create a probe file and asserts the file never appears, then rejects six malformed values,
with a plain epoch as the control. The other stages three runners' listeners and expects a
count of one, with the bare pattern over the same fixture as the control. Against the
previous script nine checks fail, including the probe.

The operator runbook for the cutover is `docs/runbooks/TIER2_RUNNER_NONROOT_CUTOVER.md`.
**Deploy:** install the heartbeat and the cron file with `ktp-install`; this must be live
before the marker is chowned to the runner user.
