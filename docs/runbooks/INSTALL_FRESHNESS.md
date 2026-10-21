# Install freshness — reconciling, then watching

Two things, in this order, because the second is useless before the first:

1. `ktp-install --record-only` — a way to say "this file is already the blob at
   this commit" without copying anything, so a correct-but-unrecorded file can
   be reconciled at all.
2. `ktp-install-freshness.sh` + its timer — the daily check, which posts only
   when the answer changes.

✅ **Both are now LIVE on the data server** — `ktp-install` carries `--record-only`,
and `ktp-install-freshness.sh` is installed with its timer enabled and running daily.
🔻 **This page said *"Nothing here is installed or enabled"* for weeks after that
stopped being true**, which is the direction that gets a running check broken by
someone who believed the doc: an edit to either file is now a change to something
live. ⚠️ **So do not read the state out of this page.** Derive it —
`systemctl is-enabled ktp-install-freshness.timer`, and the md5 of
`/usr/local/bin/ktp-install-freshness.sh` against the blob — and note that the
install steps below remain a separate, deliberate act for anything not yet live.

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

It fetches `origin/main` into `/opt/ktp-infra` (fetch only — see below), runs
`ktp-install --report --repo /opt/ktp-infra --against-ref origin/main`, writes
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
not run* — no checkout, a failed fetch, no manifest, an unresolvable ref — and
that is the only thing the drop-in should ever see.

**A failed relay post does not save the transition**, so the next run
re-announces it rather than swallowing a change nobody saw.

**Why the fetch is not optional, and where the same blindness lives twice.**
`--against-ref origin/main` resolves a *remote-tracking ref inside the checkout*,
not GitHub. `/opt/ktp-infra` is detached and never pulled, so without a refresh
that ref is only as new as the last fetch somebody happened to run, and a
freshness check whose reference is behind reports **fresh** — the failure runs in
the reassuring direction and nothing contradicts it. Measured 2026-10-06: that
checkout's HEAD was `dc7a1e7` (11:10) while its own `origin/main` ref was
`d8a2d67` (15:06), so it was behind a ref that was itself stale. The script now
refuses rather than reporting (`die "fetch failed; a freshness check that could
not refresh its reference must not report freshness"`).

⚠️ **The `hltv-api` drift checker compares against that identical never-pulled
tree.** Same mechanism, second instance, and the two must not be answered
separately: one of them refreshing its reference while the other does not leaves
a second checker quietly reporting *fresh* forever.

✅ **And the tool no longer depends on this script remembering.** `ktp-install
--report --against-ref` now settles the baseline itself: a `refs/remotes/` ref is
confirmed to be its remote's tip with `git ls-remote` (no fetch, nothing written)
and the run exits `2` naming **both** shas when it is not. A ref that tracks
nothing is run and labelled `pinned`. 🔑 **That matters because the compensation
lived entirely in the caller, and the common caller is a person typing the
command** — every figure quoted from a hand-run `--report --against-ref
origin/main` was measured against whatever that checkout happened to hold, which
on 2026-10-12 was 214 commits behind. The first line of the output is now the
baseline and how it was settled.

⛔ **This script deliberately passes the SHA it fetched, not `origin/main`.** The
remote check is right for a hand run and wrong here: the fetch above has already
settled the ref, and re-resolving it would let a merge landing in the second
between the two turn a healthy run red. The run then asserts that the baseline
the report states **is** the sha it was given, and records `baseline_stated` in
`$RESULT_FILE` so a reader can tell which kind of run produced the numbers.
⚠️ **An absent baseline line is recorded, not fatal** — an installed `ktp-install`
predating the check cannot state one, and this script's own fetch is what makes
its comparison sound, so dying there would take out a check that is working.

### Generating the installs: `ktp-install --plan`

```bash
ktp-install --plan --repo /opt/ktp-infra --against-ref origin/main
```

