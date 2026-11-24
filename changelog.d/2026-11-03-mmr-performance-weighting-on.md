### `mmr`: performance weighting on, and the report fetch that made it a no-op (2026-11-03)

- `run_weekly.py --use-performance` never split a match. `performance_scores` fetched every bound
  fixture's whole `match_report.payload` in one PostgREST request; at 80+ reports of several hundred
  KB each the statement timed out (HTTP 500, code 57014) and the run fell back to an even split for
  every match. The fetch now selects only `payload->ratings`, which is all the function reads.
  Measured on the S10 corpus (82 matches): 76 of 82 now split by KTPR.
- `mmr-weekly.yml` runs with `--use-performance` (drew's ruling, 2026-11-03). On the full S10
  regular season the split moves accuracy 58.5% to 59.8% and log-loss 0.6633 to 0.6631 against
  the even split, so it is a small gain and no loss; the S10 review found the within-match
  performance stats carry more information about results than the results do, which is the
  reason to let them steer who gets the credit. Coordination lane: `infra-mmr-ratings`.
