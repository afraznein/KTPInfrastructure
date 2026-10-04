### Changed
- Lane B now applies KTPHLStatsX migration 040 (`ktp_flag_captures` provenance + `source_action_id`, afraznein/KTPHLStatsX#143). Without a position in `DEFAULT_SCHEMA_FILES`, every Lane B build of a daemon ref that carries the file fails before it starts.
