# KTP Infrastructure

Server infrastructure, deployment scripts, and operational documentation for KTP Day of Defeat competitive servers.

---

## Overview

KTP runs a multi-server infrastructure for competitive Day of Defeat matches:

| Server | Hostname | Purpose | Ports |
|--------|----------|---------|-------|
| Atlanta Game | neinatl | 5 DoD game servers | 27015-27019 |
| Dallas Game | neindal | 5 DoD game servers | 27015-27019 |
| Data Server | neindataatl | HLTV, MySQL, HLStatsX, FastDL | 27020-27029 |

---

## Repository Structure

```
KTPInfrastructure/
├── README.md                    # This file
├── infrastructure.md            # Complete infrastructure reference
├── ktp_gameserver_setup.md      # Game server setup guide
├── ktp_dataserver_setup.md      # Data server setup guide
└── scripts/
    ├── hltv-api.py              # HLTV HTTP API
    ├── hltv-restart-all.sh      # Scheduled HLTV restart
    ├── ktp-scheduled-restart.sh # Scheduled game server restart
    ├── ktp-backup.sh            # MySQL/config backup
    ├── ktp-log-rotation.sh      # Log cleanup
    └── ktp-organize-hltv-demos.sh # Demo organization
```

---

## Scripts

### Game Server Scripts

| Script | Deploy To | Description |
|--------|-----------|-------------|
| `ktp-scheduled-restart.sh` | `~/` on game servers | Nightly restart with Discord notification |
| `ktp-log-rotation.sh` | `~/` on game servers | Prune logs older than 120 days |

### Data Server Scripts

| Script | Deploy To | Description |
|--------|-----------|-------------|
| `hltv-api.py` | `/home/hltvserver/` | HTTP API for HLTV control via FIFO pipes |
| `hltv-restart-all.sh` | `/usr/local/bin/` | Scheduled HLTV restart with Discord notification |
| `ktp-backup.sh` | `/opt/` | MySQL + config backup (28-day retention) |
| `ktp-organize-hltv-demos.sh` | `/usr/local/bin/` | Organize demos into `Cluster/Hostname/MatchType/` |

---

## Deployment

### Game Server Scripts

```bash
# Deploy to Atlanta
scp scripts/ktp-scheduled-restart.sh dodserver@<ATL_GAME_IP>:~/
scp scripts/ktp-log-rotation.sh dodserver@<ATL_GAME_IP>:~/

# Deploy to Dallas
scp scripts/ktp-scheduled-restart.sh dodserver@<DAL_GAME_IP>:~/
scp scripts/ktp-log-rotation.sh dodserver@<DAL_GAME_IP>:~/
```

### Data Server Scripts

```bash
scp scripts/hltv-api.py root@<DATA_SERVER_IP>:/home/hltvserver/
scp scripts/hltv-restart-all.sh root@<DATA_SERVER_IP>:/usr/local/bin/
scp scripts/ktp-backup.sh root@<DATA_SERVER_IP>:/opt/
scp scripts/ktp-organize-hltv-demos.sh root@<DATA_SERVER_IP>:/usr/local/bin/
```

---

## Scheduled Tasks

All times are **EST (America/New_York)**.

### Game Servers (Atlanta & Dallas)

| Schedule | Script | Description |
|----------|--------|-------------|
| Every minute | LinuxGSM monitor | Auto-restart crashed servers |
| Daily 3:00 AM | `ktp-scheduled-restart.sh` | Nightly restart + Discord notification |
| Sunday 4:00 AM | `ktp-log-rotation.sh` | Prune logs older than 120 days |

### Data Server

| Schedule | Script | Description |
|----------|--------|-------------|
| Daily 3:00 AM & 11:00 AM | `hltv-restart-all.sh` | HLTV restart + Discord (systemd timer) |
| Sunday 3:00 AM | `ktp-backup.sh` | MySQL + config backup |
| Daily 4:00 AM | `ktp-organize-hltv-demos.sh` | Organize HLTV demos |

---

## Documentation

| Document | Description |
|----------|-------------|
| [infrastructure.md](infrastructure.md) | Complete reference: scheduled tasks, deployment procedures, config locations, monitoring |
| [ktp_gameserver_setup.md](ktp_gameserver_setup.md) | Game server setup: LinuxGSM, system config, cloning servers |
| [ktp_dataserver_setup.md](ktp_dataserver_setup.md) | Data server setup: HLTV, MySQL, HLStatsX, FastDL |

---

## Quick Reference

### SSH Access

```bash
ssh dodserver@<ATL_GAME_IP>   # Atlanta game servers
ssh dodserver@<DAL_GAME_IP>   # Dallas game servers
ssh root@<DATA_SERVER_IP>     # Data server (HLTV, MySQL, etc.)
```

### Manual Server Restart

```bash
# Restart all servers on a cluster
ssh dodserver@<GAME_IP> "~/restart-all-servers.sh"

# Restart individual instance
ssh dodserver@<GAME_IP> "~/dod-27015/dodserver restart"
```

### Manual HLTV Restart

```bash
ssh root@<DATA_SERVER_IP> "systemctl start hltv-restart.service"
```

### Check Server Status

```bash
# All servers on a cluster
ssh dodserver@<GAME_IP> 'for i in 1 2 3 4 5; do echo "Server $i:"; ~/dod-2701$((i+4))/dodserver$i details 2>/dev/null | grep -E "(Status|Players)"; done'
```

---

## KTP Stack

Game servers run the custom KTP stack (no Metamod required):

```
serverfiles/
├── engine_i486.so           # KTP-ReHLDS (custom game engine)
├── libsteam_api.so          # KTP Steam API (76KB - NOT stock!)
├── rehlds/extensions.ini    # Extension loader config
└── dod/addons/ktpamx/       # KTPAMXX (AMX Mod X fork)
    ├── dlls/                # ktpamx_i386.so, reapi_ktp_i386.so
    ├── modules/             # dodx_ktp_i386.so, curl_amxx_i386.so
    ├── plugins/             # KTPMatchHandler.amxx, etc.
    └── configs/             # Plugin configurations
```

---

## Related Projects

| Project | Description |
|---------|-------------|
| [KTPAMXX](https://github.com/afraznein/KTPAMXX) | Custom AMX Mod X fork (scripting platform) |
| [KTP-ReHLDS](https://github.com/afraznein/KTP-ReHLDS) | Custom ReHLDS (game engine) |
| [KTP-ReAPI](https://github.com/afraznein/KTP-ReAPI) | ReAPI fork for extension mode |
| [KTPMatchHandler](https://github.com/afraznein/KTPMatchHandler) | Competitive match management plugin |
| [KTPHLStatsX](https://github.com/afraznein/KTPHLStatsX) | Match-based stats tracking |
| [KTPHLTVRecorder](https://github.com/afraznein/KTPHLTVRecorder) | Automatic HLTV demo recording |
| [Discord Relay](https://github.com/afraznein/Discord-Relay) | Cloud Run webhook proxy |

---

## License

MIT License - See [LICENSE](LICENSE) file for details.

---

## Author

**Nein_**
- GitHub: [@afraznein](https://github.com/afraznein)
- Project: KTP Competitive Infrastructure
