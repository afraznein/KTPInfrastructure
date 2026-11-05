### Added
- `docs/ANALYTICS_REPORT_DTO_CONTRACT.md` gains a "Who reads these rows" section:
  the served table is `ktp.match_report` under the `ktp` schema profile
  `report_sync` sends, rows are append-only, and every consumer therefore picks a
  row. Six website surfaces are tabulated with the rule each one uses, read at
  source in `searse/keep-the-prac` at `main` `1972d07c`. The file had described
  what the producer writes and nothing about what a consumer does with it, so the
  four exception classes it names were safe only by consumers nobody had written
  down — which is how the question of whether any served surface reads across a
  version the guarantee does not cover came up twice.
- The three facts that section exists to carry: three readers fetch every row for
  every match with no order and no limit, so `latestReports` is not an
  optimisation and removing it would double-count every historical revision into
  the season, player and weapon aggregates; the list page's
  `order(id desc).limit(limit * 4)` is a budget rather than a filter, and above
  800 rows it drops matches oldest-first with no error; and the captain's series
  proposal orders by `(report_schema_version, revision, id)` and checks no
  contract version, so it agrees with the other five only while `id` order agrees
  with schema/revision order.
- Stated there too: the class no consumer guarantee can reach is a value that is
  present, correctly shaped and wrong — the pre-schema-19 half-1 `map_control`
  and `progression.flag_differential`. The caveat machinery only reports keys as
  absent, so an inverted value renders. A served row below schema 19 is a match
  page showing two fields backwards, and the remedy is a regenerate and resync,
  not a website change. How many versions are actually being served is left as a
  stated open question with the row-picking rule a query has to replicate.
- Recorded in the same section: `match_report.contract_version` is the module
  constant `analytics_report_dto.CONTRACT_VERSION`, stamped by `sanitize_report`
  at sync time and never read from the stored report, so it records which
  sync-time code wrote the row and not what the payload contains. A row can read
  the current contract and carry an old schema. Any question about payload
  contents keys on `report_schema_version`; a check written against the contract
  string clears a row whose payload predates the thing it is checking for.
