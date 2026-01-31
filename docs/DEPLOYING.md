# KTP Deployment Guide

This document describes how to deploy KTP components to production and test servers.

## Prerequisites

- Built artifacts (see [BUILDING.md](BUILDING.md))
- Python 3.8+ with pip
- SSH access to target servers

## Quick Start

```bash
# Install deployment dependencies
pip install -r deploy/requirements.txt

# Deploy everything to Atlanta
make deploy-atlanta VERSION=20260127

# Deploy only plugins to all clusters
make deploy-plugins VERSION=20260127
```

## Server Inventory

Servers are defined in `deploy/config.yaml`. Copy from `config.yaml.example` and fill in your IPs:

| Cluster | Ports | Description |
|---------|-------|-------------|
| `cluster1` | 27015-27019 | Production (5 servers) |
| `cluster2` | 27015-27019 | Production (5 servers) |
| `test` | 27015-27019 | Test cluster |

## Deployment Commands

### Using Make

```bash
# Deploy all components to all production clusters
make deploy VERSION=20260127

# Deploy to specific cluster
make deploy-atlanta VERSION=20260127
make deploy-dallas VERSION=20260127
make deploy-denver VERSION=20260127  # Test cluster

# Deploy only plugins
make deploy-plugins VERSION=20260127
make deploy-plugins-atlanta VERSION=20260127
```

### Using deploy.py Directly

```bash
# Full syntax
python deploy/deploy.py --cluster atlanta --version 20260127

# All production clusters
python deploy/deploy.py --all --version 20260127

# Specific component
python deploy/deploy.py --cluster atlanta --component plugins --version 20260127

# With config deployment
python deploy/deploy.py --cluster atlanta --version 20260127 --with-configs

# LAN profile
python deploy/deploy.py --cluster lan-event --profile lan --version 20260127

# Dry run (show what would be deployed)
python deploy/deploy.py --cluster atlanta --version 20260127 --dry-run
```

## Component Deployment

### Engine

Deploys to each server instance's `serverfiles/` directory:

| File | Destination | Permissions |
|------|-------------|-------------|
| `hlds_linux` | `serverfiles/hlds_linux` | 755 |
| `engine_i486.so` | `serverfiles/engine_i486.so` | 755 |

### KTPAMXX

Deploys to `serverfiles/dod/addons/ktpamx/`:

| File | Destination | Permissions |
|------|-------------|-------------|
| `ktpamx_i386.so` | `dlls/ktpamx_i386.so` | 755 |
| `dodx_ktp_i386.so` | `modules/dodx_ktp_i386.so` | 755 |
| `fun_ktp_i386.so` | `modules/fun_ktp_i386.so` | 755 |
| `engine_ktp_i386.so` | `modules/engine_ktp_i386.so` | 755 |
| `fakemeta_ktp_i386.so` | `modules/fakemeta_ktp_i386.so` | 755 |
| `reapi_ktp_i386.so` | `modules/reapi_ktp_i386.so` | 755 |
| `amxxcurl_ktp_i386.so` | `modules/amxxcurl_ktp_i386.so` | 755 |

### Plugins

Deploys to `serverfiles/dod/addons/ktpamx/plugins/`:

| File | Destination |
|------|-------------|
| `KTPMatchHandler.amxx` | `plugins/KTPMatchHandler.amxx` |
| `KTPHLTVRecorder.amxx` | `plugins/KTPHLTVRecorder.amxx` |
| `ktp_cvar.amxx` | `plugins/ktp_cvar.amxx` |
| `ktp_file.amxx` | `plugins/ktp_file.amxx` |
| `KTPAdminAudit.amxx` | `plugins/KTPAdminAudit.amxx` |
| `KTPGrenadeLoadout.amxx` | `plugins/KTPGrenadeLoadout.amxx` |
| `KTPGrenadeDamage.amxx` | `plugins/KTPGrenadeDamage.amxx` |
| `KTPPracticeMode.amxx` | `plugins/KTPPracticeMode.amxx` |

## Backup System

The deployment script automatically creates backups before overwriting files:

```
~/backups/{version}/
├── engine_i486.so.27015.bak
├── engine_i486.so.27016.bak
├── ...
├── ktpamx.27015.tar.gz
├── ktpamx.27016.tar.gz
└── ...
```

To restore from backup:

