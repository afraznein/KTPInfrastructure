### Added
- Lane B registers KTPHLStatsX `sql/migrate_044_capture_health_rejection_reasons.sql` in apply order,
  after 043. It adds a nullable `rejection_reasons` column to `ktp_capture_health`, and the paired
  daemon (`afraznein/KTPHLStatsX`#166) names that column in every health INSERT — so a lane without it
  fails every health row, and a health row is what every capture assertion reads. Without an apply
  position, every KTPHLStatsX PR carrying the file fails at artifact collection ("no apply position"),
  so this has to merge first.
