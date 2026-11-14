### `sql/analytics`: the per-match readers use their match-id indexes (2026-11-14)

The fix that made `death_group_link_fact.sql` index-usable now covers the other
analytics readers. Ten of them still compared match ids only as
`BINARY a = BINARY b`, which cannot use an index on a `_ci` column, so each one
scanned its whole table for one match. `frag_context_fact.sql` read all of
MyISAM `hlstats_Events_Frags` that way, holding the table read lock the stats
daemon's frag `UPDATE` waits on.

- Each BINARY match-id test in `frag_context_fact`, `damage_timeline_fact`,
  `assist_timeline_fact`, `cap_break_fact`, `life_boundary_fact`,
  `position_sample_fact` (and `_legacy`), `grenade_entity_timeline_fact`,
  `objective_attempt_timeline_fact` and `player_match_fact` now sits beside a
  plain equality on the same operands. The BINARY test stays, so results are
  unchanged; the roster joins become `eq_ref` on `uk_match_player`.
- `tests/unit/test_analytics_sql_index_usable.py` now fails any BINARY
  equality anywhere in `sql/analytics` that is not directly preceded by its
  plain twin, so an `OR` or a distant twin no longer counts.
- `cap_break_fact` still filters `hlstats_Events_PlayerActions` by `actionId`:
  that table has no index on `producer_match_id`, so the pairing only fixes its
  roster joins.
