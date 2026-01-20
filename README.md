# KTP Server Scripts

Infrastructure scripts for KTP Day of Defeat server operations.

## Scripts

| Script | Location | Description |
|--------|----------|-------------|
| `hltv-api.py` | Data server (`/home/hltvserver/hltv-api.py`) | HTTP API for HLTV control via FIFO pipes and instance restarts |
| `hltv-restart-all.sh` | Data server (`/usr/local/bin/`) | Scheduled restart of all HLTV instances with Discord notification |
| `ktp-scheduled-restart.sh` | Game servers (`/home/dodserver/`) | Game server scheduled restart with Discord notification |
| `ktp-backup.sh` | Data server (`/opt/`) | MySQL database and config backup |
| `ktp-log-rotation.sh` | Game servers (`/home/dodserver/`) | Log compression and cleanup |
| `ktp-organize-hltv-demos.sh` | Data server (`/home/hltvserver/`) | HLTV demo file organization |

## Server Locations

| Server | IP | Role |
|--------|-----|------|
| Atlanta (neinatl) | 74.91.112.125 | 5 game servers (27015-27019) |
| Dallas (neindal) | 74.91.114.178 | 5 game servers (27015-27019) |
| Data (neindataatl) | 74.91.112.242 | HLTV, MySQL, HLStatsX, FastDL |

## Deployment

Scripts are manually deployed to servers. Each script header contains its target location.

### Game Server Scripts
```bash
scp ktp-scheduled-restart.sh dodserver@74.91.112.125:~/
scp ktp-scheduled-restart.sh dodserver@74.91.114.178:~/
scp ktp-log-rotation.sh dodserver@74.91.112.125:~/
scp ktp-log-rotation.sh dodserver@74.91.114.178:~/
```

### Data Server Scripts
```bash
scp hltv-api.py root@74.91.112.242:/home/hltvserver/
scp hltv-restart-all.sh root@74.91.112.242:/usr/local/bin/
scp ktp-backup.sh root@74.91.112.242:/opt/
scp ktp-organize-hltv-demos.sh root@74.91.112.242:/home/hltvserver/
```

## Scheduled Tasks

### Game Servers (Cron)
```
0 3 * * * /home/dodserver/ktp-scheduled-restart.sh >> /home/dodserver/log/scheduled-restart.log 2>&1
0 4 * * 0 /home/dodserver/ktp-log-rotation.sh >> /home/dodserver/log/log-rotation.log 2>&1
```

### Data Server
- **HLTV Restart**: 3:00 AM & 11:00 AM ET daily (systemd timer)
- **Backup**: Daily via cron
- **Demo Organization**: 4:00 AM ET daily via cron
