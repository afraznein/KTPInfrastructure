# Runbook: move the tier-2 runner off root

**Written 2026-11-10, corrected 2026-11-11 against the live box.** Steps 1 to 3 are done:
the heartbeat fix is installed, `ktp-ops` is registered (§ A) and the ops jobs run on it.
What is left is § B, an operator act as root on the data server (`neindataatl`) in one
window of about 30 minutes, then step 5. Run § B with `scripts/tier2-runner-cutover.sh`
rather than by hand; see [Running § B](#running--b).

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
| `ktp-tier2-neindataatl` (id 21, existing) | `ktp-tier2`, no sudo (root until § B) | `ktp-tier2` | `tier2-integration.yml` |
| `ktp-ops-neindataatl` (id 22, registered 2026-11-10) | root | `ktp-ops` | `fleet-audit.yml`, `report-regeneration.yml` |
| `ktp-ci-neindataatl` (id 23, registered 2026-11-11 per [CI_INSTALL_ALLOWLIST.md](CI_INSTALL_ALLOWLIST.md)) | `ktp-ci`, unprivileged | `ktp-ci-install` | `ci-install.yml` |

Three listeners therefore run on the box. Any check that counts listeners has to match the
runner's own binary path (`/opt/ktp-tier2-runner/actions-runner/bin/Runner.Listener` for
tier 2), never the bare name `Runner.Listener`.

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
# same runner release as the tier-2 runner: compare the "Runner.Listener/<version>" entry in
# bin/Runner.Listener.deps.json on both (Runner.Listener --version writes a _diag log)
tar --no-same-owner -xzf <actions-runner-linux-x64-<version>.tar.gz>
find "$OPS" ! -user root | wc -l      # must be 0 before going on
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

⚠️ **Unpack with `--no-same-owner`.** As root, a plain `tar xzf` keeps the uid stored in
the archive, which is 1001. On this box uid 1001 is `hltvserver`, the user the HLTV API
runs as. The 2026-11-10 registration used a plain `tar` and left 11,556 files under
`/opt/ktp-ops-runner/actions-runner` owned by `hltvserver`, including `bin/` and
`externals/`, so that user could have replaced the `Runner.Worker` that root executes for
every ops job. The tier-2 tree had the same 11,557 from its own unpack. Both trees were
chowned to root that night. The `find` above is the check: anything but 0 means stop and
`chown -R root:root "$OPS"`.

`ktp-ops-neindataatl` must be `online` with `self-hosted,Linux,X64,ktp-ops`. Then merge
step 3 and dispatch `fleet-audit.yml` with `dry_run=true`; the job page must name
`ktp-ops-neindataatl` as its runner.

## B. The cutover window

**When:** operator present, and clear of two schedules:

- **The tier-2 heartbeat cron**, `0 */6 * * *` in the box's timezone (America/New_York), so
  00:00, 06:00, **12:00** and 18:00 ET. Noon sits inside an ordinary daytime window. A
  heartbeat that runs while the runner is stopped records `listeners=0`, posts an alert,
  then alerts again on recovery. Start at least 40 minutes before a slot and no sooner than
  5 minutes after one.
- **The nightly tier-2 run**, 09:00 UTC (about 5 minutes). Stay out of 08:30 to 09:45 UTC.

The fleet audit no longer constrains the window: it runs on `ktp-ops` now, not on this
runner. The window touches no game server, HLTV, MySQL or nginx; the only restart is the
runner's own unit. Ask other sessions not to open `KTPInfrastructure` pull requests during
it: a job that arrives while the runner is down queues and then runs as the first
`ktp-tier2` job, which muddies check e.

**Go only when no tier-2 job is running.** The box has no `gh`, so the check that counts is
local, and it needs both signals:

```bash
ps -eo uid=,pid=,args= | grep -F /opt/ktp-tier2-runner/actions-runner/bin | grep -F Runner.Worker | grep -v grep   # nothing
find /opt/ktp-tier2-runner/actions-runner/_diag -name 'Worker_*.log' -mmin -2 | wc -l                          # 0
```

