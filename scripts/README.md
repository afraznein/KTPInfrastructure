# KTP Infrastructure Scripts

> **Coverage note (2026-07-07):** this README documents only the most-used
> scripts (~a third of `scripts/`). For anything not listed, the script's
> own header comment is the documentation — every KTP script carries one.

Operational scripts for KTP game servers and data server.

**Note:** Scripts with `.example` extension are templates. Copy to the actual filename and fill in your credentials before deploying.

### Official team-score ingestion and projection

`import_team_score_events.py` validates settled local/mounted observer
`events.jsonl` plus adjacent `metadata.json`, requires an explicit
`--source-server-root SOURCE_SERVER=ROOT`, binds the pair to its configured
source path and closed analytics context, and imports
only exact `engine-team-score-v1` rows into the append-only migration-023
ledgers. `project_team_score.py` runs the strict
post-match boundary, ordering, side-map, carryover, and conflict checks before
writing a canonical neutral-team DTO and immutable release digest.

Neither tool infers score from captures, players, KTPR, or `ktp_match_end`.
See `docs/OFFICIAL_TEAM_SCORE_TELEMETRY.md` for the migration, local commands,
quality behavior, privacy boundary, and retention integration.

## Scripts

### Bounded match accumulation and automated reports

Generate a deterministic v3 report bundle from normalized match facts:

```bash
python scripts/build_automated_match_report.py \
  --facts build/match-facts/MATCH_ID.json \
  --output-dir build/match-reports/MATCH_ID/v3
```

The bundle contains the bounded score, three-model comparison, immutable
manifest, and optional AI-review request. AI review is advisory and separate;
it cannot alter points, reliability gates, privacy, or publication state. See
`docs/ACCUMULATION_V3_BOUNDED.md` and
`docs/AUTOMATED_MATCH_REPORTS_AND_AI_CHECKPOINTS.md`.

### Match readiness, report bundle, and spatial map registry

`match_readiness.py` applies an aggregate-only `PASS`/`WARN`/`FAIL` gate to a
local `.sql` or `.sql.gz` match fixture without starting MySQL or contacting a
shared service. `build_anzio_spatial_atlas.ps1` turns one or more Anzio fixtures
into the supported heatmap/report image set. Map geometry and analytical
windows live in `config/analytics/spatial_maps/dod_anzio.json`.

For checksum-pinned multi-map handovers, `analyze_competitive_corpus.py`
restores every listed fixture into a separate ephemeral database and keeps
public aggregate/derived totals separate from private positional working data.
`build_competitive_spatial_configs.py`, `build_all_competitive_atlases.ps1`,
and `build_spatial_atlas.ps1` extend the aggregate atlas to dataset-scoped map
configs without treating those configs as reviewed scoring weights.
`build_competitive_report_site.py` produces a static, directly viewable report
site; `verify_competitive_report_site.py` checks its manifest, local links,
expected map/match coverage, and public privacy boundary before distribution.

`match_report_bundle.py` joins the canonical analytics JSON, readiness JSON,
optional shareable accumulation JSON, and optional atlas metadata into one
privacy-checked Markdown/JSON bundle. `metric_confidence.py` supplies versioned
source/sample labels. Official score input is accepted only as the paired
`objective-score-timeline.json` plus private release produced by the projector;
the bundle validates the match/map/facts digest binding and strips it before
publication. A bare sanitized score DTO is deliberately rejected.
`spatial_map_registry.py` discovers all KTP match configs
and produces the map readiness matrix; it does not infer geometry or waypoints.

`match_fixture_storage.py` measures SQL archive/transfer size and match-tagged
payload without mislabeling that value as InnoDB allocation or a human-match
average. `release_candidate_manifest.py` binds the three release repositories,
test-only dependencies, built artifacts, and migrations to exact commits and
SHA-256 values. `measure_command.py` writes elapsed/CPU/peak-RSS evidence for a
local command and preserves its exit status.

See `docs/MATCH_REPORT_READINESS.md` for commands and
`docs/MATCH_METRIC_CONTRACT_V1.md` for normative metric definitions. The first
human-match procedure is `docs/runbooks/FIRST_REAL_MATCH_ANALYTICS.md`.

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

