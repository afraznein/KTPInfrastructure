### Added
- Lane B registers KTPHLStatsX `sql/migrate_050_shot_rewind_shift.sql` after 049. It adds
  `ktp_shot_events.tgt_shift`: how far the shooter's rewind moved the victim from where the victim
  really was, in units (stats_logging 1.34.0, engine `ktp_rewind_shift_v1`). The daemon names the
  column in every shot INSERT, so Lane B cannot build that daemon ref without the migration.
