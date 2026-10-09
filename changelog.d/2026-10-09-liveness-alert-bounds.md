### `ops`: the HLTV wedge detector's alert path now ends, and a page it could not deliver leaves a mark (2026-10-09)

`ktp-hltv-liveness.sh` is the watcher built after the 9h48m `Proxy::Init` outage, where a dead
HLTV binary under a live wrapper left systemd reporting `active` all day. Its alert path posted
through `curl` with no `--max-time` and no `--connect-timeout`, and that path is reached only
once something is already wrong — so the run that finally had something to say was the run that
could hang. `TimeoutStartSec=4min` on the unit kills such a run; it never explains it. These are
the bounds inside the script, sized to fire first and report.

- **The relay POST was not the only unbounded call.** `systemctl is-active` is the other, asked
  once per down proxy on the alert path — a D-Bus round-trip to PID 1, made exactly when PID 1
  is the thing in doubt. The unit enumeration and the `ss` dump are bounded too; both already
  fail closed to *broken probe* or *total outage*, so a kill there lands on an answer the script
  was designed to give, and a killed enumeration now says so instead of reading as a fleet with
  no units left.
- 🔴 **The sharper defect was not the hang: `curl -s` exits 0 on a 503.** Measured against a
  local server answering 503 — exit 0 without `--fail`, exit 22 with it. So a page the relay
  *refused* was recorded as sent, `LAST_ALERT` was stamped, and the three-hour remind window
  elapsed on a message nobody received. `--fail` makes the refusal an exit code and `-S` puts
  curl's own reason in the journal.
- **A set-but-empty channel sent nothing and returned success.** A `for` loop whose every
  iteration `continue`s exits 0, so a mis-edited `discord-relay.conf` silenced the monitor with
  no trace anywhere. The send now counts what it attempted and fails when that is nothing. Only
  the primary channel gates the caller — a broken external would otherwise re-page the primary
  every cadence — and the external's own failure is logged.
- 🔴 **An absent channel NAME was worse than an empty one, and not in the way first written.**
  `set -u` kills the run mid-send on a key the conf never defines. Measured on the pre-fix
  script: it exits **1** — not 0 — which is this script's own code for *detected it and said
  so*, and which `SuccessExitStatus=0 1 2` forgives, so the death is camouflaged as a report.
  The lasting half is the state write it dies before reaching: `FAILS` pins at its last value,
  never advances to the threshold again, and the monitor is silenced permanently rather than
  for one cadence. Every conf key is read with `:-` now.
- **`exit 4` means detected, could not report.** It is withheld from the unit's
  `SuccessExitStatus` on purpose: 1 and 2 are forgiven because the script says what happened
  itself, and saying so is the one thing this case cannot do. The failed unit is then the
  surface, reached by the `failed-unit:` producer in `ktp-data-server-health.sh`, which is a
  catch-all rather than an allowlist. ⛔ The `CRITICAL_TIMERS` row for `ktp-hltv-liveness.timer`
  is not cover for it — the service is in no allowlist, and that row is true about the timer.
- **A lost all-clear no longer clears the state.** The all-clear is the only message that ends a
  page; writing `FAILS=0` after an undelivered one left the page open with nothing able to close
  it. State is left alone and the next run retries.
- ⚠️ **The per-proxy demo scan is deliberately left unbounded, and the script says so.** It is a
  `-maxdepth 1` read of a local directory, and a bound there is the one that could manufacture a
  false *not recording* out of a merely slow scan — the false-alarm direction the start-timeout
  work warned about. The 4min backstop covers the pathological case instead.
- **The values are the repo's own rather than an analogy.** `--max-time 15` is what
  `ktp-render-banlist.sh` already carries (as `-m 15`); `--connect-timeout 5` matches the
  `mysql` callers. ⚠️ **The budget is asserted, not described:** a test reads the defaults out of
  the script and `TimeoutStartSec=` out of the unit and fails if one bounded `ss`, one bounded
  enumeration, one bounded `systemctl` per proxy at full fleet width and a POST per channel no
  longer fit under half the backstop. Loosening a bound past the backstop is the regression that
  would otherwise put the script back to being killed silently, and it fails the test now.
- **The new checks exercise the behaviour, not the flags.** The `curl` stub honours `--max-time`
  and `--fail`, and the `systemctl`/`ss` stubs can be told not to answer, so dropping a bound
  makes a test fail on elapsed time rather than on a string match. One of them asserts the exit
  code and the unit's `SuccessExitStatus` together, because the escalation is the pair.
- 🔑 **Every bound is tested in BOTH directions, because an alerting bound fails two ways.**
  Firing: each `timeout` and the relay `--max-time` has a stub that refuses to answer. Not
  firing: a relay that is slow but inside the budget must still deliver and still stamp the
  remind window, and a healthy `systemctl`/`ss` under a 1s bound must still read healthy. Each
  direction was confirmed load-bearing by deleting the bound (the firing test goes red on
  elapsed time) and by over-tightening it (the non-firing test goes red on a false page).
- ⚠️ **`--connect-timeout` is the one flag asserted only by inspection.** The stub cannot
  separate a connect stall from a transfer stall, so `RELAY_MAX_SECONDS` is what the timing
  tests actually pin; `--connect-timeout` is a strictly narrower bound under it and carries no
  test of its own. Do not read the timing assertions as covering it.
