# KTP LAN Deployment

End-to-end provisioning of a single all-in-one KTP host for a LAN event.
One config file, one script invocation.

> **Companion doc:** this covers the *automated install*. For architecture, the
> day-of runbook, HLTV/stats/**TeamSpeak** setup, and troubleshooting, see
> [`../docs/LAN_SETUP.md`](../docs/LAN_SETUP.md). Keep the two in sync.
>
> **Current plan (July 2026 LAN):** one all-in-one box — **5 KTP-stack
> competitive servers** + HLTV + TeamSpeak. Set `NUM_INSTANCES=5`; the
> orchestrator creates all 5, auto-places HLTV after them (27020-27024), and
> pins one CPU core per server (warns if the box has fewer than
> `NUM_INSTANCES + 2` cores). A stock 24-slot **warmup** server (port 27050,
> non-KTP, no plugins/HLTV) is a SEPARATE manual install outside this count.
> TeamSpeak is a manual post-install step.

## TL;DR

```bash
# On the LAN box, as root. Clone somewhere world-readable (NOT under /root —
# Phases 2-3 run as the dodserver user and must be able to read the repo):
git clone <KTPInfrastructure repo> /opt/ktp/KTPInfrastructure
cd /opt/ktp/KTPInfrastructure/provision

# clone-ktp-stack.sh is gitignored (it can carry embedded secrets) — a fresh
# clone ships only the .example. Copy it; flag-driven values are fine as-is
# for LAN (lan-deploy.sh passes everything it needs via flags):
cp clone-ktp-stack.sh.example clone-ktp-stack.sh

cp lan-deploy.conf.example lan-deploy.conf
$EDITOR lan-deploy.conf            # set LAN_IP, ARTIFACTS_PATH, LIBSTEAM_API_PATH
./lan-deploy.sh                    # confirms once, then runs
```

(`lan-deploy.sh` preflights both of the above and fails with instructions
before touching the host if either is missing.)

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
   — sets up co-located MySQL, HLStatsX skeleton, HLTV proxies (systemd
   `hltv@<port>` units with FIFO cmdpipes — the production runtime shape),
   the HLTV API (production v2.2: `X-Auth-Key` auth, `GET /hltv/<port>/state`,
   `POST /hltv/<port>/restart` — exactly what KTPHLTVRecorder 1.7.0 calls),
   FastDL nginx. HLTV configs are generated in the 1.7.0 always-on profile:
   each proxy autoconnects to its paired game server and records continuously
   (`record auto_lanN`); demos accumulate under `/home/hltvserver/hlds/dod/`
   and are browsable at `http://<LAN_IP>/demos`. The `HLTV_API_KEY` is
   auto-generated and plumbed to BOTH the API service and every game
   instance's `hltv_recorder.ini`. Auto-generates random passwords if the
   config left them empty. Saves them to
   `/root/ktp-dataserver-credentials.txt`.
   **No demo cleanup cron is installed on LAN** — the production 6h purge
   would delete unrenamed demos and there is no renamer here; budget
   ~3 GB/day/instance of disk and archive after the event.

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
  engine prepends gamedir to download URLs). This is for **client**
  downloads only — it does not put maps on the game servers.
- **DoD base content (game-server side)** — the servers' own `dod/` tree:
  custom maps **and their command-map overviews**, WADs, `ktp_*.cfg`, and
  any custom models/sprites/sounds. `install-linuxgsm.sh` installs only
  **stock** DoD from Steam, so without this the custom KTP maps and
  overviews are missing from the servers themselves. Stage via
  `scripts/package-dod-base.sh` → `DOD_BASE_PATH`; `clone-ktp-stack.sh`
  extracts it into every instance. Empty = stock maps only (the script
  warns). **This is the historical "left out the maps/overviews folder"
  gap — now wired into the orchestrator via `DOD_BASE_PATH`.**
- **TeamSpeak voice server** — not installed by the orchestrator. Run
  `provision/install-teamspeak.sh` (creates the `teamspeak` user, installs to
  `/opt/teamspeak`, writes the `ts3server` systemd unit). It's a 64-bit upstream
  download (no i386 multilib), runs on the OS/housekeeping cores next to HLTV.
  Data (the `ts3server.sqlitedb`, logs) lives in `/opt/teamspeak`, which the disk
  prep above bind-mounts onto the larger HDD — tiny footprint, rides it for tidiness.
  **This LAN uses a paid license:** drop `licensekey.dat` into `/opt/teamspeak` and
  restart `ts3server`. Open UFW 9987/udp + 30033/tcp + 10011/tcp. Air-gapped LANs
  must stage the tarball + `licensekey.dat` ahead of time. Full walkthrough in
  [`../docs/LAN_SETUP.md`](../docs/LAN_SETUP.md) § TeamSpeak Voice Server.
- **Warmup / pub server (6th instance, port 27050)** — a STOCK HLDS DoD
  server for pre-match warmup, deliberately outside the KTP stack (no
  custom engine, no plugins, no HLTV, no stats). A separate manual
  LinuxGSM install on the larger HDD (`/srv/ktpdata/warmup`), pinned
  `taskset -c 0,1`. 24 slots, 60-min timer, rotates
  `dod_pandemic_aim ↔ dod_orange`, rcon `<WARMUP_RCON>` (real value in the gitignored `infrastructure.md`), logging off.
  Config + step-by-step in
  [`../config/lan/warmup/README.md`](../config/lan/warmup/README.md)
  (its `dodserver.cfg` + `mapcycle.txt` live in that folder). Needs its
  own `ufw allow 27050/udp`.

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

## Disk prep (two-HDD box) — do this BEFORE `lan-deploy.sh`

The pipeline has **no disk logic**. On the two-HDD LAN box, mount the larger HDD and
bind-mount the bulk / heavy-write dirs onto it first. The **MySQL bind in particular
must exist before Phase 4 installs `mysql-server`**. Game servers (`/home/dodserver`)
stay on the **primary** disk; everything else rides the larger HDD.

```bash
# ⚠️ IDENTIFY THE BULK DISK FIRST — do NOT assume /dev/sdb. Device letters are
# not stable and may be the OS disk (on the Philly box /dev/sdb IS the OS/root
# disk; the bulk disk is /dev/sda). Confirm with `lsblk -o NAME,SIZE,MODEL,MOUNTPOINT`,
# then use the /dev/disk/by-id/ path so a rename can't point mkfs at the wrong disk.
# ("two-HDD" is historical — the disks may both be SSDs.)
DISK=/dev/disk/by-id/ata-XXXX          # <- the BULK disk from `ls -l /dev/disk/by-id/`
lsblk "$DISK"                          # sanity: NOT the OS disk, nothing mounted
wipefs -a "$DISK"
parted "$DISK" --script mklabel gpt mkpart primary ext4 0% 100%
partprobe "$DISK"; udevadm settle
mkfs.ext4 -L ktpdata "${DISK}-part1"
mkdir -p /srv/ktpdata
echo 'LABEL=ktpdata /srv/ktpdata ext4 defaults,noatime 0 2' >> /etc/fstab
mount /srv/ktpdata
mkdir -p /srv/ktpdata/{hltvserver,mysql,fastdl,warmup,teamspeak,demo-archive}
mkdir -p /home/hltvserver /var/lib/mysql /var/www/fastdl /opt/teamspeak
cat >> /etc/fstab <<'EOF'
/srv/ktpdata/hltvserver /home/hltvserver none bind 0 0
/srv/ktpdata/mysql      /var/lib/mysql   none bind 0 0
/srv/ktpdata/fastdl     /var/www/fastdl  none bind 0 0
/srv/ktpdata/teamspeak  /opt/teamspeak   none bind 0 0
EOF
mount -a
```

Bind-mounting **subdirs** (not the partition directly) keeps `/var/lib/mysql`
identical (no datadir/AppArmor surgery) and avoids `lost+found` (mysqld refuses a
non-empty datadir). What lands where:
- **Larger HDD (`/srv/ktpdata`):** HLTV home + all demo output (`/home/hltvserver/hlds/dod`,
  the dominant writer — ~15 GB/day for 5 instances, no auto-cleanup), MySQL datadir,
  FastDL, the warmup server tree (`/srv/ktpdata/warmup`), and TeamSpeak (tiny — rides
  it for tidiness, not I/O).
- **Primary disk:** OS + the 5 competitive game trees (`/home/dodserver/dod-*`) — kept
  quiet (engine + AMXX logging are async, HLStatsX is UDP-out).

If provisioning already ran before the MySQL bind existed, recover with:
`systemctl stop mysql; rsync -a /var/lib/mysql/ /srv/ktpdata/mysql/; mv /var/lib/mysql /var/lib/mysql.old; mkdir /var/lib/mysql; mount -a; systemctl start mysql`.

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

### Changing the bind IP (venue day) — use `lan-change-ip.sh`, NOT a re-run

A full `lan-deploy.sh` re-run **cannot** change `LAN_IP` on a box whose servers
are already running: `clone-ktp-stack.sh` refuses to overwrite live binaries
while any `hlds_linux` is up, and Phase 1 re-installs the LinuxGSM monitor cron,
which revives the servers within a minute — before Phase 3 runs. A catch-22.

To retarget a live deployment to a new IP (the normal venue-day case), use the
dedicated tool. It rewrites only the IP-bearing config values + the
`hlstats_Servers` rows and restarts the game/HLTV/warmup servers — no re-deploy,
keys (RCON, HLTV API) untouched:

```bash
lan-show-ip.sh                          # read the new (venue) IP
sudo ./lan-change-ip.sh <new-ip>        # --dry-run to preview; --force to skip the local-IP guard
```

It refuses an IP that isn't on a local interface — hlds crashes on a bind
failure (SIGSEGV + coredump), so a typo would take the fleet down. On boot the
servers come up bound to the *old* IP and crash until you run the tool; that
first crash is expected.

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
