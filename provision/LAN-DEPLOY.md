# KTP LAN Deployment

End-to-end provisioning of a single all-in-one KTP host for a LAN event.
One config file, one script invocation.

## TL;DR

```bash
# On the LAN box, as root:
git clone <KTPInfrastructure repo>
cd KTPInfrastructure/provision
cp lan-deploy.conf.example lan-deploy.conf
$EDITOR lan-deploy.conf            # set LAN_IP, ARTIFACTS_PATH, LIBSTEAM_API_PATH
./lan-deploy.sh                    # confirms once, then runs
```

## What gets installed

The orchestrator runs five phases in order, each idempotent:

1. **`provision-gameserver.sh`** — host hardening. Creates `dodserver` user,
   installs lowlatency kernel, applies all KTP sysctls (UDP buffers, RT
   throttling disabled, netdev_budget=1200, etc.), disables apport,
   configures UFW, installs fail2ban. Sets up `ktp-chrt.timer` for CPU
   pinning + `SCHED_FIFO` priority. Deploys `ktp-fleet-health.sh` cron.
   All the optimization work that gets the public-cloud fleet to clean
   sub-millisecond p99s.

2. **`install-linuxgsm.sh`** — bootstraps LinuxGSM, installs Day of
   Defeat via SteamCMD, creates 5 server instances. *Requires internet
   access.*

3. **`clone-ktp-stack.sh`** — drops the pre-built KTP stack (engine,
   KTPAMXX, plugins, configs) on top of the LinuxGSM bootstrap.
   Configures hostnames, sv_password, HLTV ports. Installs the
   nightly 3 AM scheduled restart cron.

4. **`provision-lan-dataserver.sh`** *(optional, `ENABLE_DATASERVER=true`)*
   — sets up co-located MySQL, HLStatsX skeleton, HLTV proxies, HLTV API,
   FastDL nginx. Auto-generates random passwords if the config left them
   empty. Saves them to `/root/ktp-dataserver-credentials.txt`.

5. **`/etc/ktp/fleet-health.conf`** — writes the alerter config with
   LAN-specific values. Empty `WEBHOOK_URL` means the alerter runs in
   silent monitoring mode (state tracked locally, no Discord posts).

## What it does NOT do

Manual steps the operator still has to handle:

- **HLTV binaries** are NOT shipped. After provisioning, copy them to
  `/home/hltvserver/hlds/` and start with
  `su - hltvserver -c './hltv-ctl.sh start'`.
- **HLStatsX setup** is a skeleton only — see `/opt/hlstatsx/INSTALL.txt`
  on the provisioned box for the manual SQL import / daemon start.
- **FastDL game files** — if you want clients to download maps/sounds,
  copy them under `/var/www/fastdl/dod/` (note the mandatory `dod/`
  subdirectory — the engine appends it to every download URL).

## Pre-flight requirements

- Ubuntu 22.04 LTS or 24.04 LTS, fresh install.
- Internet access during Phase 2 (LinuxGSM/SteamCMD pulls game files).
  After that the box can be air-gapped if needed.
- KTP artifacts pre-staged in a single directory with the layout
  `clone-ktp-stack.sh` expects (engine/, ktpamx/dlls/, ktpamx/modules/,
  plugins/). Copy from the canonical build location or the most recent
  `~/backups/YYYYMMDD_HHMMSS/` on any current fleet host.
- The 76 KB KTP `libsteam_api.so` (NOT the 375 KB stock one).

## Config keys

See `lan-deploy.conf.example` for the canonical list and inline
explanations. Required: `LAN_IP`, `ARTIFACTS_PATH`, `LIBSTEAM_API_PATH`.
Everything else has a default. Empty Discord URLs == silent monitoring.

## Re-running

Each phase checks for existing state and skips if already done. Safe to
re-run after a failure once you've fixed the cause. To force a full
reinstall, remove `/home/dodserver/dod-<port>/serverfiles/` and re-run.

## Differences from the public-cloud fleet

| Concern | Cloud fleet | LAN |
|---------|-------------|-----|
| Data server IP | `74.91.112.242` baked in | `LAN_IP` (all-in-one) |
| Discord relay | Cloud Run endpoint | Optional; empty = no posts |
| Fleet-health webhook | Production Discord channel | Optional per-deployment |
| Dataserver passwords | Production secret | Auto-generated per run |
| Timezone | `America/New_York` | Operator-set (`TIMEZONE` env) |
| Netdata | Claimed to KTP Cloud | Off by default |

The wrapper sets defaults that are appropriate for LAN. Cloud
deployments still call the underlying scripts directly with the older
arg patterns — `lan-deploy.sh` is LAN-only.