```bash
# Example: Restore engine on port 27015
cp ~/backups/20260127/engine_i486.so.27015.bak ~/dod-27015/serverfiles/engine_i486.so
chmod +x ~/dod-27015/serverfiles/engine_i486.so
```

## Configuration Profiles

### Online Profile (Default)

Full-featured mode with all external services:

- Discord integration enabled
- HLStatsX logging enabled
- HLTV API recording enabled

```bash
python deploy/deploy.py --cluster atlanta --profile online --with-configs
```

### LAN Profile

Standalone mode for LAN events:

- Discord disabled
- HLStatsX disabled
- HLTV API disabled

```bash
python deploy/deploy.py --cluster lan-event --profile lan --with-configs
```

## Deployment Workflow

### Standard Update (Plugins Only)

1. Build plugins:
   ```bash
   make build-plugins VERSION=20260127
   ```

2. Deploy to test cluster:
   ```bash
   make deploy-denver VERSION=20260127
   ```

3. Verify on test cluster:
   ```bash
   ssh dodserver@denver "tail -f ~/dod-27015/log/console/*.log | grep -i ktpamx"
   ```

4. Deploy to production:
   ```bash
   make deploy-plugins VERSION=20260127
   ```

### Full Stack Update

1. Build all components:
   ```bash
   make build VERSION=20260127
   ```

2. Deploy to test cluster:
   ```bash
   python deploy/deploy.py --cluster denver --version 20260127
   ```

3. Test thoroughly:
   - Start servers
   - Run a test match
   - Verify all plugins load
   - Check Discord notifications
   - Verify HLTV recording

4. Deploy to production:
   ```bash
   python deploy/deploy.py --all --version 20260127
   ```

5. Restart servers (requires permission):
   ```bash
   ssh dodserver@<CLUSTER1_IP> "~/restart-all-servers.sh"
   ssh dodserver@<CLUSTER2_IP> "~/restart-all-servers.sh"
   ```

## Adding New Servers

### 1. Update config.yaml

```yaml
clusters:
  new-cluster:
    host: 192.168.1.100
    user: dodserver
    password: ktp
    ports: [27015, 27016, 27017, 27018, 27019]
    hostname: newcluster
    server_name_prefix: "KTP NewCluster"
    description: "New Cluster"
```

### 2. Deploy

```bash
python deploy/deploy.py --cluster new-cluster --version 20260127
```

### 3. Configure FileDistributor SSH Key (Required)

The FileDistributor service on the data server needs SSH access to deploy files (maps, plugins, configs) to the new server.

**On the data server:**

```bash
# Copy the FileDistributor SSH key to the new game server
ssh-copy-id -i /var/www/fastdl/.ssh/id_rsa.pub dodserver@<NEW_SERVER_IP>
# Enter password: ktp

# Test the connection
ssh -i /var/www/fastdl/.ssh/id_rsa dodserver@<NEW_SERVER_IP> "echo 'FileDistributor access OK'"
```

**Verify:** Distribute a test file through FileDistributor. All servers should show successful uploads.

### 4. Add to FileDistributor servers.json

Edit `/opt/ktp-file-distributor/servers.json` on the data server to add entries for the new server instances:

```json
{
  "name": "KTP - NewCluster 1",
  "host": "192.168.1.100",
  "port": 22,
  "username": "dodserver",
  "privateKeyPath": "/var/www/fastdl/.ssh/id_rsa",
  "remoteBasePath": "/home/dodserver/dod-27015/serverfiles/dod",
  "enabled": true
}
```

Repeat for each instance (ports 27015-27019).

## New Server Provisioning

When deploying to a new bare metal server, use the provisioning script to configure performance optimizations.

### Provisioning Steps

```bash
# 1. SSH to new server as root
ssh root@<NEW_SERVER_IP>

# 2. Download and run provisioning script
curl -O https://raw.githubusercontent.com/your-repo/KTPInfrastructure/main/provision/provision-gameserver.sh
chmod +x provision-gameserver.sh
sudo ./provision-gameserver.sh -y

# 3. Reboot to activate lowlatency kernel
sudo reboot

# 4. Continue with LinuxGSM and KTP stack deployment
```

### Performance Optimizations Applied by Provisioning

The provisioning script applies these optimizations automatically:

