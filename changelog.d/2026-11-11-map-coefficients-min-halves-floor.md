### `fit_map_coefficients`: the refit keeps a measured row instead of dropping a map (2026-11-11)

The weekly refit rewrote `config/map_coefficients.json` from whatever this week's fit
produced, so a map that left the fit fell to the hardcoded `(2.0, 1.0)` in `flag_swing`, and a
map re-measured on a handful of halves replaced a better-evidenced row with one that is mostly
the pooled value. The 2026-11-02 proposal did the first to `dod_solitude2` (a measured 1.2309
would have become 2.0); the 2026-10-15 fragment named this remedy first.

**The floor now lives in the fitter.** After the fit, `apply_floor` walks the committed table
and keeps a map's committed row when the map is absent from the new fit, or when it now has
fewer than `--min-official-halves` official halves AND fewer than the row it would replace. The
default is `--prior-halves` (20): below it a row's shrinkage weight is under 0.5, so the row is
more league than map. A thin map that is gaining halves takes its new fit, and a map with no
committed row is left to the fit, so a never-measured map still lands on the fit or the prior.
Kept rows carry `kept_by_floor` (`absent_from_fit` or `fewer_official_halves`),
`kept_from_fitted_at` and `refit_official_halves`, the table records `min_official_halves`, and
the refit's diff lists every kept row under its own heading.

**Kept rows are labelled like retained ones.** `flag_swing` loads them out of the live table
into `FLOOR_KEPT_MAP_COEFFICIENTS`, ranks them with the retained rows (after a carry-forward to
a fresh predecessor, ahead of `config/map_coefficients_retained.json`), and prices them as
`retained_fit:<map>@<fitted_at>` with `coefficients_retained: true`. The retained file stays as
the floor for the four maps dropped before this existed.

**No stored value changes.** The committed table has no kept rows, so every map resolves exactly
as before. Replaying the floor over the accepted 2026-11-09 refit (`c39fa04` -> `166a059`)
leaves all ten fitted rows byte-identical and brings back only the four maps #839 retained by
hand; a test pins that.
