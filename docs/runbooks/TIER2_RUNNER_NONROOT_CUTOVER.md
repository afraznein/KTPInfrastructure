# Runbook: move the tier-2 runner off root

**Written 2026-11-10.** Nothing here has been run yet. Every step is an operator act,
as root on the data server (`neindataatl`), in one window of about 30 minutes.

## Why

`tier2-integration.yml` is the only workflow here that a pull request can trigger, and it
runs on `[self-hosted, ktp-tier2]`. Today that runner's service is `User=root`, so a job
that reaches it runs as root on the box that holds MySQL, the AC API and every vhost.
Fork PRs now need approval and are skipped by a same-repo guard, but an approved job, and
everything that job pulls in (PyPI, the HUD observer plugin), still runs as root.

The integration job needs nothing only root can do. It writes under
`/opt/ktp-tier2-runner/{actions-runner,serverfiles}`, truncates the run marker, reads two
files in `/etc/ktp`, and binds `127.0.0.1:0`. There is no sudo, systemctl, docker or MySQL in
it, and no port below 1024.

`fleet-audit.yml` and `report-regeneration.yml` do need root (`/root/.ssh` keys, 600
configs, `/var/lib` state, `runuser`, `systemd-run`, `systemctl`). Neither has a PR trigger.
They move to a second runner, `ktp-ops`, which stays root for now.

| runner | user | label | serves |
|---|---|---|---|
| `ktp-tier2-neindataatl` (id 21, existing) | `ktp-tier2`, no sudo | `ktp-tier2` | `tier2-integration.yml` |
| `ktp-ops-neindataatl` (new) | root | `ktp-ops` | `fleet-audit.yml`, `report-regeneration.yml` |
| `ktp-ci` (from the install-allowlist runbook) | `ktp-ci` | `ktp-ci-install` | `ci-install.yml` |

⚠️ **Labels are not a security boundary on a personal-account repo.** Runner groups exist
only for organisations, so any workflow, including one a PR adds, can name any label. An
approved fork PR can still target `ktp-ops`. Until no root runner is registered to this
public repo, the fork-approval policy and reading `.github/` before approving a fork run
remain the outer wall.

## Order, and what breaks if it is wrong

| # | step | merge / act | if done out of order |
|---|---|---|---|
| 1 | heartbeat `ts` validation and the single-path listener pattern | merge, then **install** with `ktp-install` (heartbeat script + cron file) | chowning the marker before this gives any tier-2 job root through the heartbeat cron; a second runner reads as `DUPLICATE runner listener` |
| 2 | register `ktp-ops` (§ A) | operator | — |
| 3 | PR moving the ops jobs to `[self-hosted, ktp-ops]` | merge only once `ktp-ops` is online | the ops jobs queue for up to 24 h and then fail |
| 4 | the cutover window (§ B) | operator | — |
| 5 | PR adding the refuse-root step to `tier2-integration.yml` | merge only after § B passes | `integration` is a required check: merged early, it blocks every merge on main |

## A. Register the ops runner (any day before the window)

```bash
OPS=/opt/ktp-ops-runner/actions-runner
mkdir -p "$OPS" && cd "$OPS"
# same runner release as the tier-2 runner: compare ./bin/Runner.Listener --version on both
tar xzf <actions-runner-linux-x64-<version>.tar.gz>
./config.sh --url https://github.com/afraznein/KTPInfrastructure --token <registration token> \
  --name ktp-ops-neindataatl --labels ktp-ops --unattended
./svc.sh install root && ./svc.sh start
U_OPS=actions.runner.afraznein-KTPInfrastructure.ktp-ops-neindataatl.service
mkdir -p /etc/systemd/system/$U_OPS.d
cp /etc/systemd/system/actions.runner.afraznein-KTPInfrastructure.ktp-tier2-neindataatl.service.d/10-restart.conf \
   /etc/systemd/system/$U_OPS.d/
systemctl daemon-reload
```

Check:

```bash
gh api repos/afraznein/KTPInfrastructure/actions/runners -q '.runners[] | [.id,.name,.status,([.labels[].name]|join(","))] | @tsv'
```

