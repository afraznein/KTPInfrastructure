# Migrations-applied check: the daily run on the data server

`KTPAntiCheat`'s `scripts/check-migrations-applied.py` compares every file in that
repo's `sql/migrations/` against the live `hlstatsx` schema, and every row of
`docs/MIGRATIONS_APPLIED.md` against what the schema actually holds. It exits 0 when
nothing contradicts the schema, 1 on a finding (a migration not applied, or a ledger
row saying the opposite of the schema), and 2 when it could not check.

It runs in no GitHub workflow and cannot. Its snapshot step reaches the keys-only data
server, and the only self-hosted runner with that reach is registered to this repo, not
to `KTPAntiCheat`. A merged checker that never executes is the same kind of defect as
the stale ledger row it was built to catch. So it runs here, on a timer beside the
other morning checks.

**Status: written, not installed.** Installing it is an operator act, carried by a
`dpl-` row in `NEIN-DEPLOY.md`. Derive the live state with
`systemctl show ktp-migrations-applied-check.timer -p UnitFileState -p ActiveState`,
never from this page.

## What runs

| file | role |
|---|---|
| `scripts/systemd/ktp-migrations-applied-check.timer` | daily 06:40 ET, `Persistent=true` |
| `scripts/systemd/ktp-migrations-applied-check.service` | oneshot, wrapped by `ktp-run-record.sh`, `StateDirectory=ktp-migrations-applied-check` |
| `scripts/systemd/dropins/ktp-migrations-applied-check.service.d/` | `OnFailure=ktp-systemd-alert@%n.service` |
| `scripts/ktp-migrations-applied-check.sh` | fetches, extracts, snapshots, runs the checker, stamps |

Each run does the following:

1. `git fetch` in a `KTPAntiCheat` clone, at `/var/lib/ktp-migrations-applied-check/KTPAntiCheat` by default. A failed fetch is exit 2. It is never a run against whatever was fetched last, because a stale ledger silently skips every migration newer than it.
2. `git archive` of `origin/main`, limited to the three paths the checker reads, into a temp directory. The clone's working tree is never read.
3. Reads `SNAPSHOT_SQL` out of that checker and pipes it to the local `mysql` socket. That keeps one copy of the query, and skips the checker's own SSH path, since this box is the data server.
4. Runs the checker with `--snapshot`. Its exit code is the unit's exit code.
5. On exit 0 or 1 only, writes `last-checked`, holding the time, the `KTPAntiCheat` commit it read, and the exit code.

## How it alerts, and on what

- **A finding (exit 1) or a could-not-check (exit 2)** fails the unit. The drop-in posts
  the embed with the run's output, and `runs/<UTC>.txt` keeps the full record past
  journald's two days. A migration that is staged but not yet applied therefore alerts
  every morning until it is applied or its ledger row says so.
- **A run that never happened** is the case the unit cannot report. The health sweep
  ages `last-checked` instead (`ktp-data-server-health.sh`, leg
  `ktp-migrations-applied-check`). An absent stamp is
  `ktp-migrations-check-stamp=absent`, and one older than two days is
  `ktp-migrations-check=stale`. The stamp is written only when the checker reached a
  verdict, so a run that died before checking leaves the stamp to age too.
- The leg only runs once the timer file is installed, because the units ship uninstalled. The
  timer is deliberately **not** in `CRITICAL_TIMERS`, which pages on a timer that is
  not `active` and `enabled`. An uninstalled timer is neither, so that leg would page
  every hour until install.

## Install (operator, `dpl-` row; not performed)

```bash
# 1. A read-only clone of the PRIVATE KTPAntiCheat repo, with whatever read credential
#    this box already uses for private repos or a dedicated read-only deploy key.
#    The fetch runs as root under ProtectHome=read-only, so root's ssh config is read
#    and never written.
install -d -m 0750 /var/lib/ktp-migrations-applied-check
git clone <KTPAntiCheat remote> /var/lib/ktp-migrations-applied-check/KTPAntiCheat

# 2. The runner and the wrapper the unit's ExecStart names.
install -m 0755 scripts/ktp-migrations-applied-check.sh /usr/local/bin/
install -m 0755 scripts/ktp-run-record.sh /usr/local/bin/   # if not already present

# 3. Run it BY HAND first. A scheduled job that has never run by hand is untested.
STATE_DIRECTORY=/var/lib/ktp-migrations-applied-check \
    /usr/local/bin/ktp-migrations-applied-check.sh; echo "exit=$?"
cat /var/lib/ktp-migrations-applied-check/last-checked

# 4. Units and drop-in, then enable.
cp scripts/systemd/ktp-migrations-applied-check.{service,timer} /etc/systemd/system/
cp -r scripts/systemd/dropins/ktp-migrations-applied-check.service.d /etc/systemd/system/
systemctl daemon-reload
systemctl show ktp-migrations-applied-check.service -p OnFailure   # must name ktp-systemd-alert@
systemctl enable --now ktp-migrations-applied-check.timer

# 5. The health-script leg reaches the box only when ktp-data-server-health.sh is
#    redeployed. Until then a stopped timer is unwatched.
```

Optional `/etc/ktp/migrations-applied-check.env` overrides: `KTP_AC_CHECKOUT`,
`KTP_AC_REF` (default `origin/main`), `KTP_AC_DB` (default `hlstatsx`).

**It is done when the timer has fired on its own schedule at least once and its output
reached somewhere a person reads.** Check for a `runs/` record and a fresh
`last-checked` the morning after enabling. A unit file that exists does not count.
