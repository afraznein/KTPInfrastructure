# KTP Build System

This document describes how to build all KTP components using the Docker-based build system.

## Prerequisites

- **Docker** (20.10+) with Docker Compose
- **Windows**: Docker Desktop with WSL2 backend
- **Linux**: Docker Engine + Docker Compose plugin

## Quick Start

```bash
cd KTPInfrastructure

# Build all components
make build

# Build specific version
make build VERSION=20260127
```

## Architecture

The build system uses Docker containers to ensure consistent, reproducible builds:

```
┌─────────────────────────────────────────────────────────────┐
│                     docker-compose.yml                       │
├──────────────┬──────────────┬──────────────┬───────────────┤
│  ktp-rehlds  │   ktp-amxx   │  ktp-reapi   │   ktp-curl    │
│   (CMake)    │  (AMBuild)   │   (CMake)    │   (Premake)   │
├──────────────┴──────────────┴──────────────┴───────────────┤
│                       ktp-plugins                           │
│                    (uses amxxpc from ktp-amxx)              │
├─────────────────────────────────────────────────────────────┤
│                         ktp-base                            │
│              (Ubuntu 22.04 + GCC 32-bit)                   │
└─────────────────────────────────────────────────────────────┘
```

### Base Image

All builds use a shared base image (`ktp-base`) containing:
- Ubuntu 22.04 LTS
- GCC/G++ with 32-bit multilib support
- CMake
- Python 3 + pip
- AMBuild (for KTPAMXX)

### Build Order

Components have dependencies that determine build order:

1. **ktp-base** - Base image (no dependencies)
2. **ktp-rehlds** - Game engine (depends on: base)
3. **ktp-amxx** - Scripting platform (depends on: base, KTPhlsdk)
4. **ktp-reapi** - Engine bridge (depends on: base)
5. **ktp-curl** - HTTP module (depends on: base)
6. **ktp-plugins** - All plugins (depends on: amxx for compiler)

## Build Commands

### Full Build

Build all components:

```bash
make build VERSION=20260127
```

Output:
```
artifacts/20260127/
├── engine/
│   ├── hlds_linux
│   └── engine_i486.so
├── ktpamx/
│   ├── dlls/
│   │   └── ktpamx_i386.so
│   ├── modules/
│   │   ├── dodx_ktp_i386.so
│   │   ├── fun_ktp_i386.so
│   │   ├── engine_ktp_i386.so
│   │   ├── fakemeta_ktp_i386.so
│   │   ├── reapi_ktp_i386.so
│   │   └── amxxcurl_ktp_i386.so
│   └── scripting/
│       ├── amxxpc
│       ├── amxxpc32.so
│       └── include/
└── plugins/
    ├── KTPMatchHandler.amxx
    ├── KTPHLTVRecorder.amxx
    ├── ktp_cvar.amxx
    ├── ktp_file.amxx
    ├── KTPAdminAudit.amxx
    ├── KTPGrenadeLoadout.amxx
    ├── KTPGrenadeDamage.amxx
    └── KTPPracticeMode.amxx
```

### Individual Components

```bash
# Build only the game engine
make build-engine VERSION=20260127

# Build only KTPAMXX (includes modules and compiler)
make build-amxx VERSION=20260127

# Build only plugins (requires amxx for compiler)
make build-plugins VERSION=20260127

# Build ReAPI module
make build-reapi VERSION=20260127

# Build Curl module
make build-curl VERSION=20260127
```

### Using Docker Compose Directly

```bash
cd build

# Build base image
docker-compose build ktp-base

# Build specific component
docker-compose build ktp-rehlds

# Build and extract artifacts
docker-compose up ktp-rehlds
```

## Configuration

### Environment Variables

Create `build/.env` from the template:

```bash
cp build/.env.example build/.env
```

Variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `VERSION` | `YYYYMMDD` | Version tag for artifacts |
| `KTP_PROJECT_ROOT` | Parent directory | Path to KTP projects |
| `BUILD_JOBS` | `$(nproc)` | Parallel build jobs |
| `ARTIFACTS_DIR` | `./artifacts` | Output directory |

### Customizing Builds

Each component's Dockerfile can be modified to:
- Add build flags
- Change optimization levels
- Include additional sources

Example: Enable debug symbols in ReHLDS:

```dockerfile
# build/rehlds/Dockerfile
RUN bash build.sh -j=$(nproc) -DCMAKE_BUILD_TYPE=Debug
```

## Component Details

### KTPReHLDS (Game Engine)

**Build System**: CMake

```bash
make build-engine
```

**Output**:
- `hlds_linux` - Server executable
- `engine_i486.so` - Engine shared library

**Key Build Options**:
- `-j` - Parallel jobs
- `-DCMAKE_BUILD_TYPE=Release` - Optimization level

### KTPAMXX (Scripting Platform)

**Build System**: AMBuild (Python-based)

```bash
make build-amxx
```

**Output**:
- `ktpamx_i386.so` - Main AMXX binary
- `dodx_ktp_i386.so` - DoD stats module
- `fun_ktp_i386.so`, `engine_ktp_i386.so`, `fakemeta_ktp_i386.so` - Core modules
- `amxxpc` - Plugin compiler

**Key Build Options**:
- `--enable-optimize` - Enable optimizations
- `--no-mysql` - Skip MySQL (not used)
- `--no-plugins` - Skip plugin compilation

### KTPReAPI (Engine Bridge)

**Build System**: CMake

```bash
make build-reapi
```

**Output**:
- `reapi_ktp_i386.so` - ReAPI module

### KTPAmxxCurl (HTTP Module)

**Build System**: Premake-generated Makefiles

```bash
make build-curl
```

**Output**:
- `amxxcurl_ktp_i386.so` - Curl module

**Note**: Requires libcurl 32-bit development files.

### Plugins

**Build System**: AMXX compiler (amxxpc)

```bash
make build-plugins
```

Compiles all `.sma` files from:
- KTPMatchHandler
- KTPHLTVRecorder
- KTPCvarChecker
- KTPFileChecker
- KTPAdminAudit
- KTPGrenades
- KTPPracticeMode

## Troubleshooting

### Docker Permission Issues (Linux)

```bash
sudo usermod -aG docker $USER
newgrp docker
```

### "No space left on device"

Clean up Docker resources:

```bash
docker system prune -a
```

### Build Fails with Missing 32-bit Libraries

Ensure the base image includes all required i386 packages. Check `build/base/Dockerfile`.

### AMBuild Not Found

The build system creates a Python virtual environment for AMBuild. Ensure the KTPAMXX source includes `support/ambuild/`.

## Cleaning Up

```bash
# Remove artifacts
make clean

# Remove Docker images
make clean-images

# Full cleanup (artifacts + images)
make clean-images
```

## CI/CD Integration

Example GitHub Actions workflow:

```yaml
name: Build KTP

on: [push, pull_request]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
        with:
          submodules: recursive

      - name: Build all components
        run: |
          cd KTPInfrastructure
          make build VERSION=${{ github.sha }}

      - name: Upload artifacts
        uses: actions/upload-artifact@v3
        with:
          name: ktp-${{ github.sha }}
          path: KTPInfrastructure/artifacts/
```
