# Changelog

All notable changes to KTP Infrastructure will be documented in this file.

## [1.5.30] - 2026-07-10

### ktp-perf-rollup: retire the stale NY5 default exclusion

NY5 (74.91.123.64:27019) was still excluded from WARN evaluation and the
fleet median despite the operator clearing `PERF_EXCLUDED_HOSTS=""` in
`/etc/ktp/discord-relay.conf` on 2026-05-13 (when NY5 retired from
pingboost-4 canary duty back to fleet config). Root cause: `resolve()`
`or`-chains env → config → default, so an explicitly-empty config value is
falsy and silently falls back to the baked-in default — which still carried
the canary-era `74.91.123.64:27019`.

- `DEFAULT_EXCLUDED` now empty; NY5 participates in WARN evaluation and the
  fleet median like every other instance.
- Docstring/usage text updated; static embed "Source" footer no longer
  claims the NY5 exclusion.
- Tripwire comment on `resolve()` documenting the empty-value-cannot-override
  footgun (keep defaults empty wherever `""` is a valid config value).

## [1.5.29] - 2026-07-07

### Assessment fix waves — Buckets 1-6 of the 2026-07-07 full-surface review

Five parallel ktp-code-review agents swept the whole repo (provision/deploy,
fleet-ops scripts, data-server services + monitoring, Tier-2 harness + CI,
docs + public-hygiene); ~100 findings triaged into six buckets, fixed, each
batch re-reviewed pre-commit. Highlights (full detail in the commit messages
+ `CODE_ASSESSMENT_2026-07-06_WAVE2.md` § KTPInfrastructure in the root):

- **`d6cba1c` (Buckets 1-3):** atomic restart-script deployer
  (`deploy-restart-script.py`); discord.ini surfaces unquoted + full parser
  key union (quoted values were parser-toxic); CI gate holes closed (tier2
  filter covers `tests/smoke/`; harness unit tests wired into config-tests);
  July-LAN blockers — HLTV_API_KEY plumbed end-to-end, LAN HLTV runtime
  converged to the production systemd/FIFO/v2.2-API shape with always-on
  `record auto_lanN` configs, lan-deploy preflights, config/lan profiles
  rebuilt for extension mode, gen_pw pipefail-safety (silent exit-141 fix).
- **`fd9dd14` (Bucket 4):** fleet-health total-outage blindness fixed
  (execution-verified); renamer h2-mislabel + torn-line fixes; renamer-death
  interlock trio (OnFailure= + CRITICAL_SERVICES + cleanup guard); failed
  relay POSTs now retry instead of counting as delivered (health check,
  crashreporter, perf-rollup); deploy.py quarantine lifted (.new staging,
  config-overwrite guards, relay auth); backup prune gated on dump success
  (with pipefail); harness integrity (zero-row asserts fail, truncation
  matcher, fail-on-warning grep, extension-mode modules test, lan profile
  added to config tests, rotation-aware log tail).
- **`d65235e` (Bucket 5):** repo-vs-fleet drift refresh — expected-binaries
  at the live .927/2.7.20/1.3.13 baseline; CPU maps corrected to the actual
  fleet placement (2,5,4,3,7); THP never + tmpfiles.d + watchdog=0 + tc
  qdisc in provisioning; restart-script pinning on fixed port-keyed maps;
  `.example` lineages regenerated from canonical/deployed; deploy-to-fleet
  per-host port lists (CHI 27019).
