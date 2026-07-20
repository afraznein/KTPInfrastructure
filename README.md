# KTP Infrastructure

Server infrastructure, deployment automation, and operational documentation for KTP Day of Defeat competitive servers. *(Current version: see [CHANGELOG.md](CHANGELOG.md) — this header previously pinned a version string that drifted.)*

---

## Overview

KTP runs a multi-server infrastructure for competitive Day of Defeat matches — 24 game instances across five hosts plus a shared data server:

| Server | Type | Ports | Location |
|--------|------|-------|----------|
| Atlanta | Baremetal, 5 game servers | 27015-27019 | Atlanta, GA |
| Dallas | Baremetal, 5 game servers | 27015-27019 | Dallas, TX |
| Denver | Baremetal, 5 game servers | 27015-27019 | Denver, CO |
| New York | Baremetal, 5 game servers | 27015-27019 | New York, NY |
| Chicago | KVM VPS, 4 game servers | 27015-27018 | Chicago, IL |
| Data Server | 24 HLTV proxies, MySQL, HLStatsX, FastDL | 27020-27043 | Atlanta, GA |

Chicago runs four instances by design — its 4 dedicated vCPUs measured best with a 1:1 instance-to-core layout, and the fifth instance was removed in July 2026.

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
python deploy/deploy.py --cluster <lan-box> --profile lan --version 20260127
```

### Provision New Server

```bash
# 1. Run as root on fresh Ubuntu 22.04
sudo ./provision/provision-gameserver.sh

# 2. Switch to dodserver user and install LinuxGSM
su - dodserver
./provision/install-linuxgsm.sh <SERVER_IP>

# 3. Deploy KTP stack
#    The runnable script is gitignored (it carries credentials), so a fresh
#    clone starts from the tracked example:
cp provision/clone-ktp-stack.sh.example provision/clone-ktp-stack.sh
# Edit it to fill in credentials, then:
./provision/clone-ktp-stack.sh /path/to/artifacts/20260127
```

### Provision a LAN Box

For LAN events the primary path is the single-config orchestrator, which
provisions an all-in-one box (game servers + HLTV + stats + FastDL) in one run:

```bash
cd provision
cp lan-deploy.conf.example lan-deploy.conf   # set LAN_IP, ARTIFACTS_PATH, LIBSTEAM_API_PATH
./lan-deploy.sh
```

See [provision/LAN-DEPLOY.md](provision/LAN-DEPLOY.md) for the automated install,
and [docs/LAN_SETUP.md](docs/LAN_SETUP.md) for architecture, the day-of runbook,
and TeamSpeak/HLTV/stats setup. (TeamSpeak is a manual post-install step.)

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
│   └── clone-ktp-stack.sh.example  # Deploy KTP on LinuxGSM (copy → .sh, add creds)
│
├── config/                      # Mode-specific configs (*.example files committed)
│   ├── online/                  # Production: Discord, HLStatsX
│   │   ├── *.ini.example        # Templates (copy to *.ini and configure)
│   │   └── *.cfg.example        # Server config templates
│   └── lan/                     # LAN: Local data server, no external services
│
├── scripts/                     # Operational scripts
│   │                            # Credential-bearing ones ship as *.example only
│   │                            # — copy to the real name and fill in secrets.
│   ├── hltv-api.py.example      # HLTV HTTP API
│   ├── hltv-restart-all.sh      # Scheduled HLTV restart (shipped as-is)
│   ├── ktp-scheduled-restart.sh.example # Scheduled game server restart
│   ├── ktp-backup.sh.example    # MySQL/config backup
│   ├── ktp-log-rotation.sh      # Log rotation (shipped as-is)
│   └── ...
│
├── monitoring/                  # Monitoring daemons + alerting
│   ├── ktp-server-monitor.py    # RCON stats poll + Discord alerting (data-server cron)
│   ├── crashreporter/           # gdb-wrapped core-dump → #ktp-crashes embed (per game host)
│   ├── fleet-health/            # Per-host process-count heartbeat alerter
│   └── fps_baselines/           # Fleet FPS snapshots for A/B comparisons
│
├── tests/                       # Test infrastructure
│   ├── smoke/                   # Tier-1 smoke tests (CI)
│   └── integration/             # Tier-2 integration suite (self-hosted runner
│                                #   boots a real hlds_linux with the fleet stack)
│
├── sites/                       # Web properties
│   ├── netcode/                 # Public netcode/config guide
│   ├── lan-web/                 # LAN event web app
│   └── wsdod-lan-2026/          # WSDoD LAN 2026 site
│
├── artifacts/                   # Build output (gitignored)
│   └── {version}/
│       ├── engine/              # hlds_linux, engine_i486.so
│       ├── ktpamx/              # dlls/, modules/
│       └── plugins/             # *.amxx files
│
├── docs/
│   ├── BUILDING.md              # Build system documentation
│   ├── DEPLOYING.md             # Deployment guide
│   ├── LAN_SETUP.md             # LAN event setup
│   ├── netcode/                 # Netcode research + player config guides
│   └── ...                      # See Documentation below
│
└── (repo root, gitignored — hold IPs/credentials, not shipped)
    ├── infrastructure.md        # Complete infrastructure reference
    ├── ktp_gameserver_setup.md  # Game server setup guide
    └── ktp_dataserver_setup.md  # Data server setup guide
```

