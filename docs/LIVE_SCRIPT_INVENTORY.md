# Live script inventory — 2026-09-11

A snapshot, not a record: it was measured once, read-only, and goes stale the next time anything is
installed. `docs/DEPLOY_MANIFEST.md` is how installs get recorded from now on; this is the baseline that
existed before the manifest did.

**Update 2026-09-13.** The files marked UNTRACKED on 2026-09-11 are now in this repo, byte-identical to the
installed copies (re-hashed read-only that day), so their rows below read MATCH. `/etc/rc.local` on Atlanta and
Dallas was missing from the first pass; it is added below. Those two hosts start it through the distro unit
`/usr/lib/systemd/system/rc-local.service`, while Denver, New York and Chicago have an `/etc/systemd/system`
copy written by `provision-gameserver.sh`. None of these files is in a deploy manifest yet.

**Method.** On each host, every file reachable from a systemd unit's `Exec*=`, a cron entry, `/usr/local/{bin,sbin}`,
`dodserver`'s crontab or a running app's `/opt/<app>` tree was hashed. Each md5 was then looked up against every
historical blob of every same-named file in every KTP repo, and, where names differ, by git blob id. Controls on every
host: a known file hashed, and a nonexistent path reported missing.

**Strip CR before calling a file behind.** An md5 of a CRLF copy never equals the LF blob, so a file
deployed from a Windows checkout reads as DRIFT with the same text. `/opt/lan-web` once showed 31 files
"drifted" from `main` and every one was a CRLF-only difference from an old Windows-side deploy. Compare with
`tr -d '\r' < <file> | md5sum` against the blob, or `git hash-object --path=<repo path> <file>` inside a
checkout, which applies the repo's `eol=lf`. Plain `git hash-object` is not a neutral check: Windows
`core.autocrlf=true` strips CR and a Linux box does not.

| verdict | meaning |
|---|---|
| MATCH | byte-identical to a blob; the commit shown holds it |
| TEMPLATED | a filled `.example`; the commit is the template's last change before the file's mtime (inferred, not recorded) |
| GENERATED | written by an installer script, so no blob can equal it |
| DRIFT | a same-named source exists but no version of it has these bytes |
| UNTRACKED | no KTP repo holds a source for it |
| EXTERNAL | someone else's software we run unmodified (upstream HLstatsX, a collaborator's repo, the Actions runner) |
| THIRD-PARTY | LinuxGSM, not ours |

Files from private repos are counted, not named. Loose scripts in home directories that nothing runs, backups
left in `/usr/local/bin`, and distro files are excluded.

## SUPERSEDED and UNVERIFIABLE-PIN, and why the rows now carry them

`scripts/check-live-script-inventory.py` holds this file to the repo it points at, and
`.github/workflows/config-tests.yml` runs it unconditionally on every push and PR. Until it existed nothing
read this file at all, and a row from it was cited twice as the live revision of a script.

A row is a dated measurement, so the repo moving on does not make it false — it makes it **mute**. What was
missing was any way for a reader to tell a row that still describes the repo tip from one the repo passed
weeks ago, and the second kind kept getting read as current state. So a row whose source path has changed in
this repo since its pinned commit carries the token **SUPERSEDED**: *this row no longer says anything about
what the host runs today.* The checker asserts the token in both directions — missing on an overtaken row
fails, and present on a row whose pin is still current fails too, which is what stops the token becoming a
permanent silencer once someone re-pins a row.

⛔ **A SUPERSEDED row cannot be repaired from a checkout.** Re-pinning it means re-reading the file on the
host; guessing a newer commit would restate the same defect with fresher-looking numbers. The checker takes
an `md5sum`-format file off a host (`--live-md5`) and will verify the live half when given one — that is the
one path that closes a row rather than re-dating it.

🔴 **Some rows pin a commit that is NOT an ancestor of `main`, so nobody who clones this repo can check
them at all** — `63b45b20cc` (`ktp-demo-cleanup-auto.sh`) is reachable from no ref, and `471aab1c59`
(`ktp-demo-offsite.sh`) sits on an unmerged feature branch. Those carry **UNVERIFIABLE-PIN**; the checker
counts them, so read the count off a run rather than off this paragraph. *(`cf93488405`,
`ktp-data-server-health.sh`, was a third until 2026-10-10, when a host read re-pinned that row — see below.)*
🔑 **A pin is only provenance if a cloner can reach it**, and this was invisible
for weeks because the workstation that wrote the rows still held the dangling objects — the checker's first
CI run was the first time anything asked. Reachability is therefore the test, not whether the object happens
to be in your clone; those rows get no md5 and no supersession verdict, because a fresh clone cannot compute
one. ⛔ Re-pinning them needs a read on the host, same as a SUPERSEDED row.

