# KTPR Knobs — Calculation & Tuning Reference

Scope: this covers the **active `[profiles.new]` "team" formula** — the one every
current report is generated from (`kill_exp = 0.65`, `tw_kd = 3.00` as of
2026-08-08). The legacy Excel formulas (`old`, `current`) and the additive
`artifact` formula use a different, simpler set of knobs — see `KTPR_SPEC.md`
§§2-3 for those. Full design rationale for the team formula is `KTPR_SPEC.md`
§4; this file is the knob-by-knob reference for *what each number does and
what happens when you move it*.

---

## 1. The calculation

For each player, every stat is first converted to a **per-half rate**
(kills/half, deaths/half, etc. — see `KTPR_SPEC.md` §5 for why per-half, not
per-match or season-total). The formula then runs in four steps:

**Step 1 — normalize each stat to a ratio, 1.0 = the median regular player**

```
R(x, median) = clamp((x + k) / (median + k), ratio_floor, ratio_cap)
```

Applied to kills, assists, damage, flags, breaks, and K/D. `median` comes from
the **regular-player pool** (see `part_floor` below), and — if
`class_normalize` is on — from players in the *same role* specifically, not
the whole field. Deaths are handled separately (step 3), not clamped here.
`k` (added 2026-08-08, via `break_smooth_k`) is 0 for every stat except
breaks — see §2.

**Step 2 — combine into one score, low-kill players get a support boost**

```
kill_term   = R(kills)  ** kill_exp
amp_d       = clamp(1 + dmg_interaction    * (1 - R(kills)), dmg_scale_min, dmg_scale_max)
amp_a       = clamp(1 + assist_interaction * (1 - R(kills)), dmg_scale_min, dmg_scale_max)
dmg_term    = R(damage)  * amp_d
assist_term = R(assists) * amp_a

score = ( tw_kill*kill_term + tw_kd*R(kd) + tw_assist*assist_term
        + tw_damage*dmg_term + tw_flag*R(flags) + tw_break*R(breaks) )
        / (tw_kill + tw_kd + tw_assist + tw_damage + tw_flag + tw_break)
```

This is the core design choice of the whole formula: contributions **add**
into a weighted average rather than **multiplying** (as the old Excel
formulas do). A low-kill player isn't crushed by one bad term — their
assist/damage/flag/break terms carry them, and the `amp_d`/`amp_a`
amplifiers make that lift bigger specifically when kills are low (a
low-kill, high-damage player is telling you something the kill count alone
missed).

**Step 3 — death adjustment (normalize, don't punish — and don't punish aggression)**

```
rx        = deaths/median_deaths
adj_rx    = rx / (1 + death_kill_relief * max(0, kill_ratio - 1))
death_adj = 1 - clamp(death_w * (adj_rx - 1), -team_death_up_cap, death_cap)
```

Below-median deaths give a small *bonus* (death_adj > 1); above-median deaths
give a small, capped *penalty*. `death_kill_relief` (added 2026-08-08) softens
that penalty specifically for players whose kills are also above median —
dying while fragging above the pack is pushing, not failing — and never
touches it for below-median killers, so passive players get no extra pass.
See §2. Not clamped through `R()` — it's a direct
ratio, capped asymmetrically (small upside, small downside).

**Step 4 — scale, role float, and final-standing boost**

```
team_boost = 1 + team_placement_weight * (n_teams - placement) / (n_teams - 1)
KTPR = scale * score * death_adj * role_weights[role] * team_boost
```

`scale=1.00` means an exactly-average player across every dimension scores
KTPR ≈ 1.0. `team_boost` (added 2026-08-08) is 1.0 for a team with no listed
placement, or when `team_placement_weight` is 0 — see §2 below.

---

## 2. Every knob

### Global

| Knob | Value | What it does | Turn it up | Turn it down |
|---|---|---|---|---|
| `scale` | 1.00 | Final multiplier on every player's score. | Whole board's numbers inflate (cosmetic only — ranking unchanged). | Whole board deflates (cosmetic only). |
| `part_floor` | 0.34 | Floor on the "regular player" participation threshold. Actual threshold = `max(part_floor, 0.66 × most-matches-played-by-anyone)`. Regulars are the pool medians are computed from, and the pool `team_impact`'s replacement value is drawn from. | Fewer players count as "regular" — medians drawn from a smaller, more elite pool; more low-match players get excluded from baseline-setting. | More players (including casual/low-match ones) count as regular, pulling medians down toward a more casual baseline. |

### Kill compression

