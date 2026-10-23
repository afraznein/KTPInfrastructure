### Changed
- Lane B applies KTPHLStatsX migration 047 (`ktp_move_census.air_ms_standing`). The paired
  daemon names the column in its move-census INSERT, so a lane without it would fail every
  move-census row once the daemon ref carries it. Listed after 046; test tail and fixture repo
  updated to match.
