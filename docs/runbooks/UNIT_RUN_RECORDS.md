# Runbook: where a scheduled run's findings are kept

**The default is a dated file per run under the unit's `StateDirectory=`, written
by `scripts/ktp-run-record.sh`.** The rest of this file is why, when the other two
shapes still apply, and the one unit-file line that is missing on every oneshot in
`scripts/systemd/`.

Companions: [`ALERT_COVERAGE.md`](ALERT_COVERAGE.md) answers *what is watched*,
[`ALERT_ROUTING.md`](ALERT_ROUTING.md) answers *where it lands and how loud*. This
file answers *what is still readable next week*.

## Why a convention rather than a mechanism

Six scheduled units on the data server report by printing and exiting non-zero:
`ktp-weekly-outliers`, `ktp-install-freshness`, `ktp-stats-export`,
`ktp-telemetry-export`, `ktp-render-banlist`, `ktp-hlstatsx-ingest-monitor`.
Their stdout *is* the report, and journald here holds about two days — so a weekly
unit that fails on a Tuesday cannot be read by the following Tuesday. No incident
is needed; that is the steady state.

`ktp-identity-reconcile` is the one that already paid for this twice. On 2026-09-08
it failed carrying a real divergence and `journalctl -u` returned `-- No entries --`
six days later; the findings came back out of `/var/log/syslog.2.gz` by luck. On
2026-09-29 it failed again, the box rebooted, and journald started over.

Two fixes landed, at different layers, and **both are still correct**:

- `fe5a030` (2026-09-14) made `ktp-systemd-alert` append every capture — up to 400
  journal lines — to `/var/log/ktp-systemd-alert.log` before the cooldown check and
  before the POST. That covers **every** unit carrying the `OnFailure=` drop-in, so
  a suppressed alert, a dead relay and a rotated journal all still leave the output
  on disk. Retention is `monthly, rotate 12`.
- `reconcile-identities-run.sh` in `keep-the-prac` writes each run's output to a
  dated file under the unit's `StateDirectory`.

The appended alert log is the **floor**: shared, automatic, and keyed to failures
somebody was alerted about. It is not a per-unit record and it cannot say a run
*happened*. That is the gap this convention fills.

## The three shapes, and which one applies

### 1. A dated file per run under `StateDirectory=` — the default

```ini
[Service]
Type=oneshot
StateDirectory=ktp-stats-export
TimeoutStartSec=15min
ExecStart=/usr/local/bin/ktp-run-record.sh /usr/local/bin/ktp-stats-export.py --hours 48
```

Use this unless one of the two cases below applies. Three reasons, in order of how
much they cost to learn the other way:

- **systemd guarantees the path.** It creates `/var/lib/<name>`, owns the mode, and
  makes it writable even under `ProtectSystem=strict` with no `ReadWritePaths=`.
  That is why the reconciler ended up here: it runs `ProtectSystem=strict` with
  `/opt/keep-the-prac` as its only extra write path, so `/var/log` is read-only to
  it and a log there needs a unit-file change installed by hand on the box.
  A unit that is unhardened today and hardened later does not have to move its
  records.
- **It survives a reboot**, unlike `/run`, and outlives both journald (~2 days here)
  and syslog rotation (~1 week).
- **"Which run" is answerable.** An append-only log cannot separate a run that died
  in its first second from one that finished.

### 2. A dated report in a watched log directory — only for cron, and only unsandboxed

`ktp-precache-audit` writes `/var/log/ktp-precache-audit-<date>.md` and
`ktp-data-server-health.sh` keys `precache_freshness()` on the newest matching
mtime against an 8-day ceiling. That is sound and it stays.

It applies when the job is **cron, not systemd** — cron has no `StateDirectory`,
and inventing a state directory for it buys nothing. ⛔ Do not reach for it from a
systemd unit: `/var/log` is one `ProtectSystem=` away from being read-only, and the
failure arrives on the run you most wanted recorded.

### 3. An appended log — a stream, never a verifier

Append logs are legitimate as a running narrative: `/var/log/ktp-banlist.log`,
`/var/log/ktp-systemd-alert.log`, `/var/log/ktp-offsite.log`.

⛔ **Never key a freshness check on one.** This estate has rejected that twice in
writing, from both directions:

- `ktp-data-server-health.sh` on the precache audit: the cron's own `.log` *"is
  appended to even by a run that died before auditing anything, so it would
  certify work that never happened."*
- the same script on the ban-list renderer: keyed on the unit's last exit,
  *"never on the file's mtime or the renderer's log"* — both go permanently quiet
  once the list stops changing, which is the healthy steady state, so either would
  read `stale` forever and get tuned out.

A "work happened" signal has to be written **only on a completed run**. The estate
already has that shape: `ktp-backup-watchdog.sh` ages `/var/lib/ktp-backup-lastrun`
and reads its absence as *"the backup has not completed successfully since the
watchdog was installed"* — a success stamp, not an activity log. (Its writer is
`/opt/ktp-backup.sh` on the box, not in this repo.) The wrapper's
`runs/last-ok.txt` is the same thing per unit.

## Opting in

Three lines in the unit, and nothing in the script being wrapped:

1. `StateDirectory=<name>` — the wrapper refuses to run without it, `exit 78`,
   rather than running and keeping nothing.
2. `TimeoutStartSec=<span>` — see the next section. This is not optional.
3. `ExecStart=/usr/local/bin/ktp-run-record.sh <the command it already ran>`.

Records land in `/var/lib/<name>/runs/`:

