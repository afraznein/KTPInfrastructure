# KTPR Calculation — Detailed Walkthrough

How a KTPR number is actually produced, end to end, for the live **team**
formula (`[profiles.new]`). Companion to
[KTPR_KNOBS.md](KTPR_KNOBS.md) (what each knob does) and
[KTPR_SPEC.md](KTPR_SPEC.md) (data model & scope).
Reflects the weights as of **2026-08-08** (`kill_exp 0.65`, `tw_kd 3.00`,
break smoothing, death relief, and the placement boost all live).

---

## 0. The idea in one paragraph

KTPR rates a player by **how their per-half contribution compares to a typical
player in their role**, across six dimensions — kill volume, kill efficiency
(K/D), assists, damage, flag captures, and cap-breaks — blended into a single
weighted average, then nudged by their death rate and their team's final
standing. Because the dimensions are **added**, a player who is quiet on kills
but strong on assists/objectives is carried by those terms; a one-dimensional
star is pulled toward the middle.

---

## 1. Inputs

Per player, aggregated over the tournament matches (Sat/Sun `match_type=0`), all
expressed **per half** (one match = two halves):

| Stat | Source | Notes |
|---|---|---|
| kills, deaths, K/D | **HLstatsX** frag log | authoritative; K/D = kills ÷ deaths |
| flags (captures) | **HLstatsX** actions | objective |
| assists, damage, cap-breaks | **HUD** | the newer stats |

(See KTPR_SPEC §5 for why the two systems and how identities are matched.)

---

## 2. The six-step calculation

### Step 1 — Baselines (what "average" means)

Compute the **median of each stat over the "regulars"** — players who played
enough matches (`matches ≥ max(part_floor, 0.66 × max_matches)`). With
`class_normalize = true`, medians are taken **within each role** (Rifle / Sniper
/ Heavy / SMG), so a player is measured against peers who play the same way. A
role needs ≥ `class_min_size` regulars to get its own baseline, else it falls
back to the global median.

### Step 2 — Ratios (compare to baseline, then clamp)

Each stat becomes a ratio to its role median, clamped to `[ratio_floor,
ratio_cap]` = `[0.55, 2.50]`:

```
rk  = kills/half   ÷ median      rkd = K/D          ÷ median
ra  = assists/half ÷ median      rd  = damage/half  ÷ median
rf  = flags/half   ÷ median      rx  = deaths/half  ÷ median  (NOT clamped)
rb  = (breaks/half + k) ÷ (median + k)     k = break_smooth_k = 0.50
```

`1.0` = exactly average for the role. The **floor (0.55)** means being weak in
one stat can't tank you (a specialist survives); the **cap (2.50)** means one
freak stat can't hijack the score.

**Breaks get the extra `k` because the cap alone wasn't enough.** The break
median is near zero (~0.08 for Snipers, ~0.23 for Rifles), so a plain ratio
turned a couple of extra breaks into a pinned 2.50 that outweighed a player's
real leads everywhere else. Adding 0.50 to both sides pulls break ratios toward
1.0 without capping the stat out of existence — see the bR0M example below,
where it moves the break term from 2.04 to 1.33.

### Step 3 — Shape the kill & support terms

- **Kills get diminishing returns:** `kill_term = rk ^ kill_exp` (exp `0.65`).
  A huge fragging night is compressed toward the pack rather than dominating.
- **Damage & assists are amplified when kills are low** (they reveal
  contribution the kills didn't capture) and dampened when kills are high (that
  damage is already implied by the kills). **The two use different strengths** —
  damage bends harder than assists:
  ```
  amp_d = clamp(1 + 1.20 × (1 − rk), 0.60, 2.50)     dmg_interaction    = 1.20
  amp_a = clamp(1 + 0.60 × (1 − rk), 0.60, 2.50)     assist_interaction = 0.60
  damage_term = rd × amp_d        assist_term = ra × amp_a
  ```
  At an average kill rate (`rk≈1`) both amplifiers ≈ 1 (no effect); they only
  bend the score for players well above/below the kill baseline.

### Step 4 — Weighted average → `score`

Blend the six contributions by their weights and divide by the weight total
(so `score` stays on the "1.0 = average" scale):

```
score = ( tw_kill·kill_term + tw_kd·rkd + tw_assist·assist_term
        + tw_damage·damage_term + tw_flag·rf + tw_break·rb ) / (Σ tw_*)
```

