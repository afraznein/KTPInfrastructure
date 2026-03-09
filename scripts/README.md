# KTP Infrastructure Scripts

Operational scripts for KTP game servers and data server.

**Note:** Scripts with `.example` extension are templates. Copy to the actual filename and fill in your credentials before deploying.

## Scripts

### draft_day_monitor.py
Monitors CPU steal time, RAM, load, and game server stats during high-load events.

**Setup:**
```bash
cp draft_day_monitor.py.example draft_day_monitor.py
# Edit draft_day_monitor.py and fill in SERVERS and SSH_PASS
```

**Deployed to:** `/opt/ktp-monitoring/draft_day_monitor.py` (data server)

**Cron (draft day only):**
```
* 12-23 31 1 * /usr/bin/python3 /opt/ktp-monitoring/draft_day_monitor.py
```

**Logs:** `/var/log/ktp-draft-monitor/draft-monitor-YYYY-MM-DD.jsonl`

**Usage:**
```bash
python3 draft_day_monitor.py --test  # Test mode, doesn't write to log
python3 draft_day_monitor.py         # Production mode, writes JSONL
```

### nightly_match_monitor.py
Monitors CPU steal time, RAM, load, and game server stats during evening match hours (7 PM - 1 AM ET).

**Setup:**
```bash
cp nightly_match_monitor.py.example nightly_match_monitor.py
# Edit nightly_match_monitor.py and fill in SERVERS and SSH_PASS
```

**Deployed to:** `/opt/ktp-monitoring/nightly_match_monitor.py` (data server)

**Cron (daily, two entries for midnight boundary):**
```
*/10 19-23 * * * /usr/bin/python3 /opt/ktp-monitoring/nightly_match_monitor.py
*/10 0 * * * /usr/bin/python3 /opt/ktp-monitoring/nightly_match_monitor.py
```

**Logs:** `/var/log/ktp-nightly-monitor/nightly-monitor-YYYY-MM-DD.jsonl`

**Usage:**
```bash
python3 nightly_match_monitor.py --test  # Test mode, doesn't write to log
python3 nightly_match_monitor.py         # Production mode, writes JSONL
```

### deploy-chrt-service.sh
Deploys a systemd timer that applies CPU pinning + SCHED_FIFO 50 to all `hlds_linux` processes every 30 seconds. Ensures pinning is automatically reapplied after LinuxGSM restarts crashed servers.

**Run as:** root on target game server

**Usage:**
```bash
sudo ./deploy-chrt-service.sh            # Baremetal (8+ CPUs, 5 dedicated game CPUs)
sudo ./deploy-chrt-service.sh --chicago   # KVM VPS (4 vCPUs, 3 dedicated + 2 shared)
```

**Creates:**
- `/usr/local/bin/ktp-apply-chrt.sh` — Pinning script
- `/etc/systemd/system/ktp-chrt.service` — Oneshot service
- `/etc/systemd/system/ktp-chrt.timer` — 30-second timer (starts 60s after boot)

**Verify:**
```bash
journalctl -t ktp-chrt -f
systemctl list-timers | grep ktp-chrt
```

### profiling-report.py
Collects and analyzes frame profiling data from all KTP game servers. Parses `[KTP_PROFILE]`, `[KTP_SPIKE]`, `[KTP_SPIKE_READ]`, and `[KTP_PARSEMOVE]` log lines and generates a performance report.

**Requirements:** `pip install paramiko`

**Usage:**
```bash
python profiling-report.py                  # All servers, latest logs
python profiling-report.py --server atlanta  # Single server
python profiling-report.py --port 27015      # Single port across all servers
python profiling-report.py --logs 3          # Last 3 log files per port (default)
python profiling-report.py --spikes-only     # Only show spike data
```

### ktp-scheduled-restart.sh
Scheduled restart script for game servers with Discord notification.

**Setup:**
```bash
cp ktp-scheduled-restart.sh.example ktp-scheduled-restart.sh
# Edit ktp-scheduled-restart.sh and fill in Discord credentials and server IPs
```

**Deployed to:** `/home/dodserver/ktp-scheduled-restart.sh` (game servers)

**Cron:**
```
0 3 * * * /home/dodserver/ktp-scheduled-restart.sh >> /home/dodserver/log/scheduled-restart.log 2>&1
```

### ktp-organize-hltv-demos.sh
Organizes HLTV demo files into hostname/matchtype directories.

**Setup:**
```bash
cp ktp-organize-hltv-demos.sh.example ktp-organize-hltv-demos.sh
```

**Deployed to:** `/usr/local/bin/ktp-organize-hltv-demos.sh` (data server)

**Cron:**
```
0 4 * * * /usr/local/bin/ktp-organize-hltv-demos.sh
```

### hltv-api.py
HTTP API for sending commands to HLTV instances via FIFO pipes. Also supports restarting individual HLTV instances.

**Setup:**
```bash
cp hltv-api.py.example hltv-api.py
# Edit hltv-api.py and fill in AUTH_KEY
```

**Deployed to:** `/home/hltvserver/hltv-api.py` (data server)

**Service:** `/etc/systemd/system/hltv-api.service`

**Endpoints:**
- `POST /hltv/<port>/command` - Send command to HLTV via FIFO pipe
- `POST /hltv/<port>/restart` - Restart specific HLTV instance
- `GET /health` - Health check

### hltv-restart-all.sh
Scheduled restart script for all HLTV instances with Discord notification.

**Note:** This script reads credentials from `/etc/ktp/discord-relay.conf` on the data server.

**Deployed to:** `/usr/local/bin/hltv-restart-all.sh` (data server)

**Cron:**
```
0 3,11 * * * /usr/local/bin/hltv-restart-all.sh >> /var/log/hltv-restart.log 2>&1
```

### ktp-backup.sh
Backs up MySQL database and key configuration files.

**Setup:**
```bash
cp ktp-backup.sh.example ktp-backup.sh
# Edit ktp-backup.sh and fill in MYSQL_PASS
```

**Deployed to:** `/opt/ktp-backup.sh` (data server)

**Cron:**
```
0 3 * * 0 /opt/ktp-backup.sh >> /var/log/ktp-backup.log 2>&1
```

### ktp-log-rotation.sh
Compresses old logs and deletes archives older than a year.

**Deployed to:** `/home/dodserver/ktp-log-rotation.sh` (game servers)

**Cron:**
```
0 4 * * 0 /home/dodserver/ktp-log-rotation.sh >> /home/dodserver/log/log-rotation.log 2>&1
```

### package-dod-base.sh
Creates a tarball of base DoD game files for deployment to new servers.

**Usage:**
```bash
./package-dod-base.sh [source_path] [output_path]
```

## Deployment Locations

| Script | Server | Path |
|--------|--------|------|
| draft_day_monitor.py | Data Server | /opt/ktp-monitoring/ |
| nightly_match_monitor.py | Data Server | /opt/ktp-monitoring/ |
| ktp-apply-chrt.sh | Game Servers | /usr/local/bin/ (via deploy-chrt-service.sh) |
| ktp-scheduled-restart.sh | Game Servers | /home/dodserver/ |
| ktp-organize-hltv-demos.sh | Data Server | /usr/local/bin/ |
| hltv-api.py | Data Server | /home/hltvserver/ |
| hltv-restart-all.sh | Data Server | /usr/local/bin/ |
| ktp-backup.sh | Data Server | /opt/ |
| ktp-log-rotation.sh | Game Servers | /home/dodserver/ |
