# KTP Configuration Profiles

This directory contains configuration presets for different deployment modes.

## Profiles

### `online/` - Production Mode
Full-featured configuration with all external services enabled:
- Discord integration for match notifications
- HLStatsX logging to production data server
- HLTV API for automatic demo recording

### `lan/` - LAN Event Mode
Self-contained configuration for LAN events with a local data server:
- Discord disabled (no internet required)
- HLStatsX points to LOCAL data server
- HLTV API points to LOCAL data server
- FastDL points to LOCAL data server

**Important:** LAN mode requires setting up a local data server first.
See [LAN_SETUP.md](../docs/LAN_SETUP.md) for complete instructions.

## Configuration Files

| File | Purpose |
|------|---------|
| `discord.ini` | Discord Relay integration settings |
| `hltv_recorder.ini` | HLTV API recording configuration |
| `modules.ini` | KTPAMXX module load order |
| `plugins.ini` | KTPAMXX plugin load order |
| `dodserver.cfg.example` | (LAN only) Server config template with FastDL/HLStatsX |

## Usage

### With deploy.py

```bash
# Deploy with online profile (default)
python deploy/deploy.py --cluster atlanta --version 20260127 --with-configs

# Deploy with LAN profile
python deploy/deploy.py --cluster lan-event --version 20260127 --profile lan --with-configs
```

### Manual Deployment

Copy config files to each server instance:

```bash
scp config/online/*.ini dodserver@server:~/dod-27015/serverfiles/dod/addons/ktpamx/configs/
```

## Customization

These configs are templates. After deployment, you need to fill in:

1. **discord.ini**
   - `relay_url` - Your Cloud Run Discord Relay URL
   - `auth_secret` - Shared authentication secret
   - `match_channel` - Discord channel ID for match notifications

2. **hltv_recorder.ini**
   - `hltv_api_key` - API authentication key

## LAN Event Setup

For a LAN event, you need to:

1. **Set up a local data server** with HLTV, HLStatsX, and FastDL
   - Run `provision/provision-lan-dataserver.sh` on a dedicated machine

2. **Configure game servers** to point to the local data server
   - Edit `lan/hltv_recorder.ini` with your data server IP
   - Edit `lan/dodserver.cfg.example` with your data server IP

3. **Deploy configs** to all game server instances

See [docs/LAN_SETUP.md](../docs/LAN_SETUP.md) for the complete walkthrough.
