# Changelog

All notable changes to KTP Infrastructure will be documented in this file.

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
