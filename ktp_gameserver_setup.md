# KTP Game Server Setup Guide

## Server Clusters

### Atlanta (neinatl)
**VPS:** <ATL_GAME_IP>
**OS:** Ubuntu (via LinuxGSM)
**Specs:** 4-core / 3.8GB RAM
**User:** dodserver (password: <DODSERVER_PASSWORD>, passwordless sudo)
**Netdata:** N/A

| Instance | Port | HLTV Port | Status |
|----------|------|-----------|--------|
| Atlanta 1 | 27015 | 27020 | Running |
| Atlanta 2 | 27016 | 27021 | Running |
| Atlanta 3 | 27017 | 27022 | Running |
| Atlanta 4 | 27018 | 27023 | Running |
| Atlanta 5 | 27019 | 27024 | Running |

### Dallas (neindal)
**VPS:** <DAL_GAME_IP>
**OS:** Ubuntu (via LinuxGSM)
**Specs:** 4-core / 3.8GB RAM
**User:** dodserver (password: <DODSERVER_PASSWORD>, passwordless sudo)
**Netdata:** http://<DAL_GAME_IP>:19999

| Instance | Port | HLTV Port | Status |
|----------|------|-----------|--------|
| Dallas 1 | 27015 | 27025 | Running |
| Dallas 2 | 27016 | 27026 | Running |
| Dallas 3 | 27017 | 27027 | Running |
| Dallas 4 | 27018 | 27028 | Running |
| Dallas 5 | 27019 | 27029 | Running |

---

## Prerequisites

- LinuxGSM installed
- SteamCMD installed
- UFW configured for ports

---

## System Configuration

### Timezone Configuration (Required)
All KTP servers must use `America/New_York` (EST) timezone for scheduled tasks to run simultaneously.

```bash
# Check current timezone
timedatectl | grep "Time zone"

# Set timezone
sudo timedatectl set-timezone America/New_York

# Verify
timedatectl | grep "Time zone"
# Should show: Time zone: America/New_York (EST, -0500)
```

### RTC Timezone Configuration (Required)
The hardware clock (RTC) must use UTC, not local time. Local RTC causes Netdata clock sync warnings.

```bash
# Check current setting
timedatectl | grep "RTC in local TZ"
# Should show: RTC in local TZ: no

# Fix if needed
sudo timedatectl set-local-rtc 0
```

### NTP Time Sync with Chrony (Required)
Use chrony instead of systemd-timesyncd. Chrony properly sets the kernel synchronization flag that Netdata monitors via `adjtimex()`. Without chrony, Netdata will generate false "clock not synchronized" alerts even when the clock is actually synced.

```bash
# Install chrony (removes systemd-timesyncd automatically)
sudo apt install -y chrony

# Verify service is running
systemctl status chrony

# Check synchronization
chronyc tracking
# "Leap status: Normal" indicates proper sync

# Verify kernel sync flag (what Netdata checks)
# This should show state=1 after chrony syncs
cat /sys/devices/system/clocksource/clocksource0/current_clocksource
```

### UDP Buffer Configuration (Required)
Game servers generate heavy UDP traffic. Default Linux buffer sizes cause packet drops, resulting in lag and hit registration issues.

**Check for UDP errors:**
```bash
cat /proc/net/snmp | grep "Udp:" | tail -1
# Look at column 6 (RcvbufErrors) - should be 0 or not climbing
```

**Check current buffer sizes:**
```bash
sysctl net.core.rmem_max net.core.rmem_default net.core.wmem_max net.core.wmem_default
# Default 212992 (208KB) is too small for multiple game servers
```

**Apply fix:**
```bash
# Edit sysctl.conf
sudo nano /etc/sysctl.conf

# Add these lines:
# KTP Game Server UDP buffers
net.core.rmem_max=26214400
net.core.rmem_default=26214400
net.core.wmem_max=26214400
net.core.wmem_default=26214400

# Apply changes
sudo sysctl -p

# Verify
sysctl net.core.rmem_max  # Should show 26214400 (25MB)
```

### Swap Configuration (Recommended)
Servers without swap risk OOM kills under memory pressure:
```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### Process Priority (Recommended)
Give game servers higher CPU scheduling priority than background processes (netdata, logging, etc.). This helps reduce brief stalls that can cause lag spikes.

**Step 1: Allow dodserver to use negative nice values**
```bash
# Add to /etc/security/limits.conf
echo 'dodserver        -       nice            -5' | sudo tee -a /etc/security/limits.conf

