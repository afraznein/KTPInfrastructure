### `flag_swing`: a floor under the weekly map-coefficient refit (2026-11-10)

The weekly refit rewrites `config/map_coefficients.json` wholesale, so a map whose halves leave
the training window drops out of the table and `flag_swing` prices it on the hardcoded
`(2.0, 1.0)`. The 2026-11-09 refit did this to four maps (`dod_armory_b6`, `dod_halle`,
`dod_saints2_b3e`, `dod_saints2_b4e`), and `dod_halle` is still listed competitive.

**The floor is a separate file, `config/map_coefficients_retained.json`.** It has to be: the refit
patch rewrites the whole `maps` block, so anything kept inside the live table would be lost or
would stop the patch applying byte-for-byte. The refit never writes the new file.

**Every row is derived from git history, never typed.** `python3 -m scripts.map_coefficients_retained
--write` walks every committed version of the live table and, for each map that some version fitted
and neither table now covers, writes the last row it had, with the commit, `fitted_at` and corpus it
came from. Seeded here with the four rows above, all from the 2026-10-15 fit (`c39fa04`,
`officials_plus_all_practice`, 0 official halves each).

**Precedence, highest first:** an explicit config, the map's live row, a carry-forward to a live
predecessor, the map's retained row, then the prior. A refit that fits the map again makes its retained
row inert without anyone editing it.

**A carried row is never mistaken for a fresh fit.** Its envelope reads calibration
`retained_fit:<map>@<commit>` and `coefficients_retained: true`; every other envelope carries
`coefficients_retained: false`.

**A future drop cannot merge silently.** A unit test runs `--check`, which fails when a map that history
fitted is in neither table, so a refit that drops a map goes red until `--write` is committed on its
branch. It reads history, so on a shallow CI checkout it fails rather than skips.

The competitive list in `ktp_maps.ini` deliberately does not drive this: it lives in another repository
outside the analytics import closure, and practice reports price these maps too.

Schema 39 -> 40: four maps reprice and every flag_swing envelope gains the boolean.
