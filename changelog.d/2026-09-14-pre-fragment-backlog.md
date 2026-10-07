### `scripts`: capture authorization is per stream, not per match (2026-09-14)

Operator ruling 2026-09-14. `evaluate_capture_authorization` marked a match
unauthorized on any non-zero drop, reject, correlation failure, sequence gap or
duplicate in any half, across all eleven streams together, and `build_report`
gated `objective_attempts` and `grenade_entities` on that one verdict. A frag
correlation failure therefore withheld the objective stream, whose own counters
reconciled exactly — and it withheld it silently.

Measured on the nine official S10 matches that have reports: one authorized
under the old gate; eight now authorize at least one stream that previously
published nothing. `objective_attempts` appears on six of them and
`grenade_entities` on five.

- **Unit of authorization: one stream, across every observed half.** Consumers
  query a stream for the whole match, so a per-half verdict would publish half 1
  and drop half 2 as an aggregate with nothing marking it partial.
- **Still per-match, still fails everything:** the manifest contract (schema 22+,
  the 2.00s cadence, the declared capabilities, activation receipt latency), the
  manifest and health half sets against the observed halves, and an unknown
  health type — a producer/daemon disagreement is not attributable to a stream.
- **`sequence_gap_count` and `duplicate_or_reordered_count` are HALF-scoped, not
  per-stream.** The daemon reads both from the per-half sequence state and
  stamps the same value into every event type's row, while
  `daemon_received`/`daemon_rejected`/`correlation_failure_count` are indexed by
  event type. Measured across 328 live halves: both are identical across all
  eleven streams in every half, and a sequence gap is non-zero on 133 halves
  where the stream emitted nothing. A sequence gap is UDP intake loss, and the
  daemon's own measurement is that it equals the sum of per-stream
  `emitted - daemon_received` — so it is charged to the stream that lost the
  line, and only a residual no stream accounts for fails the match. Charging the
  half total to all eleven would have left them coupled.
- **No loss tolerance.** One dropped, rejected or correlation-failed line still
  fails its own stream. What changed is only that it stops failing the others.
  Match-level `status`/`authorized` keep their old meaning exactly — every
  precondition holds and every stream reconciles — so consumers that read them
  are unaffected. The report DTO is unchanged (`analytics-report-dto-v1.2.0`,
  report schema 11); neither field crosses into it.
- **A withheld stream is visible with its reason.** `telemetry_lifecycles` now
  carries `status: withheld` with `stream` and `withheld_reason`, and the
  markdown renders the reason in place of the counts. Silent absence was the
  defect.
- New in the authorization result: `stream_authorization`, `authorized_streams`
  and `match_errors`; `errors` still carries every error. New helpers
  `capture_stream_status` / `capture_stream_authorized`. The result is embedded
  whole in the report JSON, so those keys do appear there — the artifact grows
  even though the validated DTO does not.
- Position provenance now rides on the `position` stream alone, and
  `match_readiness`'s objective and grenade lifecycle checks on theirs.
  `METRIC_REQUIREMENTS` drops `schema22_capture_authorization` from
  `positional_impact` and `objective_control`: their per-stream checks already
  fail on every match-level precondition, so keeping both would have left
  eligibility coupled while the checks beside it said otherwise. A new
  `position_capture_authorization` check carries `positional_impact` — dropping
  the match-level one alone would have loosened it, because
  `schema23_position_provenance` only reaches FAIL once a manifest declares
  schema 23, so a schema-22 archive with broken position capture would have
  graded WARN and stayed partially eligible.
- `lane_b_match_report`'s schema22 profile gate stays **match-level on purpose**
  and now says so: the profile declares it needs an authorized capture, and
  `prepare_lane_b_pages` hard-requires the `available` lifecycle shape, so
  splitting it per stream means teaching that validator the withheld shape in
  the same change.
- A half carrying a repeated or unknown health type credits no intake shortfall
  against its sequence gaps — a duplicated row would otherwise double-count one
  stream's loss and absorb a residual that belongs to nobody.
- krod's runbook step 3b ("lost and gaps 0 or close to it = OK") contradicts
  this: there is no "close to it". Flagged for him, not edited.

### `scripts`: `deploy-restart-script.py` refuses to ship a canonical that drifted from the tracked `.example` (2026-09-14)

The canonical `scripts/ktp-scheduled-restart.sh` is gitignored and untracked, so
`git status` can never flag drift in it and the deploy shipped whatever was sitting
in the working tree. Refreshing it by hand fixed that once; nothing prevented a
recurrence. A pre-flight content guard now runs before the SSH password is even
read, and refuses unless the canonical matches the tracked `.example` outside an
allowlist of `@hostinfo` assignment keys.

- Allowlist is `CHANNEL_KTP` and `CHANNEL_EXTERNAL`, matched by KEY, not by value
  or line number — which is what `docs/runbooks/SCHEDULED_RESTART_LINEAGES.md`
  already calls L2's entire licence to differ from L3.
- Pass condition: after folding line endings and trailing whitespace and masking
  both allowlisted values in *both* files, the two are line-for-line identical.
  Insertions and deletions therefore fail, in either direction.
- ⛔ Findings carry keys and line numbers only. A canonical line is never printed:
  the allowlisted values are live Discord channel IDs and this repo is public.
  `.example` lines are quoted, being tracked here already.
- Also refuses a canonical whose placeholders are still unfilled — that ships a
  script whose 03:00 Discord notification dies while the restart prints green.
- The `.example` is read from the git blob rather than the working tree. A
  checkout behind `origin/main` carries a stale one, and comparing against it
  fails on hundreds of lines that are not drift.
- Override is `--override-example-guard "<reason>"`, deliberately named rather
  than folded into `--force`; the reason prints above the deploy and an empty
  one is rejected.
- ⚠️ **It fails on today's real pair, and the drift is reported, not fixed:**
  `.example` carries a three-line comment about the socket-map sweep that the
  canonical lacks, and the canonical's md5 equals the fleet's, so all 24 hosts
  lack it too. `tests/unit/test_deploy_restart_example_guard.py` asserts that
  drift, so reconciling it fails the test loudly instead of passing in silence.

### `tier2`: pin the reviewed KTPMatchHandler build to 0.10.173 (2026-09-14)

The Tier-2 integration workflow pinned `b891b0e` (0.10.170). The fleet ran that
same build until the `wave-20260913T182820Z` swap activated 0.10.172 at the
03:00 ET restart on 09-14, so the pin became the stale half of a parity that had
held until then.

- Pin moves to `b3b3d93` (0.10.173, the `KTPMatchHandler`#37 merge), not to the
  0.10.172 the fleet currently runs. 0.10.173 is merged and unstaged, and it
  fixes an AC flush cursor rotation that duplicated and dropped shots; pinning it
  smokes the next build against current infra before it reaches a wave, which is
  worth more here than mirroring what is already deployed.
- One line. The asserted version is derived by `sed` from the pinned source, so
  the ref is the only thing to bump; `KTP_EXPECTED_MATCHHANDLER_VERSION` stays
  blank and follows the pin.
- No runner-side change: the workflow compiles the pinned source in test mode and
  `install -D`s it, so the artifact on the runner is replaced on the next run.
- The job path-filters itself and runs pytest only when `tests/integration/`,
  `tests/smoke/` or this workflow change. This PR touches the workflow, so the
  integration tests do run against 0.10.173 here.

### `scripts`, `ops`, `docs`: five scripts that ran only on the hosts are committed (2026-09-13)

Captured read-only on 2026-09-13 and committed byte-identical, so each installed copy's md5 equals its blob.

- `scripts/ktp-kernel-update.sh`: `/usr/local/sbin` on all five game hosts, one md5 everywhere. A one-shot
  `apt-get upgrade` then `systemctl reboot`, last run 2026-08-25 01:00-01:40 ET, with nothing scheduling it now.
  It sets no GRUB default, so it boots whatever entry 0 is; see `docs/runbooks/GRUB_DEFAULT_KERNEL.md`.
- `ops/rc-local/<host>/rc.local`: `/etc/rc.local` on all five game hosts. Atlanta, Dallas and New York
  share one file, Denver's differs only in the NIC name, and Chicago's is the older provisioner layout.
  None of the three matches today's `provision-gameserver.sh` heredoc.
- `scripts/ktp-identity-reconcile-fetch.sh`: the data server's `ExecStartPre` for `ktp-identity-reconcile.service`.
  It reads `GH_TOKEN` from the environment; nothing secret is in the file.
- `scripts/curl_smoke.py`: the KTPAmxxCurl boot/changelevel/quit smoke in `/opt/ktp-tier2-runner`. Its rcon
  password is a fixed value for a throwaway `sv_lan` server on 127.0.0.1.
- `docs/LIVE_SCRIPT_INVENTORY.md`: those rows now read MATCH with full md5s; Atlanta and Dallas `rc.local` added.
- Deploy: nothing changes on any host. The installed copies still need manifest rows (see the PR).

### `scripts`: the fleet audit redacts by shape before anything is published (2026-09-14)

`.github/workflows/fleet-audit.yml` posts the drift report to a GitHub issue and
uploads it as a run artifact. This repository is public, so both are
world-readable, and `fleet-drift-snapshot.sh` captures root's crontab and
`/etc/rc.local` **verbatim**. A credential ever written into a cron line would
publish itself on the first run, and a published artifact cannot be unpublished.
It has published once already. The first scheduled run, `34864628747` on
2026-09-14, uploaded `audit-report.md` and `audit-stdout.txt` unredacted to a
world-readable run artifact — `upload-artifact` is `if: always()`, so it ran even
though the job had already failed. That artifact has since been deleted. The
next scheduled run is 2026-09-21 09:00 UTC, which is the deadline this is
written against.

- New `scripts/audit_redact.py`. It redacts by SHAPE, never against a list of
  today's credentials: a denylist goes stale at the next rotation, and it goes
  stale in the direction that leaks. Nothing survives a redacted line that is
  the userinfo half of a URL, the right-hand side of an assignment whose NAME
  names a credential, the right-hand side of any shell env assignment inside
  root's crontab, or an opaque token (≥20 chars of `[A-Za-z0-9+=_-]` mixing
  upper, lower and digits, or ≥32 hex). A `$VAR` reference is kept: it is not a
  value, and whether a host inlines a credential is the drift worth seeing.
- It runs in `snapshot_payload()`, where the fleet's text enters the process —
  not on the report. The report is one of four things built from that text
  (report, Discord delta, state file, CI artifact), and redacting the report
  alone would still upload the value.
- The value half of every fact the `provision/expected-*.conf` sections compare
  is untouched: GRUB flags, sysctl values, 16-char binary md5 prefixes, LinuxGSM
  monitor states, and the `/etc/rc.local` lines the `expected-rc-local.conf`
  globs match. A redaction that ate those would turn the report green by
  blinding it. Measured read-only against three live hosts: one line changed per
  host (the root filesystem UUID, already ignored by rule), 15/15 rc.local globs
  and 6/6 cmdline flags still matching.
- Fleet addresses leave the report: the roster prints name and group only, and
  connection errors go through `redact_diagnostic()` in both
  `audit-fleet-drift.py` and `ktp-restart-drift.py`.
- This also narrows `/var/log/ktp-audit-*.md` on the data server, which the
  weekly cron writes `0644`.
- The redaction changes no workflow behaviour; the `set +e` fix below is the
  only workflow change here, and it is control flow, not policy. The
  `fleet-audit` label now exists. `CLAUDE_CODE_OAUTH_TOKEN` does not, and is the
  remaining gate — without it `triage` fails, though `collect` still runs and
  still uploads, which is why the redaction cannot wait on the token.

### `.github`: the fleet audit's `collect` job survives its own drift exit (2026-09-14)

Run `34864628747` — the workflow's first scheduled fire, ~6h50m late off the
09:00 UTC cron, which is GitHub queueing and not a dropped schedule — failed with
`Process completed with exit code 2`. The audit itself was fine: 5/5 hosts
reached, a normal drift result. The step was.

GitHub runs every `run:` under `shell: /usr/bin/bash -e {0}`, so errexit is on
before the script's first line. `set -uo pipefail` **adds** to that; omitting
`-e` does not clear it. The audit's normal drift exit `2` came back through
`pipefail`, and bash killed the step before `rc="${PIPESTATUS[0]}"` was ever
assigned — so the `case` never ran, `Audit found drift.` never printed, and the
gate, the triage and the Discord notice were all skipped.

- `set +e` in `Fleet drift audit`, so a drift exit reaches the `case`. Exit `1`
  stays fatal: a broken audit is not drift.
- Same clear in `Restart-script drift`, which carried the identical shape. No
  outcome changes there — its pipeline is the last command, so `pipefail` hands
  the step the same status either way and `steps.restart_drift.outcome` reads the
  same. Cleared for the shape, so the next line appended there does not vanish.
  `test_the_pre_fix_restart_step_reproduces_nothing` records that honestly.
- The step's comment named this trap while sitting inside it. It now says that
  errexit arrives already on, and names the run.
- The three `set -euo pipefail` steps are deliberate and untouched.
- New `tests/unit/test_fleet_audit_collect_step.py`, 11 tests. It extracts the
  scripts from the workflow file itself and executes them under `bash -e` with
  `python3` stubbed, so no copy of the step can drift from the shipped one.
  `test_no_step_enables_pipefail_without_clearing_errexit` states the property
  over *every* `run:` step, so a step added later carrying the shape fails here
  rather than on a Monday. The bug is the non-zero path, so
  `test_the_pre_fix_step_still_reproduces_the_failure` strips `set +e` and
  asserts the failure returns — against the pre-fix file the suite goes 6 failed
  / 5 passed, and the 5 that pass are the probe controls plus the `rc=0` happy
  path, which passed while the workflow was broken.

### `scripts`: the public demo archive is searchable by player (2026-09-14)

`ktp-fastdl-indexes.py` writes `/demos/players.html`: search by name, `STEAM_0:`/`STEAM_1:`,
bare `Y:Z` or SteamID64 to list every archived demo that player appears in, with
`players.html#STEAM_0:Y:Z` as a per-player permalink. The demos index links to it.

- One read-only `SELECT` per run against `hlstatsx.ktp_match_players` over the local
  `mysql` client (auth_socket, explicit `--user`, 5s connect timeout, 20s overall).
- Joined on the match id in the filename (`<epoch>-<SERVER>` or `1.3-<n>-<SERVER>`);
  a second server token is the recording HLTV and is ignored. Queue placeholder ids
  such as `1.3-confirm-NY2` never join, because they recur across unrelated matches.
- The lookup is the only part of the run that touches a database, so it is the only
  part allowed to go missing. A missing client, refused login, timeout, non-zero exit,
  no usable row, or nothing joining prints one `WARNING: player index omitted: …`,
  removes any earlier `players.html`, drops the link, and writes every other page as
  before; the run still exits 0. Malformed rows are skipped and counted.
- `--fastdl`, `--demos`, `--out-root` and `--db-timeout` exist so the generator can be
  tested against a temp tree and dry-run on the data server without writing in place.
