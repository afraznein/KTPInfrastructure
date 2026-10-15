### `scripts`: the weekly map-coefficient refit timer joins `CRITICAL_TIMERS` (2026-10-14)

`ktp-map-coefficients.timer` is about to be installed on the data server
(`dpl-e72e`), and it ships into the health script's covered set **in the same
change** — that is this estate's standing rule, learned on the install-freshness
timer (`dpl-af3a`) and applied again today to the corpus-integrity guard and the
hltv-api drift check.

Unlike those two it needs no bespoke work-done check. They are `cron.d` jobs and
therefore **structurally invisible** to `CRITICAL_TIMERS`, which is evaluated
against `systemctl list-timers`. This one is a real systemd timer, so the existing
leg can watch it directly.

**Why it is worth listing is the failure shape.** The refit only ever *proposes*:
it writes its output to `/var/lib/ktp-map-coefficients` and never to `main`. So a
stopped timer breaks nothing and logs nothing — the committed coefficient table
stays exactly where it is and keeps serving, which is indistinguishable from *"the
maps have not changed"*. There is no error to notice and no stale artifact to spot.

The 2026-10-14 dry run is the measure of how wrong that can get while looking
fine. After weeks unfitted it proposed **13 changes** — 9 maps absent from the
table entirely, and 4 moved, including `dod_harrington`, whose `alive` coefficient
had **halved** (1.0383 → 0.5100). None of that surfaced anywhere until the fit was
run by hand.

**Tests:** 6, mutation-checked — deleting the entry reddens 3 of them.

⚠️ The list is parsed out of the shipped array with comment lines dropped, not
substring-matched. That matters here: the array's comments deliberately name a unit
that is **not** listed (`ktp-monday-reminder.timer`, omitted because a reminder
that fails to arrive is noticed by the people expecting it). A plain `in TEXT` test
would therefore pass for a unit that had been removed from the list, and one of the
six cases pins exactly that distinction.
