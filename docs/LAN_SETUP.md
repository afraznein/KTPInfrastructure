# KTP LAN Event Setup

This guide covers setting up a complete KTP infrastructure for LAN events - including game servers, a local data server, HLTV, voice (TeamSpeak), and stats tracking.

> **Two docs, two jobs — keep them in sync.**
> - To *install* the box, use the automated single-config orchestrator:
>   [`../provision/LAN-DEPLOY.md`](../provision/LAN-DEPLOY.md) (`lan-deploy.sh`,
>   one config file, one command). That is the primary install path.
> - **This** doc is the operational companion: architecture, day-of runbook,
>   HLTV / stats / TeamSpeak setup, and troubleshooting.
>
> **Current plan (July 2026 LAN):** one all-in-one box runs everything —
> game servers + HLTV + TeamSpeak — for up to **72 players (12 teams × 6)**.
> Hardware sizing and current build options live in the benchmark dossier
> (AC-admin → `fleet-benchmark.html`).
>
> **6 game servers:** set `NUM_INSTANCES=6` in `lan-deploy.conf`. The scripts now
> create 6 instances (ports 27015-27020), auto-place HLTV right after
> (27021-27026), and pin one CPU core per server — provisioning warns if the box
> has fewer than `NUM_INSTANCES + 2` cores. Leave `HLTV_BASE_PORT` empty so it
> auto-adapts. The port tables further down still show the 5-server example
> ranges for reference.

## Overview

A proper LAN setup mirrors the production infrastructure but runs entirely on the local network:

```
LAN Network
├── Data Server (1 machine)
│   ├── HLTV instances (spectating + recording)
│   ├── HLTV API (automated recording control)
│   ├── MySQL + HLStatsX (stats tracking)
│   ├── FastDL (client file downloads)
│   └── TeamSpeak 3 (voice — all players)
│
└── Game Servers (1+ machines)
    └── 5 DoD instances per machine
```

**What's different from online mode:**
- Discord notifications disabled (no internet required)
- All services run on local network
- HLTV/Stats point to local data server instead of production

## Prerequisites

### Hardware

| Role | Minimum Specs | Recommended |
|------|---------------|-------------|
| **All-in-one LAN box (current plan)** | 8 cores, 32GB RAM, 2× SSD | 12 cores, 32–64GB, 2× NVMe |
| Game Server (split setup) | 4 cores, 8GB RAM | 8 cores, 16GB RAM |
| Data Server (split setup) | 2 cores, 4GB RAM | 4 cores, 8GB RAM |

The current plan runs **everything on one all-in-one box** — game servers, data
server, HLTV, and TeamSpeak. It must be **x86-64**: the engine binaries are
32-bit i386 and need i386 multilib, so ARM is ruled out. The two SSDs split
game-server data from HLTV recordings. Full sizing rationale and current build
options are in the benchmark dossier (AC-admin → `fleet-benchmark.html`). A
split setup (separate game/data machines) still works if you prefer.

### Software
- Ubuntu 22.04 LTS or 24.04 LTS on all servers
- Pre-built KTP artifacts (on USB drive or local storage)
- Network connectivity between all machines

### Network Requirements
| Port | Protocol | Service |
|------|----------|---------|
| 27015-27019 | UDP | Game servers (current plan: 6 — see Open item) |
| 27020-27029 | UDP | HLTV instances |
| 8087 | TCP | HLTV API |
| 80 | TCP | FastDL |
| 27500 | UDP | HLStatsX logging |
| 9987 | UDP | TeamSpeak voice |
| 30033 | TCP | TeamSpeak file transfer |
| 10011 | TCP | TeamSpeak ServerQuery (LAN admin only — do not expose off-LAN) |

## Quick Start

### 1. Set Up Data Server First

```bash
# On the data server machine (as root)
sudo ./provision/provision-lan-dataserver.sh

# Follow post-install steps for HLTV binaries and HLStatsX
```

### 2. Set Up Game Server(s)

```bash
# On each game server machine (as root)
sudo ./provision/provision-gameserver.sh

# Switch to dodserver user
su - dodserver

# Install LinuxGSM
./provision/install-linuxgsm.sh <GAME_SERVER_IP>

# Deploy KTP stack
./provision/clone-ktp-stack.sh /path/to/artifacts
```

### 3. Configure for LAN

