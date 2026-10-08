### Lane B: a widened capture manifest now fails by name, at collect time (2026-10-07)

A capture contract has widened ahead of a reader in this repo three times, and both prior
*class* fixes missed the third because the duplication that mattered was not a list:

- **`move` (2026-09-29)** and **`aim_vis` (2026-10-05)** were event **types**. Both were
  carded, both were fixed with a changelog entry, and the second even removed a duplicated
  type list.
- The third was a manifest **FIELD**: `(sv_maxunlag "%.3f")`, added by `afraznein/KTPAMXX`#155
  (merged 2026-10-04). `_MANIFEST_RE` in `tests/e2e_stats/break_scenarios.py` is an **ordered
  positional grammar**, so an inserted field makes it match **zero** lines rather than ignore
  one. It matched 0 of the 46 manifest lines in run 37621405799.

Two things made that cost 14 days rather than a morning, and the guard addresses both.

**It did not name itself.** The symptom was `begin_series` aborting `current_manifest_missing`
after a 10 s wait, and then `statsme`, `diagnostic_match_stats_reconciled` and
`capture_context_isolation` failing — three scenarios that say nothing about manifests.
`ArtifactSet.collect()` now calls `assert_capture_manifest_grammar()` on the
`ktp_stats_capture.inc` it has just extracted, and refuses the bundle with a `BuildError`
naming the offending field before a match is ever started.

**A second reader agreed while reading less.** `tests/e2e_stats/log_invariants.py` matches the
manifest **prefix only** and takes its fields from `properties`, so it was unaffected and
stayed green. That is correct for its purpose and it is *not* corroboration; the asymmetry is
now stated at the regex and asserted in both directions, so the next person does not read its
green as a second opinion.

The new `tests/e2e_stats/manifest_contract.py` restates no part of the contract, which is what
the two earlier class fixes did. It extracts the producer's own format string, renders a line
from it, and asks a reader to match that line — so field names, field **order** and printf
conversions all come from the producer. The authority is the `.inc` at the amxx sha under test,
so there is no reference copy here that can go stale behind KTPAMXX. A field the producer adds
has no sample value and fails **closed**, with the field name and what to do in the message.

`tests/unit/test_capture_manifest_grammar_drift.py` is the leg that runs on **every** PR —
`config-tests.yml` already runs `tests/unit/`, while `tests/e2e_stats/` runs only inside a Lane B
job. It cannot see today's producer (different repo, no network) and does not pretend to: it
proves the machinery can **fail** (a fourth field, a reorder, a dropped field, a narrowed
conversion, a renamed marker), proves `collect()` still calls the check — the part both earlier
fixes lacked — and pins the asymmetry above. Its committed format string is an exercise corpus,
labelled as such; freshness lives in `collect()`.

⚠️ **Detection is still bounded by the nightly, which has no notifier.** Lane B `full` was red
for other reasons on 10-01 through 10-04, so a *new* red is not distinguishable from the standing
one by colour alone — the gain here is that the failure now arrives early and says what it is.
The N-consecutive-scheduled-failure notice that `lane-b-stats-e2e.yml` still owes is unchanged by
this and remains the thing that would make a red legible to a person.
