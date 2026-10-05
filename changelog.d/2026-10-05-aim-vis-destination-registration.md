### Added
- `aim_vis` is an optional capture health type, and Lane B registers KTPHLStatsX
  `sql/migrate_042_aim_vis.sql` in apply order. Both land before any producer exists, which is the
  point: `ksc_emit_health` loops over the plugin's whole event enum, so the first build that gains
  the aim-vis stream emits a health row for it whether or not it announces the capability — and a
  type outside `CAPTURE_EVENT_TYPES | CAPTURE_EVENT_TYPES_OPTIONAL` fails `capture_health` for
  every half. `move` did exactly that on 2026-09-29, taking `capture_health`,
  `diagnostic_capture_health`, `capture_context_isolation` and a v5 report authorization down with
  it over a stream that was working. The migration is applied in the lane rather than skipped for
  the same reason 038 is: the daemon INSERTs into `ktp_aim_vis`, so a lane without the table
  exercises the new handler as a no-op and reports clean either way.

### Fixed
- `check_capture_health` re-listed both the required and the required|optional event types inline,
  and that copy is what was missed when `move` was added — the SQL and
  `CAPTURE_EVENT_TYPES_OPTIONAL` are the same list maintained in two places. Both `IN (...)` lists
  are now built from `match_analytics`, the required-type count is derived from
  `len(CAPTURE_EVENT_TYPES)` instead of the literal 11, and a test asserts the derived SQL equals
  the analytics sets with a control that the two sets genuinely differ. `EVENT_TYPES` in
  `test_capture_health_assertion.py` was a third copy and is now derived too — a fixture that
  drifts from the assertion it exercises tests a shape production never has.
- `test_default_schema_sequence_includes_retention_through_shot_events` sliced
  `DEFAULT_SCHEMA_FILES[-25:]` against a tuple written out beneath it, so the literal had to be
  bumped in lockstep with every migration added to that tuple — a second edit nothing enforced.
  The slice now takes the expected tuple's own length. The `daemon_repo` fixture gained
  `migrate_042` for the same class of reason: the fixture must carry every file
  `DEFAULT_SCHEMA_FILES` names, or the collect test fails for a reason no change caused.
