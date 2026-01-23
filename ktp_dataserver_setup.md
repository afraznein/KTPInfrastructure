# KTP Data Server Setup

**Server:** `<DATA_SERVER_IP>` (neindataatl)
**OS:** Ubuntu 24.04.3 LTS
**Specs:** 8-core / 8GB RAM

---

## Initial System Configuration

### Timezone
```bash
sudo timedatectl set-timezone America/New_York
```

### RTC Configuration
Hardware clock must use UTC (prevents Netdata warnings):
```bash
sudo timedatectl set-local-rtc 0
```

### NTP with Chrony
Use chrony instead of systemd-timesyncd (properly sets kernel sync flag for Netdata):
```bash
sudo apt install -y chrony
systemctl status chrony
chronyc tracking  # "Leap status: Normal" = synced
```

---

## Services

| Service | Status | Port(s) | Details |
|---------|--------|---------|---------|
| **MySQL 8.0** | Running | 3306 | Database: `hlstatsx` |
| **Nginx** | Running | 80 | FastDL web server |
| **vsftpd** | Running | 21, 40000-40100 | FTP for file uploads |
| **HLTV** | Ready | 27020-27044 | 25 instances available |
| **HLStatsX** | Running | 27500 (UDP) | Stats daemon |
| **KTPFileDistributor** | Ready | - | File distribution to game servers |
| **HLTV Restart Timer** | Active | - | 3:00 AM / 11:00 AM EST |

---

## Credentials

### SSH
```
Host: <DATA_SERVER_IP>
User: root
Pass: <SSH_PASSWORD>
```

### MySQL
```
Host: localhost
Database: hlstatsx
User: hlstatsx
Password: <MYSQL_PASSWORD>
```

### FTP (FastDL uploads)
```
Host: <DATA_SERVER_IP>
User: ftpuser
Password: <FTP_PASSWORD>
Directory: /var/www/fastdl/
```

---

## FastDL

**URL:** `http://<DATA_SERVER_IP>/`

**Directory Structure:**
```
/var/www/fastdl/
└── dod/
    ├── maps/
    ├── sound/
    ├── models/
    └── ...
```

**Game Server Config:**
```
sv_downloadurl "http://<DATA_SERVER_IP>/dod"
sv_allowdownload 1
```

---

## HLTV

**Location:** `/home/hltvserver/hlds/`
**Configs:** `/home/hltvserver/hlds/configs/hltv-<port>.cfg`
**Ports:** 27020-27044 (25 instances available)
**Relay Delay:** 120 seconds

### Port Allocation
| Game Cluster | Game Ports | HLTV Ports | Status |
|--------------|------------|------------|--------|
| Atlanta (`<ATL_GAME_IP>`) | 27015-27019 | 27020-27024 | Active |
| Dallas (`<DAL_GAME_IP>`) | 27015-27019 | 27025-27029 | Active |
| Reserved | - | 27030-27044 | Available |

### Systemd Management (auto-restart on crash)
```bash
# Start/stop/restart single instance
systemctl start hltv@27020
systemctl stop hltv@27020
systemctl restart hltv@27020

# Enable on boot
systemctl enable hltv@27020

# Check status
systemctl status hltv@27020

# View logs
journalctl -u hltv@27020 -f

# Start/enable all 25 instances
for p in $(seq 27020 27044); do systemctl start hltv@$p; done
for p in $(seq 27020 27044); do systemctl enable hltv@$p; done
```

### Per-Instance Configuration
Each HLTV has its own config file at `/home/hltvserver/hlds/configs/hltv-<port>.cfg`

**Example config (hltv-27020.cfg):**
```
// HLTV Instance Config
// Auto-connects to game server on startup

name "KTP - Atlanta 1 - HLTV"
hostname "KTP - Atlanta 1 - HLTV"
maxclients 128
delay 60
rate 100000
adminpassword "<HLTV_ADMIN_PASSWORD>"
nomaster 0
autoretry 1

// Connect to game server
serverpassword "<PROXY_PASSWORD>"
connect "<GAME_SERVER_IP>:27015"
```

### Generate New Configs
```bash
# Regenerate missing config files
/home/hltvserver/generate-hltv-configs.sh
```

### Scheduled Restarts
HLTVs automatically restart twice daily (3:00 AM and 11:00 AM EST) with Discord notifications.

```bash
# Check timer status
systemctl list-timers hltv-restart.timer

# Manual restart all HLTVs
/usr/local/bin/hltv-restart-all.sh

# View restart logs
journalctl -u hltv-restart.service
```

---

## KTPFileDistributor

**Location:** `/opt/ktp-file-distributor/`
**Watch Directory:** `/home/dod/distribute/`
**Config:** `/opt/ktp-file-distributor/appsettings.json`
**Servers:** `/opt/ktp-file-distributor/servers.json`

Monitors the watch directory and distributes files to game servers via SFTP.

