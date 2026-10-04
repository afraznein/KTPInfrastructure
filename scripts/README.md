# KTP Infrastructure Scripts

> **Coverage note (2026-07-07):** this README documents only the most-used
> scripts (~a third of `scripts/`). For anything not listed, the script's
> own header comment is the documentation — every KTP script carries one.

Operational scripts for KTP game servers and data server.

**Note:** Scripts with `.example` extension are templates. Copy to the actual filename and fill in your credentials before deploying.

### Official team-score ingestion and projection

`import_demo_team_score.py` labels each half from the HLTV demo's engine
TeamScore (`producer = hltv-demo`, migrations 033/034) into the append-only
migration-023 ledgers; it runs hourly from the `ktp-demo-publish.sh` labels hook.
The KTPHudObserver `events.jsonl` importer was retired 2026-09-18
(`docs/OFFICIAL_TEAM_SCORE_TELEMETRY.md`). `project_team_score.py` runs the strict
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
`spatial_map_geometry.py` turns a map's `overview` block into the
world-to-overview projection pair the match report draws with, for both
`ROTATED` conventions. `make_overview_descriptor.py` runs that projection
backwards: give it a `.bsp` and it solves the `overviews/<map>.txt` descriptor
-- `ZOOM`, `ORIGIN`, `ROTATED` and layer `HEIGHT` -- from the map's own bounds,
which `bsp_bounds.py` reads out of lumps 0, 10 and 14. Pass `--json` for the
bounds box, so whatever renders the matching `.bmp` frames the same one.
`render_overview_bmp.py` makes that `.bmp` from the same BSP: a 1024x768 8-bit
file keyed on palette colour RGB(0,255,0), drawn with the same projection (the
`ROTATED 1` branch verified against `dod_thunder`), with ZOOM/ORIGIN derived
from `models[0]` bounds unless `--descriptor` supplies them.
`audit_overview_corpus.py` turns that renderer on a whole overview directory and
asks, per map, whether the shipped image agrees with its own `.txt`: it renders
each map through the shipped descriptor and searches scale/offset for the
transform that best lines the two footprints up. Identity means self-consistent;
anything else measures how far the shipped asset misplaces every player dot. It
also groups images by md5 and flags a group whose descriptors disagree, and it
refuses to score an image that keys zero pixels rather than scoring it badly.
Corpus results are in `docs/OVERVIEW_CORPUS_AUDIT.md`.

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
`spatial_map_registry.py` inventories KTP match maps from the `ktp_maps.ini`
bindings the server reads and produces the map readiness matrix; it does not
infer geometry or waypoints, and it does not read a config's `say` line.

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

### ktp-deploy.py
**The shared entry point to `stage-wave.py` and `ktp-wave-ledger.py` on the data server**, for every
deployer rather than one workstation. It runs them from a checkout it re-proves at `origin/main` on every
run, behind a lock that names its holder, against one shared ledger and rows file, and records who ran what.
Install, the credential options and the open decisions: `docs/runbooks/SHARED_STAGE_WAVE.md`.

```bash
ktp-deploy stage --preflight-only
ktp-deploy stage -f ~/X.amxx --expect X.amxx=<md5> --base X.amxx=<owner/repo@sha>
ktp-deploy ledger reconcile
```

### ktp_script_freshness.py
**Not a script to run — a gate the fleet-writing scripts call on themselves.** A checkout that has fallen
behind `origin/main` stages a wave perfectly happily: the older copy never sees the flags it lacks, so
nothing is rejected, the md5s verify, and it prints a clean 24/24 while every gate added since simply did
not run. The loss that costs something is `--pull-live` — the fleet keeps no rollback copies, the swap is
`mv -f`, and none of these artifacts is byte-reproducible, so the live build is the only copy of itself
that exists.

`require_current()` compares the file that is executing, and the siblings it loads, against `origin/main`
via `git diff`, and refuses with a report naming which flags and functions this copy is missing and which
commits added them. It fails closed: drift, no checkout, the path absent from the ref, a failed git call
and an unfetchable ref all refuse. It is inert under pytest and GitHub Actions, and says so.

**An installed copy** (`/usr/local/bin/ktp-verify-deploy`, run by the soak cron) is in no checkout, so it is
checked through the deploy manifest instead: its bytes must match the md5 of its last `DEPLOYED.tsv` row
(untouched since `ktp-install`), and that must equal the blob at the fetched `origin/main` for the row's
`source_path` in `KTP_FRESHNESS_REPO` (default `/opt/ktp-infra`). The fetch writes only
`refs/remotes/origin/main`; the tree is never pulled. A copy with no row is refused as before.

```bash
python3 ktp_script_freshness.py stage-wave.py   # report without running anything
```

`KTP_FRESHNESS_OFFLINE=<reason>` accepts an unfetchable ref that the local comparison found clean;
`KTP_FRESHNESS_BYPASS=<reason>` proceeds after a refusal, printing the whole report anyway.
⚠️ The cron scripts (`audit-fleet-drift.py`, `precache_audit.py`) are deliberately **not** gated: they run
out of `/opt/ktp-infra`, which is never auto-pulled, and failing closed there would replace stale data with
no data.

