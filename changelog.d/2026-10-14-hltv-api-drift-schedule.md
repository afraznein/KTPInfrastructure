### `scripts`: the hltv-api drift check becomes a standing check (2026-10-14)

`check-hltv-api-drift.py` has been a **tool, not a check**. Measured on the data server:
a sweep of `cron.d`, `cron.daily`, `cron.hourly`, `cron.weekly`, `/var/spool/cron` and
`/etc/systemd/system` for it returns **0 files**, against a positive control of 16 hits for
`ktp-data-server-health`. So nothing ran it, and `dpl-53ba` records the board as reading
"drift coverage now exists" when it did not.

This adds the schedule, a log, a state file, and the alerting the checker deliberately does
not do.

- **The checker is not modified, and must not be.** Its bytes are pinned to a review, and a
  wrapper that edits its subject is how a reviewed artifact stops being the thing that was
  reviewed. What "drift" means stays in one script; the wrapper only turns exit codes into
  something someone sees.
- **Exit mapping.** 0 posts nothing — a drift report repeated every morning trains everyone
  to mute the channel. 1 posts once. **2 always posts**, because "could not look" reading as
  "nothing there" is the defect this row exists to kill. 3 pages, because a redaction
  failure is a secrets-safety event and not a drift report. The checker's exit code passes
  through unchanged, so the log, the state file and the wrapper all say what the tool said.

⛔ **No alert ever carries the checker's output.** On drift that output is a diff of the live
`hltv-api.py`, which holds `AUTH_KEY`. The checker redacts by shape before printing and
aborts rather than emit an unredacted secret — but **exit 3 is that abort**, so the one case
where forwarding is most tempting is exactly the case where it is least safe. The embed
carries the verdict and points at the log; the log on the box carries the detail, created
`0640 root root`.

⛔ **Deploy order is load-bearing: `#708` first, then this.** Before `#708` the installed
checker's only reference default was "beside this script", never true at `/usr/local/bin`,
so a bare run exits 2 on `cannot read`. Fielded first, this pages every single morning about
a fielding mistake — the exact noise `dpl-53ba` warns about. The preflight refuses rather
than reporting it as drift, and the exit-2 alert names both causes, because one of them is
ours.

⛔ **And it ships with its health-script coverage in the same change.** A `cron.d` job is
structurally invisible to `CRITICAL_TIMERS`, which is checked against `systemctl
list-timers`. Without the `ktp-data-server-health.sh` leg watching this log's mtime, a
wrapper that stops running is indistinguishable from a clean morning — because a clean
morning is silent by design. That is `dpl-af3a`'s rule, and the corpus-integrity guard was
fielded the same way earlier today. The leg keys on the **log**, not the state file and not
the last exit code: a non-zero exit already alerts for itself, and the wrapper writes its
state file *before* the verdict branch, so a state file is not evidence the check completed.

**06:50 ET daily** — after the 06:15 review-integrity guard, the install-freshness window
(06:20 + jitter) and the 06:35 corpus-integrity guard, so no two morning readers overlap;
clear of the 03:00 fleet restart, 04:30 rollup, 04:40 AC retention sweep and the 05:00
digests. Deliberately *after* the freshness fetch, because that fetch is what moves
`/opt/ktp-infra`'s `origin/main` ref and the checker's provenance line reports the
reference's distance from it — running later prints the freshest number available.

Installed as `/usr/local/bin/ktp-hltv-api-drift-guard` — **without the extension**, as
`ktp-corpus-integrity-guard` and `ktp-review-integrity-guard` are. ⛔ A cron entry naming
the `.sh` is `203/EXEC`, which is how `ktp-weekly-outliers` sat dead for a week, so a test
asserts the cron path carries no extension.

**Tests:** 33 pass, and two were mutation-checked.

⚠️ **One of them was decoration until the mutation proved it.** The leak test captured the
posted text with `(.*)`, which does not match newlines, so it inspected only the *first
line* of an alert. A mutant appending the checker's whole output to the embed **passed**,
because the secret landed on line two. The capture now spans the whole log entry, and the
mutant fails. The health leg was mutation-checked too: pointed at the corpus log instead of
its own, three cases redden.
