### Interruption bands: the direction replicated, the magnitude did not (2026-10-02)

The bands `interruptions` shipped with came from 54 official halves, where the
top two rested on n=22 and n=10. Replicated on the 12-man corpus — independent
data, five times the events — and on scrims:

| band | officials | 12-mans | scrims |
|---|---|---|---|
| negligible | 0.99 (n=186) | 0.97 (n=923) | 0.82 (n=667) |
| partial | 0.64 (n=45) | 0.82 (n=188) | 0.99 (n=203) |
| substantial | **0.38** (n=22) | 0.74 (n=118) | 0.89 (n=117) |
| decisive | **0.00** (n=10) | 0.71 (n=59) | **1.06** (n=56) |

**The shape holds** on 12-mans: every band below chance, monotone in progress,
the control nearest chance, over 1,111 events. **The magnitude does not.**
Officials' 0.38 and 0.00 were small-sample noise; the honest estimate is a
modest ~0.7-0.8 in the strong bands. Scrims show no effect at all, with the
control *more* suppressed than the strong bands — either looser play not
following up a stopped capture, or noise, and these samples cannot separate
the two.

A row now carries every corpus's measurement under `measured_all_corpora` and
names which one it prices on (`PRICING_CORPUS`, the 12-man column — the largest
sample whose dose-response holds, not simply the largest). `measured_lift`
reads 0.71 rather than 0.00 for a decisive interruption, because the ledger in
`infra-mmr-ratings` is about to read it and 0.00 says "a decisive interruption
always prevents the cap-out", which five times more data contradicts.

Schema 23 → 24, `interruptions_v1` definition version 1 → 2.

Re-measure with `review/hidden-value/tools/hv_interrupt.py`, which now takes the
match types as its third argument.
