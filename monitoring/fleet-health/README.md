# ktp-fleet-health

Per-host alerter that fires a Discord embed when `pgrep -c hlds_linux` falls
below the expected instance count for N consecutive minutes. Single post per
state transition (one DEGRADED on decline, one RECOVERED on return), silent
when healthy.

Designed for the case where the LinuxGSM monitor cron either fails to
restart a crashed instance or restarts it but the process exits again
immediately — without this alerter, the host can run degraded for hours
before anyone notices.

## Files

| File | Purpose |
|------|---------|
| `ktp-fleet-health.sh` | The alerter itself. Runs every minute via cron under `dodserver`. |
| `fleet-health.conf.example` | Template for `/etc/ktp/fleet-health.conf`. Webhook + topology overrides. |

## Install

The provisioning flow (`provision-gameserver.sh`) copies the script to
`/home/dodserver/ktp-fleet-health.sh` and seeds the cron entry. For an
existing host or manual install:

```bash
sudo cp ktp-fleet-health.sh /home/dodserver/
sudo chown dodserver:dodserver /home/dodserver/ktp-fleet-health.sh
sudo chmod 755 /home/dodserver/ktp-fleet-health.sh

sudo cp fleet-health.conf.example /etc/ktp/fleet-health.conf
sudo chown root:dodserver /etc/ktp/fleet-health.conf
sudo chmod 640 /etc/ktp/fleet-health.conf
sudo $EDITOR /etc/ktp/fleet-health.conf   # set WEBHOOK_URL, MENTION_USER_ID

# crontab as dodserver
(crontab -u dodserver -l 2>/dev/null; echo '* * * * * /home/dodserver/ktp-fleet-health.sh >/dev/null 2>&1') \
    | crontab -u dodserver -
```

## Config layering

Three sources, later overrides earlier:

1. **Script defaults** — safe-by-default (`WEBHOOK_URL=""` ⇒ no Discord posts).
2. **`/etc/ktp/fleet-health.conf`** — system-wide config. Operator-managed.
3. **`~dodserver/.ktp-fleet-health/config.sh`** — per-host fine-tuning.

If `WEBHOOK_URL` is empty after all sources load, the alerter still tracks
state in `~/.ktp-fleet-health/state` but skips the network call. Useful for
LAN deployments where Discord may not be reachable or wanted.

## Topology config

`BASE_PORT` + `NUM_INSTANCES` drive the per-port enumeration in the DEGRADED
embed body. Defaults assume the standard KTP 5-instance host (`27015–27019`);
LAN events on a different port range only need to set those two keys.

## State

`~dodserver/.ktp-fleet-health/state` is a tiny shell-source file containing:

- `CONSECUTIVE_BAD` — consecutive minutes below `EXPECTED`
- `ALERT_STATE` — `healthy` | `unhealthy`
- `LAST_RUN` — epoch seconds
- `LAST_RUNNING` — last observed `pgrep -c hlds_linux`

Delete the state file to reset (the next run will recreate it).
