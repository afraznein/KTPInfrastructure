### `scripts/`: embedded match-id lookups use their indexes (2026-11-14)

#867 and #883 fixed the `BINARY a = BINARY b` match-id tests in `sql/analytics`.
The same shape was also in SQL that scripts build as strings: `report_service`,
`report_scope`, `canary_evidence`, `match_analytics`, `lane_b_match_report`,
`lane_b_e2e`, `team_score_telemetry` and `capture_authorization_rate`.

- Each BINARY test now has a plain equality in front of it. Inside an `OR`, each
  arm is `(a = b AND BINARY a = BINARY b)`. The BINARY test stays, so results
  don't change.
- Where the other side is `utf8mb4_bin` (`ktp_match_reports`, the team-score stage
  table) or a `CONVERT(... USING utf8mb4)` literal, the plain twin carries
  `COLLATE utf8mb4_unicode_ci`. Without it the twin compares in `_bin` and can't
  use `ktp_matches`' index, or it fails with ERROR 1267.
- `tests/unit/test_embedded_sql_index_usable.py` reads every string literal under
  `scripts/` plus `sql/integrity/*.sql`, and fails any BINARY equality that
  doesn't have an adjacent plain twin.