## Two rows closed by a host read, 2026-10-10

✅ **`/usr/local/bin/ktp-data-server-health.sh` and `/usr/local/bin/ktp-hltv-liveness.sh` are re-pinned from a
read on the data server**, so both rows are current and carry neither token. The live `md5sum` of each path
equals the blob at its new pin, which is also the tip of that path on `main`: health `065f4ad7…` at
`1ae8b9c09f`, liveness `a6eb2520…` at `9aecea8752`. Controls on the probe: both real paths hashed, and a
nonexistent path under the same directory reported missing rather than silently skipped. The box's own
`ktp-install --report` agrees on both bytes and names the same source commits, and `NEIN-DEPLOY.md` records
the installs (`dpl-f806` for liveness, with `9d7072d0` → `a6eb2520`).

🔑 **THE TRAP THAT MADE THIS WORTH DOING, AND IT IS THE INVERSE OF THE ONE ABOVE: a SUPERSEDED row reads as
evidence that nothing was installed.** The health row was cited as the live revision and had to be walked back
(`changelog.d/2026-10-07-health-capture-per-half-leg.md`) — that is the documented direction. But the same row
was then cited the OTHER way: *the inventory still pins the superseded blob, so nothing was installed.* Both
installs had in fact happened, and the box's `ktp-install --report` had said so the whole time. ⛔ **A mute row
is mute in both directions.** ➡️ **`ktp-install --report` on the host is the current record; this file is a
baseline that predates it.** A row here settles nothing about the box without a read there.

## Data server

DRIFT 1, TEMPLATED 2, EXTERNAL 5, MATCH 116.

| path | md5 | verdict | source | note |
|---|---|---|---|---|
| `/usr/local/bin/ktp-fleet-audit.sh` | `d06bfaa2` | DRIFT | `KTPInfrastructure:scripts/ktp-fleet-audit.sh` | equals scripts/ktp-fleet-audit.sh@f219354d once one em-dash double-encoded (cp1252) in transit is undone; comment-only |
| `/opt/ktp-tier2-runner/curl_smoke.py` | `1e6564a0` | MATCH | `KTPInfrastructure:scripts/curl_smoke.py` @ `8d8fdccf21` | SUPERSEDED; full md5 `1e6564a0b43ce9c79f1d9eb0b5a31a28`; root 644; imports `tests.smoke.rcon` from the runner's `_work` checkout |
| `/usr/local/bin/ktp-identity-reconcile-fetch.sh` | `ad9a5f53` | MATCH | `KTPInfrastructure:scripts/ktp-identity-reconcile-fetch.sh` @ `8d8fdccf21` | full md5 `ad9a5f53f2d134aad40448ec7735e70c`; root 750; its unit files are versioned in a private repo; reads `GH_TOKEN` from the unit's EnvironmentFile |
| `/home/hltvserver/hltv-api.py` | `ae54529b` | TEMPLATED | `KTPInfrastructure:scripts/hltv-api.py.example` @ `fd9dd147e9` | SUPERSEDED; full md5 `ae54529b34cf0a978c4cdbf99100c4d7`, 16468 B, mtime 2026-08-08, `hltvserver:hltvserver` 755. Holds a live `AUTH_KEY`, so it can never be tracked verbatim; `scripts/check-hltv-api-drift.py` is how the two get compared. See § hltv-api drift. |
| `/opt/ktp-backup.sh` | `d99c6e9e` | TEMPLATED | `KTPInfrastructure:scripts/ktp-backup.sh.example` @ `aabb405c6b` |  |
| `/opt/hlstatsx/scripts/hlstats-awards.pl` | `c2c1f750` | EXTERNAL | — | upstream HLstatsX:CE, not carried in KTPHLStatsX |
| `/opt/hlstatsx/scripts/hlstats-resolve.pl` | `a2d98cd3` | EXTERNAL | — | upstream HLstatsX:CE, not carried in KTPHLStatsX |
| `/opt/hlstatsx/scripts/proxy-daemon.pl` | `7bc0f6c3` | EXTERNAL | — | upstream HLstatsX:CE, not carried in KTPHLStatsX |
| `/opt/hud-observer/backend/src/app.ts` | `b8e5e0c3` | EXTERNAL | — | KTPHudObserver, maintained upstream by a collaborator; equal to upstream main after LF normalisation |
| `/opt/ktp-tier2-runner/actions-runner/runsvc.sh` | `aa5d79f1` | EXTERNAL | — | GitHub Actions runner |
| `/opt/hlstatsx/scripts/selftest-getproperties.pl` | `ef4e9542` | MATCH | `KTPHLStatsX:scripts/selftest-getproperties.pl` @ `7ca69892b4` | an older version than the repo's tip |
| `/usr/local/bin/ktp-tier2-stack-drift.py` | `f5937dab` | MATCH | `KTPInfrastructure:scripts/ktp-tier2-stack-drift.py` @ `a029be244f` | SUPERSEDED; an older version than the repo's tip |

