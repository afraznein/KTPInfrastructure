# KTP crashreporter

Watches `/tmp/core.*` on each game host. When a new core appears, runs `gdb -batch -ex bt`, posts an embed to Discord `#ktp-crashes`, and saves a full backtrace + state sidecar next to the core for human triage.

**Pre-condition:** `kernel.core_pattern = /tmp/core.%e.%p.%t` (set fleet-wide 2026-04-22; persisted in `/etc/sysctl.d/99-ktp-coredump.conf`).

## What gets posted

```
ATL3 (<host>:27017) — SIGSEGV in Mem_Free
─────────────────────────────────────────────
Binary: hlds_linux       PID: 12345        Signal: SIGSEGV (Segmentation fault)
Top frame: Mem_Free at zone.cpp:432
Backtrace (top 20):
#0  Mem_Free at zone.cpp:432
#1  HPAK_GetDataPointer at hpak.cpp:201
…
Core file: /tmp/core.hlds_linux.12345.1745683200
crashed at 2026-04-26 14:12:34 UTC · gdb -batch -ex bt
```

`@here` is included on the **first** crash per server-alias per hour. Subsequent crashes within the cooldown post the embed silently.

## Sidecar files

For every processed core, two sidecars land next to it:

| File | Contents |
|------|----------|
| `*.bt` | Full `gdb -batch` output: bt, `thread apply all bt`, `info registers`, `info proc mappings`. Use this for deep dive. |
| `*.reported` | JSON state — alias, port, signal, top frame, post status. Read by the v1.5 aggregator for MySQL trend ingestion. |

The core itself is **not** deleted — `gdb` it interactively whenever you want.

## Install

On a single game host (as root):

```bash
sudo ./install.sh                # auto-detects region from primary IP
sudo ./install.sh --region ATL   # override
```

Installs:
- `/usr/local/bin/ktp-report-core` — the daemon
- `/etc/systemd/system/ktp-crashreporter.service` — systemd unit
- `/etc/ktp/crashreporter.conf` — config (mode `0640 root:dodserver`)
- apt deps: `gdb`, `inotify-tools`, `python3-requests`

The script is idempotent — re-run anytime to update binary + service file. Config is preserved unless `--force-config` is passed.

Non-interactive install (e.g. via paramiko fan-out):

```bash
RELAY_URL=https://relay.example.run.app/api \
RELAY_SECRET=secret-here \
sudo -E ./install.sh
```

## Verify

```bash
journalctl -u ktp-crashreporter -f          # live log
systemctl status ktp-crashreporter          # is it running?
ls /tmp/core.*.reported                     # what's been processed
```

To deliberately trigger one (only on a non-prod test instance!):

```bash
sudo -u dodserver kill -SEGV "$(pgrep -f 'hlds_linux.*-port 27015' | head -1)"
```

Within ~3 seconds you should see a new `/tmp/core.hlds_linux.<pid>.<ts>` plus matching `.bt` + `.reported` sidecars, and an embed in `#ktp-crashes`.

## Friendly host aliases

Embeds use `<region><instance>` shorthand — same convention as KTPMatchHandler's `match_id` (`1772072225-ATL5`):

| Host | Region | 27015 | 27016 | 27017 | 27018 | 27019 |
|---------|--------|-------|-------|-------|-------|-------|
| `<ATL_BM_GAME_IP>` | ATL | ATL1 | ATL2 | ATL3 | ATL4 | ATL5 |
| `<DAL_GAME_IP>` | DAL | DAL1 | DAL2 | DAL3 | DAL4 | DAL5 |
| `<DEN_GAME_IP>` | DEN | DEN1 | DEN2 | DEN3 | DEN4 | DEN5 |
| `<NYC_GAME_IP>` | NY | NY1 | NY2 | NY3 | NY4 | NY5 |
| `<CHI_GAME_IP>` | CHI | CHI1 | CHI2 | CHI3 | CHI4 | — |

Chicago runs four instances — its fifth (27019) was removed 2026-07-13.

If port resolution fails (PID gone before daemon could check `/proc`, no live PID matched), the alias becomes `<REGION>?` and the embed flags it.

## Operational notes

- **Daemon is restart-safe.** The `.reported` sidecar prevents duplicate alerts after a service restart or systemd reload.
- **inotify can miss events under load.** A safety-net rescan of `/tmp/` runs every 5 minutes regardless.
- **gdb is capped at 60s** per invocation — pathologically large cores won't block the daemon.
- **No outbound MySQL.** v1 only POSTs to the Discord Relay (already firewalled-allowed from every host). MySQL trend ingestion is v1.5 via the existing aggregator pulling sidecars over SSH.
- **Cleanup is manual.** Cores accumulate in `/tmp/`. When you've finished investigating, delete the `core.*`, `*.bt`, and `*.reported` triplet together.

## v1.5 path

When ready, apply `schema.sql` on the data server and extend KTPProfileAggregator to fetch each host's `/tmp/core.*.reported` files alongside its existing `[KTP_PROFILE]` log scan. One INSERT per JSON sidecar; the `UNIQUE KEY (host_alias, pid, crashed_at)` makes it idempotent.

After v1.5, `/ops crashes [hours] [region]` becomes trivial — it's a SELECT against `ktp_telemetry_crashes`.