`ktp-ops-neindataatl` must be `online` with `self-hosted,Linux,X64,ktp-ops`. Then merge
step 3 and dispatch `fleet-audit.yml` with `dry_run=true`; the job page must name
`ktp-ops-neindataatl` as its runner.

## B. The cutover window

**When:** a weekday, daytime ET, operator present. Not 09:00 UTC ± 30 min (the nightly
tier-2 run, about 5 minutes), not Monday 09:00 UTC (fleet-audit). Touches no game server,
HLTV, MySQL or nginx; the only restart is the runner's own unit.

**Go only when both hold:**

```bash
gh api repos/afraznein/KTPInfrastructure/actions/runners/21 -q .busy        # false
gh run list -R afraznein/KTPInfrastructure --status in_progress             # empty
```

```bash
RUN=/opt/ktp-tier2-runner
U=actions.runner.afraznein-KTPInfrastructure.ktp-tier2-neindataatl.service
B=/root/runner-deroot-bak-$(date +%Y%m%dT%H%M%S)
```

1. **Confirm step 1 is installed.** The installed heartbeat must contain the validation and
   the cron file must carry the pattern line:
   ```bash
   grep -c 'is_epoch' /usr/local/bin/ktp-tier2-heartbeat.sh                       # >= 2
   grep -c '^KTP_TIER2_LISTENER_PATTERN=' /etc/cron.d/ktp-tier2-heartbeat         # 1
   grep -c 'zqwbw1110' /usr/local/bin/ktp-tier2-heartbeat.sh                      # 0 (control)
   ```
   If the first two are not met, stop. Do not chown the marker.
2. **Snapshot** (outside the runner tree):
   ```bash
   mkdir -m 700 "$B"
   cp -a /etc/systemd/system/$U /etc/systemd/system/$U.d "$B"/
   find "$RUN" -xdev -printf '%u:%g %m %p\n' > "$B/owners.txt"; wc -l "$B/owners.txt"
   stat -c '%U:%G %a %n' /etc/ktp /etc/ktp/tier2-test-rcon.env /etc/ktp/discord-relay.conf > "$B/etc-ktp.txt"
   ```
3. **Stop the runner, and make sure no listener survives:**
   ```bash
   cd "$RUN/actions-runner" && ./svc.sh stop
   ps -eo user,pid,ppid,args | grep -F "$RUN/actions-runner/bin/Runner.Listener" | grep -v grep
   ```
   The `ps` must print nothing. A leftover listener on PPID 1 keeps taking jobs **as root**
   while `systemctl` reports the migration done; kill it before going on.
4. **Create the user**, with no supplementary groups (never `sudo`, `ktpreports` or `ktp-ci`):
   ```bash
   useradd --system --user-group --create-home --home-dir "$RUN/home" --shell /usr/sbin/nologin ktp-tier2
   ```
5. **Ownership.**
   ```bash
   chown -R ktp-tier2:ktp-tier2 "$RUN/actions-runner" "$RUN/serverfiles"
   chown ktp-tier2:ktp-tier2 "$RUN/tier2-last-run.json"
   chmod -R g-w,o-w "$RUN/serverfiles"
   ```
   `actions-runner/` itself (today `hltvserver`) and `_work/_tool` are inside the first path;
   missing either breaks the runner's self-update or `setup-python`. These stay root, so the
   runner cannot change them: `$RUN` itself, `toolchain/`, `stage-manifest.json`,
   `stack-sync.json`, every `stack-bak-*` directory, and the preprod marker.
6. **Two secret files, read-only, nothing else in `/etc/ktp`:**
   ```bash
   chmod o+x /etc/ktp
   chgrp ktp-tier2 /etc/ktp/tier2-test-rcon.env /etc/ktp/discord-relay.conf
   chmod 640 /etc/ktp/tier2-test-rcon.env /etc/ktp/discord-relay.conf
   ```
   `o+x` is traversal only; every other file there stays 600 or 640. ⛔ Never give that
   group write: the heartbeat cron **sources** `discord-relay.conf` as root.
7. **Reinstall the service as the new user** (the unit name and its `.d/10-restart.conf`
   drop-in are kept):
   ```bash
   cd "$RUN/actions-runner" && ./svc.sh uninstall && ./svc.sh install ktp-tier2 && ./svc.sh start
   ```

