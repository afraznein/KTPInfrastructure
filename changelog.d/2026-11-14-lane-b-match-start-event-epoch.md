### Lane B: the diagnostic series parses a `KTP_MATCH_START` that carries `event_epoch` (2026-11-14)

The full nightly has failed `diagnostic_match_stats_reconciled` and `capture_context_isolation`
on every run since KTPMatchHandler 0.10.185 (`afraznein/KTPMatchHandler`#67, merged 2026-11-11
19:39Z) appended `(event_epoch "<n>")` to `KTP_MATCH_START`. The harness's `_MATCH_START_RE` in
`tests/e2e_stats/break_scenarios.py` anchored the line at `(type "<n>")` followed by end of line,
so it matched no start at all. `begin_series` then aborted with `current_match_start_missing`
before any scenario ran, the diagnostic match ended with 0 kills, and both checks failed for
want of diagnostic evidence rather than on anything the producers did.

- The parser now accepts an optional `(event_epoch "<digits>")` after `type`, so it still binds
  matchhandler refs from before the change.
- Replaying the 11-14 nightly's own `lane-b-e2e.log` (run 43564773586), cut at the diagnostic
  match's first lifecycle boundary: the old parser finds 0 starts and returns
  `current_match_start_missing`; the new one finds 2 and binds `("1794637433-TEST", 1, 1794637448)`.
  The 11-11 06:08Z log (run 42970288647, before the change) binds the same manifest under both.
- New tests: the verbatim fielded line binds, and a malformed or extended epoch suffix does not.
  The first fails against the old regex.