```bash
# Copy LAN configs (replace IPs first!)
cp config/lan/*.ini ~/dod-27015/serverfiles/dod/addons/ktpamx/configs/

# Edit hltv_recorder.ini with your data server IP
nano ~/dod-27015/serverfiles/dod/addons/ktpamx/configs/hltv_recorder.ini

# Copy server config template
cp config/lan/dodserver.cfg.example ~/dod-27015/serverfiles/dod/dodserver.cfg
# Edit with your data server IP for FastDL and HLStatsX
```

### 4. Start Everything

```bash
# On data server (as root — hltv-ctl.sh wraps the systemd hltv@<port> units)
/home/hltvserver/hltv-ctl.sh start
systemctl start hltv-api    # usually already enabled + started by provisioning

# On game servers (as dodserver)
~/restart-all-servers.sh
```

## Detailed Setup

### Data Server

#### 1. Run Provisioning Script

```bash
sudo ./provision/provision-lan-dataserver.sh
```

This installs and configures:
- MySQL with hlstatsx database
- Nginx for FastDL
- HLTV control scripts
- HLTV API service
- Firewall rules

#### 2. Install HLTV Binaries

HLTV binaries need to be copied manually:

```bash
# Copy to data server
scp hltv hltv_i686.so proxy.so root@<DATA_SERVER>:/home/hltvserver/hlds/

# Set permissions
ssh root@<DATA_SERVER> "chown hltvserver:hltvserver /home/hltvserver/hlds/hltv*"
ssh root@<DATA_SERVER> "chmod +x /home/hltvserver/hlds/hltv"
```

#### 3. Install HLStatsX (Optional but Recommended)

```bash
# Download HLStatsX CE
wget https://github.com/NomisCZ/hlstatsx-community-edition/archive/refs/heads/master.zip
unzip master.zip
mv hlstatsx-community-edition-master /opt/hlstatsx

# Import database schema
mysql -u hlstatsx -p hlstatsx < /opt/hlstatsx/sql/install.sql

# Configure
nano /opt/hlstatsx/scripts/hlstats.conf
# Set: DBHost=localhost, DBUsername=hlstatsx, DBPassword=<from provision script>

# Start daemon
cd /opt/hlstatsx/scripts
./run_hlstats start
```

#### 4. Populate FastDL

Copy game files that clients need to download:

```bash
# On data server
mkdir -p /var/www/fastdl/dod

# Copy custom content (maps, sounds, etc.)
scp -r maps/*.bsp root@<DATA_SERVER>:/var/www/fastdl/dod/maps/
scp -r sound/* root@<DATA_SERVER>:/var/www/fastdl/dod/sound/
```

### Game Servers

#### 1. Run Provisioning

```bash
# As root
sudo ./provision/provision-gameserver.sh

# As dodserver
su - dodserver
./provision/install-linuxgsm.sh <THIS_SERVER_IP>
./provision/clone-ktp-stack.sh /path/to/artifacts
```

#### 2. Configure for LAN

Edit each config file to point to your data server. (`lan-deploy.sh` writes
these automatically — manual editing is only needed for standalone installs.)

**hltv_recorder.ini** — values must be UNQUOTED (the plugin parser keeps
quotes as part of the value); the key comes from
`/root/ktp-dataserver-credentials.txt` (`HLTV_API_KEY=`):
```ini
hltv_enabled = 1
hltv_api_url = http://192.168.1.100:8087
hltv_api_key = <HLTV_API_KEY from the credentials file>
hltv_port = 27020
```

**dodserver.cfg:**
```
sv_lan 0
logaddress_add 192.168.1.100 27500
sv_downloadurl "http://192.168.1.100/"
```

> **`sv_lan 0` depends on venue internet for Steam auth.** It is the correct
> setting — real SteamIDs are required for per-player HLStatsX, admin auth, and
> AC identity. But if the venue uplink dies mid-event, players can't authenticate
> and new joins break. **Contingency:** set `sv_lan 1` on the affected server(s)
> to let players connect without Steam, and set `Mode "LAN"` (or `NameTrack`) in
> `hlstats.conf` so HLStatsX keys players by name instead of collapsing every
> `STEAM_ID_LAN` player into one row. Cost: no per-player SteamID stats, SteamID
> admin/AC identity degrades. Revert to `sv_lan 0` once the uplink is back.

#### 3. Apply to All Instances

```bash
# Copy configs to all instances
for port in 27015 27016 27017 27018 27019; do
    cp ~/dod-27015/serverfiles/dod/addons/ktpamx/configs/*.ini \
       ~/dod-$port/serverfiles/dod/addons/ktpamx/configs/
    cp ~/dod-27015/serverfiles/dod/dodserver.cfg \
       ~/dod-$port/serverfiles/dod/
done
```

