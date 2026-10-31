### `docs`+`tests`: the ALERT_COVERAGE timer-table rule gets a test, and three stale sentences go (2026-10-30)

That runbook's rule — adding a timer means adding a row in the same change — was a paragraph,
and it was broken twice inside a fortnight. Four live timers sat unlisted until 2026-10-12, and
then two more joined `CRITICAL_TIMERS` with a reason written into the array and no row in the
table, each in a change that cited the runbook. Measured from the repo, nothing production:
the array holds fourteen entries and the table described twelve of them.

- **`ktp-install-freshness.timer` and `ktp-map-coefficients.timer` get rows.**
  `ktp-map-coefficients.service` has **no `OnFailure=`** — nothing in the unit and no drop-in
  under `scripts/systemd/dropins/`, against `ktp-stats-export.service.d/` as a control that has
  one — so a failing run reaches only the hourly sweep's generic `failed-unit:` leg, which
  covers it purely because a weekly oneshot sits `failed` long enough to be sampled.
- 🔴 **The freshness row carries an unresolved contradiction rather than hiding it.** That
  timer's own first line reads `⛔ NOT INSTALLED OR ENABLED — proposal`, and the
  `CRITICAL_TIMERS` leg flags anything not `active` **and** `enabled` — so an entry for a unit
  nobody installed is an hourly page that cannot clear by itself. The entry was added *so the
  units could be installed*, which met the one-change rule in the order that leaves this gap.
  **Settling it needs one read on the box** (`systemctl cat ktp-install-freshness.timer`, then
  the health state file) and is named in the row, not guessed at here.
- **`tests/unit/test_alert_coverage_timer_table.py` holds the rule.** It parses the array out
  of the shipped script (dropping its comments, which name units that are deliberately
  unlisted) and the first column out of the table, and asserts containment **one way only**:
  every entry has a row, and not the reverse — a row marked `**no**` for an uncovered timer is
  the table doing its job, and asserting the reverse would delete exactly those rows.
  Mutation-checked: removing a row reddens it, retitling the header reddens it, a comment read
  as an entry reddens it, and a deliberately dead anchor reports *could not apply*. **Deleting
  an array entry leaves it green on purpose** — that direction belongs to the per-timer
  membership tests, and the test says so.
- **`config-tests.yml`'s path filter now carries `docs/runbooks/ALERT_COVERAGE.md`.** The guard
  reads a doc and that job's filter was `scripts/`-shaped, so without this a PR deleting a row
  would skip the only job that runs it.
- 🔻 **Hole 5 corrected.** *"`ktp-restart-drift.py` runs on no schedule"* is false:
  `fleet-audit.yml` runs it every Monday as the `restart_drift` step, and `fleet-audit-gate.sh`
  reads it on two legs — a change in the `DRIFT:`/`UNREACHABLE` set, and the check failing to
  complete, keyed on the absence of a `^hosts reached:` line, because a broken check and a
  clean fleet otherwise produce the same nothing. It is not expected on the box; it runs from
  the CI checkout, which is the point of moving the audit into a workflow. The entry no longer
  claims anything about whether a divergence is currently reported.
- 🔻 **`tests/integration/_stage_manifest.py` stops asserting a claim its sibling corrected.**
  It said the version *"cannot be read out of the compiled `.amxx`"*; `stage-runner.py` has
  corrected that since 2026-08-10 and `scripts/amxx_version.py` does it. The manifest is
  provenance, not a workaround. The docstring now also records why `staged_md5()` has no
  caller: a manifest-vs-disk assertion would be permanently red for most of what the manifest
  holds — the workflow rebuilds the plugins it gates on every run, and `sync-runner-stack.py`
  mirrors the stack files from the fleet — so the decision to make, before wiring it into a
  test, is which artifacts are left.
- 🔻 **`stage-runner.py`'s *"three lists, one fact"* comment corrected.** It is two identical
  lists and one deliberately narrower one: `stage-wave.py`'s `RUNNER_TESTMODE_PLUGINS` omits
  `KTPHudObserver.amxx`, which is externally maintained and never staged or waved from here,
  with the reason stated one line above the set. The comment cost a reader a measurement.
