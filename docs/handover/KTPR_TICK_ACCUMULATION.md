# Handover: tick-accumulated KTPR (Battlefield-style scoring)

**For:** an AI agent or engineer producing a **plan**, not an implementation.
**Origin:** idea raised 2026-08-10. Nothing is agreed or started.
**Deliverable:** a design that could be built and, crucially, a way to tell
whether it is better than what exists.

---

## The idea in one paragraph

Rate a player by what they accumulate continuously through a half, the way a
Battlefield scoreboard does, instead of by counting discrete outcomes after the
match. Caps, capouts, **holding** a point, breaking a cap, defending, kills,
assists, and position at each tick all add to a running total. The half's total
is the rating.

## Why it is worth considering

The current model (`KTPR_KNOBS.md`, `KTPR_CALCULATION.md`) rates from event
counts. That makes an entire class of contribution invisible, because it is a
*duration* rather than an event: standing on a point for four minutes under
pressure emits nothing at all, while someone who touches the flag once at the
end gets the capture. Tick accumulation makes time-on-objective first-class,
which is closer to how people actually judge who played well.

---

## What already exists — read this before designing anything

### The current formula is not a strawman

It has been tuned against real data and has measured behaviour. From
`KTPR_KNOBS.md`:

- Per-player, per-**half** rates, normalised so `1.0` = the median regular
  player, then combined as a **weighted average** of six terms (kills, K/D,
  assists, damage, flags, breaks), with amplifiers that lift damage/assist
  credit specifically when kills are low.
- **`tw_kd` = 3.00 is the single biggest lever in the tuning history.** At
  1.50 the formula rated a 6-6 team above a 10-1 team; raising it inverted
  that correctly and moved predict-accuracy from **70.4% → 77.8%**.
- `tw_break` = 1.00 is the second most sensitive knob, because breaks are
  low-count and high-variance.
- `tw_damage` = 0.50 is the *least* sensitive — literally zero rank movement
  at ±10%.

**77.8% predict-accuracy is the number to beat.** A new model that cannot say
what it scores against that is not a proposal, it is a preference.

### The weights carry over; the accumulation model is what changes

The hard-won part of `weights.toml` is the *relative* valuation — what a cap is
worth next to a kill. That stays meaningful whether the value is awarded once
or accrued over time. Roughly:

```
today:     score = Σ weight(action) × count(action)
proposed:  score = Σ weight(action) × count(action)
                 + Σ weight(state)  × ticks(state)
```

So this is an **extension of the existing tuning**, not a replacement for it.
Frame it that way or the work looks like throwing away a year of calibration.

---

## The central design tension — address this first

Accumulation rewards **volume and presence**. The current model's biggest
measured improvement came from rewarding **efficiency** (`tw_kd`).

A naive tick model rates the player who stands on a point all game very
highly, whether or not they were any good. That is the exact failure mode
`tw_kd = 3.00` was raised to fix, approached from the other direction.

Any plan must say how it avoids that. Options worth costing:

- accrue per-tick value only when the state is *contested* (enemies nearby, or
  the point actually under threat) rather than for mere occupancy
- keep the per-half **rate** normalisation the current model uses, so totals
  do not simply scale with how long the half ran
- weight ticks by what else the player did while accruing them
- cap the tick contribution as a fraction of the total, the way `flag_cap` and
  `death_cap` already bound their terms

## Data: almost none of this is captured today

This is the main reason the idea is parked, and the plan must be explicit about
it.

| Needs | Status |
|---|---|
| periodic point-occupancy sampling | **not captured** — but see below, the poll already exists |
| per-player occupancy (who, not how many) | **not captured**; the poll counts bodies per team, it does not attribute them |
| position at tick | partial — `pos_x/y/z` land on assist and break rows, at event time only |
| holding / defending as distinct states | not captured |
| capout | Phase 7 in `IMPLEMENTATION_PHASES.md` |
| a tick event table | does not exist |

### The poll you want already runs and throws its reading away

`ktp_stats_capture.inc` polls `dodx_area_get_data(...)` every **0.5s**
(`KSC_ZONE_POLL_SECS`) for cap-break detection, reads `CA_num_allies` /
`CA_num_axis` / `CA_is_capturing` / `CA_owning_team`, and discards everything
it does not need. That is the natural source for hold/defend ticks and it is
already proven to work under bots.

**But it counts bodies, it does not identify them.** Per-player attribution —
which is what a rating needs — means either correlating with
`dodx_get_user_origin` per player per tick, or extending DODX. Cost that
honestly; it is the difference between a small change and a real one.

