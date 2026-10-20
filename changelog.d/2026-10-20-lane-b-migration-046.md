### Changed
- Lane B applies KTPHLStatsX migration 046 (`ktp_move_census.steps_ducked`,
  `ground_ms_ducked_silent`). The paired daemon (KTPHLStatsX#168) names both columns in its
  move-census INSERT, so a lane without them would fail every move-census row once the daemon
  ref carries it. Listed in `DEFAULT_SCHEMA_FILES` after 045, with the test's expected tail
  and fixture repo updated to match.
