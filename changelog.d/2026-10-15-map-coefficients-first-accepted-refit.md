### `config`: the first refit proposal the league actually accepted (2026-10-15)

The weekly refit reached the end for the first time — 64m00s, one pass, 698
labelled halves — and the operator accepted its proposal. The table here is the
run's own patch applied with `git am`, so `config/map_coefficients.json` is
byte-identical to the reviewed artifact rather than a fresh fit of the same data.

Thirteen changes: four maps move their existing row, nine gain one. The fit also
switched corpus from `officials_only` to `officials_plus_all_practice` on held-out
loss (0.651250 against 0.651386), and found for the third consecutive run that
adding 12man play makes the fit *worse*.

**What the change list hides, and the reason to read the shrinkage weights.** The
largest moves land on the thinnest evidence. A map with no row gets
`FlagSwingConfig`'s hardcoded `(2.0, 1.0)`, and a new row is shrunk toward the
fit's pooled ~1.23 — so `dod_halle` moves −1.06 on 33% own weight, `dod_armory_b6`
−1.05 on 23% with its own estimates at `0.0`, and `dod_anjou_a5` −0.88 on 9%, from
two practice halves. Those rows are not saying "this map plays differently". They
are saying "the league prior is 1.23, not 2.0" — backed by 698 halves, and likely
right, but wearing per-map clothing. Two things follow, neither done here: a
minimum-halves floor before a map earns a row, so a row implies a measurement; and
a look at the `(2.0, 1.0)` default those rows are really arguing with.

**The `pooled` block changes and nothing reads it.** flag 1.4956 → 1.2318, alive
1.1299 → 0.8485. `_load_map_coefficients()` consumes only the `maps` block and no
other caller in `scripts/` touches `pooled`, so it is provenance the fitter
records, not a fallback production uses. Worth stating because the figure looks
load-bearing and is not — a review that treated it as the default for every
unlisted map would be reviewing the wrong number.

**One regression in `#713` showed up where it hurts most.** Collapsing three fitter
passes into one made `diff.txt` the `tee` of the single `--write`, which fixed the
review-integrity bug — the diff now describes the table that was written — but it
also puts 28 lines of loader progress into `diff.txt` and therefore into the
generated `body.md`. The PR body a human reads opens with a progress log. The fix
is to filter the progress lines out of the tee, not to restore the extra pass.
