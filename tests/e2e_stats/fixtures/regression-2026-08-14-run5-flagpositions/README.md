# Run 5 — first fixture with real ktp_flag_positions data

Real 16-bot Lane B match on `dod_anzio`, run to validate KTPAMXX's
`ksc_flag_positions_task` fix (`feat/stats-break-context` @ 34b28b72):
`controlpoints_init()`'s flag-position markers were reaching
`log_message()` successfully but never landing in the game log at that
early point in map load — root-caused with a diagnostic build across two
prior Lane B runs (2026-08-14), fixed by deferring the actual writes to a
one-shot delayed task. See that commit and `KTPAMXX/CHANGELOG.md` for the
full story.

Every fixture before this one (including
`regression-2026-08-13-run4-flagcaps`) has zero `ktp_flag_positions` rows
for exactly this reason — not a data-collection gap, a write-timing bug.

## Result

136 kills, 20 assists, 1 cap_break, 6 suicides — all exact log-vs-DB
matches. 1928 `ktp_position_samples` rows. All 5 `dod_anzio` flags
recorded with correct names and coordinates:

| flag | x | y |
|---|---|---|
| POINT_ANZIO_LAUNDRY | -1495 | -326 |
| POINT_BRIDGE | 1040 | -288 |
| POINT_ANZIO_STREET | 448 | 800 |
| POINT_ANZIO_PLAZA | -698 | 923 |
| POINT_ANZIO_HILL | 1375 | 1682 |

First real run of `scripts/positional_baseline.py`:

```
=== baseline: dod_anzio (n=1928) ===
  mean=1331  median=1133  min=2  max=3984  (map units)
```

0 of 1928 samples excluded for "no known-enemy flag at that moment" —
better coverage than `run4-flagcaps` (which had fewer, more concentrated
captures); this match's capture activity was frequent and spread out
enough that ownership was known for most of the match's duration.

Per-player advancement vs. baseline ranged from +563 (most forward) to
-443 (most back) map units — a real, usable spread, not noise clustered
near zero. Still one match: the script's own `n<30` confidence note
didn't fire here (n=1928 samples clears that bar easily), but one
match's *baseline* is still one data point pretending to be a
distribution across matches, same caveat as always. The next real
improvement is more matches, not more code.
