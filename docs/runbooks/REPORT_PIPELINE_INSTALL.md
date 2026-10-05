# Report pipeline: first install on the data server

Match reports are built on `neindataatl` and pushed to the website. Nothing in
this pipeline existed on the box before Season 10; this runbook is the install.

Three commands run in order on a timer: `generate` turns finished matches in
`hlstatsx` into report rows, `aggregate` rolls those into season totals, and
`report_sync` pushes both to Supabase for ktpleague.gg to read.

Everything below needs root. It is a one-time setup.

## 1. Service account

Not `krodssh`. That is an interactive login for analysis and has never run
automation. The pipeline gets its own identity: SELECT on the tables it reads,
and INSERT on the two it owns.

Confirm the auth plugin first, because the `CREATE USER` below depends on it:

```bash
sudo mysql -N -e "SELECT user, host, plugin FROM mysql.user WHERE user='krodssh';"
```

Expect `auth_socket`. Anything else and the `CREATE USER` needs a different
clause — stop and ask rather than improvising one.

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin ktpreports
sudo mysql -e "CREATE USER 'ktpreports'@'localhost' IDENTIFIED WITH auth_socket AS 'ktpreports';"
```

The Linux user and the MySQL user must have the same name. `auth_socket`
authenticates by peer credential, so a mismatch fails at connect time with a
confusing access-denied rather than anything that names the cause.

Grant the tables the pipeline names, and nothing else. Don't copy `krodssh`'s
grants: they also cover `hlstatsx_lan` and `ktp_lan`, which the pipeline never
reads, and `SHOW GRANTS` prints lines with no trailing `;`, so piping them back
into `mysql` fails at line 2.

This block is written by hand but checked by machine: `check_report_grants.py`
derives the same set from the code and fails if the two disagree, so treat the
script's output as the source of truth and this block as a copy of it.

Two derivations of it have already gone stale. The 2026-09-13 one walked the
import closure of `scripts/report_service.py` and `scripts/report_sync.py` plus
`sql/analytics/*.sql` at `f498463`, and was never re-derived as the aim-shadow,
AC-precision and score/duel/grenade-throw sources landed; the 2026-09-21 one
found the five it had missed but fixed them by hand. Both failures are the same
shape — a list of table names that no test held to the code that reads them.

The probe leg matters even though `sql/analytics/*.sql` happens to name every
probed table today: a capability probe can be added before the SQL that consumes
it, and in that window the probe is the only place the table appears. A grep over
the pipeline's Python alone never sees the probed tables at all.

The pipeline only appends — a new report or aggregate is a new revision row — so
there is no UPDATE or DELETE.

```bash
sudo mysql <<'SQL'
GRANT SELECT ON hlstatsx.hlstats_Actions                    TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.hlstats_Events_Frags               TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.hlstats_Events_PlayerActions       TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.hlstats_Events_PlayerPlayerActions TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.hlstats_Events_Statsme             TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.hlstats_Events_Statsme2            TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.hlstats_Events_Suicides            TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.hlstats_Events_Teamkills           TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.ktp_ac_weapon_fires                TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.ktp_assist_events                  TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.ktp_capture_health                 TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.ktp_capture_manifests              TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.ktp_damage_events                  TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.ktp_duel_stats                     TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.ktp_flag_captures                  TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.ktp_flag_positions                 TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.ktp_flag_state_events              TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.ktp_grenade_entity_events          TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.ktp_grenade_throw_events           TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.ktp_life_events                    TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.ktp_match_players                  TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.ktp_match_stats                    TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.ktp_matches                        TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.ktp_objective_attempt_events       TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.ktp_position_samples               TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.ktp_score_events                   TO 'ktpreports'@'localhost';
GRANT SELECT ON hlstatsx.ktp_shot_events                    TO 'ktpreports'@'localhost';
GRANT SELECT, INSERT ON hlstatsx.ktp_match_reports          TO 'ktpreports'@'localhost';
GRANT SELECT, INSERT ON hlstatsx.ktp_web_season_aggregates  TO 'ktpreports'@'localhost';
SQL
```

When the code starts reading a new table — including a new `information_schema`
probe added to `source_capabilities()`, not just a new `FROM`/`JOIN` — add it here
and grant it. Don't maintain this block by hand and don't re-derive it by grepping:
both went stale once each, which is why the check below derives it instead.

### Check the grants against the code

`source_capabilities()` decides which optional sources to use by asking
`information_schema` whether each table exists, and MySQL hides tables the
account holds no privilege on. A missing grant therefore looks like a missing
table: that source is skipped, the report comes out WARN, and it still
publishes. No error anywhere.

`scripts/check_report_grants.py` derives the table set from the code — the
`source_capabilities()` probes unioned with the `FROM`/`JOIN` closure over the
pipeline's Python and `sql/analytics/*.sql` — and names any table that set holds
and the grants don't. It exits 1 on a discrepancy and 2 when it could not run at
all, so a clean 0 is the only result that means anything:

```bash
# on the data server, as the account
cd /opt/ktp-reports/KTPInfrastructure
sudo -u ktpreports python3 -m scripts.check_report_grants --source both
```

`--source runbook` needs no database and is what `tests/unit/test_report_grants.py`
gates in CI; `--source live` reads `SHOW GRANTS` and needs the box. Both legs are
worth running: the live grants were already complete on 2026-09-21 while this
block was short five tables, so the live leg alone cannot see a defect in the
rebuild path, and the runbook leg alone cannot see drift on the box.

To confirm you measured the right account:

```bash
sudo -u ktpreports mysql --user=ktpreports hlstatsx -N -e "SELECT CURRENT_USER()"
```

Pass `--user` every time: without it `sudo -u` sends `root` and gets `ERROR 1698`,
and the account has no home, so there is no `.my.cnf` to fall back on. If
`CURRENT_USER()` names anyone else, you measured the wrong account.

### Smoke-test the writes without leaving a row

The account cannot DELETE, so an insert-then-delete smoke test fails halfway
and strands a permanent `smoke-test` row in an append-only table. Both tables
are InnoDB, so roll it back instead:

```sql
-- sudo -u ktpreports mysql --user=ktpreports hlstatsx
SELECT COUNT(*) FROM ktp_match_reports;
START TRANSACTION;
INSERT INTO ktp_match_reports
  (match_id, schema_version, revision, generated_at, quality_status, publishable, report_sha256, report)
  VALUES ('smoke-test', 0, 1, NOW(), 'SMOKE', 0, REPEAT('0', 64), '{}');
SELECT ROW_COUNT();   -- 1
ROLLBACK;
SELECT COUNT(*) FROM ktp_match_reports;   -- same as before

SELECT COUNT(*) FROM ktp_web_season_aggregates;
START TRANSACTION;
INSERT INTO ktp_web_season_aggregates
  (kind, revision, generated_at, source_report_count, report_schema_version, payload_sha256, payload)
  VALUES ('smoke-test', 1, NOW(), 0, 0, REPEAT('0', 64), '{}');
SELECT ROW_COUNT();   -- 1
ROLLBACK;
SELECT COUNT(*) FROM ktp_web_season_aggregates;   -- same as before
```

If either count moved, a row was committed: stop and have root remove it.

## 2. Deployment checkout

A real checkout owned by `ktpreports`. Not the Actions runner's work directory
under `/opt/ktp-tier2-runner`, which is CI scratch and gets wiped. Not
`/opt/ktp-infra` either — that is a separate, deliberately stale copy that the
weekly fleet audit runs from and that never pulls.

To inspect this checkout, run git as its owner: `sudo runuser -u ktpreports -- git -C /opt/ktp-reports/KTPInfrastructure log -1`.
Root's git refuses a repository it does not own and prints an empty remote, which reads as
"there is no checkout here".

```bash
sudo install -d -o ktpreports -g ktpreports /opt/ktp-reports
sudo -u ktpreports git clone https://github.com/afraznein/KTPInfrastructure.git \
  /opt/ktp-reports/KTPInfrastructure
```

## 3. The Supabase secret

```bash
sudo install -d -m 0750 -o root -g ktpreports /etc/ktp
sudo install -m 0640 -o root -g ktpreports /dev/null /etc/ktp/reports.env
```

Then write into `/etc/ktp/reports.env`:

```
KTP_SUPABASE_URL=https://yxpjfenpnwksvvquqlde.supabase.co
KTP_SUPABASE_SECRET_KEY=<service-role secret>
KTP_SITE_REVALIDATE_SECRET=<INTERNAL_WARM_SECRET>
```

This is the **service-role** secret, not the publishable key. The publishable
key is read-only and public by design; this job writes. It must never reach a
game server or the website repo.

`KTP_SITE_REVALIDATE_SECRET` is the site's `INTERNAL_WARM_SECRET` (same value
the warm/purge endpoints use, not a new one). After a run that POSTs at least
one new row to `ktp_match_reports`, `report_sync.revalidate_site()` sends it as
`x-internal-revalidate` to `https://ktpleague.gg/api/internal/revalidate` with
`{"scope": "ktp"}`, so `/stats/matches` stops waiting for its own hourly cache
turnover. Optional by design: if it is unset, `report_sync` logs one warning
and continues -- it never fails the run over a missing cache-refresh secret.
On an HTTP error or a network timeout it retries once, logs loudly, and still
returns 0; the synced report simply waits for the site's own cache turnover.

## 4. Install the units

```bash
sudo install -m 0644 /opt/ktp-reports/KTPInfrastructure/systemd/ktp-reports.service /etc/systemd/system/
sudo install -m 0644 /opt/ktp-reports/KTPInfrastructure/systemd/ktp-reports.timer   /etc/systemd/system/
sudo systemctl daemon-reload
```

Dry-run the sync before arming anything. This is the step that catches a
misplaced or unreadable secret, and it writes nothing:

```bash
sudo -u ktpreports env $(sudo cat /etc/ktp/reports.env | xargs) \
  python3 -m scripts.report_sync --since 2026-09-13 --dry-run
```

Run it from `/opt/ktp-reports/KTPInfrastructure`. It should report what it
would push and exit 0. `missing env KTP_SUPABASE_URL` means the file is not
readable by the account — check group ownership and the `0640` mode.

These work because `report_service.py` passes `--user` explicitly. It did not
always: plain `mysql` sends `root` even when the process really is uid
`ktpreports` and `$USER`/`$LOGNAME` are already `ktpreports` — measured,
including with `--no-defaults` and with the environment unset. The server then
refuses with `ERROR 1698 (28000): Access denied for user 'root'@'localhost'`,
which reads exactly like a broken pipeline rather than a wrong invocation.

An earlier version of this page blamed `sudo -u` for leaking `$USER` and told
you to unset it. **That was wrong** — those variables are already correct
under `sudo`, and unsetting them changes nothing. The fix belongs in the client
invocation, not the shell.

Then arm it:

```bash
sudo systemctl enable --now ktp-reports.timer
systemctl list-timers ktp-reports.timer
```

## 5. Confirm after the first real match

Three counts, walking the chain in order. The first that reads zero says where
it stopped.

```sql
SELECT COUNT(*) FROM ktp_match_reports;          -- generate ran
SELECT COUNT(*) FROM ktp_web_season_aggregates;  -- aggregate ran
```

Then open <https://ktpleague.gg/stats/matches>. The empty-state text should be
gone and the match listed.

| Symptom | Cause |
|---|---|
| 0 reports | Timer never fired, or the match is before the `--since` floor |
| Reports but 0 aggregates | `aggregate` failed; read the second ExecStart in the journal |
| Both built, site empty | `report_sync` did not push. Almost always the secret |
| A rating renders negative | Checkout is behind `main`; the display floor is 50 |

```bash
journalctl -u ktp-reports.service -n 50 --no-pager
```

### Use the verifier, not a row count

`SELECT COUNT(*) FROM ktp_match_reports` returns 0 when the timer never ran,
when it ran and correctly found nothing, and when it ran and failed — and the
site answers 200 in all three. The verifier tells those apart and exits
non-zero when the pipeline is broken:

```bash
cd /opt/ktp-reports/KTPInfrastructure
sudo -u ktpreports python3 -m scripts.verify_report_pipeline --since 2026-09-13 --site https://ktpleague.gg
```

It reads `/var/log/ktp-report-service.log`, which the unit writes via
`StandardOutput=append:`. If that file is absent the `RAN` check fails, which
is the correct answer to "did it run" rather than a fault in the verifier.

## Importing the weekly MMR payload

The ladder runs in CI, which holds no write credential here, so it publishes a file on the
`mmr-ratings` branch and the box inserts it:

```bash
cd /opt/ktp-reports/KTPInfrastructure
sudo -u ktpreports python3 -m scripts.report_service --repo . import-mmr /tmp/<payload>.json
```

Run it from the serving checkout, as `ktpreports`. `import-mmr` loads its validators out of
`--repo`, so a personal or behind checkout guards a production write with code the box is not
running; and the grant is `auth_socket`, tied to that account name. Stage the payload outside
the checkout — it is not a tracked file and does not belong in one.

Only `mmr_openskill_payload.json` and `rating_methodology_payload.json` are importable.
**Never substitute `ratings_current.json`.** It is the ladder's internal state, keyed by raw
numeric player ids, and this aggregate is published to a public page. `validate_for_import`
does refuse it — it carries no `kind` and no `players` — but on shape, so the identifier leak
is stopped by accident rather than by a check that names it.

Acceptance is a row, not a log line: `SELECT COUNT(*) FROM ktp_web_season_aggregates WHERE
kind='mmr_openskill'`. The website's profile card stays empty until players clear the payload's
own `min_matches` floor, so an empty card after a good import is expected, not a failure.

## The `--since` floor

`ktp-reports.service` pins `--since 2026-09-13`, and every step also requires an
official match type: `.ktp` (0) or `.ktpOT` (4), the set KTPMatchHandler's
`is_official_match_type()` uses, defined once in `scripts/report_scope.py`.
Scrims, 12mans, drafts and untyped (NULL) matches are never reported, whatever
their date. Widening either publishes practice matches as league results.

All three steps apply the same scope: an official-type half that started on or
after the floor. `aggregate` and `report_sync` refuse to start without a floor.
`generate` only uses it to discover matches; a report persisted any other way (an
explicit match id, a manual test run by someone with INSERT on
`ktp_match_reports`) is still held back by `aggregate`, which will not pool it
into the season, and by `report_sync`, which will not push it. They print
`held back by --since …: N` and `held back by match_type …: N` when they skip
one, and `generate <match_id>` warns when an explicit id is out of scope. A
report whose match has no `ktp_matches` row is held back too, since neither its
date nor its type can be proved.

When you move the floor for a new season, move it on all three `ExecStart` lines.

Nothing is lost by a late install. `generate` reads `hlstatsx` retroactively, so
matches played before the timer existed still publish on the first run.

## Regenerating reports by hand: the gated workflow

Regeneration runs from GitHub, not from a shell on the box:
**Actions → Report Regeneration → Run workflow**, on `main`. The job runs on the
tier-2 runner, which is root on this server, so every run is a production
change and waits for an approval click before it starts.

**Who can trigger it:** anyone with write access to this repository (that is
what `workflow_dispatch` requires). **Who lets it run:** the required reviewer
on the `report-regeneration` environment, the operator (`afraznein`). A run
nobody approves sits in "Waiting" and does nothing.

**Dry run first.** `dry_run` defaults to on. A dry run persists nothing, syncs
nothing and refreshes no cache: it runs `generate --dry-run` (how many reports
would be built) and `report_sync --dry-run` (what would be pushed), and the job
summary shows the counts. Read them, then dispatch again with `dry_run` off.
Each dispatch needs its own approval.

Inputs:

| Input | Meaning |
|---|---|
| `scope = pending` | Exactly what the 15-minute timer runs: `systemctl start ktp-reports.service`. After a report schema bump lands on main this is the corpus-wide regeneration, because `generate` revisits every report stamped at an older schema version. |
| `scope = match_ids` | A new revision for the listed matches (`generate <ids>`), then the service for aggregate and sync. Refused while the service is running or when the next timer tick is under 8 minutes away, because `generate` has no lock against the timer. |
| `dry_run` | On by default. Off means it writes. |
| `reason` | Required. Logged with your GitHub login in the job log and in `/var/log/ktp-report-regeneration.log`. |

There is no date-range scope: `generate --since` only floors discovery, and the
season floor is read from the installed unit, never typed in.

What the job refuses, before running anything:

- `/opt/ktp-reports/KTPInfrastructure` dirty (any modified or untracked path).
- Its HEAD not equal to `origin/main` after a fetch, or the dispatched commit
  not equal to that same commit. The job fetches (one ref, `--refmap=`, as
  `ktpreports`) and never pulls, merges or checks out, so a behind checkout
  stays behind and the run stops. Bring the checkout to main first, as its
  owner: `sudo runuser -u ktpreports -- git -C /opt/ktp-reports/KTPInfrastructure merge --ff-only origin/main`.
- A dispatch from any branch other than `main`.

What it prints: counts only. Reports name players, so the pipeline's own output
(match ids, names, errors) goes to `/var/log/ktp-report-regeneration.log`
(root-only, `0600`) and `/var/log/ktp-report-service.log`, never to the public
Actions log.

Site cache: a real run refreshes it the way the timer does, through
`report_sync`'s revalidate call, which fires only after it pushed at least one
report. A dry run never refreshes it.

Interim: Drew's manual regeneration runs on the box end when this workflow
first runs green, or on 2026-10-31, whichever comes first.

### One-time setup (operator)

1. Settings → Environments → New environment `report-regeneration`.
2. Required reviewers: `afraznein`. Deployment branches: `main` only.
3. Leave "Prevent self-review" off if you want to approve your own dispatches.

The workflow never creates or edits the environment. Until it exists, the
first dispatch creates an environment with no protection rules, so create it
before anyone dispatches.