- This deliberately makes the archive identity-bearing (operator ruling 2026-09-08:
  a SteamID may be a public search key).

### `support-web`/`support-poller`: default `public.json` path no longer names the deleted docroot (2026-09-14)

`PUBLIC_DEFAULT`/`public_json` in both `run_poller.py` copies and `app/config.py`,
plus `support-web.env.example`, still named `/var/www/support.ktpdod.com/status/public.json`
after that vhost's docroot was removed. `support-poller.service` loads
`/etc/ktp/support-web.env` with `EnvironmentFile=-…` (leading `-` ignores a
missing file), so if that env file ever vanished the poller would have silently
re-targeted the deleted path. The live `/opt/support-web` copies were already
corrected 2026-09-14 (no restart); this brings the repo default in line.

- Defaults now read `/var/lib/support-web/public.json` in
  `services/support-poller/tools/run_poller.py`, `sites/support-web/tools/run_poller.py`,
  `sites/support-web/app/config.py`, and `sites/support-web/deploy/support-web.env.example`.
- `sites/support-web/deploy/nginx-support.conf.example` is marked RETIRED — the
  `support.ktpdod.com` vhost's `sites-enabled` entry and docroot are gone from
  the data server, and delivery is now a direct push to ktpleague.gg rather than
  nginx serving a static file, so the example is kept as a historical record only.
- `tests/test_config.py`: added a case asserting the default never names
  `support.ktpdod.com`.

### Fixed: every capture-reading query excludes warmup bleed-through (2026-09-14)

The daemon tags a `ktp_flag_captures` row with the live match/half only if its
own `round_live` flag is set at the moment the capture *completes*. That flag
flips the instant `KTP_MATCH_START` fires, but a capture already in progress
from warmup can still finish a fraction of a second later and land fully
credited to the new half. A real capture needs several seconds of continuous
presence, so it can never complete in the same rounded second as the half's
own `start_time` -- every leaked row measured did.

Found auditing S10 day-1 production data: 2 of 1,049 captures on 2026-09-13,
76 of ~4,700 since August. Fixed everywhere the table is read for a live
report, not just the two queries found first:

- `sql/analytics/capture_credit_fact.sql`, `capture_event_fact.sql` (the
  per-flag and per-event breakdowns)
- `sql/analytics/cap_participation_fact.sql` (participation share)
- `sql/analytics/objective_timeline_fact.sql` (private shadow correlations)
- `sql/analytics/player_match_fact.sql`, `player_half_fact.sql` (the box
  score's own `capture_credits`/"Caps" column -- the field the report
  question that started this review was actually about)
