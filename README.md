# KTP Infrastructure

**Version 1.0.0** - Server infrastructure, deployment automation, and operational documentation for KTP Day of Defeat competitive servers.

---

## Overview

KTP runs a multi-server infrastructure for competitive Day of Defeat matches:

| Server Type | Purpose | Ports |
|-------------|---------|-------|
| Game Cluster 1 | 5 DoD game servers | 27015-27019 |
| Game Cluster 2 | 5 DoD game servers | 27015-27019 |
| Data Server | HLTV, MySQL, HLStatsX, FastDL | 27020-27029 |

Configure your server IPs in `deploy/config.yaml` (see Initial Setup).

---

## Quick Start

### Initial Setup

Before deploying, configure your credentials:

```bash
cd KTPInfrastructure

# 1. Copy example configs and fill in your credentials
cp deploy/config.yaml.example deploy/config.yaml
cp deploy/.env.example deploy/.env  # Optional: for environment variables

# 2. Edit deploy/config.yaml with your server IPs and passwords
# Or use environment variables in deploy/.env

# 3. Copy online config examples
cp config/online/discord.ini.example config/online/discord.ini
cp config/online/hltv_recorder.ini.example config/online/hltv_recorder.ini
```

**Note:** Files with credentials (`config.yaml`, `.env`, `*.ini`) are gitignored.

### Build All Components

```bash
# Build all components (outputs to artifacts/YYYYMMDD/)
make build VERSION=20260127

# Build specific component
make build-plugins VERSION=20260127
```

### Deploy to Servers

```bash
# Deploy everything to a cluster
make deploy-atlanta VERSION=20260127

# Deploy only plugins to all clusters
make deploy-plugins VERSION=20260127

# Deploy with LAN profile
python deploy/deploy.py --cluster lan-event --profile lan --version 20260127
```

### Provision New Server

```bash
# 1. Run as root on fresh Ubuntu 22.04
sudo ./provision/provision-gameserver.sh

# 2. Switch to dodserver user and install LinuxGSM
su - dodserver
./provision/install-linuxgsm.sh <SERVER_IP>

# 3. Deploy KTP stack
./provision/clone-ktp-stack.sh /path/to/artifacts/20260127
```

### Provision LAN Data Server

For LAN events, set up a local data server with HLTV, stats, and FastDL:

```bash
sudo ./provision/provision-lan-dataserver.sh
```

See [docs/LAN_SETUP.md](docs/LAN_SETUP.md) for complete LAN setup.

---

## Repository Structure

```
KTPInfrastructure/
├── README.md                    # This file
├── Makefile                     # Build/deploy convenience targets
│
├── build/                       # Docker build system
│   ├── docker-compose.yml       # Orchestrates all builds
│   ├── .env.example             # Build configuration template
│   ├── base/Dockerfile          # Ubuntu 22.04 + GCC 32-bit
│   ├── rehlds/Dockerfile        # KTPReHLDS builder
│   ├── amxx/Dockerfile          # KTPAMXX builder
│   ├── reapi/Dockerfile         # KTPReAPI builder
│   ├── curl/Dockerfile          # KTPAmxxCurl builder
│   └── plugins/Dockerfile       # Plugin compiler
│
├── deploy/                      # Deployment automation
│   ├── deploy.py                # Main deployment script
│   ├── config.yaml.example      # Server inventory template
│   ├── .env.example             # Environment variables template
│   ├── requirements.txt         # Python dependencies
│   └── templates/               # Jinja2 config templates
│
├── provision/                   # Fresh server setup
│   ├── provision-gameserver.sh  # Ubuntu 22.04 game server setup
│   ├── provision-lan-dataserver.sh  # LAN data server (HLTV, stats, FastDL)
│   ├── install-linuxgsm.sh      # LinuxGSM + DoD bootstrap
│   └── clone-ktp-stack.sh       # Deploy KTP on LinuxGSM
│
├── config/                      # Mode-specific configs (*.example files committed)
│   ├── online/                  # Production: Discord, HLStatsX
│   │   ├── *.ini.example        # Templates (copy to *.ini and configure)
│   │   └── *.cfg.example        # Server config templates
│   └── lan/                     # LAN: Local data server, no external services
│
├── scripts/                     # Operational scripts
│   ├── hltv-api.py              # HLTV HTTP API
│   ├── hltv-restart-all.sh      # Scheduled HLTV restart
│   ├── ktp-scheduled-restart.sh # Scheduled game server restart
│   ├── ktp-backup.sh            # MySQL/config backup
│   └── ...
│
├── artifacts/                   # Build output (gitignored)
│   └── {version}/
│       ├── engine/              # hlds_linux, engine_i486.so
│       ├── ktpamx/              # dlls/, modules/
│       └── plugins/             # *.amxx files
│
└── docs/
    ├── BUILDING.md              # Build system documentation
    ├── DEPLOYING.md             # Deployment guide
    ├── LAN_SETUP.md             # LAN event setup
    ├── infrastructure.md        # Complete infrastructure reference
    ├── ktp_gameserver_setup.md  # Game server setup guide
    └── ktp_dataserver_setup.md  # Data server setup guide
```

