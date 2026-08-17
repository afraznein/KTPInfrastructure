# Spec: side-balance correction and a KTPR error bar

**For:** an engineer implementing steps S1–S2 of `KTPR_SPATIAL_PLAN.md`.
**Status:** planning only. Nothing agreed, nothing started.
**Why it is first:** it needs **no new data capture**. Everything below runs against the
existing tournament database. It is independent of the spike, the plugin work, and the
phase backlog, and it produces the noise floor that every later tuning decision needs.

---

## What already exists

`compute_side_splits` (`ktpr_engine.py:556-585`), exposed as `side_report`
(`ktpr_mcp.py:205-221`), fed by `load_half_player_stats` (`ktpr_mysql.py:670-730`).

It scores every half-row against **season-wide role medians**
(`_team_baselines(season_players)`, `:563`), groups each player's halves by `.side`, and
reports `side_diff = avg_ktpr_axis − avg_ktpr_allies` per player.

Reported finding (`KTPR_SPEC.md:323-325`):

> **72% of players (44/61) score better on Allies than Axis**, mean `side_diff` −0.053
> across the tournament — "a real, consistent skew worth a look at the map pool/spawn
> balance, not sampling noise."

The side value itself is sound. `.side` comes from `hud_player_stats.team` keyed on
`(steam_id, match_id, half)` (`ktpr_mysql.py:713-717`), so it is the **actual side played
in that half**, not the match slot. `KTPR_SPEC.md:253-259` is explicit that
`ktp_match_players.team` is only a per-match slot and that DoD swaps sides at halftime
without changing the roster-to-slot mapping. The loader gets this right.

**So `σ` — which side a player occupied in a given half — is already available and
already correct.** That is the input the whole spatial plan's depth sign depends on, and
it needs no work.

---

## Two defects in the current estimator

Both are in the *statistics*, not the data.

### D1 — the estimate is unpaired

`compute_side_splits` computes a per-player mean over Allies halves and a per-player mean
over Axis halves, then subtracts. Those two pools come from **different matches**, with
different teammates, different opponents and different maps.

That means `side_diff` absorbs every difference between the matches a player happened to
play Allies in and the ones they happened to play Axis in. With 8–13 matches per player,
scheduling luck alone produces meaningful imbalance.

The data supports a much stronger estimator, because **both halves of a match have the
same players, the same teammates, the same opponents, the same map and the same sitting.**
Differencing within `(player, match)` cancels all of it by construction:

```
Δ_{p,m} = KTPR(p, m, half where p played Allies) − KTPR(p, m, half where p played Axis)
```

Everything that is constant within a match — player quality, teammate quality, opponent
quality, map, patch, mood — cancels exactly. What remains is side effect plus
half-order effect plus noise.

### D2 — half dropout is non-random, and pairing makes it visible

`load_half_player_stats:729-730`:

```python
if side is None:
    continue    # no HUD row for this player/match/half -> can't tell which side
```

Halves with no HUD row are dropped. `DATA_QUALITY.md:7` characterises the divergence
precisely: it is a **half-coverage gap**, and *every divergent player has fewer HUD halves
than HLstatsX halves* — HUD drops half-snapshots.

For the current unpaired estimator this is a silent thinning of one pool. For a **paired**
estimator it is louder and more tractable: a match where only one of a player's two halves
survived contributes **no pair at all**, and you can count exactly how many pairs you lost.

**This is an improvement, not a new problem.** The pairing makes an existing bias
observable. But the drop must be reported, not silently absorbed — see the gates.

---

## S1 — prerequisites

Small, and both are worth doing on their own merits.

### S1a — quantify half coverage

Report, per player and in aggregate: HLstatsX half count, HUD half count, and the number
of `(player, match)` pairs where exactly one half survives. This is a query, not a fix.

**It is a gate, not a chore.** If pair loss is large or correlated with side, the paired
estimator inherits the bias it was meant to remove, and that must be known before any
number is published.

### S1b — fix the dead latency metric

Unrelated to the statistics, but it is the cheapest fix in the entire plan and it removes
the fleet's blindness to `/ingest` saturation.