- `sql/analytics/quality_inventory.sql` (so the `capture_grouping` quality
  check's raw counts match what the report actually shows)
- `scripts/lane_b_match_report.py`'s capture query for the accumulation
  scorer, which was clamping a bled-through row's time to 0 rather than
  excluding it, silently crediting `capture_points`/`conversion_points`

Two ad-hoc exploration scripts (`composite_v2.py`, `positional_baseline.py`,
both self-declared "not part of the test suite") and a handful of offline
tooling scripts that read the table from an already-dumped fixture for an
unrelated purpose (spatial atlas prep, retention, momentum research) were
left alone -- none of them are on the live report path.

### `scripts`, `systemd`: the wave ledger reconciles the restart, not the stage call (2026-09-14)

`ktp-wave-ledger.py reconcile` read only the artifacts a wave named, so a restart
that activated more than the ledger held reported "reconciled". The 2026-09-08
03:00 swap activated `stats_logging.amxx` and `ktp_cvar.amxx` 7.38 with only
`stats_logging` in the ledger, and the 2026-09-10 `ktp_cvar` 7.39 stage never
entered the ledger at all, so reconcile had nothing to say about it.

- `reconcile` now reads every pinned artifact and every staged `.new` on every
  instance, once, even when no wave is due, and leaves a wave open until the
  whole fleet agrees with `CLAUDE.md`. Findings: `UNLEDGERED_LIVE`,
  `LIVE_NOT_ON_ROW`, `ROW_NOT_LIVE` (the row's first md5 is on no instance),
  `NOT_UNIFORM` (partial activation) and `STAGED_UNLEDGERED` (a `.new` in no
  pending wave; it fails the run but does not hold an activated wave open).
- New `sweep` subcommand: the same read, marks nothing, for a timer. Exit 0
  clean, 1 finding, 2 could not look (unreachable instance, unreadable
  `CLAUDE.md`, no ledger without `--no-ledger`).
- `systemd/ktp-wave-sweep.{service,timer}`: 03:45 ET after the swap and 23:45 ET
  before it, `OnFailure=` alerting. Not installed.
- The three KTPAMXX artifacts now match their own rows (`KTPAMXX core`,
  `KTPAMXX dodx`, `stats_logging.amxx`). Against the current table they had
  fallen back to a file-wide md5 search.
- KTPFileChecker is `ktp_file.amxx` on the fleet, not `KTPFileChecker.amxx`.
  The first live sweep reported the row's md5 absent on all 24; `md5sum` finds
  it in `plugins/ktp_file.amxx`.
- Game instances only. The data server's artifacts are not swept.

### `scripts`, `docs`: a failed unit's output survives journald rotation (2026-09-14)

`ktp-identity-reconcile.service` failed on 2026-09-08 carrying a real finding —
exit 1 is how it reports a registry/anti-cheat identity divergence — and six days
later `journalctl -u ktp-identity-reconcile` returned `-- No entries --`.
journald on the data server is capped at `SystemMaxUse=1G`, whose drop-in comment
budgets "roughly 4 days at the measured ~230MB/day"; measured now, the journal
spans about two days, so the write rate has roughly doubled and nothing reported
that the window halved.

For a unit whose stdout **is** its report, that is data loss rather than a lost
trace. The findings were recovered from `/var/log/syslog.2.gz` — `ForwardToSyslog=yes`
had left a second copy — but syslog is `rotate 4` with a `maxsize 1G` trigger that
fires every couple of days on this box, so that copy expires about a week after
the run. Discord is not an archive either: the embed is unsearchable, the
per-unit cooldown drops repeats, and a relay outage loses it outright.

Fixed once at the shared layer instead of per-unit, per `OBSERVABILITY_PLAN.md`
(new checks become producers for an existing alerter, not new alerters):

- `scripts/ktp-systemd-alert.py` appends every capture to
  `/var/log/ktp-systemd-alert.log` — unit, result, exit code, sub-state,
  is-active, restart count and the journal tail under a UTC-stamped header.
  Written **before** the cooldown check and before the POST, so a suppressed
  alert, a failed relay and a rotated journal each still leave the output on
  disk. `append_alert_log()` swallows `OSError` and warns: losing the archive
  must never lose the alert, which is the same fail-open rule the cooldown
  writer already follows.
- The journal capture goes from 25 lines to 400, and only the **last 25** reach
  the embed — Discord's description cap is unchanged and so is the embed. A run
  that reports many findings is exactly the run whose tail must not be clipped,
  and that run is no longer the one that gets truncated.
- `--alert-log` overrides the path, so the capture can be exercised without
  writing to `/var/log`.
- `scripts/ktp-systemd-alert.logrotate` → `/etc/logrotate.d/ktp-systemd-alert`.
  Monthly, `rotate 12`, `maxsize 64M`, `delaycompress`, `create 0640 root root`,
  copying the `ktp-disk-history.logrotate` stanza. Retention is deliberately long
  — rotating this on journald's two-day horizon would rebuild the hole it fills.
  Also adopts `/var/log/ktp-systemd-alert-failed.log`, the POST-failure sentinel,
  which was unrotated.

Not built: no freshness check on the new artifact. Alerting on work done needs a
cadence to compare against, and this file is written only when something fails —
so an mtime gate would read `stale` forever on a healthy estate, which is the
`BANLIST_STALE_SEC` mistake `ktp-data-server-health.sh` already documents.

Deploy: `install -m 0755 scripts/ktp-systemd-alert.py /usr/local/bin/ktp-systemd-alert`
and `install -m 0644 scripts/ktp-systemd-alert.logrotate /etc/logrotate.d/ktp-systemd-alert`,
then `logrotate -d /etc/logrotate.d/ktp-systemd-alert` to confirm it is not
skipped — `/var/log` is group-writable here, and a stanza logrotate refuses is
silent (see `scripts/README-hltv-connection-logging.md`). No unit change, no
`daemon-reload`, no restart.

### `scripts`: grenade viewmodels return to the manifest at severity `review` (2026-09-13)

The 2026-09-13 ruling was revised the same day. `models/v_grenade.mdl`,
`v_mills.mdl` and `v_stick.mdl` stay allowed at any hash and must never be
scored — but a modified copy has to reach an admin again, and excluding them
could not do that. The client hashes only the paths the manifest lists, so an
excluded path is unobservable rather than forgiven: no comparison, no capture,
nothing in the bundle. `review` is the severity that separates the two, and it
is not new — `gfx/env/*` has shipped at it since 2026-08-27.

- `build-game-files-manifest.py` takes the three out of `EXCLUDED_EXACT` and
  into a new `REVIEW_EXACT`, which `severity_for` consults beside
  `REVIEW_PATH_PREFIXES`. `models/` cannot be a prefix rule without releasing
  the weapon kit, so the set is matched whole. Their explicit emit block comes
  back unchanged.
- **Operator ruling 2026-09-14: the two `ALTERNATE_HASHES` entries for
  `v_grenade` and `v_stick` are REMOVED, so every modified copy is captured —
  the known community pack included.** An `AllowedAlternateHashes` match hits
  `continue` before the `IsReview` branch, so an alternate is precisely what
  stops a copy being taken. Visibility is the point of the revised ruling, and
  "we already recognise this one" is not a reason to withhold its bytes.
  ⚠️ This supersedes an earlier revision of this entry, which kept them.
- That also squares the two allowlists. KTPAntiCheat dropped both paths from
  `KnownBenignFileVariants` once they became allowed at any hash; all three
  `BenignVariantManifestSyncTests` now pass against the regenerated manifest
  (checked by running their logic over AC `origin/main`'s table, not assumed) —
  6 manifest alternate pairs, 6 client pairs, identical. Keeping the alternates
  would have left `EveryManifestAlternate_IsAlsoInTheClientAllowlist` naming
  them, so the PR closes a guard rather than leaving one red.
- Capture volume: the three viewmodels are 262/332/220 KB, so a player with all
  three modified spends 0.79 MB of the 12 MB per-scan asset budget and 3 of its
  16-file cap (`afraznein/KTPAntiCheat`#207). Comfortable.
- `categorize()` now names the three `grenade_model` itself. The `.res` route
  called them `model_other` while the explicit route said `grenade_model`, and
  the dossier prints the category. Caught by the new tests, not by review.
- `p_`/`w_` grenade models are untouched and stay violations.
- Tests: 13, up from 9. They assert presence and severity together, because
  either alone passes for the wrong manifest.
- Deploy: regenerate and install `/opt/ktp-ac-api/game_files_manifest.json`
  (operator). The live manifest is still the pre-#346 one, so installing this
  changes three `severity` fields to `review` and removes two
  `allowed_alternate_hashes` lists — nothing else.

### `scripts`, `sql`, `config`: match reports carry kill streaks, per-side weapon and duel splits, and per-class rows (2026-09-14)

Builds items 1-5 of `docs/proposals/streaks-and-side-splits.md`. Report schema
10 -> 11, website contract `analytics-report-dto-v1.1.0` -> `v1.2.0` (additive;
a report built before schema 11 reads `status: unavailable`, flag
`not-in-report`, never zero).

- `player_halves.rows[]` gains `side` (the side the player held that half, from
  the life ledger) and `best_streak`. Cap breaks take `producer_half` when the
  archive carries it, instead of placement by event time.
- `kill_streaks` (`kill_streak_v1`, `scripts/kill_streaks.py`): best run of
  enemy kills between the player's own life ends, per half, per match
  (`players[]`) and per side (`players[].by_side`). Own teamkills neither count
  nor reset; a grenade landing after the thrower died counts toward the fresh
  counter; a frag with no producer clock takes the victim's death time when one
  unclaimed death boundary lies within 2 s, otherwise its row is `lower_bound`.
  Never the stock hlstatsx `kill_streak_N` actions. `players[].best_streak` is
  the match value.
- `weapon_sides` (`sql/analytics/weapon_half_fact.sql`): kills, headshot kills,
  shots, hits and damage per player per half per weapon, under the player's
  side, so picked-up enemy weapons stay on the player's side. `reconciled` says
  whether the rows sum back to `weapons[]`.
- `duels_by_side`: `duels[]` split by the killer's side, with `reconciled`.
- `player_classes`: lives, kills, deaths and headshot kills per class id read at
  spawn, labelled from `config/analytics/dod_classes.toml` (pinned against
  hlstatsx `killerRole` by a test). No accuracy per class: shots have no class
  or time at the source.
- Not built: clutches (naming ruling pending) and momentum per side (profile
  is still DRAFT).
- Deploy regenerates every in-season match at schema 11 on the next tick, and
  report_sync inserts them as new rows (the site reads the highest id).

### `lane-b`: apply the migrations the KTPHLStatsX ref under test carries (2026-09-14)

Lane B extracted a fixed migration list out of the KTPHLStatsX commit under
test, so every `main`-based KTPHLStatsX PR, and this repo's post-merge
`lane-b-corpus-main` run, failed at the build step with
`sql/migrate_028_shot_events_dedup.sql not found`: 028 onward exist only on
KTPHLStatsX `preprod`.

- `ArtifactSet.collect` lists the daemon commit's `sql/migrate_*.sql` and skips
  any `DEFAULT_SCHEMA_FILES` migration newer than the ref, printing a
  `::warning::` per skipped file and recording `schema_applied` /
  `schema_skipped` in the manifest.
- Still fatal: a gap (the ref carries a migration but not one that applies
  before it); a carried migration with no apply position in
  `DEFAULT_SCHEMA_FILES` and no reason in `NOT_APPLIED_MIGRATIONS`; a missing
  `ktp_schema.sql`, `hlstats.pl` or seed.
- The builder writes the applied migrations to `artifacts/schema-migrations.txt`
  and both `--schema` blocks in `lane-b-stats-e2e.yml` expand it, so
  `DEFAULT_SCHEMA_FILES` is the only list. The drift guard now fails if a
  literal migration path returns to the workflow.
- Adding a KTPHLStatsX migration: register it here first. Refs without it skip
  it; the PR that adds it then applies it.
- KTPHLStatsX's required check runs this workflow's YAML at a pinned sha but
  takes `tests/` and `scripts/` from this repo's `preprod`, so it picks up the
  builder change once `reconcile-preprod` fast-forwards `preprod`. The YAML
  half reaches that check only when the pin moves.

### `scripts/report_sync`: revalidate the site's match-report cache after a sync (2026-09-14)

A synced `ktp.match_report` row sat behind the site's `cacheLife("hours")` read
with nothing to tell it the data changed, so `/stats/matches` could take up to
about an hour longer than the pipeline itself to show a finished match.

- After a run that POSTs at least one new row, `report_sync.revalidate_site()`
  POSTs `{"scope": "ktp"}` to `https://ktpleague.gg/api/internal/revalidate`
  (header `x-internal-revalidate`), the narrowest of the endpoint's four
  POST-able scopes whose tag list carries `MATCH_REPORTS_TAG`.
- Reads its secret from `KTP_SITE_REVALIDATE_SECRET` at run time; unset logs
  one warning and skips. One retry on a transient failure (5xx, timeout); a
  4xx is not retried. Never raises, never changes the run's exit status, and
  never runs on `--dry-run` or when nothing changed.

### `scripts`: match reports carry the in-game result and per-half player rows; `mean_depth` unit stated (2026-09-13)

The public match report had to read its score from the website's `ktp.match`,
had match totals only, and rendered `depth_profiles.mean_depth` on a guess.
Report schema 9 -> 10, website contract `analytics-report-dto-v1.0.0` -> `v1.1.0`
(additive; the site accepts any `analytics-report-dto-v1.` prefix).

- `in_game_result`: per-half points, cumulative score and side per team, total
  and winner or `draw`, read from the game engine's team score in the HUD
  observer's settled `events.jsonl` through the importer's strict reader
  (`scripts/in_game_result.py`). It is the in-game score, not the
  captain-reported league result, and says so in `authority` and `notice`.
  The close of a half is its last `final` row; the 0/0 scoreboard reset at the
  start of half 2 is ignored; `ktp_match_end` is checked in half-1 side terms.
  Missing, late-starting, mis-carried or disagreeing streams publish
  `status: unavailable` with a flag and no score.
- `player_halves`: one row per player per closed half from
  `sql/analytics/player_half_fact.sql` (same tables as the box score; assists
  and cap breaks placed by event time), with `reconciled` saying whether the
  halves add up to the match totals.
- `lane_analytics.depth_profiles.units`: `mean_depth`/`depth_sd` are a fraction
  of the lane through the flag origins, 0 = own end, 1 = enemy end, clamped to
  [0, 1]; `lateral_mean` is world units.
- `report_service generate --observer-root` (default `/opt/hud-observer/matches`).
- The v1.1.0 contract doc also describes `ratings.ktpr_v2.display_scale`
  (#350), which shipped without a version change: a v1.1.0 row always
  carries it, a v1.0.0 row may not.
- Deploy regenerates every in-season match at schema 10 on the next tick, and
  report_sync inserts them as new rows (the site reads the highest id).

### `scripts`, `provision`, `docs`: game hosts rank lowlatency kernels by flavour instead of by menu position (2026-09-13)

Ubuntu's `10_linux` sorts kernels by version first, so a generic kernel published ahead of its
lowlatency twin becomes GRUB entry 0 and the first entry of the Advanced submenu. Both
`GRUB_DEFAULT=0` and the runbooks' `saved` + `1>0` canon boot it. Atlanta, Dallas and New York were
pinned on 2026-09-13 with `/etc/default/grub.d/99-ktp-kernel-flavour.cfg`
(`GRUB_FLAVOUR_ORDER="lowlatency"`) and `update-grub`.

- `scripts/fix-grub-default-kernel.sh` checks that the default entry boots the newest installed
  lowlatency kernel, for `GRUB_DEFAULT=0`, `saved` and menu paths by index, title or id, and
  predicts entry 0 after the next `update-grub` from the installed kernels and
  `GRUB_FLAVOUR_ORDER`. It no longer fails a correct `GRUB_DEFAULT=0` host as an unresolvable
  "positional literal". Title and id pins, indexes past the first entry, and a grub without the
  flavour patch are findings.
- `--fix` used to run `grub-set-default '1>0'`. It now writes the drop-in and runs `update-grub` on
  a `GRUB_DEFAULT=0` host, after copying `grub.cfg` to `/root`, then re-audits. It refuses every
  other shape and never reboots. New `KTP_GRUB_DEFAULT_DIR`, `KTP_GRUB_SORT_VERSION`,
  `KTP_UPDATE_GRUB` and `KTP_GRUB_BACKUP_DIR` overrides keep the tests off real paths.
- The tests run against GRUB files from Atlanta (before and after the pin), Chicago and Denver,
  with filesystem UUIDs replaced, in `tests/fixtures/grub_default_kernel/`.
- `provision-gameserver.sh` installs the drop-in and sets `GRUB_DEFAULT=0` instead of writing a
  menu title into `GRUB_DEFAULT`, and `lan-deploy.sh`'s reboot box gives the same fix.
- `docs/runbooks/GRUB_DEFAULT_KERNEL.md` is rewritten around the drop-in (apply, no-reboot check,
  rollback, risks). `docs/KERNEL_EXPERIMENT_RUNBOOK.md` drops its `grub-set-default '1>0'` steps.
  Both keep the old reasoning and say why it was wrong.
- Deploy: nothing to pull. Chicago still needs the pin, once console access is confirmed. Denver
  has no generic kernel installed.

### `scripts`: first-person grenade viewmodels leave the AC game-files manifest (2026-09-13)

Operator ruling 2026-09-13, "allowable to be modified (for now)":
`models/v_grenade.mdl`, `v_mills.mdl` and `v_stick.mdl` only change what a
player sees in their own hands, so a modified copy is no longer a violation.
The held (`p_`) and thrown (`w_`) grenade models are seen by other players
and stay enforced.

- `build-game-files-manifest.py` puts the three viewmodels in
  `EXCLUDED_EXACT` and applies that set to `ktp_file.ini` as well as `.res`
  references. Their explicit emit block and their two `ALTERNATE_HASHES`
  entries are gone. They are excluded outright rather than downgraded,
  because the client treats every severity except `review` as a violation,
  and `review` copies the player's file into the session bundle.
- The note that the viewmodels were in scope "to match ktp_file.ini" was
  stale: KTPFileChecker dropped them from `ktp_file.ini` in `1bf59f6`.
- `test_game_files_manifest_scope.py` offers the viewmodels through every
  source and asserts they stay out, and that all six `p_`/`w_` grenade
  models are still `grenade_model` violations.
- Deploy: regenerate and install `/opt/ktp-ac-api/game_files_manifest.json`
  (operator). KTPAntiCheat's `KnownBenignFileVariants` still lists
  `v_grenade`/`v_stick`; its `Manifest=required` sync test will name them
  as untracked until they are removed there.

### `scripts`: `report_service generate` reports a match only once every half has closed (2026-09-13)

`ktp_matches` holds one row per half, and discovery tested `end_time` per row,
so a match qualified as soon as its first half closed. On the first S10 night
the 15-minute timer wrote four reports during half breaks or second halves:
three failed quality, and one, written 22 seconds before its second half began,
passed as a one-half match and was published. A written report was never
regenerated, because discovery only looked for matches with no report at all.

- Discovery aggregates per match: no half may be open, and the last half must
  have closed at least `SETTLE_MINUTES` (20) ago. The longest official half
  break on record was 12.6 minutes; the timer adds at most one tick on top.
- A match is rediscovered when no report at the current schema was generated
  after its last half closed, so a partial report gets the next revision.
  Once that revision exists the match is not picked again.
- `excluded_by_match_type()` shares the builder and applies the same gate.
- `verify_report_pipeline`'s DRAINED check measures the settle window from the
  run, in server-local time. It had compared a UTC ceiling with the local
  `start_time`.
- Deploy: pull `/opt/ktp-reports/KTPInfrastructure` forward. The stuck reports
  regenerate on the next tick after their match settles.

### `sql`: the official team-score ledger names the HUD observer as its producer (2026-09-13)

`ktp_team_score_observations` holds the engine's team score as relayed by the
HUD observer (KTPHudObserver), not the captain-reported league score in the
website's database. Nothing in the table said so: `source` names what the value
is, and the table comment read "official engine team-score observations".

- New `sql/migrate_032_team_score_producer.sql` adds `producer VARCHAR(32)`
  (ascii, NOT NULL) to `ktp_team_score_observations` (after `source_version`)
  and `ktp_team_score_ingest_manifests` (after `source_server`), with CHECK
  constraints pinning it to `KTPHudObserver`. Both table comments now say the
  score is relayed by the HUD observer and is not the captain-reported league
  score.
- 032 is idempotent, refuses any shape other than migration 023's, finishes a
  partial run, and verifies its result. Existing rows are backfilled by the
  column default, which is then dropped so a writer has to name the producer.
- Migration 023's verifier now accepts the post-032 shape as well as its own,
  so re-running 023 (including via `--migrate`) still passes after 032.
- The importer writes `producer` explicitly into both ledgers. `--migrate`
  applies 023 then 032, and `--migration` is repeatable and replaces that list.
  Lane B loads both.
- Apply order: a fresh database gets 023 then 032. Production `hlstatsx`
  already has 023 and needs 032 through the migration queue before its first
  import.

### `scripts`: `report_sync` sends an explicit `--user` to mysql, like `report_service` (2026-09-13)

`ktpreports` authenticates by `auth_socket` and has no `.my.cnf`. Without
`--user`, the mysql client sends `root` even under `sudo -u ktpreports`, and the
server refuses with `ERROR 1698`. `report_service` has sent the flag since the
#313 correction; `report_sync.mysql()` never did, so the runbook's manual
`sudo -u ktpreports … report_sync --dry-run` could fail that way. The timer is
unaffected: under `User=ktpreports` its log shows no 1698.

- `report_sync.mysql()` passes `--user=<effective user>` using
  `report_service._os_user()`, which reads `pwd.getpwuid(os.geteuid())`. Under
  the timer that resolves to `ktpreports`, the account it already runs as.
- A uid with no passwd entry raises before mysql runs rather than dropping the flag.

### `scripts`: `report_sync` retries a transient Supabase read instead of failing the tick (2026-09-13)

`ktp-reports.service` failed 18 of 200 runs in the week to 2026-09-12, every one
an `HTTP Error 504: Gateway Timeout` on a PostgREST GET (`match_report` or
`season_aggregate`) against an empty table, arriving about five seconds in. No
POST has ever failed. Nothing was lost, since the next tick re-reads, but each
failure was an unalerted red run.

- `supabase()` retries a GET on 500/502/503/504, a timeout or a dropped
  connection, sleeping 5s, 15s and 45s between attempts, and logs each retry to
  stderr. After the last attempt the error is raised, so the run still exits
  non-zero during a real outage.
- A 4xx is never retried, and neither is a POST: a gateway 504 does not say
  whether the insert committed, and the next tick's read-then-diff is the safe retry.
- `ktp-reports.service` gains `OnFailure=ktp-systemd-alert@%n.service`. It needs
  a reinstall of the unit to take effect.
- The `__main__` guard restores the stock excepthook. Ubuntu's apport hook
  builds its path from `sys.argv[0]`, which is `-m` under `python3 -m`, and its
  own `FileNotFoundError` doubled every traceback in the log.

### `scripts`: the team-score importer refuses `--migrate` without an explicit `--database` (2026-09-13)

`import_team_score_events.py` defaults `--database` to the LAN schema
`hlstatsx_lan`. On the production data server, `--migrate` with that default
would create the ledger tables in the wrong schema and import into them,
reporting success, while production `hlstatsx` already carries migration 023.

- `--migrate` now exits 2 unless `--database` is given. Without `--migrate`, the
  default is unchanged, and the documented LAN command already passes
  `--database hlstatsx_lan`.
- `docs/OFFICIAL_TEAM_SCORE_TELEMETRY.md` gains a production section: pass
  `--database hlstatsx`, never `--migrate`, run `--validate-only` first, and
  pre-filter the inputs, because one bad file fails the whole batch.

### `scripts`: `sync-runner-stack.py`'s "not during a run" guard can fire now (2026-09-12)

The guard ran `pgrep -af '<runner tree>'` and looked for `hlds_linux` in the
output. The Tier-2 harness starts `./hlds_linux` from inside the tree
(`tests/smoke/boot_subprocess.py`: `cwd=serverfiles`), so the tree path is in
no command line and the guard never matched a live run.

- The probe now lists every `hlds_linux` process and resolves its
  `/proc/<pid>/exe` and `cwd`; a process is in the runner tree if either one is.
  The tree path itself is resolved with `readlink -f`.
- It fails closed: a probe that returns nothing (a dropped session) is reported
  as a blocker, and a process whose exe and cwd are both unreadable counts as busy.
- `config-tests.yml` now installs `paramiko`. `tests/unit/test_sync_runner_stack.py`
  importorskips it, so until now that whole file was skipped in CI.
- Tests cover a relative launch, a sibling directory sharing the prefix, a replaced
  binary still mapped, an unreadable process and an empty probe, plus a Linux-only
  end-to-end test that starts a real `./hlds_linux` from inside a temp tree.

### `scripts`: the report sync and aggregate now apply generate's match-type rule too (2026-09-11)

`generate` only discovers official matches (`.ktp` 0, `.ktpOT` 4), but an
explicit `generate <match_id>` bypasses discovery, and `aggregate` and
`report_sync` checked only the date floor. A test report for a real scrim or
12man played on or after the floor would have been pooled into the season and
pushed to Supabase, where the sync never deletes it.

- `OFFICIAL_MATCH_TYPES` and the scope test move to `scripts/report_scope.py`,
  and generate, aggregate and report_sync all use it. A report is in scope only
  if its match has an official-type half that started on or after `--since`:
  the same per-half test generate's discovery applies. NULL types stay out.
- Out-of-scope reports are held back and counted:
  `held back by match_type (official only: 0, 4): N`.
- `generate <match_id>` warns when an explicit id has no `ktp_matches` row or no
  official-type half. It still persists the report, since that is how the
  pipeline is tested.
- No unit change: updating the checkout is the whole deploy.

### `scripts`: the report sync and aggregate now honour the season floor too (2026-09-11)

`ktp-reports.service` scoped only `generate` to `--since 2026-09-13`. `aggregate`
pooled, and `report_sync` pushed to the website, the latest publishable report
for EVERY match in `ktp_match_reports`, whatever its date. That held only while
nothing but the timer's own `generate` wrote to the table. A test run with an
explicit match id (which bypasses `--since`) could write a publishable report
for a pre-season match; the next 15-minute tick would then fold it into the season
aggregates and push it to Supabase, where the sync never deletes it.

- `report_sync` and `report_service aggregate` take a required `--since`. They
  keep only reports whose match has a `ktp_matches.start_time` on or after it,
  the same column and "any half" semantics `generate --since` uses, and print
  `held back by --since …: N` for what they skip.
- A report whose match has no `ktp_matches` row is held back, not published.
- Without `--since` both exit 2 before touching the database: a forgotten floor
  must stop the pipeline, never silently re-open publication of everything.
- `systemd/ktp-reports.service` passes `--since 2026-09-13` to all three steps.

Deploy the unit and the checkout together: new code under the old unit, or the
old code under the new unit, fails `aggregate` with exit 2, so the tick publishes
nothing until both land.

### `scripts`: a deploy manifest, so every live script can be traced to a commit (2026-09-11)

Nothing recorded what was installed where. The only way to learn which commit a
live script came from was to hash it against every version in the repo's
history, and a hand-edited or re-encoded copy matched nothing at all. A sweep of
the data server and the five game hosts found exactly that: a cron wrapper whose
only difference from its commit is one em-dash re-encoded in transit, and live
scripts with no source in any repo.

- `scripts/ktp-install` installs a file from a git commit: a compare-and-swap on
  the destination's current md5, a banked backup, `.new` then `mv`, a read-back,
  and one appended row in the deploy manifest. The installed bytes are the blob,
  so no version string is written into any script.
- One manifest format in two places: `/usr/local/share/ktp-infra/DEPLOYED.tsv`
  for root, `~/.ktp/DEPLOYED.tsv` for everyone else, so `dodserver` records game
  host installs without sudo.
- A host without a checkout installs pushed bytes with `--file --blob-md5`. A
  filled template installs with `--template` and records the `.example` it came
  from.
- `ktp-install --report` flags DRIFT, MISSING and, with `--repo`,
  SOURCE-MISMATCH. It fails closed on a missing or unparseable manifest.
- `docs/DEPLOY_MANIFEST.md` documents both; `docs/LIVE_SCRIPT_INVENTORY.md` records
  what is live today and where it came from.

Nothing is installed by this change and no manifest exists on any host yet.

### `scripts`: the demo renamer dropped every cancelled or force-reset half (2026-09-11)

KTPHLTVRecorder sends `MATCH_WINDOW_CLOSE` only at match end. A cancelled second
half or a `.forcereset` never sends one, so `hltv-demo-renamer` held the window
open, abandoned it after 4h with a WARNING, and renamed nothing;
`ktp-demo-cleanup-auto.sh` then deleted the demo at 6h. Six halves went that way
between 2026-09-03 and 2026-09-10, three of them real play (`1.3-6704-NY1`,
`1.3-6706-NY1`, `1.3-6755-DAL1`, all h1).

- A window still open when a *different* match opens on the same HLTV port is
  bounded by that OPEN (`Orphaned window` WARNING) and renamed through the normal
  path, half-less. A candidate whose last write runs past the bound belongs to
  the later match and is never taken, even as a sole candidate: the sole-candidate
  allowance is for one match's h1 file running into its own h2, not into someone
  else's match.
- A window that reaches the 4h abandon with nothing after it now flushes the one
  recording that was live at its open, half-less, instead of nothing. Later idle
  recordings are left to the cleanup sweep.
- `closed but no matching auto-* files` is now WARNING. The renamer has no alert
  path, so it is not paged; `ktp-soak-verify` now counts it together with
  `Abandoning stale window` and `Orphaned window`.
- `verify-hltv-demo-renamer.sh` no longer looks for `SSH connected` in the last
  200 journal lines. That line is logged only on connect, so the check failed on
  any healthy long-running process; the `last_read_ok` check already proves the
  loop is reading.

Not deployed: installing the script and restarting `hltv-demo-renamer` is an
operator act.

### `hltv`: a proxy that is up but never connected now alerts (2026-09-11)

On 2026-09-09 the 11:00 HLTV restart brought `hltv@27020` (ATL1) up without its
own `configs/hltv-27020.cfg`, so it never connected to its game server. It
answered `Not connected.` for about 15h45m, until the next 03:00 restart, and the
12man played on ATL1 that evening was never recorded. Every check passed: the
port was bound, the unit was active, and the restart summary read "24 succeeded".

- `ktp-hltv-liveness.sh` also checks that each bound proxy is RECORDING: it alerts
  when the newest `auto_*` demo named by that proxy's own `record` line is older
  than `STALE_SECONDS` (default 300). A connected proxy writes continuously, even
  to an empty server. It fails closed: a config with no `record` line, or no demo
  at all, is reported rather than skipped. The existing two-sample threshold, 3h
  reminder and recovery message cover both checks.
- `hltv-restart-all.sh` counts a proxy as a success only once its journal shows a
  connect line after its own `Started` line, within `CONNECT_WAIT_SECONDS`
  (default 180). A proxy that never connects is listed as *up but not connected*,
  the summary turns orange, and the log line carries `failed` so
  `ktp-soak-verify` flags it.
- The liveness DOWN alert escaped its backticks as `\``, which is not a valid JSON
  escape, so the relay could not parse that embed. It now uses plain backticks.
- Paths and timings can be overridden from the environment, so
  `tests/unit/test_hltv_liveness_and_restart.py` runs both scripts against stubbed
  `systemctl`, `ss`, `journalctl` and `curl`.

### `ci`: the shared smoke gate could not tell a regression from its own breakage (2026-09-10)

`smoke-callable.yml` is reusable, so its red check lands on the CALLER's PR.
`assert-no-failed` reported every non-running plugin, which meant a plugin the
base image had failed to ship failed somebody else's build under a name they
had never touched. It did, on `JimmyLockhart65616/DoD-hud-observer`: the plugin
under test loaded fine and the job died on `stats_loggi=bad load`.

The three gates added earlier the same day — the compile guard, the manifest
check, and `verify-plugin-artifacts` — all fire at BUILD time, so they stop the
next bad image. None of them changes what a caller sees when a bad image is
already on `:latest`.

- `assert-no-failed --under-test <names>` splits the verdict by attribution: a
  non-running module or plugin matching one of `<names>` exits `1`, anything
  else exits `3`. Without the flag every failure exits `1`, as before.
- `smoke-callable.yml` passes `assert_plugin` and `assert_module` through, and
  turns exit `3` into a `KTP base image fault` warning plus a job-summary entry
  — but only after the forced GHCR re-pull has ruled out a stale `:latest`, so
  the 2026-04-29 propagation race still self-heals. A caller that names neither
  keeps the strict behaviour; a gate that excuses everything is worse than one
  that is red.
- `publish-base-image.yml` now boots the image it just built and runs the
  *unscoped* `assert-no-failed` BEFORE pushing. That is what makes the scoping
  safe: the class callers stop failing on now fails in the repo that owns it,
  and a broken image never reaches `:latest`. Build-time checks cannot see a
  plugin that is present and still fails to load.

Not fixed here: `stats_logging.amxx` cannot be built from `KTPAMXX` `main` —
`851c67e5` added a `dod_is_deployed()` call to
`plugins/dod/ktp_stats_capture.inc`, and that native is declared in
`dodfun.inc`, which `stats_logging.sma` does not include. Adding the include
compiles and then the native is missing at runtime: `dodfun` is in none of
`config/{local,online,lan}/modules.ini` and is absent from the fleet. That
needs a DODX-side deployed check or a deliberate module addition, in
`afraznein/KTPAMXX`.

### `build`: verify the plugin set an image ships against the manifest that loads it (2026-09-10)

The compile guard added the same day makes a plugin that fails to compile fail
the build. It does not cover the two ways a plugin goes missing without any
compile failing:

- `runtime/Dockerfile` copies `artifacts/$(VERSION)/plugins/`, not the builder
  image, and `extract-artifacts` downgrades a failed `docker cp` to
  `|| echo "Warning"`. A short or stale artifact directory reaches a published
  base image with every step reporting success.
- `build/plugins/Dockerfile` prints `SKIP: <path> not found` and returns 0 when
  a plugin's `.sma` is absent, so an un-checked-out plugin repo builds green and
  ships one plugin short.

Either way the first symptom is at boot, where KTPAMXX reports the plugin as
`bad load` under a truncated name — `stats_loggi` for `stats_logging.amxx`. On
the shared Tier 1 gate that reads as "the change under test is broken" to every
consumer, including repos we do not own.

- `scripts/verify-plugin-manifest.sh` asserts every `.amxx` in
  `config/{local,online,lan}/plugins.ini` exists in a given plugins directory,
  and with `--sources <root>` that each also has a `.sma` under that root. A
  manifest parsing to zero entries is an error, so the check cannot pass
  vacuously.
- The `Makefile` runs it as `verify-plugin-artifacts` against
  `artifacts/$(VERSION)/plugins/` — after `extract-artifacts`, before
  `publish-latest`.
- `tests/unit/test_verify_plugin_manifest.py` covers both directions, including
  the empty-manifest control and the missing-source case.

### Fixed - the report pipeline's first run would have published 213 pracc matches as league data (2026-09-10)

`pending_match_ids()` selected every match with flag-state producer rows,
gated only by the `--since` date floor. Its comment said no official/scrim
flag exists on a match. One does: `ktp_matches.match_type`, whose own column
COMMENT on the server reads *"KTPMatchHandler enum: 0=official, 1=scrim,
2=12man, 3=draft, 4=KTP OT, 5=draft OT"*.

Measured on the production `hlstatsx` before the fix: **213 pending matches,
68 scrim and 145 12man, zero official**. Every one of them would have been
generated, persisted and synced to ktpleague.gg on the first cron run, and
nothing would have errored.

The filter is now `match_type IN (0, 4)` — the same set KTPMatchHandler's own
`is_official_match_type()` spells, `.ktp` and `.ktpOT`, the two password-gated
results-bearing types. A NULL `match_type` is dropped deliberately (`IN`
excludes NULL): an untyped match is not a provably official one, so the filter
fails closed. `generate` now prints what the filter dropped, by type, so the
exclusion is never silent.

### Added - `scripts/verify_report_pipeline.py`, a post-cron check that can fail (2026-09-10)

The pipeline handover's sanity check was `SELECT ... FROM ktp_match_reports
ORDER BY id DESC LIMIT 5` plus "look at `/stats/matches`". Both are blind:
the query returns 0 rows when cron never ran, when cron ran and correctly
found nothing, and when cron ran and failed; the page answers 200 in all
three (so does a nonsense match id -- only the `<title>` differs).

The replacement asserts the log's mtime, that a `generate` block reached its
own terminator line (a truncated run fails instead of passing), that
`failures:` is present and zero, that no match which ended before the run is
still pending, that no report is `publishable=0` at `quality_status=PASS`,
and that the page's empty-state marker agrees with the report count in both
directions. Exits non-zero on any of them. A healthy pipeline with nothing to
do reports `IDLE` rather than success.

`quality_status=FAIL` at `publishable=1` is expected, not a defect: the
cosmetic `match_id_shape` check fails on every legacy `1.3-` match id.

### Fixed - a plugin that failed to compile produced a SUCCESSFUL build (2026-09-10)

`build/plugins/Dockerfile` ran the Pawn compiler as
`./amxxpc ... || echo "WARNING: $name may have had errors"`. That `||` also
neutralised the script's own `set -e`, and the missing-artifact branch printed
`FAILED` and returned 0. So a plugin that failed to compile produced a
**successful** image whose `/output/plugins/` simply lacked that `.amxx`.

A server that loads no `stats_logging.amxx` collects **nothing at all** --
silently, with every build and deploy step reporting success. This is not
hypothetical: KTPAMXX `main` did not compile for several hours today
(`undefined symbol "dod_is_deployed"`, KTPAMXX #106) and nothing anywhere
reported it. KTPAMXX CI skips plugin compilation by design and defers to this
build, so this swallow was the only thing standing between a broken plugin and
a deploy, two days before the season opener.

The script now collects failures and fails the build at the end, naming every
broken plugin rather than stopping at the first. A plugin counts as failed if
`amxxpc` exits non-zero **or** no `.amxx` is produced -- checked separately,
because a cached or stale artifact can outlive a failed compile.

Verified against the real toolchain (`amxxpc 2.7.33.5799`) by running the
shipped script over both cases: a plugin that compiles exits 0 and reports
`Compilation Complete`; a plugin that does not exits 1 and reports
`PLUGIN BUILD FAILED: <names>`.

### `scripts`: capture-health type checks no longer break on a newer producer (2026-09-10)

Two places compared the set of per-half health streams against
`CAPTURE_EVENT_TYPES` for **exact equality**:
`match_analytics.evaluate_capture_authorization` and `canary_evidence`'s
`complete_types`. `ksc_emit_health` loops over every event type the plugin
knows, so a plugin that gains a stream gains a health row — and schema 24
(KTPAMXX #102) added `shot`, making it 12 rows where the list has 11.

Left alone, the first match played on the new plugin would have reported
`half N does not contain each exact health type once` on **every half of
every match**, and the canary would have called its health coverage
incomplete — while nothing was actually wrong. That would have landed
squarely on the wave-0 canary it was meant to validate.

- `CAPTURE_EVENT_TYPES` stays the **required** core that must appear exactly
  once per half; new `CAPTURE_EVENT_TYPES_OPTIONAL` carries streams a newer
  producer may additionally emit (`shot`).
- Both checks now require all of the core, permit the optional, and still
  reject an unknown type or a repeat — so the original intent (catch a stream
  that went dark, catch duplicates) is preserved while a fleet mid-rollout
  passes on both plugin versions.
- Five tests in `tests/e2e_stats/test_match_analytics_integration.py` cover
  both directions: an 11-type and a 12-type producer both accepted, and a
  missing / unknown / repeated type each still an error.

This is the same exact-equality trap as the schema-version gates fixed
earlier today, in a different guise.

### `config` + `scripts`: spawn ownership now comes from the maps, not from play (2026-09-10)

`config/analytics/spawn_ownership.toml` seeds the opening flag position of
every generated report. It was a majority vote over 886 HUD recordings, taken
after skipping each half's opening readings — which meant it measured who
*usually holds* each flag during play, not who the mapper *authored* it to.
On a home flag those are the same answer; on a neutral flag they are not, so
the table asserted home flags on five maps that author none.

Corrected against the maps themselves. Every `dod_control_point` entity in a
BSP carries `point_default_owner` (0 neutral / 1 allies / 2 axis) — the
authored value, and the only thing that means "who owns this at spawn".

- **New `scripts/map_spawn_ownership.py`** reads it straight out of the entity
  lump, fetching maps from the public fastdl mirror (cached locally, so a
  re-run is offline). Self-contained; no dependency on the observer repo's
  copy of the same parse. It refuses to guess a `flag_index` on maps that ship
  no usable `point_index` — those still get authoritative per-flag ownership
  keyed by name, with `index_source` saying why the order is absent.
- **Removed, authored all-neutral:** `dod_halle`, `dod_lennon5_b1`,
  `dod_railroad2_s9a`, `dod_railyard_s9d`, `dod_thunder2`. Their flag names
  and indices were right — they match the BSP exactly — so this was purely a
  wrong ownership call. `dod_lennon5_b1` and `dod_thunder2` are the two
  most-played maps in the pool, so between them this was the majority of
  affected reports.
- **Corrected `dod_saints2_b3e`:** the table had The Bridge — the map's
  neutral centre flag — at index 0 and owned by allies, and omitted Allied 2nd
  entirely. saints2 ships `point_index = -1` on every CP, so its order comes
  from the game DLL; the corrected order is confirmed twice over, by
  KTPHudObserver's hand-verified permutation and by production's own
  `ktp_flag_state_events`.
- **Unchanged:** `dod_armory_b6` and `dod_solitude2` — the BSPs agree with
  what the table already said.
- Provenance strings in `match_analytics.load_spawn_ownership` and
  `flag_swing.py`'s report caveat updated: they described the table as
  reconstructed from HUD recordings, which is no longer true.
- `tests/unit/test_spawn_ownership_table.py` pins the corrected content, the
  authored-neutral omissions, and the saints2 index regression specifically,
  so a future re-derivation from play cannot quietly reintroduce it.

`config/analytics/map_spawn_ownership.json` carries the full audit record for
all 17 pool maps, including the neutral ones the TOML deliberately omits.

### Lane B + analytics: shot-context stream coverage, and a schema-24 drift fix (2026-09-10)

Wave 0 of `ENGINE_STATS_EXPANSION_PLAN_20260909.md`, following KTPAMXX and
KTPHLStatsX's `dod_client_weapon_fire` / `ktp_shot_events` change (schema
23 -> 24).

- **Lane B now exercises the `shot` stream.** `scripts/lane_b_e2e.py` counts
  the `triggered "shot"` marker and `tests/e2e_stats/assertions.py` gained
  `check_shot_events`: emitted-vs-persisted parity against `ktp_shot_events`
  (tolerant of the table not existing, same reasoning as `check_damage_ledger`
  for a corpus log older than migrate_027), plus a per-attacker invariant —
  a player's shot rows must cover their damage-dealt rows in the same
  match/half, since damage cannot happen without a prior weapon-fire
  dispatch. `migrate_027_shot_events.sql` added to `DEFAULT_SCHEMA_FILES`
  and both `--schema` blocks in `lane-b-stats-e2e.yml`
  (`tests/unit/test_lane_b_schema_list_drift.py` guards the three staying
  in sync).
- **Found and fixed the same exact-schema-equality defect PR #87 fixed in
  the daemon, in three more places in this repo:**
  `match_analytics.evaluate_capture_authorization` (`schema_version not in
  {22, 23}`), `match_analytics.evaluate_position_provenance` (`!= 23`), and
  `match_readiness`'s position-cadence authorization (`in {22, 23}`) would
  each have rejected a schema-24 manifest outright the moment the new
  plugin shipped fleet-wide — not merely missing the new `shot` capability,
  but failing capture authorization and position provenance for every match
  played on the new plugin. All widened to include 24 (schema 24 is
  additive over 23: adds `shot`, drops nothing). `check_capture_health` in
  `tests/e2e_stats/assertions.py` had the same defect in SQL
  (`schema_version = 23`), fixed to `>= 23`.
  New regression coverage: `test_schema24_position_provenance_authorizes_the_same_contract_as_schema23`.

### `scripts`: fleet timezone-uniformity check (2026-09-09)

- `hlstats.pl:2542` computes `$ev_remotetime = timelocal(...)` unconditionally — it reads a game
  server's naked wall-clock log stamp and interprets it in the **daemon's** timezone. That value
  already drives the `last_team_change + 2 s` grace that suppresses a team-kill after a team switch
  (`HLstats_EventHandlers.plib:792, 877, 1145`). **A game host provisioned in UTC would mis-attribute
  team kills today, silently.** The fleet agrees on `America/New_York` by convention: no runtime
  assertion, no fleet check, nothing in the provisioning path pins it. A rebuilt or newly provisioned
  host is the arrival path, and today it lands with nothing reporting.
- New `scripts/ktp-timezone-drift.py`. Read-only: it reads clocks, one config line and a log tail,
  writes nothing, restarts nothing. Host addressing comes from the same `/etc/ktp/audit-fleet.json`
  the fleet audit uses; nothing is hardcoded.
- **The load-bearing probe is not `timedatectl`.** That reads a host's *config*; the daemon consumes
  what the *engine stamps into the log line*, and a host can satisfy the first while failing the
  second. So per instance: take the last log line's reading, interpret it the way the daemon does,
  and compare against the log file's mtime, which is absolute. A wrong zone lands whole hours away.
  `timedatectl`, `/etc/localtime` and NTP are kept as secondary config checks and are labelled as
  such in the output.
- The two legs are complementary and neither subsumes the other: stamp-vs-mtime catches a wrong
  **zone** (a host whose clock is merely wrong shifts both readings together and passes), while
  host-clock-vs-auditor catches a wrong **clock** (right zone, dead NTP, internally consistent stamps
  hours from reality).
- Also checks the daemon and MySQL, because that is where a game host's stamp is finally
  interpreted: `@@system_time_zone` against the zone's abbreviation *at that instant*,
  `NOW()`−`UTC_TIMESTAMP()` against its offset, `@@global.time_zone` still `SYSTEM`, and that no host
  sets `TZ` explicitly for the daemon — it is supposed to resolve through `/etc/localtime`.
- The expected offset and abbreviation are **derived from the tz database at the measured instant**,
  never written down, so the check needs no editing twice a year and a DST transition cannot read as
  drift. Both DST folds are tried for a log stamp and the nearer taken: during the fall-back hour a
  local reading names two instants, and resolving to the wrong one would report an hour of legitimate
  lines as drift every November.
- **Controls travel in the script, not only in the testing.** Per host a positive control (instance
  dirs discovered, `dodserver.cfg` carrying its `hostname` line) and a negative control (listing a
  directory that cannot exist must fail). If the negative control *succeeds*, no result from that
  host counts — on this estate a clean zero has repeatedly been a permissions denial rendered as a
  number. The probes are `PROBE_BEGIN`/`PROBE_END` bracketed because a killed probe emits a prefix
  that parses perfectly and reads as a host with fewer instances.
- Exit **1** = the check could not be trusted (host unreachable, control failed, probe truncated, no
  tz database), **2** = drift, **0** = clean. An unreachable host is a failure rather than a skip,
  and `ERROR` outranks `DRIFT`: a sweep you cannot trust is worse news than one that measured
  something wrong.
- `mysql.time_zone_name` is empty, so a future `CONVERT_TZ()` with a named zone returns `NULL`
  rather than erroring. Nothing reads it today, so this is **reported and does not affect the exit
  code** — the output says so.
- Not scheduled and not wired into `ktp-fleet-audit.sh`. That wrapper's argument handling makes a
  check that never ran look like a check that passed; run the Python directly.
- `tests/unit/test_ktp_timezone_drift.py` injects the drift the fleet does not have — a host
  stamping in UTC, a database that stopped following the host clock, a daemon with `TZ` pinned — plus
  every way the probe can fail while looking clean. A check that has only ever been seen to pass is a
  check nobody has tested.

### `ci`: Lane B can boot a candidate engine instead of the image's baked one (2026-09-09)

- Lane B took refs for AMXX, the daemon, MatchHandler and this repo, but never for the engine.
  `engine_i486.so` is baked into `ktp-runtime-test-base`, so every lane measured a fixed engine —
  and the engine is the one fleet artifact the nightly `mv -f` keeps no rollback for.
- New `workflow_dispatch`/`workflow_call` input `engine_ref`. Empty means the baked engine and is
  the default, so a scheduled run behaves exactly as before. `ENGINE_REF` deliberately has **no**
  matrix fallback: `amxx_ref` and its siblings fall back to the matrix ref, and copying that here
  would start injecting an engine on every nightly.
- It is a download-and-overlay, not a source ref. The other refs are checkouts compiled in-image;
  the engine is not built here at all. `KTP-ReHLDS`#16 added the `upload-artifact` step this
  consumes — before that there was nothing to fetch.
- `scripts/fetch_engine_artifact.py` resolves the ref to a commit, finds `rehlds-engine-<sha>`,
  and refuses to continue on anything unexpected. **There is no fallback to the baked engine**: a
  silent one would smoke the old engine and report green, which is worse than not having the
  feature at all. Missing, expired, wrong-architecture and rejected-credential are four distinct
  exit codes — expired is its own outcome because the engine is not byte-reproducible, so
  rebuilding that commit cannot recreate the artifact.
- **The cross-repo download needs a token carrying `actions:read` on `KTP-ReHLDS`.** Listing
  artifacts on a public repo works unauthenticated; downloading one answers 401. A workflow's own
  `GITHUB_TOKEN` is scoped to its repository, so the step uses `KTP_CHECKOUT_TOKEN` and fails with
  a named error when it is unset rather than surfacing an opaque HTTP code.
- `lane_b_e2e.py` gains `--engine-so`/`--engine-provenance`, overlays the engine at the tree root
  where `hlds_linux` dlopens it, and re-hashes it after staging: an overlay that quietly did not
  land leaves the baked engine in place, and every downstream result then describes an engine
  nobody meant to test.
- `tests/e2e_stats/engine_telemetry.py` asserts the `[KTP_PROFILE] net:` and `rewind:` records are
  emitted carrying the field set `scripts/ktp-net-profile.py` reads off production, and that
  `maxunlag=` echoes the configured ceiling — without that last one a record of frozen constants
  would pass. Profiling cvars are written only on the engine lane, so a run without `engine_ref`
  keeps today's exact console stream and the log invariants stay calibrated.
- ⚠️ **The clamp and rewind counters cannot be exercised by bots, and are recorded rather than
  asserted.** `SV_ParseMove` calls `SV_SetupMove` only for a non-fakeclient, and the per-packet
  sampler skips fakeclients outright, so the bots reach neither `maxunlag_hits` nor rewind
  `attempts` nor `clients`. An all-zero record is the correct result there. Anyone adding a
  nonzero assertion will get a test that cannot pass.
- No new trigger, and still no `pull_request`: the `full` lane stays non-required. It runs on
  GitHub-hosted `ubuntu-latest`, not the self-hosted Tier 2 runner, so this adds no load to the
  data server. `tests/unit/test_lane_b_engine_injection.py` holds those decisions in place — they
  are choices nothing in the harness would otherwise notice being undone.

### `ops`: the post-activation version-row flip is a gate, not a follow-up step (2026-09-03)

- The bump checklist puts the root `CLAUDE.md` version-row flip AFTER the 03:00 ET swap, so it
  depended on someone coming back the next morning and **nothing failed when they did not**. The
  2026-09-01 wave left two rows stale at once — KTPCvarChecker read 7.36 against a fleet on 7.37,
  KTPMatchHandler read 0.10.168 against a fleet on 0.10.170 — and only an md5 sweep a day later
  found it. Both artifacts were correct; only the record was wrong, while the table read as
  authoritative. Two rows out of one wave is a process defect, not two mistakes.
- New `scripts/ktp-wave-ledger.py`. `stage-wave.py` records `(basename, md5, version)` at STAGE
  time — the md5 is already known there, from `--expect NAME=MD5` — and computes when that wave
  activates. `reconcile` re-reads the fleet and **fails if `CLAUDE.md` does not carry the md5 the
  fleet is running**.
- **The half that does not rely on memory:** `stage-wave.py` refuses to stage the NEXT wave while an
  earlier one has activated and its row still names the build it replaced. The gate sits on the
  action the operator was going to take anyway, and editing the row clears it — there is no second
  command to remember. `--allow-unreconciled` overrides, for a deliberate stack.
- Assertions chosen so they cannot rot into vacuity: the md5 must appear **on that component's table
  row**, not merely somewhere in the file (the 7.37 hash was in a paragraph while its row still said
  7.36); a superseded md5 named in the same row does not satisfy it; an unmapped basename degrades to
  a file-wide search and **says so**; a mapped component with no row is reported as a table rename
  rather than passed. An unreadable `CLAUDE.md` exits **2**, never 0 — "I could not look" and "the
  row is fine" stay distinct verdicts.
- Read-only with respect to the fleet (`md5sum` only) and never restarts anything. The ledger lives
  at `$KTP_WAVE_LEDGER_DIR` (default `~/.ktp/waves`), outside this public repo.

### `ops`: the nightly restart's cron backup now survives a reboot, and restores itself (2026-09-02)

- `ktp-scheduled-restart.sh` strips the per-minute monitor cron for the duration of the restart and
  restores it from a `mktemp` backup on an EXIT trap. **An EXIT trap does not fire on power loss, a
  kernel panic or a hard reboot**, and `/tmp` is cleared on the way back up. A reboot inside that
  window therefore leaves the crontab stripped with its only backup gone: the instances are down and
  the mechanism that would have restarted them has been deleted. Nothing alerts, because the thing
  that would have reported it is what went missing. Measured on a fleet host: cron paused `03:00:01`,
  restored `03:01:33` — an exposure of roughly a minute and a half, every night.
- The backup moves to `${KTP_STATE_DIR:-$HOME/.ktp}/monitor-cron.bak` — the script's own user, no
  provisioning needed, and it outlives a reboot. It is armed by `mv` from a `.partial` sibling, so a
  half-written backup can never be the thing recovery trusts.
- **A backup found at startup is the recovery signal**, and the script now acts on it before doing
  anything else. It appends only the monitor lines back rather than installing the saved file whole,
  so a crontab edit made between the interrupted run and this one survives.
- Debris is distinguished from a real unfinished restore by SHAPE, not by age: the pause strips
  *every* matching line, so a backup holding monitor entries beside a live crontab that has none is
  the state only an interrupted run leaves. An operator who disables one instance leaves the others,
  which correctly reads as debris and is cleared without touching the crontab. Recovery is therefore
  idempotent — once the entries are back, a second pass is a no-op.
- The trap is unchanged in intent and still handles the normal path. Two adjacent one-way doors are
  closed alongside it: restoring an *empty* backup (`crontab -l` having failed) would have deleted
  every entry, and the pause is now skipped entirely if no durable backup could be written — a
  monitor cron left running is a far cheaper failure than one deleted.
- **No boot-time start for the game instances is added here.** That has a real double-start hazard
  against the nightly and is a separate decision.
- Template only. `.example` is the source of truth per the 2026-08-27 reconciliation; the fleet's
  copies are unchanged and `ktp-restart-drift.py` will report the difference until an operator
  reconciles them. **Nothing is deployed and no server is restarted by this change.**

### `ops`: reconcile the restart scripts' three lineages, and make the next divergence visible (2026-08-27)

- `~/restart-all-servers.sh` had drifted into **two mutually incompatible fleet variants** and neither
  matches the generator. Atlanta/Dallas/Denver run one shape; New York/Chicago run another that carries
  `set -e` alongside `((running++))`, so its verify loop exits 1 at the FIRST healthy server and never
  prints its summary. On Chicago it dies earlier still, on `~/dod-27019` - an instance deleted
  2026-07-13 that the hardcoded `1 2 3 4 5` loop still addresses. Every copy dates from Feb-Mar 2026.
  The repair path already exists -- #169's `--regen-management-scripts` and
  `docs/runbooks/FLEET_MANAGEMENT_SCRIPTS.md` -- and its pinned output is re-derived here rather than
  taken on trust: a sandboxed `HOME` reproduces both md5s exactly. What was missing is anything that
  NOTICES a host has fallen off it.
- `ktp-scheduled-restart.sh` drifted the other way. This `.example` is the most complete of the three
  lineages, the gitignored working copy stopped at 2026-08-04 (no #164, and a relay secret the fleet is
  not using), and the fleet sits between them. Its header asserted a regeneration direction that
  produced exactly that; corrected here to name `.example` as the source of truth.
- **No script is deployed and no server is restarted by this change.** `docs/runbooks/SCHEDULED_RESTART_LINEAGES.md` records
  what each lineage has, which differences are deliberate versus drift, and the per-host blast radius of
  a later deploy - including the two ways a naive one destroys something: pushing the gitignored copy
  reverts #164, pushing `.example` blanks the relay secret and both channel IDs.
- **`scripts/ktp-restart-drift.py`** (new, read-only) checks both scripts on every host. The scheduled
  script is compared against `.example` with secret VALUES masked, so a rotation is not drift and no
  secret leaves the host. The manual script is checked by PROPERTY after comments are stripped, not by
  string: the generator's own warning comment contains `((running++))` once, so a literal grep reports
  the correct file as broken. Hosts reached is printed beside every count.

### `tier2`: a re-sync tool for the runner stack, and the section the checklist pointed at (2026-08-26)

- **`scripts/sync-runner-stack.py`** mirrors the Tier-2 runner's stack from a live fleet instance. The
  runner is a declared must-match-fleet environment and the only thing enforcing that was a checklist
  line — `Re-sync the Tier-2 runner stack (above)` — that pointed at no section. The detector
  (`ktp-tier2-stack-drift.py`, in the 6h heartbeat) worked correctly and alerted `ok -> drift` within
  hours of the 2026-08-26 ABI wave; nothing existed to act on it, so the runner kept testing against
  the pre-wave engine, core, dodx and reapi.
- The synced file set is **imported from the drift checker** rather than restated, and the artifacts it
  refuses to overwrite are asserted against that set rather than merely documented: KTPMatchHandler and
  KTPPracticeMode are `KTP_TEST_MODE` builds where byte-equality with the fleet is wrong, and
  KTPHudObserver is rebuilt from upstream by `tier2-integration.yml` on every run.
- Dry run by default. `--apply` backs up each drifted file on the runner first — neither the fleet nor
  the runner keeps rollback copies — and re-reads md5 after the pull and after the push. It refuses
  while a Tier-2 run is live, and while the reference instance holds staged `.new` files, since a sync
  into a pending wave is stale again at the next 03:00.
- `docs/RELEASE_CHECKLISTS.md` gains the § *Tier-2 runner re-sync* section, including what the tool does
  **not** cover and therefore still needs a per-wave look: test-mode plugins, KTPHudObserver, and configs.

### `ops`: loud swap failures, and a two-marker Tier 2 heartbeat (2026-08-26)

- `ktp-scheduled-restart.sh`: a `.new` -> live swap failure used to be logged and
  otherwise ignored — the server start proceeded and Discord could still report
  a full green "restart complete" while a wave sat half-applied. Deliberately
  NOT escalated to aborting the start (a down server is worse than a
  partially-applied one); instead the run now forces the Discord status off
  green, names every unswapped file, and exits non-zero. New
  `ktp-verify-post-swap.sh` re-derives the same swap globs to check the morning
  after — a failed `mv -f` leaves its `.new` file in place, which is itself the
  durable record.
- `ktp-tier2-heartbeat.sh`: now watches `tier2-last-run.json` (main) and
  `tier2-last-run-preprod.json` (preprod) independently and names both in every
  alert, instead of only the former. Watching one marker produced a false
  alarm claiming the runner was offline/broken off a 65h-stale `main` marker
  while the runner was healthy and had completed a `preprod` job 35 minutes
  earlier — that run simply never touched the marker being watched. Either
  marker going stale or failing is reported by name; `KTP_TIER2_WATCH_PREPROD=0`
  is the one-line way to stop watching the preprod leg if it is ever retired,
  without repointing it at the main marker (which would just recreate the same
  blind spot under a different name).

### `local`: bot-backed game server on ktp-game-2 for go-live testing (2026-08-25)

- `ktp-game-2` is now a **bot server** and no longer a plain second game server
  on 27017: Metamod-R hosts new_bot while ktpamx keeps loading through
  `extensions.ini`, so plugins still run in extension mode. `ktp-game-1` is
  deliberately untouched as the control — under Metamod `fakemeta` is reachable
  and it is not on the fleet.
- New targets: `local-bots-amxx`, `local-bots-plugins`, `local-bots-build`,
  `local-bots-up`, `local-bots-match`. `local-bots-match` fills 6v6 with bots and
  drives the real `.ktp`/`.confirm`/`.ready` flow through go-live, so the local
  stack can finally exercise the mass-respawn stat re-wipe, wave clock and
  halftime swap.
- The bot server requires a `KTP_LANE_B_FAKECLIENTS` ktpamx, which is NOT a
  production binary; `runtime/entrypoint-bots.sh` refuses to boot without one
  rather than warning, because a bot-blind core is silent and looks healthy.
  `local-up` / `local-up-full` start game-1 (and `data`) alone when no core has
  been built, instead of letting game-2 crash-loop.
- The image carries third-party binaries (new_bot, Metamod-R), both SHA-256
  pinned, and must never be pushed to a registry. Runbook and limits — including
  that the custom map pool ships no bot waypoints — in `build/bots/README.md`.
### `analytics`: coordinated FPS-stat private-shadow bundle (2026-08-19)

- Match analytics schema version 6 adds symmetric basic trades, all-death-reset
  revenge, producer-clock damage conversion, temporally gated sampled objective
  pressure, weapon kill-time player separation, and physical-life KAT coverage.
  Every exploration reports definition parameters, source coverage, confidence,
  private visibility, and zero rating effect; unavailable sources never become
  observed zeroes.
- Adds read-only SQL feeds for canonical assist context, producer-clock frag and
  damage facts, life boundaries, positions, flag geometry, and ownership. Raw
  coordinates, paths, position timelines, and reconstructed lives are excluded
  from aggregate explorations; the separately named private kill/objective
  diagnostic timeline remains local-only and rating-neutral.
- Extends Lane B for migrations 016/017, life and canonical-assist reconciliation,
  and a fail-closed four-repository SHA manifest. Manual full runs can pin exact
  Infrastructure, MatchHandler, AMXX, and HLStatsX refs instead of mutable
  branch tips.
- Extends 14-day scrim/12man/`*-TEST` retention to `ktp_life_events` and
  `ktp_assist_events`; draft and official retention rules are unchanged.
- Documents the coordinated collection-branch, validation, dependency-order,
  full-HLDS-restart, privacy, and human-canary gates in
  `docs/FPS_STAT_EXPLORATION_BUNDLE.md`.

### `analytics`: canary evidence and private event timelines (2026-08-19)

- Adds a local-dump-only canary evidence bundle covering match classification,
  current capture sources, ownership baselines/transitions, operational log
  errors, retention eligibility, and fixture provenance.
- Match analytics schema version 3 adds configurable fast multikills, basic
  trades, opening duels, head-to-head results, and post-multikill objective
  conversion. These remain private, read-only shadow outputs with no public API
  or rating writes; replay-compressed fixtures suppress timed inferences.
- Extends the isolated MySQL query-contract fixture and tests the new tools
  against the same Lane B database engine used in CI.

### `scripts`: the lan-web drift check now says which tree it compared (2026-08-18)

`ktp-lan-web-drift.py` reads a working tree, so its verdict was about whichever
branch was checked out — "in sync" read as "in sync with `main`" no matter what
was actually out, and the same box could be reported clean and drifted on the
same day with neither report wrong about anything it said.

- Every report opens with a `source:` line naming the checkout and whether
  `sites/lan-web/app` matches `LAN_WEB_BASE_REF` (default `origin/main`).
  `UNKNOWN` is said out loud rather than omitted. Exit codes are unchanged —
  `deploy-lan-web.sh` branches on them, so they stay an interface.
- `deploy-lan-web.sh --apply` refuses when that tree differs from the base ref,
  alongside the existing box-only refusal. An unresolvable base ref is refused
  too, rather than skipped. Override: `--force-unreviewed-source`.
- `tests/unit/test_lan_web_drift_provenance.py` pins all five states, including
  that an edit outside `sites/lan-web/app` is not a divergence.

### `docs`: one production runbook for the stats and retention release (2026-08-17)

- Adds `docs/STATS_RETENTION_PRODUCTION_DEPLOY.md`: exact reviewed source pins,
  build-once artifact manifests, ordered database/daemon/fleet rollout, live
  match-type validation, retention dry-run and first-apply gates, and rollback.
- Keeps production activation one artifact per nightly and makes the first
  destructive retention apply a separately approved, backed-up operation.

### `tests`: cover StatsMe in the all-bot Lane B match (2026-08-15)

- Full Lane B builds `stats_logging.amxx` with the test-only
  `KTP_LANE_B_BOT_WEAPONSTATS=1` define and records that define in artifact
  provenance. Local Lane B uses the same build shape.
- Missing bot `weaponstats` emission is now a pipeline failure. Emitted lines
  must produce `hlstats_Events_Statsme` rows through the real HLStatsX parser.
- Production KTPAMXX builds omit the define and continue excluding bots.

### `scripts`: reconcile the HLStatsX ingest path hourly (2026-08-12)

Three defects at the Philadelphia 2026 LAN each destroyed real data and **none of
them raised anything at the time**. The stats were only discovered to be wrong ten
days later, by comparing them against photographs of the scoreboard. 982 kill
events and 2,755 objective events had to be reconstructed from the servers' own
console logs. This turns each of those failures into a check that fires on the day.

- **`scripts/hlstatsx-ingest-monitor.py`** plus a service + hourly timer. Checks:
  UDP receive-buffer drops (delta since last run), halves with no summary rows,
  summaries short of the events they summarise, second halves far below their own
  first half, and the daemon's own `KTP_HEALTH` line. `--logs` adds a
  log-versus-database comparison, which is only possible where the game servers
  share a host with the daemon — the LAN case, and the check that would have
  caught all three.
- Findings exit 1, failing the unit, which fires the existing `ktp-systemd-alert`
  `OnFailure` wiring into Discord. That delivery path is deliberate: a monitor
  writing to a log nobody opens repeats the original failure.

⚠️ **UDP loss is not detectable per-event, by construction.** GoldSrc `logaddress`
is fire-and-forget — the sender keeps no copy and the receiver never sees the
packet, so there is nothing to retry and nothing to notice. The kernel's
`RcvbufErrors` counter is the only evidence, which is why this lives here rather
than in the daemon: the daemon cannot see its own dropped packets. **On the
production data server that counter already reads 5,404** — the fleet is losing
log lines today, and buffer size is not the constraint (`net.core.rmem_max` is
25 MB and the daemon's 1 MB request is granted in full).

⚠️ **Three false-positive controls, all found by running it against live data.**
The load-bearing one: `ktp_match_stats` is written by `doEvent_KTPMatchEnd` —
once, at **match** end, for every half together. A half legitimately has no
summary rows for as long as its match is still being played, so keying the checks
on the half rather than the finished match alerts on *every live match*. That is
how a monitor gets muted and stops being a monitor. Also: a half that ended in the
last ten minutes may not be aggregated yet, and a summary running *ahead* of its
tagged events is explained by freeze-time kills being untagged (`recordEvent` only
stamps `match_id` while the round is live) rather than by any defect.

⚠️ **The schema is two collation families.** Upstream `hlstats_Events_*` tables are
`utf8mb4_unicode_ci`; the KTP `ktp_*` tables are `utf8mb4_0900_ai_ci`. Joining
`match_id` across them raises *Illegal mix of collations* and the query returns
**nothing at all**, which reads exactly like a clean result. Every join in the
script pins the collation explicitly; keep it that way if you add one.

### `tests`: Lane B scaffolding — bot-driven stats-capture e2e, Phase 0 (2026-08-09)

The stats-capture branches (assists / cap breaks / positions, see
`docs/ktpr_mcp/KTPR_DEPLOYMENT_PLAN.md`) cannot be covered by the existing
Tier 2 lane, and the reason is structural rather than a gap to fill in. Every
emit path in `ktp_stats_capture.inc` is gated on `is_user_connected()`, and the
cap-break detector's only input is a 0.5s poll of `dodx_area_get_data(...)`
zone occupancy. So `dodx_test_dispatch_client_death(1, 2, …)` on an empty
server returns at the first guard and emits nothing — **a synthetic-dispatch
test of this code would pass while proving nothing.** The four negatives the
deployment plan asks for (completed capture, off-point kill, voluntary
walk-off, round restart) are timing behaviours of real bodies in real zones,
and they are the ones that catch false-positive breaks, which silently inflate
a player's objective rating.

This lands the scaffolding and the spike, and deliberately **no assertions
yet** — see the last bullet.

- **`tests/integration/STATS_CAPTURE_E2E_DESIGN.md`** — two-lane model. Lane A
  (existing, deterministic, dispatch primitives) gates merges; Lane B (new,
  bot-driven, asserts on MySQL rows) runs nightly and never gates. Neither can
  do the other's job: a non-deterministic lane that blocks merges becomes the
  "disable the integration test to merge the urgent fix" antipattern the test
  plan already warns about.
- **Sturmbot is not usable here** — its current release (1.9) is a Windows
  installer only, and the legacy Linux build targets DoD 3.1B rather than 1.3
  and does not load against modern glibc. Per sturmbot.org's own Linux guide
  the viable DoD 1.3 bots are **Marine Bot** (primary) and **new_bot**
  (fallback, converts Sturmbot waypoints), both Metamod plugins loaded via
  `+localinfo mm_gamedll`. `tests/e2e_stats/bot_driver.py` isolates the choice
  behind a `BotSpec`, so swapping is a flag.
- **`tests/e2e_stats/ephemeral_tree.py`** — per-run serverfiles copy, because
  `help.md` requires the runner tree to match the fleet and a bot `.so` in it
  is exactly the tripwired drift. Hardlink copies make this fast and also
  dangerous: a bare `open(path, "w")` on a hardlinked path writes THROUGH to
  the fleet-matching tree. Every write unlinks first, and teardown re-hashes
  every shadowed source file and fails loudly if one changed. 11 unit tests
  cover it; the guard was mutation-checked (removing the unlink fails two
  tests, including the integrity backstop).
- **`tests/e2e_stats/ephemeral_mysql.py`** — "ephemeral MySQL" as a second
  `mysqld` on a private datadir/socket/port, not a container, because the
  Tier 2 runner is deliberately Docker-free and also runs production HLStatsX.
  Loopback-only and `--no-defaults`, so it cannot inherit the `~/.my.cnf` that
  on that box points at the **live** server. `prepare()` loads schema +
  migrations + seeds before the daemon may start, encoding the ordering trap
  that lost every objective capture at the Philly LAN as fixture order rather
  than as a note someone has to remember.
- **`scripts/spike_bot_lane.py`** — Phase 0. Answers, stopping at the first
  "no": does the bot load without displacing amxxcurl/reapi/dodx, which
  add-bot command works, do bots join a team and spawn (where `addbot` failed),
  do they fight, do they contest flags, what is the event volume per minute,
  and can a private mysqld apply the migration SQL to an empty database.
- **Assertions are deliberately not written yet.** This repo has already paid
  for the alternative: `DODX_FORWARD_FIRING_DESIGN.md` Phase 2 was written on
  the belief that `addbot` yields a playing bot, three tests shipped on it, and
  they were skip-marked a day later (1.5.25) when the first real run showed DoD
  ships no bot AI. Everything downstream of "the bots actually play" is cheap
  to write and worthless if that premise is wrong, so the spike answers it
  first. Lane B also inherits conftest's fail-don't-skip rule — a
  configured-but-broken bot is a failure, not a skip.

Quarantine, per the operator's requirement that the bot never reach
production: bot kit lives outside any fleet-matching tree, is `.gitignore`d, is
in no deploy manifest, loads from the **command line** rather than
`plugins.ini` (so a copy of the tree booted normally has no bot), and the
ephemeral tree is deleted on teardown.

Bot decision confirmed with the operator: **Marine Bot primary, new_bot
fallback** — Sturmbot is not available for Linux at all, so the substitution is
forced by the platform rather than chosen.

#### Build + daemon steps (same series)

- **`tests/e2e_stats/artifacts.py`** + **`scripts/build_stats_lane_artifacts.py`**
  — the build step. Extracts `stats_logging.sma`, `ktp_stats_capture.inc`,
  `hlstats.pl` and the SQL from **branch refs via `git show`**, never from a
  working tree: "Lane B passed on this branch" must not silently mean "passed
  on whatever was lying around on the runner". Writes a manifest of SHAs and
  md5s so a run is traceable to exact bytes, the same way the deployment plan
  verifies deploys by md5 rather than by console banner. Three plugin sources
  supported — compile with `--amxxpc`, adopt a Docker/CI build with
  `--prebuilt-plugin`, or `--no-plugin` for the toolchain-free daemon+SQL half.
  Encodes two constraints instead of documenting them: the `.sma`/`.inc`
  sibling requirement (the production Dockerfile needed a dedicated `COPY` for
  it), and **compile failures are fatal** — unlike `build/plugins/Dockerfile`,
  which ends each compile with `|| echo "WARNING: …"` and so does not fail on a
  broken plugin. A test lane that proceeds against a stale artifact reports on
  the wrong thing.
- **`tests/e2e_stats/hlstats_daemon.py`** — runs `hlstats.pl` in its
  **`--stdin` mode** (hlstats.pl:1971), fed by a thread tailing the ephemeral
  server's log. Stdin mode disables the UDP listener *and* sets `$g_rcon = 0`,
  so the test daemon cannot rcon the server under test; feeding the log
  directly also removes UDP loss and reordering from a test whose whole purpose
  is attribution. Enforces both silent-failure prerequisites: the
  `hlstats_Servers` row the daemon resolves lines against (hlstats.pl:815), and
  seeds-before-daemon-start. `drain()` waits past the plugin's own 5s
  `KSC_BUF_FLUSH_SECS` — asserting before that flush looks identical to the
  capture being broken.

Unverified and flagged in code: whether stdin mode wants the engine's
`L <date> - <time>: ` line prefix intact, and whether `--timestamp` belongs on
the command line. Both are config switches with a documented default, settled
by Phase 0.

#### Containerised, on a GitHub-hosted runner (same series)

The operator asked whether the stack already runs as a Docker image and whether
the lane could just live there. Largely yes, and it supersedes much of the
host-based design above.

What the stack actually is: Docker is the **build system** plus the Tier 1 test
runtime (`ktp-runtime-test-base`, a complete ~2 GB image rebuilt nightly by
`publish-base-image.yml`); the **production fleet is bare metal**, artifacts
staged as `.new` and swapped at the 03:00 ET restart (`docs/DEPLOYING.md`).

- **`build/lane-b/Dockerfile`** — `FROM ktp-runtime-test-base` plus MariaDB, the
  Perl DBI stack, and the 32-bit bot runtime. Four things it fixes: `amxxpc` is
  **already in the base image** and `smoke-callable.yml:324` already compiles
  plugins by `docker run`-ing it (the toolchain blocker was self-inflicted); the
  container filesystem is ephemeral so there is no fleet-matching tree to
  contaminate; glibc is pinned to Ubuntu 22.04's **2.35**, below the 2.41
  threshold where the loader rejects shared objects needing an executable stack
  — the likeliest failure mode for a 20-year-old bot `.so`; and it runs nowhere
  near the data server, which hosts production HLStatsX and is deliberately
  Docker-free.
- **`EphemeralTree.in_place()`** — writes to `/opt/hlds` directly, no copy.
  Copying 2 GB inside a container that is itself thrown away buys nothing. The
  shadow-hash integrity check is disabled in this mode (there is no pristine
  source, and recording hashes of files about to be overwritten would guarantee
  a spurious `TreeIntegrityError`), and it refuses a tree without `hlds_linux`.
  `build()` remains the default outside the container.
- **`.github/workflows/lane-b-stats-e2e.yml`** — `ubuntu-latest`,
  `workflow_dispatch` + 06:00 UTC nightly, deliberately slotted between the
  base-image rebuild (04:30) and Tier 2's nightly (09:00) so two hlds-booting
  suites never overlap. **No `pull_request` trigger and not a required check** —
  bot AI is non-deterministic and a flakeable lane must not gate merges.
- **Bug fixed before it could bite:** `mysqld`/`mariadbd` refuse to start as uid
  0 without `--user=root`, and containers run as root by default, so the whole
  image path would have died at startup. Both the initialiser and the server
  invocation now pass it when euid is 0.
- **The bot is not baked into the image** — third-party, not ours to
  redistribute, and a GHCR push would publish it. Mounted at run time; CI fetches
  it from a secret-held private URL. If that secret is missing on a `full` run
  the workflow **fails with an explanatory error** rather than skipping, because
  a skip is indistinguishable from coverage.

Recorded in both the design doc and the README: the image is a
**reconstruction** of the fleet built from repo refs, so green here means "this
branch works against this branch's stack", not "works against what is deployed".
That second question still belongs to the Tier 2 runner's fleet-matching tree
and its drift tripwire; neither is retired by this.

#### First real run of the image — five bugs, one blocker (same series)

Docker turned out to be installed as a **snap inside WSL** (invisible to
`dpkg -l`, `/snap/bin` off PATH), so the image finally got built and run. Every
one of these failed in a way that pointed somewhere other than the cause:

1. **`ENTRYPOINT` inherited from the base image.** The runtime base sets
   `ENTRYPOINT ["/entrypoint.sh"]`, which boots `hlds_linux` — so
   `docker run … bash -c "python3 …"` appended the whole command line to the
   game server's argv and never ran it. `docker top` showed python's arguments
   hanging off `hlds_linux`. `smoke-callable.yml` sidesteps this per-invocation
   with `--entrypoint bash`; the Lane B image now clears it with
   `ENTRYPOINT []` so callers cannot forget.
2. **`amxxpc` must run from its own directory.** It `dlopen`s `amxxpc32.so` by
   bare name, so the loader searches the CWD: "compiler failed to instantiate:
   amxxpc32.so: cannot open shared object file". Both existing build paths
   already `cd` to the compiler dir; `compile_plugin()` now does too.
3. **`--no-defaults` must be MariaDB's first argument.** It is a pre-option;
   anywhere later, the server completes a full InnoDB startup and *then* aborts
   with `unknown option '--no-defaults'`, which reads as a mysterious late
   crash. It is load-bearing, not hygiene — without it the server reads
   `~/.my.cnf`, which on the data server points at the **live** database.
4. **`sql()` always selected a schema**, including for the `CREATE DATABASE`
   that creates it — `ERROR 1049 Unknown database` before the statement was
   ever sent. Now `database=None` connects without selecting one.
5. **`git` and `pytest` were missing from the image**, and git refused the
   bind-mounted repos with "detected dubious ownership" (host uid vs container
   root). Added via apt — `python3-pytest`, not pip, because Ubuntu 24.04
   enforces PEP 668 — plus a `safe.directory '*'` waiver, justified in the
   Dockerfile: the alternatives break `/opt/hlds` writes and the
   mysqld-as-root path, and the mounts are read-only in a throwaway container.

**What is now proven rather than reasoned:** the image builds on a **public**
base (no GHCR auth needed) that is **Ubuntu 24.04.4 / glibc 2.39** — *not* the
22.04/2.35 previously claimed here, which is `build/base/Dockerfile`, a
different image; **`stats_logging.amxx` compiles** from `feat/stats-positions`
with the capture include, **0 warnings**, md5
`018b17442ef4ef352623428eebe93200` — retiring open verification debt #2 in
`CONTINUATION_NOTES.md` ("Nothing is compiled"); the private `mysqld` starts and
serves; and the unit suite passes **40/40 inside the image** (Linux path).
Artifact md5s match byte-for-byte between Windows and Linux.

**Blocker found, not a bug:** `sql/ktp_schema.sql` is an **overlay, not a
schema** — 8 `ALTER TABLE`, 3 `CREATE TABLE IF NOT EXISTS`, 4 indexes, all
assuming stock HLStatsX tables exist. On an empty database it dies at
`ERROR 1146 … 'hlstats_Events_Frags' doesn't exist`. That is the file behaving
as documented (its header warns fresh installs are the hazard), but it means
**Lane B cannot build a database from this repo alone** — it needs a base
schema, ideally a `mysqldump --no-data` of production. Options and trade-offs
are in `tests/e2e_stats/README.md`.

- **`scripts/lane_b_local.sh`** — local driver, and the place three
  environment traps are written down so they are not rediscovered: Git Bash
  rewrites POSIX paths in `-v` arguments when invoking `wsl.exe`/`docker.exe`
  (a mount silently pointed at `G:\GIT\scripts`, so the directory came up empty
  and python reported a missing file); the docker **snap has a private `/tmp`**,
  so `-v /tmp/out:…` writes into its own namespace and every artifact vanishes
  on exit — a green-looking run that produced nothing; and WSL shuts the distro
  down between commands, taking `dockerd` with it.

#### Database half green, and it caught a real MySQL incompatibility (same series)

With ssh access to the data server, Lane B took a schema-only dump of
production and the database half now passes 5/5:

```
[PASS] mysqld-private-instance  (MySQL 8.0.46 — same version string as production)
[PASS] schema-load              1 schema + 2 seed files onto an empty database
[PASS] schema-tables            64 tables
[PASS] seed-assist              for_PlayerActions=0 for_PlayerPlayerActions=1, reward 0
[PASS] seed-cap_break           for_PlayerActions=1 for_PlayerPlayerActions=0, reward 0
```

The last two are `KTPR_DEPLOYMENT_PLAN.md`'s most dangerous check — flags the
wrong way round record every event twice and double-apply the reward — now
verified automatically rather than by hand.

- **Switched the image from MariaDB to MySQL**, and this is load-bearing rather
  than tidiness. `sql/ktp_schema.sql` uses `ADD COLUMN IF NOT EXISTS` /
  `CREATE INDEX IF NOT EXISTS`, which is MariaDB-only; production is MySQL
  8.0.46 and rejects it with `ERROR 1064`, aborting before every later
  statement. The file's own header documents exactly this and warns that a
  *fresh* install — LAN data-server provisioning — is where it "silently
  applies almost nothing". **On the MariaDB build the run passed.** A
  MariaDB-backed lane would have gone green on the one migration hazard already
  written down in the repo. Standing item for the project: `ktp_schema.sql`
  still needs porting to plain `ALTER`s before a fresh MySQL install relies on
  it.
- **`scripts/fetch_base_schema.sh`** — read-only, repeatable production schema
  dump (`--no-data --single-transaction --skip-lock-tables --no-tablespaces`).
  Verified against production: **64 tables, 0 INSERTs**. Needed because no repo
  contains a base schema — `ktp_schema.sql` is an ALTER-only overlay, so an
  empty database cannot be built from source, which is the same reason a fresh
  LAN provision is the documented hazard.
- Two grant limitations, handled rather than routed around: **`hlstats_Servers`
  is denied** to the read-only account (HLStatsX keeps per-server rcon
  configuration there), so the table is reconstructed from `information_schema`
  metadata — types, nullability, defaults, indexes — reading no values; and
  **views are denied** (`SHOW VIEW`), which aborts mysqldump mid-run, so the
  table list is enumerated explicitly rather than left to its own discovery.
- **`--no-defaults` also has to be first on the *initialiser*.** Without it
  MySQL reads Ubuntu's `mysqld.cnf`, drops to the `mysql` user, and then cannot
  read a root-owned `0700` datadir — surfacing as
  `[MY-013276] Failed to set datadir … (OS errno: 13)`, which reads as a
  filesystem permissions problem rather than as "it read a config we did not
  want".
- A production-derived base already carries `match_id`, `half` and `pos_x/y/z`,
  so `ktp_schema.sql` is redundant on top of it and is no longer applied by
  default; `LANE_B_APPLY_KTP_SCHEMA=1` reproduces its MySQL failure on purpose.

#### new_bot installed by the image — and a Metamod blocker found (same series)

The Lane B image now downloads and installs **new_bot 0.2.2** at build time
from the installer page, **SHA-256 pinned** (`8f659fe1…`) so a replaced upstream
artifact fails the build rather than silently swapping the bot under a lane
whose whole job is trusting what it ran. `NEW_BOT_URL` is overridable for a
vendored copy when the Google Drive link rots or the host is offline.

Verified in the built image: `dod/new_bot/new_bot_mm.so` (442 KB, chmod 0755)
plus **93 waypoint files** covering the real KTP pool — anzio, avalanche, jagd,
donner, flash, kalt, caen, merderet, charlie, sturm. Upstream changelog dated
13-07-2026; this is maintained software.

🔻 **ANNOTATED 2026-10-07 — the "covering the real KTP pool" framing just
above was wrong when it was written, and is deliberately LEFT AS WRITTEN because
this is a dated record of what was believed on 2026-09-14.** Those ten are stock
DoD maps; five of them do not appear in the fleet's `ktp_maps.ini` at all. The
measured position is in `build/bots/README.md` — **"The custom competitive pool
has no waypoints at all."** ⛔ **Do not rewrite the entry to match** — rewriting a
dated note into a present-tense truth makes the date lie. Read it as of its day.

**`BotSpec.NEW_BOT` now holds facts, not guesses**, read from the shipped
`_README.txt` / `_COMMANDS.txt`: `addbot {team} {class} {skill} {name}` (team
accepts allies/axis), `target_players {0-32}` to fill, and the objective knobs
`flag_priority_percent` / `wait_for_cap_percent` (defaults 70/75, raised to 100
so bots go to flags and stay on them — which is what cap-break capture needs).
Two prior guesses were wrong: the binary is `new_bot_mm.so`, not `new_bot.so`,
and it lives at `dod/new_bot/`, not `dod/addons/`.

**⛔ It cannot be activated.** new_bot's `_mm` suffix is literal — its README
says it is a Metamod plugin and "will crash" if loaded any other way. The KTP
stack is **Metamod-free**, confirmed inside the image: `dod/addons/` holds only
`extensions.ini` + `ktpamx`, `extensions.ini` points at
`addons/ktpamx/dlls/ktpamx_i386.so`, `liblist.gam` still has
`gamedll_linux "dlls/dod.so"`, and `find -iname "*metamod*"` returns nothing.
AMXX loads through ReHLDS's extension mechanism — the same reason
`CreateFakeClient` is unavailable and the DODX tests needed dispatch
primitives. There is no plugin loader for new_bot to register with.

Files are therefore installed but **deliberately not activated**, and
`BotKit.activation_blocker()` reports the reason as a fact so a Phase 0 run
explains itself instead of timing out. Activating it means installing Metamod
between the engine and `dlls/dod.so` while `ktpamx` still loads via
`extensions.ini`; whether those coexist is unverified, and it would give the bot
lane a different loader topology than production. That is a decision about the
stack under test, not a build detail, so it is not taken here.

Note: the image now contains a third-party binary that is not ours to
redistribute, so **it must not be pushed to a public registry**. It is a
local/CI artifact; the fleet consumes no images at all.

#### Bots run. Phase 0's premise is verified. (same series)

The question that has gated this work since the beginning — *can we get real
players into the world?* — is answered yes.

`scripts/spike_metamod_ab.py --split-layers` returns **8/8, exit 0**: both
topologies show 3 modules and the same plugin count, `amxxcurl + reapi + dodx`
present under both, and **zero differences**. And in ~60s of bot play on
`dod_anzio`: 12 bots entered / joined a team / picked a role, **10 kills** with
real weapons (thompson, luger, mp40, k43), **10 `triggered` events including
`dod_control_point` captures** on HILL / LAUNDRY / STREET / PLAZA, and 692
waypoints loaded.

Bots fight *and* capture flags — the two inputs the capture code needs: kills
drive assist attribution and cap-break candidacy, flag contention drives the
`dodx_area_get_data` zone poll. This retires the "24-player synthetic load —
requires bot tooling" non-goal in `TEST_INFRASTRUCTURE_PLAN.md` and the
`BOT_AI_REQUIRED_REASON` skips from 1.5.25.

- **The topology that works is `--split-layers`**: ktpamx keeps loading via
  `extensions.ini` exactly as production does, and Metamod hosts **only** the
  bot. Each loads once, at its own hook point, and ktpamx still logs "Running
  without Metamod - using ReHLDS hookchains". The obvious topology — Metamod
  hosting both — **segfaults 3 of 3**, because ktpamx reports "ReHLDS extension
  mode detected" even when Metamod loads it and so installs ReHLDS hookchains
  from inside Metamod's chain.
- **The bot cannot live inside KTPAMXX**, which is worth recording because it
  looks plausible. AMX Mod X is not a fork of Metamod, it is a Metamod *plugin*
  — hence `Meta_Attach` in `ktpamx_i386.so`. `CModule::queryModule()` checks
  modules for `Meta_Attach` only to label them `"amxx&mm"`; it still requires
  `AMXX_Query`. `new_bot_mm.so` has 0 of the former and 1 of the latter, and the
  engine says `[AMXX] Couldn't find "AMXX_Query"`.
- **The fingerprint now reads the server log, not rcon.** `amxx modules` /
  `amxx plugins` return *nothing* over rcon in extension mode — verified
  directly: with the server fully up, `status` returned 230 characters while
  `amxx version` and `amxx modules` both returned 0, and the log meanwhile
  showed "Completed initialization" and "SV_ActivateServer". AMXX is fine; its
  console commands just do not emit into rcon's redirect buffer when it is
  loaded as a ReHLDS extension. The log carries the same facts and does not
  depend on command registration, so it is now the primary source with rcon
  supplementary.

#### Verification (container path)

- `pytest tests/e2e_stats/` — **39 passed, 1 skipped**; full repo suite
  **202 passed, 70 skipped, 0 failed**.
- Both new YAML files parse; the workflow resolves to 1 job / 10 steps with
  `workflow_dispatch` + `schedule` triggers only (no `pull_request`, as intended).
- ~~The image has NOT been built.~~ **Superseded** — see "First real run of the
  image" above. It builds, the plugin compiles, mysqld serves, and the unit
  suite passes inside it. The prediction that the first build would need
  iteration held: it took five fixes.
- Still unrun: the bot half (no bot kit yet) and the daemon (`hlstats.pl` needs
  a populated database, which is blocked on the base-schema question). The
  `docker-compose.lane-b.yml` path is also still unexercised — all real runs so
  far went through `scripts/lane_b_local.sh`.

#### Verification (build + daemon)

- `pytest tests/e2e_stats/` — **35 passed, 1 skipped**.
- The build step was run for real against the actual branches:
  `--amxx-ref feat/stats-positions` (`5f0e5379`) and
  `--daemon-ref feat/seed-cap-break-action` (`a8c9a97`) — SHAs match
  `KTPR_DEPLOYMENT_PLAN.md`, all four daemon-side artifacts extracted, manifest
  written with md5s.
- Incidental finding, now documented in `artifacts.py`: `git show` may emit LF
  even where the working tree is CRLF, depending on `core.autocrlf` /
  `.gitattributes`. The CRLF normalisation before amxxpc is therefore
  unconditional rather than guarded on "looks like CRLF".
- Compile paths are covered by monkeypatched-compiler tests (failing rc,
  exit-0-writes-nothing, CRLF normalisation) rather than a real amxxpc — no
  AMXX toolchain on the authoring machine.

#### Verification

- `pytest tests/e2e_stats/` — 11 passed, 1 skipped (symlink case needs
  privileges on Windows).
- Mutation check on the write-through guard: disabling the unlink fails
  `test_write_text_does_not_touch_source[hardlink]` and
  `test_overlay_file_shadowing_an_existing_file_leaves_source_intact`.
- Full collection clean at 232 tests — the new package does not disturb the
  existing suites.
- `scripts/spike_bot_lane.py --help` resolves all imports, exit 0.
- Not yet run against a real bot or a real mysqld; that is Phase 0's own job
  on the runner.

### `ops`: disk-usage trend sampling in ktp-data-server-health (2026-08-02)

Three misconfigured systemd units wrote `/var/log/syslog` at 14.8 GiB/day from
2026-07-30 and reached 46 GiB before anyone noticed on 08-02 — at 49% used, which
trips no absolute ceiling. Worse, the box kept **no `df` history at all**
(`/var/log/sysstat` is empty; its collector was never enabled), so the growth rate
had to be reconstructed from file mtimes after the fact.

- **`scripts/ktp-data-server-health.sh`** — samples every real filesystem each
  hourly run and appends to `/var/log/ktp-disk-history.log`: timestamp, epoch,
  device, mount, size/used/avail KiB, use%, inode use%, plus the six largest
  entries directly under `/var/log`. `du -a` on that last one is deliberate — the
  incident was a single runaway *file*, which no directory listing surfaces.
- Two new conditions join the existing `down[]` set, so they inherit the
  transition-only alerting, the recovery edge and the embed for free:
  `disk-usage:<mount>` at ≥75% (also `disk-inodes:`), and
  `disk-growth:<mount>` at ≥3 GiB/day measured over ≥12 h of history. The rate
  trigger is the one that would have caught 07-30 on day one.
- Reported values are bucketed (5% steps; 3/5/10/20/40/80 GiB/day bands) because
  the set comparison reads an unbucketed "78%"→"79%" tick as one recovery plus one
  new failure — i.e. an hourly Discord post.
- Overridable for testing: `DISK_HISTORY`, `DISK_PCT_WARN`,
  `DISK_GROWTH_WARN_GIB`, `DISK_GROWTH_MIN_HOURS`.
- Every added command is `|| true`-guarded and the `/var/log` walk is
  `timeout`-bounded: disk sampling must never abort the service checks it rides on.
- **`scripts/ktp-disk-history.logrotate`** → `/etc/logrotate.d/ktp-disk-history`.
  Monthly, `rotate 12`, `maxsize 32M`, `delaycompress` (keeps `.1` plain text so
  the 24h lookback still resolves the day after a rotation). Also adopts
  `/var/log/ktp-data-server-health.log`, which was previously unrotated at 155 KiB
  and growing. Separate stanza on purpose — the `maxsize 1G` syslog cap in
  `/etc/logrotate.d/rsyslog` is owned elsewhere and was not touched.

Verified on `neindataatl`: alert path exercised against a loopback sink (never the
real relay) — rate trigger fires at the production 3 GiB/day threshold when fed the
real incident's 14.8 GiB/day; absolute trigger fires under a forced 5% ceiling;
recovery edge posts green; 2 GiB/day stays silent; a repeat run in the same bucket
stays silent; baseline still resolves out of a rotated `.1`. Clean run under cron's
own empty environment. Backup at
`/usr/local/bin/ktp-data-server-health.sh.bak-20260802-200233-pre-disk-sampling`;
new live md5 `870fc9e3…`.

Deploying this also closed pre-existing drift: the box was still running the dead
`<:ktp:1105490705188659272>` emoji token in its embed title (repo had been correct
since `a6b47cc`). Deployed file is now byte-identical to the repo copy.

### GitHub Sponsors funding integration (2026-07-21 / 22)

Stood up community funding for the fleet: a GitHub Sponsors profile
(`github.com/sponsors/afraznein`) with five tiers, plumbed into the repos and the
Discord tooling. Perks are recognition-only by design — sponsorship never affects
a match, a queue, roster spots, or anything competitive (a hard rule for a league
that runs an anti-cheat).

- **`SUPPORTERS.md`** — recognition list for $5-and-up sponsors, grouped by tier
  (Server Month $55 / Half a Server $25 / MVP $10 / Supporter $5). One bare-metal
  game server runs $55/mo, which anchors the top tier and the funding goal.
- **`scripts/list-sponsors.sh`** — on-demand sponsor/tier lister via the GitHub
  GraphQL API (`gh api graphql`); needs no extra token scope for login + tier
  (only `read:user` if timestamps are wanted).
- **`.github/FUNDING.yml`** rolled out to all 19 public KTP repos (Sponsor button
  → `github.com/sponsors/afraznein`).
- **Real-time alerts** — KTPAdminBot 0.9.10 serves `POST /github/sponsors` behind
  the `api.ktpdod.com` nginx vhost (exact-match location + `limit_req`), HMAC-SHA256
  verified, posting new/tier-change/cancel events to a Discord alert channel.
  Confirmed live end-to-end by GitHub's own setup ping. See the KTPAdminBot
  CHANGELOG for the handler detail.

### Documentation stack refresh (2026-07-20)

The two big reference docs had been carrying staleness banners since 2026-07-07;
both are now current and the banners are gone.

- **`docs/TECHNICAL_GUIDE.md`** — full refresh against the deployed fleet:
  all version callouts (engine 3.22.0.929, KTPAMXX 2.7.24, ReAPI 5.29.0.365-ktp,
  AmxxCurl 1.3.15-ktp, plugins, services); new Layer 1 sections for the async
  log writer, `KTP_ExtensionShutdown`, the every-attempt RCON audit, the
  `SV_ClientUserInfoChanged` re-enable, and lag-compensation config; a Layer 2
  extension-mode lifecycle section; DODX score-persistence natives; the
  KTPHLTVRecorder section rewritten for the 1.7.x always-on architecture
  (the retired 1.5.x record/stop text is gone); a Fleet Monitoring & Operations
  section (Netdata retirement, in-house monitoring set, nightly `.new` swap
  discipline); a KTPHudObserver section crediting Jimmy Lockhart's external
  DoD-hud-observer project (screenshot vendored to `docs/images/`, MIT);
  the installation guide gained the `extensions.ini` step with the correct
  path; remaining real host IPs in prose replaced with placeholders.
- **`docs/DEVELOPMENT_HISTORY.md`** — May, June, and July 2026 sections
  appended (HLTV rebuild + 1000fps + shutdown races; hitreg audit + LAN prep;
  the root-cause month), monthly scope table and totals updated.
- **`README.md`** — staleness note removed; fleet inventory corrected to 24
  instances (Chicago runs four); repo layout updated with `tests/`, `sites/`,
  and the monitoring additions; scheduled-task tables brought current.
- Point fixes: CHI5 rows in `monitoring/crashreporter/README.md` and
  `scripts/README-hltv-demo-renamer.md`; fleet counts in
  `TEST_INFRASTRUCTURE_PLAN.md`.

### Scrub placeholders were functioning as real secrets

The credential history-scrub replaced secrets with `REDACTED*` literals, and in
four places those literals had become working default values rather than obvious
errors. Each now fails loudly instead of deploying.

- `lan-deploy.sh` defaulted `SV_PASSWORD` to the literal `REDACTED`, so a run
  without an explicit value deployed `REDACTED` as the LAN join password — and
  the plan summary printed `Join password: REDACTED`, which reads like sanitized
  output rather than the actual credential. It cannot be auto-generated (players
  type it), so it is now required, and unset/`REDACTED*`/`CHANGEME` are refused.
  `lan-deploy.conf.example` documents the requirement.
- `provision-gameserver.sh` carried a guard whose comment claimed it refused
  placeholder HLTV secrets, but it only checked `HLTV_API_KEY`. The config
  generator was invoked with **no arguments**, so its `ADMIN_PASS`/`PROXY_PASS`
  defaults — `REDACTED_HLTV_ADMIN`/`REDACTED_HLTV_PROXY` — were what actually
  landed in live HLTV configs. `HLTV_ADMIN_PASS`/`HLTV_PROXY_PASS` are now
  required and passed through; the generator refuses to run without both.
- `setup-denver-dataserver.sh` defaulted `MYSQL_PASS` to `REDACTED_DB`. The
  existence probe swallows auth failures (`2>/dev/null || echo "0"`), so a bad
  password reported "no servers found" and the script inserted duplicate rows.
  Now required from the environment. Also dropped the unused `DENVER_PASSWORD`.

### Docs described files a fresh clone doesn't have

The same scrub that removed credential-bearing scripts from the tree left the
README describing them as shipped. On a maintainer's box every path resolves, so
the gap only appears to someone cloning fresh.

- Quick Start step 3 ran `provision/clone-ktp-stack.sh`, which is gitignored —
  the documented three-step provisioning sequence dead-ended. Now starts from the
  tracked `.example` and copies it, matching the convention the config flow
  already uses.
- The Scripts tables listed `ktp-scheduled-restart.sh`, `hltv-api.py`,
  `ktp-backup.sh` and `ktp-organize-hltv-demos.sh` as deployable artifacts
  alongside two that really are shipped, with nothing distinguishing them. Added
  a "Ships as" column marking which are `.example`-only.
- The structure tree had the same problem; entries now carry the `.example`
  suffix where that's what exists.

### Extension-loader path corrected in two docs

`DEVELOPMENT_HISTORY.md` and `TECHNICAL_GUIDE.md` both said KTPAMXX loads via
`rehlds/extensions.ini`. The engine reads `<gamedir>/addons/extensions.ini`
(`sys_dll.cpp:1067`); no `rehlds/` path exists. Part of a stack-wide correction
of this error across five files.
