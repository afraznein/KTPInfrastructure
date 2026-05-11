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

The internet-dependent and binary-distribution pieces. All three have
the same bundle-staging pattern: run a `package-*-bundle.sh` helper on a
current data server to produce a tarball, transfer it, set the matching
`*_PATH` conf key, re-run `lan-deploy.sh`. Each is also fine to leave
empty if you'd rather do it manually post-install.

- **HLTV binaries** — upstream HLDS+HLTV bundle (~1 GB compressed). Not
  in the repo. Stage via `scripts/package-hltv-bundle.sh` →
  `HLTV_BINARIES_PATH`. Excludes recorded demos and the cstrike subtree.
- **HLStatsX install** — base `install.sql` schema is upstream (not in
  our repo), plus our `KTPHLStatsX` scripts and migrations. Stage via
  `scripts/package-hlstatsx-bundle.sh` (run on data server) →
  `HLSTATSX_SOURCE_PATH`. The dataserver phase imports schemas, writes
  `hlstats.conf` with the generated DB password, and enables the
  `hlstatsx.service` systemd unit.
- **FastDL game files** — DoD asset tree (`maps/`, `sprites/`, `sound/`,
  `models/`). Stage via `scripts/package-fastdl-bundle.sh` (supports
  `--maps-only` for a much smaller bundle) → `FASTDL_FILES_PATH`. Files
  land at `/var/www/fastdl/dod/` (the mandatory `dod/` subdir — the
  engine prepends gamedir to download URLs).

Each `_PATH` is optional. Whatever you leave unset becomes a manual
step listed in the script's post-install output.

## Pre-flight map asset check

The wrapper runs `scripts/validate-map-assets.sh` as Phase 6 — walks every
`dod/maps/*.bsp`, cross-checks asset refs (from the sibling `.res` file
plus a `strings`-fallback against the BSP itself) against on-disk files,
and flags anything missing.

This catches the failure mode that took ATL1 down on 2026-05-11: an
admin changelevel to a test map whose `.bsp` referenced
`bakery_counter3.mdl`, the asset was missing fleet-wide, engine
`Sys_Error`'d from `Mod_LoadModel`, SIGSEGV, ~2 min outage.

Phase 6 is informational only — it logs missing assets but does not
fail the deploy. For each FAIL on the list, you decide:

- **Source the asset** and copy into the right `dod/<path>` location, or
- **Quarantine the map** so it can't accidentally be loaded:
  `mv dod_X.bsp dod_X.bsp.broken` (and the same for the `.res`).

You can also run the validator standalone any time:

```bash
sudo ./scripts/validate-map-assets.sh                    # crash-risk only
sudo ./scripts/validate-map-assets.sh --all              # include WARN-level
sudo ./scripts/validate-map-assets.sh dod_X.bsp          # one map only
```

Defaults to checking `/home/dodserver/dod-27015/serverfiles/dod`; use
`--maps-dir <path>` to point elsewhere.

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