| Knob | Value | What it does | Turn it up | Turn it down |
|---|---|---|---|---|
| `kill_exp` | 0.65 | Exponent on the kill ratio. `1.0` = linear (raw kill volume counts fully); `<1` compresses high-volume fraggers toward the pack (diminishing returns). | Toward 1.0: fraggers get more credit for volume, ratings spread out more by kill count. | Toward 0: kills matter less in absolute terms, support/efficiency stats matter proportionally more. **Measured**: moving 0.80→0.65 (the 2026-08-08 change) fixed a real bias — ßℓυ†н was ranking #2 by team KTPR on a 50% win rate while NATO sat at #6 on 75%; stronger kill-compression corrected the ordering. Team-vs-win-rate Spearman rho 0.830→0.891, stable across the whole 0.55-0.65 range, **zero** individual-player rank disruption (max KTPR delta 0.007 across all 61 players). Sensitivity report: rho 0.9999 at ±10% (essentially insensitive at small perturbations — the 2026-08-08 move was a large, deliberate step, not something that drifts on its own). |

### Contribution weights (relative importance of each stat)

All six divide by their sum, so only *relative* size matters, not absolute scale.

| Knob | Value | What it does | Turn it up | Turn it down |
|---|---|---|---|---|
| `tw_kill` | 1.00 | Weight on raw kill volume (`kill_term`). | Fraggers rate higher. | Fraggers rate lower relative to support players. Sensitivity: rho 0.9999 (low). |
| `tw_kd` | 3.00 | Weight on K/D **efficiency** (not volume) — rewards players who frag without dying much, even with low support stats. | Efficient, low-death fraggers pull further ahead. | Efficiency matters less; a low-K/D player with good support stats can compete more easily. **Measured**: 1.50→3.00 (2026-08-07) was the single biggest lever in the tuning history — fixed KTPR predicting match winners *worse* than a naive K/D-ratio baseline (70.4% tie). At 1.50, ßℓυ†н (6-6 record, 0.96 team K/D) rated the tournament's #1 team ahead of iH.hildebrand? (10-1, 1.32 K/D); at 3.00 that inverted correctly. Predict-accuracy 70.4%→77.8%. **Most sensitive knob in the formula** at ±10% (rho 0.9987, 1.5 players move ≥3 ranks on average) — small changes here move the board more than any other knob. |
| `tw_assist` | 1.00 | Weight on the (amplified) assist term. | Support/assist-heavy players rate higher. | Assists matter less. Sensitivity: rho 0.9995 (low). |
| `tw_damage` | 0.50 | Weight on the (amplified) damage term. Lowest base weight of the six — damage is the noisiest/least-trusted HUD stat (see `KTPR_SPEC.md` §5 on the two-telemetry-system gap). | Damage-heavy playstyles rate higher. | Damage matters less. **Least sensitive knob measured** — rho 1.0 at ±10% (literally zero rank movement in testing). |
| `tw_flag` | 0.70 | Weight on objective (flag capture) contribution. | Objective players (flaggers) rate higher relative to fraggers. | Objective play matters less. Sensitivity: rho 0.9996 (low). |
| `tw_break` | 1.00 | Weight on cap-break contribution — "valued highly per design" (breaks are rare and disruptive, worth a full kill-sized weight). | Break-heavy players get a bigger lift. | Breaks matter less. Sensitivity: rho 0.9987, 2.0 players move ≥3 ranks — **second-most sensitive knob**, because breaks are a low-count/high-variance stat (a single extra break is a bigger relative swing than a single extra kill). |

### Low-kill amplifiers

Reward damage/assists *more* specifically when a player's kill count is
below the pack — the idea being their damage/assist numbers are revealing
contribution the raw kill count didn't capture.

| Knob | Value | What it does | Turn it up | Turn it down |
|---|---|---|---|---|
| `dmg_interaction` | 1.20 | How strongly low kills amplify the damage term. `amp_d = 1 + dmg_interaction*(1-kill_ratio)`, clamped to `[dmg_scale_min, dmg_scale_max]`. | Low-kill/high-damage players get a bigger boost. | Damage counts more "flat," less situationally. **Measured**: found *not* to matter in the 2026-08-07 search — the whole 0.0-1.5 range scored identically once `tw_kd`/`assist_interaction` were fixed; current value is inherited, not independently re-validated. Sensitivity: rho 0.9999 (low). |
| `assist_interaction` | 0.60 | Same idea, for the assist term. | Low-kill/high-assist (pure support) players get a bigger boost. | Support play counts more "flat." **Measured**: 1.20→0.60 (2026-08-07, same pass as `tw_kd`) — halving this was part of fixing the ßℓυ†н-overrated-vs-iH problem; the assist amplifier had been letting a support-heavy, sub-1.0-K/D team outrate a dominant-K/D team. Sensitivity: rho 0.9999 (low at small perturbations — the 2026-08-07 move was a large deliberate step). |
| `dmg_scale_min` | 0.60 | Floor on both amplifiers — even a high-volume fragger's damage/assist credit can't be reduced below 60% of normal. | Amplifier range widens on the downside (high fraggers penalized more on damage/assist credit). | High fraggers keep more of their damage/assist credit regardless of kill volume. |
| `dmg_scale_max` | 2.50 | Ceiling on both amplifiers — a zero-kill player's damage/assist credit can't exceed 2.5x normal. | Low-kill specialists can get a bigger support-stat lift. | Caps how much a pure-support playstyle can be rewarded. |