### Service Management
```bash
# Status
systemctl status ktp-file-distributor

# Start/Stop/Restart
systemctl start ktp-file-distributor
systemctl stop ktp-file-distributor
systemctl restart ktp-file-distributor

# View logs
journalctl -u ktp-file-distributor -f
tail -f /opt/ktp-file-distributor/logs/*.log
```

### Current Game Servers
- FastDL (localhost)
- Atlanta 1-5 (<ATL_GAME_IP>)
- Dallas 1-5 (<DAL_GAME_IP>)

### Adding New Game Servers
1. Add data server's SSH public key to the new game server:
   ```bash
   # Get the public key from data server
   cat /var/www/fastdl/.ssh/id_rsa.pub
   # Add to new server's ~/.ssh/authorized_keys
   ```

2. Edit `/opt/ktp-file-distributor/servers.json`:
   ```json
   {
     "name": "KTP - <City> <N>",
     "host": "<IP>",
     "port": 22,
     "username": "dodserver",
     "privateKeyPath": "/var/www/fastdl/.ssh/id_rsa",
     "remoteBasePath": "/home/dodserver/dod-<PORT>/serverfiles/dod",
     "enabled": true
   }
   ```

3. Restart the service:
   ```bash
   systemctl restart ktp-file-distributor
   ```

---

## Discord Integration

**Config File:** `/etc/ktp/discord-relay.conf`

Shared configuration for all KTP services that post to Discord.

```bash
# View/edit config
cat /etc/ktp/discord-relay.conf
nano /etc/ktp/discord-relay.conf
```

**Config Contents:**
```
RELAY_URL="https://discord-relay-xxxxx.run.app/reply"
AUTH_SECRET="your-auth-secret"
CHANNEL_HLTV_STATUS="channel-id"
```

---

## HLStatsX

**Location:** `/opt/hlstatsx/`
**Daemon:** `/opt/hlstatsx/scripts/hlstats.pl`
**Listen Port:** 27500 (UDP)

### Service Management
```bash
# Status
systemctl status hlstatsx

# Start/Stop/Restart
systemctl start hlstatsx
systemctl stop hlstatsx
systemctl restart hlstatsx

# View logs
journalctl -u hlstatsx -f
```

### Game Server Configuration
Add to each game server's `server.cfg`:
```
log on
logaddress_add <DATA_SERVER_IP> 27500
```

### Database Tables
- Base HLStatsX:CE tables (60 total)
- KTP custom tables:
  - `ktp_matches` - Match metadata
  - `ktp_match_players` - Players per match
  - `ktp_match_stats` - Aggregated stats per match

---

## Service Commands

```bash
# Check all services
systemctl status mysql nginx vsftpd hlstatsx

# Restart all services
systemctl restart mysql nginx vsftpd hlstatsx

# View service logs
journalctl -u <service> -f
```

---

## Firewall Ports

| Port | Protocol | Service |
|------|----------|---------|
| 22 | TCP | SSH |
| 21 | TCP | FTP |
| 80 | TCP | HTTP (FastDL) |
| 3306 | TCP | MySQL (local only) |
| 8087 | TCP | HLTV API |
| 27015-27050 | UDP | Game/HLTV |
| 27500 | UDP | HLStatsX |
| 40000-40100 | TCP | FTP Passive |

---

## File Locations

```
/home/hltvserver/
├── hlds/                    # HLTV installation
│   ├── hltv                 # HLTV binary
│   ├── configs/            # Per-instance configs
│   │   ├── hltv-27020.cfg
│   │   ├── hltv-27021.cfg
│   │   └── ...
│   └── dod/                # DoD mod folder
├── hltv-ctl.sh             # HLTV helper script
├── generate-hltv-configs.sh # Config generator
└── steamcmd/               # SteamCMD

/opt/hlstatsx/
├── scripts/                # HLStatsX daemon
│   ├── hlstats.pl         # Main daemon
│   ├── HLstats.plib       # KTP modified
│   └── HLstats_EventHandlers.plib  # KTP modified
└── sql/                    # Database schemas

/var/www/fastdl/           # FastDL root
└── dod/                   # DoD files

/opt/ktp-file-distributor/ # File Distributor
├── KTPFileDistributor     # Binary
├── appsettings.json       # App config
├── servers.json           # Target servers
└── logs/                  # Application logs

/home/dod/
└── distribute/            # Watch directory for file distribution

/etc/ktp/
└── discord-relay.conf     # Discord relay config (shared)

/usr/local/bin/
└── hltv-restart-all.sh    # HLTV restart script
```

---

## Maintenance

### Backup MySQL
```bash
mysqldump -u hlstatsx -p hlstatsx > /root/hlstatsx_backup_$(date +%Y%m%d).sql
```

### Update FastDL
Upload files via FTP to `/var/www/fastdl/dod/`

### Check Disk Space
```bash
df -h
du -sh /var/www/fastdl /home/hltvserver /opt/hlstatsx
```
