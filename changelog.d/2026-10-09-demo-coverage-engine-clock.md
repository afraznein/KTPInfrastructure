### `stats`: `demo_coverage` takes each half's end from the engine round clock (2026-10-09)

`scripts/demo_coverage.py` measured demo loss against `MIN(context_live) + 1200`. That row is
written by the producer, so when KTPMatchHandler 0.10.176 moved go-live onto the real
`RoundState=1` the reference moved about 10 s later and read as a fleet-wide +10 s of demo
tail loss with no demo changed. The half end is now the median of
`game_time + round_time_left` over the half's `ktp_score_events` rows (schema 25), else its
non-initial `ktp_flag_state_events` rows. A clock at 0 and the `-1` "no time limit" sentinel
are excluded.

- The context_live reference stays only as the fallback for halves with no clock, and those
  rows print `assumed` in a new `end_src` column; the summary line counts each source.
- `--half-seconds` now applies only to that fallback. Overtime and short halves no longer
  need it, because the engine clock already knows how long they ran.
- Re-run read-only on the data server's archive (21 days, all match types, 544 halves): the
  median loss is 49.3 s on every producer from 1.23.1 through 1.26.3, including 1.26.1, 1.26.2
  and 1.26.3. The old reference gave 44.6 s up to 1.26.1 and 54.6 s on 1.26.2 and 1.26.3.