<details><summary>77 files match the tip of their source</summary>

- `/home/hltvserver/hltv-wrapper.sh` `26f31b0a` = `KTPInfrastructure:scripts/hltv-wrapper.sh` @ `5df1d26d2a`
- `/opt/hlstatsx/scripts/hlstats.pl` `7f0f6b57` = `KTPHLStatsX:scripts/hlstats.pl` @ `b87c490ba1`
- `/opt/lan-web/app/admin_audit.py` `6704d45d` = `KTPInfrastructure:sites/lan-web/app/admin_audit.py` @ `eabe94d2cc`
- `/opt/lan-web/app/audit.py` `0cd0645a` = `KTPInfrastructure:sites/lan-web/app/audit.py` @ `9ba20a7457`
- `/opt/lan-web/app/auth.py` `1cc366d6` = `KTPInfrastructure:sites/lan-web/app/auth.py` @ `683fea61cb`
- `/opt/lan-web/app/awards.py` `d87657e1` = `KTPInfrastructure:sites/lan-web/app/awards.py` @ `3fa56053bd`
- `/opt/lan-web/app/bracket.py` `8b798c41` = `KTPInfrastructure:sites/lan-web/app/bracket.py` @ `1d7d3df19f`
- `/opt/lan-web/app/common.py` `4b49eb7f` = `KTPInfrastructure:sites/lan-web/app/common.py` @ `6a0796b278`
- `/opt/lan-web/app/config.py` `9d5a4491` = `KTPInfrastructure:sites/lan-web/app/config.py` @ `683fea61cb`
- `/opt/lan-web/app/db.py` `5c378469` = `KTPInfrastructure:sites/lan-web/app/db.py` @ `eabe94d2cc`
- `/opt/lan-web/app/demos.py` `bdeae8b8` = `KTPInfrastructure:sites/lan-web/app/demos.py` @ `2fd6e8d0b4`
- `/opt/lan-web/app/ics.py` `4c27fbd7` = `KTPInfrastructure:sites/lan-web/app/ics.py` @ `e5e939b528`
- `/opt/lan-web/app/main.py` `b9dda92a` = `KTPInfrastructure:sites/lan-web/app/main.py` @ `4794d5e007`
- `/opt/lan-web/app/mapskip.py` `7a635947` = `KTPInfrastructure:sites/lan-web/app/mapskip.py` @ `a229c4be57`
- `/opt/lan-web/app/match_slugs.py` `ff3a4125` = `KTPInfrastructure:sites/lan-web/app/match_slugs.py` @ `4794d5e007`
- `/opt/lan-web/app/match_stats.py` `a7d5331b` = `KTPInfrastructure:sites/lan-web/app/match_stats.py` @ `4794d5e007`
- `/opt/lan-web/app/notify.py` `eb8ad8ac` = `KTPInfrastructure:sites/lan-web/app/notify.py` @ `683fea61cb`
- `/opt/lan-web/app/parse.py` `71f46795` = `KTPInfrastructure:sites/lan-web/app/parse.py` @ `683fea61cb`
- `/opt/lan-web/app/photos.py` `26b29e65` = `KTPInfrastructure:sites/lan-web/app/photos.py` @ `2fd6e8d0b4`
- `/opt/lan-web/app/placements.py` `3a172d08` = `KTPInfrastructure:sites/lan-web/app/placements.py` @ `9ba20a7457`
- `/opt/lan-web/app/schedule.py` `037fce25` = `KTPInfrastructure:sites/lan-web/app/schedule.py` @ `b74454da80`
- `/opt/lan-web/app/seeding.py` `35cb9653` = `KTPInfrastructure:sites/lan-web/app/seeding.py` @ `eabe94d2cc`
- `/opt/lan-web/app/site_gate.py` `91ab539a` = `KTPInfrastructure:sites/lan-web/app/site_gate.py` @ `4794d5e007`
- `/opt/lan-web/app/standings.py` `c7760a21` = `KTPInfrastructure:sites/lan-web/app/standings.py` @ `2ca2d4efaf`
- `/opt/lan-web/app/stat_awards.py` `9f223b0f` = `KTPInfrastructure:sites/lan-web/app/stat_awards.py` @ `eabe94d2cc`
- `/opt/lan-web/app/stations.py` `d22b760b` = `KTPInfrastructure:sites/lan-web/app/stations.py` @ `9ba20a7457`
- `/opt/lan-web/app/templating.py` `5e5fcff1` = `KTPInfrastructure:sites/lan-web/app/templating.py` @ `9ba20a7457`
- `/opt/lan-web/app/veto.py` `7b5b43b2` = `KTPInfrastructure:sites/lan-web/app/veto.py` @ `9ba20a7457`
- `/opt/lan-web/migrate.py` `b35332b7` = `KTPInfrastructure:sites/lan-web/migrate.py` @ `9ba20a7457`
- `/opt/lan-web/tools/backfill_thumbs.py` `79033be3` = `KTPInfrastructure:sites/lan-web/tools/backfill_thumbs.py` @ `2fd6e8d0b4`
- `/opt/lan-web/tools/lan_admin.py` `442231d8` = `KTPInfrastructure:sites/lan-web/tools/lan_admin.py` @ `9ba20a7457`
- `/opt/lan-web/tools/load_match_scoreboard.py` `5e7f98c0` = `KTPInfrastructure:sites/lan-web/tools/load_match_scoreboard.py` @ `4794d5e007`
- `/opt/lan-web/tools/reset_for_event.py` `7d6161fa` = `KTPInfrastructure:sites/lan-web/tools/reset_for_event.py` @ `9ba20a7457`
- `/opt/lan-web/tools/seed_awards.py` `f50f1f3a` = `KTPInfrastructure:sites/lan-web/tools/seed_awards.py` @ `2fd6e8d0b4`
- `/opt/support-web/app/a2s.py` `63edfac7` = `KTPInfrastructure:sites/support-web/app/a2s.py` @ `243dae2c7a`
- `/opt/support-web/app/config.py` `39d9c315` = `KTPInfrastructure:sites/support-web/app/config.py` @ `e4db6bab07` SUPERSEDED
- `/opt/support-web/app/hostname.py` `82766609` = `KTPInfrastructure:services/support-poller/app/hostname.py` @ `3e9e398e5d`
- `/opt/support-web/app/main.py` `261efac5` = `KTPInfrastructure:sites/support-web/app/main.py` @ `871d2365ae` SUPERSEDED
- `/opt/support-web/app/poller.py` `085d4d74` = `KTPInfrastructure:services/support-poller/app/poller.py` @ `3e9e398e5d`
- `/opt/support-web/app/relay.py` `f3258127` = `KTPInfrastructure:sites/support-web/app/relay.py` @ `871d2365ae`
- `/opt/support-web/app/reports.py` `dd91445d` = `KTPInfrastructure:sites/support-web/app/reports.py` @ `d194750f71`
- `/opt/support-web/app/season.py` `73c1c827` = `KTPInfrastructure:sites/support-web/app/season.py` @ `dbed070332`
- `/opt/support-web/app/status.py` `c833f872` = `KTPInfrastructure:sites/support-web/app/status.py` @ `871d2365ae`
- `/opt/support-web/app/store.py` `ea62f112` = `KTPInfrastructure:sites/support-web/app/store.py` @ `871d2365ae` SUPERSEDED
- `/opt/support-web/app/tickets.py` `b2f3f427` = `KTPInfrastructure:sites/support-web/app/tickets.py` @ `871d2365ae`
- `/opt/support-web/app/tiers.py` `99eff417` = `KTPInfrastructure:sites/support-web/app/tiers.py` @ `c7090f0e37` SUPERSEDED
- `/opt/support-web/tools/run_poller.py` `611b6827` = `KTPInfrastructure:services/support-poller/tools/run_poller.py` @ `8f6b61e2da` SUPERSEDED
- `/usr/local/bin/hlstatsx-ingest-monitor.py` `d6be6fca` = `KTPInfrastructure:scripts/hlstatsx-ingest-monitor.py` @ `78930bcf04`
- `/usr/local/bin/hltv-demo-renamer.py` `bc7e4a24` = `KTPInfrastructure:scripts/hltv-demo-renamer.py` @ `a26727c372`
- `/usr/local/bin/hltv-restart-all.sh` `036ed8ab` = `KTPInfrastructure:scripts/hltv-restart-all.sh` @ `a26f37f9ca` SUPERSEDED
- `/usr/local/bin/ktp-ac-retention.sh` `92e7926d` = `KTPInfrastructure:scripts/ktp-ac-retention.sh` @ `c4268ad113` SUPERSEDED
- `/usr/local/bin/ktp-backup-watchdog.sh` `46f2a66a` = `KTPInfrastructure:scripts/ktp-backup-watchdog.sh` @ `1545ceac6f` SUPERSEDED
- `/usr/local/bin/ktp-data-server-health.sh` `065f4ad7` = `KTPInfrastructure:scripts/ktp-data-server-health.sh` @ `1ae8b9c09f`
- `/usr/local/bin/ktp-db-offsite.sh` `b17911a5` = `KTPInfrastructure:scripts/ktp-db-offsite.sh` @ `4a1fa4be92`
- `/usr/local/bin/ktp-demo-cleanup-auto.sh` `b7ccf0e9` = `KTPInfrastructure:scripts/ktp-demo-cleanup-auto.sh` @ `63b45b20cc` UNVERIFIABLE-PIN
- `/usr/local/bin/ktp-demo-offsite.sh` `7bfe04b2` = `KTPInfrastructure:scripts/ktp-demo-offsite.sh` @ `471aab1c59` UNVERIFIABLE-PIN
- `/usr/local/bin/ktp-demo-publish.sh` `4e872dbb` = `KTPInfrastructure:scripts/ktp-demo-publish.sh` @ `0583d2ee4d` SUPERSEDED
- `/usr/local/bin/ktp-demo-retention.sh` `35f1244b` = `KTPInfrastructure:scripts/ktp-demo-retention.sh` @ `750f4f4441` SUPERSEDED
- `/usr/local/bin/ktp-fastdl-indexes.py` `91d9e391` = `KTPInfrastructure:scripts/ktp-fastdl-indexes.py` @ `0583d2ee4d` SUPERSEDED
- `/usr/local/bin/ktp-fastdl-prune-configs.sh` `1b2ba512` = `KTPInfrastructure:scripts/ktp-fastdl-prune-configs.sh` @ `e471b192dd`
- `/usr/local/bin/ktp-hltv-connection-ingest.py` `54b35fcf` = `KTPInfrastructure:scripts/ktp-hltv-connection-ingest.py` @ `ca6d4046de`
- `/usr/local/bin/ktp-hltv-correlate.py` `ae51ed0d` = `KTPInfrastructure:scripts/ktp-hltv-correlate.py` @ `ca6d4046de`
- `/usr/local/bin/ktp-hltv-liveness.sh` `a6eb2520` = `KTPInfrastructure:scripts/ktp-hltv-liveness.sh` @ `9aecea8752`
- `/usr/local/bin/ktp-organize-hltv-demos.sh` `42ca9ab8` = `KTPInfrastructure:scripts/ktp-organize-hltv-demos.sh` @ `220c9053b8`
- `/usr/local/bin/ktp-perf-rollup` `9bc872e1` = `KTPInfrastructure:scripts/ktp-perf-rollup.py` @ `1ea13102c7` SUPERSEDED
- `/usr/local/bin/ktp-post-reboot-verify.sh` `9fdebeab` = `KTPInfrastructure:scripts/ktp-post-reboot-verify.sh` @ `1545ceac6f`
- `/usr/local/bin/ktp-precache-audit` `608d24de` = `KTPInfrastructure:scripts/precache_audit.py` @ `fd9dd147e9` SUPERSEDED
- `/usr/local/bin/ktp-render-banlist.sh` `87750f7a` = `KTPInfrastructure:scripts/ktp-render-banlist.sh` @ `9a29f71952`
- `/usr/local/bin/ktp-restore-test.sh` `50e2ef66` = `KTPInfrastructure:scripts/ktp-restore-test.sh` @ `cb35963bcd`
- `/usr/local/bin/ktp-scheduled-kernel-reboot.sh` `9f5c6332` = `KTPInfrastructure:scripts/ktp-scheduled-kernel-reboot.sh` @ `b182ad4c23` SUPERSEDED
- `/usr/local/bin/ktp-soak-verify` `46545923` = `KTPInfrastructure:scripts/ktp-soak-verify.py` @ `a26727c372` SUPERSEDED
- `/usr/local/bin/ktp-spike-digest` `bba770a4` = `KTPInfrastructure:scripts/ktp-spike-digest.py` @ `a6b47ccca5` SUPERSEDED
- `/usr/local/bin/ktp-stats-export.py` `278b5584` = `KTPInfrastructure:scripts/ktp-stats-export.py` @ `50717a0d19` SUPERSEDED
- `/usr/local/bin/ktp-systemd-alert` `de1e2a92` = `KTPInfrastructure:scripts/ktp-systemd-alert.py` @ `7d17d5b28b` SUPERSEDED
- `/usr/local/bin/ktp-tier2-heartbeat.sh` `bcc990cf` = `KTPInfrastructure:scripts/ktp-tier2-heartbeat.sh` @ `be9b7f5ee7` SUPERSEDED
- `/usr/local/bin/ktp-verify-deploy` `54466b4c` = `KTPInfrastructure:scripts/ktp-verify-deploy.py` @ `fd9dd147e9` SUPERSEDED
- `/usr/local/bin/verify-hltv-demo-renamer.sh` `4049bbba` = `KTPInfrastructure:scripts/verify-hltv-demo-renamer.sh` @ `a26727c372`