## Network Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     LAN Event Network                        │
│                      192.168.1.0/24                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────┐        ┌──────────────────┐          │
│  │  Game Server 1   │        │   Data Server    │          │
│  │  192.168.1.10    │        │  192.168.1.100   │          │
│  ├──────────────────┤        ├──────────────────┤          │
│  │ Port 27015 ──────┼───────►│ HLTV 27020       │          │
│  │ Port 27016 ──────┼───────►│ HLTV 27021       │          │
│  │ Port 27017 ──────┼───────►│ HLTV 27022       │          │
│  │ Port 27018 ──────┼───────►│ HLTV 27023       │          │
│  │ Port 27019 ──────┼───────►│ HLTV 27024       │          │
│  │                  │        │                  │          │
│  │ Logs ────────────┼───────►│ HLStatsX :27500  │          │
│  │ FastDL ◄─────────┼────────┤ Nginx :80        │          │
│  │ Recording ───────┼───────►│ HLTV API :8087   │          │
│  └──────────────────┘        └──────────────────┘          │
│                                                              │
│  ┌──────────────────┐                                       │
│  │   Player PCs     │                                       │
│  │ 192.168.1.50-99  │                                       │
│  ├──────────────────┤                                       │
│  │ Connect to game  │                                       │
│  │ Watch HLTV       │                                       │
│  │ Download files   │                                       │
│  └──────────────────┘                                       │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## HLTV Setup

### Connecting HLTV to Game Servers

The generated `hltv-<port>.cfg` files already carry `connect` + `serverpassword`
lines pairing each proxy 1:1 with its game server (KTPHLTVRecorder 1.7.0
always-on architecture) — no manual connect step. To re-point one manually:

```bash
# Via the HLTV API's command passthrough (auth is X-Auth-Key; the key is in
# /root/ktp-dataserver-credentials.txt):
curl -X POST http://192.168.1.100:8087/hltv/27020/command \
    -H "X-Auth-Key: <HLTV_API_KEY>" \
    -d '{"command": "connect 192.168.1.10:27015"}'

# Or write to the instance's FIFO cmdpipe directly (as root/hltvserver):
echo 'connect 192.168.1.10:27015' > /home/hltvserver/cmdpipes/hltv-27020.pipe
```

### Recording (always-on — 1.7.0 architecture)

Recording is NOT started/stopped per match. Each HLTV config carries
`record auto_lanN`, so every instance records continuously from boot; demos
accumulate as `auto_lanN*.dem` under `/home/hltvserver/hlds/dod/` and are
browsable at `http://<LAN_IP>/demos`. The KTPHLTVRecorder plugin only:
- health-checks `GET /hltv/<port>/state` at match start (players get a chat
  warning if the paired HLTV is down or not recording), and
- drives `POST /hltv/<port>/restart` via the `.hltvrestart` admin command.

There is no renamer/organizer at the LAN — identify match demos by timestamp
and map (each map change rotates to a new `auto_lanN-<date>-<map>.dem`).
No cleanup cron is installed (it would delete unrenamed demos); budget
~3 GB/day/instance and archive demos after the event.

Manual state check:

```bash
curl -H "X-Auth-Key: <HLTV_API_KEY>" http://192.168.1.100:8087/hltv/27020/state
# -> {"recording": true, "basename": "auto_lan1-...", "process_running": true, ...}
```

### HLTV Spectators

Players can watch matches via HLTV:
```
connect 192.168.1.100:27020
```

## Match Workflow

The match workflow is identical to online mode:

1. **Setup**: Players join server
2. **Start**: Captain runs `.ktp password` or `.draft`
3. **Confirm**: Both teams `.confirm`
4. **Ready**: Players `.ready` (6 per team)
5. **Live**: Match begins, HLTV auto-records
6. **Pause**: `.tech` for technical pauses
7. **End**: Scores displayed, HLTV recording saved

The only difference is Discord notifications don't post.

## HLStatsX Stats

### Viewing Stats

If you installed the HLStatsX web interface:

```bash
# Install Apache/PHP for web interface
apt-get install apache2 php php-mysql
cp -r /opt/hlstatsx/web/* /var/www/html/hlstatsx/
```

Access at: `http://192.168.1.100/hlstatsx/`

### Without Web Interface

Stats are still tracked in MySQL:

