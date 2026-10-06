### Added
- Lane B registers KTPHLStatsX `sql/migrate_043_position_samples_time_index.sql` in apply order, after 042.
  It only adds `idx_pos_match_half_time (match_id, half, game_time)` to `ktp_position_samples`; nothing
  the daemon writes depends on it. Without an apply position, every KTPHLStatsX PR carrying the file
  fails Lane B at artifact collection ("no apply position"), so this has to merge first.