### Per-role float

| Knob | Value | What it does | Turn it up | Turn it down |
|---|---|---|---|---|
| `role_weights` | all 1.00 (neutral) | Final flat multiplier per role (`Rifle`/`Sniper`/`Heavy`/`SMG`), applied *after* everything else. A tuning pass explored `Heavy = 1.05` (gently floating Heavies up) but it was reset to neutral — not currently active. | Elite members of a boosted role gain the most in absolute KTPR (multiplicative on an already-high score). | Elite members of that role lose the most. |

### Ratio clamping (applies to every `R()` term)

| Knob | Value | What it does | Turn it up | Turn it down |
|---|---|---|---|---|
| `ratio_cap` | 2.50 | No single stat-ratio (kills, assists, damage, flags, breaks, K/D) can contribute more than 2.5x the median. Tames noisy/rare stats — especially breaks, where one player having 6 in a tournament of median ~2 would otherwise dominate. | Outlier performances (e.g. a huge break night) count for more. | Outlier performances get capped harder, formula rewards consistency over spikes. |
| `ratio_floor` | 0.55 | No single stat-ratio can drag a player below 55% of the median. Lets a one-dimensional specialist (elite K/D, weak everywhere else) still reach the top instead of being crushed by their weak dimensions — "normalize, don't punish." | Weak dimensions hurt less; specialists float up more. | Weak dimensions hurt more; well-rounded players are rewarded relative to specialists. |
| `break_smooth_k` | 0.50 | Adds a constant to both sides of the **breaks ratio only**: `(x+k)/(median+k)`. Breaks have a near-zero median (~0.08-0.4/half), so `ratio_cap`/`ratio_floor` alone weren't enough — a modest absolute break count was still enough to hit the 2.5x cap and let that one term outweigh a player's real leads on every other stat combined. | Toward 0: breaks behave like every other stat, ratios explode from small absolute counts (the pre-2026-08-08 behavior). | Higher k: breaks matter less no matter how many a player gets — at very large k the stat is effectively neutralized. **Measured (2026-08-08, user-reported bug)**: fixed 3 confirmed cases (TillJim/element, steve/"s i k") where a break-ratio swing decided a ranking despite the "loser" leading on kills, K/D, damage, assists, and/or flags. Fully flips 2 of 3; narrows the third (TillJim/element) from a 19.7% KTPR gap to 7.2% (TillJim keeps a smaller, legitimate lead from real assist production). Costs a little `predict_accuracy` on its own (77.8%→74.1%) — some break-inflated ratings had coincidentally correlated with match wins; a real, expected trade-off for a correctness fix. Rank impact: Spearman rho 0.945 vs. pre-change weights, 21/61 players moved ≥5 ranks — more disruptive than any single prior knob, but this is fixing a pervasive mechanism (every high-break player was overrated, every low-break player underrated), not chasing noise. |

### Team placement boost

| Knob | Value | What it does | Turn it up | Turn it down |
|---|---|---|---|---|
| `team_placement_weight` | 0.15 | Max multiplicative boost for finishing 1st place; 0 = off (the default before 2026-08-08). Linear taper to +0% at last place: `1 + weight * (n_teams - placement) / (n_teams - 1)`. Applied as a final per-player multiplier, same stage as `role_weights`. | Placement matters more — a champion team's roster gets a bigger uniform lift regardless of individual stats. | Placement matters less; KTPR reverts toward a pure individual-stats rating. |
| `team_placements` | `{NATO:1, iH:2, dice:3, Bluth:4, JTM:5, bb:6, NoSo:7, $:8, b:9, uR:10}` | The actual final tournament standings (not round-robin win rate, which can diverge — NATO won the LAN outright despite iH having the better round-robin record). Source of truth is external; there's no bracket/playoff data in the DB to derive this from. | — | — |

Added 2026-08-08 per request — a team's actual tournament finish previously
had zero connection to any individual player's rating. **Untested starting
value** (like `role_weights` originally was) — there's only one LAN's worth
of placement data, so this can't be leave-one-out validated the way the core
contribution weights were. Using it in `predict_accuracy` is partly circular
(it bakes in outcome information the match log itself produced) — see the
caveat at the top of `predict_accuracy.md`.

### Death handling