# Verify (requires new SSH session)
nice -n -5 echo 'test'  # Should succeed without "Permission denied"
```

**Step 2: Configure LinuxGSM to use nice**
```bash
# Add to common.cfg (applies to all instances)
echo 'nice="-5"' >> ~/dod-27015/lgsm/config-lgsm/dodserver/common.cfg
```

The nice setting takes effect on next server restart. Verify with:
```bash
ps -o pid,ni,comm -p $(pgrep hlds_linux)
# NI column should show -5
```

### Firewall Configuration (UFW)
Enable UFW with rules for game servers:
```bash
sudo ufw allow 22/tcp comment "SSH"
sudo ufw allow 27015:27019/udp comment "DoD Game Servers"
sudo ufw allow 27015:27019/tcp comment "DoD RCON"
sudo ufw allow 19999/tcp comment "Netdata"
sudo ufw allow 8087/tcp comment "HLTV API"
sudo ufw --force enable
sudo ufw status
```

### LinuxGSM Monitor Cron
Set up auto-restart on crash for all server instances:
```bash
mkdir -p ~/log
crontab -e
```

**CRITICAL:** Ensure `ip="<SERVER_IP>"` is set in each instance config, otherwise LinuxGSM monitors 127.0.0.1 and will falsely restart servers after ~8 failed queries.

Add entries (adjust paths for each instance):
```
*/1 * * * * /home/dodserver/dod-27015/dodserver monitor >> /home/dodserver/log/monitor.log 2>&1
*/1 * * * * /home/dodserver/dod-27016/dodserver2 monitor >> /home/dodserver/log/monitor.log 2>&1
*/1 * * * * /home/dodserver/dod-27017/dodserver3 monitor >> /home/dodserver/log/monitor.log 2>&1
*/1 * * * * /home/dodserver/dod-27018/dodserver4 monitor >> /home/dodserver/log/monitor.log 2>&1
*/1 * * * * /home/dodserver/dod-27019/dodserver5 monitor >> /home/dodserver/log/monitor.log 2>&1
```

### LinuxGSM "Old Type" tmux Session Bug

**Status:** Patched on all KTP servers (January 2026)

LinuxGSM has a bug in `command_monitor.sh` where the "old type tmux session" detection uses `pgrep -f` with a pattern that matches BOTH old and new session formats due to substring matching. This causes the monitor to kill healthy servers thinking they're using deprecated tmux sessions.

**Symptoms:**
- Monitor log shows repeated kills: `Killing process using old type tmux session`
- Servers randomly restart every few minutes
- Mass player disconnects at regular intervals

**Root Cause:**
The detection at lines 203-212 in `command_monitor.sh` uses:
```bash
pgrep -f "tmux new-session -d -x ... -s ${sessionname}"
```
This pattern matches the new format `tmux -L xxx new-session -d ...` because pgrep does substring matching.

**Fix Applied:**
Comment out lines 203-212 in each instance's `command_monitor.sh`:
```bash
# On each game server cluster:
for dir in dod-27015 dod-27016 dod-27017 dod-27018 dod-27019; do
  sed -i '203,212s/^/# KTP-DISABLED: /' ~/$dir/lgsm/modules/command_monitor.sh
done
```

**Note:** This patch will need to be reapplied after LinuxGSM updates that overwrite the module files. Check monitor logs after any LinuxGSM update for the "old type tmux session" message.

---

## Atlanta 1 (Reference)

**Directory:** `/home/dodserver/`
**LinuxGSM Script:** `./dodserver`
**Process:** `hlds_linux -game dod -port 27015`

### Resource Usage (idle)
- CPU: ~8% of 1 core
- RAM: ~125 MB

---

## Setting Up Additional Instances

### Method: LinuxGSM Multiple Instances

LinuxGSM supports multiple instances by creating copies of the main script with different names. Each instance gets its own config.

---

## Atlanta 2 Setup (Port 27016)

### Step 1: Copy LinuxGSM Structure

```bash
cd ~/dod-27016

# Copy LinuxGSM scripts and directories
cp ~/dod-27015/linuxgsm.sh ~/dod-27016/
cp ~/dod-27015/dodserver ~/dod-27016/dodserver2
cp -r ~/dod-27015/lgsm ~/dod-27016/
```

### Step 2: Create Instance Config

**IMPORTANT:** LinuxGSM looks for configs in `lgsm/config-lgsm/dodserver/` directory.
The instance-specific config must be named `<scriptname>.cfg` (e.g., `dodserver2.cfg`).

```bash
nano ~/dod-27016/lgsm/config-lgsm/dodserver/dodserver2.cfg
```

**Config contents (NO leading spaces!):**
```bash
##################################
####### Instance Settings ########
##################################
port="27016"
clientport="27006"
ip="<ATL_GAME_IP>"
servercfg="dodserver.cfg"
startparameters="-game dod -strictportbind +ip ${ip} -port ${port} +clientport ${clientport} +map ${defaultmap} +servercfgfile ${servercfg} -maxplayers 13 -pingboost 2 +condebug"
```

### Step 3: Copy Server Files

```bash
# Copy entire serverfiles from Atlanta 1 (~350MB)
cp -r ~/dod-27015/serverfiles ~/dod-27016/

