# Changelog

All notable changes to KTP Infrastructure will be documented in this file.

## [1.0.0] - 2026-01-31

### Initial Release - Complete Infrastructure Automation

This release transforms KTPInfrastructure from a documentation repository into a complete infrastructure-as-code system with Docker builds, automated deployment, and LAN event support.

### Added

#### Docker Build System (`build/`)
- **docker-compose.yml** - Orchestrates all component builds
- **base/Dockerfile** - Ubuntu 22.04 + GCC 32-bit base image
- **rehlds/Dockerfile** - KTPReHLDS builder (CMake)
- **amxx/Dockerfile** - KTPAMXX builder (AMBuild)
- **reapi/Dockerfile** - KTPReAPI builder (CMake)
- **curl/Dockerfile** - KTPAmxxCurl builder (Premake)
- **plugins/Dockerfile** - Plugin compiler using amxxpc

#### Deployment Automation (`deploy/`)
- **deploy.py** - Python deployment script with Paramiko SSH
- **config.yaml.example** - Server inventory template
- **requirements.txt** - Python dependencies (paramiko, pyyaml, jinja2)
- **templates/** - Jinja2 templates for config generation
  - `discord.ini.j2` - Discord integration config
  - `hltv_recorder.ini.j2` - HLTV recorder config

#### Server Provisioning (`provision/`)
- **provision-gameserver.sh** - Ubuntu 22.04 game server setup
  - Lowlatency kernel installation
  - CPU governor set to performance
  - C-state optimizations (disable C3/C6)
  - UDP buffer tuning (25MB)
  - Firewall configuration
  - fail2ban for SSH protection
- **provision-lan-dataserver.sh** - LAN data server setup
  - MySQL with hlstatsx database
  - Nginx for FastDL
  - HLTV control infrastructure
  - Firewall rules
- **install-linuxgsm.sh** - LinuxGSM + DoD bootstrap
- **clone-ktp-stack.sh** - Deploy KTP on LinuxGSM installation

#### Configuration Profiles (`config/`)
- **online/** - Production configuration templates
  - Discord integration enabled
  - HLStatsX logging enabled
  - HLTV API recording enabled
- **lan/** - LAN event configuration
  - Discord disabled (no internet required)
  - Local data server endpoints
  - Standalone operation

#### Documentation (`docs/`)
- **BUILDING.md** - Docker build system documentation
- **DEPLOYING.md** - Deployment guide with troubleshooting
- **LAN_SETUP.md** - Complete LAN event setup guide

#### Scripts (`scripts/`)
- **README.md** - Script documentation with deployment locations
- **ensure-priority.sh** - Sets hlds_linux to nice -5
- **setup_renice_cron.py.example** - Deploy priority script via SSH
- **draft_day_monitor.py.example** - High-load event monitoring
- **nightly_match_monitor.py.example** - Evening match monitoring
- **package-dod-base.sh** - Create DoD base tarball
- **setup-denver-dataserver.sh** - Denver test cluster setup

#### Build/Deploy Automation
- **Makefile** - Convenience targets
  - `make build VERSION=YYYYMMDD` - Build all components
  - `make build-plugins` - Build only plugins
  - `make deploy-atlanta` - Deploy to Atlanta cluster
  - `make deploy-plugins` - Deploy plugins to all clusters
  - `make clean` - Remove artifacts

### Changed

- **README.md** - Complete rewrite
  - Added Quick Start guide
  - Added repository structure documentation
  - Added scheduled tasks reference
  - Added KTP Stack overview
- **ktp_gameserver_setup.md** - Major expansion
  - Added performance tuning section
  - Added UDP buffer configuration
  - Added LinuxGSM multi-instance setup
  - Added troubleshooting guides
- **scripts/ktp-scheduled-restart.sh** - Updated for new structure
- **scripts/ktp-organize-hltv-demos.sh** - Updated paths and logic
- **.gitignore** - Added 36 new patterns
  - Credential files (*.ini, config.yaml, .env)
  - Build artifacts (artifacts/)
  - Python cache (__pycache__)
  - Editor files

### Security

- All credential files are gitignored (*.ini, config.yaml, .env)
- Example files provided with placeholder values
- SSH passwords stored only in local config files

### Infrastructure

This release enables:
1. **One-command builds** - `make build` builds entire stack
2. **Automated deployment** - `make deploy-atlanta` deploys to production
3. **LAN event support** - Complete offline operation for tournaments
4. **Reproducible builds** - Docker ensures consistent build environment
5. **Performance-optimized provisioning** - Lowlatency kernel, CPU tuning

---

## [0.1.0] - 2026-01-15

### Initial Commit

- Basic documentation structure
- Original infrastructure scripts
- Manual deployment instructions