**Swap failures:** a `.new` -> live `mv -f` that fails is logged, but never aborts the server start
that follows (leaving players on a DOWN server is a worse outcome than one running a partial wave).
Instead a swap failure forces the Discord status off green, exits the script non-zero even when every
server comes back up, and — because the failed `mv` leaves the `.new` file exactly where it was —
`ktp-verify-post-swap.sh` (below) is the durable, run-anytime way to confirm a wave fully activated.

### ktp-verify-post-swap.sh
Read-only, run on a game host any time after a nightly restart. Re-derives the same swap-glob set
`ktp-scheduled-restart.sh` uses and reports any `.new` file still sitting unswapped — the durable
signature of an incomplete activation, independent of whether you caught the restart log live.

```bash
./ktp-verify-post-swap.sh   # exit 0 = fully activated, exit 1 = leftover .new file(s) found
```

### stage-wave.py
**The standard way to push a wave to the fleet — prefer this over calling `deploy-to-fleet.py` directly.**
It wraps that script (single source of truth for the 24-instance topology and the password-from-env rule)
and adds the two gates the manual process relied on people remembering:

- **Pre-stage attribution gate** — refuses to stage if any `.new` already sits in the swap globs. That is
  the one-wave-per-nightly rule made mechanical: if a 03:00 activation produces a core, exactly one new
  variable tells you what did it. `--allow-existing-new` overrides.
- **`--expect NAME=MD5` pin** — refuses to ship a binary whose md5 isn't the one you reviewed. KTPAMXX
  bakes a per-minute build timestamp, so an accidental rebuild silently produces a *different* artifact;
  this catches it. Verify by md5, never by the console banner.

Then stages `<file>.new` to all 24 instances, mode-matches perms to the live file, re-verifies md5 24/24,
and prints the morning-after `ktp-verify-deploy.py` command (plus a runner-resync reminder for
module/engine waves). Never restarts a server.

```bash
python3 stage-wave.py --preflight-only        # is the fleet clean to stage into?
python3 stage-wave.py -f path/to/KTPMatchHandler.amxx --expect KTPMatchHandler.amxx=<md5>
```

### deploy-to-fleet.py
Raw push, no gates — `stage-wave.py` (above) is the normal entry point. Local-to-fleet artifact push as `.new` files; nightly `ktp-scheduled-restart.sh` (above) auto-swaps them in. Closes the local-build → fleet-SCP gap discovered 2026-05-20. No `.example` template needed — the SSH password is resolved from `$KTP_FLEET_SSH_PASSWORD` or `~/.ktp_fleet_ssh_password` (never hardcoded; the pre-2026-05-31 `ktp` value was leaked in this public repo and rotated — do not document credential values here).

**Features:**
- `-f <path>` repeatable for multi-artifact pushes
- Auto-routing by filename pattern: `ktpamx_i386.so` → `dlls/`, `*_ktp_i386.so` → `modules/`, `*.amxx` → `plugins/`, `engine_i486.so` / `hlds_linux` / `libsteam_api.so` → `serverfiles/`
- `--remote-path` override for non-standard targets
- `--hosts atlanta,dallas,…` or `--hosts all` filter
- `--ports 27015,27016,…` or `--ports all` filter
- `--dry-run` mode (no SCP, just prints intent)
- `--parallel N` (default 5 = one host worker per server; each (host, port) currently opens its own SSH+SFTP session)
- md5 verify post-upload; mismatch reported as failure
- Per-instance failure isolation — one host down doesn't abort others
- Summary table with OK/FAIL counts per artifact per host

**Activation behavior:** NO automatic restart. `.new` files sit on disk until next nightly 03:00 ET restart auto-swaps them in via `ktp-scheduled-restart.sh`. Intentional safety — no production restart without explicit operator permission.

**Usage:**
```bash
# Dry-run to inspect what would deploy
python3 deploy-to-fleet.py -f path/to/KTPMatchHandler.amxx --dry-run

# Single-instance smoke test before going --all
python3 deploy-to-fleet.py -f path/to/KTPMatchHandler.amxx --hosts atlanta --ports 27015

# Full fleet, multi-artifact (e.g., plugin + module rebuild)
python3 deploy-to-fleet.py \
    -f path/to/KTPMatchHandler.amxx \
    -f path/to/dodx_ktp_i386.so \
    --hosts all
```

