# Runbook: what is alerted, and what is not

**Measured 2026-09-10** against the repo and against the live data server
(`neindataatl`), read-only. Rows marked **unverified** could not be checked from
a workstation and need a fleet-side look — see [Unverified](#unverified).

This file answers *what is watched*. [`ALERT_ROUTING.md`](ALERT_ROUTING.md) answers
*where it lands and how loud*, and carries the producer → lane table, the measured
per-producer volumes and the severity canon.

## Why this exists

Nine independent checks alert into Discord, each with its own state file, its
own fail-streak rule and its own cooldown. Every one of them was written well
and for a specific incident. What no document said, until this one, is which
failure modes are covered by *any* of them — so the only way to find a hole was
for something to break inside it and stay quiet.

That has happened five times, and each time the check that now exists was built
after the outage rather than before it:

| Date | What went unnoticed | For how long |
|---|---|---|
| 2026-08-10 | `hltv@27035` died inside `Proxy::Init`; the wrapper stayed alive so systemd read `active (running)` | 9h48m — the 12man played on NY 1 that evening was never recorded |
| 2026-08-16 | A scheduled backup run simply did not happen; cron firing nothing produces no output | 5 days, found by measuring the archive by hand |
| 2026-08-25 | `hltv-demo-renamer` wedged on a half-open SSH session and sat `active` | 53h; every match demo in the window went unrenamed and was purged |
| 2026-07-22 | LinuxGSM `command_monitor.sh` stopped parsing on the LAN box; monitor exited 2 every minute, silently | 9 days, including a 3h outage monitor sat through |
| 2026-08-12 | `ktp-render-banlist` ran every minute and failed every minute, keeping its exit timestamp fresh | Until the three-legged check was added |
| 2026-09-08→22 | Six AC evidence bundles were lost to aborted uploads; nginx logs the cause at `info`, below the default `error` level, so `api.ktpdod.com.error.log` has been 0 bytes since 2026-07-18 | The whole fortnight — found by reading the access log, not by an alert |
| 2026-10-07 | A match-half had 100% of eleven event types rejected. `capture-loss` was watching, running hourly, and silent: it averages a flat 24 hours, so the dead half landed under its 5% warn | Found by an evidence pass over the rows, not by the alert built for exactly this |

The pattern is the same every time: **a component that is dead in a way its
watcher cannot see**. The 10-07 entry is the variant worth knowing, because the
watcher existed and ran: **a check can be live, correct and still unable to see
the fault, because of the shape of its aggregation**. The two shapes that do
that are below the matrix legend. This table is the inventory that makes the
next one findable before it costs a match.

## How to read the matrix

- **Detected** — something observes the failure mode at all.
- **Alerted** — a human is told, without anyone going looking.
- **Remediated** — recovery happens without a human.

A row that is detected but not alerted is a report nobody reads. A row that is
alerted but not remediated is fine, and is most of this estate.

## Two shapes that make a `yes` in this matrix untrue

Both have already happened here, and neither leaves a gap a reader of the matrix
can see — the row says *alerted*, the check runs on schedule, and the fault goes
past it anyway. Test a new row against both before writing `yes`.

- **A cumulative counter under a windowed headline makes the worst night and an
  ordinary one produce the same number.** The headline is an average, and an
  average is the one statistic a localised fault cannot move. `capture-loss`
  summed a trailing 24 hours per event type and warned at 5%, so the match-half
  on 2026-10-07 that lost 100% of eleven event types divided by a day of healthy
  traffic and landed under the threshold. `disk-growth` hit the same shape from
  the other side — a magnitude bucketed into the alert key, so the set
  comparison read a rising rate as a recovery. **Keep the aggregate and add a
  leg at the granularity the fault actually has** (per half, per unit, per run),
  reduced to the worst one rather than the mean. Keep that leg's alert key
  constant and put the identity in the body, or the key ages out of the trailing
  window and announces a recovery for something that never recovered.
- **An alert threshold above everything ever observed is an alert that cannot
  fire.** It passes review, runs forever, and reports a clean estate. Set every
  threshold from the measured distribution of the thing it watches; when that
  distribution has not been measured, say so at the constant and name the one
  query that would settle it. A number borrowed from a sibling check is not
  evidence — a per-half rate and a 24-hour average are different distributions,
  and the same figure can be far too tight on one and unreachable on the other.
  A threshold worth keeping also has a test that goes red when somebody pushes
  it out of reach.

---

## Game fleet — 24 instances across 5 hosts

| Failure mode | Detected | Alerted | Remediated | By what |
|---|---|---|---|---|
| Game server process dies | yes | no | **yes** | LinuxGSM monitor cron, per host, per instance (`docs/LINUXGSM.md`) |
| Game server unreachable by A2S | yes | no | no | `support-web` poller, 60s, `DOWN_AFTER = 3` — a status page, not an alert path |
| Poller itself dies | yes | no | no | `status.py` `STALE_AFTER = 240` renders UNKNOWN rather than a green fleet |
| LinuxGSM monitor patch reverted by `update-lgsm` | **yes, new** | no | no | `ktp-monitor-patch-check.sh`, weekly via the fleet audit — nothing before PR #297 |
| Patched `command_monitor.sh` fails to parse | **yes, new** | no | no | same; this is the 2026-07-22 shape |
| HLTV proxy dies while its wrapper lives | yes | yes | no | `ktp-hltv-liveness.sh` — fail-streak plus alert cooldown |
| HLTV proxy bound but never connected to its game server | **yes, new** | **yes, new** | no | `ktp-hltv-liveness.sh` alerts when a proxy's newest `auto_*` demo goes stale; `hltv-restart-all.sh` counts a proxy only once it has connected. Before this, a proxy answering `Not connected.` passed both |
| HLTV instance coverage gap (27020-27044) | yes | yes | no | `ktp-data-server-health.sh`, hourly |
| Host disk or inode exhaustion | yes | yes | no | `ktp-fleet-health.sh` disk leg (2026-09-18), per host, every minute, 75% warn / 72% clear on bytes or inodes — needs the per-host rollout to be live |
| Configuration drift between hosts | yes | yes | no | `ktp-fleet-audit.sh`, Monday 05:00 ET, posts only NEW items |
| `~/restart-all-servers.sh` / `~/status.sh` drift | yes | no | no | `ktp-restart-drift.py` — read-only, **run by hand only, on no schedule** |
| Binary md5 drift from the repo baseline | yes | yes | no | fleet audit; **15 items open as of 2026-09-07** |
| A config set on the instances and never mirrored into `/home/dod/distribute` — reverted fleet-wide by the next push of that file, silently | **yes, new** | **yes, new** | no | `audit-distribute-drift.py`, weekly via the fleet audit. Nothing watched this before: the distributor is event-driven with no startup sync, so tree and fleet were compared only by hand. This is the 2026-08-19 `discord.ini` shape, and `ktp_maps.ini` / `users.ini` before it — see [`DISTRIBUTE_DRIFT.md`](DISTRIBUTE_DRIFT.md) |
| A deploy-tree file carrying per-instance data that no `excludePatterns` declares | **yes, new** | **yes, new** | no | same check, hazard leg — reported on every run, not only on a change |
| A push that reached part of the fleet and was never retried | **yes, new** | **yes, new** | no | same check, `partial` / `absent` shapes |
| A config KEY on the instances and in no source file — **deleted** on all 24 by the next push of that file | **yes, new** | **yes, new** | no | `audit-config-key-drift.py`, weekly via the fleet audit. The file-level check above calls this `discord.ini differs` and can say no more; this one names the key and reports which side is missing it. This is the exact half of the 2026-08-19 incident that broke match embeds — `discord_channel_id_default` was deleted, and a missing key is not an error anywhere in the stack — see [`CONFIG_KEY_DRIFT.md`](CONFIG_KEY_DRIFT.md) |
| A config KEY in the source and on no instance — **imposed** on all 24 by the next push | **yes, new** | **yes, new** | no | same check, `instance-missing`. Found `mp_clan_readyrestart` set in 34 source map configs and on no instance |
| A key-drift sweep that reached fewer than 24 instances, or could not parse a config | **yes, new** | **yes, new** | no | same check — a level, not a transition. Exit 2, and the gate fires every run. A partial sweep reported as clean is how the 2026-08-19 revert stayed invisible for six weeks |

## Data server — services

`ktp-data-server-health.sh` (hourly cron) and `OnFailure=` are two independent
paths, and a unit needs only one of them. `OnFailure=` fires the moment a unit
fails; the health check catches a unit that is down for any reason including one
that never "failed", and alerts on state transitions only.

| Unit | `OnFailure=` | In `CRITICAL_SERVICES` | Covered |
|---|---|---|---|
| `mysql.service` | yes | yes | yes |
| `nginx.service` | yes | yes | yes |
| `hlstatsx.service` | yes | yes | yes |
| `hltv-api.service` | yes | yes | yes |
| `ktp-ac-api.service` | yes | yes | yes |
| `ktp-file-distributor.service` | yes | yes | yes |
| `hltv-demo-renamer.service` | yes | yes | yes, plus two liveness legs |
| `ktp-profile-aggregator.service` | **no** | yes | yes — by the health check alone |
| `hud-observer.service` | yes | no | yes |
| `hud-observer-web.service` | yes | no | yes |
| `hltv-restart.service` | yes | no | yes |
| `ktp-identity-reconcile.service` | yes | no | yes |
| `ktp-hlstatsx-ingest-monitor.service` | yes | no | yes |
| `ktp-weekly-outliers.service` | yes | no | by design: exit 1 means a player-half scored at or above `--alert-z` this week, so the Monday alert IS the report's delivery; the report is at `/var/lib/ktp-weekly-outliers/latest.md` |
| `ktp-reports.service` | yes, once the unit from `systemd/` is reinstalled; the live unit has none | no | a failing run alerts; `ktp-reports.timer` is not in `CRITICAL_TIMERS`, so a timer that stops firing does not. The journal only says `exit-code`; the cause is in `/var/log/ktp-report-service.log` |
| `ktp-admin-bot.service` | **no** | **no** | not critical — operator ruling 2026-09-18; a `failed` exit is still caught by `failed-unit:` |
| `ktp-frag-diag-tail.service` | **no** | **no** | not critical — operator ruling 2026-09-18; a `failed` exit is still caught by `failed-unit:` |
| any other unit systemd calls `failed` | — | via `failed-unit:<name>` | yes — `systemctl --failed` is a producer for the health check since 2026-09-16 |

Both are long-lived daemons currently `active (running)`. The operator ruled
on 2026-09-18 that neither is critical: a clean exit or a stuck-inactive state
pages nobody, by decision, not by omission. A `failed` exit is still reported
once by the `failed-unit:` producer.

## Data server — timers and scheduled work

`CRITICAL_TIMERS` covers ten timers as of 2026-09-16; before that, three of ten.

| Timer | In `CRITICAL_TIMERS` | If it silently stops |
|---|---|---|
| `hltv-restart.timer` | yes | alerted |
| `ktp-render-banlist.timer` | yes | alerted, on three independent legs |
| `ktp-demo-publish.timer` | yes | alerted |
| `ktp-hltv-liveness.timer` | yes (2026-09-16) | **the HLTV liveness check stops and nothing notices** |
| `ktp-hlstatsx-ingest-monitor.timer` | yes (2026-09-16) | ingest monitoring stops silently |
| `ktp-weekly-outliers.timer` | yes (2026-10-05) | the weekly outlier report stops and nobody notices until someone asks why Monday was quiet |
| `ktp-stats-export.timer` | yes (2026-09-16) | exports stop; last file stays in place and reads healthy |
| `ktp-corpus-push.timer` / `-denver` | yes (2026-09-16) | corpus pushes stop silently |
| `ktp-roster-history-audit.timer` | yes (2026-09-16) | audit stops silently |
| `ktp-identity-reconcile.timer` | yes (2026-09-16) | the *service* has `OnFailure=`, so a failing run alerts; a timer that stops firing does not |
| `ktp-monday-reminder.timer` | **no** | reminder stops; human-visible |

The distinction that matters: `OnFailure=` fires when a unit **runs and fails**.
Nothing fires when a unit **stops running at all**. Five of the incidents in the
table at the top are that exact shape, which is why `CRITICAL_TIMERS` exists.
Only `ktp-monday-reminder.timer` is deliberately left out: a reminder that fails
to arrive is noticed by the people expecting it.

Cron-scheduled work is outside both mechanisms entirely:

| Job | Watched by |
|---|---|
| `ktp-data-server-health` (hourly) | **the next run of itself**, via the run ledger (2026-09-17): an aborted or missed run becomes `health-check-aborted` / `health-check-missed-runs` in the following completed run's report. A check that stops for good still says nothing on the box — `KTPAdminBot`#21's stale-state field (merged, not deployed) covers it in minutes, the weekly audit gate (2026-09-18) in days |
| `ktp-fleet-audit` (Monday 05:00 ET) | **nothing**; it does refuse to run against a non-git `/opt/ktp-infra` |
| `ktp-tier2-heartbeat` | itself; deliberately a data-server cron so it does not share fate with the GH runner it watches. ⚠️ **Diagnose it with `ktp-tier2-heartbeat.sh --dry-run`.** It alerts on transitions, so a run that saved a verdict computed without the cron file's environment can mask the next real change — the state write is armed by the cron file (or a cron parent) and by `--write`, and by nothing else |
| `ktp-backup-watchdog` | itself; exists because a run that never happens produces no output |
| `ktp-demo-cleanup-auto` (30 min) | **nothing** |
| `ktp-offsite` (Sunday 04:00 / 05:00 / 06:00): DB dumps, demos, AC corpus (bundles **and** weapon-context sidecars since 2026-10-05) | **nothing** — output goes to `/var/log/ktp-offsite.log` and no one is told when a leg fails. ⚠️ The sidecars ride the corpus leg, so a corpus-leg failure now loses both populations' copy for that week, and a missing or empty weapon-context store fails the whole leg before anything ships. The corpus leg (2026-09-25) adds a second blind spot on top of that: it encrypts to a key this host does not hold, so even a clean run only proves ARRIVAL. Nothing scheduled anywhere decrypts, and nothing can be scheduled here to, because that would put a private key on the one host the design keeps it off |
| `ktp-precache-audit-weekly` (Sunday 06:00 ET) | `ktp-data-server-health`, on the newest `/var/log/ktp-precache-audit-*.md` mtime against an 8-day ceiling (7d cadence + a day, so a late run is not a page and a missed Sunday is). Keyed on the report because the audit is silent on a green week, so its Discord post cannot distinguish "nothing to report" from "did not run" |
| `ktp-perf-rollup-daily`, `ktp-spike-digest-daily`, `ktp-soak-verify-*`, `ktp-ac-retention`, `ktp-credential-carrier-purge`, `ktp-fastdl-*` | **nothing** |

## Data integrity

| Failure mode | Detected | Alerted | By what |
|---|---|---|---|
| Backup run does not happen | yes | yes | `ktp-backup-watchdog.sh` |
| Backup written but unrestorable | yes | yes | `ktp-restore-test.sh` — restores into a scratch DB and compares |
| Offsite copy missing | yes | yes | `ktp-db-offsite.sh`, `ktp-demo-offsite.sh`, `ktp-corpus-offsite.sh` — each refuses an empty selection rather than reporting success over one; the corpus leg refuses an empty bundle set and an empty weapon-context store separately |
| Offsite weapon-context copy **stale** (current-version manifest on the far side not the one the run wrote) | yes | **no** | `ktp-corpus-offsite.sh` checks both current manifests on the far side by content after shipping them and fails the run on a mismatch — but nothing watches `ktp-offsite`, so only the log says so |
| Offsite AC corpus or weapon-context sidecars present but **unrecoverable** (wrong recipient, lost identity file) | **no** | **no** | `ktp-corpus-drill.sh` is the only thing that would catch it (it round-trips both populations, including a sidecar rewritten in place), and it runs where a private key is — the operator's machine, quarterly, by hand. ⛔ Do not close this by scheduling the drill on the data server |
| HLStatsX ingest stalls | yes | yes | `hlstatsx-ingest-monitor.py` |
| Tier 2 suite goes quiet | yes | yes | `ktp-tier2-heartbeat.sh` |
| Perf spike signatures | yes | yes | `ktp-profile-aggregator` → MySQL → Discord, `posted_alert` dedup |
| Stats daemon rejecting the fleet's capture events | yes | yes | `ktp-data-server-health.sh`, `capture-loss:<event_type>` — trailing 24h per event type from `ktp_capture_health`, warn 5% / clear 2%, floor 200 received. Added after the 09-02→09-08 loss went six days unnoticed. ⛔ **This leg is an average and cannot see one bad half** — that is what the next two rows are for |
| **One match-half** loses its events, on a day that otherwise looks fine | yes (2026-10-07, in the repo) | yes | `ktp-data-server-health.sh`, `capture-half-loss` — worst `(half, event_type)` in a trailing 24h by `emitted - daemon_accepted` over `emitted`, floor 200 emitted, one constant key with the half named in the body. Scored against the producer's own `emitted`, not against `daemon_received`, so a half that arrived as nothing scores 100% instead of 0/0. ⚠️ **Warn 50 / clear 25 are PROVISIONAL** — bracketed by migration 035's ~0.1% measured transit loss and the 10-07 half's 100%, not taken from the per-half distribution, which nobody has looked at. The query that would settle it is at the constant. **Open on the data server**: `scripts/` has no deploy workflow, so merging does not field it |
| A match-half **never reconciles at all** (health rows missing, not rejected) | yes (2026-10-07, in the repo) | yes | `ktp-data-server-health.sh`, `capture-half-unreconciled` — `ktp_capture_manifests` rows with no `ktp_capture_health` row after a 180-minute grace, warn 1. No rejection rate can see this: a missing row is not a 100% rate, and health rows travel the same one-way UDP path as the events. ⚠️ **Known false positive**: an abandoned half (map change mid-half, `.forcereset`, crash) never sends health either. **Open on the data server** for the same reason as the row above |
| Hits stop turning into damage (registration regresses) | yes (2026-09-18) | yes | `ktp-data-server-health.sh`, `hitreg-reg` — clean live-enemy trace hits vs `ktp_damage_events` within 300 ms, per finished 12-man half in `ktp_hitreg_quality` (KTPHLStatsX 036), trailing 48h, warn 10 / clear 5 per thousand missed, floor 300 hits. Measured normal 0–2. `hitreg-reg=stale` when 12-mans ran for 7d and none was scorable — the watcher saying it has gone blind, not a clean 100%. Lane B runs the same predicate pre-deploy (`check_hit_registration`) |
| AC evidence bundle never reaches the API (aborted upload) | yes (2026-09-23) | yes | `ktp-data-server-health.sh`, `ac-upload-abort` — a request on `/api/session/upload` that nginx answered itself (`urt=-`) with a 4xx/5xx, over a trailing 6h of `api.ktpdod.com.access.log`, warn 1. The discriminator is `urt`, never the status: a 400 the API produced carries a duration and is a rejected bundle, not a lost one. `ac-upload-abort=unmeasurable` fires when the window holds lines with no `rt`/`urt`/`rl` — the fields only exist from the 2026-09-16 `log_format` change, and a rotated file from before it scores 0 aborts out of real traffic |

---

## Holes

Ranked by what they would cost during Season 10.

1. ~~**No disk or inode alerting on the five game hosts.**~~ Closed in the repo
   2026-09-18: a disk leg in the per-minute `ktp-fleet-health.sh`, same
   thresholds and deadband as the data server. **Open on the fleet** until the
   changed script is rolled to all five hosts.
2. ~~**`CRITICAL_TIMERS` is three entries against ten timers.**~~ Closed
   2026-09-16: all ten live timers bar the Monday reminder are listed.
3. ~~**`ktp-admin-bot` and `ktp-frag-diag-tail` have no detection path at all**~~
   Ruled not critical, 2026-09-18. Not a hole; a decision.
4. **Narrowed 2026-09-17, not closed: the hourly health check now reports its own
   last run; the weekly fleet audit still reports nothing.** Both are watchers,
   and a watcher that stops looks exactly like a quiet estate — which is why the
   2026-08-31 abort ran for fifteen days before anyone asked why the channel had
   gone calm. `ktp-data-server-health.sh` keeps a run ledger, and the next
   completed run raises `health-check-aborted` (naming the line it died on) or
   `health-check-missed-runs`. **A run that dies still cannot speak for itself** —
   the following run speaks for it — so a check that stops for good is invisible
   from the box. Two external detectors: `afraznein/KTPAdminBot`#21's stale-state
   field (merged, **not deployed**, minutes), and since 2026-09-18 the weekly
   audit's gate, which triages a state file older than 6h and any item open more
   than 3 days — the latter being the ten-day identity-reconcile shape, which
   presence-reporting alone never surfaced.
5. **`ktp-restart-drift.py` runs on no schedule.** The drift it was written to
   find is real and, as of 2026-08-30, still open.
6. **Narrowed 2026-09-21, not closed: an age is only as old as the watcher that
   stamped it.** `since` in `/var/lib/ktp-data-server-health.json` is the first
   run of the health check that *saw* an item — a detection date. `systemctl
   --failed` only became a producer on 2026-09-16, so the identity-reconcile
   outage that began **2026-09-08 09:01:53** was stamped **2026-09-17 01:17:03**
   and the weekly gate aged it at **4 days against a 3-day threshold for a
   13-day fault**. The under-count is silent and runs the wrong way: a fault
   older than its watcher can sit under any threshold keyed on `since`
   indefinitely, and the two dates agreeing proves nothing because nothing ever
   compared them. The check now also writes **`fault_since`**, an onset taken
   from systemd's `InactiveEnterTimestamp` for `failed-unit:` items, clamped to
   `since` and carried forward so it only ever moves *earlier* — which makes the
   state file the only home for an onset that outlives journald (~2 days here)
   and syslog rotation (~1 week). `fleet-audit-gate.sh` and support-web's
   incidents list both age off it when present and fall back to `since`.
   **Sparse by design:** no other item class has a durable onset signal, and an
   absent entry means "nothing knows", never "no fault". Still uncovered — a
   periodic unit that fails, stays failed and fails *again* resets systemd's
   stamp, so the onset is a lower bound until this file has carried it once.
   The 09-08 date above was recovered from `syslog.4.gz` and exists nowhere the
   check can read.
7. **Partly closed 2026-09-23: an nginx log level is an alerting decision nobody
   made.** `ac-upload-abort` now reads the class that cost six evidence bundles.
   What stays open is the shape rather than the case: **every vhost on this box
   logs at the default `error` level**, so "client prematurely closed
   connection", "upstream prematurely closed" and the rest of the `info` tier are
   discarded at write time on all of them. `api.ktpdod.com.error.log` being 0
   bytes since 2026-07-18 reads as clean operation and means only that nothing
   loud enough to clear the level has happened. The access log rescued this one
   because `ktp_timed` happens to carry `urt`; **no other vhost logs `urt`**, so
   the same failure on `hud.ktpdod.com` or `admin.ktpdod.com` is still invisible
   in both logs at once. Raising a vhost to `info` is not the answer on its own —
   it is a disk-growth decision, and `ktp-data-server-health.sh` watches
   `/var/log` growth for the reason in its own comment.

   **Measured 2026-09-24, and now measured every run.** The shape is **22 server
   blocks, 1 covered, 21 not** — and the covered one is the `:443` half of the
   upload vhost. Its own `:80` twin inherits the shared `access.log` and
   `combined`, so **coverage is a property of the server BLOCK, not the
   `server_name`**: judging by name would report that vhost covered and hide the
   half that is not. Three `error_log` directives exist in the whole effective
   config and **none carries a level token**, which is what "every vhost logs at
   `error`" means concretely.

   Two further couplings, both of which make a silent zero cheaper than it looks.
   `log_format ktp_timed` is declared **inside the upload vhost's own file**; that
   works only because `sites-enabled` is included within `http{}`, so a second
   vhost adopting the format would depend on the first still being enabled.
   And `grep -r` over `sites-enabled` **does not follow symlinks** — most vhosts
   there are symlinks — so a survey done that way finds a fraction of the config
   and reads as complete. Derive from the effective config instead:

   ```bash
   nginx -T | grep -cE '^[[:space:]]*server[[:space:]]*\{'   # blocks, not files
   ```

   `ac-upload-abort` now carries this itself: the covered/uncovered split is in
   the hourly report line with the uncovered blocks named, and
   `=coverage-regressed` fires if a log in `AC_UPLOAD_URT_LOGS` stops resolving to
   a urt-capable format or stops being written at all. The gap above is printed
   and never alerted — an item that can only clear by editing nginx would latch
   down forever — but losing the *one* log the detector reads is a regression that
   nothing else catches: `=unmeasurable` only speaks while the window holds upload
   lines, and on a quiet night `scanned` is 0.
8. **Upload *volume* is unwatched.** `ac-upload-abort` counts uploads that failed,
   and cannot see uploads that never started — a client-side regression, a DNS
   change or a dead uploader all read as a quiet, healthy zero. Deliberately not
   built here: a naive floor would fire every weekday morning. It needs a
   seasonal baseline, which is `ktp-telemetry-export` territory.

### Open right now

`ktp-identity-reconcile.service` has been **failed since 2026-09-08 09:01:53
EDT** — six days as of 2026-09-14. Its `OnFailure=` alert *did* fire
(`ktp-systemd-alert@ktp-identity-reconcile.service.service`, `Result=success`,
same timestamp), so this is not a detection failure. The alert was delivered and
the unit is still failed.

That is §2.2 of the infra research handover stated as a live case rather than a
hypothetical: alerts land in a channel, nothing tracks open-versus-resolved, and
a fired alert with no acknowledgement is indistinguishable from a handled one.
The failure reason is not readable without journal access
(`krodssh` is not in `adm` / `systemd-journal`).

**And by 2026-09-14 it was not readable with journal access either.**
`journalctl -u ktp-identity-reconcile` returned `-- No entries --`: journald
here holds about two days against a weekly unit. This unit's stdout *is* its
report — it prints its `CRITICAL` lines and exits 1 to raise them — so rotation
destroyed the findings themselves, not a trace of them. **The alert having fired
is what makes that survivable**, and only by luck: the embed reached Discord,
and `ForwardToSyslog=yes` left a second copy in `/var/log/syslog.2.gz`, which is
where the 09-08 findings were recovered from. Neither is an archive — syslog's
own stanza is `rotate 4` with a `maxsize 1G` trigger firing every couple of days
here, so that copy expires within about a week of the run.

Fixed at the shared layer rather than in this unit, per the standing rule in
[`OBSERVABILITY_PLAN.md`](../../OBSERVABILITY_PLAN.md) (§ no new alerting
implementations): `ktp-systemd-alert` now appends every capture to
`/var/log/ktp-systemd-alert.log` before it attempts the POST, so a suppressed
alert, a relay outage and a rotated journal all still leave the output on disk.
**Read a failed unit's output there first** — the journal is the copy that expires.

## Unverified

These need the live fleet and could not be answered from a workstation —
`dodserver@` refuses the workstation key on all five hosts, `krodssh` holds no
private key, and `sudo` on the data server needs a password. The access model,
and why the weekly audit is the only path that reaches the fleet today, are in
[`FLEET_AUDIT_ACCESS.md`](FLEET_AUDIT_ACCESS.md).

1. Do the five game hosts carry a local disk/inode check this repo does not
   track? Hole 1 assumes not.
2. Is the LinuxGSM tmux patch currently in place on all 24 instances, and which
   LinuxGSM version is each host running? `ktp-monitor-patch-check.sh` answers
   this in one read-only sweep; it has not been run against production.
3. ~~Which Discord channels receive which alerts today?~~ **Answered 2026-09-15**,
   measured against all five game hosts and the data server: the full producer →
   channel table is in [`ALERT_ROUTING.md`](ALERT_ROUTING.md). Seven producers
   share `#ktp-crashes` (`1497957091107668070`), one of them — the admin bot's
   `ops_alerts` cog — posting through the Discord gateway rather than the relay,
   and `ktp-fleet-health.sh` on the game hosts posting to a raw webhook that no
   relay-side change reaches. **Still open: does anyone have notifications on
   outside working hours?**
4. What is the on-call expectation? The failed unit above suggests the honest
   answer is "whoever notices", which is worth stating explicitly rather than
   leaving as an assumption each person makes differently.

## Keeping this true

This document is a snapshot and will rot the way `expected-sysctls.conf` did
when a key went missing from it — silently, reading as coverage. Two habits keep
it honest:

- Adding a unit or a timer to the data server means adding a row here in the
  same change, with its detection path named. "It has `OnFailure=`" is a
  complete answer; "nothing" is also a complete answer, and a legitimate one.
- A row says who is *told*. Whether the run's findings are still readable next
  week is a separate question, answered once in
  [`UNIT_RUN_RECORDS.md`](UNIT_RUN_RECORDS.md) — a dated file per run under the
  unit's `StateDirectory=`. ⚠️ **A `Type=oneshot` unit with no
  `TimeoutStartSec=` makes a row here untrue in a third way**, on top of the two
  in the matrix legend: systemd disables the start timeout for `oneshot` by
  default, so a wedged run never exits, `OnFailure=` never fires, and the row
  reads *alerted* about a unit that has silently gone quiet. Measured
  2026-10-07: nine `Type=oneshot` units in `scripts/systemd/`, zero of them
  setting it.
- Every incident that reaches this estate should end with a row in the table at
  the top of this document. That table is the argument for the whole file: five
  entries, five checks that exist now, and each one built after the outage that
  motivated it rather than before.