# Create log directory
mkdir -p ~/dod-27016/log
```

### Step 4: Update Instance-Specific Configs

```bash
# Create servername configs for Atlanta 2
echo 'hostname "KTP - Atlanta 2 - KTP Match In Progress"' > ~/dod-27016/serverfiles/dod/configs/servername.cfg
echo 'hostname "KTP - Atlanta 2"' > ~/dod-27016/serverfiles/dod/configs/servernamedefault.cfg

# Update HLTV recorder to use port 27021
sed -i 's/hltv_port = 27020/hltv_port = 27021/' ~/dod-27016/serverfiles/dod/addons/ktpamx/configs/hltv_recorder.ini

# Fix logaddress if needed (ensure no typo)
sed -i 's/log_address_add/logaddress_add/' ~/dod-27016/serverfiles/dod/dodserver.cfg
```

### Step 5: Firewall Rules

```bash
sudo ufw allow 27016/udp comment "DoD Atlanta 2"
sudo ufw allow 27016/tcp comment "DoD Atlanta 2 RCON"
```

### Step 6: Update Cron Monitoring

```bash
crontab -e
```

Add/update entry:
```
*/1 * * * * /home/dodserver/dod-27016/dodserver2 monitor >> /home/dodserver/log/monitor.log 2>&1
```

### Step 7: Start and Test

```bash
cd ~/dod-27016
./dodserver2 start
sleep 5
./dodserver2 details
```

**Verify:**
- Server IP shows <ATL_GAME_IP>:27016
- Port is 27016
- servercfgfile is dodserver.cfg
- maxplayers is 13

---

## Atlanta 3 Setup (Port 27017)

*Repeat Atlanta 2 steps with:*
- Script: `dodserver-3`
- Port: `27017`
- Client Port: `27007`
- HLTV: `27022`
- Hostname: "KTP Atlanta 3"

---

## Atlanta 4 Setup (Port 27018)

*Repeat Atlanta 2 steps with:*
- Script: `dodserver-4`
- Port: `27018`
- Client Port: `27008`
- HLTV: `27023`
- Hostname: "KTP Atlanta 4"

---

## Atlanta 5 Setup (Port 27019)

*Repeat Atlanta 2 steps with:*
- Script: `dodserver-5`
- Port: `27019`
- Client Port: `27009`
- HLTV: `27024`
- Hostname: "KTP Atlanta 5"

---

## Post-Setup Checklist (Per Server)

### System Configuration (once per VPS)
- [ ] Timezone set to `America/New_York`
- [ ] UDP buffers configured (25MB)
- [ ] Swap configured (2GB)
- [ ] UFW rules added
- [ ] Process priority: `dodserver - nice -5` in `/etc/security/limits.conf`
- [ ] Process priority: `nice="-5"` in `common.cfg`

### Per-Instance Configuration
- [ ] Server starts successfully
- [ ] Can connect via game client
- [ ] Logs sending to HLStatsX (`logaddress_add <DATA_SERVER_IP>:27500`)
- [ ] HLTV recording configured (`hltv_recorder.ini`)
- [ ] KTP plugins loaded (check `ktpamx plugins` in console)
- [ ] Discord integration working
- [ ] Monitor cron job added

---

## Cloning a Full Server (New VPS)

When setting up a new game server cluster from scratch, clone from an existing server rather than doing a fresh LinuxGSM install. This ensures the KTP stack is properly configured.

### Critical: KTP Stack Files

Stock LinuxGSM installs don't have the KTP stack. You must clone from an existing KTP server:

```
serverfiles/
├── engine_i486.so        # KTP ReHLDS (replaces stock engine)
├── libsteam_api.so       # MUST be KTP version (76KB), NOT stock (375KB)!
├── dod/addons/ktpamx/    # Complete KTPAMXX installation
└── rehlds/extensions.ini # Extension loader config
```

**CRITICAL BUG:** If servers crash with `undefined symbol: SteamGameServer_Init`, you have the wrong `libsteam_api.so`. The KTP version is 76KB; the stock version is 375KB. Copy the correct one from a working KTP server.

### Step-by-Step Clone Process

```bash
# 1. On SOURCE server (e.g., Atlanta), create tarball
ssh dodserver@<ATL_GAME_IP>
cd ~ && tar -czvf dod-full.tar.gz dod-27015/

# 2. Set up SSH key for direct transfer (one-time)
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
ssh-copy-id dodserver@<DEST_IP>

