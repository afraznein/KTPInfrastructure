# Install freshness — reconciling, then watching

Two things, in this order, because the second is useless before the first:

1. `ktp-install --record-only` — a way to say "this file is already the blob at
   this commit" without copying anything, so a correct-but-unrecorded file can
   be reconciled at all.
2. `ktp-install-freshness.sh` + its timer — the daily check, which posts only
   when the answer changes.

⛔ **Nothing here is installed or enabled.** The script, the unit and the timer
are files in this repo. The install steps are written down below; running them
is a separate, deliberate act.

## Why the order is not negotiable

`ktp-install` refuses a no-op: *"already has md5 …; nothing to install"*. That
guard is right — an install is a copy, and copying bytes that are already there
is a lie in the manifest. But it left one state unreachable. A file that is
correct and was never recorded could not be recorded, because the only way in
was through a copy that would not happen.

Measured on the data server, 2026-09-29, read-only: `ktp-install --report` over
120 recorded paths returns 10 `DRIFT`, 108 `OK`, 2 `TEMPLATED`, exit 1. Schedule
a daily alert over that and it names ten paths every morning that nobody has any
mechanism to clear. That is how a detector gets muted, and this estate already
has one that alerted for weeks with nobody reading it.

## 1. `--record-only`

```bash
ktp-install --record-only --repo /opt/ktp-infra \
            --commit <sha> --src scripts/foo.sh --dest /usr/local/bin/foo.sh
```

It hashes what is on disk, resolves the blob at that commit, and appends the row
**only if they are equal**. It writes no file, keeps no backup and touches no
mode. Everything it will not do:

| refuses | why |
|---|---|
| bytes ≠ the blob at `--commit` | the whole point; a mode that trusts its caller launders drift into a clean report |
| no `--repo` | without the blob here the row is the caller's word, not a check |
| `--template` | a filled template cannot equal any blob, so there is nothing to verify against |
| `--file`, `--blob-md5`, `--mode` | each one would name something other than the file being recorded |
| the file is missing | there is nothing installed to record |
| `--expect-md5` given and not matching | the same compare-and-swap discipline an install has |
| an identical last row already exists | a duplicate row records nothing |
| a manifest that does not parse | fail closed, as everywhere else in this tool |

A recorded row carries `previous_md5 == md5`. The install path refuses a no-op,
so it can never write one — that equality is how the two are told apart later,
and it needs no new column.

**What it does not buy.** Recording states *which blob these bytes are*, not
that they are the newest. Record an old commit and `--against-ref` still says
`STALE`; the row is honest and the file is still behind.

### Reconciling the ten

For each `DRIFT` path, find the commit whose blob equals the installed bytes and
record that, or install the current one. There is no bulk mode on purpose: a
`DRIFT` row means somebody edited a live file, and each one is a question about
what they were doing, not a batch.

## 2. The daily check

`scripts/ktp-install-freshness.sh`, `scripts/systemd/ktp-install-freshness.{service,timer}`,
`scripts/systemd/dropins/ktp-install-freshness.service.d/00-ktp-onfailure-alert.conf`,
`scripts/ktp-install-freshness.conf.example`.

It runs `ktp-install --report --repo <mirror> --against-ref origin/main`, writes
the result, and compares the **set** of non-fresh paths to the previous run's.

**It keys on work done, not on the unit being up.** A hung unit reads as
`active`; `hltv-demo-renamer` sat "healthy" for 53h and every demo in the window
was lost. So the durable artifact is `/var/lib/ktp-install-freshness/last-run.json`,
rewritten on every completed run, and the full report beside it. If a run cannot
produce that file it produced nothing, whatever systemd says.

**It alerts on a transition, never on a count.** Ten paths stale today will be
ten tomorrow; a daily "10 paths are stale" is a number people learn to skim. So:

- a path **entered** the non-fresh set → 🟠 `warn`, ops-daily lane
- the set **emptied or shrank** → 🟢 `recovery`, same lane, because an all-clear
  belongs beside the thing it clears