### Volume is the other open question

At 0.5s, 12 players, two 20-minute halves:

```
2400s / 0.5 = 4800 ticks per half
4800 × 12 players = 57,600 rows per half
× 2 halves × 3 matches = ~350,000 rows for one evening
```

That is per *match night*, on a database that also carries every frag. The
plan should decide between a row per tick, write-time aggregation (per player
per point per N seconds), or in-memory accumulation with only the totals
persisted. Phase 6's damage ledger raises the identical question — settle them
together, and note that the answer there was "measure the real volume from a
Lane B run before sizing anything".

---

## How to validate — the part most likely to be skipped

A scoring change of this size cannot be argued into correctness. Three tests,
in increasing order of what they prove:

1. **Predict-accuracy against match winners.** The existing harness does this;
   the bar is 77.8%. A model that scores below that needs a very good story.
2. **Rank stability / sensitivity.** `KTPR_KNOBS.md` records rho and
   "players moving ≥3 ranks" per knob. Any new knob needs the same treatment,
   or it will be tuned by vibes.
3. **Does it rank players the way people who watched the game would?** This is
   the only test that actually matters and the only one that needs humans.
   The other two can both be satisfied by a model that is subtly wrong.

**Lane B can now produce the fixture for 1 and 2.** `scripts/lane_b_match_series.py`
plays full KTP-shaped matches — two halves, sides swapped, one `match_id`
spanning both — and dumps the resulting database. See
`tests/e2e_stats/README.md`. Caveats to inherit: every fixture is
`dod_anzio`-shaped (no other KTP map has bot waypoints yet), the players are
bots, and a run carries ~17 players rather than the 12 named ones.

---

## Sequencing

This sits **after** Phases 5-8 of `IMPLEMENTATION_PHASES.md`, not instead of
them:

- Phase 5 (frag context) and 6 (damage ledger) produce inputs this consumes
- Phase 7 (break context: contester count, capout, last-flag defence) is
  *most* of the state vocabulary this needs
- Phase 8 wires `ktpr_mcp` to read event rows at all

Designing an accumulation model over data that does not exist yet risks
specifying inputs nobody will build. A reasonable plan might instead
**propose what Phase 7 should capture** so that this becomes possible later —
that is a much cheaper intervention than a parallel rating project.

## What not to do

- **Do not replace the existing profiles.** `weights.toml` keeps `old` and
  `current` frozen deliberately so redesigns can be compared against them. Add
  a profile; do not edit theirs.
- **Do not assume the 0.5s poll rate.** It was chosen for break detection
  (`KSC_BREAK_WINDOW` is 5 polls ≈ 2.5s). A rating tick may want to be much
  coarser, and coarser is cheaper.
- **Do not design the heatmap first.** Position-at-tick is the most
  attractive part of the idea and the least load-bearing for a *rating*.
  Occupancy and contest state carry the value.

## Files to read, in order

| File | Why |
|---|---|
| `docs/ktpr_mcp/KTPR_KNOBS.md` | the current formula, every knob, and the measured sensitivity of each |
| `docs/ktpr_mcp/KTPR_CALCULATION.md` | how the calculation is actually implemented |
| `docs/ktpr_mcp/weights.toml` | the per-action valuations that carry over |
| `docs/ktpr_mcp/KTPR_SPEC.md` §5 | why per-half rates, and the two-telemetry-system gap behind `tw_damage` being distrusted |
| `KTPAMXX plugins/dod/ktp_stats_capture.inc` | the 0.5s zone poll — the natural tick source |
| `docs/ktpr_mcp/IMPLEMENTATION_PHASES.md` | Phases 5-8, which produce the inputs |
| `tests/e2e_stats/README.md` | how to get a fixture to evaluate against |
| `docs/ktpr_mcp/KTPR_IDEA_TICK_ACCUMULATION.md` | the shorter parked note this expands |

## Definition of done for the plan

- [ ] states an accumulation model concretely enough to implement
- [ ] says how it avoids rewarding presence over performance — the `tw_kd` tension
- [ ] lists every input it needs and whether it exists, with a cost for each gap
- [ ] answers the volume question with a number, not an adjective
- [ ] says what it would score on predict-accuracy and how that was measured
- [ ] proposes what Phase 7 should capture, if the answer is "not yet"
- [ ] is explicit about what it would make *worse* — every scoring change
      re-ranks somebody, and a proposal that claims only upside has not been
      thought about hard enough