# 3. Transfer to destination
scp dod-full.tar.gz dodserver@<DEST_IP>:~/

# 4. On DESTINATION server, extract and clone
ssh dodserver@<DEST_IP>
tar -xzf dod-full.tar.gz

# 5. Create copies for each port
for port in 27016 27017 27018 27019; do
  cp -r dod-27015 dod-$port
done

# 6. Rename executables per instance
mv ~/dod-27016/dodserver ~/dod-27016/dodserver2
mv ~/dod-27017/dodserver ~/dod-27017/dodserver3
mv ~/dod-27018/dodserver ~/dod-27018/dodserver4
mv ~/dod-27019/dodserver ~/dod-27019/dodserver5

# 7. Configure instance ports (CRITICAL - configs go in dodserver/ folder!)
for port in 27015 27016 27017 27018 27019; do
  n=$((port - 27014))
  clientport=$((port - 10))
  cat > ~/dod-$port/lgsm/config-lgsm/dodserver/dodserver$n.cfg << EOF
##################################
####### Instance Settings ########
##################################
port="$port"
clientport="$clientport"
ip="<SERVER_IP>"
startparameters="-game dod -strictportbind +ip \${ip} -port \${port} +clientport \${clientport} +map \${defaultmap} +servercfgfile \${servercfg} -maxplayers 13 -pingboost 2"
servercfg="dodserver.cfg"
EOF
done

# 8. Update hostnames
for port in 27015 27016 27017 27018 27019; do
  n=$((port - 27014))
  echo "hostname \"KTP - <CITY> $n\"" > ~/dod-$port/serverfiles/dod/configs/servernamedefault.cfg
done

# 9. Disable HLTV if not configured
for port in 27015 27016 27017 27018 27019; do
  sed -i 's/hltv_enabled = 1/hltv_enabled = 0/' ~/dod-$port/serverfiles/dod/addons/ktpamx/configs/hltv_recorder.ini
done

# 10. Configure process priority (requires limits.conf setup first)
echo 'nice="-5"' >> ~/dod-27015/lgsm/config-lgsm/dodserver/common.cfg
```

---

## Clone Configs from Atlanta 1

### Files to Copy

```
serverfiles/dod/
├── server.cfg                    # Main config (update hostname!)
├── dodserver.cfg                 # Map change config
├── mapcycle.txt                  # Map rotation
├── addons/
│   └── ktpamx/
│       ├── configs/
│       │   ├── discord.ini       # Same for all servers
│       │   ├── hltv_recorder.ini # UPDATE per server!
│       │   ├── cvarchecker.ini   # Same for all
│       │   └── filechecker.ini   # Same for all
│       ├── plugins/              # Same for all
│       └── modules/              # Same for all
└── maps/                         # Same for all (or symlink)
```

### Instance-Specific Changes

| File | Change |
|------|--------|
| `server.cfg` | `hostname`, `rcon_password` (optional) |
| `hltv_recorder.ini` | HLTV port (27021/27022/27023/27024) |

---

## LinuxGSM Commands Reference

```bash
./dodserver-X start      # Start server
./dodserver-X stop       # Stop server
./dodserver-X restart    # Restart server
./dodserver-X console    # Attach to console (Ctrl+B, D to detach)
./dodserver-X details    # Show server details
./dodserver-X monitor    # Check and restart if crashed
./dodserver-X update     # Update server files
./dodserver-X backup     # Backup server
```

---

## Health Monitoring

```bash
# Memory check
free -h  # Look at "available" column

# Process uptime (detect crashes/restarts)
ps -eo pid,etime,cmd | grep hlds_linux | grep -v grep

# Load average
uptime

# UDP error monitoring (should be 0 or stable)
cat /proc/net/snmp | grep "Udp:" | tail -1 | awk '{print "RcvbufErrors:", $6}'

# All servers status
for i in 1 2 3 4 5; do echo "Atlanta $i:"; ./dodserver-$i details 2>/dev/null | grep -E "(Status|Players)"; done
```

---

## Troubleshooting

### Server won't start
```bash
./dodserver-X debug  # Start in debug mode
```

### Port already in use
```bash
ss -ulnp | grep 27016
```

### Check logs
```bash
cat ~/log/console/dodserver-2-console.log
cat ~/serverfiles/dod/logs/
```

---

## Data Server Integration

After game server setup, configure on data server (<DATA_SERVER_IP>):

1. **HLTV Config:** Create `/home/hltvserver/hlds/configs/hltv-2702X.cfg`
2. **HLTV Service:** `systemctl enable --now hltv@2702X`
3. **HLStatsX:** Add server to `hlstats_Servers` table
4. **FileDistributor:** Add to `/opt/ktp-file-distributor/servers.json`

See `KTP_DataServer_Setup.md` for data server details.