- **Bucket 6 (this entry's commit):** staleness banners on TECHNICAL_GUIDE +
  DEVELOPMENT_HISTORY (+ unlag retraction note, AC-mention trims, literal
  pre-rotation password dropped); TECHNICAL_GUIDE's HLTVRecorder section
  marked superseded by the 1.7.0 always-on architecture; renamer docs
  corrected from the retired 7-day cleanup numbers to the real 30-min/6h
  sweep; README extension-loader path fixed (`dod/addons/`, not `rehlds/`);
  DEPLOYING.md no longer sends incident responders to the disabled Netdata;
  Denver "(test)" labels retired; UBUNTU_OPTIMIZATION superseded banner;
  BUILDING/CI_SETUP/test-doc/comment-drift sweep; this CHANGELOG backfill.

## [1.5.28] - 2026-07-06 (backfill — recorded 2026-07-07)

### June-July commits that predated this entry

- `3334275` provision: `.gitattributes` (sh=lf) + sanitized
  clone-ktp-stack.sh.example (the committed, secret-free template)
- `03e7655` lan-web: admin publish-gating for polls + Sat/Sun
  schedule/bracket (pre-event wipe workflow)
- `97a0c56` scripts: canonical ktp-ac-retention (uploads 60d, weapon rows
  30d batched deletes, token purge) — behavior-bearing: the retention cron
  the data server runs
- `5c4a264` provision: clone-ktp-stack fails loudly when no HLTV API key is
  available (behavior-bearing: fresh boxes no longer silently ship an
  unauthenticated recorder)
- `fbc8782` scripts: drop stale ktp-fleet-health.sh duplicate; renormalize
  sh eol to LF
- `674add1` tier2: un-skip the five bot-gated DODX forward tests via the
  KTPAMXX 2.7.19+ dispatch primitives (spawn/team/class/death/flush)
- Plus the June lan-web wave + Ubuntu 26.04 provision support commits
  between 1.5.27 and the above.

## [1.5.27] - 2026-06-06

### `provision` + `docs`: LAN box supports 6 servers, dynamic core pinning, custom-map deploy fix, TeamSpeak

#### Provision changes

**1. 6 game servers end-to-end.** `install-linuxgsm.sh` now honors `NUM_INSTANCES` (env or arg 2, default 5) and generates the monitor crontab per instance instead of a hardcoded 5-line block; `lan-deploy.sh` forwards the count to it. `HLTV_BASE_PORT` defaults to `BASE_PORT+NUM_INSTANCES` (27021 for 6 servers) so HLTV no longer collides with a 6th game server at 27020.

**2. Dynamic CPU pinning + under-provision alert.** `provision-gameserver.sh` detects the real core count and pins one game server per CPU from CPU 2 up (cores 0,1 reserved for OS/IRQ/HLTV/TeamSpeak), adapting to whatever chip the box has. If a host has fewer usable cores than servers, it prints a loud warning (and prompts unless `YES=1`) that servers will share cores. `isolcpus`/`nohz_full`/`rcu_nocbs` now derive from the actual game-CPU set. The proven cloud-fleet 4c/8t map (8 CPUs, ≤5 servers) is preserved byte-for-byte — no production drift.

**3. Custom-map/overview deploy gap fixed.** `lan-deploy.sh` never passed `--dod-base` to `clone-ktp-stack.sh`, so custom KTP maps, command-map **overviews**, WADs and `ktp_*.cfg` were left off the game servers (Steam provides stock content only). Added `DOD_BASE_PATH` config key, wired into the orchestrator and surfaced in the run summary. This is the historical "left out the maps/overviews folder" bug.

#### Doc changes

**1. Cross-referenced the two LAN docs.** `docs/LAN_SETUP.md` (operational guide) and `provision/LAN-DEPLOY.md` (automated `lan-deploy.sh` install) now link to each other with clear, non-overlapping roles. README and `DEPLOYMENT_TARGETS.md` now point at the orchestrator as the primary LAN install path (previously only the older manual `provision-lan-dataserver.sh` was referenced; `LAN-DEPLOY.md` had no inbound links).

**2. Both docs brought current with the July 2026 all-in-one plan.** One box runs game servers + HLTV + TeamSpeak for up to 72 players (12 teams × 6). Hardware row added (8–12 cores, 32GB, 2× SSD, x86-64 only — i386 multilib rules out ARM); Ubuntu 24.04 noted alongside 22.04.

**3. TeamSpeak Voice Server section.** Native Linux amd64 server install (user, download, license-accept, first-run admin token, `ts3server` systemd unit), UFW ports (9987/udp, 30033/tcp, 10011/tcp LAN-only), the free 512-slot non-commercial license required for 72 players, channel layout, troubleshooting, offline-USB staging, and day-of checklist items.

**4. Open item flagged in both docs:** plan calls for 6 concurrent game servers; `install-linuxgsm.sh` still creates 5. 6th instance + HLTV/ports to settle before the event.

## [1.5.26] - 2026-05-31

### `scripts` + `tests`: AC alternate-hash allowlist, match-flow coverage, orphan-demo cleanup

#### Changes

**1. `build-game-files-manifest.py`: operator-curated `ALTERNATE_HASHES`.**

The four KTP league score-event ambient sounds (`alliescap`/`alliesscore`/`axiscap`/`axisscore`.wav) ship a community-standard replacement set that predates the AC — present on the operator's own machine and every player bundle in the corpus. Without an allowlist they surfaced as 4 file-integrity false positives on every legitimate player. The manifest now records the accepted alternate hash per file; the AC client (0.5.2+) treats a mismatch that matches an alternate as clean. Hashes only — no canonical Valve hash removed.

**2. `tests/integration`: match-flow Discord + log-event coverage.**

New `test_match_flow_discord.py` + expanded `test_match_flow_logs.py` / `match_flow.py` assertions exercise the Discord-relay fan-out and the KTP_MATCH_* log emissions end-to-end against the test-mode binary.

**3. `scripts/ktp-orphan-cleanup`: daily orphan-demo prune.**

`/etc/cron.daily/` script deleting `auto_*.dem` HLTV captures >7d old that fell outside any match window (no `ktp_match_start`, so the renamer left them unattributed). Past the renamer's 4h abandon-window; unattributed captures carry no `match_id` to retrieve by.

#### Verification

- AST/`pytest --collect-only` clean; no secrets in committed files (fleet-credential helper scripts kept local via `.gitignore`).

## [1.5.25] - 2026-05-06

### `tests`: Tier 2 first-fire follow-ups — bot-AI test skips + version-pin sync

First end-to-end Tier 2 run on the newly-registered self-hosted runner produced 29 PASS / 10 FAIL / 3 SKIP (47 collected). Of the 10 failures, 9 traced to two distinct root causes both fixed in this commit + companion KTPMatchHandler 0.10.131. The 10th was a stale version pin in test_match_flow_spine.py (also fixed below).

#### Changes

**1. Bot-AI-dependent tests skip-marked (5 tests, Class A).**

`tests/integration/test_dodx_forward_firing.py:test_dod_client_spawn / changeteam / changeclass / client_death / dod_stats_flush_fires_on_match_end` all rely on `addbot` rcon producing a connected player that picks a team and spawns. Reality: DoD itself ships **no bot AI**, and production game servers don't run bots. `addbot` creates a fake-client slot but the client never spawns into a team without an external bot DLL. Without that, the witness events never fire and the tests timeout at 10s.

Skip-marked with a clear `BOT_AI_REQUIRED_REASON` constant explaining the gap and how to re-enable (install a DoD bot AI mod into the test serverfiles tree). Deterministic-dispatch test natives (Phase 3+) still cover the dispatch primitive without requiring a real player chain — the 6 non-bot tests in this file (`controlpoints_init`, `client_damage`, `grenade_explosion`, `client_score_event`, `dod_score_event`, `control_point_captured`) all PASSED in the first run.

**2. Version pin synced to 0.10.131 (Class C, trivial).**

`tests/integration/test_match_flow_spine.py:42`: `EXPECTED_KTPMATCHHANDLER_VERSION` bumped 0.10.130 → 0.10.131 to match the new test-mode binary that includes the score-propagation + log_message-mirror fixes (see KTPMatchHandler 0.10.131 CHANGELOG).

#### Companion fixes outside this repo

Classes B (score propagation, 3 tests) and D (log_message dir mismatch, 1 test) live in KTPMatchHandler test-mode rcons — fixed in KTPMatchHandler 0.10.131 commit. Production binary unaffected.

#### Verification

- `pytest --collect-only`: 47 tests, 0 errors (regression-clean post-skip-marks)
- AST parse: clean
- Test-mode binary recompiled (md5 `f1b21414…`); restaged to `/opt/ktp-tier2-runner/serverfiles/...`

#### Expected post-fix Tier 2 run

| Outcome | Pre-fix | Expected post-fix |
|---|---|---|
| PASSED | 29 | 33 (29 + 3 score tests + 1 log_message + 1 version pin = 34, but bots stay skipped so net +5) |
| FAILED | 10 | 0 (5 bot tests now skip; 4 + 1 fixed) |
| SKIPPED (intentional) | 3 | 8 (3 prior + 5 bot-AI) |
| Total | 47 | 47 (all 47 either pass or have documented-skip reason) |

Estimate: 33 PASSED / 0 FAILED / 8 SKIPPED + ≤2 reruns on flaky timing — **green Tier 2** depending on environmental noise.

#### Files changed

- `tests/integration/test_dodx_forward_firing.py` — 5 `@pytest.mark.skip` decorators + `BOT_AI_REQUIRED_REASON` constant + 14-line explanatory comment block
- `tests/integration/test_match_flow_spine.py` — `EXPECTED_KTPMATCHHANDLER_VERSION` 0.10.130 → 0.10.131
- `CHANGELOG.md` — § 1.5.25

#### Cross-references

- KTPMatchHandler 0.10.131 (companion commit; Class B + Class D fixes)
- 1.5.24 — review-fix follow-ups from the original stack review (now stale on the bot-AI assumption)
- Tier 2 first-fire run 25454115479 (the failing baseline these fixes correct)

---

## [1.5.24] - 2026-05-06

### `tune`: Tier 2 / spike-digest deferred refinements (4 of 6 from review)

Closes 4 of the 6 deferred items filed as TODO #28 after the 1.5.18-1.5.23 ktp-code-review pass. Remaining 2 items (KTPAdminBot bucket Choice gate + 500ms-1s color severity) shipped in the companion KTPAdminBot 0.9.2 commit.

#### Changes

**1. `tests/integration/conftest.py` — pytest_sessionstart hook for forward-compatible duration calculation.**

Previously `pytest_sessionfinish` read `terminalreporter._sessionstarttime` (a private attribute) with `getattr(reporter, "_sessionstarttime", time.time())`. The fallback silently returned `time.time()` (= zero duration in the embed) if the private attribute name ever changes in a future pytest release. Replaced with a `pytest_sessionstart` hook that records `time.time()` on `session.config._ktp_session_start`, which `pytest_sessionfinish` reads. Forward-compatible against pytest API drift; defensive `None`-fallback preserves the no-crash behavior if `pytest_sessionstart` somehow doesn't fire.

**2. `scripts/post-tier2-result.py` — `failures_field` truncation order fix.**

Earlier ordering applied the 1024-char cap AFTER appending the "…and N more" sentinel, leaving a theoretical hole if 5 long node IDs (>200 chars each, e.g. deeply parameterized fixtures) blew past the cap before the check ran. New order: format the line block, char-cap to 990 (reserving 30 chars for the sentinel + safety), THEN append "…and N more", THEN belt-and-suspenders absolute 1020-char cap. No production exposure on current test IDs (~85 chars each), but hardens against future parameterized test refactors.

**3. `scripts/ktp-spike-digest.py` — logged warning on uncalibrated red threshold.**

Red-tier color was triggered by `count > 1000` for any fingerprint, set without production calibration during 1.5.23 deploy. Threshold may be too tight (false-red on noisy steady state) or too loose (silent on real fleet event). Added `logging.warning` on first fire so the operator sees a calibration opportunity rather than a quiet alert. Threshold itself unchanged — adjusted by future commit after ~1-2 weeks of production data.

**4. `scripts/ktp-data-server-health.sh` — KTP canonical colors.**

Embed used raw hex `color=65280` (pure green) and `color=16711680` (pure red) instead of KTP brand colors. Other embeds (perf-rollup, crashreporter, soak-verify) all use `5763719` (KTP green) / `15548997` (KTP red). Aligning so data-server-health visually matches the rest of the alert flow in #ktp-crashes. Replaced raw hex with named bash variables (`KTP_GREEN` / `KTP_RED`) for the same reason.

**Plus a companion review-fix amend on 1.5.23** (deployed in this session): added a clarifying comment in `ktp-spike-digest.py:open_mysql` explaining the MySQL session TZ inheritance from `SYSTEM` (= `America/New_York` via the data server's `TZ` env). Reviewer flagged a Critical TZ-mismatch concern that turned out to be incorrect — pymysql does NOT default to UTC session TZ; it inherits whatever the server has set (`SYSTEM` in this case). Verified live with dual queries confirming naive ET datetime params return identical 11-row count via mysql CLI and pymysql. Comment prevents future maintainers from worrying about the same false alarm.

#### Verification

- pytest --collect-only: 47 tests collect cleanly (regression-free)
- AST parse all 4 modified files: clean
- `ktp-data-server-health.sh` test invoke: "no transitions" — script runs clean post-color-change
- `ktp-spike-digest --dry-run` for today: 5 top + 10 new fingerprints across 4 phases, color correctly yellow (no row exceeds the 1000 threshold; the new logged warning would have fired if any did)

#### Operator deploy (executed 2026-05-06 14:07 ET)

- `/usr/local/bin/ktp-spike-digest` — updated; cron picks up at next 05:00 ET fire
- `/usr/local/bin/ktp-data-server-health.sh` — updated; hourly cron picks up next fire
- Test invoke confirmed both run clean

Backups at `<live-path>.bak-20260506-1407XX-deferred-fixes`.

#### Two items NOT in this commit

- KTPAdminBot bucket Choice gate (Suggestion #5 from review) — shipped as KTPAdminBot 0.9.2
- KTPAdminBot 500ms-1s color severity bump (Warning #6) — shipped as KTPAdminBot 0.9.2

#### Cross-references

- 1.5.18-1.5.23 — the stack reviewed
- TODO.md #28 — original deferred-refinements task (now resolved)
- KTPAdminBot 0.9.2 (companion commit) — bucket Choice + severity bump

---

## [1.5.23] - 2026-05-06

### `feat`: Tier 3 Project 3 — daily digest cron + per-fingerprint alert hook

Closes the next-phase items filed in 1.5.20: aggregator-side immediate-alert on never-before-seen fingerprints + a separate daily-digest cron that rolls up the full day's signature activity. Project 3 is now operationally complete (modulo the AdminBot `/ops spikes-by-fingerprint` command, which is its own task).

#### Schema migration (live on data server)

Added `posted_alert TINYINT(1) NOT NULL DEFAULT 0 AFTER sample_line` + `KEY idx_posted_alert (posted_alert)` to `ktp_spike_signatures`. Backfill suppression: one-shot `UPDATE ktp_spike_signatures SET posted_alert=1 WHERE posted_alert=0` ran post-ALTER (2 rows updated — the existing READ:0-5ms + STEAM:0-5ms from the first post-deploy cycle). New rows from this point forward default to `posted_alert=0` and trigger an alert on next aggregator cycle.

Canonical DDL in `scripts/spike_signatures.py:DDL_SIGNATURES` updated to include the new column + index — fresh installs apply the right schema via `CREATE TABLE IF NOT EXISTS`. Vendored copy in KTPProfileAggregator updated to match (sync md5 d73ec76a…).

#### Aggregator alert hook (KTPProfileAggregator commit, separate)

New cycle-level alert step in `aggregator.py`:
- After all per-server `write_metrics_and_watermark` calls in a cycle, the union of fingerprints observed across all servers is collected
- `find_unposted_fingerprints` SELECTs rows where `fingerprint IN (cycle's set) AND posted_alert=0`
- Per row: `build_alert_embed` formats a yellow heads-up embed (title `🆕 New spike fingerprint: PHASE:BUCKET`, fields for phase + bucket + sample log line + count, footer "alert fires once per fingerprint")
- `post_alert_embed` POSTs via the relay using same conventions as `ktp-perf-rollup` and `post-tier2-result` (`X-Relay-Auth` header, channel-id payload)
- On 2xx response: `UPDATE ktp_spike_signatures SET posted_alert=1 WHERE fingerprint=%s` per row, so a relay failure mid-batch doesn't lose track

Gated by `SPIKE_ALERTS_ENABLED` env var (default `0` — safety net so a misconfigured deploy doesn't flood `#ktp-crashes` with historical fingerprints). Relay creds via `RELAY_URL` + `AUTH_SECRET`. Channel default `1497957091107668070` (#ktp-crashes — same as `PERF_ALERT_CHANNEL`); override via `SPIKE_ALERT_CHANNEL`.

Smoke-tested 4 short-circuit paths locally (disabled flag, missing creds, empty fingerprint set) + the embed-shape (sample line correctly truncated, all fields present).

#### Daily digest cron (this repo)

`scripts/ktp-spike-digest.py` (~250 LOC) reads `ktp_spike_signatures` for a target day window and posts a Discord embed summarizing:
- **Top fingerprints** (top 5 by all-time count, `last_seen` in target day) — what's chronically active
- **New fingerprints** (first 10 with `first_seen` in target day) — never-before-seen patterns; cross-checks the alert hook (any "alert NOT posted" sentinel here means the alert was suppressed somehow)
- **Daily totals by phase** — sum of `count` per phase across all fingerprints active in the day, in canonical order (READ/PHYS/STEAM/SEND/POST/MISC1)

Color ladder: green (steady-state only), yellow (any new fingerprints — heads-up), red (any single fingerprint count >1000 in one day — fleet anomaly).

CLI mirrors `ktp-perf-rollup`: `--day YYYY-MM-DD` (default = yesterday server-local), `--dry-run`, `--config`. Reads relay creds + channel from `/etc/ktp/discord-relay.conf` (new optional key `SPIKE_DIGEST_CHANNEL`, defaults to `#ktp-crashes`).

Cron: `scripts/cron.d/ktp-spike-digest-daily` fires at 05:00 ET daily — after the 04:30 ET ktp-perf-rollup so today's digest reads yesterday's complete fleet data. Reuses the `ktp-profile-aggregator` venv (pymysql lives there; sharing avoids maintaining a second venv).

#### Verification

Aggregator restarted on data server 2026-05-06 11:59:14 EDT (PID 838865 → 839407). First post-restart cycle clean: `cycle complete in 3.7s: 24/24 servers reported, 0 silent, 0 alerts` (correct — alerts disabled by default).

Digest dry-run for today (with 13 spike occurrences captured by aggregator across the day so far):
- 5 top fingerprints + 5 new fingerprints surfaced
- Phase distribution: READ 8 / PHYS 2 / STEAM 2 / SEND 1
- **Notable**: `PHYS:100-250ms` from DAL5 — a real meaningful regression event (single occurrence today, but the magnitude bucket 100-250ms is significant). Would have triggered an alert if the hook were enabled.

#### Operator deploy steps

Schema migration: ✅ already executed.
Aggregator restart: ✅ already executed (still with `SPIKE_ALERTS_ENABLED=0`).
Digest script + cron: ✅ deployed live (md5 `a538f185…`); first auto-fire 2026-05-07 05:00 ET.

**To enable per-fingerprint alerts** (operator-driven, deferred-by-default):
1. Add `SPIKE_ALERTS_ENABLED=1` to `/opt/ktp-profile-aggregator/.env` (or to `/etc/ktp/discord-relay.conf` if RELAY_URL+AUTH_SECRET aren't already set per-aggregator).
2. `systemctl restart ktp-profile-aggregator`
3. Watch `journalctl -u ktp-profile-aggregator -f` for "spike alert posted: …" lines.
4. If a flood appears (shouldn't happen — historical backfill was suppressed), `systemctl stop ktp-profile-aggregator` + `UPDATE ktp_spike_signatures SET posted_alert=1 WHERE posted_alert=0` + restart.

#### Files changed (this repo)

- `scripts/spike_signatures.py` — DDL_SIGNATURES updated with `posted_alert` column + index
- `scripts/ktp-spike-digest.py` — new file (~250 LOC)
- `scripts/cron.d/ktp-spike-digest-daily` — new file (cron entry)
- `CHANGELOG.md` — § 1.5.23

KTPProfileAggregator (separate commit):
- `aggregator.py` — alert hook (~120 LOC: 4 new helper functions + cycle-loop integration)
- `spike_signatures.py` — vendor re-sync to match canonical DDL update
- `.env.example` — new `SPIKE_ALERTS_ENABLED` / `SPIKE_ALERT_CHANNEL` / `RELAY_URL` / `AUTH_SECRET` keys

#### Cross-references

- 1.5.20 — Project 3 aggregator wiring (parser + DDL + UPSERT — what this builds on)
- 1.5.22 — Tier 2 reporting embed (parallel reporting pattern using same relay)
- KTPProfileAggregator commit (separate repo) — the alert-hook code itself

---

## [1.5.22] - 2026-05-06

### `feat`: Tier 2 post-run Discord reporting embed (Session 5 sub-followup closed)

Closes the "post-run reporting Discord embed" piece deferred in 1.5.19's CHANGELOG. Pytest writes a session-summary JSON via a new `pytest_sessionfinish` conftest hook; CI workflow reads it after pytest and POSTs a Discord embed via the relay.

#### What landed

**Conftest hook** (`tests/integration/conftest.py:pytest_sessionfinish`):

- Triggered iff `KTP_TIER2_REPORT_PATH` env var is set — preserves the dev-loop's "no extra files written" behavior. CI workflow sets it to `tier2-report.json` at job-env scope.
- Pulls counts from pytest's `terminalreporter.stats`: `passed`, `failed`, `skipped`, `errors`, `rerun`, plus failed-test node IDs (full pytest IDs like `tests/integration/test_match_flow_spine.py::test_3_setup_match_enters_prestart`).
- Writes JSON. Best-effort error handling — a write failure surfaces as a yellow warning line in pytest output but does NOT fail the session (the run's pass/fail status is the load-bearing signal).

**Helper script** (`scripts/post-tier2-result.py`, ~250 LOC):

- Reads the JSON, builds a Discord embed with green/red color ladder, formats a "Failed tests (N)" field with first 5 IDs + truncation sentinel for longer lists (Discord 1024-char field-value cap).
- Title: `KTP Tier 2 Integration — GREEN/RED (Np / Mf / Ks)` plus `/ Eerr` if any errors.
- Description includes total test count, runtime, branch + commit-short-SHA, and a clickable run-details link to GitHub Actions.
- Footer: `tier2-integration · <exitstatus> exit · N rerun(s)`.
- Reads relay creds from `/etc/ktp/discord-relay.conf` (same conf as `ktp-perf-rollup`). New optional key `TIER2_REPORT_CHANNEL` overrides the default channel; default is `1498813261263405097` (scheduled-report channel — same destination as perf-rollup + canary embeds + RemoteTrigger reports).
- `--dry-run` flag prints embed JSON to stdout without POSTing — useful for local verification + CI step debugging without spamming Discord.
- Same exit-code convention as `ktp-perf-rollup`: 0 success, 1 input invalid, 2 missing creds, 3 relay non-2xx.

**Workflow integration** (`.github/workflows/tier2-integration.yml`):

- Added `KTP_TIER2_REPORT_PATH: tier2-report.json` to job env.
- New `Post Tier 2 result embed to Discord` step with `if: always()` runs after pytest. Wrapped in `|| true` semantically — a relay failure logs a warning but does NOT fail the workflow (a test regression is the load-bearing signal, not a transient relay hiccup).
- New `Upload Tier 2 report JSON (always)` artifact step preserves the JSON for 14 days alongside the Allure bundle. Useful for post-mortem correlation even after the embed has scrolled out of Discord.
- Self-hosted runner is on the data server so `/etc/ktp/discord-relay.conf` is readable directly — no GH Actions secrets needed for relay creds.

#### Smoke-tested 3 report shapes locally

All `--dry-run` invocations rendered correctly:

| Shape | Title | Color | Failures field |
|---|---|---|---|
| GREEN (47p/0f/8s) | "GREEN (47p / 0f / 8s)" | green | (omitted) |
| RED (42p/3f/8s/1err) | "RED (42p / 3f / 8s / 1err)" | red | 4 IDs listed |
| MANY (12 fails) | "RED (30p / 12f / 5s)" | red | 5 IDs + "…and 7 more" sentinel |

Truncation sentinels work; embed stays under Discord's 1024 field-value cap.

### `ops`: ktp-data-server-health alerts re-routed to #ktp-crashes

`scripts/ktp-data-server-health.sh:22` default channel changed from `1498813261263405097` (scheduled-report channel) to `1497957091107668070` (#ktp-crashes). Reverses the May 3 "dedicated #ktp-data-server-health channel" decision per operator preference 2026-05-06.

Rationale: data-server-health alerts (services dying, HLTV instance count drop) are crash-class signals — they belong alongside crashreporter + perf-rollup alerts in `#ktp-crashes` rather than mixed with the broader scheduled-report stream. Mirrors the same consolidation perf-rollup did earlier (`PERF_ALERT_CHANNEL="1497957091107668070"` already in the conf file).

`ALERT_CHANNEL` env-var override still works for runtime routing experiments. Backup of pre-change script at `/usr/local/bin/ktp-data-server-health.sh.bak-20260506-104907`. New live md5 `c7dfb1fb…`. Verified script runs cleanly post-deploy (no transitions to alert on at the moment).

#### Files changed

- `tests/integration/conftest.py` — added `pytest_sessionfinish` hook + 3 new imports (json, time, Path)
- `scripts/post-tier2-result.py` — new file (~250 LOC), helper script + embed builder
- `.github/workflows/tier2-integration.yml` — `KTP_TIER2_REPORT_PATH` env, post-pytest embed step, JSON upload step
- `scripts/ktp-data-server-health.sh` — `ALERT_CHANNEL` default updated + comment refreshed
- `CHANGELOG.md` — § 1.5.22

#### Operator deploy step

Tier 2 reporting: lands automatically on next workflow trigger (no separate deploy — the workflow YAML + helper script + conftest are all in-tree). Optional: add `TIER2_REPORT_CHANNEL=<id>` to `/etc/ktp/discord-relay.conf` if a dedicated `#ktp-tier2` channel is preferred over the default scheduled-report channel.

Data-server-health: deployed to data server 2026-05-06 10:49 ET (verified via test invoke). Next hourly cron fire on a transition lands in #ktp-crashes.

#### Cross-references

- 1.5.19 — original Session 5 finishing (deferred this reporting embed as sub-followup)
- 1.5.21 — perf-rollup FPS-floor refinement (concurrent change in same session)
- TODO.md § Tier 2 — closes the "Tier 2 post-run Discord reporting embed" sub-followup line
- Memory `scheduled_report_channel.md` — channel routing convention

---

## [1.5.21] - 2026-05-06

### `tune`: ktp-perf-rollup FPS-side absolute-drop floor (suppress sub-1-fps boundary alerts)

The 2026-05-06 second-fire data showed the same Gaussian-vs-tight-σ false-positive pattern that bit DAL3 on the spike side, but on the FPS side this time. Two hosts (DAL1 σ=0.3 fps, DAL4 σ=0.2 fps) had per-host σ tight enough that a sub-1-fps drop technically passed 2σ even though the actual delta was player-imperceptible (~0.05% throughput).

Original 2σ-only rule on 2026-05-05 data:
- NY3 fps 973.2 < 978.7 (μ 979.5 σ 0.4) → drop = 6.3 fps (0.64%) → real signal ✓
- DAL1 fps 980.2 < 980.2 (μ 980.7 σ 0.3) → drop = 0.5 fps (0.05%) → boundary noise ✗
- DAL4 fps 978.7 < 978.8 (μ 979.1 σ 0.2) → drop = 0.4 fps (0.04%) → boundary noise ✗

Filed in 1.5.18's CHANGELOG as a "low-priority follow-up" — the alerts were dismissable, just noisy. Filed as a TODO immediately after.

#### Fix shipped (1.5.21)

Added an absolute-drop floor that gates the 2σ trigger:

```python
sigma_breach = fps_today < (mean - FPS_SIGMA_THRESHOLD * stddev)
drop_fps = mean - fps_today
drop_pct = drop_fps / mean
magnitude_meaningful = drop_fps >= FPS_MIN_DROP_FPS or drop_pct >= FPS_MIN_DROP_PCT
warn_fps = sigma_breach and magnitude_meaningful
```

Defaults: `FPS_MIN_DROP_FPS = 1.0`, `FPS_MIN_DROP_PCT = 0.001` (0.1%). Lenient OR keeps the floor sensitive on lower-fps hosts (Chicago at 967 fps where 1 fps is already 0.1%) without producing tight-σ noise on near-1000-fps baremetals.

Validation: re-replayed `--day 2026-05-05 --dry-run` against deployed 1.5.21:

```
findings: 24 hosts; warn=1; fleet_median_fps=978.6
title: WARN — 2026-05-05
hosts in WARN (1): NY3 (74.91.123.64:27017) — fps 973.2 < 978.7 (μ 979.5 σ 0.4)
```

Down from 3 WARN (NY3 + DAL1 + DAL4 → "CRITICAL (partial fleet)" tier) to 1 WARN (NY3 → standard WARN tier). DAL1 + DAL4 boundary alerts suppressed as intended. NY3's real signal preserved. Embed Source-field text updated to `fps 2σ + ≥1 fps floor / spike 2.5σ thresholds` so operators see the gating logic in the alert itself.

#### Files changed

- `scripts/ktp-perf-rollup.py`:
  - Added `FPS_MIN_DROP_FPS` + `FPS_MIN_DROP_PCT` constants with the validation table inline as a docstring (NY3/DAL1/DAL4 row-by-row).
  - Replaced the simple `if today < baseline` WARN test with the two-condition gate.
  - Updated embed Source field text to include the floor in the threshold description.
- `CHANGELOG.md` — § 1.5.21

#### Operator deploy step (executed 2026-05-06 10:39 ET)

```bash
# Already done — recorded for repeatability:
scp scripts/ktp-perf-rollup.py root@74.91.112.242:/usr/local/bin/ktp-perf-rollup
ssh root@74.91.112.242 chmod 755 /usr/local/bin/ktp-perf-rollup
```

Live at md5 `14914a8b…` on data server. Backup of pre-fix script at `/usr/local/bin/ktp-perf-rollup.bak-20260506-103910`. Cron unchanged — picks up the new script at next 04:30 ET fire.

#### Cross-references

- 1.5.20 — Tier 3 Project 3 spike-categorizer (separate concurrent change in same session)
- 1.5.18 — `--dry-run` lift + filing of this follow-up
- 1.5.17 — initial spike-side 2σ → 2.5σ tune (same false-positive class, different metric)

---

## [1.5.20] - 2026-05-06

### `feat`: Tier 3 Project 3 — spike-categorizer aggregator wiring

Closes the open "Aggregator wiring (~3-4h, NEXT)" item from the Project 3 spec. The canonical parser + DDL shipped 2026-05-04 (commit `abe75e8`, version 1.5.13/14 era — `scripts/spike_signatures.py` + 34 unit tests at `tests/unit/test_spike_signatures.py`); this commit wires it into the production daemon.

#### What landed

**Schema deploy** (data server, idempotent — `CREATE TABLE IF NOT EXISTS`):

```
ktp_spike_signatures (
  fingerprint      VARCHAR(64) NOT NULL PRIMARY KEY,
  phase            VARCHAR(16) NOT NULL,
  magnitude_bucket VARCHAR(16) NOT NULL,
  first_seen       TIMESTAMP   NOT NULL,
  last_seen        TIMESTAMP   NOT NULL,
  count            INT         NOT NULL DEFAULT 0,
  sample_endpoint  VARCHAR(48) NOT NULL,
  sample_line      TEXT        NOT NULL,
  KEY idx_last_seen (last_seen),
  KEY idx_phase_bucket (phase, magnitude_bucket)
)
```

Applied as MySQL root on the data server. `ktp_telemetry@localhost` granted `SELECT, INSERT, UPDATE` on the new table; FLUSH PRIVILEGES applied. Verified post-deploy via `SHOW CREATE TABLE` + `SHOW GRANTS`.

**KTPProfileAggregator wiring** (companion repo — separate commit there):

- Vendored `spike_signatures.py` from `KTPInfrastructure/scripts/` to `KTPProfileAggregator/` as a sibling of `aggregator.py`. Header comment documents the canonical home + sync md5 (`4b96d608c2139f0323fbfde913008fdb` as of vendor date 2026-05-06).
- Added `RE_SPIKE_UMBRELLA` regex to match `[KTP_SPIKE]` umbrella lines (timestamp prefix only — full structural parse still goes through `parse_spike_line`).
- New `SignatureOccurrence` dataclass aggregates first/last/count/sample-line per fingerprint within a single server's cycle.
- `CycleResult` extended with `signatures: dict[str, SignatureOccurrence]` field.
- `aggregate_lines()` extended with a third match arm for umbrella lines, populating signatures dict.
- New `write_signatures()` function does an `INSERT ... ON DUPLICATE KEY UPDATE` for each fingerprint, incrementing count + advancing last_seen on collision while preserving first_seen + sample.
- `write_metrics_and_watermark()` calls `write_signatures()` after the metrics insert (separate transaction-scope so a malformed signature row doesn't roll back metrics).
- Per-cycle debug log line extended with `signatures=N` count.
- README updated: new vendor file in `Files` table, new GRANT in `Required MySQL grants`, new schema-deploy snippet in `Schema` section.

**Smoke test** (no SSH, no real DB): exercised `aggregate_lines()` against 5 sample log lines covering FPS / per-phase spike / 2× same-fingerprint umbrella / 1× distinct-fingerprint umbrella. Confirmed:

- FPS samples + per-phase spike counts unchanged from pre-wiring (`spikes={'PHYS': 0, 'READ': 1, 'STEAM': 0, 'SEND': 0}`)
- Two unique fingerprints captured: `READ:0-5ms` (count=2, first/last spanning the two same-fingerprint lines) + `STEAM:5-10ms` (count=1)
- Window aggregation expanded to include umbrella-line timestamps
- The STEAM-dominated umbrella line had no companion `[KTP_SPIKE_STEAM]` per-phase line — exactly the gotcha called out in the spike_signatures docstring; categorizer caught it.

#### Service restart held

Aggregator daemon on data server is still running 1.5.x without the umbrella handling. Restart pending operator decision — service is `ktp-profile-aggregator.service`, restart cost is ~30s of one-cycle gap.

```bash
# When ready (operator):
scp aggregator.py spike_signatures.py root@74.91.112.242:/opt/ktp-profile-aggregator/
ssh root@74.91.112.242 systemctl restart ktp-profile-aggregator
journalctl -u ktp-profile-aggregator -f --since "1 minute ago"
# Verify first-cycle output: "wrote <endpoint>: ... signatures=N" in debug logs
# Verify rows: SELECT * FROM ktp_spike_signatures ORDER BY first_seen DESC LIMIT 10
```

#### Next-phase TODOs

- **Daily digest cron + alert hook** (~6-8h, separate followup) — script similar to `ktp-perf-rollup` reads `ktp_spike_signatures`, posts daily summary to `#ktp-crashes`. Immediate-alert hook fires inline when an INSERT (vs UPDATE) occurs — never-before-seen fingerprint is the high-signal event.
- **AdminBot `/ops spikes-by-fingerprint`** (~2-3h) — replace existing raw-line-fetch with structured fingerprint lookup. Existing `/ops spikes` stays as the count-based view.

#### Files changed

This repo:
- `CHANGELOG.md` — § 1.5.20

KTPProfileAggregator (separate repo):
- `aggregator.py` — wiring (RE_SPIKE_UMBRELLA, SignatureOccurrence, signatures dict, write_signatures, integration with write_metrics_and_watermark)
- `spike_signatures.py` — vendored copy with header comment
- `README.md` — vendor file + new GRANT + schema deploy snippet

#### Cross-references

- 2026-05-04 § "spike_signatures wedge" — original parser + DDL + 34 unit tests
- TODO.md § "KTP test infrastructure" — Tier 3 Project 3 aggregator wiring resolved
- KTPProfileAggregator commit (separate repo)

---

## [1.5.19] - 2026-05-06

### `tests`: Tier 2 finishing — `_timing` migration + Allure publish

Closes the open Session 5 finishing items from the Tier 2 test infrastructure plan. Two parallel changes:

#### `_timing` constant migration (3 files, 20 inline floats → named constants)

All remaining inline `timeout=X.0` floats in the Tier 2 suite migrated to the `_timing` module's named constants. Previously the matchhandler / discord / match-types / ac / admin-recovery test files were already on `_timing` (per 1.5.16's CI flake-hardening pass); the spine, logs, and dodx forward-firing files still had inline floats that wouldn't scale with `KTP_TEST_TIMEOUT_MULTIPLIER`. Migration:

- `test_match_flow_spine.py` — added `LOG_POLL_TIMEOUT, WITNESS_TIMEOUT` import; 4 inline floats migrated (3× `2.0` log-event waits → `LOG_POLL_TIMEOUT`; 1× `3.0` witness wait → `WITNESS_TIMEOUT`).
- `test_match_flow_logs.py` — added `LOG_POLL_TIMEOUT` import; 3 inline floats migrated (2× `5.0` log-event waits + 1× `2.0` companion-event wait → `LOG_POLL_TIMEOUT`).
- `test_dodx_forward_firing.py` — added `WITNESS_TIMEOUT, scaled` import; 13 inline floats migrated (12× `5.0`/`10.0` witness-event waits → `WITNESS_TIMEOUT`; 1× `30.0` boot/mapload wait → `scaled(30.0)` to preserve the unusual longer-than-default deadline).

Net effect: a CI runner with `KTP_TEST_TIMEOUT_MULTIPLIER=2.0` (set per workflow input or repo var) now scales every Tier 2 deadline uniformly, including these 20 sites that previously would have stayed locked at their inline values and false-failed under load. AST + `pytest --collect-only` verified all 47 tests still collect cleanly.

The original 2.0/3.0 inline values in spine were deliberately tighter than the 5.0 default; the migration consolidates to `LOG_POLL_TIMEOUT` (5.0×_M). On passing tests no behavior change; on failing tests the diagnostic delay grows by 2-3s — acceptable trade for uniform scaling.

#### Allure publish in `tier2-integration.yml`

Added `allure-pytest==2.13.5` to the runner's pip install line, `--alluredir=./allure-results` to the pytest invocation, and a new `Upload Allure results (always)` step that uploads the per-test JSON bundle on every run (pass + fail, 14-day retention). Operators download the bundle + `allure serve <unzipped-dir>` locally for the HTML report — no Allure CLI install on the runner needed.

The "post-run reporting Discord embed" piece of Session 5's spec is intentionally deferred — that needs a hook to extract pytest counts + format an embed via the relay, which is its own ~60-90 LOC deliverable. Filed as a sub-followup TODO.

#### Files changed

- `tests/integration/test_match_flow_spine.py` — import + 4 timeout sites
- `tests/integration/test_match_flow_logs.py` — import + 3 timeout sites
- `tests/integration/test_dodx_forward_firing.py` — import + 13 timeout sites
- `.github/workflows/tier2-integration.yml` — `allure-pytest` install + `--alluredir` flag + always-upload step
- `CHANGELOG.md` — § 1.5.19

#### Verification

- `pytest --collect-only` against the local checkout: **47 tests collected, 0 errors** (was already 47 pre-migration; collection contract preserved)
- AST parse of all 4 modified files: clean
- `_timing` reference count post-migration: 20 references across the 3 test files (was 0)

#### Cross-references

- 1.5.16 — initial Session 5 commit (workflow + `_timing` module + first wave of file migrations)
- TODO.md § "KTP test infrastructure" — Tier 2 still-open list updated
- Sub-followup: "Tier 2 Discord reporting embed" (filed in TODO.md)

---

## [1.5.18] - 2026-05-06

### `ops`: ktp-perf-rollup `--dry-run` lifted (Discord posts now live)

Second dry-run fire (2026-05-06 04:30:01 ET, target_day=2026-05-05) ran clean of spike-side false-positives — confirming the 1.5.17 spike threshold widening (2σ → 2.5σ) eliminated the DAL3-class boundary triggers from the first fire. Lifted `--dry-run` flag from `/etc/cron.d/ktp-perf-rollup-daily` per the original 48h-suppression protocol.

#### Verification fire findings

3 hosts WARN today, all FPS-side:

- **NY3** (74.91.123.64:27017) — fps 973.2 < 978.7 (μ 979.5 σ 0.4). **Real ~6 fps regression.** Drilled down: localized to a single 21:15-22:00 EDT window where NY3-only dropped to 818-890 fps for 9 consecutive 5-min samples while NY1/NY2/NY4 held 974-985 normal. Spike total 84 vs 12-18 on siblings (7× baseline). Pattern is transient gameplay load (12man/scrim on NY3 specifically), not a systemic regression — recovered fully by next sample, 2026-05-06 NY3 back to 979.7 fps avg post-nightly-restart. The alert correctly surfaced a real per-instance anomaly worth a brief investigation.
- **DAL1** (74.91.126.55:27015) — fps 980.2 < 980.2 (μ 980.7 σ 0.3). Sub-1-fps drop.
- **DAL4** (74.91.126.55:27018) — fps 978.7 < 978.8 (μ 979.1 σ 0.2). Sub-1-fps drop.

DAL1 + DAL4 are the same flavor as the earlier spike-side DAL3 false-positive: tight-σ hosts trigger 2σ technically while the actual fps drop is player-imperceptible (~0.05% throughput). Filed as a low-priority follow-up TODO ("FPS floor refinement") to add an absolute-drop minimum (e.g., `WARN only if fps drop ≥ 1.0 fps OR ≥ 0.1%` AND 2σ). Not blocking the lift — DAL1/DAL4-style alerts are estimated at ~1-2 false positives/week on tight-σ hosts, an acceptable noise floor in exchange for surfacing real signals like NY3.

#### Changes

- `scripts/cron.d/ktp-perf-rollup-daily`:
  - Removed `--dry-run` from the cron command line.
  - Replaced "48-hour suppression" comment block with soak-history note (recording the 1.5.17 spike-threshold tune + the 1.5.18 lift) so future operators can read the timeline.
  - Updated the inline `# --dry-run for the first 48h post-deploy` comment above the cron line to "Live (post-soak) — Discord posts enabled."

#### Operator deploy step (executed 2026-05-06 09:38 ET)

```bash
# (Already done — recorded for repeatability)
scp scripts/cron.d/ktp-perf-rollup-daily root@74.91.112.242:/etc/cron.d/ktp-perf-rollup-daily
```

cron auto-reloads `/etc/cron.d/` on file change; no `systemctl reload` needed. Verified live execution line is `--dry-run`-free; cron service active. Backup of pre-lift cron at `/etc/cron.d/ktp-perf-rollup-daily.bak-20260506-093758`.

#### Cross-references

- 1.5.17 — spike threshold widening (2σ → 2.5σ) that this 1.5.18 lift validates
- 1.5.16 — initial perf-rollup deploy
- TODO.md "FPS floor refinement" — filed follow-up tracking the DAL1/DAL4 sub-1-fps boundary case
- discord-embeds/CHANGES_SUMMARY_2026-05-08.md § "perf-rollup spike threshold tuned" — pre-lift decision rationale

---

## [1.5.17] - 2026-05-05

### `tune`: ktp-perf-rollup spike threshold 2σ → 2.5σ (Poisson-tail tolerance)

First dry-run fire (2026-05-05 04:30:01 ET) flagged **3 hosts in WARN**, triggering "CRITICAL (partial fleet)" embed (suppressed by `--dry-run` per the 48h soak protocol). Two of the three were boundary false-positives:

- **DAL3** spikes 333 vs threshold 332 (μ=200 σ=66 → 2σ=132 → threshold μ+2σ=332). 1 spike over threshold = textbook Poisson-tail false-positive.
- **DEN1** fps 973.4 vs threshold 973.6 (μ=977.2 σ=1.8 → 2σ=3.6). 0.2 fps below threshold = boundary false-positive on Gaussian-ish data, less concerning since fps distribution is closer to normal.

Only **DAL5** (spikes 378 vs 321 threshold; 57 over) was a real-anomaly signal worth surfacing.

Per the original design doc note: "distribution is heavily Poisson (avg 0.47 spikes/window, max 26, steam=send=0 since 2026-04-22 threading fix), so per-window 2σ is meaningless. Daily total per host vs trailing-7-day baseline is the right granularity. Once Project 3 categorizer ships, swap to 'new signature appeared OR count > 2σ AND signature severity ≥ 2'." — Project 3 categorizer is deferred to a separate phase; in the interim, widening spike threshold to 2.5σ suppresses the worst Poisson-tail false-positives without losing the real anomalies.

Same DAL3 example with 2.5σ: μ + 2.5σ = 200 + 165 = 365. DAL3's 333 sits comfortably below — would not flag. DAL5: μ + 2.5σ = 233 + 110 = 343. DAL5's 378 still 35 over — still flags.

#### Changes

- `scripts/ktp-perf-rollup.py`:
  - `SIGMA_THRESHOLD = 2.0` split into `FPS_SIGMA_THRESHOLD = 2.0` (unchanged) and `SPIKE_SIGMA_THRESHOLD = 2.5` (widened). fps stays at 2σ — Gaussian-ish distribution, 2σ catches real regressions cleanly.
  - Updated docstring + dataclass field comment + embed `Source` text to reflect the dual thresholds.

#### Operator deploy step

Stage updated `scripts/ktp-perf-rollup.py` to `/usr/local/bin/ktp-perf-rollup` on data server (74.91.112.242) before tomorrow's 04:30 ET cron fire. The cron itself is unchanged.

```bash
scp scripts/ktp-perf-rollup.py root@74.91.112.242:/usr/local/bin/ktp-perf-rollup
ssh root@74.91.112.242 chmod 755 /usr/local/bin/ktp-perf-rollup
```

After the 2nd dry-run fire (tomorrow 04:30 ET), re-eyeball the table + log to confirm the threshold widening eliminates the false-positives. If clean, lift `--dry-run` from `/etc/cron.d/ktp-perf-rollup-daily` per the original 48h-suppression protocol.

#### Cross-references

- TODO.md § "Tier 3 Project 1 follow-up" — original spec
- discord-embeds/CHANGES_SUMMARY_2026-05-08.md § "Perf-rollup dry-run review" — first-fire data + decision rationale
- 1.5.16 (entry below) — initial deploy

---

## [1.5.16] - 2026-05-04

### `feat`: ktp-perf-rollup daily threshold-alert script (Tier 3 Project 1 follow-up)

Implements the spec'd Tier 3 Project 1 follow-up: `[KTP_PROFILE]` rollup daemon already populates `hlstatsx.ktp_telemetry_metrics` every 5 min (Phase 8.2 from 2026-04-25), but no automated alerting on regressions. This is the alert layer.

Three-tier severity model per `TODO.md` Tier 3 Project 1 spec:

- **WARN** — yellow embed, no role-ping. Per-host `fps_p50` < (mean − 2σ) OR per-host daily `spike_total` > (mean + 2σ).
- **CRITICAL (partial fleet)** — red embed, no role-ping. ≥3 hosts in WARN on the same day. Catches partial-fleet regressions like one region's kernel update batch.
- **CRITICAL (fleet)** — red embed, ping `@KTP Admin`. Fleet daily median `fps_p50` < `FLEET_CRITICAL_FPS` (default 963 = 976.5 − 2 × 6.83 per fleet baseline measured 2026-05-03). Catches fleet-wide regressions like a kernel-experiment fallout or bad plugin deploy.

Daily aggregates, NOT per-window — per-window 2σ would fire on every 03:00 ET nightly restart artifact (server-fresh warm-up jitter). Daily smoothing absorbs 1-2 anomalous 5-min windows in 288/day. Trailing 7-day window per host as baseline; ≥4 baseline data points required for σ to stabilize (with only 2 points `statistics.stdev` returns `abs(a-b)` which gives random thresholds during fresh-deploy warmup).

NY:27019 excluded from WARN evaluation and from fleet-median computation (perpetual pingboost-4 canary, σ=0.12; would fire on any drop below ~999.7 fps; not a player-serving instance). Configurable via `PERF_EXCLUDED_HOSTS` in `/etc/ktp/discord-relay.conf`.

#### Files

- `scripts/ktp-perf-rollup.py` — ~570 LoC including docstring. Reads `ktp_telemetry_metrics`, computes per-host trailing-7-day baselines, persists forensic cache rows to new `ktp_telemetry_baselines` table, builds + posts embed via existing relay.
- `scripts/cron.d/ktp-perf-rollup-daily` — cron entry, 04:30 ET daily (after 03:00 fleet restart + 04:00 demo organizer + 04:15 demo retention sweeps complete).

#### Schema

New `hlstatsx.ktp_telemetry_baselines` table — forensic cache, ~50 KB/year:

```
server_endpoint VARCHAR(48) PK1
day             DATE PK2
fps_p50_today / fps_p50_mean / fps_p50_stddev / fps_p50_baseline (= mean − 2σ)
spike_total_today / spike_total_mean / spike_total_stddev / spike_total_baseline (= mean + 2σ)
warn_fps / warn_spikes / posted_to_discord (TINYINT bools)
computed_at  TIMESTAMP
KEY idx_day (day)
```

DDL is inline in the script as `DDL_BASELINES`. `ensure_baseline_schema()` probes via `SHOW TABLES LIKE` first and only runs `CREATE TABLE` if absent — `CREATE TABLE IF NOT EXISTS` itself requires CREATE privilege to evaluate (MySQL behavior), so the steady-state path stays SELECT-only on `information_schema` (which the scoped user has by default). First-ever run requires the operator to pre-create the table as root, then ktp_telemetry takes over.

#### Operator setup (one-time)

```sql
-- as MySQL root
CREATE TABLE hlstatsx.ktp_telemetry_baselines ( ... );  -- DDL above, or run script once as root
GRANT SELECT ON hlstatsx.ktp_telemetry_metrics TO 'ktp_telemetry'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON hlstatsx.ktp_telemetry_baselines TO 'ktp_telemetry'@'localhost';
FLUSH PRIVILEGES;
```

DELETE pre-authorizes future replay scenarios (script is idempotent on `ON DUPLICATE KEY UPDATE`, but DELETE lets an operator wipe a bad day for a clean rerun if needed).

Also add to `/etc/ktp/discord-relay.conf`:
```
PERF_ALERT_CHANNEL="<channel_id>"
PERF_EXCLUDED_HOSTS="74.91.123.64:27019"
# Optional:
# FLEET_CRITICAL_FPS=963
# KTP_ADMIN_ROLE_ID=1002394466700767332
```

Deploy artifact: `/usr/local/bin/ktp-perf-rollup` (symlink or copy of script). Cron file install: `/etc/cron.d/ktp-perf-rollup-daily`.

#### 48-hour suppression on first deploy

Cron entry ships with `--dry-run` flag. Daemon computes alerts and writes to `ktp_telemetry_baselines` but does NOT POST to Discord. Operator eyeballs `/var/log/ktp-perf-rollup.log` + the table for 2 days, then removes `--dry-run` from `/etc/cron.d/ktp-perf-rollup-daily` to enable posting.

#### Live test results (data server, dry-run)

- **Target 2026-05-03 (matchday):** 24 hosts, 7 in WARN, fleet median fps 975.3 → embed severity **CRITICAL (partial fleet)**. WARN cases: ATL1 (951 fps vs 968 baseline; spikes 539 vs 457 — both fps + spikes WARN), ATL4 (966 vs 974), CHI3/CHI4/ATL5/DAL2/DAL4 (tight-σ hosts on small drops). Embed JSON renders cleanly within Discord field-value caps.
- **Target 2026-05-04 (today, off-season Mon):** 24 hosts, 0 WARN, fleet median 979.1 → all-clear, no embed.

Output JSON snippet:
```json
{"title": "KTP perf rollup — CRITICAL (partial fleet) — 2026-05-03",
 "color": 15548997,
 "fields": [{"name": "Hosts in WARN (7)", "value": "**ATL1** ... fps 951.0 < 968.3 ...", "inline": false}, ...]}
```

#### ktp-code-review pass

Approved with 2 actionable warnings — both addressed before commit:

- **Warning 1 (truncation):** `[:1020]` cap was a silent mid-line cut on bad-fleet days (15+ WARN hosts overflow the 1024 field-value limit). Replaced with line-aware truncation + `…(truncated)` sentinel so operators see the cut.
- **Warning 2 (baseline floor):** `>= 2` baseline-data-points floor was too low; `statistics.stdev` with 2 points = `abs(a-b)` which gives random thresholds during fresh-deploy warmup. Bumped to `>= 4` (4 silent days of warmup, then reliable σ).
- Plus 2 doc clarifications (DELETE grant in cron-file operator note; MYSQL_USER/HOST/DB in script docstring).

#### Cross-references

- `TODO.md` Tier 3 Project 1 follow-up — closed by this commit
- `/opt/ktp-profile-aggregator/aggregator.py` — upstream collector (Phase 8.2 of KTPAdminBot, 2026-04-25)
- Memory `KTP off-season operational tempo` — 48h suppression aligns with off-season's lower production-change risk
- Spec at `TODO.md` lines 566-578 (or wherever it sits post-this-commit's TODO update)

#### Open follow-ups (post-deploy, not blocking)

- After 48h, operator removes `--dry-run` from cron.
- After ~1 week of live posting, tune `SIGMA_THRESHOLD` based on observed false-positive rate per spec (>5 WARNs/day fleet-wide → 2.5σ; <1/day → 1.5σ).
- Tier 3 Project 3 (`[KTP_SPIKE]` categorizer) is the remaining open Tier 3 work; this commit doesn't address it.
- Tier 1 smoke for output format — additive, can ship as a follow-up if helpful.

## [1.5.15] - 2026-05-04

### `feat`: ktp-verify-deploy — `--check-runtime` flag (Tier 2 prereq for runtime version assertion)

Closes the Tier 2 sub-item filed as "`amx_ktp_versions` rcon assertion — extends ktp-verify-deploy with a runtime 'is this what's loaded?' check (vs. just 'is this what's on disk?')". The rcon command itself shipped 2026-05-01 in KTPAMXX 2.7.15 (`ktp_version_reporter.inc` v2 multi-forward redesign); the asserter side was the missing piece.

#### What it catches

The disk-side check answers "are the right `.amxx` and `.so` files on disk?" — but a plugin's bytecode is loaded once at server start and held in KTPAMXX's memory for process lifetime. So a host can have the correct `.amxx` on disk (passes existing checks) while still RUNNING the prior version's bytecode because the instance hasn't restarted since deploy. This drift is invisible to the disk-side path.

`--check-runtime` runs `amx_ktp_versions` rcon on each instance, parses the loaded-plugin table, and diffs against the reference's loaded set. Catches:

- `runtime_drift`: plugin loaded with different `version` or build `sha` than reference (RED)
- `runtime_missing`: plugin loaded on reference, not loaded on target (RED — plugin failed to load there)
- `runtime_missing_partial`: above, but allowlisted via new `KNOWN_PARTIAL_RUNTIME` set (currently `{"KTP HUD Observer"}` — Jimmy's external-contributor plugin, deployed only to a subset of instances per `KNOWN_PARTIAL_DEPLOYS`) — INFO only
- `runtime_extra`: plugin loaded on target, not on reference (YELLOW)
- `runtime_error`: rcon failure on target (YELLOW; doesn't block GREEN-on-other-instances)

#### Implementation

- Added an inlined minimal GoldSrc UDP rcon client (`_RconClient` dataclass + `RconError`) at module scope. ~80 LoC. Mirrors the wire format in `tests/smoke/rcon.py` (canonical reference) but omits the smoke-only `wait_until_responsive` boot polling. Inlined rather than imported to keep `ktp-verify-deploy` single-file deployable to `/usr/local/bin` without a `sys.path` detour. Two-place sync required if the wire format changes; current format has been stable since the smoke harness shipped 2026-04-26.
- `collect_runtime_versions(host, port, password=RCON_PASS)` — runs `amx_ktp_versions` rcon, returns `{display_name: {version, sha, build_time}}`. Parses the fixed-column `%-32s %-14s %-10s %s` output (per `ktp_version_reporter.inc:111-117`) via `str.rsplit(maxsplit=3)` — the last 3 tokens are space-free (version, sha, build_time) and everything before is the multi-word display name. Robust against `-dirty` SHAs that overflow the 10-char column (`%-Ns` minimum-pads, doesn't truncate).
- `verify_fleet(...)` gained a `check_runtime: bool = False` parameter. When set, fetches the reference's runtime versions first; if that fails, sets `ref_runtime_error` and skips per-instance checks (avoids cascading false RED across the fleet from one transient ref-rcon timeout). Reference instance reuses its own `ref_runtime` for the self-comparison rather than issuing a duplicate rcon round-trip.
- New `--check-runtime` CLI flag (default off). Per-instance rcon adds ~1-9s wall time per host; full fleet sweep with `--check-runtime` ran ~3 min vs ~30s baseline.
- Constants: `RCON_PASS = "REDACTED_RCON"` (mirrors existing `GAME_PASS = "REDACTED"` pattern; uniform fleet-wide per `dodserver.cfg`).
- Status integration: `runtime_drift` or non-allowlisted `runtime_missing` → RED; `runtime_extra` or `runtime_error` → YELLOW; otherwise GREEN unchanged.
- JSON report schema additions are additive: `check_runtime: bool` at top level, `reference.runtime_plugins` (sorted name list) and `reference.runtime_error`, per-instance `runtime_drift` / `runtime_missing` / `runtime_missing_partial` / `runtime_extra` / `runtime_count` / `runtime_error`. No breaking change for existing report consumers.

#### Verification

- `python3 -m py_compile` clean.
- Live test against 24-instance production fleet: **24/24 GREEN**. ATL1 (reference) reports 9 plugins; the other 23 instances report 8 with `runtime_missing_partial: ["KTP HUD Observer"]` correctly classified as INFO. Zero `runtime_drift`, zero `runtime_error`, zero `runtime_extra`. Default path (no `--check-runtime`) regression-tested: identical JSON output to pre-change.
- ktp-code-review agent reviewed; approved with two warnings — both addressed in the commit:
  - **Warning 1:** `timeout` parameter in `collect_runtime_versions` only covers the response-receive phase (challenge has its own `connect_timeout=5.0`, drain has `drain_timeout=0.4`). Worst-case per-instance wall is ~9.4s, not 4.0s. Fix: docstring clause clarifying the bound, with the cumulative formula spelled out.
  - **Warning 2:** redundant column-header keyword guard in `_parse_amx_ktp_versions` could silently drop a future plugin whose display name happens to contain "Name", "Version", and "SHA" all at once. Fix: removed the keyword check (the separator-line state machine already skips the header correctly).
  - **Suggestion (also fixed):** when reference instance re-enters the per-instance loop, it was issuing a duplicate `amx_ktp_versions` rcon to itself. Fix: `is_ref` short-circuit reuses the already-fetched `ref_runtime`.

#### Cross-references

- `KTPAMXX/plugins/include/ktp_version_reporter.inc` (rcon source side; v2 multi-forward design from 2026-04-30)
- `tests/smoke/rcon.py` (canonical wire-format reference; suggested follow-up: add a "KEEP IN SYNC WITH scripts/ktp-verify-deploy.py" marker in its module docstring for symmetric discoverability)
- TODO.md sub-bullet "`amx_ktp_versions` rcon assertion" — closed by this commit
- TEST_INFRASTRUCTURE_PLAN.md Tier 2 — incremental progress

## [1.5.14] - 2026-05-04

### `fix`: HLTV recording-pipeline 3-bug bundle (post-matchday YELLOW root-cause)

Three correlated bugs surfaced by the 2026-05-04 post-matchday soak-verify YELLOW: 10 "no matching auto-*" warnings from `hltv-demo-renamer` plus 4 ATL1 in-game "HLTV up but not recording" alerts from `KTPHLTVRecorder`. Forensics on ATL1 + HLTV 27020 confirmed **no actual data loss** — every demo file was preserved on disk; all three bugs were observability or labeling. Root cause for each follows; ktp-code-review approved diffs after one round of corrections (case-mismatch in `_sibling_demo_extends_into` glob + State.load forward-compat field-filter).

#### Bug 1 — `hltv-demo-renamer.py` mislabels h2 demos when HLTV does not rotate at half boundary

The renamer's contract with KTPHLTVRecorder v1.7.0 (`MATCH_WINDOW_OPEN` per half + `MATCH_WINDOW_CLOSE` once at MATCH_END) presumes HLTV rotates `auto_*.dem` files at half boundaries. HLTV's actual rotation is on its own internal cadence (~22-30 min, time-based), unrelated to plugin events. When rotation does not align with the h1→h2 boundary, the renamer's auto-close logic claimed the still-being-written file at the moment it received OPEN h2 — and `rename(2)` preserves the open FD, so HLTV continued writing h2 data into the file already labeled `_h1-...partN`. The h2 close then found nothing to claim and emitted "no matching auto-*". Net: data preserved, label wrong.

##### Change
- `OpenWindow` dataclass gains `deferred: bool` + `deferred_candidates: List[str]` fields, persisted to `state.json` via existing `asdict`/`from-dict` round-trip.
- `Renamer.rename_for_window(window, *, force=False)` rewritten: when the candidate set's max mtime is at-or-newer than every other auto-* file for the same friendly (i.e., HLTV may still be writing to a candidate), defer the rename. Stash candidate basenames on `OpenWindow.deferred_candidates`. Subsequent poll cycles retry — on rotation (a newer auto-* appears) flush normally as `_h1`/`_h2`; at the 4h `WINDOW_ABANDON_AGE_SEC` timeout, force-flush as combined-name with `omit_half=True` (no half marker — the file is a single-recording whole-match; organizer regex `(_h[12])?` accepts the marker-less form).
- New helpers: `_all_auto_for_friendly`, `_has_successor_auto`, `_sibling_demo_extends_into` — the last differentiates the no-data-loss case (HLTV did not rotate; data is in the prior-half file) from a true recording loss and emits a different INFO log line. The new line is INTENTIONALLY EXCLUDED from `ktp-soak-verify`'s YELLOW grep (see Bug 1 soak-verify change below).
- `_build_target_name` gains keyword-only `omit_half: bool = False` for the combined-name flush path.
- `_process_closed_windows` updated to keep deferred windows in state across poll cycles, force-flush at abandon, and drop normally on successful rename.
- `State.load` now filters JSON keys to known dataclass fields, defending against forward-compat schema drift in either direction.

#### Bug 2 — `hltv-api.py` `/state` returns false-positive `recording: false`

`_parse_state()` scanned the last 5 minutes of `journalctl -u hltv@<port>.service` for `Recording to X.dem, Length N sec.` lines, on the assumption that HLTV emits them periodically. The 2026-05-04 forensics on the ATL1 HLTV journal disproved this: those lines only appear in response to external rcon `status` calls, paired 1:1 with `Executing rcon "status" from 127.0.0.1:<ephemeral>` log lines. Nothing periodic emits them. So whenever the last 5 minutes had no rcon-status traffic (the steady state for any match running >5 min with no monitor traffic), `/state` returned `recording: false`, and the plugin's `hltv_health_check_callback` logged the in-game WARNING "HLTV up but not recording — match may be missing" at every match start. ATL1 fired this 4 times on 2026-05-03 — all false positives; HLTV was actively recording the whole time.

##### Change
- New `_trigger_status_rcon(port)` helper: writes `status\n` to the cmdpipe (`/home/hltvserver/cmdpipes/hltv-<port>.pipe`) non-blocking via `O_WRONLY | O_NONBLOCK`, swallows `BlockingIOError` and `OSError` (graceful degrade to pre-fix journal-only scan if the pipe is unreachable).
- `_parse_state()` now calls `_trigger_status_rcon(port)` before the journalctl scan, then sleeps `STATE_TRIGGER_SLEEP_SEC` (default 0.25s) so HLTV's status response has time to flush to the journal. 250ms is a 2.5x safety margin over the typical ~10ms HLTV stdin tick + ~100ms journald flush; under peak matchday journal pressure if telemetry shows false-idle returns, bumping this to 0.5 is a one-line followup.
- Outdated comment block at lines 40-43 corrected (the prior comment claimed periodic emission).

Failure mode under journal pressure: `/state` reverts to pre-fix behavior (false-idle) for that one call. Identical to current buggy state, no regression. KTPHLTVRecorder's caller would see false idle and fall through; the alert is harmless beyond noise.

#### Bug 3 — `hltv-demo-renamer.py` emits misleading "Auto-closing prior half: h1" on duplicate OPEN

KTPHLTVRecorder's `ktp_match_start` forward fires twice for h1 in some scenarios, confirmed via wall_time diffs in the 2026-05-03 logs (same-second duplicates with identical `wall_time=1777856520`, AND 2-min-apart duplicates with different `wall_time=1777783177` vs `1777783316`). The renamer's auto-close loop in `_ingest_lines` did not check `w.half`, so a duplicate same-half OPEN auto-closed the prior h1 entry and emitted "Auto-closing prior half: port=27020 match=<id> half=h1" every time. The downstream replace-on-same-key dedup at the OPEN-append step prevented actual state corruption (the auto-closed entry was deleted before `_process_closed_windows` could process it), but the log noise polluted operator inspection and inflated the perceived event rate.

##### Change
- `_ingest_lines` open branch: explicit `dup` check at the top — `any(w.key() == (port, match_id, half) and w.close_unix is None for w in open_windows)`. On dup, log "Duplicate OPEN ignored (idempotent)" and `continue` before reaching the auto-close loop.
- Auto-close loop additionally requires `w.half != half` as defense-in-depth.
- Original closed-same-key replace block preserved (handles the rare "stale closed-pending-rename entry" case).

Plugin-side root cause for the duplicate forward fire is unconfirmed and **not addressed** in this commit — the renamer dedup is sufficient to silence the operator-visible symptom, but the underlying double-fire likely also produces duplicate Discord embeds + duplicate HLStatsX events. Filed as a low-priority followup in TODO.md (suspect: `restore_match_context_from_localinfo` replaying state in `plugin_cfg` on map load, or a non-deferred match-start path bypassing the documented `task_deferred_discord_fwd` defer pattern).

#### Bug 1 soak-verify wording correction

`ktp-soak-verify.py` check 4 grep pattern updated to `no matching auto-\* files in mtime|Deferred-rename abandon`, intentionally excluding the renamer's new "HLTV did not rotate at half boundary; data is in the prior-half file" INFO line — those are zero-data-loss cases and were the bulk of pre-fix YELLOW noise. Check renamed to "Recording-loss / abandon warnings" so the message matches the actual semantics.

#### Bug 4 — `ktp-soak-verify.py` check 9 false-positive on HLTV restart success summary

The same 2026-05-04 post-matchday YELLOW also flagged "HLTV restart timer ⚠ completion seen but 1 error/fail line(s) in journal". Investigation showed the `1` was the script's own success summary line `[2026-05-04 03:00:01 EST] 24 succeeded, 0 failed` — `grep -iE "error|failed|fatal"` matched the literal string `failed` in the success-context. Same class of bug as Bug 1's overly broad grep.

##### Change
- `ktp-soak-verify.py` check 9 error-grep gains a pre-filter: `grep -vE "succeeded, 0 failed$"` excludes the success-summary trailer. A real partial failure (e.g., `23 succeeded, 1 failed`) still passes the filter and triggers YELLOW correctly. Comment block at line 421-426 documents the trigger + non-trigger semantics so a future reader doesn't strip the filter as redundant.

#### Verification
- `python3 -m py_compile` on all three edited scripts: clean.
- ktp-code-review agent reviewed both diagnosis (pre-code) and code diffs (post-code); approved after one round of corrections.
- Forensic data covers all 10 reported events from 2026-05-03 — every demo file present on disk, no actual data loss in any case.
- Deployment: not yet deployed to data server. Local commit only; deploy planned for next maintenance window.

#### Cross-references
- Plugin source: `KTPHLTVRecorder/KTPHLTVRecorder.sma` v1.7.0 (no changes, contract preserved).
- Plugin chat-side alert: `hltv_health_check_callback` lines 285-380 (no changes; will stop firing falsely once Bug 2 fix deploys).
- Memory updates: indexed in MEMORY.md (none added — investigations resolved in-session, fix lives in this CHANGELOG).
- Soak-verify cron: `cron.d/ktp-soak-verify-post-matchday` (Mon 10:00 ET); next firing on 2026-05-11 will validate the fix end-to-end.

## [1.5.13] - 2026-05-03

### `fix`: ktp-report-core ProcessLookupError race in scan_pid_port_table

The crashreporter's PID-port table scanner walks `/proc/[0-9]*` and reads each `/proc/<pid>/cmdline` to map live `hlds_linux` PIDs to their game ports. The existing exception handler at `report_core.py:89` caught `PermissionError` + `FileNotFoundError`, but not `ProcessLookupError` — Linux raises the latter (not the former) when `/proc/<pid>/` exists but the task struct behind it has been reaped between `Path.glob()` yielding the PID and `read_bytes()` opening the cmdline file. The /proc reaper is asynchronous, so the directory entry can survive the task struct briefly.

ATL crashreporter hit this race once on 2026-05-01 04:52:01 EDT and crashed; systemd auto-restarted 11s later. No core-event was lost in the gap (no cores landed in `/tmp` during the window), but a longer-running race could have masked a real game-server crash. Discovered 2026-05-03 while reviewing Tier 3 Project 2 status.

#### Change
- `scan_pid_port_table()` exception tuple `(PermissionError, FileNotFoundError)` → `(PermissionError, FileNotFoundError, ProcessLookupError)`. Same continue-and-skip-this-PID semantics for all three.
- Added 4-line comment explaining the race so future readers don't strip `ProcessLookupError` thinking it's redundant with `FileNotFoundError`.

#### Operational steps applied 2026-05-03
- Deployed in parallel to all 5 game hosts (ATL/DAL/DEN/NY/CHI). md5 `8a2d50a4...` → `d76f010d...`. `systemctl restart ktp-crashreporter` per host; all 5 came back `active` at the same instant 13:16:21 EDT, all logged the canonical `crashreporter started · region=<X>` line.
- Backups: `/root/cron-backups/ktp-report-core.bak-20260503-130000` per host.
- `python3 -c "import py_compile; py_compile.compile(...)"` syntax check passed pre-restart on each host.
- Service consumed memory peak 17-19M per host pre-restart (38-150s CPU lifetime), no leak signals.

#### Why this slipped 2026-04-26
`ProcessLookupError` vs `FileNotFoundError` vs `PermissionError` looks like a distinction without a difference at first glance — they're all "this PID went away or isn't readable." Original handler caught the two more obvious ones. `ProcessLookupError` fires specifically when the kernel still has the `/proc` directory entry but the task struct has been reaped — rare on idle systems, more frequent on busy ones with high process churn. Defensive fix.

### `chore`: Tier 3 Project 2 (Core-dump auto-reporter) — TODO checkbox flipped post-hoc

Project shipped 2026-04-26 per memory `crashreporter_fleet_2026-04-26.md`; TODO checkbox in `TODO.md` was never flipped. Updated to `[x]` with a resolved-line pointing at the memory + the race-condition fix above. Scope totals math refreshed: Tier 3 remaining ~25h (rollup + spike categorizer) instead of ~40h. ~168h total Tier-2/3 remaining instead of ~180h.

## [1.5.12] - 2026-05-03

### `fix`: ktp-demo-cleanup-auto retune for F+A always-on-recording rate

`ktp-demo-cleanup-auto.sh` deployed 2026-04-29 22:43 with a 7-day age threshold and daily 04:45 ET cron. KTPHLTVRecorder 1.7.0 F+A activation flipped HLTV recording from match-windowed to always-on the same day, raising root-level `auto_*.dem` accumulation from a few GB/week (matches only) to ~75 GB/day (24-instance fleet × continuous recording during dead time + map rotations on empty servers). The 7-day threshold meant the script logged `nothing past 7d at root` four nights running while the disk drowned. Discovered 2026-05-03 12:00 ET when `/dev/xvda2` hit 100% used (468G/493G); root partition wedged.

#### Retune
- `AGE_DAYS=7` → `AGE_MINUTES=360` (6 hours). 6h covers a full DoD match plus renamer-recovery grace; renamer normally renames within seconds of `MATCH_WINDOW_CLOSE`, and renamer outages page via the `OnFailure=` alert framework well before this window elapses. `find -mtime` → `find -mmin`.
- Cron daily 04:45 ET → `*/30 * * * *` (every 30 min). Bounds max disk pressure between sweeps to ~1.5 GB.
- No logic changes — same dry-run mode, same per-file logging, same human-bytes formatter, same `-maxdepth 1` to keep `demos/<friendly>/<matchtype>/*.dem` untouchable.

#### Operational steps applied 2026-05-03
- Manual triage cleanup ahead of script retune: 6,035 root-level `auto_*.dem` files / 305.32 GB deleted via `find -maxdepth 1 -mmin +120 -delete`. Manifest at `/var/log/ktp-cleanup/auto-dem-purge-20260503-121032.txt`. Disk: 100% → 35% used (305 GB freed).
- Sanity assertions: `demos/` subtree (137 GB sorted demos) untouched; renamer service still `active`; all 24 HLTV instances still running.
- Script + cron deployed via SFTP, dry-run validated, real cron picks up new schedule on next refresh.
- 12:30 ET first scheduled fire under new schedule logged `auto-cleanup: nothing past 360m at root` — expected (manual triage already covered the >120m set). First real sweep arrives ~18:30 ET when the post-triage in-flight backlog crosses the 6h threshold.

#### Why this slipped 2026-04-29
Pure timing miss. The cleanup script was sized for the pre-F+A world (matches only) and the F+A activation landed the same day. Pre-F+A, dead-time recording produced ~zero GB; post-F+A, it's the dominant volume source. The script's premise ("anything past 7d is forgotten by the renamer") was correct; the ASSUMPTION ("disk has weeks of headroom") wasn't audited against the F+A change.

### `fix`: ktp-data-server-health alerts move to #ktp-updates

`ktp-data-server-health.sh` was posting state-transition alerts to channel `1081255192529477744` (legacy "drift audit" channel) while every other operational alert framework on the data server (`ktp-soak-verify`, `ktp-systemd-alert`, `ktp-precache-audit`, RemoteTrigger / canary / cron embeds) posts to `#ktp-updates` (`1498813261263405097`). The split-channel state meant operators had to watch two channels for an essentially identical class of signal. Surfaced 2026-05-03 03:00 ET when a hltv@27027=deactivating alert landed in the wrong place.

#### Change
- `ALERT_CHANNEL` default `1081255192529477744` → `1498813261263405097` (memory `scheduled_report_channel.md`).
- Script header comment updated: stale `Schedule: every 10 minutes` corrected to match the actual cron (`hourly`); the 10-min comment was a leftover from an earlier draft of the cron file's own justification block.
- Imported as canonical source into `KTPInfrastructure/scripts/ktp-data-server-health.sh` + `.cron` — the script was previously only deployed, not in the repo. No `.example` template required (no inline secrets — `RELAY_URL` + `AUTH_SECRET` source from `/etc/ktp/discord-relay.conf` at runtime).

#### Operational steps applied 2026-05-03
- Backup: `/root/cron-backups/ktp-data-server-health.sh.bak-20260503-122500`.
- Deploy: SFTP'd to `/usr/local/bin/ktp-data-server-health.sh`, line endings normalized, `chmod 755`, `chown root:root`. md5 changed from `99ec3855…` to `747574a9…`.
- Verification: manual run `[2026-05-03 12:39:10] no transitions (currently down: 0)` — script reads new channel value, won't post anything until next real transition. Next real transition lands in `#ktp-updates` as proof.

#### Housekeeping
- Moved my own `.bak-*` backup files out of `/etc/cron.d/` (defensive — cron's run-parts naming rule ignores filenames containing dots, so they weren't firing, but they shouldn't sit in `/etc/cron.d/` regardless). Backups now live in `/root/cron-backups/`.

## [1.5.11] - 2026-05-01

### `fix`: hltv-demo-renamer no longer double-appends friendly hostname into canonical filename

The renamer's `_build_target_name` was producing names like `scrim_1777594479-ATL4-ATL4_h1-2604302009-dod_harrington.dem` — the friendly appears twice. Root cause: KTPMatchHandler intentionally bakes the short hostname into `match_id` itself (`{timestamp}-{shortHostname}` for standard, `1.3-{queueId}-{shortHostname}` for 1.3 community 12mans, see `KTPMatchHandler.sma:1966,1971`) because match_id is also used as a uniqueness key for HLStatsX, Discord embeds, and scoring. The renamer then dutifully appended `<UPPER_FRIENDLY>` again per the canonical format spec, creating the doubled token. The downstream organizer (`ktp-organize-hltv-demos.sh`) regex expects single-friendly names and rejected every doubled-token demo as "unrecognized format" — last 24h `Moved: 0 | Skipped: 2127 | Errors: 0`. Soak verification step #1 (portal populated) would have failed Sunday matchday.

`_build_target_name` now skips the redundant `<FRIENDLY>` append when `match_id` already ends with `-<friendly>`. Output collapses to single-friendly:

- Before: `scrim_1777594479-ATL4-ATL4_h1-...`
- After:  `scrim_1777594479-ATL4_h1-...`

Both shapes match the existing organizer's regex (which already supports both standard `<matchtype>_<timestamp>-<hostname>` and 1.3 `<matchtype>_1.3-<queueid>-<hostname>` forms). Single-file fix; no plugin recompile or fleet redeploy required.

### Operational steps applied 2026-05-01

- Backup: `/usr/local/bin/hltv-demo-renamer.py.bak-pre-friendly-fix-2026-05-01` (21.8 KB).
- Deploy: SCP'd to `/usr/local/bin/hltv-demo-renamer.py` (22.6 KB), `chmod +x`, `systemctl restart hltv-demo-renamer`. Service active 2s post-restart, all 5 SSH connections to game hosts re-established cleanly.
- Backfill: 12 stuck double-friendly demos at HLTV root renamed in-place via paramiko regex sweep, then `/usr/local/bin/ktp-organize-hltv-demos.sh` sorted them into `/home/hltvserver/hlds/dod/demos/<friendly>/<matchtype>/`. Final tally: `Moved: 12 | Skipped: 2811 | Errors: 0` (the 2811 skipped are pre-renamer auto-*.dem files awaiting their 7d cleanup window).
- Verified: `/demos/ATL4/scrim/` returns HTTP 200 with all 6 backfilled demos visible; `/demos/CHI1/12man/` shows the 2 12man halves; `/demos/ATL1/scrim/`, `/demos/ATL2/scrim/` also populated. New format matches the historical demos already in those directories byte-for-byte (organizer was working pre-1.7.0; only the renamer-introduced double-friendly broke it).

### Sunday 2026-05-03 soak verification status (pre-matchday)

- ✅ Renamer service active 1d 14h (now 2 min post-restart), `open_windows: []`.
- ✅ Canonical format consistent with historical demos.
- ✅ Portal `/demos/<friendly>/<matchtype>/` accessible + populated.
- ⚠️ 5 "no matching auto-* files" h2 warnings since 2026-04-30 — possible real recording loss for ~5 half-windows, small absolute number, defer to post-Sunday `lookup_demo.py` analysis.
- ⚠️ Cosmetic systemd unit warning: `Unknown key name 'StartLimitIntervalSec' in section 'Service'` — should be `StartLimitInterval` or move to `[Unit]`. Not impacting operation.

## [1.5.10] - 2026-04-30

### `ci`: bump GitHub Actions to Node 24 runtimes

Closes the Node.js 20 deprecation warning emitted on every smoke run ahead of GitHub's 2026-06-02 forced cutoff (full removal 2026-09-16).

#### Bumped
- `actions/checkout` v4 → v6 (GA on Node 24 since 2025-11-20)
- `actions/setup-python` v5 → v6 (GA on Node 24, current v6.2.0 from 2026-01-22)
- `docker/login-action` v3 → v4 (GA on Node 24, current v4.1.0 from 2026-04-02)

#### Files touched (this repo)
- `.github/workflows/smoke-callable.yml` — 17× checkout, 1× setup-python, 1× login-action
- `.github/workflows/publish-base-image.yml` — 15× checkout, 1× login-action
- `.github/workflows/config-tests.yml` — checkout, setup-python

#### Done in coordinated companion commits
Same bump applied across the 9 caller / sibling KTP repos that pin these actions directly: KTPMatchHandler, KTPHLTVRecorder, KTPFileChecker, KTPGrenades (config-tests.yml each); KTPAMXX (ci.yml); KTPAntiCheat (dotnet-tests.yml + vac-safety-lint.yml); KTPReHLDS (rehlds/build.yml); KTPReAPI (build.yml). Caller smoke.yml files don't need the bump — they delegate to smoke-callable.yml.

## [1.5.9] - 2026-04-30

### `docs/CANARY_RUNBOOK.md` — production canary pre-flight + toggle pattern

New 178-line operational runbook codifying the single-instance canary pattern (cvar/cfg/feature toggle on one host with same-day fleet propagation gate). Sibling to `KERNEL_EXPERIMENT_RUNBOOK.md`.

#### Background
Two consecutive HPAK `sv_send_logos` canary attempts (2026-04-29, 2026-04-30) aborted on `*.new`-presence pre-flight rules. The first was a true positive (swap-glob bug had blocked the night's swap, leaving stale binaries running). The second was a false positive (operator legitimately staged the next day's deploy queue 44 min before the canary fired). The rule conflated "deploy state is broken" with "next deploy is staged" — same evidence, different meanings.

#### Added
- `docs/CANARY_RUNBOOK.md` — §1 use cases, §2 pre-flight rules (live-binary md5/size assertions replacing `.new`-absence), §3 toggle execution pattern (cfg sed-edit + LinuxGSM `send`), §4 rollback, §5 RemoteTrigger automation, §6 known false-positive patterns (both 2026-04-29 + 2026-04-30 cases documented), §7 cross-references.

#### Why
Locks in the live-binary md5/size assertion pattern as the canonical pre-flight rule. Future canary prompts (likely fleet-wide HPAK propagation post-2026-05-03 if matchday clean) will source pre-flight from this doc rather than reinventing it. Closes the "two-strikes" pattern before it becomes three.

## [1.5.8] - 2026-04-29

### `scripts/hltv-demo-renamer` — match-window-driven demo renamer (Phase 1c of HLTV F+A architecture)

New systemd service on the data server that watches each game host's amxx log for `[KTP HLTV] MATCH_WINDOW_OPEN` / `MATCH_WINDOW_CLOSE` lines emitted by KTPHLTVRecorder v1.7.0+, and renames `auto_<friendly>-<TS>-<map>.dem` files to the canonical format the existing 4 AM `ktp-organize-hltv-demos.sh` recognizes.

#### Added
- `scripts/hltv-demo-renamer.py` — Python service, ~450 LOC. Paramiko-tails logs every 30s; in-memory state of open match windows keyed by `(hltv_port, match_id, half)` with persistent JSON checkpoint at `/var/lib/hltv-demo-renamer/state.json`. h1's effective close is auto-derived from h2's open event (KTPMatchHandler only emits `MATCH_WINDOW_CLOSE` once per whole match at MATCH_END).
- `scripts/hltv-demo-renamer.service` — systemd unit (Type=simple, root, Restart=on-failure, StartLimitBurst=5).
- `scripts/ktp-demo-cleanup-auto.sh` — Phase 1d sibling cleanup: sweeps unmatched root-level `auto*-*.dem` >7 days. Required because `ktp-demo-retention.sh` only operates on `demos/{ktp,draft,12man,scrim}/` subfolders — its blind spot is exactly where unmatched auto-* files land.
- `scripts/ktp-demo-cleanup-auto.cron` — daily at 04:45 ET (sequenced after organize 04:00, retention 04:30).
- `scripts/install-hltv-demo-renamer.sh` — single-shot installer: copies binaries, installs systemd unit + cron, ensures python3-paramiko, reloads systemd.
- `scripts/README-hltv-demo-renamer.md` — operations runbook (pipeline diagram, friendly-alias table, dry-run / state-reset / failure-mode docs).

#### Verified design
- Output format (`<matchtype>_<match_id>-<UPPER_FRIENDLY>(_h1|_h2)?-<hltv_ts>-<map>.dem`) matches the existing organizer's regex; verified via Python AST replay of the bash regex on real production filenames.
- HLTV's auto-rotation suffix behavior (`-<YYMMDDHHMM>-<map>` appended to whatever basename is configured) confirmed against current production v1.6.0 amxx log evidence — no canary needed before rollout.
- Unit + ingest tests pass: friendly mapping (5 region bases), MATCH_WINDOW parse, auto-* regex, target-name builder including multi-segment `_part2`, h1→h2 auto-close-prior-half logic.

#### Activation
Idle until KTPHLTVRecorder v1.7.0 is fleet-wide AND HLTV cfgs include `record auto_<friendly>` (Phase 1a). Service can be enabled before those land — it simply has no events to process.

#### Pipeline order (cron + service)
```
hltv-demo-renamer.service       continuous     auto-*.dem -> canonical
ktp-organize-hltv-demos.sh      04:00 ET       canonical -> demos/<F>/<T>/
ktp-demo-retention.sh delete    04:30 ET       per-tier age sweep (subfolders only)
ktp-demo-cleanup-auto.sh        04:45 ET       root-level auto-*.dem >7d sweep
```

---

## [1.5.7] - 2026-04-29

### `scripts/hltv-restart-all.sh` — fix syntax error that broke nightly HLTV restarts since 2026-04-10

#### Fixed
The for-loop on line 36 was previously:

```bash
for port in $(seq 27020 27044); do
```

A 2026-04-10 edit on the deployed copy added a comment about CHI:27044 being disabled, but the comment was placed in a way that broke bash:

```bash
for port in $(seq 27020 27043)  # 27044 (chi5) disabled 2026-04-10; do
```

The `; do` ended up INSIDE the comment (after `#`), so bash saw an incomplete `for` statement and threw `syntax error near unexpected token 'if'` at the next line. Every nightly HLTV restart attempt has failed since the edit went in:

- Timer fires correctly twice daily (3:00 AM + 11:00 AM ET, per `hltv-restart.timer`).
- `hltv-restart.service` immediately exits with `status=2/INVALIDARGUMENT`.
- No restart actually happens. No Discord notification fires (the Discord post is at the END of the script).
- Failures only visible via `journalctl -u hltv-restart` — which nobody watches.

Net effect: HLTV proxies ran 3 weeks without restart. By 2026-04-29 (uptime 7 days 13 hours on most instances; some longer windows preceded by other one-off restarts), proxy 27036 was in a degraded state where match-start `mp_clan_restartround` cycles triggered a 14-reconnect storm, causing both halves of a 14:40 ET scrim on NY2 to record as 0-byte demos.

Surfaced 2026-04-29 mid-day when KTPHLTVRecorder 1.6.0's verification fired on the failed recording — the plugin worked correctly; the issue was HLTV-side and the script had been failing for weeks.

#### Changed
- Canonical `scripts/hltv-restart-all.sh` line 36: `; do` moved to BEFORE the `#` comment, so bash sees a complete for-loop on the line:
  ```bash
  for port in $(seq 27020 27043); do  # 27044 (chi5) disabled 2026-04-10
  ```
- Range is `27020-27043` (24 ports) — skips 27044 which is the disabled CHI:5 HLTV. Previous canonical had `27020-27044` and would have logged 1 failure per run for the disabled port; the deployed version had `27020-27043` baked in but with the syntax-breaking comment.

#### Recovery applied
Same-session manual fix on the data server:
1. `cp -p /usr/local/bin/hltv-restart-all.sh /usr/local/bin/hltv-restart-all.sh.bak-20260429T193507Z-syntax-fix`
2. SFTP-write the patched version.
3. `bash -n` clean.
4. `systemctl reset-failed hltv-restart.service && systemctl start hltv-restart.service` — fired the script via systemd, restarting all 24 active HLTV instances. Verified all came back fresh (uptimes 8-9 seconds post-restart).
5. Tonight's 03:00 ET 2026-04-30 nightly will be the first scheduled successful run since 2026-04-10.

#### Lesson — surfaced as a gap
**systemd unit failures should not be silent for weeks.** `hltv-restart.service` failed 24+ times across 2026-04-10 → 2026-04-29 with zero observability. Adding `OnFailure=` to a Discord-alerting unit (or an external systemd-monitor check across the data server's services) would have caught this at the first failed run. Tracked as a follow-up TODO ("HLTV restart service had silent failures for 3 weeks — add monitoring for systemd unit health").

---

## [1.5.6] - 2026-04-29

### Deploy preflight integration

#### Added — `deploy/deploy.py` now requires CI green for HEAD before deploying
The canonical Python deploy entry point (used by `make deploy`, `make deploy-atlanta`, `make deploy-plugins`, etc.) now fires `scripts/preflight.py::assert_ci_passing` before doing any work. Catches the regression class where someone compiles + deploys without realizing their last commit broke smoke or config-tests.

##### Changed
- `deploy/deploy.py` — Added a new `--force-deploy` flag and a pre-flight block that imports `preflight` from `../scripts/`, calls `assert_ci_passing(repo_root=KTPInfrastructure root, force=args.force_deploy)`, and exits with `REFUSING TO DEPLOY: <reason>` on failure. Skipped on `--dry-run` (no point gating a dry-run).

##### Behavior
- Normal path: deploy aborts if HEAD has no workflow runs, has any in-progress run, or has any non-success conclusion. Push your commit and wait for CI; or use `--force-deploy` to bypass.
- `--dry-run`: pre-flight skipped, deploy proceeds in dry-run mode regardless of CI state.
- `--force-deploy`: pre-flight runs but logs a warning instead of failing. Same convention as branch-protection bypass — sparingly, and document why.

##### Why now
TODO entry "Tier 1 housekeeping (c) — Deploy-script preflight integration" had been deferred since 2026-04-29. The pre-flight library + CLI shipped 2026-04-27 but no deploy script called it yet. Now the highest-traffic deploy entry point does.

##### Compatibility
Purely additive. Existing invocations work the same. The `--force-deploy` flag is opt-in. No env vars required beyond what `gh` CLI already needs (the dev machine should already have `gh auth login`'d).

##### Scope note
This integration covers the tracked Python deploy entry point (`deploy/deploy.py`). The dev-local gitignored deploy scripts in plugin repos (e.g., `KTPAmxxCurl/scripts/deploy_curl.py`) are not touched here — those vary per developer and per session and should adopt the pattern individually when next modified. See `docs/CI_SETUP.md` section 5 for the canonical library + shell integration patterns.

##### Related
- Branch protection per-repo (the other half of the TODO entry) remains pending. Operator UI / `gh api` work — per `docs/CI_SETUP.md` section 3 — held for a focused review pass to avoid getting status check names wrong (a wrong required check blocks all PRs on that repo).

---

## [1.5.5] - 2026-04-29

### Build system — drop external `metamod-am` checkout

#### Changed
KTPAMXX 2.7.14 vendored its required Metamod headers in-tree at `KTPAMXX/third_party/metamod/`, eliminating the need for the build chain to clone `alliedmodders/metamod-hl1` as a sibling repo. Companion infrastructure cleanup:

- **`build/amxx/Dockerfile`** — Removed `COPY metamod-am /build/metamod-am` and `ENV METAMOD=/build/metamod-am`. The KTPAMXX builder image is now ~self-contained against vendored sources.
- **`.github/workflows/publish-base-image.yml`** — Removed the `Checkout metamod-am (alliedmodders/metamod-hl1)` step. Saves ~5-10s per nightly base-image publish.
- **`.github/workflows/smoke-callable.yml`** — Removed the slow-path `Checkout metamod-am` step. Saves ~5-10s per slow-path smoke run; fast-path runs were never affected (they pull a pre-built image).

#### Compatibility
No runtime change. Anyone who had been passing `--metamod` to KTPAMXX's `configure.py` or setting `METAMOD=` in their environment can drop those — the build no longer recognizes them.

#### Why now
Closes the corresponding TODO ("Vendor metamod-am headers — drop external build dep"). Removes one external dep, ~6 lines of CI YAML, and a recurring source of "we don't use metamod, why is metamod-am here?" confusion.

---

## [1.5.4] - 2026-04-29

### Tier 1 smoke — defenses against GHCR `:latest` propagation race

#### Fixed
On 2026-04-29 06:42 UTC, a manual `publish-base-image` rebuilt the GHCR base image with newly-promoted `KTPHudObserver.amxx` baked in. Plugin pushes at 06:49 UTC triggered Tier 1 Smoke runs across 7 plugin repos. Each runner pulled `ghcr.io/.../ktp-runtime-test-base:latest` within ~7 minutes of publish; GHCR's edge caches hadn't yet propagated the new manifest, so each smoke pulled the previous image (no HudObserver) → `Plugin file open error` → `assert-no-failed` failure across the entire fleet. Re-running ~8h later, after propagation settled, succeeded against the same `:latest` tag — confirming the failure was purely registry-side, not a code bug.

Two layers of defense added.

#### Changed — `.github/workflows/publish-base-image.yml` (Layer 1: publish-side propagation verify)
- New step `Verify :latest propagation` runs after `docker push :latest` and `:<short_sha>`. Both tags were pushed from the same local image and MUST resolve to the same manifest digest globally — the step polls `docker buildx imagetools inspect` for `:latest` and compares its manifest digest to `:<short_sha>`'s. Up to 6 attempts × 10s sleep; if `:latest` is still serving the previous manifest after 60s, the publish workflow fails rather than silently shipping a stale tag. Catches the most common race window cleanly.

#### Changed — `.github/workflows/smoke-callable.yml` (Layer 2: smoke-side fallback retry)
- Combined four sequential steps (`Boot ktp-game-1 container`, `Wait for server rcon-ready`, `Wait for plugins to finish initializing`, `Assert no failed modules or plugins`) into one composite step `Boot, wait, and assert (with single retry on fast-path)`.
- On first failure, if `inputs.use_base_image: true` (fast path), step tears down the container, force-removes the local copy of the base image, re-pulls from GHCR, rebuilds the smoke overlay using the existing under-test artifact at `${GITHUB_WORKSPACE}/.smoke-artifact/payload`, and retries the boot+assert sequence once. Slow path (`use_base_image: false`) builds the runtime image locally from source — it doesn't touch GHCR, so a failure there is real and isn't retried.
- Retry success is annotated with `::warning::` so the run is visibly flaky-recovered rather than silently passing.
- Real failures (under-test plugin compile bug, KTPAMXX runtime crash, etc.) still surface — they fail on first attempt AND on retry, terminating the workflow.

#### Why both layers
Layer 1 catches the publisher-side race (where `:latest` lookup at the same edge that pushed it might still be stale for a few seconds). Layer 2 catches the consumer-side race (where a smoke runner in a different region pulls `:latest` while THAT region's edge cache is still serving the previous manifest, even after Layer 1 verified propagation against ITS local edge). Together, the user-visible flake from this incident class becomes essentially zero, while real failures still surface unmasked.

#### Compatibility
Purely additive on the publish side. On the smoke side, the four-step → one-step refactor changes the workflow run's step structure visible in the GHA UI; no functional change for first-attempt-success runs (~99% of cases).

---

## [1.5.3] - 2026-04-29

### `scripts/ktp-scheduled-restart.sh` — plugins glob added

#### Fixed
- **Swap loop now covers `~/dod-*/serverfiles/dod/addons/ktpamx/plugins/*.new`**, in addition to the previously covered engine binaries, KTPAMXX dll, and modules. Without this, every `.amxx.new` plugin deployed to staging was invisible to the swap loop — the script would log `"No .new files pending — nothing to swap"` and servers would come back up running the old plugin versions despite a clean restart run.

#### Why
On 2026-04-29 03:00 ET, eight plugin updates were silently no-op'd by the swap loop (KTPHLTVRecorder 1.6.0, KTPMatchHandler 0.10.119, KTPCvarChecker 7.25, KTPFileChecker, KTPAdminAudit, KTPGrenadeDamage, KTPGrenadeLoadout, KTPPracticeMode, KTPScoreTracker). Discovered ~6 hours later via the post-activation monitoring routine, which file-size-checked HLTVRecorder against the v1.6.0 expected size (~19565 bytes) and saw the live `.amxx` was still pre-fix size (13771 bytes).

The swap loop iterates an explicit glob list, not a recursive glob — `bash`'s `*.new` doesn't recurse into subdirectories, and the `[ -f "$new_file" ] || continue` early-exit makes new-file-type drift silent. Documentation comments in the script and CLAUDE.md both listed the same three covered paths the script actually iterated, so grepping either for "is plugins covered?" didn't surface the gap. Independent verification requires observed runtime behavior (file size, version banner, `amx_ktp_versions` rcon), not text-grep against `*.md` and `*.sh`.

#### Changed
- Comment block (lines ~226-229 in `scripts/ktp-scheduled-restart.sh`, ~183-186 in `.example`) updated to enumerate all four covered paths.
- Glob array (line ~237 in `scripts/ktp-scheduled-restart.sh`, ~194 in `.example`) gained the `plugins/*.new` entry.

#### Compatibility
Idempotent — existing deploys without plugins/*.new files behave identically. Deploys that do stage plugin .new files now work as documented. The chmod +x applied post-mv to swapped files is a no-op on .amxx (which doesn't need executable bit) but harmless.

#### Recovery action
On 2026-04-29 ~14:00 ET, the eight staged plugins were activated fleet-wide via per-instance manual `mv` + LinuxGSM rolling restart (24 active instances, ~192 plugin swaps total). CHI:27019 (intentionally disabled per 2026-04-17 trial) still has all 8 `.new` files staged; the patched script will swap them correctly if/when that instance is re-enabled.

#### Backups
- All 5 game hosts retain pre-patch script as `~/ktp-scheduled-restart.sh.bak-20260429T140234Z-plugins-glob-fix`.

---

## [1.5.2] - 2026-04-28

### `scripts/hltv-api.py` v2.1 → v2.2

#### Added
- **`GET /hltv/<port>/state`** endpoint — returns HLTV recording state by parsing the last 5 minutes of `journalctl -u hltv@<port>` and walking newest-first. Recognizes four HLTV journal events: `Start recording to X.dem.` / `Already recording to X.dem.` / `Completed demo X.dem.` / `Recording to X.dem, Length N sec.`. `process_running` derives from `systemctl is-active`. Auth via existing `X-Auth-Key` header.
- **Response shape:** `{"recording": bool, "basename": str|null, "process_running": bool, "last_event": {"type": str, "age_sec": int}|null, "already_recording_warning": bool}`. The `already_recording_warning` flag is the bleed signal — true when HLTV's most recent journal event was the explicit "Already recording" line that indicates a silently-rejected record command.

#### Why
KTPHLTVRecorder 1.6.0 polls `/state` before issuing `record` to avoid the record-while-recording bleed (HLTV silently kept the original basename across match boundaries). Fleet-wide audit 2026-04-28 found 60 misfiled match keys / 350 files / 59 missing-h1 cases caused by this. Plugin-side fix lives in `KTPHLTVRecorder.sma`; this is the API half.

#### Changed
- Refactored `do_POST` / `do_GET` dispatch — pulled common path-parse + auth-check into helpers (`_parse_path`, `_check_auth`). Same external behavior; new `/state` slots in cleanly.
- Module-level helper `_parse_state(port)` — testable independently of the HTTP server. Tolerant of `journalctl` timeouts (returns safe "process up but state unknown" rather than blocking the client).

#### Compatibility
Purely additive. POST `/command` and `/restart` endpoints unchanged. Existing 1.5.x KTPHLTVRecorder plugins continue to work unmodified — they just don't poll the new endpoint. Older plugins receive HTTP 400 if they accidentally hit `/state`.

#### Backup
`/home/hltvserver/hltv-api.py.bak-20260428T124827` on the data server preserves the v2.1 binary for one-command rollback.

---

## [1.5.1] - 2026-04-12

### Updated
- **curl/Dockerfile** — Upgraded OpenSSL 1.1.1w (EOL) → 3.3.2, curl 8.5.0 → 8.11.1, c-ares 1.19.1 → 1.34.4
- **config.yaml.example** — Updated cluster definitions to match current infrastructure (Atlanta/Dallas/Denver/NYC/Chicago). Removed unused module paths (fun_ktp, engine_ktp, fakemeta_ktp).
- **README.md** — Updated server inventory table with all 5 locations and data server. Version bump to 1.5.1.

---

## [1.5.0] - 2026-03-08

### Variable Server Count + Co-located HLTV Support

Two new features for flexible deployments and LAN events.

### Added

#### `provision-gameserver.sh`
- **`--num-servers <N>` flag** — Configure any number of game server instances (default: 5). All port ranges (UFW, conntrack, CPU pinning) are computed dynamically from the count.
- **`--with-hltv` flag** — Sets up co-located HLTV proxies on the same machine as game servers. Installs HLTV directory structure, config generator, screen-based control script (`hltv-ctl.sh`), Flask API on port 8087, and systemd service. HLTV ports start at `MAX_PORT + 1` (e.g., 6 game servers = HLTV on 27021-27026).
- **Dynamic CPU pinning** — CPU map is generated based on `NUM_SERVERS` and available CPUs. Baremetal 6th+ server overflows to CPU 4 (housekeeping). VPS 4th+ server shares CPU 0.

#### `ktp-scheduled-restart.sh`
- **Dynamic port detection** — Scans `~/dod-*` directories at runtime to build port list. No more hardcoded `27015-27019` loops.
- **Dynamic CPU pinning** — CPU map generated at runtime based on detected server count and `nproc --all`.
- **Chicago server name** — Added 172.238.176.101 to IP-to-name lookup.

### Changed

#### `provision-gameserver.sh`
- UFW rules, conntrack bypass (immediate + rc.local), and summary output all use `$GAME_PORT_RANGE` instead of hardcoded `27015:27019`.

#### `clone-ktp-stack.sh`
- Embedded restart script template now uses dynamic port detection and `SCHED_FIFO 50` (was stale `chrt -r 20`).
- CPU pinning in embedded template is dynamically generated based on server count.
- All `/5` references replaced with `/$NUM_SERVERS`.

#### `ktp-scheduled-restart.sh`
- All `for port in 27015 27016 27017 27018 27019` loops replaced with `for port in "${PORTS[@]}"`.
- All `/5` and `-eq 5` references replaced with dynamic `$NUM_SERVERS`.
- Discord status messages use dynamic server count.

---

## [1.4.2] - 2026-03-07

### Filesystem & Bug Fixes

### Added

- **noatime mount option** — `provision-gameserver.sh` now enables `noatime` on all ext2/3/4 filesystems. Eliminates a write I/O for every file read, reducing SSD wear and removing intermittent latency spikes from atime writes hitting SSD garbage collection pauses. Applied immediately via remount and persisted in `/etc/fstab`.

### Fixed

- **`$NUM_CPUS` undefined variable** — `provision-gameserver.sh` used `$NUM_CPUS` for CPU isolation GRUB params before defining it. Added `NUM_CPUS=$(nproc --all)` before the check. Previously this silently skipped CPU isolation on fresh provisions.

---

## [1.4.1] - 2026-03-02

### CPU Pinning Audit Fixes

Fixes discovered during CPU pinning enforcement audit across all 5 servers.

### Fixed

- **Chicago restart script CPU map** — Deployed `ktp-scheduled-restart.sh` on Chicago had `[27018]=1 [27019]=2` (sharing with 27015/27016), conflicting with the timer's intentional `[27018]=0 [27019]=0`. Updated to match the timer.
- **`nproc` detection bug** — `ktp-scheduled-restart.sh` used `nproc` which returns only available (non-isolated) CPUs. On baremetals with `isolcpus=2,3,5,6,7`, this returned 3 instead of 8, incorrectly selecting the Chicago CPU map. Changed to `nproc --all`.

### Changed

- **scripts/README.md** — Replaced stale `ensure-priority.sh` and `setup_renice_cron.py` entries with `deploy-chrt-service.sh` and `profiling-report.py`. Added `ktp-apply-chrt.sh` to deployment locations table.

---

## [1.4.0] - 2026-02-27

### CPU Isolation + Per-Port Pinning

Upgraded all three infrastructure scripts from `chrt -r 20` (SCHED_RR, no CPU affinity) to per-port CPU pinning + `SCHED_FIFO 50` with auto-detection of baremetal vs VPS layout.

### Changed

#### `provision-gameserver.sh`
- **CPU isolation GRUB params** — Adds `isolcpus=2,3,5,6,7 nohz_full=2,3,5,6,7 rcu_nocbs=2,3,5,6,7` on baremetals (8+ CPUs)
- **IRQ affinity steering** — Steers all IRQs to housekeeping CPUs 0,1,4 (bitmask 0x13) via rc.local
- **Per-port CPU pinning** — `ktp-apply-chrt.sh` now pins each game server to a dedicated CPU based on port number
- **SCHED_FIFO 50** — Upgraded from `SCHED_RR 20` for stricter real-time scheduling
- **Auto-detect CPU layout** — 8+ CPUs = baremetal (5 dedicated game CPUs), 4 vCPUs = VPS (3 dedicated + 2 shared)
- **`taskset` in sudoers** — Added alongside existing `renice` and `chrt`

#### `deploy-chrt-service.sh`
- **Per-port CPU pinning** — Replaced blanket `chrt -r 20` with port-to-CPU mapping + `taskset`
- **`--chicago` flag** — Selects 4-vCPU layout for KVM VPS servers
- **SCHED_FIFO 50** — Upgraded from `SCHED_RR 20`
- **Pinning status check command** — Added to post-deploy instructions

#### `ktp-scheduled-restart.sh`
- **Per-port CPU pinning after restart** — Applies `taskset` + `SCHED_FIFO 50` immediately after server start
- **Auto-detect CPU count** — Uses `nproc` to select baremetal vs VPS CPU map

---

## [1.3.0] - 2026-02-19

### New York & Chicago Server Support

Extended provisioning and restart scripts for 5-location deployment.

### Changed

#### `clone-ktp-stack.sh`
- **New York & Chicago HLTV port mapping** - Auto-detects newyork (27035) and chicago (27040) base ports
- **`--sv-password` flag** - Sets sv_password in dodserver.cfg (for KTPSCRIM servers)
- **`--relay-url` / `--relay-secret` flags** - Configure Discord relay in scheduled restart script
- **Relay URL auto-detection** - Falls back to reading from discord.ini if flags not provided
- **HLTV config always created** - Creates hltv_recorder.ini from scratch instead of patching existing (prevents stale config)
- **dodx.ini auto-created** - Creates default `pdata_offset = 4` if missing
- **Server name prefix** - Uses `$SERVER_NAME_PREFIX` consistently (supports "KTPSCRIM" branding)
- **nice=-5 in common.cfg** - Adds process priority to new and existing installations
- **Updated Dallas IP** - 74.91.114.195 → 74.91.126.55 in restart script name lookup

#### `provision-gameserver.sh`
- **`mitigations=off`** - Added to GRUB for Spectre/Meltdown performance bypass
- **`nice=-5` in limits.conf** - Allows dodserver user to use negative nice values

#### `ktp-scheduled-restart.sh`
- **New York server name** - Added 74.91.123.64 → "KTPSCRIM - New York"
- **Updated Dallas IP** - 74.91.114.195 → 74.91.126.55

### Added
- **`OLDSERVERS.md`** - Decommissioned server reference (Atlanta VPS, Dallas VPS)
- **`scripts/profiling-report.py`** - Frame profiler report generator for all servers

---

## [1.2.0] - 2026-02-03

### Performance Optimizations & Ubuntu 24.04 Support

Major expansion of provisioning scripts with all performance optimizations from the bare metal deployment campaign.

### Added

#### Comprehensive Performance Optimizations in `provision-gameserver.sh`
- **Ubuntu 24.04 support** - Now detects and supports both Ubuntu 22.04 and 24.04
- **Memory optimizations:**
  - Transparent Hugepages set to `madvise` (eliminates khugepaged stalls)
  - THP defrag disabled (`never`)
  - Proactive memory compaction disabled
  - KSM memory deduplication disabled
  - MGLRU min TTL set to 1000ms (keeps hot pages longer)
- **Network optimizations:**
  - NIC offloading disabled (GRO/LRO/TSO) for lower latency
  - Conntrack bypass for game ports 27015-27019
  - Ring buffer and interrupt coalescing tuning
- **Dirty ratio tuning** - `vm.dirty_ratio=5` for reduced I/O stutter
- **C-state control** - ALL C-states disabled (`max_cstate=0`) for lowest latency
- **rc-local service** - Creates systemd service for Ubuntu 22.04+ compatibility

#### Real-Time Scheduling Automation
- **ktp-chrt.timer** - Systemd timer that applies `chrt -r 20` every 30 seconds
- **ktp-apply-chrt.sh** - Script that checks and applies real-time scheduling
- Handles server restarts automatically - no manual intervention needed
- Logs changes to syslog (`journalctl -t ktp-chrt`)

#### New Deployment Scripts
- **scripts/deploy-chrt-service.sh** - Deploy chrt timer to existing servers (run as root)

#### HLTV API Key Support
- **clone-ktp-stack.sh** - Added `--hltv-api-key` parameter for secure HLTV API authentication

### Changed

- **provision-gameserver.sh** - Major refactoring
  - Expanded from 13 to 17+ optimization steps
  - All optimizations now persist across reboots via rc.local
  - Creates sysctl.d config for persistent dirty ratio tuning
- **clone-ktp-stack.sh** - Added note about ktp-chrt.timer automatic scheduling

### Documentation

All optimizations are based on research documented in `docs/UBUNTU_OPTIMIZATION_RESEARCH.md`.

---

## [1.1.0] - 2026-02-01

### LinuxGSM Fix & Optimization Research

Added critical LinuxGSM bug fix documentation and Ubuntu optimization research.

### Added

- **docs/UBUNTU_OPTIMIZATION_RESEARCH.md** - Comprehensive 22.04 vs 24.04 comparison
  - Kernel and scheduler analysis
  - Network stack optimizations
  - Memory subsystem tuning
  - Prioritized recommendations

### Changed

- **ktp_gameserver_setup.md** - Added LinuxGSM monitor bug fix (HIGH PRIORITY)
  - Documents `command_monitor.sh` patch for lines 203-212
  - Prevents random server restarts during matches
  - Must reapply after `./dodserver update-lgsm`

---

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
