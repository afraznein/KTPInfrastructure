# Warmup / Pub Server (6th instance) — setup notes

A **stock HLDS** DoD server for players to warm up on, deliberately outside the KTP
stack: no custom engine, no plugins, no HLTV, no stats. It's a **separate manual
install** — NOT created by `lan-deploy.sh` (which only makes the 5 competitive servers).

## Spec
- **Port 27050** (clientport 27040) — clear of the game (27015-19) and HLTV (27020-24) ranges
- **24 slots**, **60-minute** map timer
- Map rotation: **dod_pandemic_aim → dod_orange → repeat** (starts on pandemic_aim)
- **rcon password** — set `<WARMUP_RCON>` in `dodserver.cfg` at deploy (this server only, for an admin to change maps). Placeholder in the repo (public); the real value lives in the local gitignored `infrastructure.md`.
- **Logging off**, stock high-fps (`sys_ticrate 1000`, `-pingboost 2`, **no `-absgrid`** — that's a KTP-engine flag)
- Lives on the **larger HDD** (`/srv/ktpdata/warmup`), pinned `taskset -c 0,1` (housekeeping cores)

## Install (once the box is online)
1. Fresh LinuxGSM DoD instance on the big disk — do NOT run `clone-ktp-stack.sh` on it:
   ```
   mkdir -p /srv/ktpdata/warmup && cd /srv/ktpdata/warmup
   .../linuxgsm.sh dodserver && ./dodserver auto-install
   ```
   This yields stock `hlds_linux` + stock `libsteam_api.so`, no addons.
2. Startparameters (its LinuxGSM instance cfg):
   `-game dod -strictportbind +ip <LAN_IP> -port 27050 +clientport 27040 +map dod_pandemic_aim +servercfgfile dodserver.cfg -maxplayers 24 -pingboost 2`
3. Drop these files into `serverfiles/dod/`:
   - `dodserver.cfg`  (substitute `<LAN_IP>` for the FastDL URL)
   - `mapcycle.txt`
4. Place both maps in `serverfiles/dod/maps/`: `dod_pandemic_aim.{bsp,res}` + its assets
   (WADs, `gfx/env/grnplsnt*`, `models/mapmodels/flags.mdl`) and `dod_orange.{bsp,res,txt}`.
   Also copy them to **FastDL** (`/var/www/fastdl/dod/maps/` + assets) so clients can download.
5. `ufw allow 27050/udp` — Phase 1 only opened 27015-27019.
6. Apply the LinuxGSM old-type-tmux patch to its modules before enabling any monitor cron.

## Notes
- `dod_orange`'s `.res` references two ambient sounds (`sound/ambience/bsl/axisscore.wav`,
  `alliesscore.wav`) that aren't on disk — **cosmetic, non-fatal** (missing sounds just
  don't play; only missing *models* crash a map). Safe to run as-is.
- `dod_pandemic_aim`'s assets are all present locally; they ride the FastDL/dod-base bundle.
