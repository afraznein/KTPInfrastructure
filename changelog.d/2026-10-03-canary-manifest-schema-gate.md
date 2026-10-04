### `canary_evidence`: `manifest_authorized` reads the producer contract's schema set, not a literal 22 (2026-10-03)

`capture_health_evidence` tested the manifest schema with `== 22`. Measured on the
live `ktp_capture_manifests` 2026-10-03: 794 rows across 405 matches, distributed
23 → 340, 24 → 356, 25 → 98, and **zero rows at 22**. So the field was `false` for
every match in the database — a field that cannot be true carries no information,
which is indistinguishable from one correctly reporting a problem.

- The schema leg now reads `match_analytics.CAPTURE_SCHEMAS`, the same set
  `evaluate_capture_authorization` already tests against, rather than restating a
  number. A schema added to the contract reaches this gate with no second edit.
- The other two legs of the same `all(...)` were re-measured and are **not** frozen:
  all 794 rows are at `position_interval` 2.00 and carry both `objective_attempt`
  and `grenade_entity`. They are left exactly as they were.
- `manifest_authorized` is reported, not gated — `trusted` is computed from
  `evaluate_capture_authorization`, which has accepted 23/24/25 all along. No canary
  passed that should have failed.
- Tests prove the gate returns both values: every schema in `CAPTURE_SCHEMAS`
  authorizes, one below the floor does not, and a bad cadence or a missing stream
  still fails on a fielded schema.