</details>

Plus 35 live files from private repos, each matching a commit in its repo.

## Atlanta

GENERATED 1, TEMPLATED 1, MATCH 4, THIRD-PARTY 10.

| path | md5 | verdict | source | note |
|---|---|---|---|---|
| `/etc/rc.local` | `f7fe55f8` | MATCH | `KTPInfrastructure:ops/rc-local/atlanta/rc.local` @ `8d8fdccf21` | full md5 `f7fe55f8d489986412233664af6cf3f7`; root 755; same bytes as New York; missed on 2026-09-11, see the update note |
| `/usr/local/sbin/ktp-kernel-update.sh` | `c313dd98` | MATCH | `KTPInfrastructure:scripts/ktp-kernel-update.sh` @ `8d8fdccf21` | full md5 `c313dd98ee87208642d16d412f1d94f5`, same on all five hosts; root 700; one-shot, last ran 2026-08-25, nothing schedules it now |
| `/usr/local/bin/ktp-apply-chrt.sh` | `d4ffb423` | GENERATED | `KTPInfrastructure:scripts/deploy-chrt-service.sh` | written by an unquoted heredoc in deploy-chrt-service.sh with the host's CPU map expanded in |
| `/home/dodserver/ktp-scheduled-restart.sh` | `4c5297d2` | TEMPLATED | `KTPInfrastructure:scripts/ktp-scheduled-restart.sh.example` @ `582ead5608` | SUPERSEDED |