**First live use:** always pair `--hosts <one> --ports <one>` as a smoke test before `--all`. The dry-run validates routing + arg parsing locally; the SCP + remote-md5-verify path is paramiko-shaped boilerplate but should still be confirmed on one instance before broadcasting.

### sync-runner-stack.py
**Mirrors the Tier-2 runner's stack onto a live fleet instance — the deploy-flow step that had a checklist line but no tool.**
The runner is must-match-fleet; a green suite certifying a stack production doesn't run is the worst
failure mode a test tier has, and `ktp-tier2-stack-drift.py` could only ever report it.

- **Syncs exactly what the tripwire alerts on**, imported from that module rather than restated — the
  repo already carries several hand-kept copies of the test-mode plugin list, and this is not another.
- **Never touches** KTPMatchHandler / KTPPracticeMode (`KTP_TEST_MODE` builds, where byte-equality with
  the fleet is wrong) or KTPHudObserver (rebuilt from upstream per run). Asserted, not just documented.
- **Dry run by default.** `--apply` backs each drifted file up on the runner first, then verifies md5
  after the pull and again after the push. It refuses during a live Tier-2 run, and refuses when the
  reference instance holds staged `.new` files.

Holds no IPs — hosts come from `KTP_TIER2_SSH_HOST` / `KTP_DRIFT_REF_HOST`. Full procedure and ordering:
`docs/RELEASE_CHECKLISTS.md` § Tier-2 runner re-sync.

