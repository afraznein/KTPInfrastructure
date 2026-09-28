### Per-map coefficients: a weekly refit that proposes, never decides (2026-09-28)

`scripts/fit_map_coefficients.py` fits `config/map_coefficients.json`, and a
weekly timer on the data server opens a pull request when the numbers move. It
never commits to `main` and never merges: a coefficient change is a claim about
how a map plays, and every one of them is reviewed (drew, 2026-09-28). Git
history of that one file is then the record of how the maps evolved.

Three decisions worth knowing:

**Labels come from the engine feed, not the demo ledger.** The demo stops ~45 s
before a half ends, and that can flip a winner — on `1789953124-DAL1` h2 the
engine reads 82-74 to side 1 with 30 of those points in the final minute, and
without them the half belongs to the side the ledger records. The engine feed is
also the only label that reaches 12-mans and scrims, which is where 204 of the
available halves live.

**Practice is training data that has to earn its place.** Officials are about a
sixth of the halves played on the week's map. Rather than argue about whether
looser play belongs in the fit, each candidate corpus (officials only, plus
12-mans, plus all practice) is scored by held-out loss **on official halves**
and the best one wins. Ties go to the least data, and a gain under 1e-4 is a
tie. Practice is never the thing being predicted.

**`--check` is the drift gate.** It refits and fails when the committed table no
longer matches the data, so CI and the weekly job use the same command, and the
table cannot quietly rot.

The table is still absent, so `MAP_COEFFICIENTS` resolves empty and behaviour is
unchanged until the first refit PR is reviewed and merged.
