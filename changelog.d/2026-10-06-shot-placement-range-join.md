### Changed
- `sql/analytics/shot_placement_fact.sql` joins position samples on bounds
  (`p.match_id >= sh.match_id AND p.match_id <= sh.match_id`, same for `half`) instead of equalities.
  With equalities MySQL plans a `ref` on the `(match_id, half)` prefix and reads every sample of the
  half for every shot; with bounds it re-plans a range per shot, and with KTPHLStatsX migration 043's
  `idx_pos_match_half_time (match_id, half, game_time)` that range covers the two-second window
  only. Output is unchanged. **Deploy only after migration 043 is applied**: without the index this
  join is slower than the old one.

### Added
- `tests/e2e_stats/test_shot_placement_plan.py` runs both join forms on an ephemeral MySQL, asserts
  they return identical rows, that the shipped form plans `Range checked for each record` with the
  new index available, and (control) that the equality form plans a `ref` that never reaches
  `game_time`.
