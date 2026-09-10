# Runbook: what is alerted, and what is not

**Measured 2026-09-10** against the repo and against the live data server
(`neindataatl`), read-only. Rows marked **unverified** could not be checked from
a workstation and need a fleet-side look — see [Unverified](#unverified).

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
| HLTV instance coverage gap (27020-27044) | yes | yes | no | `ktp-data-server-health.sh`, hourly |
| Host disk or inode exhaustion | **no** | **no** | no | **hole** — see below |
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
| `ktp-admin-bot.service` | **no** | **no** | **no — hole** |
| `ktp-frag-diag-tail.service` | **no** | **no** | **no — hole** |

Both uncovered units are long-lived daemons currently `active (running)`. If
either exits, nothing on this box says so.

## Data server — timers and scheduled work

`CRITICAL_TIMERS` covers three timers. The data server runs ten.

| Timer | In `CRITICAL_TIMERS` | If it silently stops |
|---|---|---|
| `hltv-restart.timer` | yes | alerted |
| `ktp-render-banlist.timer` | yes | alerted, on three independent legs |
| `ktp-demo-publish.timer` | yes | alerted |
| `ktp-hltv-liveness.timer` | **no** | **the HLTV liveness check stops and nothing notices** |
| `ktp-hlstatsx-ingest-monitor.timer` | **no** | ingest monitoring stops silently |
| `ktp-stats-export.timer` | **no** | exports stop; last file stays in place and reads healthy |
| `ktp-corpus-push.timer` / `-denver` | **no** | corpus pushes stop silently |
| `ktp-roster-history-audit.timer` | **no** | audit stops silently |
| `ktp-identity-reconcile.timer` | **no** | the *service* has `OnFailure=`, so a failing run alerts; a timer that stops firing does not |
| `ktp-monday-reminder.timer` | **no** | reminder stops; human-visible |

The distinction that matters: `OnFailure=` fires when a unit **runs and fails**.
Nothing fires when a unit **stops running at all**. Five of the incidents in the
table at the top are that exact shape, which is why `CRITICAL_TIMERS` exists —
it is just three entries wide against ten timers.

Cron-scheduled work is outside both mechanisms entirely:

| Job | Watched by |
|---|---|
| `ktp-data-server-health` (hourly) | **nothing — this is the watcher** |
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

---

## Holes

Ranked by what they would cost during Season 10.

1. **No disk or inode alerting on the five game hosts.** The data server checks
   both (`ktp-data-server-health.sh:236-237`). Nothing in this repo does the
   same for the hosts that write demos and logs during a match. The May 2026
   disk-full event is the shape of the cost. *(Repo-derived; a game host may
   carry a local crontab this repo does not track — see Unverified.)*
2. **`CRITICAL_TIMERS` is three entries against ten timers.** Most relevant:
   `ktp-hltv-liveness.timer` is unwatched, so the check built after the 9h48m
   HLTV outage can itself stop without anyone hearing about it.
3. **`ktp-admin-bot` and `ktp-frag-diag-tail` have no detection path at all** —
   no `OnFailure=`, not in `CRITICAL_SERVICES`.
4. **Nothing watches the hourly health check or the weekly fleet audit.** Both
   are the watchers, and a watcher that stops looks exactly like a quiet estate.
5. **`ktp-restart-drift.py` runs on no schedule.** The drift it was written to
   find is real and, as of 2026-08-30, still open.

### Open right now

`ktp-identity-reconcile.service` has been **failed since 2026-09-08 09:01:53
EDT** — two days, three days before Season 10 opens. Its `OnFailure=` alert
*did* fire (`ktp-systemd-alert@ktp-identity-reconcile.service.service`,
`Result=success`, same timestamp), so this is not a detection failure. The alert
was delivered and the unit is still failed.

That is §2.2 of the infra research handover stated as a live case rather than a
hypothetical: alerts land in a channel, nothing tracks open-versus-resolved, and
a fired alert with no acknowledgement is indistinguishable from a handled one.
The failure reason is not readable without journal access
(`krodssh` is not in `adm` / `systemd-journal`).

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
3. Which Discord channels receive which alerts today, and does anyone have
   notifications on outside working hours? The repo pins
   `ALERT_CHANNEL=1497957091107668070` (`#ktp-crashes`, consolidated with
   perf-rollup per the 2026-05-06 operator decision); the rest is routing this
   repo cannot see.
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