<details><summary>2 files match the tip of their source</summary>

- `/home/dodserver/ktp-fleet-health.sh` `8ea29f52` = `KTPInfrastructure:monitoring/fleet-health/ktp-fleet-health.sh` @ `90545573fc` SUPERSEDED
- `/usr/local/bin/ktp-report-core` `6fde1357` = `KTPInfrastructure:monitoring/crashreporter/report_core.py` @ `fd9dd147e9` SUPERSEDED

</details>

LinuxGSM: 10 files (the per-instance launchers and `lgsm/modules/command_monitor.sh`, one md5 each across instances).

## Dallas

GENERATED 1, TEMPLATED 1, MATCH 4, THIRD-PARTY 10.

| path | md5 | verdict | source | note |
|---|---|---|---|---|
| `/etc/rc.local` | `f7fe55f8` | MATCH | `KTPInfrastructure:ops/rc-local/dallas/rc.local` @ `8d8fdccf21` | full md5 `f7fe55f8d489986412233664af6cf3f7`; root 755; same bytes as New York; missed on 2026-09-11, see the update note |
| `/usr/local/sbin/ktp-kernel-update.sh` | `c313dd98` | MATCH | `KTPInfrastructure:scripts/ktp-kernel-update.sh` @ `8d8fdccf21` | full md5 `c313dd98ee87208642d16d412f1d94f5`, same on all five hosts; root 700; one-shot, last ran 2026-08-25, nothing schedules it now |
| `/usr/local/bin/ktp-apply-chrt.sh` | `d4ffb423` | GENERATED | `KTPInfrastructure:scripts/deploy-chrt-service.sh` | written by an unquoted heredoc in deploy-chrt-service.sh with the host's CPU map expanded in |
| `/home/dodserver/ktp-scheduled-restart.sh` | `4c5297d2` | TEMPLATED | `KTPInfrastructure:scripts/ktp-scheduled-restart.sh.example` @ `582ead5608` | SUPERSEDED |

