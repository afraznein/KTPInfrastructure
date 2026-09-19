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

The pattern is the same every time: **a component that is dead in a way its
watcher cannot see**. This table is the inventory that makes the next one
findable before it costs a match.

## How to read the matrix

- **Detected** — something observes the failure mode at all.
- **Alerted** — a human is told, without anyone going looking.
- **Remediated** — recovery happens without a human.

A row that is detected but not alerted is a report nobody reads. A row that is
alerted but not remediated is fine, and is most of this estate.

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
| `ktp-tier2-heartbeat` | itself; deliberately a data-server cron so it does not share fate with the GH runner it watches |
| `ktp-backup-watchdog` | itself; exists because a run that never happens produces no output |
| `ktp-demo-cleanup-auto` (30 min) | **nothing** |
| `ktp-perf-rollup-daily`, `ktp-spike-digest-daily`, `ktp-soak-verify-*`, `ktp-precache-audit-weekly`, `ktp-ac-retention`, `ktp-credential-carrier-purge`, `ktp-fastdl-*` | **nothing** |

## Data integrity

| Failure mode | Detected | Alerted | By what |
|---|---|---|---|
| Backup run does not happen | yes | yes | `ktp-backup-watchdog.sh` |
| Backup written but unrestorable | yes | yes | `ktp-restore-test.sh` — restores into a scratch DB and compares |
| Offsite copy missing | yes | yes | `ktp-db-offsite.sh`, `ktp-demo-offsite.sh` |
| HLStatsX ingest stalls | yes | yes | `hlstatsx-ingest-monitor.py` |
| Tier 2 suite goes quiet | yes | yes | `ktp-tier2-heartbeat.sh` |
| Perf spike signatures | yes | yes | `ktp-profile-aggregator` → MySQL → Discord, `posted_alert` dedup |
| Stats daemon rejecting the fleet's capture events | yes | yes | `ktp-data-server-health.sh`, `capture-loss:<event_type>` — trailing 24h per event type from `ktp_capture_health`, warn 5% / clear 2%, floor 200 received. Added after the 09-02→09-08 loss went six days unnoticed |
| Hits stop turning into damage (registration regresses) | yes (2026-09-18) | yes | `ktp-data-server-health.sh`, `hitreg-reg` — clean live-enemy trace hits vs `ktp_damage_events` within 300 ms, per finished 12-man half in `ktp_hitreg_quality` (KTPHLStatsX 036), trailing 48h, warn 10 / clear 5 per thousand missed, floor 300 hits. Measured normal 0–2. `hitreg-reg=stale` when 12-mans ran for 7d and none was scorable — the watcher saying it has gone blind, not a clean 100%. Lane B runs the same predicate pre-deploy (`check_hit_registration`) |

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
- Every incident that reaches this estate should end with a row in the table at
  the top of this document. That table is the argument for the whole file: five
  entries, five checks that exist now, and each one built after the outage that
  motivated it rather than before.
