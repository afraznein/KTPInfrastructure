### The first per-map coefficient table, and the label gap that nearly hid it (2026-09-28)

`config/map_coefficients.json` ships with its first fitted values, so
`flag_swing` now prices a flag configuration by the map it is on. Schema 21 ->
22: every `p_allies`, `attributed_swing`, `key_moment` and `terminal_value` on
a fitted map changes.

| map | ships | own fit | official halves | weight |
|---|---|---|---|---|
| dod_thunder2 | 2.779 | 4.097 | 18 | 0.47 |
| dod_harrington | 1.673 | 1.773 | 16 | 0.44 |
| dod_lennon5_b1 | 1.240 | 0.888 | 20 | 0.50 |

Pooled is 1.592 over 54 halves. Thunder2 is the outlier the cap-out rates
predicted from the other direction — it is the map where flags rarely turn
over (0.33 cap-outs a half against harrington's 3.88), so holding them decides
more.

**The label feed does not reach the whole season.** `ktp_score_events` begins
2026-09-17 with migration 033, and thunder2 was played in week 37 — so the
engine labelled **2 of its 18 halves**, the map was fitted on those two, and
shrinkage correctly pinned it to the league value at a weight of 0.09. That
looked like "thunder2 is unremarkable after all" and it was nothing of the
kind. The driver now falls back to the demo ledger where the engine feed is
silent, tagging each half with its source and reporting the mix: 242 engine,
18 ledger. `--no-ledger-fallback` keeps the strict behaviour.

The ledger is the weaker label — the demo stops ~45 s early and on 3 of 38
halves carrying both it names a different winner — but for fitting, an
occasionally wrong label costs far less than discarding 89% of a map.

**Practice still does not help, and now says so with a margin.** Held-out loss
on official halves: officials only 0.6477, plus 12-mans 0.6496, plus all
practice 0.6501. The 206 extra halves make the prediction of officials worse,
not better, so the corpus stays officials-only — measured each week rather
than settled by opinion.