| Optimization | Value | Purpose |
|--------------|-------|---------|
| **Kernel** | lowlatency | 1000Hz tick rate, full preemption |
| **CPU Governor** | performance | No frequency scaling delays |
| **C-States** | C3/C6 disabled | No 59-80µs wake latency |
| **NMI Watchdog** | disabled | Eliminates watchdog micro-stutters |
| **UDP Buffers** | 25MB | Prevents packet drops under load |
| **tcp_low_latency** | 1 | Minor TCP latency improvement |
| **busy_poll** | 50 | Reduced network latency |
| **File Descriptors** | 65535 | Prevents "too many open files" |
| **fail2ban** | enabled | SSH brute force protection |

### Manual Performance Tuning

If you need to apply optimizations to an existing server:

```bash
# Set CPU governor to performance
for gov in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    echo performance | sudo tee $gov
done

# Disable deep C-states
for state in /sys/devices/system/cpu/cpu*/cpuidle/state{3,4}/disable; do
    echo 1 | sudo tee $state 2>/dev/null
done

# Disable NMI watchdog
sudo sysctl -w kernel.nmi_watchdog=0

# Apply network tuning
sudo sysctl -w net.ipv4.tcp_low_latency=1
sudo sysctl -w net.core.busy_poll=50
```

### Verifying Performance Settings

```bash
# Check CPU governor
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor | sort | uniq -c

# Check C-states (should show DISABLED for C3/C6)
for state in /sys/devices/system/cpu/cpu0/cpuidle/state*; do
    name=$(cat $state/name)
    disabled=$(cat $state/disable 2>/dev/null)
    [ "$disabled" = "1" ] && echo "$name: DISABLED" || echo "$name: enabled"
done

# Check sysctls
sysctl kernel.nmi_watchdog net.ipv4.tcp_low_latency net.core.busy_poll
```

## Troubleshooting

### Connection Refused

- Verify SSH access: `ssh dodserver@<host>`
- Check firewall rules on the server
- Verify the IP address in config.yaml

### Permission Denied

- Verify password in config.yaml
- Check that the user has write access to server directories

### File Not Found

- Ensure artifacts exist: `ls artifacts/20260127/`
- Build first: `make build VERSION=20260127`

### Servers Not Loading New Files

After deployment, servers need to be restarted to load new binaries:

```bash
# Individual server
ssh dodserver@host "~/dod-27015/dodserver restart"

# All servers on a cluster
ssh dodserver@host "~/restart-all-servers.sh"
```

**Note**: Restarting disconnects all players. Only restart during maintenance windows or when servers are empty.

### Verify Plugin Loading

Check console logs after restart:

```bash
ssh dodserver@host "tail -50 ~/dod-27015/log/console/*.log | grep -iE '(ktpamx|loaded|error)'"
```

Expected output:
```
[KTPAMX] Loaded plugin KTPMatchHandler.amxx
[KTPAMX] Loaded plugin ktp_cvar.amxx
...
```

### Investigating Lag Reports

When players report lag, check these in order:

**1. Server-side metrics (SSH to game server):**

```bash
# CPU steal (should be 0% on bare metal)
vmstat 1 3 | tail -1 | awk '{print "CPU Steal:", $16"%"}'

# Memory
free -h | head -2

# UDP buffer errors (should be 0)
cat /proc/net/snmp | grep "Udp:" | tail -1 | awk '{print "RcvbufErrors:", $6}'

# Load average
uptime
```

**2. Network health:**

```bash
# Packet loss to upstream
ping -c 10 8.8.8.8

# Interface errors
ip -s link show | grep -E 'errors|dropped'

# Current bandwidth usage
cat /sys/class/net/*/statistics/rx_bytes; sleep 5; cat /sys/class/net/*/statistics/rx_bytes
```

**3. If server metrics are healthy:**

The lag is likely upstream/network-related:
- Player's ISP issues
- Routing path congestion
- Datacenter peering issues (not visible from inside the server)
- Geographic distance (East Coast players to West Coast server)

**4. Netdata investigation:**

Check Netdata Cloud for historical anomalies:
- CPU spikes
- Network throughput drops
- Unusual softirq activity

Local Netdata: `http://<SERVER_IP>:19999`

**Key insight:** If ALL players experience lag simultaneously, it's likely upstream (datacenter/provider network). If only some players lag, it's routing/ISP-specific.
