### `sql/analytics/player_match_fact.sql`: no full Statsme scan per report (2026-11-14)

`player_match_fact` read shots and hits with `WHERE match_id = X` on MyISAM
`hlstats_Events_Statsme`, which has no `match_id` index, so every report scanned
the whole table under the read lock the stats daemon's writes wait on. That scan
was nearly all of the query's ~2 s; it is now ~0.2 s on a recent match.

- `weapon_totals` now joins Statsme from the roster through its `playerId`
  index and keeps the `match_id` filter. The outer query only keeps roster
  players, so the rows are unchanged.
- `assists` reads MyISAM `hlstats_Events_PlayerPlayerActions` the same way.
  It has no `match_id` index either, and nearly every row is an assist, so the
  `actionId` index was reading the whole table.
- The `producer_coverage` checks compare an open match against the DATETIME
  maximum instead of the row's own time, which is the same answer and lets
  `ktp_flag_captures` seek its `event_time` index.
- `tests/unit/test_player_match_fact_bounded_reads.py` pins both shapes.
- `cap_break_fact.sql` is unchanged: it can only be bounded by an index on
  `hlstats_Events_PlayerActions(producer_match_id)`, which is a MyISAM rebuild
  and is staged for the operator rather than shipped here.