```sql
-- Top players
SELECT name, skill, kills, deaths
FROM hlstats_Players
ORDER BY skill DESC LIMIT 10;

-- Recent matches
SELECT * FROM hlstats_Events_Entries
ORDER BY id DESC LIMIT 100;
```

## TeamSpeak Voice Server

All LAN players connect to one TeamSpeak 3 server running on the LAN box
alongside the game servers. **TeamSpeak ships an official Linux amd64 server
build — it runs natively on Ubuntu, no Windows needed** (Linux is the normal way
to host it). It's a 64-bit binary, so unlike the game servers it needs no 32-bit
libraries, and it rides the OS/housekeeping cores next to HLTV — it never
consumes an isolated game core. Footprint at 72 players: ~50–150 MB RAM and a
fraction of one core.

### Ports

```bash
sudo ufw allow 9987/udp comment "TeamSpeak voice"
sudo ufw allow 30033/tcp comment "TeamSpeak file transfer"
sudo ufw allow 10011/tcp comment "TeamSpeak ServerQuery (LAN admin)"
```

Keep 10011 (ServerQuery) on the LAN only — never expose it off-network.

### Install

The download needs internet — **grab the tarball before the event** if the box
will be air-gapped (stage it on the USB package; see Offline Artifact
Preparation).

```bash
# Dedicated unprivileged user
sudo useradd -m -s /bin/bash teamspeak

# Latest Linux amd64 server from https://teamspeak.com/downloads
# (pin a known version for air-gapped installs)
TS_VER=3.13.7
sudo -u teamspeak bash -c "cd ~ && \
  wget https://files.teamspeak-services.com/releases/server/${TS_VER}/teamspeak3-server_linux_amd64-${TS_VER}.tar.bz2 && \
  tar xjf teamspeak3-server_linux_amd64-${TS_VER}.tar.bz2"

# Accept the license (without this the server refuses to start)
touch /home/teamspeak/teamspeak3-server_linux_amd64/.ts3server_license_accepted
```

### First run — capture the admin token (shown once)

The first start prints a one-time **ServerAdmin privilege key** and the
ServerQuery login. **Save both** — the privilege key is how you claim admin in
the client, and it is only shown once.

```bash
sudo -u teamspeak /home/teamspeak/teamspeak3-server_linux_amd64/ts3server_startscript.sh start
sleep 3
grep -iE "token=|loginname=" /home/teamspeak/teamspeak3-server_linux_amd64/logs/*.log
sudo -u teamspeak /home/teamspeak/teamspeak3-server_linux_amd64/ts3server_startscript.sh stop
```

### Auto-start with systemd

```bash
sudo tee /etc/systemd/system/ts3server.service >/dev/null <<'EOF'
[Unit]
Description=TeamSpeak 3 Server
After=network.target

[Service]
Type=simple
User=teamspeak
WorkingDirectory=/home/teamspeak/teamspeak3-server_linux_amd64
ExecStart=/home/teamspeak/teamspeak3-server_linux_amd64/ts3server_minimal_runscript.sh
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now ts3server
sudo systemctl status ts3server
```

### Slot license — REQUIRED for 72 players

The default (unlicensed) server caps at **32 slots**. A full LAN is 72 players,
so you must raise the cap with TeamSpeak's **free non-commercial license** (up
to 512 slots):

1. Request it at https://teamspeak.com/en/licensing (free, non-profit/gamer tier).
2. Drop `licensekey.dat` in the server directory
   (`/home/teamspeak/teamspeak3-server_linux_amd64/`).
3. `sudo systemctl restart ts3server`.

**Do this well before the event** — without the key you're locked to 32 of 72
players on the day.

### Players connect

Point the TeamSpeak client at the LAN box (default port 9987, no port needed):

```
<LAN_IP>
```

Suggested layout: a lobby plus one channel per team. Splitting into team
channels keeps per-channel voice relay tiny (a few Mbps) instead of one big
72-person channel.

## Troubleshooting

### HLTV Won't Connect to Game Server

1. Verify game server is running:
   ```bash
   ~/status.sh
   ```

2. Check firewall allows HLTV traffic:
   ```bash
   # On game server
   sudo ufw status
   ```

3. Verify sv_lan is set:
   ```bash
   grep sv_lan ~/dod-27015/serverfiles/dod/dodserver.cfg
   ```

### Stats Not Recording

1. Check HLStatsX daemon is running:
   ```bash
   ps aux | grep hlstats
   ```