### Verify — each check has a control

| | command | must |
|---|---|---|
| a | `systemctl show $U -p User` | `User=ktp-tier2` |
| a | `ps -eo user,pid,ppid,args \| grep -F "$RUN/actions-runner/bin/Runner.Listener" \| grep -v grep` | exactly one line, user `ktp-tier2`, PPID not 1 |
| b | `gh api repos/afraznein/KTPInfrastructure/actions/runners/21 -q '.status,.busy'` | `online`, `false` |
| c | `sudo -u ktp-tier2 touch /usr/local/bin/zqwbw1110-probe` | Permission denied |
| c | `sudo -u ktp-tier2 cat /etc/ktp/audit-fleet.json` | Permission denied |
| c | `sudo -u ktp-tier2 sudo -n true` | refused |
| c | `sudo -l -U ktp-tier2` | not allowed to run sudo |
| d | `sudo -u ktp-tier2 test -r /etc/ktp/tier2-test-rcon.env && echo R` | prints `R` |
| d | `sudo -u ktp-tier2 test -r /etc/ktp/discord-relay.conf && echo R` | prints `R` |
| d | `sudo -u ktp-tier2 test -w /etc/ktp/discord-relay.conf && echo W` | prints nothing |
| d | `sudo -u ktp-tier2 test -w "$RUN/serverfiles/dod/addons/ktpamx/plugins" && echo W` | prints `W` |

The negative controls (c) only mean something next to the positive ones (d): a user who
can do nothing at all also passes (c).

**e. A real run.** `gh workflow run tier2-integration.yml -R afraznein/KTPInfrastructure --ref main`.
It must be green **and** its passed/failed/skipped counts in `tier2-report.json` must match
the last root run's. ⚠️ A permission problem shows up as more skips, and a run with more
skips still reads green. The log must show the plugin install, the KTPWitness build and the
HUD observer staging lines, and the Discord result embed must have posted.

**f.** `stat -c '%U %y' $RUN/tier2-last-run.json` is `ktp-tier2` with a fresh mtime, and its
`outcome` is `success`.

**g.** The next six-hourly heartbeat raises no listener alert and no stale alert.

**h.** Merge step 5 (refuse root), then open a trivial same-repo PR touching
`tests/integration/`; it must go green through the new step.

## Rollback (under 5 minutes)

If step 5 has merged, **revert it first**, or every tier-2 run fails and main is blocked.

```bash
cd "$RUN/actions-runner" && ./svc.sh stop && ./svc.sh uninstall && ./svc.sh install root && ./svc.sh start
chmod o-x /etc/ktp
chown root:root /etc/ktp/tier2-test-rcon.env /etc/ktp/discord-relay.conf
chmod 600 /etc/ktp/tier2-test-rcon.env /etc/ktp/discord-relay.conf
systemctl show $U -p User        # User=root
```

Ownership in the tree can stay as it is; root reads everything. A `ktp-tier2`-owned marker
under a root runner is safe only because step 1 is installed. `$B/owners.txt` holds the
previous owners if a full restore is wanted.

## After the cutover

- `sync-runner-stack.py` and `stage-runner.py` SFTP in as root. An overwritten file keeps its
  owner; a **new** file or directory lands root-owned, and a root-owned directory blocks
  the runner's writes. Run `chown -R ktp-tier2:ktp-tier2 $RUN/serverfiles` after every sync
  until those tools do it themselves.
- Still to do, with the runner already de-rooted: open the stack-drift checker's files with
  `O_NOFOLLOW` (it runs as root over a tree the runner now owns), have the crash reporter
  skip cores owned by `ktp-tier2`, and move the relay credential the runner reads to a
  tier-2-only one.
- The second phase takes `ktp-ops` off root as well: an audit user with its own key and
  state directory (`KTP_AUDIT_FLEET_CONFIG`, `KTP_AUDIT_STATE_DIR`), and a root-owned
  report-regeneration wrapper behind exact sudoers lines. Or register `ktp-ops` to a private
  repo instead, which takes it out of fork reach entirely.
