# Deployment Targets

This repo serves two related but distinct purposes:

1. **Documentation and tooling for real production and LAN deployments** — standing up KTP game servers on bare metals or LAN event hosts, matching the configuration and optimizations of the live fleet.
2. **Local development scaffolding** — Docker-based dev stack for collaborators working on the KTP codebase, tooling, and integrations.

Both paths live in this repo. This doc clarifies which is which, so a contributor or event organizer can tell load-bearing canonical paths apart from dev-time conveniences.

---

## Canonical deployment paths

**Load-bearing for real production and LAN events.** Changes to these paths should match actual fleet state — when production gets a new sysctl tweak, systemd unit, or configuration change, it gets back-ported here.

### Bare-metal / VPS provisioning

| Path | Purpose |
|------|---------|
| `provision/provision-gameserver.sh` | Base OS setup — kernel tuning, sysctl, ufw, LinuxGSM install, CPU pinning |
| `provision/install-linuxgsm.sh` | LinuxGSM instance creation for 5 game server ports |
| `provision/clone-ktp-stack.sh` | Overlay KTP binaries onto a fresh LinuxGSM install |
| `provision/deploy-chrt-service.sh` | Install the SCHED_FIFO pinning timer service |

These scripts are the authoritative recipe for new-region stand-ups and LAN event provisioning. The live fleet (Atlanta BM, Dallas, Denver, New York, Chicago) was built from these scripts.

### Configuration profiles

| Profile | Use case |
|---------|----------|
| `config/online/` | Production competitive servers — baseline for the live fleet |
| `config/lan/` | LAN event configuration — self-contained with local data server, no external service dependencies |

When running a real match or event, use one of these.

### Runtime / container image

- `runtime/Dockerfile` + `runtime/entrypoint.sh` — reproduces the production `/opt/hlds` layout in a container. SteamCMD install of HLDS app 90 + KTP artifact overlay. Same binaries, same install path, same boot flags as `provision-gameserver.sh` produces on bare metal.

Usable for:
- Validating that the build pipeline produces a bootable server
- Running a production-equivalent game server on a LAN event host that prefers containers to bare metal
- Dev-vs-prod parity testing

### Deployment tooling

- `deploy/deploy.py` — pushes built artifacts (`.so`, `.amxx`, configs) to live servers via SSH/SFTP
- Makefile `build`, `build-*`, `deploy`, `deploy-*` targets — the pipeline that produces versioned artifacts and ships them

---

## Dev convenience (not load-bearing for events)

These paths exist to make iteration on the KTP codebase and adjacent tooling easier. They are **not** authoritative deployment artifacts and should not be used as templates for real production or LAN deployments.

### Local Docker dev stack

| Path | Purpose |
|------|---------|
| `docker-compose.local.yml` | Orchestrates game servers (and optionally a data service) via Docker Compose on a single dev machine |
| `config/local/` | Stripped-down configuration for Docker-based dev iteration (`sv_lan 1`, short timelimit, `changeme` secrets) |
| `Makefile` `local-*` targets | Convenience wrappers around `docker-compose.local.yml` |

For a real LAN event use `config/lan/` + `runtime/Dockerfile` (or bare-metal provisioning), **not** the `local/` profile.

### HUD Observer integration

| Path | Purpose |
|------|---------|
| `data-server/` | supervisord + MySQL + HLTV proxy stubs, packaged for the DoD-hud-observer project's dev environment |
| `config/local/config.yaml` | HUD Observer backend config for the local Docker stack |
| `test-env/data/hltv-*.cfg` | HLTV proxy configs for the data-server container |

This stack is tied to the sibling `DoD-hud-observer` repo. It activates only with `docker-compose --profile full` (`make local-up-full`) and requires `DoD-hud-observer` cloned alongside `KTPInfrastructure`. It's dev-time plumbing for HUD Observer work, not a LAN deployment path.

---

## Quick decision guide

| Use case | Path to follow |
|----------|----------------|
| New bare-metal region (adding a location to the fleet) | `provision/*` scripts in order + `config/online/` |
| LAN event on a bare-metal host | `provision/*` + `config/lan/` |
| LAN event on a Docker host | `runtime/Dockerfile` + `config/lan/` |
| Dev iteration on KTP code (single machine) | `make local-up` |
| Dev iteration including HUD Observer | `make local-up-full` (needs sibling `DoD-hud-observer`) |
| Push new binaries to the live fleet | `make build` + `deploy/deploy.py` |

---

## When in doubt

If you are preparing for a real event or touching the live fleet and the path you are considering lives under `config/local/`, `data-server/`, or `docker-compose.local.yml`, **you are looking at the wrong file**. Use the canonical paths instead.

If you are adding a new optimization to the live fleet, capture it in `provision/` and/or `config/online/` so a fresh provisioning reproduces the current state. Silent drift between the fleet and this repo is the single biggest risk to the LAN-reproducibility goal.
