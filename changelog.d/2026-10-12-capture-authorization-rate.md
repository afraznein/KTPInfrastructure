### Added

- `scripts/capture_authorization_rate.py` — fully-capture-authorized reports
  per day over a window, read-only, reusing `match_analytics`'
  `evaluate_capture_authorization` rather than reimplementing it.
  `match_capture_authorization` already answered this for ONE match; the rate
  over a week had no tool, which is why the number the D5 daemon was deployed
  to move went days without being re-derived — the fix was proven to execute
  and unproven to work, and re-deriving it meant hand-writing the queries
  again.
  🔴 **The denominator is the finding and it is worth more than the number.** A
  "report" is a match carrying a `ktp_match_reports` row, not a match. About a
  third of played matches never get one, so counting `ktp_matches` is
  defensible, reads identical in a summary and gives a different answer —
  measured over the same week, 21% against 27%. It is also the wrong direction
  to be wrong in, because the recorded baseline was taken on the report
  denominator, so swapping it shrinks a real improvement while still looking
  like a comparison. `--denominator matches` exists so the gap can be seen; it
  is not the default.
  ⚠️ **And the metric the question is usually asked in cannot see the
  improvement at all.** Fully-authorized reports per day ran 0..5 over that
  week against a 0..4 baseline, because a per-day count is bounded by how much
  was played. The share is what moved, 8% to 27%. The report prints the series
  and the ratio together for that reason.
  An empty window says so instead of printing 0%, and a non-zero `mysql` exit
  is raised rather than read as a window with no matches — the two shapes are
  identical otherwise.
- `tests/unit/test_capture_authorization_rate.py` — the fixture is built so the
  two denominators **disagree**, and a test asserts it: one where they agreed
  would pass whichever the code used. It also pins that the excluded matches
  are the clean ones, so dropping the report join moves the answer in the
  flattering direction rather than merely adding noise. Every withholding
  bucket is driven from a string `_reconcile_failures` actually emits, and an
  unrecognised reason survives verbatim as `UNCLASSIFIED:` instead of being
  folded into a bucket that would hide a new failure mode.