<details><summary>2 files match the tip of their source</summary>

- `/home/dodserver/ktp-fleet-health.sh` `8ea29f52` = `KTPInfrastructure:monitoring/fleet-health/ktp-fleet-health.sh` @ `90545573fc` SUPERSEDED
- `/usr/local/bin/ktp-report-core` `6fde1357` = `KTPInfrastructure:monitoring/crashreporter/report_core.py` @ `fd9dd147e9` SUPERSEDED

</details>

LinuxGSM: 10 files (the per-instance launchers and `lgsm/modules/command_monitor.sh`, one md5 each across instances).

## Denver

GENERATED 1, TEMPLATED 1, MATCH 4, THIRD-PARTY 10.

| path | md5 | verdict | source | note |
|---|---|---|---|---|
| `/etc/rc.local` | `5384a5b8` | MATCH | `KTPInfrastructure:ops/rc-local/denver/rc.local` @ `8d8fdccf21` | full md5 `5384a5b81c13cc79feb957b3a7a70069`; root 755; differs from Atlanta/Dallas/New York only in the NIC name (`enp2s0f0`) |
| `/usr/local/sbin/ktp-kernel-update.sh` | `c313dd98` | MATCH | `KTPInfrastructure:scripts/ktp-kernel-update.sh` @ `8d8fdccf21` | full md5 `c313dd98ee87208642d16d412f1d94f5`, same on all five hosts; root 700; one-shot, last ran 2026-08-25, nothing schedules it now |
| `/usr/local/bin/ktp-apply-chrt.sh` | `d4ffb423` | GENERATED | `KTPInfrastructure:scripts/deploy-chrt-service.sh` | written by an unquoted heredoc in deploy-chrt-service.sh with the host's CPU map expanded in |
| `/home/dodserver/ktp-scheduled-restart.sh` | `4c5297d2` | TEMPLATED | `KTPInfrastructure:scripts/ktp-scheduled-restart.sh.example` @ `582ead5608` | SUPERSEDED |

