# KTP Infrastructure Reference

Complete reference for KTP server infrastructure, scheduled tasks, deployment procedures, and operational scripts.

---

## Table of Contents

- [Server Overview](#server-overview)
- [Architecture](#architecture)
- [Scheduled Tasks](#scheduled-tasks)
- [Scripts Reference](#scripts-reference)
- [Config Locations](#config-locations)
- [Log Files](#log-files)
- [Deployment Procedures](#deployment-procedures)
- [Backup System](#backup-system)
- [Monitoring](#monitoring)
- [Web Services](#web-services)
- [Systemd Services](#systemd-services)
- [Operational Notes](#operational-notes)

---

## Server Overview

| Server | Hostname | SSH User | Purpose | Ports |
|--------|----------|----------|---------|-------|
| Atlanta Game | neinatl | dodserver | 5 DoD game servers | 27015-27019 |
| Dallas Game | neindal | dodserver | 5 DoD game servers | 27015-27019 |
| Data Server | neindataatl | root | HLTV, MySQL, HLStatsX, FastDL | 27020-27029, 3306, 80 |

### Game Server Instances

Each game server cluster runs 5 instances via LinuxGSM:

| Instance | Port | HLTV Port | Directory |
|----------|------|-----------|-----------|
| Server 1 | 27015 | 27020 (ATL) / 27025 (DAL) | `~/dod-27015/` |
| Server 2 | 27016 | 27021 (ATL) / 27026 (DAL) | `~/dod-27016/` |
| Server 3 | 27017 | 27022 (ATL) / 27027 (DAL) | `~/dod-27017/` |
| Server 4 | 27018 | 27023 (ATL) / 27028 (DAL) | `~/dod-27018/` |
| Server 5 | 27019 | 27024 (ATL) / 27029 (DAL) | `~/dod-27019/` |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        KTP Infrastructure                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐    │
│  │   Atlanta    │     │    Dallas    │     │ Data Server  │    │
│  │  Game Cluster│     │  Game Cluster│     │              │    │
│  ├──────────────┤     ├──────────────┤     ├──────────────┤    │
│  │ 5 DoD Servers│     │ 5 DoD Servers│     │ 10 HLTV      │    │
│  │ Port 27015-19│     │ Port 27015-19│     │ Port 27020-29│    │
│  │              │     │              │     │              │    │
│  │ LinuxGSM     │     │ LinuxGSM     │     │ MySQL        │    │
│  │ KTPAMXX      │     │ KTPAMXX      │     │ HLStatsX     │    │
│  │ KTP-ReHLDS   │     │ KTP-ReHLDS   │     │ FastDL       │    │
│  └──────┬───────┘     └──────┬───────┘     │ FileDistrib  │    │
│         │                    │             └──────┬───────┘    │
│         │    Game Logs       │                    │            │
│         └────────────────────┼────────────────────┘            │
│                              │                                  │
│                              ▼                                  │
│                    ┌──────────────────┐                        │
│                    │  Discord Relay   │                        │
│                    │  (Cloud Run)     │                        │
│                    └──────────────────┘                        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### KTP Stack (Game Servers)

```
serverfiles/
├── engine_i486.so           # KTP-ReHLDS (custom game engine)
├── libsteam_api.so          # KTP Steam API (76KB - NOT stock 375KB!)
├── rehlds/
│   └── extensions.ini       # Extension loader config
└── dod/
    └── addons/
        └── ktpamx/          # KTPAMXX installation
            ├── dlls/        # ktpamx_i386.so, reapi_ktp_i386.so, etc.
            ├── modules/     # dodx_ktp_i386.so, curl_amxx_i386.so
            ├── plugins/     # KTPMatchHandler.amxx, etc.
            └── configs/     # Plugin configurations
```

---

## Scheduled Tasks

### Game Servers (Atlanta & Dallas)

All times are **EST (America/New_York)**.

| Schedule | Command | Description |
|----------|---------|-------------|
| Every minute | `dodserver monitor` | LinuxGSM auto-restart on crash |
| Daily 3:00 AM | `ktp-scheduled-restart.sh` | Nightly restart + Discord notification |
| Sunday 4:00 AM | `ktp-log-rotation.sh` | Prune logs older than 120 days |

**Crontab (dodserver user):**
```cron
*/1 * * * * /home/dodserver/dod-27015/dodserver monitor >> /home/dodserver/log/monitor.log 2>&1
*/1 * * * * /home/dodserver/dod-27016/dodserver2 monitor >> /home/dodserver/log/monitor.log 2>&1
*/1 * * * * /home/dodserver/dod-27017/dodserver3 monitor >> /home/dodserver/log/monitor.log 2>&1
*/1 * * * * /home/dodserver/dod-27018/dodserver4 monitor >> /home/dodserver/log/monitor.log 2>&1
*/1 * * * * /home/dodserver/dod-27019/dodserver5 monitor >> /home/dodserver/log/monitor.log 2>&1
0 3 * * * /home/dodserver/ktp-scheduled-restart.sh >> /home/dodserver/log/scheduled-restart.log 2>&1
0 4 * * 0 /home/dodserver/ktp-log-rotation.sh >> /home/dodserver/log/log-rotation.log 2>&1
```

### Data Server

| Schedule | Type | Command | Description |
|----------|------|---------|-------------|
| Daily 3:00 AM & 11:00 AM | systemd timer | `hltv-restart.service` | Restart all HLTV + Discord notification |
| Sunday 3:00 AM | cron | `/opt/ktp-backup.sh` | MySQL + config backup |
| Daily 4:00 AM | cron | `ktp-organize-hltv-demos.sh` | Organize HLTV demos |

**Crontab (root):**
```cron
0 3 * * 0 /opt/ktp-backup.sh >> /var/log/ktp-backup.log 2>&1
0 4 * * * /usr/local/bin/ktp-organize-hltv-demos.sh >> /var/log/ktp-demo-organize.log 2>&1
```

---

## Scripts Reference

### Game Server Scripts

| Script | Location | Description |
|--------|----------|-------------|
| `ktp-scheduled-restart.sh` | `~/` | Nightly restart with Discord embed notification |
| `restart-all-servers.sh` | `~/` | Manual restart (stops all, restarts in order, verifies) |
| `ktp-log-rotation.sh` | `~/` | Prune logs > 120 days, truncate large files |

### Data Server Scripts

| Script | Location | Description |
|--------|----------|-------------|
| `hltv-restart-all.sh` | `/usr/local/bin/` | Restart all HLTV proxies + Discord embed |
| `ktp-organize-hltv-demos.sh` | `/usr/local/bin/` | Organize demos into `Cluster/Hostname/MatchType/` |
| `ktp-backup.sh` | `/opt/` | MySQL + config backup (28-day retention) |
| `hltv-api.py` | `/home/hltvserver/` | HTTP API for HLTV control via FIFO pipes |
| `hltv-ctl.sh` | `/home/hltvserver/` | HLTV control script (start/stop/status) |
| `hltv-manager.sh` | `/home/hltvserver/` | HLTV process manager |
| `generate-hltv-configs.sh` | `/home/hltvserver/` | Generate HLTV config files |

---

## Config Locations

### Game Servers

| Path | Description |
|------|-------------|
| `~/dod-2701X/lgsm/config-lgsm/dodserver/` | LinuxGSM instance configs |
| `~/dod-2701X/serverfiles/dod/dodserver.cfg` | Main server config |
| `~/dod-2701X/serverfiles/dod/addons/ktpamx/configs/` | KTPAMXX plugin configs |

### Data Server

| Path | Description |
|------|-------------|
| `/etc/ktp/discord-relay.conf` | Discord relay URL, auth, channel IDs |
| `/home/hltvserver/hlds/configs/hltv-2702X.cfg` | HLTV instance configs |
| `/opt/hlstatsx/scripts/hlstats.conf` | HLStatsX daemon config |
| `/opt/ktp-file-distributor/config.json` | File distributor config |

---

## Log Files

### Game Servers

| Path | Description |
|------|-------------|
| `~/log/monitor.log` | LinuxGSM monitor output |
| `~/log/scheduled-restart.log` | Nightly restart script output |
| `~/dod-2701X/log/console/` | Server console logs |
| `~/dod-2701X/serverfiles/dod/logs/` | Game logs |
| `~/dod-2701X/serverfiles/dod/addons/ktpamx/logs/` | KTPAMXX plugin logs |

### Data Server

| Path | Description |
|------|-------------|
| `/var/log/ktp-backup.log` | Backup script output |
| `/var/log/ktp-demo-organize.log` | Demo organization output |
| `/var/log/hltv-restart.log` | HLTV restart output |
| `/home/hltvserver/hlds/dod/logs/` | HLTV logs |
| `/opt/hlstatsx/scripts/hlstats.log` | HLStatsX daemon log |

---

## Deployment Procedures

### Deploying Plugins to Game Servers

```bash
# Single server
scp KTPMatchHandler.amxx dodserver@<GAME_IP>:~/dod-27015/serverfiles/dod/addons/ktpamx/plugins/

# All instances on one cluster
for port in 27015 27016 27017 27018 27019; do
  scp KTPMatchHandler.amxx dodserver@<GAME_IP>:~/dod-$port/serverfiles/dod/addons/ktpamx/plugins/
done

# Both clusters
for ip in <ATL_GAME_IP> <DAL_GAME_IP>; do
  for port in 27015 27016 27017 27018 27019; do
    scp KTPMatchHandler.amxx dodserver@$ip:~/dod-$port/serverfiles/dod/addons/ktpamx/plugins/
  done
done
```

### Deploying Modules (DODX, ReAPI, etc.)

```bash
# Deploy to all instances on both clusters
for ip in <ATL_GAME_IP> <DAL_GAME_IP>; do
  for port in 27015 27016 27017 27018 27019; do
    scp dodx_ktp_i386.so dodserver@$ip:~/dod-$port/serverfiles/dod/addons/ktpamx/modules/
  done
done
```

### Deploying KTPAMXX Core

```bash
# Deploy ktpamx_i386.so to all instances
for ip in <ATL_GAME_IP> <DAL_GAME_IP>; do
  for port in 27015 27016 27017 27018 27019; do
    scp ktpamx_i386.so dodserver@$ip:~/dod-$port/serverfiles/dod/addons/ktpamx/dlls/
  done
done
```

### Deploying Scripts

```bash
# Game server scripts
scp scripts/ktp-scheduled-restart.sh dodserver@<ATL_GAME_IP>:~/
scp scripts/ktp-scheduled-restart.sh dodserver@<DAL_GAME_IP>:~/

# Data server scripts
scp scripts/hltv-restart-all.sh root@<DATA_SERVER_IP>:/usr/local/bin/
scp scripts/ktp-backup.sh root@<DATA_SERVER_IP>:/opt/
```

### Post-Deployment: Restart Servers

**IMPORTANT:** Only restart during off-peak hours or when no matches are active.

```bash
# Restart all servers on a cluster
ssh dodserver@<GAME_IP> "~/restart-all-servers.sh"

# Or restart individual instance
ssh dodserver@<GAME_IP> "~/dod-27015/dodserver restart"
```

---

## Backup System

**Script:** `/opt/ktp-backup.sh`
**Schedule:** Sundays at 3:00 AM EST
**Retention:** 28 days
**Location:** `/opt/backups/`

### What's Backed Up

- HLStatsX MySQL database (`hlstatsx`)
- File distributor configs
- HLStatsX daemon configs
- HLTV configs
- Systemd service files (ktp-*, hlstatsx)

### Manual Backup

```bash
ssh root@<DATA_SERVER_IP> "/opt/ktp-backup.sh"
```

### Restore from Backup

```bash
# List available backups
ls -la /opt/backups/

# Restore MySQL
mysql -u hlstatsx -p hlstatsx < /opt/backups/hlstatsx_YYYYMMDD.sql
```

---

## Monitoring

### Netdata

All servers report to **Netdata Cloud** with Discord alerts for critical issues.

- **Dashboard:** https://app.netdata.cloud (requires login)
- **Local Fallback:** `http://<SERVER_IP>:19999`

### Health Checks

```bash
# Memory
free -h

# Process uptime (detect recent restarts)
ps -eo pid,etime,cmd | grep hlds_linux | grep -v grep

# Load average
uptime

# UDP buffer errors (should be 0 or stable)
cat /proc/net/snmp | grep "Udp:" | tail -1 | awk '{print "RcvbufErrors:", $6}'

# All servers status
for i in 1 2 3 4 5; do
  echo "Server $i:";
  ~/dod-2701$((i+4))/dodserver$i details 2>/dev/null | grep -E "(Status|Players)"
done
```

---

## Web Services

| URL | Description |
|-----|-------------|
| `http://<DATA_SERVER_IP>/` | FastDL root (game file downloads) |
| `http://<DATA_SERVER_IP>/demos/` | HLTV Demo Browser |
| `http://<DATA_SERVER_IP>:8087/` | HLTV API endpoint |
| `http://<SERVER_IP>:19999/` | Netdata monitoring |

---

## Systemd Services

### Data Server

```bash
# HLTV restart timer status
systemctl status hltv-restart.timer
systemctl list-timers hltv-restart.timer

# Manual HLTV restart
systemctl start hltv-restart.service

# HLStatsX daemon
systemctl status hlstatsx

# View service logs
journalctl -u hltv-restart.service -n 50
journalctl -u hlstatsx -n 50
```

### Timer Configuration

**File:** `/etc/systemd/system/hltv-restart.timer`
```ini
[Unit]
Description=KTP HLTV Restart Timer

[Timer]
OnCalendar=*-*-* 03:00:00
OnCalendar=*-*-* 11:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

---

## Operational Notes

### Timezone

All servers **must** use `America/New_York` (EST) timezone.

```bash
# Check
timedatectl | grep "Time zone"

# Set if needed
sudo timedatectl set-timezone America/New_York
```

### LinuxGSM Monitor IP Configuration

**CRITICAL:** Each instance config must have `ip="<SERVER_IP>"` set, otherwise LinuxGSM monitors 127.0.0.1 and will falsely restart servers.

### LinuxGSM tmux Patch

LinuxGSM has a bug where the monitor kills valid tmux sessions. Lines 203-212 in `command_monitor.sh` are commented out on all KTP servers.

**Must reapply after:** `./dodserver update-lgsm`

```bash
for dir in dod-27015 dod-27016 dod-27017 dod-27018 dod-27019; do
  sed -i '203,212s/^/# KTP-DISABLED: /' ~/$dir/lgsm/modules/command_monitor.sh
done
```

### HLTV Demo Storage

- **Raw demos:** `/home/hltvserver/hlds/dod/`
- **Organized:** `/home/hltvserver/hlds/dod/demos/<Cluster>/<Hostname>/<MatchType>/`
- Organization runs nightly at 4:00 AM EST

### Discord Notifications

All scheduled restarts and critical events send Discord notifications via the Discord Relay service.

Config: `/etc/ktp/discord-relay.conf`
```ini
DISCORD_RELAY_URL=https://...
DISCORD_AUTH_SECRET=...
DISCORD_CHANNEL_ID_KTP=...
DISCORD_CHANNEL_ID_13=...
```