`ingest.ts:572` reads latency from an `x-plugin-sent-at` **header**. The plugin sends only
`Content-Type`, `X-Auth-Key`, `X-Server-Hostname` (`KTPHudObserver.sma:485-496`) and puts
`plugin_sent_at` in the JSON **body** (`:533`). `metrics.recordLatency` is therefore dead
code on the live path and `avg_latency_ms` is permanently `null`.

Either send the header or read the body. One line.

---

## S2a — the paired side-balance estimator

### Model

For a half-level metric `y`:

```
y_{p,m,h} = μ + α_p + γ_m + β_map · side_{p,m,h} + δ · order_h + ε
```

`α_p` (player quality) and `γ_m` (match context) are nuisances. Difference within
`(player, match)` and they vanish:

```
Δ_{p,m} = ±2·β_map + δ' + noise        # sign determined by which side p started on
```

Multiply by the start-side sign and average to get an unbiased `β̂_map`, free of player
and team quality.

### Procedure

1. Load half rows as `side_report` does today (`load_half_player_stats`, tournament only).
2. Score every half against **season-wide role medians** — reuse
   `_team_baselines(season_players, p)` exactly as `compute_side_splits:563` does. Do not
   compute per-half baselines; the point is that the scale is held fixed.
3. Group by `(steam_id, match_id)`. Keep only groups with **exactly two halves on
   opposite sides**. Count and report everything dropped.
4. Form `Δ`, sign-corrected by start side.
5. Aggregate: pooled `β̂`, and per-map `β̂_map` with a confidence interval.
6. Apply as a pre-normalisation correction: `y_adj = y − β̂_map,side`, *before* the
   values enter `R(x, median)`.

### Sizing

~55 tournament matches over 7 maps is roughly 8 matches per map, ×12 players ≈ 90 pairs
per map before dropout. The **pooled** estimate is very well determined; **per-map**
estimates will be noisy and must ship with intervals. If a map's interval crosses zero,
apply the pooled correction there rather than a per-map one.

### Why it is worth doing

- Mean `side_diff` is 0.053 against a full board range of 1.30 → 0.71 — **~9% of the
  range**.
- The board is dense: ranks 26–30 all score exactly 1.00, and rank 31 scores 0.99.
- Players have 8–13 matches, so side imbalance of 2–4 halves is routine.

A 9%-of-range bias operating on a board that dense is moving real ranks, and it is
currently uncorrected.

### Caveats to honour

- **Sides are not randomly assigned** — knife round, toss, or schedule. Include a
  start-side indicator and check for imbalance. If assignment correlates with team
  strength, `δ` and `β` are entangled.
- **H2 is not exchangeable with H1.** A team down 5–0 at halftime plays differently.
  Include the half-order term `δ`, and record the halftime score as a covariate.
  Precedent exists: `KTPR_SPEC.md` §5 already ran a half-1-vs-half-2 asymmetry check on
  damage for a different reason.
- **Substitutions break pairing.** Drop unpaired player-matches from `β̂` estimation
  rather than half-including them — and report the count (S1a).
- **Do not source side from `ktp_match_end`.** Its `axis_score`/`allies_score` are swapped
  in **100% of the 55 tournament matches** (`KTPR_SPEC.md` §6a). The existing loader
  already avoids this; do not reintroduce it.

---

## S2b — the error bar

The same pairing yields a reliability estimate, which the project currently does not have.

```
r_halves = corr(KTPR_H1, KTPR_H2)   across all paired player-matches
r_full   = 2·r_halves / (1 + r_halves)            # Spearman-Brown
SEM      = sd(KTPR) · sqrt(1 − r_full)
```

Within a match, true player quality is approximately constant, so the residual between
the two halves is measurement noise. That is what separates it from `ktpr_consistency`,
which is reported today as the stdev of per-match KTPR and **conflates true match-to-match
variation with measurement error**.

Compute `r_halves` on the side-**adjusted** values from S2a, or the side effect inflates
the apparent noise.

### Why this matters more than any single new term

