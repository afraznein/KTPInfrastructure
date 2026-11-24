### Added
- Lane B registers the `shot_miss` capture stream and KTPHLStatsX
  `sql/migrate_052_shot_miss_events.sql` after 051: the ray and trace count of a shot that hit nobody,
  which the shot line had no room for. `CAPTURE_EVENT_TYPES_OPTIONAL` gains the name, so the derived
  known-health-types SQL and every assertion built from it learn it in one edit.
- Registered BEFORE the producer that emits it is fielded, which is the whole point and is the third
  time this has had to be said: `ksc_emit_health` loops over the plugin's whole event enum, so the
  first build that gains the stream emits a health row for it whether or not it announces the
  capability -- and an unknown type fails `capture_health` for every half. `move` did exactly that on
  2026-09-29, over a stream that was working.
- The optional-stream drift guard and the health-type integration test each gain a `shot_miss` case,
  and the Lane B schema fixture gains its migration row. Producer: `afraznein/KTPAMXX`#185; daemon:
  `afraznein/KTPHLStatsX`#182.
