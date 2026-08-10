# Idea: tick-accumulated KTPR (battlefield-style scoring)

**Status: parked.** Captured from a conversation on 2026-08-10 so it is not
lost. Nothing here is agreed, designed or started — it is a direction for a
future revision of KTPR, recorded while the reasoning was fresh.

## The idea

Instead of rating from discrete end-of-match outcomes, accumulate points
continuously through a half, the way a Battlefield-style scoreboard does.
Everything a player does that has value adds to a running total:

- caps and capouts
- **holding** a point — periodic, not one-shot
- breaking a cap
- defending a point
- kills and assists
- position at point-tick, as a heatmap contribution

The player's rating for the half is what they accumulated.

## Why it might be better than what exists

The current design (`KTPR_CALCULATION.md`, `weights.toml`) rates from event
counts after the fact. That makes some real contributions invisible, because
they are *durations* rather than events: standing on a point for four minutes
under pressure produces no event at all, and someone who touches a flag once
at the end can outscore them.

Tick accumulation makes time-on-objective first-class, which is closer to how
people actually judge who played well.

## What carries over

**The knobs already done are the input, not wasted work.** `KTPR_KNOBS.md` and
`weights.toml` are per-action values — the hard part is agreeing what a cap is
worth relative to a kill, and that stays true whether the value is awarded once
or accrued. The change is the *accumulation model*, not the valuations.

Roughly: today `score = Σ weight(action) × count(action)`; this would become
`score = Σ weight(action) × count(action) + Σ weight(state) × ticks(state)`.

## What would have to exist first

Most of this is not capturable today, which is the main reason it is parked:

| Needs | Status |
|---|---|
| periodic point-occupancy sampling | **not captured.** The cap-break detector already polls `dodx_area_get_data` every 0.5s (`KSC_ZONE_POLL_SECS`) and throws the reading away — that poll is the natural source |
| position at tick | partially there — `pos_x/y/z` land on assist and break rows, but only at event time |
| defending / holding as distinct states | not captured; would need the zone poll to attribute occupancy per player, not just count it |
| capout | Phase 7 in `IMPLEMENTATION_PHASES.md` |
| a tick event table | new; volume is the open question — a 0.5s tick × 12 players × 40 min is ~57k rows per match |

That last row is the one to think hardest about. The per-hit damage ledger
(Phase 6) already raises the same question, and the answer there —
buffer sizing measured from a real run — applies here too. A tick table may
want aggregation at write time (per player per point per N seconds) rather
than a row per tick.

## Sequencing

This sits **after** Phases 5-8, not instead of them. Frag context, the damage
ledger and break context all produce inputs this would consume, and Phase 8
wires `ktpr_mcp` to read event rows at all. Doing this first would mean
designing an accumulation model over data that does not exist yet.

Worth revisiting once Lane B can produce a multi-match fixture, because a
scoring change of this size needs to be evaluated against real matches —
"does it rank the players the way people who watched the game would?" is the
only test that matters, and it needs data.
