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

## Colleague feedback (2026-08-12): additional signal ideas

A second colleague reviewed the point-accumulation idea and raised nine more
candidate inputs, independent of whether the final system ends up
tick-accumulated or stays event-counted. **Treat these as ideas to weigh in
the plan, not a requirement list** — the plan should say which are worth the
capture cost and which are not, the same way the tension section above asks
for `tw_kd` vs. presence to be argued, not assumed.

For each, this table says what would have to be captured that is not today,
so the plan does not have to re-derive it:

| Idea | What it needs captured | Status today |
|---|---|---|
| Win/loss weighted by opponent strength | a per-team or per-opponent skill estimate at match time, to weight a win over a stacked team above a win over a weak one | **not captured** — no opponent-strength signal exists; would need a rating-at-match-time snapshot, which is circular with KTPR itself and needs care (rate players using a rating derived from the same players' rating) |
| K:D | — | **already the model's biggest lever** (`tw_kd`, see above); this is not new work, just confirms the direction |
| Flag-cap weighting: mine vs. enemy's vs. neutral vs. recovering my own, per-map | per-flag-event classification (capturing a neutral point vs. an enemy-held one vs. retaking a lost one) crossed with a per-map value table | **not captured** — `flag_cap` today is one undifferentiated action; the doc's own warning applies ("this could get complicated") — recovering your own point and taking a neutral one are different plays and DoD's `dod_control_point_captured` forward does carry `old_owner`, so the raw signal exists (see KTPAMXX CHANGELOG's territorial-scoring-clock entry, which documents `old_owner` semantics), the gap is in what the capture layer does with it |
| Nade kills vs. gun kills | none — **already there** | `hlstats_Events_Frags.weapon` is populated on every kill today; splitting nade (`hand_grenade`, `riflegrenade`, etc.) from gun weapons is a query-time classification, not a new capture. Cheapest item on this list |
| Class-weighted scoring | per-kill (or per-life) DoD class of the player | **not captured anywhere** — no class capture exists in `ktp_stats_capture.inc` or the schema. DoD exposes class via the player entity; this is a real gap, not a query-time fix |
| Map-weighted kills / K:D | a per-map difficulty or role-value table | **not captured** — `hlstats_Events_Frags` already carries the map per event (standard HLStatsX), so the join key exists; what's missing is the weight table itself, which is a design/tuning artifact more than a capture gap |
| Capouts | a distinct capout event, separate from a contested capture | **Phase 7** in `IMPLEMENTATION_PHASES.md` — already planned, not yet built |
| Cap breaks: differentiate a body block from a kill-break | break *mechanism* (killed the capturer vs. simply stood in the zone and denied progress without a kill) | **partially not captured** — `cap_break` today is kill-attributed only (see the KTPAMXX cap-break CHANGELOG entry: "killing an enemy standing on a point... is the only way to stop capture progress" as currently modeled). A body-block-without-a-kill is not a DoD server event in the same sense — worth scoping carefully before committing to it, since it may not be detectable the way a kill-break is |
| % of a player's frags out of the match total (and the same for deaths) | none beyond what exists — **derivable today** | both frags and deaths per player per match are already captured; this is a normalization done at query/scoring time, not a capture gap. Flagged in the source feedback as possibly "the best frag value" — worth an early predict-accuracy check since it's nearly free to try |

**Two items are free to prototype against the existing corpus** (weapon-type
split, frag/death share) — they need no new capture, just a query over data
Lane B's corpus replay (`scripts/replay_corpus.py`, `tests/e2e_stats/corpus/`)
already produces. Worth trying those first as a cheap signal check before
costing the expensive ones (class capture, opponent-strength weighting).

**Two items need new capture work before they can be evaluated at all**
(class, capout-vs-contested-capture) — same category as the tick-accumulation
idea itself: don't design the scoring around them until Phase 7 (or a
class-capture equivalent) lands.

**One item (opponent-strength-weighted win/loss) has a circularity to solve**
before it's even a capture question: weighting a win by the opponent's KTPR
means using KTPR to rate KTPR inputs. That needs its own design note on
which rating snapshot to use (pre-match, rolling, or season) — flag it to
the plan's author rather than letting it get waved through as "just weight
by opponent skill."

## More backlog ideas (2026-08-12, same source)

A follow-up batch from the same colleague, again independent of tick-
accumulation vs. event-counting:

