### `build-game-files-manifest.py`: every declared excluded bucket is enforced on every route (2026-11-14)

`_meta.excluded_buckets` was a hand-written list beside the code that enforced it, so the two
could drift, and they did: `maps/*.bsp` was declared for months while the `.res` route admitted
it (fixed in #875). Auditing the other buckets the same way found a second, latent leak: the
`ktp_file.ini` route applied only the flag-model names, so an `overviews/*`, `*.res` or `*.bsp`
line there would have entered scope at `violation`. Today's `ktp_file.ini` carries none, and the
installed manifest holds no such entry beyond the three `.bsp` paths #875 already removes.

- `EXCLUDED_BUCKETS` is now the single source: each bucket is the label the artifact carries
  plus the rule that enforces it. `_meta.excluded_buckets` is derived from it, and
  `EXCLUDED_PATH_PREFIXES` / `EXCLUDED_EXTENSIONS` / `EXCLUDED_EXACT` are views of it.
- `is_excluded()` (case-insensitive) runs on the `.res` and `ktp_file.ini` routes; an import-time
  guard refuses an explicit list (equipment singletons, grenade viewmodels, weapon kit) that names
  an excluded path; and `build_manifest` refuses rather than emits if any route lets one through.
- `tests/unit/test_excluded_buckets_enforced.py` feeds one path per declared bucket, plus an
  upper-cased copy, through every route. Ten single-point mutations (each route filter, the
  backstop, the import guard, each rule kind, case folding, a hand-edited label list, the weapon
  kit missing from the guard) each fail it.
- No change to the manifest a regeneration produces from today's inputs.
