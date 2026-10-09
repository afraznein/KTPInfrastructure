### `ops`: a scheduled run keeps its findings, and a wedged one is now an exit (2026-10-07)

journald on the data server holds about two days. Six oneshot units report by printing and
exiting non-zero — `ktp-weekly-outliers`, `ktp-install-freshness`, `ktp-stats-export`,
`ktp-telemetry-export`, `ktp-render-banlist`, `ktp-hlstatsx-ingest-monitor` — so a weekly
unit that failed on a Tuesday could not be read by the following Tuesday. `fe5a030` already
fixed the alert path (`/var/log/ktp-systemd-alert.log`, `monthly, rotate 12`, written before
the cooldown and before the POST); what had no answer was a per-unit record, and whether a
run happened at all.

- **The convention is written down, because there were three.** An appended log, a dated
  report in a watched log directory, and a state directory per run, with nothing saying
  which applied when. `docs/runbooks/UNIT_RUN_RECORDS.md` picks **a dated file per run under
  the unit's `StateDirectory=`** and says where the other two still belong: a watched log
  directory for cron, which has no `StateDirectory`; an appended log as a stream and never as
  a verifier. The estate had already rejected the third as a verifier twice in its own
  comments — `ktp-data-server-health.sh` on the precache audit (*"appended to even by a run
  that died before auditing anything, so it would certify work that never happened"*) and on
  the ban-list renderer (keyed on the unit's last exit, *"never on the file's mtime or the
  renderer's log"*). `OBSERVABILITY_PLAN.md` carries it as a standing rule beside
  *no new alerting implementations*.
- **`scripts/ktp-run-record.sh`** is the shared implementation: a unit opts in with three
  lines and its script is untouched. It writes `runs/<UTC>.txt` — header, the run's merged
  output, then a `finished:`/`rc:` footer — promotes it atomically, relays both streams on so
  the Discord embed's journal tail is unchanged, and passes the exit code through, which
  matters because every one of these units delivers its findings *by* failing. Refuses with
  `exit 78` if no `StateDirectory=` resolves, rather than running and keeping nothing.
  `KTP_RUN_RECORD_ONLY_FAILURES=1` keeps a dated record only for failures and stamps
  `runs/last-ok.txt` otherwise, for the per-minute and per-ten-minute units.
- 🔴 **`TimeoutStartSec=` defaults to *disabled* for `Type=oneshot`** (`systemd.service(5)`),
  and none of the nine oneshots in `scripts/systemd/` set it. A wedged run therefore never
  exited, so `OnFailure=` never fired and nothing was written anywhere — the
  `hltv-demo-renamer` shape (53 hours `active`, two days of demos purged) relocated into the
  reporting units. All six now set one, sized from the timer. A wedge is readable three ways:
  a record whose footer says `killed: SIGTERM`, an orphan `.part` with no `finished:` line
  (SIGKILL or a reboot — do not clean these up), or `last-ok.txt` older than the cadence.
- **`ktp-weekly-outliers` stops re-dating a stale report.** Its `ExecStart` copied
  `latest.md` to `week-<date>.md` unconditionally, so a run that exited 2 (no official
  halves) or crashed re-published last week's report under this week's date.
  `weekly_outliers.py` writes `--out` before deciding its exit code, so 0 and 1 are exactly
  the codes that mean this run wrote the report — and 1 is the interesting week. The copy is
  now guarded on those two. Its `ExecStartPre=/bin/mkdir -p` is replaced by `StateDirectory=`.
- **`tests/unit/test_ktp_run_record.py`**: 18 cases, including a mutation test that strips
  the footer writer and requires the failure assertion to go red (a retention mechanism never
  shown to capture a failure is not one), SIGTERM and SIGKILL driven through bash rather than
  `terminate()` — on Windows that is `TerminateProcess`, no signal is delivered and the trap
  under test never runs — and a per-unit guard that every unit naming the wrapper declares
  both `StateDirectory=` and `TimeoutStartSec=`, with a positive control so the parametrised
  assertions cannot pass on an empty list.
- ⚠️ **Not installed.** `scripts/` has no deploy workflow, so merging does not field any of
  this; it needs one `install -m 0755` and a `daemon-reload` on the data server. And writing
  a record is not coverage — nothing ages these files yet. The leg that would (newest
  `runs/*` per unit against that unit's cadence, plus any `.part` older than its timeout)
  belongs in `ktp-data-server-health.sh` as a producer, per `OBSERVABILITY_PLAN.md` § 2.1.
- 🔻 **`scripts/systemd/dropins/README.md` called `ktp-render-banlist` "the last unwired unit
  on the box".** Its drop-in landed in `9a29f71` on 2026-08-16 — thirteen days before that
  file was last edited, so the claim survived an edit to the file it was wrong in. Corrected
  in place.