2. Verify logaddress_add is set:
   ```bash
   grep logaddress ~/dod-27015/serverfiles/dod/dodserver.cfg
   ```

3. Check for UDP traffic:
   ```bash
   tcpdump -i any port 27500
   ```

### FastDL Not Working

1. Test Nginx is running:
   ```bash
   curl http://192.168.1.100/
   ```

2. Check file permissions:
   ```bash
   ls -la /var/www/fastdl/
   ```

3. Verify sv_downloadurl in server config.

### Players Can't Connect

1. Check firewall on game server
2. Verify correct IP in LinuxGSM config
3. Test with: `ping <GAME_SERVER_IP>`

### TeamSpeak Issues

1. Server won't start — confirm the license-accepted file exists:
   ```bash
   ls -la /home/teamspeak/teamspeak3-server_linux_amd64/.ts3server_license_accepted
   ```
2. Capped at 32 slots — the free-license cap; install `licensekey.dat` and restart.
3. Lost the admin privilege key — generate a new one:
   ```bash
   sudo -u teamspeak /home/teamspeak/teamspeak3-server_linux_amd64/ts3server_startscript.sh stop
   grep -i "token=" /home/teamspeak/teamspeak3-server_linux_amd64/logs/*.log   # or use ServerQuery: tokenadd
   ```
4. Players can't connect — check the service and the voice port:
   ```bash
   systemctl status ts3server
   sudo ufw status | grep 9987
   ```

## Offline Artifact Preparation

Before the LAN event, prepare a USB drive with everything needed:

```
ktp-lan-package/
├── artifacts/
│   └── 20260127/
│       ├── engine/
│       ├── ktpamx/
│       └── plugins/
├── config/
│   └── lan/
├── provision/
│   ├── provision-gameserver.sh
│   ├── provision-lan-dataserver.sh
│   ├── install-linuxgsm.sh
│   └── clone-ktp-stack.sh
├── hltv/
│   ├── hltv
│   ├── hltv_i686.so
│   └── proxy.so
├── hlstatsx/
│   └── hlstatsx-ce.zip
├── teamspeak/
│   ├── teamspeak3-server_linux_amd64-<version>.tar.bz2
│   └── licensekey.dat          # free 512-slot non-commercial key
├── dod-base/
│   └── dod-base-files.tar.gz   # game-server dod/: custom maps + OVERVIEWS,
│                               # WADs, ktp_*.cfg (scripts/package-dod-base.sh)
└── fastdl/
    └── dod/
        ├── maps/
        └── sound/
```

The **dod-base** tarball (set as `DOD_BASE_PATH`) is what puts the custom KTP
maps and their command-map overviews on the game servers. Steam only provides
stock DoD content, so without it the servers can't load custom maps. This is
separate from `fastdl/` (which only feeds client downloads).

If the LAN is air-gapped, the TeamSpeak tarball and the `licensekey.dat` must be
on the USB — neither can be fetched on the day without internet.

## Example: 16-Player Tournament

### Hardware
- 1x Game Server: 8 cores, 16GB RAM
- 1x Data Server: 4 cores, 8GB RAM
- Gigabit switch

### Configuration
- 5 competitive game server instances (27015-27019, full KTP stack)
- 5 HLTV proxy instances (27020-27024, index-paired to the game servers)
- 1 stock warmup server (27050 — 32 slots, no plugins, no HLTV; a SEPARATE manual
  install, not part of `NUM_INSTANCES`). Its port is outside Phase 1's firewall
  range, so it needs an explicit `ufw allow 27050/udp` (clientport 27040).

### IP Assignments
| Machine | IP | Role |
|---------|-----|------|
| Game Server | 192.168.1.10 | DoD servers |
| Data Server | 192.168.1.100 | HLTV, Stats, FastDL |
| Admin PC | 192.168.1.2 | Tournament management |
| Players | 192.168.1.50-99 | DHCP pool |

### Day-of Checklist

- [ ] Power on all servers
- [ ] Verify network connectivity
- [ ] Start data server services (HLTV, HLStatsX, Nginx)
- [ ] Start game servers
- [ ] Connect HLTV to game servers
- [ ] Start TeamSpeak (`systemctl status ts3server`); confirm slot license is active (72-capable, not 32)
- [ ] Test a TeamSpeak client connects and admin claims the privilege key
- [ ] Test match workflow on warmup server
- [ ] Verify HLTV recording works
- [ ] Verify stats are tracking
- [ ] Brief admins on `.forcereset` command