| path | written when |
|---|---|
| `<UTC>.txt` | every run, once it ends — header, the run's merged stdout+stderr, then a `finished:`/`rc:` footer |
| `last-ok.txt` | `KTP_RUN_RECORD_ONLY_FAILURES=1` only, on a clean run, in place of a dated file |
| `<UTC>.txt.part` | a run that never ended. See below |

Knobs, all optional: `KTP_RUN_RECORD_DIR` (overrides `STATE_DIRECTORY`, for a test
run — use a temp path, never the live one), `KTP_RUN_RECORD_KEEP_DAYS` (default 400,
so last season's records are readable during the next) and
`KTP_RUN_RECORD_ONLY_FAILURES=1`.

### Choosing the two from the cadence

**More often than hourly → `ONLY_FAILURES=1`. Hourly or less → a dated record per
run, with the horizon set so the directory stays in the hundreds of files.** The
number of files is the whole decision: a directory nobody can scan is a record
nobody reads, and a unit's successes are not what anyone goes looking for.

| unit | timer | setting | files kept |
|---|---|---|---|
| `ktp-weekly-outliers` | Mon 06:00 | dated, default 400d | ~57 |
| `ktp-install-freshness` | daily 06:20 ET | dated, default 400d | ~400 |
| `ktp-hlstatsx-ingest-monitor` | hourly | dated, `KEEP_DAYS=30` | ~720 |
| `ktp-telemetry-export` | hourly at `:40` | dated, `KEEP_DAYS=30` | ~720 |
| `ktp-stats-export` | `*:0/10` | `ONLY_FAILURES=1` | failures + `last-ok.txt` |
| `ktp-render-banlist` | `OnUnitActiveSec=60s` | `ONLY_FAILURES=1` | failures + `last-ok.txt` |

## How a wedge shows up — and the line every oneshot here is missing

🔴 **`TimeoutStartSec=` defaults to *disabled* for `Type=oneshot`.** From
`systemd.service(5)`: *"Defaults to `DefaultTimeoutStartSec=` from the manager
configuration file, except when `Type=oneshot` is used, in which case the timeout is
disabled by default."*

Measured 2026-10-07: **nine** `Type=oneshot` units in `scripts/systemd/` and
**zero** of them declare `TimeoutStartSec=`. So a wedged run of any of them hangs
indefinitely — it never fails, `OnFailure=` never fires, no embed is posted and
nothing is written anywhere. That is the `hltv-demo-renamer` shape (53 hours
`active`, two days of demos purged unrenamed) relocated into the reporting units,
and `Restart=`/`OnFailure=`/`systemctl is-active` are all blind to it by
construction. `ktp-identity-reconcile` is the only one of the seven that sets a
timeout, at 15 minutes.

With a timeout set, a wedge is readable three ways:

| what you see | what happened |
|---|---|
| a dated record whose footer carries `killed: SIGTERM` | `TimeoutStartSec=` expired and systemd cut the run short. `rc:` is the wrapped command's, usually `143` |
| an orphan `<UTC>.txt.part` with no `finished:` line | the run was SIGKILLed — `TimeoutStopSec` expired after the TERM, or the box went down. Nothing ran to promote it, and the file left behind is the evidence. ⛔ Do not clean these up; they are the only trace |
| `last-ok.txt` older than the unit's cadence | the unit has not completed cleanly since that stamp, whatever its current state says |

A promoted record **always** carries a `finished:` line: a footer that cannot be
written fails the promotion loudly instead of leaving a record that looks complete.

➡️ **Pick the timeout from the work, not from a sibling.** Long enough that a slow
but healthy run is not a page, short enough that a wedge is caught inside one
cadence. A weekly unit can afford 15 minutes; a 60-second timer cannot.

## Not covered, deliberately

- **A timer that stops firing.** No record shape can see this — nothing runs. That
  is what `CRITICAL_TIMERS` in `ktp-data-server-health.sh` is for, and every one of
  these units' timers is already in it.
- **Journal priority.** The wrapper merges stderr into stdout so a
  stdout-is-the-report unit keeps one ordered record. `journalctl -p err` was
  already not a check on these units; now it definitely is not. Read the record.
- **Buffering.** The record inherits the wrapped command's buffering. The wrapper
  exports `PYTHONUNBUFFERED=1` so a killed Python run's last lines are on disk
  rather than in a kernel buffer; a C or shell program that buffers its own output
  will still lose the tail when SIGKILLed.
- **Ageing `last-ok.txt` automatically.** The files are written; nothing reads them
  on a schedule yet. The leg that would — newest `runs/*` mtime per unit against
  that unit's cadence, plus any `.part` older than its timeout — belongs in
  `ktp-data-server-health.sh` as a producer, per `OBSERVABILITY_PLAN.md` § 2.1.
  Until it exists, these records answer *what happened* on demand and alert nobody
  by themselves. ⚠️ Writing a record is not coverage; say which it is.

## Install

```bash
# on the data server, from a checkout of this repo
sudo install -m 0755 scripts/ktp-run-record.sh /usr/local/bin/ktp-run-record.sh
sudo cp scripts/systemd/ktp-*.service /etc/systemd/system/
sudo systemctl daemon-reload
```

Verify without waiting for a timer, and **against a temp path**, because a bare run
writes the live record directory:

```bash
KTP_RUN_RECORD_DIR=$(mktemp -d) /usr/local/bin/ktp-run-record.sh /bin/sh -c 'echo probe; exit 1'
```

Then confirm the unit resolves its own directory — `systemctl show <unit> -p
StateDirectory --value` and `-p TimeoutStartUSec --value`, never a grep of the unit
file: two units in this estate carried a *comment* claiming `OnFailure=` while the
directive was absent, and both greps hit.