The entire tuning literature is denominated in Spearman ρ and "players moving ≥3 ranks"
(`KTPR_KNOBS.md` §2, `SENSITIVITY_SWEEP.md`). Those counts are uninterpretable without a
noise floor.

With `SEM` you can finally say: *`break_smooth_k` moved 21/61 players ≥5 ranks, and the
noise floor is ±N ranks* — turning a judgement call into a measurement. It also speaks
directly to the tier-boundary problem, where the Regular/Recruit cut currently falls
between two players both scoring 0.93.

Convert `SEM` to a rank-equivalent for reporting; "±0.04 KTPR" means less to a reader
than "±3 ranks in the middle of the board."

---

## Shape of the change

Additive. Nothing existing is modified.

| Where | What |
|---|---|
| `ktpr_engine.py` | `compute_side_balance(season_players, half_rows, p)` → per-map `β̂` + intervals + drop counts. `compute_reliability(...)` → `r_halves`, `r_full`, `SEM`, rank-equivalent. |
| `ktpr_engine.py` | Optional `side_adjust` parameter threading `β̂` into the rate computation before `R()`. **Default off.** |
| `ktpr_mcp.py` | Two new tools alongside `side_report`, same `source='mysql'` guard. |
| `ktpr_mysql.py` | Nothing. `load_half_player_stats` already returns what is needed. |
| `weights.toml` | Nothing. This is not a knob and must not become one. |

**Leave `compute_side_splits` in place.** It is the descriptive view and it is cited in
the spec. The paired estimator is a second, inferential function — not a replacement.

**Do not touch `old`, `current`, or `new_v1..v4`.** They are frozen so redesigns can be
compared against them.

---

## Validation

1. **Sign agreement.** Pooled `β̂` must reproduce the direction of the existing finding
   (Allies-favoured, mean `side_diff` −0.053) while being **tighter**, since player and
   match effects are differenced out. A sign flip means an implementation bug — most
   likely the start-side sign correction — not a discovery.
2. **Pair accounting.** Report pairs formed, pairs lost to dropout, pairs lost to
   substitution. Check whether loss correlates with side; if it does, say so and stop.
3. **Predict-accuracy.** Side adjustment should move it **up or neutral**. A drop means
   the correction is absorbing signal rather than bias.
4. **Rank disruption in house format** — ρ and players moving ≥3 ranks, now reported
   *against the new noise floor*, which is the first time that comparison is possible.
5. **Reliability sanity.** `r_halves` should be positive and materially below 1.0. Near
   1.0 means the two halves are not independent — check that season-wide baselines are
   genuinely being reused rather than recomputed per half. Near 0 means either KTPR is
   mostly noise at half granularity or the pairing is wrong; both need investigating
   before anything is published.

---

## What this makes worse

- **Some players lose rank for a reason they will dispute.** A player whose schedule gave
  them more Allies halves will drop. The correction is defensible, but it must be
  explained in terms of the schedule, not the player.
- **Per-map `β̂` on ~8 matches/map is noisy**, and a noisy correction can add variance
  rather than remove bias. Hence the "pooled unless the interval excludes zero" rule.
- **Publishing an error bar makes the board look less authoritative.** It is more honest
  and it will be less popular. Ranks separated by less than the SEM should be presented
  as tied — which is the correct reading of a board where five players score exactly 1.00,
  but it is a visible change.
- **It cannot fix a genuine map-pool imbalance**, only measure and neutralise it in the
  rating. If Allies really are favoured on several maps, the finding belongs to whoever
  sets the map pool, and the correction should not be used to make that problem invisible.

---

## Done when

- [ ] half-coverage and pair-loss numbers published (S1a)
- [ ] `avg_latency_ms` reports a real value (S1b)
- [ ] pooled `β̂` agrees in sign with the existing `side_report` finding and is tighter
- [ ] per-map `β̂` published with intervals, pooled fallback where they cross zero
- [ ] `SEM` published as both a KTPR delta and a rank-equivalent
- [ ] predict-accuracy under side adjustment reported, up or neutral
- [ ] the frozen profiles are untouched