| Idea | What it needs captured | Status today |
|---|---|---|
| Throwback nade kills (killing with a live grenade caught and thrown back) | grenade-entity ownership tracking — who threw it originally, and whether it changed hands before detonating | **not captured, and not cheap** — this is not a log line DoD emits; it needs tracking individual grenade entities across a possible catch-and-return, which is a real engine-level capture project, not a query or a small hook. Scope before committing |
| Last-flag full caps completed | a distinct "this was the game-deciding flag" marker on a capture | **not captured** — depends on Phase 7's capout work and on the plan knowing which flag is "last" per map (asymmetric in DoD; not always the numerically-final one). Couples to the map-layout gap already tracked in `tests/e2e_stats/NEXT_PHASES.md` (KTP maps have no waypoints yet, which blocks more than just bots — any per-map "which flag is last" table needs the same map-by-map work) |
| Enemy-flag caps vs. recaptures of your own 1st/2nd flag ("double caps") | capture classification by prior ownership, i.e. the same `old_owner` signal flagged under the flag-cap-weighting idea above | **not captured**, same gap as the earlier flag-cap-weighting row — this is really that idea's central example, not a separate one. The colleague's intuition (recapturing your own early flag may be close to half of some players' total on some maps and is lower-impact) is exactly the kind of thing worth checking empirically once `old_owner` is captured, before weighting anything |
| Total nades thrown | a grenade-throw event, which does not exist in capture today | **not captured** — DoD logs a throw distinctly from a detonation/kill; this is a new, fairly cheap hook (one event type, no attribution ambiguity) compared to the throwback-kill idea above, which needs the same underlying entity but a lot more logic on top |
| Time spent holding forward ("holding W") | continuous per-tick input or movement-vector sampling | **not captured, and the cheapest-sounding one is a trap** — DoD's server does not expose client input state (which key is held) directly; the closest proxy is inferring movement from position deltas between polls, which conflates walking, running, being pushed by an explosion, and knockback. Flag this to the plan's author as needing a validated proxy before it is trusted as a signal, not a straightforward capture |

## Baseline signal set (2026-08-12, same source) — confirms the core, not new ideas

A third round from the same colleague, but this one is different in kind from
the two batches above: it names the **basic** signals a scoring system should
be built on, not a novel idea to scope. Frags (total or per-match), K:D,
assists, breaks, flags, damage. None of this is new information to this
project — it is exactly `KTPR_KNOBS.md`'s existing six-term weighted average
(kills, K/D, assists, damage, flags, breaks) — so the useful reading of this
feedback is as **confirmation that the existing core is the right core**, not
as a request to build something new. Worth stating plainly to whoever plans
future work: the fancier ideas in the two sections above are refinements on
top of this set, not replacements for it.

### Damage should be capped per hit before it feeds any stat — read before Phase 6 ships a raw column

**This one is not a someday idea — it is a capture-time design decision, and
Phase 6 (the per-hit damage ledger) is being built right now.** DoD's engine
damage values are the *nominal* weapon value with multipliers applied
(headshot, wallbang/penetration, etc.) — they are not clamped to a player's
actual HP pool (0-100) the way a kill's real effect is. A single hit can
carry a logged value like 400 even though the target had at most 100 HP to
lose. Un-capped, that number does not mean "how much this hit mattered" — it
means "how strong this weapon+hitzone combination is on paper," which is a
different, less useful quantity for a per-player rating. CS2 caps logged
per-hit damage at 100 for exactly this reason.

**Design decision made in Phase 6** (see the phase's own section below for
the implementation): capture the raw engine value *and* a capped value
side by side, rather than choosing one. Raw is kept because this project's
standing rule is never to discard a real reading (the same principle behind
storing `k_prone` un-collapsed in Phase 5, and omitting rather than
fabricating a failed position read) — some future consumer may legitimately
want to know a wallbang connected for absurd values, or may want to compute
overkill. But **any KTPR-facing stat should read the capped column, not the
raw one** — a rating that summed raw damage would let one absurd wallbang
distort a player's rating more than three clean kills, and that is not a
real signal about how the player performed.


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
- [ ] addresses the colleague-feedback ideas above — which are worth
      prototyping now (weapon-type split, frag/death share), which need new
      capture first (class, capout-vs-contested), and whether
      opponent-strength weighting is worth its circularity cost