<details><summary>2 files match the tip of their source</summary>

- `/home/dodserver/ktp-fleet-health.sh` `8ea29f52` = `KTPInfrastructure:monitoring/fleet-health/ktp-fleet-health.sh` @ `90545573fc` SUPERSEDED
- `/usr/local/bin/ktp-report-core` `6fde1357` = `KTPInfrastructure:monitoring/crashreporter/report_core.py` @ `fd9dd147e9` SUPERSEDED

</details>

LinuxGSM: 10 files (the per-instance launchers and `lgsm/modules/command_monitor.sh`, one md5 each across instances).

## New York

GENERATED 1, TEMPLATED 1, MATCH 4, THIRD-PARTY 10.

| path | md5 | verdict | source | note |
|---|---|---|---|---|
| `/etc/rc.local` | `f7fe55f8` | MATCH | `KTPInfrastructure:ops/rc-local/newyork/rc.local` @ `8d8fdccf21` | full md5 `f7fe55f8d489986412233664af6cf3f7`; root 755; same bytes as Atlanta and Dallas |
| `/usr/local/sbin/ktp-kernel-update.sh` | `c313dd98` | MATCH | `KTPInfrastructure:scripts/ktp-kernel-update.sh` @ `8d8fdccf21` | full md5 `c313dd98ee87208642d16d412f1d94f5`, same on all five hosts; root 700; one-shot, last ran 2026-08-25, nothing schedules it now |
| `/usr/local/bin/ktp-apply-chrt.sh` | `d4ffb423` | GENERATED | `KTPInfrastructure:scripts/deploy-chrt-service.sh` | written by an unquoted heredoc in deploy-chrt-service.sh with the host's CPU map expanded in |
| `/home/dodserver/ktp-scheduled-restart.sh` | `4c5297d2` | TEMPLATED | `KTPInfrastructure:scripts/ktp-scheduled-restart.sh.example` @ `582ead5608` | SUPERSEDED |

<details><summary>2 files match the tip of their source</summary>

- `/home/dodserver/ktp-fleet-health.sh` `8ea29f52` = `KTPInfrastructure:monitoring/fleet-health/ktp-fleet-health.sh` @ `90545573fc` SUPERSEDED
- `/usr/local/bin/ktp-report-core` `6fde1357` = `KTPInfrastructure:monitoring/crashreporter/report_core.py` @ `fd9dd147e9` SUPERSEDED

</details>

LinuxGSM: 10 files (the per-instance launchers and `lgsm/modules/command_monitor.sh`, one md5 each across instances).