```bash
python3 sync-runner-stack.py            # what drifted?
python3 sync-runner-stack.py --apply    # sync it
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

**Note:** It restarts the `hltv@<port>` units only. The `hltv-api` service is not
in its scope, so a change to `hltv-api.py` needs an explicit
`systemctl restart hltv-api` - waiting for the scheduled restart will not pick it up.

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

### ktp-backup-watchdog.sh
Notices a weekly backup that never ran or finished short. `ktp-backup.sh` logs and alerts on the
failures it can see; nothing watched for the run that simply did not happen.

**Deployed to:** `/usr/local/bin/ktp-backup-watchdog.sh` (data server)

**Cron:** daily 08:30 ET, after the Sunday 03:00 backup window has closed.

### ktp-scheduled-kernel-reboot.sh
Reboots the data server into a newer kernel, but only while nobody is playing -- a reboot here stops
HLTV recording, stats ingest and AC uploads. Aborts and retries the next night otherwise, and posts
the outcome either way. Disables its own timer before rebooting, so it is one-shot by construction.

**Deployed to:** `/usr/local/bin/ktp-scheduled-kernel-reboot.sh` (data server)

**Units:** [`systemd/ktp-kernel-reboot.service`](systemd/ktp-kernel-reboot.service) +
[`systemd/ktp-kernel-reboot.timer`](systemd/ktp-kernel-reboot.timer), 02:00 ET.

> 🔴 **Known defect -- the idle gate can never be satisfied, so this has never once rebooted.**
> The gate requires `frags_20m` **and** `demos_15m` to both be zero. The 24 HLTV proxies write `.dem`
> files continuously, so `find /home/hltvserver -name '*.dem' -mmin -15` is never zero while HLTV is
> running -- it counts recording, not play. The log shows a nightly abort with 42-45 demos every time,
> including nights when frags was genuinely 0.
> ➡️ **The frags check is the one that measures play; the demo check needs to measure something that
> actually goes quiet, or come out.** Fixing it arms a real unattended reboot, so it is an operator
> decision, not a cleanup.

### ktp-post-reboot-verify.sh
Companion to the above: runs once after the reboot, reports kernel version, HLTV proxy count and any
failed units, then disables itself.

**Deployed to:** `/usr/local/bin/ktp-post-reboot-verify.sh` (data server)

**Unit:** enabled by `ktp-scheduled-kernel-reboot.sh` immediately before it reboots, so it only ever
runs on a boot that script caused.

### ktp-log-rotation.sh
Compresses old logs and deletes archives older than a year.

**Deployed to:** `/home/dodserver/ktp-log-rotation.sh` (game servers)

**Cron:**
```
0 4 * * 0 /home/dodserver/ktp-log-rotation.sh >> /home/dodserver/log/log-rotation.log 2>&1
```

### hlstatsx-ingest-monitor.py
Hourly reconciliation of the HLStatsX ingest path, for the failures that produce no error. Full detail in [`README-hlstatsx-ingest-monitor.md`](README-hlstatsx-ingest-monitor.md).

**Usage:**
```bash
hlstatsx-ingest-monitor.py [--db hlstatsx] [--since 90] [--logs <dod/logs>] [--quiet]
```

Findings print with a `!!` prefix and set exit 1, which fails the systemd unit and fires the existing `ktp-systemd-alert` `OnFailure` wiring into Discord.

| Check | Catches |
|---|---|
| UDP `RcvbufErrors` delta | log lines dropped before the daemon saw them — the only evidence that exists |
| Half with no summary rows | the empty-match-id shape that lost the 2026 LAN's Grand Final half |
| Summary short of its events | aggregation stopped while ingest continued |
| Half 2 far below half 1 | partial ingest loss, which leaves plausible rows rather than a gap |
| Daemon `KTP_HEALTH` line | unresolved actions, failed writes (needs KTPHLStatsX ≥ 0.3.5) |
| `--logs` log-vs-database | everything, but only where servers and daemon share a host (LAN) |

⚠️ At a LAN, drop the timer to every 10 minutes and pass `--logs`. ⚠️ Runs as root and reaches MySQL over the local socket — it holds no credentials, and this repo is public.

### package-dod-base.sh
Creates a tarball of base DoD game files for deployment to new servers.

**Usage:**
```bash
./package-dod-base.sh [source_path] [output_path]
```

### precache_audit.py
Fleet-wide precache-gap audit. Cross-references map-declared asset references against the actual on-disk state of every game-server instance + FastDL. Surfaces files that are referenced (and could be precached on map load) but missing on one or more hosts → crash candidates when those hosts rotate to the relevant map.

**Reference sources:**
- **`.res` files** (Phase 1, 2026-05-02). Custom maps' explicit asset manifests. Caught the 2026-05-01 `xrain2.spr` crash on `dod_thunder`.
- **BSP `entdata` lump** (Phase 2, 2026-05-02). Stock DoD maps don't have `.res` files but DO embed precache references in entity definitions (`env_sprite "model"`, `ambient_generic "message"`, `worldspawn "wad"`). Generalizes the bug class to stock maps.

**Severity model:**
| Severity | Trigger | Discord post |
|---|---|---|
| `CRITICAL` | Missing on 5+ game-server instances | yes |
| `HIGH`     | Missing on 1-4 game-server instances | yes |
| `MEDIUM`   | Present on every game host, missing on FastDL | yes |
| `LOW`      | Other drift | yes |
| `INFO`     | Reference host AND ≥80% of fleet missing — stale entdata, engine-tolerated | no (silent in cron mode; listed in saved report.md) |

**Usage:**
```bash
# Manual run, full report to stdout
python3 precache_audit.py

# Save report to a file (markdown)
python3 precache_audit.py --output /tmp/audit.md

# BSP-only or .res-only
python3 precache_audit.py --scope bsp
python3 precache_audit.py --scope res

# Pull references from a different reference host
python3 precache_audit.py --ref-host dal --ref-port 27015

# Cron mode — post Discord embed only on actionable severity, silent otherwise
python3 precache_audit.py --scope all --cron-mode --output /var/log/ktp-precache-audit-$(date +%Y%m%d).md
```

**Cron:** `/etc/cron.d/ktp-precache-audit-weekly` runs Sun 06:00 ET → posts to `#ktp-updates` (channel id `1498813261263405097`) only on actionable severity (silent on green/INFO-only).

**Deployed to:** `/usr/local/bin/ktp-precache-audit` (data server symlink to the script).

**Phase 3 deferred** — SHA256 drift detection (presence-only today). Add only if a real drift incident shows up; deploys are pretty atomic via FTP fan-out.

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
| hlstatsx-ingest-monitor.py | Data Server | /usr/local/bin/ (+ systemd timer) |
| ktp-log-rotation.sh | Game Servers | /home/dodserver/ |
