# KTP LAN Event Setup

This guide covers setting up a complete KTP infrastructure for LAN events - including game servers, a local data server, HLTV, and stats tracking.

## Overview

A proper LAN setup mirrors the production infrastructure but runs entirely on the local network:

```
LAN Network
├── Data Server (1 machine)
│   ├── HLTV instances (spectating + recording)
│   ├── HLTV API (automated recording control)
│   ├── MySQL + HLStatsX (stats tracking)
│   └── FastDL (client file downloads)
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
| Game Server | 4 cores, 8GB RAM | 8 cores, 16GB RAM |
| Data Server | 2 cores, 4GB RAM | 4 cores, 8GB RAM |

A single powerful machine can run both roles (game servers in VMs, data server on host).

### Software
- Ubuntu 22.04 LTS on all servers
- Pre-built KTP artifacts (on USB drive or local storage)
- Network connectivity between all machines

### Network Requirements
| Port | Protocol | Service |
|------|----------|---------|
| 27015-27019 | UDP | Game servers |
| 27020-27029 | UDP | HLTV instances |
| 8087 | TCP | HLTV API |
| 80 | TCP | FastDL |
| 27500 | UDP | HLStatsX logging |

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
# On data server (as hltvserver)
./hltv-ctl.sh start
sudo systemctl start hltv-api

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

Edit each config file to point to your data server:

**hltv_recorder.ini:**
```ini
hltv_api_url = "http://192.168.1.100:8087"
hltv_api_key = "lan-api-key"
hltv_port = 27020
```

**dodserver.cfg:**
```
sv_lan 1
log_address_add 192.168.1.100:27500
sv_downloadurl "http://192.168.1.100/"
```

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

After starting HLTV instances, connect them to game servers:

```bash
# Via HLTV API
curl -X POST http://192.168.1.100:8087/connect \
    -H "Authorization: Bearer lan-api-key" \
    -H "Content-Type: application/json" \
    -d '{"port": 27020, "server": "192.168.1.10:27015"}'

# Or via screen directly
screen -r hltv-27020
> connect 192.168.1.10:27015
```

### Manual Recording

```bash
# Start recording
curl -X POST http://192.168.1.100:8087/record \
    -H "Authorization: Bearer lan-api-key" \
    -H "Content-Type: application/json" \
    -d '{"port": 27020, "filename": "match1_semifinal"}'

# Stop recording
curl -X POST http://192.168.1.100:8087/stoprecording \
    -H "Authorization: Bearer lan-api-key" \
    -H "Content-Type: application/json" \
    -d '{"port": 27020}'
```

### Automatic Recording

With KTPHLTVRecorder configured, recording starts automatically when matches begin:
- Plugin sends HTTP request to HLTV API
- HLTV starts recording with match ID as filename
- Recording stops when match ends

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

2. Verify log_address_add is set:
   ```bash
   grep log_address ~/dod-27015/serverfiles/dod/dodserver.cfg
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
└── fastdl/
    └── dod/
        ├── maps/
        └── sound/
```

## Example: 16-Player Tournament

### Hardware
- 1x Game Server: 8 cores, 16GB RAM
- 1x Data Server: 4 cores, 8GB RAM
- Gigabit switch

### Configuration
- 3 game server instances (27015, 27016, 27017)
- 3 HLTV instances (27020, 27021, 27022)
- Port 27015: Match server (main)
- Port 27016: Match server (backup)
- Port 27017: Warmup/practice

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
- [ ] Test match workflow on warmup server
- [ ] Verify HLTV recording works
- [ ] Verify stats are tracking
- [ ] Brief admins on `.forcereset` command