## Chicago

GENERATED 1, TEMPLATED 1, MATCH 4, THIRD-PARTY 8.

| path | md5 | verdict | source | note |
|---|---|---|---|---|
| `/etc/rc.local` | `73286230` | MATCH | `KTPInfrastructure:ops/rc-local/chicago/rc.local` @ `8d8fdccf21` | full md5 `73286230706f9107f6ce1017005532c5`; root 755; the older `provision-gameserver.sh` layout plus appended `eth0` lines; no IRQ affinity block |
| `/usr/local/sbin/ktp-kernel-update.sh` | `c313dd98` | MATCH | `KTPInfrastructure:scripts/ktp-kernel-update.sh` @ `8d8fdccf21` | full md5 `c313dd98ee87208642d16d412f1d94f5`, same on all five hosts; root 700; one-shot, last ran 2026-08-25, nothing schedules it now |
| `/usr/local/bin/ktp-apply-chrt.sh` | `2352211a` | GENERATED | `KTPInfrastructure:scripts/deploy-chrt-service.sh` | written by an unquoted heredoc in deploy-chrt-service.sh with the host's CPU map expanded in |
| `/home/dodserver/ktp-scheduled-restart.sh` | `4c5297d2` | TEMPLATED | `KTPInfrastructure:scripts/ktp-scheduled-restart.sh.example` @ `582ead5608` | SUPERSEDED |

<details><summary>2 files match the tip of their source</summary>

- `/home/dodserver/ktp-fleet-health.sh` `8ea29f52` = `KTPInfrastructure:monitoring/fleet-health/ktp-fleet-health.sh` @ `90545573fc` SUPERSEDED
- `/usr/local/bin/ktp-report-core` `6fde1357` = `KTPInfrastructure:monitoring/crashreporter/report_core.py` @ `fd9dd147e9` SUPERSEDED

</details>

LinuxGSM: 8 files (the per-instance launchers and `lgsm/modules/command_monitor.sh`, one md5 each across instances).


## hltv-api drift — the box is BEHIND the example, not ahead

Measured 2026-09-15, read-only, with `scripts/check-hltv-api-drift.py` run on the data server against
`/home/hltvserver/hltv-api.py` (the file `hltv-api.service` actually execs — `ExecStart=/usr/bin/python3
/home/hltvserver/hltv-api.py`; there is no copy under `/usr/local/bin` or `/opt`, and a grep there returns
nothing and reads as "gone").

The example and the installed file diverge in **both** directions, which is why neither is simply stale:

- **The example is ahead on code.** v2.3 (2026-07-07) added `import sys` and a fail-fast that refuses to
  start on an empty key. The installed file does not have it. That guard has never been deployed.
- **The installed file is ahead on one comment** — the 2026-08-08 dual-key-close note — and is otherwise
  the v2.2 body with looser line wrapping. Its startup banner still prints `v2.2`.
- Everything else in the 243-line diff is comment and formatting churn. `hmac.compare_digest` is present
  on **both** sides, so the timing-safe compare is deployed.

⚠️ **The missing fail-fast is latent, not live.** The installed file assigns a non-empty `AUTH_KEY`
inline, so there is no empty key for it to fail open on today. The exposure is that the guard which makes
that safe by construction is absent — a future rotation that blanks the line, or a move to
`HLTV_API_KEY` with the env var unset, gets an API that authenticates any request with a missing header
on a `0.0.0.0` bind. Closing it means installing the v2.3 body and `systemctl restart hltv-api`, which is
the operator's call: `hltv-restart-all.sh` does **not** restart `hltv-api`.

⚠️ **The restart is a timing decision, not a technical one.** A mistimed `hltv-api` restart loses a demo
**permanently** — 1,568 API requests were measured in a 15-minute window with demos landing continuously.
There are three ways to do it: a session watches for a real lull and fires unattended; the operator accepts
the risk now; or it goes at 03:00 ET. ⚠️ **But `hltv-restart-all.sh` does not touch `hltv-api`, so "riding
03:00" still means someone runs the restart by hand at 03:00.** It is safe to leave indefinitely: the
missing guard is latent hardening, and a staged copy persists until someone acts.

**Verification controls used, so the "no leak" result means something.** The 32-character `AUTH_KEY`
value was extracted from the live file and counted: 1 occurrence in the file (the control is alive) and
**0** in the checker's 11,789 bytes of output. A nonsense token counted 0 in both. `grep -c AUTH_KEY` on
the live file returned 2.
