### Fixed
- `report_service.persist_report` wrote `report['generated_at']` (UTC ISO with microseconds and an
  offset) straight into the whole-second `ktp_match_reports.generated_at` DATETIME. MySQL 8.0
  converts such a literal to the session zone only when the fraction rounds down; from .5 up it
  rounds and stores the UTC wall clock, so about half the rows sat four hours in the future. The
  pending gate compares that column with `end_time` (the daemon's `NOW()`, session zone), so a skewed
  row could suppress a needed regeneration. The column is now written as
  `FROM_UNIXTIME(<whole-second epoch>)`, the same zone `NOW()` uses; a value with no offset is
  refused. The report JSON keeps its own `generated_at` unchanged. Existing rows are not backfilled.