- the set is **unchanged** → silent, at any size
- the **first run** records a baseline and says nothing; announcing every path
  once is the standing count this design exists to avoid
- the check **did not run** for longer than `MAX_GAP_SEC` → posted on the next
  run that completes, because a gap is always news

**A dirty estate exits 0.** `ktp-install --report` exits 1 whenever anything is
stale. Letting that fail the unit would fire the `OnFailure` drop-in every single
run until somebody masked it. Non-zero from this script means the check *could
not run* — no mirror, no manifest, an unresolvable ref — and that is the only
thing the drop-in should ever see.

**A failed relay post does not save the transition**, so the next run
re-announces it rather than swallowing a change nobody saw.

### Install steps (not performed)

```bash
# 1. the tool itself must be current first -- see "Is this live?" below
ktp-install --repo /opt/ktp-infra --commit <sha> --src scripts/ktp-install \
            --dest /usr/local/bin/ktp-install --expect-md5 <md5 there now>

# 2. the check, and the mirror it reads
ktp-install --repo /opt/ktp-infra --commit <sha> --src scripts/ktp-install-freshness.sh \
            --dest /usr/local/bin/ktp-install-freshness.sh --expect-md5 -
install -d -m 750 /var/lib/ktp-install-freshness
git clone --bare https://github.com/afraznein/KTPInfrastructure \
    /var/lib/ktp-install-freshness/mirror.git
git -C /var/lib/ktp-install-freshness/mirror.git config \
    remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
git -C /var/lib/ktp-install-freshness/mirror.git fetch --prune origin

# 3. conf, units, drop-in
cp scripts/ktp-install-freshness.conf.example /etc/ktp/install-freshness.conf  # then edit
chmod 600 /etc/ktp/install-freshness.conf
# ... units and drop-in into /etc/systemd/system, then daemon-reload

# 4. dry run BEFORE enabling the timer, so the first scheduled run is not the first run
/usr/local/bin/ktp-install-freshness.sh
systemctl show -p OnFailure ktp-install-freshness.service   # the check, not a grep
```

⚠️ **`/opt/ktp-infra` is not the mirror.** The check fetches, and that tree must
not be auto-pulled; the script refuses it outright. The mirror is a bare clone it
owns, and it is a `--bare` clone configured to fetch into `refs/remotes/origin/*`
— a `--mirror` clone puts branches in `refs/heads`, where `origin/main` does not
resolve and every run would exit 2.

⚠️ **Enable the timer and add it to `CRITICAL_TIMERS` in the same change.**
`ktp-data-server-health.sh` is what notices a *stopped* timer; the gap leg inside
this script only fires on a run that happens. Adding the entry before the timer
exists pages for a missing unit; adding the timer without the entry leaves the
watcher unwatched. Neither half is safe alone.

⚠️ **This repo's Tier 2 CI job runs on the production data server.** A change to
this repo is a change on that box the moment a job checks it out. The unit tests
below are a different matter — `config-tests.yml` runs `tests/unit/` on
`ubuntu-latest`, so they execute nowhere near production.

⛔ **Not a required CI check.** Ten paths are non-fresh today; gating merges on
the report would block every PR until they are reconciled. That is sequenced
separately and deliberately.

## Is this live?

Measured on the data server 2026-09-29, read-only, with controls:

- `/usr/local/bin/ktp-install` is `3a8b80ce94f8ff1f07c8808b10b575ce`, recorded
  from `8be1d8f223074c193844b6e50de5ebfc8c3cffcf` on 2026-09-11. `grep -c` for
  `against-ref` in it returns **0** — the installed copy predates the freshness
  work entirely, never mind `--record-only`.
- Nothing schedules `--report`: `grep -rl ktp-install` over `/etc/cron.d`,
  `/etc/cron.{daily,hourly}`, `/var/spool/cron` and `/etc/systemd/system` returns
  nothing, against a positive control (`ktp-data-server-health` in `/etc/cron.d`)
  that returns two hits on the same sweep.

So both jobs exist **in git only** until somebody runs step 1 above. Installing
`ktp-install` is what makes `--record-only` reachable at all.
