### Added

- `tests/e2e_stats/manifest_contract.py` — the capture EVENT-TYPE set is now
  bound to the daemon-side registry that has to know it. The manifest grammar
  guard next door is structurally blind to this: `capabilities` reaches it as a
  `%s` conversion, so whatever the producer lists inside that string is never
  read. The producer's own `g_kscEventNames` table is the authority and nothing
  here copies it; `ArtifactSet.collect()` runs the check against the `.inc`
  extracted at the amxx sha under test, so it cannot go stale behind KTPAMXX.
  A second leg compares the name table against the enum it is sized by, because
  Pawn zero-fills a short tail and the unnamed type then emits under an empty
  name.
  Both earlier instances of this defect — `move` on 2026-09-29 and `aim_vis` on
  2026-10-05 — were repaired by editing a list after the fact. `move` sat
  unregistered for three days, taking four Lane B assertions and a report
  authorization down over a stream that was working.
  `tests/unit/test_capture_event_type_registration_drift.py` adds the leg that
  runs on every PR, including a replay of the `move` window and a check that
  `collect()` still calls both guards.

### Changed

- `tests/e2e_stats/test_artifacts.py` — the fake producer now carries the event
  enum and name table as well as the manifest format string. A fixture simpler
  than the production shape passes checks the real producer would fail.
