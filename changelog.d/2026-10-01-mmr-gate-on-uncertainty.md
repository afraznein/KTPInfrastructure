### `mmr`: a rating is shown once its uncertainty comes down, not once 3 matches are played (2026-10-01)

Two defects, both live on player profiles since the first import on 2026-09-21.

**The `min_matches` gate was enforced by nobody.** The producer published the threshold; the
consumer never applied it. `keep-the-prac`'s `findMmrEntry` filters on `name !== null` and
nothing else — while `mmr-data.ts`'s own docstring claims the entry is null when *"this player
is below the payload's own `min_matches`"*. So **120 of 161 players were below the threshold and
each got a card**, 41 of them on a single match.

**`conservative` (μ−3σ) was negative for 76 of them.** Not because they were under-sampled, but
because σ is **8.16 for every player** — barely off the 8.333 starting value — so μ−3σ is just
μ−24.5, and half the μ values sit below 24.5. Raising `min_matches` would not have helped: every
displayable player already had exactly 3 matches.

`conservative()` is deliberately pessimistic, and the reasoning in its docstring is right — a
flattering μ off two matches is a claim the evidence does not support, *"and it is the player's
own profile reading it back at them"*. The unanticipated consequence was that the same concern
got violated from the other side: it published a negative number as someone's skill.

So the gate is now **σ**, not match count: a rating ships when uncertainty has halved from the
model's starting value (`SIGMA_CONVERGED_FRACTION = 0.5`, so σ ≤ 4.167). Match count says how
often someone turned up; σ says whether the rating knows anything yet, which is the question the
card is actually asking. Both gates apply, not either.

**Gated in the producer, not published as a threshold.** A row that should not be displayed is a
row that should not be published — a consumer that ignores every threshold still cannot render
someone it was never sent. That is the lesson of the first defect.

The import guard had to be split to allow this. An empty `players[]` used to be refused outright
("publishing zero players would blank every profile card"), which is right for a *broken build*
and wrong for the honest early-season state. It now checks `rated_players` — how many the ladder
rated at all — so "nobody has converged yet" publishes while "the builder produced nothing" still
fails.

⚠️ **On current data this withholds everyone**: 161 rated, 0 shown, because the lowest σ in the
live payload is 8.16. The card goes empty, which is the accepted outcome of the choice — ratings
return when σ halves, needing roughly 10+ matches per player against a median of 4 per season.
That interacts with `FINDING_s9-carryover-is-empty_20260930.md`: with unofficial play excluded
from the calculation, that may be a long wait, and the honest answer is to show nothing rather
than a number that is mostly prior.
