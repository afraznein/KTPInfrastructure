### `config`: the 2026-11-09 map-coefficient refit is accepted, with its schema bump (2026-11-10)

The operator accepted the 11-09 weekly refit over the 11-02 one, because 11-02 dropped
`dod_solitude2`'s row and left a map in the current rotation pricing on the hardcoded
`(2.0, 1.0)`. The table here is the run's own patch applied with `git am`, so
`config/map_coefficients.json` is byte-identical to the reviewed artifact on the data
server rather than a fresh fit (md5 `95562020083af55f490815e674cd6fa2`, the same as that
run's `map_coefficients.proposed.json`).

**The corpus switch is the whole story, and it is stable.** The fit chose `officials_only`
for the fourth consecutive run (held-out loss on officials 0.654706, against 0.656456 with
all practice and 0.657220 with 12-mans). The committed 10-15 table, which chose practice on a
margin of 0.000136, was the outlier. So every row is now fitted on official halves only, and
the pooled fit moves 1.2318 -> 1.4787.

**Week on week it barely moves.** Of the nine rows both the 11-02 proposal and this one carry,
eight shift by less than 0.11 on the flag term; the exception is `dod_lennon5_b1` (1.0899 ->
0.9520 on two more halves). A per-map fit that holds still while the corpus grows is the evidence that it is
measuring the map rather than the week.

**What changes for which map:**
- `dod_solitude2` keeps a measured row: flag 1.129 from 8 official halves at 29% own weight,
  instead of the 2.0 constant (+62% on the flag term) the 11-02 table would have shipped. Its own
  alive estimate is `0.0`, so the shipped alive term is mostly shrinkage toward the pooled fit.
- `dod_railroad2_s10b` earns its own row (18 halves), so the s10a carry-forward added in schema 33
  goes inert exactly as designed. The entry stays: it is what keeps s10b off the prior if a later
  corpus flip drops its row.
- `dod_armory_b6`, `dod_halle`, `dod_saints2_b3e` and `dod_saints2_b4e` leave the table. All four
  were fitted on practice halves only and none has an official half since `corpus_since`
  (2026-09-13), so a report on any of them now prices on `(2.0, 1.0)`.
- Two thin rows remain, both in rotation: `dod_railroad2_s10a` on 6 official halves (own flag
  3.37, shrunk to 1.91) and `dod_anjou_a5` on 12 with its own alive estimate at `0.0`.

Schema 37 -> 38 so the stored reports regenerate onto the new values; the generator's only test
for "already current" is that number, and a refit patch stages only the JSON, so the bump is a
separate commit. The real-artifact carry-forward test now asserts that s10b resolves to its own
row when it has one and to s10a's when it does not, rather than pinning the carry-forward.

Not done here: a minimum-halves floor or retained-rows file so a map that loses its row keeps its
last measured value. It is no longer on the critical path for solitude2, and is owed as hardening.
