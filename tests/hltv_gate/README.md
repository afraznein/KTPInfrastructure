# HLTV wrapper startup-gate harness

Proves `scripts/hltv-wrapper.sh` exits when its proxy fails to come up, and
keeps working when it does. Runs against fake proxies on unused ports in
`/tmp`; touches no systemd unit, no live wrapper, no real proxy.

```bash
./gate-harness.sh ../../scripts/hltv-wrapper.sh          # expect 4 passed, 0 failed
GRACE=8 ./gate-harness.sh ../../scripts/hltv-wrapper.sh  # default; raise for slow hosts
```

| case | what it models | expected |
|---|---|---|
| `healthy` | proxy binds its port | wrapper stays up |
| `wedged` | FATAL, binds nothing, never exits — the 2026-08-10 state systemd called `active (running)` | wrapper exits non-zero |
| `wrongport` | the port is held by someone else — the actual incident, 27035 going for 27020 | wrapper exits non-zero |
| `fifo` | `record` / `stoprecording` reach the proxy | both delivered |

## Why this exists

The gate shipped once without ever being observed firing, and it did not work.
Two independent defects, both invisible to inspection:

1. The check was `ss ... | grep :PORT` — **is anything listening**, not is *our*
   proxy listening. In the one scenario it exists to catch, another process holds
   the port, so it read healthy. An induced-failure test on an occupied port
   therefore passed and proved nothing.
2. `$!` on `tail -f | hltv | grep` names **grep**. The gate detected the failure,
   logged it, killed the proxy — and the wrapper stayed blocked in `wait` on a
   pipeline that never collapsed. Measured: gate logged "not bound after 8s",
   wrapper still alive when `timeout` killed it.

Run the harness against the previous implementation and it fails `wedged` and
`wrongport` while passing `healthy` and `fifo`. That asymmetry is the point — a
harness that cannot go red is not evidence.

**Measure the wrapper's own exit code.** An earlier attempt read `tail`'s status
via `| tail -4; echo $?` and concluded the opposite of the truth.

**Keep the fake faithful.** It must `exec` so the process that binds IS the
wrapper's direct child. Verified on the live fleet: every real proxy's
socket-owning pid is `hltv` with `ppid` == the wrapper. A fake that binds in a
child makes a correct wrapper look like it false-trips on a healthy proxy.