The log check is not redundant. A pull-request job that skips itself finishes in seconds,
so by the time anyone looks there is no `Runner.Worker` left, but its worker log is still
fresh. On 2026-11-10 the log check caught exactly that, after the process check had passed.
From the workstation, `gh api repos/afraznein/KTPInfrastructure/actions/runners/21 -q .busy`
should also print `false`.

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
   ps -eo uid=,pid=,ppid=,args= | grep -F "$RUN/actions-runner/bin/Runner.Listener" | grep -v grep
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
   `actions-runner/` itself and `_work/_tool` are inside the first path; missing either
   breaks the runner's self-update or `setup-python`. `serverfiles/` is not root-owned
   today: it is `ftpuser:ftpuser 775`, with most entries owned by `ftpuser` and the rest by
   root, because an overwritten file keeps its owner. That is harmless (`ftpuser` is
   chrooted to the FastDL docroot), but the chown erases it, and only `$B/owners.txt` can
   put it back. These stay root, so the runner cannot change them: `$RUN` itself,
   `toolchain/`, `stage-manifest.json`, `stack-sync.json`, every `stack-bak-*` directory,
   and the preprod marker.
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
| a | `ps -eo uid=,pid=,ppid=,args= \| grep -F "$RUN/actions-runner/bin/Runner.Listener" \| grep -v grep` | exactly one line, the uid of `ktp-tier2` (`id -u ktp-tier2`), PPID not 1 |
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

⚠️ **Match the listener on uid, not on the `user` column.** procps-ng truncates a user name
longer than 8 characters, so `ps -eo user` prints `ktp-tier2` as `ktp-tie+` (on this box
`hltvserver` already prints as `hltvser+`). A check for the literal name then fails, or
gets passed by eye. `ps -eo user:20,...` also works.

**e. A real run.** `gh workflow run tier2-integration.yml -R afraznein/KTPInfrastructure --ref main`.
It must be green **and** its passed/failed/skipped counts in `tier2-report.json` must match
the last root run's. ⚠️ A permission problem shows up as more skips, and a run with more
skips still reads green. The log must show the plugin install, the KTPWitness build and the
HUD observer staging lines, and the Discord result embed must have posted.

**f.** `stat -c '%U %y' $RUN/tier2-last-run.json` is `ktp-tier2` with a fresh mtime, and its
`outcome` is `success`.

**g.** The next six-hourly heartbeat raises no listener alert and no stale alert.

**h.** Prove step 5 before merging it. Push an **empty commit** to its branch
(`ci/tier2-refuse-root`, #847) from a worktree; never `gh run rerun`. The refuse-root step
is the job's first step and has no condition, so it runs on any same-repo push. It must
print `Running as ktp-tier2, uid <n>.` and `integration` must go green. Then mark the PR
ready and merge it.

## Rollback (under 5 minutes)

If step 5 has merged, **revert it first**, or every tier-2 run fails and main is blocked.

```bash
cd "$RUN/actions-runner" && ./svc.sh stop; ./svc.sh uninstall; ./svc.sh install root && ./svc.sh start
chmod o-x /etc/ktp
chown root:root /etc/ktp/tier2-test-rcon.env /etc/ktp/discord-relay.conf
chmod 600 /etc/ktp/tier2-test-rcon.env /etc/ktp/discord-relay.conf
systemctl show $U -p User        # User=root
ps -eo uid=,ppid=,args= | grep -F "$RUN/actions-runner/bin/Runner.Listener" | grep -v grep   # one line, uid 0, PPID not 1
```

Ownership in the tree can stay as it is; root reads everything. A `ktp-tier2`-owned marker
under a root runner is safe only because step 1 is installed. Leaving it does not give
`serverfiles/` back to `ftpuser`, though. If the previous owners matter, restore them from
the snapshot:

```bash
while read -r og m p; do chown -h "$og" "$p"; [ -L "$p" ] || chmod "$m" "$p"; done < "$B/owners.txt"
```

## Running § B

`scripts/tier2-runner-cutover.sh` is § B steps 1 to 7 and the box-side verify checks (a,
c, d, and what g will read) as one script, with an assertion after every step. Run it
from a checkout, over SSH, as root:

```bash
ssh root@<DATA_SERVER_IP> "bash -s" < scripts/tier2-runner-cutover.sh            # preflight, changes nothing
ssh root@<DATA_SERVER_IP> "bash -s -- --go" < scripts/tier2-runner-cutover.sh    # cutover
```

- The preflight refuses unless it runs as root on `neindataatl`, step 1 is installed, the
  unit is still `User=root`, the window rules above hold, and both no-job signals are clear.
- `--go` saves the snapshot in `$B` (unit, drop-in, `owners.txt` checked against a fresh
  `find`, `/etc/ktp` modes, heartbeat state) before it stops anything.
- It never runs the heartbeat. A hand run writes the alerter's state, so the script works
  out what the next cron run will read instead.
- On a failure from step 3 on it prints the rollback block. Steps 2 to 6 are safe to
  repeat; a stopped, still-root unit is treated as an interrupted run and resumed.
- The box takes about 1 to 3 minutes. Checks b and e and the step 5 proof (h) still run
  from the workstation, and the script prints them at the end. Allow the full 30 minutes.

On 2026-11-10 a copy of the preflight, with only the window refusal turned into a message,
ran read-only against the live box and passed every check.

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
