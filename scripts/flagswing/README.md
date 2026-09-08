# flagswing-js — reference implementation of `flag_swing_v1`

A dependency-free JavaScript port of the momentum baseline the KTP analytics
pipeline computes for every Day of Defeat match, plus a test suite that pins it
to the Python it was ported from.

## Why this exists

The broadcast overlay wants to draw the momentum curve live, in the browser,
while the analytics pipeline draws the same curve after the fact, in Python. If
the two drift, the overlay is telling the audience a different story than the
match report. This package is the shared definition: port `flagswing.js` into
the React frontend, keep `flagswing.test.js` and `golden.json`, and the live
curve provably matches the pipeline's.

Note that the coefficients are **uncalibrated priors** (as the pipeline's own
envelope says). They are comparative, not absolute probabilities. If the
pipeline recalibrates, `flagCoefficient` / `aliveCoefficient` change and
`golden.json` must be regenerated.

## The model

```
p_allies = sigmoid( flagCoefficient  * (alliedFlags - axisFlags) / flagCount
                  + aliveCoefficient * (alliesAlive - axisAlive) / rosterSize )

sigmoid(x) = 1 / (1 + e^-x)
flagCoefficient = 2.0, aliveCoefficient = 1.0
```

That is the entire metric. Source of truth:
`../flag_swing.py` (this repo, one directory up), `_HalfState.p_allies`,
definition `flag_swing_v1`, `definition_version: 1`.

## Conventions you must reproduce

Each of these is something a from-prose port gets wrong, and each has a test.

| Convention | Python | Why it is easy to get wrong |
| --- | --- | --- |
| `flagCount` is the number of **distinct flag indices seen in the match** | `len(flag_ids)` where `flag_ids` is a `set` of `flag_index` | Tempting to use the number of ownership *changes*, or the map's nominal flag count; a 5-flag map where only 2 flags ever changed hands has `flagCount == 2`. |
| `flagCount` falls back to **5** when no indices were seen | `len(flag_ids) or 5` | A zero denominator is the obvious bug; picking 1 or the roster size as the fallback silently doubles or halves every flag swing. |
| A flag with **no index** still counts | `state.owners[None] = owner` | Rows without a `flag_index` are excluded from `flag_ids` (the denominator) but still stored as an owner (the numerator), so such a match can exceed +/-1 on the flag term. Ported naively it either crashes on a null key or drops the flag entirely. |
| `rosterSize` is **both teams combined** | `len(teams)` over the whole roster | The natural reading is "team size", i.e. 6 in a 6v6. It is 12. Using 6 doubles every frag's swing. |
| Both denominators **floor at 1** | `max(flag_count, 1)`, `max(roster_size, 1)` | Empty roster / no flags is a real state at the top of a half and must yield `0.5`, not `NaN`. |
| Team **1 = Allies, 2 = Axis**; everything else is neutral | `owner if owner in (1, 2) else 0`, `p.get("team") in (1, 2)` | A neutralised flag (owner `0`) counts for *neither* side, it is not "still owned by whoever had it". Spectators and team 0 are outside the roster entirely. |
| A half boundary is a **full reset** | new `_HalfState` per half: `owners = {}`, `alive[pid] = True` for all | Flag ownership is not carried into the second half even though the map layout is the same; sides swap in DoD, so carrying it over inverts the curve. Everyone is alive again. |
| Frags/spawns for **unknown players are ignored** | `if victim in state.alive` | A frag involving someone off the roster (spectator, late connect) must not move the curve. |

Perspective is always the Allies: `p_allies` is `P(Allies win this half)`, and
the Axis value is `1 - p_allies`. The clock is `producer_game_time`.

## Usage

```js
import { FlagSwing } from './flagswing.js';

const swing = new FlagSwing({ flagCount: 5, rosterSize: 12 });
for (const { playerId, team } of roster) swing.setTeam(playerId, team);

swing.setFlagOwner(2, 1);        // flag index 2 captured by the Allies
swing.setFlagOwner(2, 0);        // flag index 2 neutralised
swing.setAlive(playerId, false); // frag
swing.setAlive(playerId, true);  // spawn
swing.resetHalf();               // half boundary

swing.pAllies(); // -> 0.0 .. 1.0, plot this
```

The per-event *swing* the pipeline attributes to players is simply the
difference in `pAllies()` across a single event: read it before, apply the
event, read it after. This module deliberately implements only the baseline;
attribution, cap-credit splitting and the break reel stay in the pipeline.

`flagCount` and `rosterSize` may be omitted: `flagCount` then uses the 5
fallback, and `rosterSize` tracks the number of players passed to `setTeam`
(useful live, where the roster fills in as players connect).

## Tests

```
cd scripts/flagswing
node --test
```

No dependencies, no build step, no jest. Two layers:

1. **Unit vectors** — hand-built states with expected values computed
   independently in Python and pasted as literals, asserted to `1e-9`. Covers
   the degenerate cases: no flags owned, all flags on one side, empty roster,
   one team wiped, the `flagCount` fallback of 5, and both denominator floors.
2. **Golden curve** — `golden.json` holds three ~180-step event streams shaped
   from real matches, where every expected `p_allies` was produced by importing
   and running the *actual pipeline module's* `_HalfState.p_allies`. The test
   replays the same streams through the JS and asserts to `1e-6`. Observed
   cross-language agreement is `2.8e-17`, i.e. exact to double precision.

The golden cases deliberately exercise the traps above: case 2 contains
null-index flags, case 3 is a match whose flag rows carry no index at all, so
its denominator is the 5 fallback. Corrupting the roster convention
(per-team instead of combined) moves the curve by up to `0.094`; hardcoding
`flagCount = 5` moves it by up to `0.209` — the golden test catches both.

## Regenerating the golden file

```
python make_golden.py
```

Standard library only, and needs nothing outside this repo. It imports the
co-located `../flag_swing.py` by path (override with `--source`) and drives
synthetic replay from `match_shapes.json` — 3 small (roster, flag) shapes
committed alongside it, so this is fully reproducible from a clean checkout
and is exactly what CI runs. Re-run whenever the Python definition or its
coefficients change; if the JS then fails, the JS is the thing that is wrong.

To pick a *different* set of shapes from real matches (e.g. after a schema
change makes the current three stale), pass a local Tier-2 prod-reports glob
and `--refresh-shapes`:

```
python make_golden.py --reports "G:\path\to\prod-reports\*.json" --refresh-shapes
```

That overwrites `match_shapes.json` (commit the result) and regenerates
`golden.json` from it. `--reports` is a local analytics artifact, never part
of this repo, and is ignored unless `--refresh-shapes` is also passed —
plain `make_golden.py` never touches it.

## Consuming this from another repo

There is no package registry step. `flagswing.js` is 90 lines with zero
dependencies — the website and the overlay each vendor a copy of the file
directly. When `flag_swing.py` changes here, re-run `make_golden.py` and
`node --test`; a consumer stays in sync by re-copying `flagswing.js` and
noting the `flag_swing_v1` `definition_version` it was copied at.

## Files

- `flagswing.js` — the implementation (ES module, ~90 lines, browser + Node).
- `flagswing.test.js` — `node --test` suite, both layers.
- `golden.json` — 546 state/expectation steps produced by the Python.
- `match_shapes.json` — the 3 (roster, flag) shapes `golden.json` is built from.
- `make_golden.py` — regenerates `golden.json` from `match_shapes.json` + the Python.