Prints the `ktp-install` commands for every `STALE` row and writes nothing. Each
is pinned to the md5 on the box (`--expect-md5`) and to the ref's bytes
(`--blob-md5`), so a plan that has gone out of date refuses rather than clobbers,
and one staged from the wrong tree refuses too. Exit `1` means a plan was
emitted, which is the productive outcome; ⛔ never pipe it. Full semantics, and
the two things it deliberately does not do: `docs/DEPLOY_MANIFEST.md`.

⚠️ **The one dependency order it cannot derive and must not guess:**
`ktp-verify-deploy` imports `ktp_script_freshness` at module level, so **the guard
installs first**. The other way round, the verifier fails at import — a verifier
that would have given a wrong answer becomes one that gives none.

### Install steps (not performed)

```bash
# ⛔ --repo /opt/ktp-infra is REFUSED by ktp-install: that checkout is never a source of
# bytes. Stage the blob and pass --file, which needs no checkout on the box. Take the sha and
# the blob md5 off-box: git rev-parse origin/main, and git show <sha>:<path> | md5sum.

# 1. the tool itself must be current first -- see "Is this live?" below
ktp-install --file /root/ktp-install.src --source-repo KTPInfrastructure --commit <40-hex sha> \
            --src scripts/ktp-install --dest /usr/local/bin/ktp-install \
            --expect-md5 <md5 there now> --blob-md5 <md5 of the blob>

# 2. the check
ktp-install --file /root/freshness.src --source-repo KTPInfrastructure --commit <40-hex sha> \
            --src scripts/ktp-install-freshness.sh \
            --dest /usr/local/bin/ktp-install-freshness.sh \
            --expect-md5 - --blob-md5 <md5 of the blob> --mode 755
# The unit now declares StateDirectory= + StateDirectoryMode=0750, so systemd
# creates /var/lib/ktp-install-freshness; this line only matters if you run the
# script by hand before the unit has ever started.
install -d -m 750 /var/lib/ktp-install-freshness

# 2b. the run-record wrapper the unit's ExecStart names
install -m 0755 scripts/ktp-run-record.sh /usr/local/bin/ktp-run-record.sh

# 3. conf, units, drop-in
cp scripts/ktp-install-freshness.conf.example /etc/ktp/install-freshness.conf  # then edit
chmod 600 /etc/ktp/install-freshness.conf
# ... units and drop-in into /etc/systemd/system, then daemon-reload

# 4. dry run BEFORE enabling the timer, so the first scheduled run is not the first run
/usr/local/bin/ktp-install-freshness.sh
systemctl show -p OnFailure ktp-install-freshness.service      # the check, not a grep
systemctl show -p StateDirectory -p TimeoutStartUSec ktp-install-freshness.service
```

Each run's output is kept under `/var/lib/ktp-install-freshness/runs/` —
[`UNIT_RUN_RECORDS.md`](UNIT_RUN_RECORDS.md). This unit earns it more than most:
its only failure mode is *could not compare*, so the output explaining why **is**
the whole content of the failure, and before the wrapper it existed only in a
journal that holds about two days against a daily unit.

⚠️ **The check FETCHES `/opt/ktp-infra` and never pulls it.** The standing rule is
that the deploy checkout is not auto-pulled, and that still holds: the fetch uses
an explicit refspec, `+refs/heads/main:refs/remotes/origin/main`, so the only
thing it can write is that one remote-tracking ref. HEAD, the index, the working
tree and every local branch stay where a person put them — even if the checkout's
configured refspec were changed to write `refs/heads/*`. The script records HEAD
before the fetch and exits 1 if it moved. What changes is that `origin/main` in
that checkout is now current, which is what the comparison needs, and it also
means a newly merged commit is present there to compare against without anyone
moving the tree. ⛔ **It does NOT make that tree an install source** — `ktp-install`
refuses it, because the fetch moves only `origin/main` while HEAD, and therefore
every byte in the working tree, stays where it was. `AGAINST_REF` must be a
`<remote>/<branch>` ref; a local ref is refused, because a fetch never refreshes
it and it would read as fresh forever.

⚠️ **A fetch can lose a race.** If someone runs git in `/opt/ktp-infra` at 06:20
the fetch may fail on a lock; that run exits 1, the `OnFailure` drop-in fires,
and the next run is normal.

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
