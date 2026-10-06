### `ci`: Lane B applies KTPHLStatsX migration 043 (2026-10-06)

The daemon ref in afraznein/KTPHLStatsX#159 carries
`sql/migrate_043_position_samples_time_index.sql`, and `plan_schema_files` refuses any carried
migration with no apply position, so that PR's `corpus-regression / Lane B` fails at the build step
before anything runs. 043 is applied rather than skipped, and not only because an index changes no
rows: the lane runs the query the index serves. `scripts/match_analytics.py` executes
`sql/analytics/shot_placement_fact.sql`, which joins every shot to enemy `ktp_position_samples`
rows within ±1.0 s, and `lane_b_match_report.py` runs inside the Lane B job. Skipping 043 would
leave the lane planning that join against the only `(match_id, half, …)` index that exists today —
a schema production will not have once the migration is applied — which is the asymmetry
`NOT_APPLIED_MIGRATIONS` is wrong for. The three entries there are all redundant-or-irrelevant
(columns already in `ktp_schema.sql`, tables the daemon never writes); this one is neither.
