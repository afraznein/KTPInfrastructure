### Added
- A pull request that changes the analytics output path now fails
  `Analytics schema decision` unless it either bumps `SCHEMA_VERSION` in
  `scripts/match_analytics.py` in its own diff, or declares in its own body, under a
  heading whose line carries `schema` and `version`/`bump`, that stored values do not
  change. #693 and #696 changed what the analytics produce and left the constant alone;
  that constant is the generator's only test for "already current", so 237 published
  reports kept pre-fix values with nothing that would ever revisit them, and both PRs
  merged on full green CI. New `scripts/check-analytics-schema-decision.py` plus
  `.github/workflows/analytics-schema-decision.yml`, modelled on the two audit-record
  gates in `afraznein/KTPAntiCheat`.
- The output path is **derived**, not listed: the transitive `scripts.*` import closure
  rooted at the generator (25 modules), plus the `config/` data files those modules read
  (4). A gate keyed on `scripts/**` would red-light docs- and test-adjacent touches that
  owe nothing, and a hand-written list rots silently in the permissive direction. The
  data leg is not decoration — schema 22 and 27 were both bumps this repository made for
  a change to `config/map_coefficients.json` and to no code at all.
  `scripts/analytics_report_dto.py` is out of scope by construction and a test records
  that as a decision: it is reached from `report_service`/`report_sync`, never from the
  generator, and nothing about it is skipped at schema parity.
- `tests/fixtures/analytics_schema_gate/` holds #693's, #696's and #697's real payloads
  as GitHub served them — every changed file with its `status` and `patch` verbatim, and
  each body as written — and `tests/unit/test_check_analytics_schema_decision.py` fails
  if the gate would pass either of the first two or fail the third. Both of those PRs
  also ship a `changelog.d/` fragment and new unit tests, so a gate keyed on either of
  those cheap signals is green on both; that is pinned too. Mutation-checked: reading a
  declaration out of loose body prose, dropping the data leg, or accepting a bare mention
  of the constant in a diff each break the suite.
- ⚠️ A green on this check says a **decision was recorded**, never that the data is
  right. Bumping costs one character, the author need not have regenerated anything, and
  the regeneration is an operator act on another host. The script prints that on every
  pass rather than leaving it to whoever reads the tick.