---

## Documentation

### Build & Deploy Guides
| Document | Description |
|----------|-------------|
| [DEPLOYMENT_TARGETS.md](docs/DEPLOYMENT_TARGETS.md) | **Start here** — distinguishes canonical production/LAN paths from dev conveniences |
| [BUILDING.md](docs/BUILDING.md) | Docker build system, component builds |
| [DEPLOYING.md](docs/DEPLOYING.md) | Deployment to production/test clusters |
| [provision/LAN-DEPLOY.md](provision/LAN-DEPLOY.md) | **LAN install** — automated all-in-one orchestrator (`lan-deploy.sh`) |
| [LAN_SETUP.md](docs/LAN_SETUP.md) | LAN operations — architecture, day-of runbook, TeamSpeak/HLTV/stats |

### Stack Reference
| Document | Description |
|----------|-------------|
| [TECHNICAL_GUIDE.md](docs/TECHNICAL_GUIDE.md) | Full-stack architecture and component reference |
| [DEVELOPMENT_HISTORY.md](docs/DEVELOPMENT_HISTORY.md) | Month-by-month development timeline + ADRs |
| [docs/netcode/](docs/netcode/) | Netcode research and player config guidance |

### Infrastructure Reference (Private - gitignored)
These files contain server IPs and credentials. Create your own copies:

| Document | Description |
|----------|-------------|
| `infrastructure.md` | Complete infrastructure reference |
| `ktp_gameserver_setup.md` | Manual game server setup |
| `ktp_dataserver_setup.md` | Data server setup |

---

## Scripts

Scripts marked **(example)** carry credentials and are gitignored — the repo ships
only `<name>.example`. Copy it to the real filename and fill in secrets before
deploying. The rest ship ready to run.

### Game Server Scripts

| Script | Ships as | Deploy To | Description |
|--------|----------|-----------|-------------|
| `ktp-scheduled-restart.sh` | **(example)** | `~/` on game servers | Nightly restart with Discord notification |
| `ktp-log-rotation.sh` | as-is | `~/` on game servers | Compress logs >120 days, delete >365 days |

### Data Server Scripts

| Script | Ships as | Deploy To | Description |
|--------|----------|-----------|-------------|
| `hltv-api.py` | **(example)** | `/home/hltvserver/` | HTTP API for HLTV control |
| `hltv-restart-all.sh` | as-is | `/usr/local/bin/` | Scheduled HLTV restart |
| `ktp-backup.sh` | **(example)** | `/opt/` | MySQL + config backup |
| `ktp-organize-hltv-demos.sh` | **(example)** | `/usr/local/bin/` | Organize demos by match |

---

## Scheduled Tasks

All times are **ET (America/New_York)**.

### Game Servers (all five hosts)

| Schedule | Script | Description |
|----------|--------|-------------|
| Every minute | LinuxGSM monitor | Auto-restart crashed servers |
| Every minute | `ktp-fleet-health.sh` | Process-count heartbeat → Discord on degrade/recover |
| Daily 3:00 AM | `ktp-scheduled-restart.sh` | Nightly restart + staged `.new` binary swap + Discord |
| Sunday 4:00 AM | `ktp-log-rotation.sh` | Prune logs > 120 days |

### Data Server

| Schedule | Script | Description |
|----------|--------|-------------|
| Daily 3:00 AM & 11:00 AM | `hltv-restart-all.sh` | HLTV restart + per-instance post-restart verify + Discord |
| Sunday 3:00 AM | `ktp-backup.sh` | MySQL + config backup |
| Every 30 min | HLTV demo cleanup | Sweep raw `auto_*.dem` churn (always-on recording) |
| Continuous | `hltv-demo-renamer` | Rename auto-recorded demos to canonical match names |
| Every 5 min | Telemetry aggregation | Engine profiler/spike lines → MySQL |
| Daily | `ktp-perf-rollup` | FPS + spike digests vs baselines → Discord |
| Every 6 h | Tier-2 heartbeat + stack-drift check | Test-runner liveness + fleet-parity tripwire |
| Mon 5:00 AM | Fleet drift audit | Live state vs declarative expected-state files |

---

## KTP Stack

Game servers run the custom KTP stack (no Metamod required):

```
serverfiles/
├── hlds_linux               # KTP-ReHLDS executable
├── engine_i486.so           # KTP-ReHLDS engine
├── libsteam_api.so          # KTP Steam API (76KB - NOT stock!)
├── dod/addons/extensions.ini # Extension loader config (NOT rehlds/ — the engine only reads it from the game dir)
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