---

## Documentation

### Build & Deploy Guides
| Document | Description |
|----------|-------------|
| [BUILDING.md](docs/BUILDING.md) | Docker build system, component builds |
| [DEPLOYING.md](docs/DEPLOYING.md) | Deployment to production/test clusters |
| [LAN_SETUP.md](docs/LAN_SETUP.md) | Setting up for LAN events |

### Infrastructure Reference (Private - gitignored)
These files contain server IPs and credentials. Create your own copies:

| Document | Description |
|----------|-------------|
| `infrastructure.md` | Complete infrastructure reference |
| `ktp_gameserver_setup.md` | Manual game server setup |
| `ktp_dataserver_setup.md` | Data server setup |

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
| `hltv-api.py` | `/home/hltvserver/` | HTTP API for HLTV control |
| `hltv-restart-all.sh` | `/usr/local/bin/` | Scheduled HLTV restart |
| `ktp-backup.sh` | `/opt/` | MySQL + config backup |
| `ktp-organize-hltv-demos.sh` | `/usr/local/bin/` | Organize demos by match |

---

## Scheduled Tasks

All times are **EST (America/New_York)**.

### Game Servers (Atlanta & Dallas)

| Schedule | Script | Description |
|----------|--------|-------------|
| Every minute | LinuxGSM monitor | Auto-restart crashed servers |
| Daily 3:00 AM | `ktp-scheduled-restart.sh` | Nightly restart + Discord |
| Sunday 4:00 AM | `ktp-log-rotation.sh` | Prune logs > 120 days |

### Data Server

| Schedule | Script | Description |
|----------|--------|-------------|
| Daily 3:00 AM & 11:00 AM | `hltv-restart-all.sh` | HLTV restart + Discord |
| Sunday 3:00 AM | `ktp-backup.sh` | MySQL + config backup |
| Daily 4:00 AM | `ktp-organize-hltv-demos.sh` | Organize HLTV demos |

---

## KTP Stack

Game servers run the custom KTP stack (no Metamod required):

```
serverfiles/
├── hlds_linux               # KTP-ReHLDS executable
├── engine_i486.so           # KTP-ReHLDS engine
├── libsteam_api.so          # KTP Steam API (76KB - NOT stock!)
├── rehlds/extensions.ini    # Extension loader config
└── dod/addons/ktpamx/       # KTPAMXX installation
    ├── dlls/                # ktpamx_i386.so
    ├── modules/             # dodx, reapi, curl modules
    ├── plugins/             # KTPMatchHandler.amxx, etc.
    └── configs/             # Plugin configurations
```

---

## Related Projects

| Project | Description |
|---------|-------------|
| [KTPReHLDS](../KTPReHLDS) | Custom ReHLDS (game engine) |
| [KTPAMXX](../KTPAMXX) | Custom AMX Mod X fork (scripting platform) |
| [KTPReAPI](../KTPReAPI) | ReAPI fork for extension mode |
| [KTPAmxxCurl](../KTPAmxxCurl) | Non-blocking HTTP module |
| [KTPMatchHandler](../KTPMatchHandler) | Competitive match management |
| [KTPHLStatsX](../KTPHLStatsX) | Match-based stats tracking |
| [Discord Relay](../Discord%20Relay) | Cloud Run webhook proxy |

---

## License

MIT License - See [LICENSE](LICENSE) file for details.

---

## Author

**Nein_**
- GitHub: [@afraznein](https://github.com/afraznein)
- Project: KTP Competitive Infrastructure
