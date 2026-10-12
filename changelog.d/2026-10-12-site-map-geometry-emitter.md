### Added

- `scripts/emit_site_map_geometry.py` — the derivation can now be turned back
  into the file the website ships. `test_spatial_map_geometry.py` already proved
  `spatial_map_geometry.py` reproduces that table, but the proof was one-way:
  there was no generator, so the hand edit stayed the only producer and every
  immutable match report written meanwhile baked in hand-typed values.
  The emitter owns four geometry fields and carries every other descriptor key
  through byte-for-byte. That is the point rather than a limitation:
  `registry.json` records `overview_transform_reviewed` for `dod_anzio` alone —
  absent, not false, on the other five — while the site's table marks all three
  of its maps `technical_validation: passed`. A generator that wrote whole
  descriptors would have to mint that field for maps nothing has reviewed, so a
  configured map the base table does not already carry is refused by name
  instead of added. `dod_lennon5_b1` has no config here and is reported as
  deferred, never silently skipped (operator ruling 2026-10-08: the generator
  cannot invent an overview without captured flag positions).
  `--refresh-pin` is the other half. Regenerating the site's table is an
  upstream hand-edit as far as `PIN.json` is concerned, which its own
  `drift_directions` already records as NOT CAUGHT — so the vendored copy would
  go stale and the suite would stay green against bytes the site no longer
  ships. The refresh re-vendors upstream, rewrites the provenance fields, and
  sets the new `equality_grade` from a comparison rather than from a claim.
- `tests/unit/test_site_map_geometry_emitter.py` — covers both of those, and
  the exact-equality leg keys on `equality_grade`, so moving the pin upgrades
  the gate instead of merely recording that someone moved it. Mutation-tested
  nine ways with none vacuous: dropping the unbacked-map refusal, overwriting
  the carried-through review field, either serialisation change, rewriting the
  deferred map, dropping a descriptor key, letting the refresh assert the grade
  instead of measuring it, and both wrong grades each redden a named leg.

### Changed

- `tests/fixtures/site_map_geometry/PIN.json` — carries `equality_grade`, which
  says which gate the equality runs under and is written by the refresh tool,
  never by hand. `rounded` today: upstream's `pixel_to_world` is cut to about
  twelve significant figures, so only a relative tolerance can hold.
