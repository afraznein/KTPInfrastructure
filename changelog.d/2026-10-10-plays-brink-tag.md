### A cap that reached the brink says so in the public plays block (2026-10-10)

`plays` ranks by swing, and the swing curve flattens exactly where a round is
about to end — so on anzio the fourth of five flags prices at +0.126 and the
fifth at +0.102. A cap that leaves the enemy one flag from losing the half reads
as an ordinary cap, which is how drew's three anzio brinks were reported back to
him at +0.24, +0.18 and +0.16 with nothing to mark what they were.

Such a play now carries the tag `brink` and says so in its summary. Measured
over 963 of them: the side converts a cap-out within 90 s **26.1%** of the time
against **13.4%** for the same sides taking one flag fewer.

**The value is untouched, deliberately.** We have no fitted price for the threat,
and `plays` is a public block — putting an invented number in it would be worse
than leaving the play unranked. `infra-mmr-ratings` holds the ledger and prices
it; this makes the play legible to a human in the meantime.

A completed cap-out is not tagged: the round is over there and the threat is
moot. Interruptions are deliberately NOT synthesised into plays either — without
a price they would sort to the bottom of a value-ranked list and be truncated,
which is a worse outcome than their own block, where their evidence is intact.

Schema 28 → 29.
