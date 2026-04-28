# KTP Test Infrastructure Plan

**Status:** Planning scoped 2026-04-24. **Tier 1 fully live 2026-04-28** — all 9 KTP plugin/module callers auto-trigger smoke on push, ~3-5 min runs via GHCR fast path. **Tier 3 Project 1 partially shipped 2026-04-25** via KTPAdminBot Phase 8.2 work. Tier 2 not started — now unblocked since T1 is live and the `amx_ktp_versions` rcon prerequisite shipped. Open T1 leaf: KTPAntiCheat xUnit scaffolding.
**Scope:** Three-tier test infrastructure across the KTP stack — build-time smoke tests, pre-deploy integration tests, and continuous production baseline monitoring.

## Already shipped (overlaps with this plan)

KTPAdminBot Phase 8.2 + 8.3 (2026-04-25) shipped infrastructure that overlaps with parts of this plan:

- **`[KTP_PROFILE]` aggregation daemon** (Tier 3 Project 1) — exists at `/opt/ktp-profile-aggregator/` on the data server. Paramiko-tails 25 game-server logs on a **5-min cycle** (the plan called for 60s but 5 min is sufficient for v1), parses `[KTP_PROFILE]` + `[KTP_SPIKE_*]`, persists to MySQL. Watermark-driven (clean restart re-sync). **Real schema names:** `ktp_telemetry_metrics` + `ktp_telemetry_watermarks` (the plan's planned names — `profile_samples`, `profile_rollups_daily`, `spikes`, `spike_signatures`, `crashes`, `ingest_watermarks` — were aspirational and supersede the actual table names below).
- **Ad-hoc query commands** — `/ops fps`, `/ops spikes`, `/ops pull-spikes` (AdminBot 8.2). Reads the aggregator's data on demand. Does **not** include auto-rollup + 2σ-deviation alerting; that piece of Tier 3 still needs to ship.
- **Adjacent: `/ops versions`** (AdminBot 8.3) — md5sums engine + KTPAMXX binary + KTPMatchHandler.amxx fleet-wide via async SSH fan-out. **Not the same** as the Tier 2 prerequisite `amx_ktp_versions` rcon — `/ops versions` covers 3 specific files, `amx_ktp_versions` would be a per-plugin reporter that every plugin registers. The latter is still an open dependency for Tier 2.

**What's still TODO in Tier 3:** auto-rollup + alerting on profile deviations, core-dump auto-reporter, `[KTP_SPIKE]` categorizer with new-signature alerts. ~40 hours remaining (down from the planned 60).

## Motivation

Seven production incidents in recent memory would have been caught earlier by systematic testing:

| Incident | Tier that would have caught it |
|---|---|
| 2026-04-14 KTPAmxxCurl CMake missing `.cc` → all plugins "bad load" | Tier 1 (module-load smoke) |
| 2026-04-21 `.new` files staged but never swapped | Tier 2 (deploy verification) |
| HPAK fleet segfault under specific customization traffic | Tier 3 (core-dump auto-report) |
| cmd_ready 163ms spike regression (undetected for days) | Tier 3 (profile baseline diff) |
| JIT strip side effects (only testable post-restart) | Tier 1/2 (local A/B scaffolding) |
| DODX forward-firing silent data loss | Tier 2 (forward assertion) |
| Plugin version activation confusion (loaded ≠ running) | Tier 2 (live version diagnostic) |

5 of 7 incidents land in Tier 1/2 (prevention), 2 in Tier 3 (faster response). Prevention > response for equivalent cost.

## Tier framework

**Three tiers map to three cost/latency envelopes:**

- **Tier 1 — Build-time smoke.** Seconds per run. Every compile/push. Catches "it doesn't even load" failures.
- **Tier 2 — Pre-deploy integration.** Minutes per run. Before each fleet deploy. Catches workflow + deploy-verification failures.
- **Tier 3 — Runtime prod baseline.** Continuous passive. Uses data the engine already emits. Catches performance regressions + crash patterns.

**Explicit non-goals:**
- Testing the closed-source `dod_i386.so` game DLL — we don't own it.
- 24-player synthetic load — requires synthetic-client tooling that doesn't exist yet.
- Replacing Netdata / existing ad-hoc monitoring — test infra complements, doesn't replace.

---

## Tier 1 — Fast smoke tests (build-time)

**Goal.** Catch "it doesn't even load" regressions in <60s so CMake/include/symbol breakage never reaches staging.

### Session 1 shipped 2026-04-26 — shared smoke harness

`KTPInfrastructure/tests/smoke/` provides:
- **`rcon.py`** — GoldSrc UDP rcon client (stdlib only). Wire format verified against `KTPReHLDS/rehlds/engine/sv_main.cpp` (challenge / SV_Rcon / SV_FlushRedirect with A2A_PRINT). Multi-packet response drain.
- **`server_handle.py`** + **`boot.py`** + **`boot_subprocess.py`** — dual boot drivers. Compose path layered on existing `docker-compose.local.yml`; subprocess path runs hlds_linux directly with WSL trampoline on Windows. Same `ServerHandle` API.
- **`parse.py`** — fixed-column parser keyed off KTPAMXX's `srvcmd.cpp` format strings (`%-23.22s %-11.10s %-20.19s %-11.10s` for modules; equivalent for plugins). Truncation-aware matcher (`%-12.11s` truncates filenames to 11 chars; matcher handles full-vs-truncated bidirectional with 8-char prefix floor).
- **`asserts.py`** — `assert_modules_loaded(expected)`, `assert_plugins_running(expected)`, `assert_no_failed_modules`, `assert_no_failed_plugins`. Each names the offender on failure.
- **`cli.py`** — `python -m tests.smoke.cli {wait-ready,rcon,assert-modules,assert-plugins,assert-no-failed}`. Exit `0` clean / `1` assertion / `2` infrastructure.
- **`fixtures/test_server.cfg`** — minimal sv_lan boot config.
- **`test_parse.py`** + **`test_asserts.py`** — 24 unit tests covering the risky paths (parser column drift, AMXX truncation, all four assertion functions on both green and red inputs). Green.
- **`README.md`** — usage, layout, the truncation gotcha, the WSL DrvFs `_stat` gotcha for local-Windows live boot.

**Live boot validation:** deferred to Session 2 CI run on `ubuntu-latest`. Local Windows path is blocked by WSL DrvFs incompatibility with hlds_linux (engine core-dumps on `_stat` of `liblist.gam` from `/mnt/n`). Docker compose path is the local workaround once Docker Desktop is up. Risk surface (parser correctness, assertion semantics) is covered by unit tests.

**~6h spent of ~40h budget.** Remaining sessions:
- Session 2 (~6-8h) — `KTPAmxxCurl/.github/workflows/smoke.yml` + shared `compile-amx` composite action. First live boot.
- Session 3 (~10-12h) — KTPAntiCheat xUnit projects.
- Session 4 (~8-10h) — config-parse pytest + branch protection wiring.

### In scope for v1
- Plugin-load smoke for 3 highest-churn plugins: KTPMatchHandler, KTPAmxxCurl-dependent plugins (KTPMatchHandler, KTPHLTVRecorder), KTPCvarChecker.
- Module-load smoke for 4 `.so` modules: `amxxcurl_ktp`, `reapi_ktp`, `dodx_ktp`, `amxmodx_mm_i386.so`.
- C# unit tests for KTPAntiCheat.Core (hash/verdict logic, config parsing) and KTPAntiCheat.Api (controller happy-path + 401/403).
- Config-parse tests: `ktp_maps.ini`, `discord.ini`, AntiCheat `appsettings.json` schema validation.

### Deferred to later
- Pawn unit tests of individual natives
- Full AMXX module ABI compatibility matrix
- KTPHLStatsX Perl tests (low churn, painful tooling)
- Google Apps Script tests (small projects, manual OK)

### Tooling stack
- **C# (KTPAntiCheat):** xUnit + FluentAssertions + `Microsoft.AspNetCore.Mvc.Testing.WebApplicationFactory`.
- **C++ modules:** no unit tests at this tier. Python-driven load-smoke harness boots local `serverfiles/hlds_linux`, sends `meta list` and `amxx modules` via rcon, parses output, asserts zero "bad load" entries + expected module count.
- **Pawn plugins:** same Python load-smoke harness — `amxx plugins` rcon output, assert status `running` for every expected plugin. (See "Pawn testing strategy" in cross-cutting section.)
- **Config parsing:** Python `pytest` with parse-and-assert fixtures in `KTPInfrastructure/tests/`.
- **CI host:** GitHub Actions. Matrix: `ubuntu-latest` for plugin compile, `windows-latest` for C# tests. Load-smoke runs on a self-hosted runner (see CI host decision).

### Project coverage order
1. **KTPAmxxCurl** — caused the 04-14 incident; highest ROI.
2. **KTPMatchHandler** — most complex, most dependencies, most blast radius.
3. **KTPAntiCheat (Core + Api)** — pre-launch, xUnit scaffolding should exist before service ships.

### New infrastructure required
- `KTPInfrastructure/tests/smoke/` — Python harness: `boot_local_hlds.py`, `rcon_assert.py`, `plugin_load_smoke.py`, `module_load_smoke.py`.
- `test_mapcycle.txt` + `test_server.cfg` — minimal boot config (empty map, no bots, `sv_lan 1`, stdout logging, clean exit).
- `.github/workflows/smoke.yml` per-project in KTPAmxxCurl, KTPMatchHandler, KTPAntiCheat.
- Shared composite action `.github/actions/compile-amx/action.yml` in KTPInfrastructure referenced by plugin repos.
- `KTPAntiCheat.Core.Tests/` + `KTPAntiCheat.Api.Tests/` xUnit projects in the solution.

### Integration with workflow
- Runs on every push + PR.
- **Blocks** fleet deploys for the affected project. `deploy_curl.py` (and analogous) gains pre-flight check reading the last GitHub Actions run status for HEAD.
- Optional local pre-commit hook (`install-hooks.sh` already exists) runs C# + config-parse tests; skips slower load-smoke.

### Observability
- GitHub Actions UI = primary surface.
- Red main-branch builds post to `#ktp-ci` via Discord Relay. Embed includes: project, commit SHA, failing job, first 30 lines of failure log.
- PR builds: status checks only, no Discord.

### Rollout + maintenance
Author of change owns test update. Red main = P1, fix-forward or revert same day. No disable-the-test escape hatch. Flaky test = fix in 48h or delete.

### Scope
~1,500 LoC (harness + workflows + xUnit projects). ~40 engineering hours to v1-complete.

---

## Tier 2 — Slow integration tests (pre-deploy)

**Goal.** Verify full match-flow round-trip works on local test server before nightly fleet deploy, so DODX-forward-silent-failure and `.new`-swap-didn't-happen regressions are caught before production.

### Prerequisite: live version diagnostic
**Must ship before Tier 2 is meaningful.** A new rcon command `amx_ktp_versions` that every KTP plugin registers on load, returning `{plugin_name, CHANGELOG_version, sha_of_loaded_amxx}`. Implemented once in a shared include (`ktp_version_reporter.inc`), pulled in by every plugin — one-line addition per plugin. Enables deploy-verification ("is this actually what we deployed?") and integration test version-assertions.

### In scope for v1
- **Match-flow integration test:** scripted rcon driver walks through `.confirm` → `.ready` → half-start → simulated score events → half-end → match-end. Assert: match_id in logs, Discord embed HTTP attempted (via fake Relay endpoint on localhost), DODX `save_frag` native called (via test-only cvar debug-print OR staging MySQL row).
- **AntiCheat API integration:** ephemeral MySQL via Testcontainers.NET + `WebApplicationFactory` exercising login → heartbeat → verdict upload → admin query. Already partially specified in `KTPAntiCheat/docs/INTEGRATION_PLAN.md`.
- **DODX forward-firing test:** narrow pytest file booting hlds, triggering known events, asserting DODX forwards fired (via diagnostic cvar exposed by test-only DODX build, or staging MySQL row).
- **Deploy-verification script:** post-deploy paramiko script SSHes each target, `md5sum`s deployed `.amxx`/`.so`, asserts match to staged artifacts. Runs `amx_ktp_versions` rcon, asserts expected versions. Directly addresses 04-21 `.new`-swap bug.

### Deferred to later
- Full 24-player synthetic load (requires bot tooling)
- HLTV demo recording verification (complex, low bug incidence)
- KTPHLStatsX Perl daemon integration (defer until Tier 3 catches stat-write anomalies)
- KTPFileDistributor Python (low churn)

### Tooling stack
- **Integration driver:** Python + `pytest` + custom `ktp_rcon` client (thin wrapper over existing `KTPAmxxCurl/scripts/` rcon logic).
- **Fake Discord Relay:** 50-line `aiohttp` mock recording POSTs for assertion, swapped in via `RELAY_URL=http://localhost:PORT/test`.
- **AntiCheat integration:** xUnit + Testcontainers.NET (MySQL container per test class) + `WebApplicationFactory`.
- **CI host:** self-hosted runner on data server or dedicated box (see CI host decision).

### Project coverage order
1. **KTPMatchHandler + KTPAmxxCurl + KTPReAPI as a system** — the match-flow core, tested together.
2. **KTPAntiCheat.Api end-to-end** — greenfield, cheap to wire up pre-launch.
3. **DODX forward-firing test** — narrow, targeted at silent-data-loss bug.

### New infrastructure required
- `KTPInfrastructure/tests/integration/` — pytest suite, hlds boot/teardown fixtures, rcon helpers, fake Discord Relay, fake KTPFileDistributor endpoint.
- `docker-compose.integration.yml` — ephemeral MySQL 8 for DODX/HLStatsX assertions, ephemeral whatever-AntiCheat-uses.
- Shared `ktp_version_reporter.inc` (the prerequisite above).
- **Test-mode plugin build flag.** `-DKTP_TEST_MODE` define that (a) enables synthetic event injection via `amx_ktp_test_inject_event` rcon, (b) lowers all timers for fast runs, (c) always logs to stdout. Test harness uses test-mode builds; prod uses normal.
- `KTPInfrastructure/scripts/verify_deploy.py` — post-deploy md5 + rcon version assertion across fleet.

### Integration with workflow
- Runs on PRs touching KTPMatchHandler, KTPAmxxCurl, KTPReAPI, KTPAntiCheat.
- Mandatory before 3 AM fleet deploy. Deploy script blocks if most recent main-branch integration run is red or >24h old.
- Deploy-verification runs post-swap at 3:05 AM. Discord alert if md5 or version doesn't match expected.

### Observability
- Pytest JUnit XML → GitHub Actions artifact + Allure report on GitHub Pages (KTPInfrastructure). 30-day history.
- Failures → `#ktp-ci` with one-line summary + run link.
- Deploy-verification failures → `#ktp-deploys` (new channel, ops audience) at @channel severity.

### Rollout + maintenance
Strict flake rule: test failing twice in a row on unchanged main is quarantined (`@flaky`), mandatory tracking issue, **1-week fix-or-delete SLA**. No long-lived quarantines. Max 3 simultaneous quarantined tests = stop adding tests, fix existing first.

### Scope
~3,500 LoC (harness + fixtures + AntiCheat integration project + test-mode plugin wiring). ~120 engineering hours to v1-complete.

---

## Tier 3 — Prod-baseline monitoring (continuous)

**Goal.** Detect performance regressions and crashes in production before users or manual log inspection do, using data the engine already emits.

### In scope for v1
- **`[KTP_PROFILE]` aggregation daemon.** ✅ **Partially shipped** as `/opt/ktp-profile-aggregator/` (AdminBot Phase 8.2, 2026-04-25). Paramiko-tails fleet on **5-min cycle**, parses `[KTP_PROFILE]` + `[KTP_SPIKE_*]`, persists to `ktp_telemetry_metrics` + `ktp_telemetry_watermarks`. Watermark-driven, clean restart re-sync. **Still TODO:** daily rollup computing per-server per-phase p50/p95/p99 + diff vs trailing-7-day median + alert on >2σ deviation routing to `#ktp-perf`.
- **Core-dump auto-reporter.** 2026-04-22 core-dump infrastructure writes cores to known path. systemd path unit (or inotify watcher) per baremetal runs `gdb -batch -ex bt` on new cores, extracts top-20 frames, posts to Discord `#ktp-crashes` with server, binary, timestamp, top frame.
- **`[KTP_SPIKE]` categorizer.** Parser already exists in the aggregator (sees the data). **Still TODO:** signature bucketing by (phase, map, cause-if-detectable), daily digest to Discord, immediate alert on never-seen-before signatures.

### Deferred to later
- Real-time sub-minute alerting on profile deviations (daily rollup enough for v1)
- ML anomaly detection (overkill; 2σ on stable baseline works)
- Per-player metrics
- Memory growth tracking (separate concern, existing ad-hoc tooling)

### Tooling stack
- **Language:** Python — matches existing `KTPInfrastructure/monitoring/ktp-server-monitor.py`, `profiling-report.py`, `scripts/*.py`, and the now-shipped aggregator at `/opt/ktp-profile-aggregator/`.
- **Storage:** MySQL on data server. **Real schema:** `ktp_telemetry_metrics` (raw samples + parsed spike rows) + `ktp_telemetry_watermarks` (per-server-per-port last-parsed timestamps). The aspirational separate tables (`profile_samples`, `profile_rollups_daily`, `spikes`, `spike_signatures`, `crashes`) are not (and need not be) created — rollups will be SQL views/queries against `ktp_telemetry_metrics`; signatures + crashes get their own tables when those projects start.
- **Scheduling:** systemd timer for the aggregator already in place. Daily rollup will be a separate cron (or systemd timer) when it ships.
- **CI host:** N/A — Tier 3 is a production daemon with its own deploy story.

### Project coverage order (revised 2026-04-25)
1. ✅ **`[KTP_PROFILE]` ingest** — shipped as AdminBot Phase 8.2. **Remaining:** rollup + alert on >2σ deviation. ~10-15 hours.
2. **Core-dump auto-reporter** — addresses HPAK class directly. Low LoC, high ops value. ~10-15 hours, ~200 LoC.
3. **`[KTP_SPIKE]` categorizer + new-signature alerts** — parser already exists in the aggregator; this layer adds bucketing + daily digest + immediate alert path. ~15 hours.

### New infrastructure required (revised)
- ~~`KTPInfrastructure/monitoring/telemetry_ingest/`~~ — superseded by `/opt/ktp-profile-aggregator/` (private repo, deployed via SFTP).
- **Rollup query/script** layered on top of `ktp_telemetry_metrics` — daily systemd timer, computes p50/p95/p99 per (server, phase) over trailing 7 days, posts deviation alerts to `#ktp-perf`.
- **`spike_signatures` + `crashes` tables** — added when those projects start, not earlier.
- **`KTPInfrastructure/monitoring/crashreporter/`** — per-baremetal systemd path unit + `report_core.py` calling `gdb -batch -ex bt`.
- **New Discord channels:** `#ktp-perf` (digest + regressions, info severity), `#ktp-crashes` (cores + new spike signatures, pager severity).

### Integration with workflow
Passive. No workflow change. Complements Netdata (host metrics) vs. Tier 3 (engine-internal metrics).

### Observability
- Primary: Discord channel routing.
- Secondary: MySQL-backed Grafana dashboard on data server for 30-day trends per server per phase. Deferrable to v2 if Grafana isn't already in the KTPHLStatsX stack.

### Rollout + maintenance
Daemon owner = infra-on-call. Schema changes require PR + migration SQL. Alert thresholds tuned quarterly based on false-positive rate. Alerts with <1 true-positive per month get loosened.

### Scope (revised 2026-04-25)
~2,000 LoC originally planned. **Aggregator (~800 LoC, ~20h equivalent) shipped as Phase 8.2.** Remaining: rollup + alert (~400 LoC, ~12h), core-dump reporter (~200 LoC, ~12h), spike categorizer (~400 LoC, ~15h). **~40 hours remaining** (down from 60).

---

## Cross-cutting decisions

### Test ownership + maintenance

One non-negotiable rule: **author of code change owns test change**. No dedicated QA, no handoff.

**Flake discipline per tier:**
- **Tier 1** — flakes fixed or deleted in 48h. No quarantine tier.
- **Tier 2** — `@flaky` quarantine, hard 1-week fix-or-delete SLA. Max 3 simultaneously quarantined.
- **Tier 3** — production code; flakes = alerts, handled via on-call.

Test code gets same code-review standard as production code. No "it's just a test" escape hatch.

### CI host decision

**Locked: GitHub Actions hosted for Tier 1, self-hosted runner on data server for Tier 2.**

Tier 1 is lightweight, parallelizes well, GitHub-hosted Linux handles compile + xUnit in <1 min. Pro-tier minutes (3000/mo free) cover Tier 1 easily.

Tier 2 needs hlds_linux booted with full `serverfiles/` tree (~2 GB), Testcontainers (~500 MB pulls), 3-8 min runs. Self-hosted runner on data server spare capacity amortizes setup, caches tree, runs 5x faster. Systemd cgroup limits (`CPUQuota=50%`, `MemoryMax=2G`, `IOWeight=10`) prevent test spikes from starving prod. Match-hours embargo (7pm-midnight ET) skips CI during prime-time matches; PRs queue and clear post-match. Register as GitHub Actions self-hosted runner — workflow syntax identical, just `runs-on: self-hosted`.

**Fallback if coupling bites:** $15/mo VPS (Hetzner CX22, Linode g6-nanode, etc.). Runner registration is the only change; schema/workflows stay identical.

**Not recommended:** Jenkins, Drone, Buildkite — too much operational overhead for 1-2 person team.

### Alert routing (four new Discord channels)

| Channel | Purpose | Severity | Source |
|---|---|---|---|
| `#ktp-ci` | Tier 1/2 test failures on main | Info, no @channel | GitHub Actions → Relay |
| `#ktp-deploys` | Deploy-verification failures | Warning + @channel | verify_deploy.py → Relay |
| `#ktp-perf` | Tier 3 profile regressions | Info digest + threshold-breach warning | Tier 3 alert_router → Relay |
| `#ktp-crashes` | Tier 3 core dumps + new spike signatures | Pager (@here per-server-first, @channel on ≥3/hr) | crashreporter → Relay |

AntiCheat verdict alerts stay in their existing channel — different audience.

### Baseline data retention

- Tier 1 test history: GitHub Actions 90d. Sufficient.
- Tier 2 test history: Allure report on GH Pages, 30d. Sufficient.
- Tier 3 raw profile samples: **7 days** (sampled every 10th line for storage sanity).
- Tier 3 daily rollups: indefinite (~5 KB/server/day = ~45 MB/year for 25 servers).
- Tier 3 raw cores: 30 days (large, rotate aggressively); extracted backtraces forever (tiny).

**Year-1 data server storage footprint:** ~20 GB. Negligible.

### Pawn testing strategy

**Chosen: Python + rcon + log assertions.** Rejected alternatives:
- **Test harness plugin** — duplicates Tier 2 at Tier 1 cost, Pawn testing Pawn is same-language blind spot, requires every plugin to link harness. Not worth maintenance.
- **Skip Pawn entirely** — leaves 04-14 incident class uncaught. Unacceptable.

Python load-smoke catches load failures (dominant failure mode) with zero new Pawn infrastructure. Deeper plugin logic testing is Tier 2's job.

One Pawn concession: shared `ktp_version_reporter.inc` for `amx_ktp_versions` rcon. That's infrastructure, not tests.

---

## Starting sequence

**Prevention > response for equivalent cost.** Tier 1 catches 5 of 7 listed incidents; Tier 3 catches 2. Tier 1 first.

| Weeks | Track A (build/integration) | Track B (prod monitoring) |
|---|---|---|
| ~~1-2~~ | ~~Tier 3 profile ingest daemon~~ ✅ shipped as AdminBot Phase 8.2 | |
| 1-2 | Tier 1 for KTPAmxxCurl (prevents 04-14 class) | Tier 3 rollup + 2σ alert (`#ktp-perf`) |
| 3-4 | — | Tier 3 core-dump auto-reporter (`#ktp-crashes`) |
| 3-5 | Tier 1 for KTPMatchHandler + KTPAntiCheat | — |
| 4-5 | — | Tier 3 spike categorizer + new-signature alerts |
| 5-9 | Tier 2 scaffolding: live-version diagnostic → match-flow → AntiCheat integration | — |
| 9-11 | Deploy verification integrated into 3 AM deploy | — |

Tracks A and B are parallel (different skill areas — CI/C#/Python vs. Python/SQL/systemd). Single-dev could sequence as A→B instead.

Tier 2 last because it depends on Tier 1 build reliability + version diagnostic, and is the most complex/flaky tier. Better to start it with experience from Tier 1 + Tier 3.

---

## Scope totals (revised 2026-04-25)

| Tier | LoC planned | Hours planned | Shipped | Hours remaining |
|---|---|---|---|---|
| Tier 1 | ~1,500 | ~40 | full harness + 9 callers + GHCR fast path + config-parse + preflight + bring-up debug (~26h) — fully live 2026-04-28 | ~14 (KTPAntiCheat xUnit only) |
| Tier 2 | ~3,500 | ~120 | — | ~120 |
| Tier 3 | ~2,000 | ~60 | aggregator (~800 LoC, ~20h) via AdminBot 8.2 | ~40 |
| Cross-cutting | ~300 | ~20 | — | ~20 |
| **Total** | **~7,300** | **~240** | **~46** | **~194** |

~5.5 weeks focused solo, ~9-11 calendar weeks part-time alongside regular plugin development.

---

## Decisions locked 2026-04-24

**Q1. Tier 2 self-hosted runner host → data server spare capacity with cgroup limits.**
Runner co-located with ktp-ac-api / HLStatsX / etc. Systemd cgroup: `CPUQuota=50%`, `MemoryMax=2G`, `IOWeight=10`. Runner refuses jobs 7pm-midnight ET (match-hours embargo) unless invoked with `--force-offpeak`; CI queues to post-match to prevent test spikes during live matches. $0/month ongoing. Migration path: if coupling bites, fall back to $15/mo VPS — schema unchanged, just move the runner registration.

**Q2. Branch protection: Tier 1 blocks merges day 1, Tier 2 warn-only until 2 weeks of green-on-main, then flip to blocking.**
Tier 1 is fast/simple/low-flake — blocking is fine immediately. Tier 2 is minutes-long/complex/high-flake initially — premature blocking causes "disable the integration test to merge urgent fix" antipatterns. Hotfix escape hatch: admin-only "merge without checks" in GitHub branch protection, used sparingly, logged in PR description. Tier 3 is production monitoring, not PR-gating — N/A.

**Q3. Tier 3 log shipping: paramiko-pull with MySQL-persisted watermarks.** ✅ **Implemented 2026-04-25 as AdminBot Phase 8.2.**
Daemon at `/opt/ktp-profile-aggregator/` SSHes fleet on a **5-minute** interval (revised from the planned 60s — sufficient for v1; sub-minute can be revisited if a regression hits faster than rollup catches it), parallelized via asyncio, tails each active log file since last watermark. **Watermarks persist in MySQL** (`ktp_telemetry_watermarks`, per-server-per-port last-parsed timestamp) — daemon restart mid-shift re-syncs cleanly without re-ingesting or gap. Migration path to fluent-bit-push if fleet grows past ~40 instances or sub-second freshness becomes a goal; ingest schema is shipper-agnostic.

---

## Cross-references

- `KTPAntiCheat/docs/INTEGRATION_PLAN.md` — Tier 2 AntiCheat integration tests must assert against this contract.
- `KTPInfrastructure/scripts/README.md` — paramiko fleet patterns Tier 1 load-smoke and Tier 2 deploy-verification will reuse.
- `KTPAmxxCurl/scripts/check_logs.py` — reference paramiko-tail pattern for Tier 3 log ingest.
- `KTPInfrastructure/monitoring/ktp-server-monitor.py` — existing monitoring daemon; Tier 3 telemetry daemon should co-locate and share config.
- `KTPInfrastructure/monitoring/fps_baselines/fleet_fps_2026-04-23_pre-jit.json` + `fleet_fps_2026-04-25_post-jit.json` — pre/post-JIT baselines (127k + 138k samples) for Tier 3 profile comparison + rollup validation.
- `/opt/ktp-profile-aggregator/` (data server) — actually-shipped aggregator daemon, private repo. Tier 3 rollup + alerting layer goes on top of its `ktp_telemetry_metrics` table.