Current weights: `tw_kill 1.0, tw_kd 3.0, tw_assist 1.0, tw_damage 0.5,
tw_flag 0.7, tw_break 1.0` → Σ = **7.20**. `tw_kd` at 3.0 makes kill
*efficiency* the single heaviest input — it alone is 42% of the weight total.

### Step 5 — Death adjustment (gentle, and aggression-aware)

```
adj_rx    = rx ÷ (1 + death_kill_relief × max(0, rk − 1))    relief = 1.50
death_adj = 1 − clamp( death_w × (adj_rx − 1), −team_death_up_cap, death_cap )
          = 1 − clamp( 0.20 × (adj_rx − 1), −0.10, +0.15 )
```

A high-death player loses at most 15%; a low-death player gains at most 10%.
(K/D already accounts for deaths once via `tw_kd`; this is a softer second nudge.)

`death_kill_relief` discounts the death rate for players who are *also* fragging
above their role median — dying while pushing is aggression, not failure. It
only ever softens: `max(0, rk − 1)` is zero for below-median killers, so a
passive player gets no relief and never gets extra punishment.

### Step 6 — Role multiplier and placement boost → KTPR

```
team_boost = 1 + team_placement_weight × (n_teams − placement) ÷ (n_teams − 1)
KTPR = scale × score × death_adj × role_weight[role] × team_boost
```

`scale = 1.0` and all `role_weights = 1.0` currently. `team_placement_weight`
is 0.15 across 10 teams, so the boost runs from **1.15 (1st place) down to
1.00 (last)** in even steps of 0.0167.

> ⚠️ **The boost breaks the "1.0 = average player" calibration.** Because it
> only ever multiplies *up*, the average player now lands near 1.075 rather than
> 1.0, and a player on a team with no listed placement is scored as if they
> finished last. Read KTPR values as relative rankings, not against the old
> absolute bands, until this is either re-centred or the placement list covers
> every team.

---

## 3. Worked examples (real players)

Inputs below are the per-half stats and role medians as displayed — rounded to
the precision shown — so every line is reproducible from the table itself to
about ±0.01. Both the current and prior values are given, because the
2026-08-08 changes reordered these three players.

### A — "Ace Sharpshooter": hildebrand? (Sniper, iH, 2nd place)

Elite efficiency, little support — the efficiency term carries him, and `tw_kd`
tripling is exactly what he was waiting for.

```
raw/half   K/D 1.69 · kills 23.6 · assists 1.05 · damage 3864 · flags 3.59 · breaks 0.09 · deaths 13.95
Sniper med K 22.69 · KD 1.11 · A 1.11 · D 3576 · F 2.97 · B 0.08 · X 21.64
ratios     rk 1.04 · rkd 1.52 · ra 0.95 · rd 1.08 · rf 1.21 · rb 1.02 · rx 0.64
shape      kill_term 1.04^0.65 = 1.026 ; amp_d 0.95, amp_a 0.98 → dmg_term 1.03, assist_term 0.92
terms      kill 1.026 | kd 4.568 | assist 0.923 | dmg 0.514 | flag 0.846 | break 1.017
score      8.894 / 7.20 = 1.235
death_adj  rx 0.64 → adj_rx 0.61 → 1.078   (biggest single boost available)
boost      2nd of 10 → 1.133
KTPR       1.0 × 1.235 × 1.078 × 1.133 = 1.510      (was 1.259 under the old weights)
```

The `tw_kd·rkd = 4.568` term now dominates outright — over half the weighted
total. His 1.52× role K/D was always the story; at `tw_kd 3.0` the formula
finally says so.

### B — "Ace Flagger": bR0M (Rifle, bb, 6th place)

Average fragger, exceptional on objectives. **The clearest illustration of break
smoothing in the whole doc.**

```
raw/half   K/D 1.10 · kills 24.4 · assists 4.47 · damage 4078 · flags 6.31 · breaks 0.47 · deaths 22.1
Rifle med  K 25.17 · KD 1.05 · A 4.35 · D 4256 · F 3.79 · B 0.23 · X 23.18
ratios     rk 0.97 · rkd 1.05 · ra 1.03 · rd 0.96 · rf 1.66 · rb 1.33 · rx 0.95
shape      kill_term 0.97^0.65 = 0.980 ; amp_d 1.04, amp_a 1.02 → dmg_term 0.99, assist_term 1.05
terms      kill 0.980 | kd 3.143 | assist 1.046 | dmg 0.497 | flag 1.165 | break 1.329
score      8.160 / 7.20 = 1.133
death_adj  rx 0.95 → 1.009
boost      6th of 10 → 1.067
KTPR       1.0 × 1.133 × 1.009 × 1.067 = 1.220      (was 1.296 under the old weights)
```