⚠️ **The gate is Python-only, and the shell scripts are where that bites.** `require_current()` is wired
into the Python fleet writers; a `.sh` in this directory has no equivalent, so a stale copy of one is still a
live hazard with nothing standing in front of it.

**Measured instance (2026-09-27) — `scripts/ktp-ac-retention.sh`.** The project-root checkout on this
workstation holds that file byte-identical to a blob that predates the commits which *widened* the windows, so
its env defaults declare shorter retention than the current ones: shorter for weapon rows and for expired
tokens, and it sweeps the evidence bundles `origin/main` now deliberately retains by default. Redeploying it
from that tree, or running it there with the env unset, quietly reinstates the window the current comments
exist to argue against — and **nothing reports that**. The script prints the same closing line either way,
and `ktp-ac-retention` carries no alert coverage (`docs/runbooks/ALERT_COVERAGE.md`).

➡️ **Read and install these from the ref, never from the working copy**
(`git show origin/main:scripts/<name>`), and diff the two before anything is installed. ⛔ Do not settle it
with the figures in either file — whichever number you remember is the one that has rotted. Ask git which
blob you are holding.

⚠️ **A green test run says nothing about `origin/main` here.** The retention tests that do exist
(`tests/unit/test_demo_retention.py`, `tests/unit/test_match_retention.py`) resolve their script by a fixed
relative walk-up from the test file, so they exercise whichever checkout they happen to sit in: a stale tree
tests its own stale script and passes. `ktp-ac-retention.sh` has no test at all.

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

**Note:** A proxy counts as a success only once its journal shows it connected to its
game server after the restart (`Received baseline` or `Connected to Game Server`), within
`CONNECT_WAIT_SECONDS` (default 180). An active proxy that never connects is reported as
*up but not connected* and turns the summary orange.

**Deployed to:** `/usr/local/bin/hltv-restart-all.sh` (data server)

**Schedule:** the `hltv-restart.timer` systemd timer, 03:00 and 11:00 ET. It is not cron:
`ktp-soak-verify.py` reads `journalctl -u hltv-restart`, which a cron job would not write.

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

> ✅ **Fixed 2026-08-31 -- the idle gate is judged on PLAY, not on recording.**
> It previously required zero `.dem` writes in 15 minutes, but the 24 HLTV proxies record
> continuously, so that term could never reach zero and the reboot never once fired. The demo
> term is gone; the second signal is now an unfinished match row, **bounded to 6h** because 186
> rows carry a NULL `end_time` going back to January and an unbounded check would block forever.
> `--force` skips the idle check for an operator-directed reboot, but **still fails closed on a
> database error** -- forcing past a known-busy state is allowed, forcing past an unknown one is not.

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

### build_map_bundle.py / build_resgen.sh
One entry point from "a new `.bsp` landed" to the four files a client needs:
`maps/<map>.bsp`, `maps/<map>.res`, `overviews/<map>.txt`, `overviews/<map>.bmp`,
plus a `MANIFEST.json` of md5s for the post-deploy sweep. It writes to a staging
directory and touches no server — `docs/MAP_DEPLOY.md` is the operator half.

```bash
scripts/build_resgen.sh                      # clone + build RESGen at the pinned 2.0.3 tag
export KTP_RESGEN=~/.cache/ktp/resgen/bin/resgen

python scripts/build_map_bundle.py dod_newmap_b1.bsp \
    --out ~/staging/maps \
    --compare-against <dir with the predecessor's .res> --predecessor dod_newmap_a9
```

RESGen is GPL-2.0 third-party code (`kriswema/resgen`) and is deliberately not
vendored; `build_resgen.sh` fetches and builds it into a scratch directory.

Two things worth knowing before running it. RESGen lists the overview pair **only
if both files already exist** next to the map, so the overview has to be rendered
first — the tool enforces that order and fails the bundle otherwise. And it writes
CRLF, matching every `.res` already on the fleet.

`--compare-against` prints the entry-list delta against the predecessor map
alongside the BSP's worldspawn `wad` and `skyname` keys, so a WAD that appeared or
vanished can be checked against the map rather than accepted.

The validation behind the pinned tag — 44 fleet maps replayed, what reproduced and
what did not — is in `docs/MAP_DEPLOY.md`.

### assemble_changelog.py
Folds the per-change fragments in `changelog.d/` into a numbered `CHANGELOG.md` section. Runs on `main` at release time, and is the only thing that writes that file — a PR adds its own fragment instead, so two PRs never touch the same line. `changelog.d/README.md` is the contributor-facing convention.

```bash
python scripts/assemble_changelog.py preview                  # render the unreleased section
python scripts/assemble_changelog.py check                    # validate fragments + the stub (Tier 1 runs this)
python scripts/assemble_changelog.py release --version 1.6.0  # fold, then delete the fragments
```

Output is ordered by filename and normalised to LF, so the same fragments always produce the same bytes and a regeneration is never a spurious diff.

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