| Knob | Value | What it does | Turn it up | Turn it down |
|---|---|---|---|---|
| `death_w` | 0.20 | Weight on the raw (deaths/median − 1) term before capping. | Deaths matter more, in both directions (bigger penalty above median, bigger bonus below). | Deaths matter less. Sensitivity: rho 0.9996 (low). |
| `death_cap` | 0.15 | Max penalty (15% of score) for high deaths, however far above median. | Reckless/high-death players can be hurt more. | High-death players are protected from a larger penalty. |
| `team_death_up_cap` | 0.10 | Max bonus (10% of score) for low deaths, however far below median. | Careful/low-death players can be rewarded more. | Low-death play gives less of a bonus. |
| `death_kill_relief` | 1.50 | Softens the death-rate used in the penalty calc for **above-median killers only**: `adj_rx = rx / (1 + relief*max(0, kill_ratio-1))`. DoD-specific reasoning: a player dying often *while* fragging above the pack is pushing/being aggressive, not failing — the raw death-rate penalty didn't distinguish that from a low-kill player dying for nothing. `max(0, ...)` floors the relief at zero, so below-median killers are completely untouched — this only ever *reduces* punishment, never adds it. | More relief for any above-median killer, scaling with how far above median their kills are. At high values, an elite fragger's death penalty can flip into a small bonus. | Less relief; toward 0, behaves like the pre-2026-08-08 raw death-rate penalty regardless of kills. |

### Within-class (role) normalization

| Knob | Value | What it does | Turn it up / on | Turn it down / off |
|---|---|---|---|---|
| `class_normalize` | `true` | When on, every `R()` ratio is computed against the median of the player's **own role**, not the whole field — so a great Sniper is judged against other Snipers (who naturally produce fewer assists/flags than Rifles), not punished for their role's shape. | — (boolean) | Off: everyone judged against one global median regardless of role; role-shape differences (e.g. Snipers naturally flag less) start looking like weakness instead of role identity. |
| `class_min_size` | 4 | Minimum regulars in a role before its own median is trusted; below that, falls back to the global regular-pool median (too few Snipers to form a stable median, for instance). | Fewer roles get their own baseline (more fall back to global). | More roles get their own baseline even with a thin sample (noisier per-role medians). |

---

## 3. How the pieces interact

- **`ratio_floor`/`ratio_cap` bound every term** in step 1 — they're the
  first thing applied, before weights or amplifiers, so they set the outer
  bounds every other knob operates within.
- **`class_normalize` changes what "median" means** for every `R()` call —
  it doesn't change the formula shape, just which population the medians in
  step 1 are drawn from.
- **`role_weights` and `team_placement_weight` are the last things applied** —
  strict multipliers on the fully-computed score, applied in that order, so
  they move everyone in that role/team by the same percentage regardless of
  their other stats.
- **The six `tw_*` weights only matter relative to each other** (they divide
  by their own sum) — doubling all six simultaneously does nothing.
- **`break_smooth_k` only affects the breaks ratio** — every other stat's
  `R()` call still uses `k=0`.

## 4. What's actually been validated vs. what's inherited

Five knobs have real empirical backing from leave-one-out match-prediction
testing or a concrete, reproducible user-reported bug: `tw_kd` (1.50→3.00)
and `assist_interaction` (1.20→0.60) from the 2026-08-07 pass, `kill_exp`
(0.80→0.65) from 2026-08-08, `break_smooth_k` (0→0.5) from a 2026-08-08
bug report (3 confirmed cases where a near-zero-median stat's ratio decided
a ranking over players ahead on every other dimension), and `death_kill_relief`
(0→1.5) from a follow-up 2026-08-08 report (aggressive high-kill/high-death
players were penalized the same as low-kill/high-death ones). The last of
these is the cleanest change in the whole tuning history — Spearman rho
0.993 vs. the pre-change weights, only 2/61 players moved ≥5 ranks — because
it's precisely targeted (only fires for above-median killers) rather than a
blanket reduction. Everything else in
the "Contribution weights" and "Low-kill amplifiers" sections is either an
untested inherited default or was explicitly found *not* to matter in the
08-07 search (`dmg_interaction`, tested 0.0-1.5, all scored identically).
`team_placement_weight` is a deliberate, requested design addition (not a
bug fix) with **no validation methodology at all** yet — a single LAN's
placement data can't be leave-one-out tested. An exhaustive 16-knob search
on 2026-08-08 found no further combination beats 77.8% prediction accuracy
(the pre-break-smoothing baseline) without unacceptable ranking disruption —
see `predict_accuracy.md` / `KTPR_SPEC.md` §6b for the full tuning history
and the negative results (median/map-adjusted team strength, the rejected
smooth-loss overfit candidate) that ruled out further changes to the
*original* six contribution weights specifically.