His 0.47 breaks/half against a 0.23 median used to produce `rb 2.04` — a term
larger than any other single contribution, on a stat where the gap is a
fraction of one break per half. Smoothing pulls it to **1.33**, and his flag
lead (`rf 1.66`) becomes the honest driver of his rating instead.

**This pair reversed.** bR0M previously edged out hildebrand (1.296 vs 1.259);
now hildebrand leads clearly (1.510 vs 1.220). Three changes push the same way:
`tw_kd` rewards hildebrand's efficiency, break smoothing removes bR0M's inflated
term, and iH finishing 2nd to bb's 6th adds the rest. Whether that ordering is
*right* is a judgment call about how much a break is worth — but it's now driven
by four terms instead of one near-zero-median stat.

### C — "Support carries a low-kill player": p12 (Rifle, Bluth, 4th place)

Below-average K/D and *more* deaths than average — yet still lands above the
middle because assists and objectives lift him. This is the whole point of the
additive design, and it survives the reweighting.

```
raw/half   K/D 0.85 · kills 21.9 · assists 6.00 · damage 3757 · flags 4.54 · breaks 0.33 · deaths 25.7
Rifle med  K 25.17 · KD 1.05 · A 4.35 · D 4256 · F 3.79 · B 0.23 · X 23.18
ratios     rk 0.87 · rkd 0.81 · ra 1.38 · rd 0.88 · rf 1.20 · rb 1.14 · rx 1.11
shape      low kills (rk 0.87) → amp_a 1.08, so assist_term = 1.38 × 1.08 = 1.49
terms      kill 0.914 | kd 2.429 | assist 1.487 | dmg 0.510 | flag 0.839 | break 1.137
score      7.315 / 7.20 = 1.016
death_adj  rx 1.11 → 0.978   (a small penalty, not a hammer)
boost      4th of 10 → 1.100
KTPR       1.0 × 1.016 × 0.978 × 1.100 = 1.093      (was 1.113 under the old weights)
```

Note what `assist_interaction` halving did: his assist term dropped from 1.59 to
**1.487**, because the low-kill amplifier that used to bend assists as hard as
damage now bends them half as much (`amp_a 1.08` vs `amp_d 1.16`). He gets no
death relief — `rk 0.87` is below median, so `max(0, rk−1)` is zero, exactly as
intended for a low-kill player.

---

## 4. Reading the output

- Compare the *terms* to see *why* a player ranks where they do (kd-driven vs
  break-driven vs assist-driven) — that's exactly what the **style** label
  summarizes (e.g. "Ace Sharpshooter" vs "Ace Flagger").
- Because everything is role-relative, cross-role comparison is fair: the #1
  sniper and #1 rifle are both "best-in-role," not "whoever's role frags most."
- Absolute-value bands ("elite is above X") are deliberately omitted here. The
  placement boost shifted the whole distribution upward and no re-derived band
  set exists yet — see the warning in Step 6.

---

## 5. The other formulas (for reference)

- **`old` / `current`** — the legacy Excel formulas. *Multiplicative*:
  `KTPR = scale × [min(K/D, 1.1) × (kills/half ÷ median)] × (1 + flag_bonus) ×
  (1 − death_penalty)`. Kills are the core and everything else scales it — which
  is why they can't reward a low-kill player (the core is small, bonuses only
  multiply it). This limitation is what motivated the additive team formula.
- **`artifact`** — an additive average of ratios to the population *mean*:
  `KTPR = [ (K/D/avg) + (kills/avg) + 0.25·(flags/avg) ] / 2.25`. A simpler
  ancestor of the team formula; kept as a comparison datapoint.
- **`new_v1` … `new_v4`** — frozen snapshots of the team formula at each tuning
  step, kept for before/after comparison. The "old weights" numbers in §3 are
  `new_v1`.

---

## 6. Styles (descriptive only)

After scoring, each player gets a `<tier> <archetype>` label:
- **Tier** from KTPR percentile: Ace / Veteran / Regular / Recruit.
- **Archetype** from profile shape vs the *global* median: Sharpshooter, Fragger,
  Flagger, Support, All-rounder, Generalist.

Styles are labels for humans; they do **not** feed back into the KTPR value.
