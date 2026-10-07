### Fixed
- Lane B's `full` lane has been red on every scheduled run since 2026-10-05, and all three failures
  were one cause. `BreakDriver._current_diagnostic_manifest` parses `KTP_CAPTURE_MANIFEST` with an
  exact ordered grammar, and schema 26 inserted `(sv_maxunlag "%.3f")` between the map-revision pair
  and `sequence` (ruling ③ of the schema-26 design). `_MANIFEST_RE` was last widened for schema 23
  and never for 26, so it matched **zero** of the 46 manifest lines in a real nightly log.
  `begin_series` could not bind, aborted `current_manifest_missing` after its 10 s wait, and every
  diagnostic scenario was skipped — so the isolated diagnostic match produced no events and
  `statsme`, `diagnostic_match_stats_reconciled` and `capture_context_isolation` all failed
  downstream of it. ⚠️ **This is the third time this lane has gone down because a capture contract
  widened in KTPAMXX and a list in the harness did not follow** (`move` 2026-09-29, `aim_vis`
  2026-10-05, both event types). The new shape is a manifest FIELD, and a positional regex is what
  makes an inserted field fatal rather than ignored: the other two manifest readers in this repo
  (`log_invariants.py`, which matches the prefix only) were unaffected, so nothing else flagged it.
  The field is accepted as an optional ordered group, as the schema-23 pair already is, because the
  lane also runs older `amxx_ref`s; it is signed because `stats_logging` emits `-1.000` when the
  cvar pointer is null.
- A second defect on the same path, which only the first fix exposes: `ksc_manifest_repeat` re-logs
  the identical manifest line — same bytes, same sequence, same epoch — on a tick while the half
  stays confirmed, and the resolver counted each repeat as another activation and returned
  `current_manifest_ambiguous`. Measured, not inferred: the two diagnostic manifests in run
  37621405799 are byte-identical, so widening the regex alone would have left the lane aborting
  whenever `begin_series` landed after one 10 s tick. Identities are now counted distinct, which is
  what the docstring already meant — a real re-activation carries a new sequence and epoch, a
  heartbeat does not, and a test asserts a genuinely distinct second manifest is still refused.
- ⚠️ **Not fixed, and not the same event:** the nightly has no notifier at all. `lane-b-stats-e2e.yml`
  carries no notify/Discord/webhook step, so this lane can be red for a fortnight in silence. A
  single-failure notice is the wrong shape — the `full` lane is deliberately non-deterministic and
  deliberately not a required check — so what is owed is a notice on N consecutive SCHEDULED
  failures, which needs state.
