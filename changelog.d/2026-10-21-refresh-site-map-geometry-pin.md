### `tests`: the site map-geometry pin gates on byte equality (2026-10-21)

Upstream regenerated its `map-geometry.json` on 2026-10-12 (`4a48edf`, "map geometry: generated
matrices for anzio and thunder2, not hand-typed"). That is the one drift direction `PIN.json`
records as NOT CAUGHT: the vendored copy kept the bytes captured on 2026-10-08, its sha256
self-check kept passing against them, and the suite stayed green against a table the site had
stopped shipping.

`scripts/emit_site_map_geometry.py --refresh-pin` re-vendors upstream and sets `equality_grade`
from a comparison rather than a claim. It moved `rounded` to `generated`, because upstream now
ships this emitter's own bytes.

- The vendored blob is `66ef745a1f625c778e668ee4d2ee4745805af977`, equal to upstream's
  `origin/main` blob for that path; the stale pin held `a413eaddd8584becbf582562eb3ecfc3ec4448ec`.
- `test_at_grade_generated_the_equality_is_exact` skipped under `rounded` and now runs, so the
  gate is exact bytes instead of the relative tolerance in `test_spatial_map_geometry.py`.
- `technical_validation` is carried through unchanged on every map, and `dod_lennon5_b1` stays
  byte-identical as the deferred descriptor. Agreeing with the generator still says nothing
  about whether either side is right for a map `registry.json` records no review for.
- `--refresh-pin` now also writes `captured_utc`. It was the one provenance field left to hand
  upkeep, so this refresh would have dated a 2026-10-12 capture to 2026-10-08 — a capture
  predating the commit it claims to come from.
