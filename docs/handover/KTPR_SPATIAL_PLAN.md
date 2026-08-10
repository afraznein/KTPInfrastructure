# Plan: spatial KTPR — positional telemetry as a rating input

**For:** an engineer or AI agent picking this up **after** the current phase backlog merges.
**Origin:** investigation 2026-08-10, expanding `KTPR_TICK_ACCUMULATION.md`.
**Status:** planning only. Nothing agreed, nothing started, no code written.
**Sequencing:** this sits behind Phases 5–8 of `IMPLEMENTATION_PHASES.md`. It is written
now so that when those land, the spatial work is a decision rather than a discovery.

---

## The idea in one paragraph

Rate players partly by *where* they did things, not only *what* they did. Position at
each event is nearly free — kills, damage, caps, breaks and spawns already fire, and the
positions can be attached inside the existing handlers. A low-rate sample stream fills
the gaps between events so that dwell, occupancy and depth are measurable. From that,
define a single side-signed scalar **depth** ∈ [−1, +1] per position, and use it to
**re-price the counts the current formula already consumes** rather than adding a new
presence term.

---

## What changed since `KTPR_TICK_ACCUMULATION.md`

That document parked the idea largely on data availability and transport cost. Three
findings move it.

### 1. Capture-zone geometry needs no C++ change

`dodx_area_get_data(i, CA_edict)` → `get_entvar(ent, var_absmin/var_absmax)` yields the
zone AABB in world coordinates.

- `CA_edict` returns a real Pawn-usable entity index — `modules/dod/dodx/NCP.cpp:283-284`
- ReAPI is the **first** module in every deployed `modules.ini`
  (`config/online`, `config/lan`, `config/local` — only `reapi`, `dodx`, `amxxcurl`)
- `get_entvar` is registered **unconditionally**; only the ReGameDLL-gated
  `ReGameVars_Natives` is stubbed on DoD —
  `branches/KTP-ReAPI/reapi/src/natives/natives_members.cpp:923-930`
- It reads only `edict_t::v`, with `offsetof`-derived offsets — `natives_members.cpp:352-406`

**Do not expose `pd_dca.mins/maxs` via a new `CA_VALUE` key.** Those struct fields are
documented in-tree as wrong: `moduleconfig.cpp:1933-1936` bypasses the pdata origin
offsets because they read as `(0, world_x)` on `dod_anzio`. A C++ change there would ship
known-bad data. The geometry floats sit in the same unvalidated region.

**Residual risk: `get_entvar` has zero in-tree callers on DoD.** See
`SPIKE_ENTVAR_GEOMETRY.md` — one afternoon, and it gates everything below.

### 2. A BSP entity-lump parser already exists

`modules/dod/dodx/moduleconfig.cpp:1689-1897` — `DODX_LoadBSPEntityLump()` and
`DODX_ReadBSPControlPoints()` already load `maps/<map>.bsp`, validate v30, read lump 0,
and run a hardened `{ "key" "value" }` tokeniser with truncation guards, extracting
`classname`, `point_index`, `point_default_owner` and `origin`.

Adding `info_player_allies`, `info_player_axis`, `info_initial_player_allies`,
`info_initial_player_axis` is **more `strcmp` branches in a proven loop**, plus a
Pawn-facing accessor. That yields every spawn origin for both teams at map load.

**This is what makes "own side vs enemy side" objective with no hand-labelling of any map.**

### 3. Sampling only has to cover the gaps — the volume question is closed

Two observations collapse the transport problem:

- **Event positions are free.** Kills, damage, caps, breaks and spawns already fire; the
  forwards already carry both player indices; `dodx_get_user_origin` works on either.
  The production fixture `match-1777342963-NY1` carries 603 kills, 1,086 damage,
  644 spawns and 66 captures — **~2,400 positioned events per match at zero added
  transport cost.** These cluster exactly where contact happens, which is where spatial
  resolution matters most.
- **Dead players need no samples.** A dead player is in a spawn queue. Gating the sample
  loop on alive removes ~20% of rows and all of the uninformative ones.

So the sample stream is *gap-fill for dwell and occupancy*, not a trajectory recorder.
5s is sufficient for that.

---

## The transport budget, with numbers

One server-night = 3 matches × 2 halves × 1200s = **7,200s of live play**.

| | Value |
|---|---|
| Sample interval | 5s |
| Tick events/night (batched, all players per event) | **1,440** |
| Added POST rate | **0.20/s** |
| Measured baseline POST rate | **~7.5/s** (`match-1777342963-NY1`, incl. socket-only events) |
| **Increase over baseline** | **+2.7%** |
| Player-samples/night, alive-gated | **~13,800** |
| Packed at 20 B/sample | **276 KB/night** |
| MySQL, 64 B/row clustered + 1 index | **~880 KB/night** |
| Fleet-wide added POST rate (5 servers) | **1.0/s** |

**Batch all players into one event per tick.** Precedent exists: `flag_zone_players`
already emits one event carrying every flag rather than one per flag
(`KTPHudObserver.sma:1783-1808`).

**Payload constraint:** `BUFFER_SIZE` is 4,096 B with silent `formatex` truncation
(`KTPHudObserver.sma:46, :532`), and the roster guard breaks at 3,712 B (`:1730`).
Twelve entries at ≤250 B each fits comfortably; a compact position entry
(id, x, y, z, state) is ~50 B. **Budget ≤250 B per player entry and assert the total
before POST** — do not inherit the 192 B `pbuf` shape from `player_state`, which carries
far more than this needs.

### What this does *not* fix

The `/ingest` path has real defects that a +2.7% load increase does not trigger but does
sit on top of. They are worth fixing on their own merits, and they are prerequisites for
any *later* rate increase:

| Defect | Cite |
|---|---|
| p95 1.2–1.8s against a 3s timeout at 5 servers; 1s timeouts starved AMXX repeating tasks | `KTPHudObserver.sma:47-50` |
| `fs.appendFileSync` per persisted event on the Node event loop | `backend/src/handler/matchRecorder.ts:150` |
| No backpressure — always 200, no 429, no queue check | `backend/src/handler/ingest.ts:523-596` |
| No retry — failure logs a warning and discards | `FINDINGS.md:286-298` |
| Unbounded in-flight curl handles | `KTPAmxxCurl/src/amx_curl_manager_class.h:218-231` |
| `avg_latency_ms` permanently `null` — plugin sends `plugin_sent_at` in the **body**, `ingest.ts:572` reads a **header** | `KTPHudObserver.sma:485-496, :533` |

That last one means the fleet is currently blind to the exact metric that would warn of
saturation. It is a small fix and worth doing regardless of this plan.

**Do not route position through the HL log path.** `sv_log.cpp:310` truncates at
1,023 usable bytes silently, with no error and no counter, and the `hlstats.pl` UDP drain
(500 packets/cycle, uncounted kernel buffer overflow — `hlstats.pl:2092, :1993`) drops
without signalling. Data would be lost invisibly.

---

## The depth coordinate

One number per position, computed once per map and cached in a `map_geometry` table.

**1. Poles.** Spawn centroids per team, from the BSP parse (or clustered from the first
position sample of each life, as a fallback that needs no C++ change at all).

**2. Order the flags.** With `n ≤ 6` flag origins, choose the permutation minimising the
path `S_allies → f_1 → … → f_n → S_axis`. 720 candidates — brute force, no heuristic.

**3. Spine.** Polyline through `v_0 = S_allies, v_1..v_n = flags, v_{n+1} = S_axis`, with
each vertex anchored at `u_i = i / (n+1)`.

> **Anchor on flag index, not arc length.** A map with a long empty run-up out of one
> spawn would otherwise generate depth for simply walking. Flag-index anchoring
> denominates depth in *objectives* — "past the 4th flag" — which is what makes it
> poolable across the map rotation.

**4. Project** a position onto the nearest segment, giving `u(p) ∈ [0,1]` along the spine
and a signed lateral offset `lat(p)`.

**5. Sign by side:**

```
σ(T,h) = +1 if team T played Allies in half h,  −1 if Axis

depth(p,T,h)   = σ(T,h) · (2·C_map(u(p)) − 1)      ∈ [−1, +1]
lateral(p,T,h) = σ(T,h) · lat(p) / W_map
```

`depth = −1` is your own spawn, `+1` is the enemy spawn, `0` is the calibrated neutral
point. **Side-swap invariance is one multiplication.**

**Sign `lateral` too.** Otherwise "the left flank" swaps meaning between halves and every
flank statistic averages to zero. This is a silent, season-destroying bug.

### Asymmetric maps

`C_map` is a monotone piecewise-linear recentring pinning the *empirically* neutral depth
to 0.5 — the depth at which both teams suffer deaths in equal proportion, computed from
pooled historical kill positions. Use the kill distribution for what it is good at
(locating where the teams meet), not for partitioning territory.

### Report a fit score, and gate on it

`spine_fit = median(perpendicular error / map width)`. Where it is large — branching
layouts, a big parallel flank wing — Euclidean projection can place a player "deep"
*through a wall*. **Gate the depth term off for maps that fail rather than reporting
garbage.**

### v2: geodesic depth

Accumulate samples into a navigability grid, BFS from each spawn cluster, then
`depth = (g_A − g_X) / (g_A + g_X)`. Strictly better where it differs: respects walls,
handles branching, needs no flag ordering and no spine. Cannot be built on day one — it
needs accumulated samples. The prior-art survey is unambiguous that **geodesic, not
Euclidean, distance is the difference between a real metric and one that is quietly
nonsense**; every sports method assumes an open convex field, and a corridor map is not
one. Validate by correlating the two per map; disagreement localises exactly where the
spine was lying.

The same grid gives data-derived chokepoints via betweenness centrality, for free.

---

## The scoring shape: re-price, do not accrue

The central tension in `KTPR_TICK_ACCUMULATION.md` is that accumulation rewards presence
while the biggest measured win in the tuning history came from rewarding efficiency
(`tw_kd` 1.50 → 3.00, 70.4% → 77.8%).

**Re-pricing sidesteps the tension rather than mitigating it.**

```
effective_kills  = Σ_kills   (1 + λ_k · depth(killer_pos))
effective_damage = Σ_damage  dmg · (1 + λ_d · depth(attacker_pos))
effective_flags  = Σ_caps    (1 + λ_f · depth(capper_pos))
effective_deaths = Σ_deaths  (1 − λ_x · max(0, depth(victim_pos)))

λ_k ≈ 0.30,  λ_d ≈ 0.30,  λ_f ≈ 0.20,  λ_x ≈ 0.15,  depth clamped to [−1, +1]
```

Feed `effective_*` into the existing `R(x, median)`. **No new term, no new `tw_*`, no new
cap, no re-tuning of the six weights.**

Why this shape:

- **It cannot fight `tw_kd`.** Depth multiplies production within `[1−λ, 1+λ]`. A player
  with depth but no production gets nothing. Efficiency stays dominant; depth breaks ties
  *within* production.
- **At λ = 0 it is bit-identical to today.** Ideal for the established sweep methodology
  (one knob at a time, Spearman ρ, players moving ≥3 ranks).
- **The kill/death asymmetry does real work.** `death_kill_relief = 1.50` currently uses
  "your kills are above the median" as a *proxy* for "you were dying while pushing."
  Victim position measures the thing itself.
- **`max(0, …)` on deaths is deliberate.** Deep deaths are discounted; shallow deaths are
  not surcharged. Matches the "normalize, don't punish" rationale behind `ratio_floor`,
  and dying at depth −0.8 is partly a team failure.

### Anti-feed, quantified

A player who dies 22× a half (≈ the Rifle median) and makes **every** death a deep one
drops `effective_deaths` to 18.7 → `rx` 1.00 → 0.81 → `death_adj` 1.000 → 1.038.
**A 3.8% ceiling on the total value of pure suicide-pushing**, against uncapped K/D
degradation. The exploit does not pay.

If a sweep wants `λ_x = 0.5`, refuse — at that point a rush costs half a death and the
incentive inverts.

### The companion, if a standalone term is wanted

Not time-in-enemy-territory. **Controlled vs uncontrolled advance**, borrowed from hockey
zone-entry analysis — the single best transferable answer to "productive vs reckless
aggression" found in the prior-art survey. Tag every capture-point boundary crossing as
*controlled* (reached and held or contested it) or *uncontrolled* (pushed and died with
no gain), and report the volume of **controlled** advances.

The deeper lesson from that literature: Corsi/Fenwick exist because goals are too rare to
trust, so the field moved down the causal chain to a higher-frequency predictive proxy.
Kills and captures are the goals here. This is the proxy, and a 5-point corridor map *is*
a blue-line structure.

---

## What positional data repairs

Ordered by leverage, not by how positional the fix is.

| Documented problem | Fix |
|---|---|
| `class_normalize` is the most load-bearing knob (ρ 0.80 when disabled — largest single effect in `SENSITIVITY_SWEEP.md`) yet partitions on spawn class into cells of Sniper=10, **SMG=1** | Behavioural role clustering on the `(depth, lateral)` occupancy histogram + engagement range. Cell sizes become a choice, not an accident of what the roster picked. |
| `breaks` — median ~0.24/half, second-most sensitive knob; `break_smooth_k` cost 77.8% → 74.1% and moved 21/61 players ≥5 ranks just to stop it hijacking rankings | **Contest-denial presence** — alive time inside a zone the enemy is capturing. Same contribution, continuous, healthy non-zero median, order-of-magnitude more observations. Needs no smoothing. May recover the 3.7pp. |
| `flags` credits only whoever completed the cap; a fought 3-man cap and a walk-on score identically | **Cap participation** from per-player zone presence during the capture window. Raises the count, lowers the variance, removes the flag-hog artefact. |
| `tw_damage = 0.50` pinned low from distrust; the stated blocker is "no team-damage column exists to test against" | Attacker + victim position and identity partitions damage into enemy vs team and allows physical-plausibility checks. An independent third source for a stat that has two. |
| `death_kill_relief` is a proxy for "dying while pushing" | `effective_deaths` measures it directly. Validate as a refinement — if depth-at-death does not beat the proxy, keep the proxy; it is the cleanest change in the tuning history (ρ 0.993, 2/61 movers). |
| Per-half denominators corrupted by subs and mid-match leaves | A sample stream carrying the alive flag gives a **true alive-time denominator**. Rates become per-minute-alive. Unglamorous; improves every term at once. |

---

## The side-swap crossover — do this first, it needs no new capture

One `match_id`, two halves, sides swapped, same roster, same map. That is a
**within-subject crossover design**: player quality, teammate quality, opponent quality,
map, patch and sitting are all held fixed by construction.

`KTPR_SPEC.md` §6a already reports the descriptive finding — 44/61 players score better
on Allies, mean `side_diff` −0.053. Three things follow that are not currently extracted:

**1. Side-balance correction.** Difference within player-and-match, sign-corrected by
start side, to get `β̂_map` free of player and team quality. Then `y_adj = y − β̂_map,side`
before normalising. Worth doing: mean `side_diff` is **~9% of the full board range**
(1.30 → 0.71) on a board where ranks 26–30 all score exactly 1.00.

**2. An error bar on KTPR.** Compute `KTPR_H1` and `KTPR_H2` per player-match against
season-wide medians (`compute_match_splits` already has the `baseline_for` machinery),
then Spearman-Brown to a full-length reliability and an SEM. **The entire tuning
literature is denominated in "players moving ≥3 ranks" and those counts are
uninterpretable without a noise floor.**

**3. A causal test of the aggression hypothesis.** Regress `Δ(half margin ratio)` on
`Δ(active depth)` with match fixed effects, controlling for `Δkills` and `Δdamage`. A
surviving positive coefficient is evidence that depth contributes beyond what event
counts capture. Correlational analysis cannot get here — a cross-sectional
depth/winning relationship is exactly what team-quality contamination predicts even if
depth is worthless.

### Prerequisites and caveats

- **Clean half attribution is a hard prerequisite.** HUD and HLstatsX half counts
  disagree by up to 4 per player (`DATA_QUALITY.md`), and
  `hlstats_Events_PlayerActions` has no `half` column, which is why `side_report`
  already sources flags from `hud_flag_events` as a scoped exception. **Fix this first
  or the depth coordinate, the crossover and the causal test all rest on sand.**
- **`σ` must key on the half's actual side, not the match slot.** `ktp_match_players.team`
  is a slot stable across both halves; the Allies/Axis assignment flips at halftime.
  Getting this backwards inverts half the dataset and produces plausible-looking noise.
- **Do not source side from `ktp_match_end`** — `axis_score`/`allies_score` are swapped in
  100% of the 55 tournament matches. Use the `team_score` stream ordered by `(half, tick)`.
- **Sides are not randomly assigned** (knife round / toss / schedule) and **H2 is not
  exchangeable with H1** — a team down 5–0 plays differently. Include a start-side
  indicator and a half-order term.
- **Substitutions break the pairing.** Drop unpaired player-matches from `β̂` estimation.

---

## What this makes worse

Every scoring change re-ranks somebody.

1. **Team-quality contamination enters the rating.** A winning team plays deeper, so
   absolute depth partly measures your teammates. This is genuinely new — every current
   input is an individual event. Mitigation: re-pricing conditions on *your own* events,
   which are far less contaminated than your own position; and where a presence reading
   is wanted, use **relative depth** (`depth_p − mean_depth_team`), which differences out
   team field position. Absolute depth is a *team* territory metric; relative depth is an
   *individual* aggression metric. Conflating them is the most likely way this produces a
   term that looks meaningful and measures the scoreboard.
2. **Snipers and Heavies are structurally shallow, and that is correct play.** They hold
   angles onto a point from outside it. This inherits the thinnest part of
   `class_normalize` — which is a direct argument that behavioural role clustering should
   ship alongside or before the depth term, not after.
3. **More knobs.** Four λ, plus depth thresholds, contest radius, sustain time, and a
   per-map `C_map`. The existing 16-knob exhaustive search already found nothing beating
   77.8%; enlarging the space enlarges the overfitting risk. Fix radii and thresholds
   *a priori* from physical reasoning rather than sweeping them.
4. **Per-map calibration is a new failure surface.** A bad spine on one map silently
   corrupts every rating from it. Hence `spine_fit` and the gate.
5. **A gameable physical coordinate.** Every current term is a consequence of contested
   action. "Be at this depth" is a position that can be occupied on purpose. Bounded at
   3.8% for the suicide-push case, but chip-damage farming from a deep safe angle is the
   residual — keep `λ_d` small, or require per-event damage above a floor.
6. **The 54-match historical set has no position data and never will.** A depth-bearing
   profile cannot be computed against `old` / `current` on the existing tournament. You
   lose backfill and you lose "here is the 2026 LAN under the new formula."

---

## Phasing

Nothing here starts before the current backlog merges. Within this work:

| Step | Content | Gate | Cost |
|---|---|---|---|
| **S0** | `get_entvar` smoke test — see `SPIKE_ENTVAR_GEOMETRY.md` | Works on a live player and on a `CA_edict` | hours |
| **S1** | Fix half attribution. Fix the `avg_latency_ms` header bug. | Half counts reconcile between HUD and HLstatsX | small |
| **S2** | Side-swap correction + KTPR error bar. **No new capture.** | `β̂` reproduces the sign of the existing `side_report` finding, much tighter | ~2 days |
| **S3** | BSP spawn extraction + flag origins → `map_geometry` table + depth coordinate | `spine_fit` acceptable on the map pool; H1/H2 depth distributions for the same team are congruent, **not** mirror images (this catches the σ sign bug) | ~3 days |
| **S4** | Event-time position enrichment — attacker and victim on kills/damage/caps/breaks. **No new hook, no C++ change.** | Positions land non-null; victim positions sane | ~2 days |
| **S5** | `position_sample` event, 5s, alive-gated, batched, ≤250 B/player entry | Payload asserted under the guard; no dropped-line counter movement | ~2 days |
| **S6** | Depth re-pricing as `[profiles.new_v5]`, all λ defaulting to 0 | See validation below | ~3 days |
| **S7** | Contest-denial presence and cap participation — **replacing** `breaks` and `flags`, not added alongside | Replacement median comfortably non-zero; `break_smooth_k` becomes unnecessary | later |
| **S8** | Behavioural role clustering; geodesic depth | Needs a season of accumulated samples | later |

**S2 is deliberately ahead of all the capture work.** It needs no new data, corrects a
bias worth ~9% of the board range, and produces the noise floor that every subsequent
tuning decision has been missing.

### Validation for S6, in order

1. **Incremental validity first.** Partial correlation of the depth adjustment against
   each existing term. Gate: `|r| < 0.7` with all six, or the term is redundant and gets
   dropped regardless of how good it looks. Depth-of-kills correlating 0.85 with `kills`
   would mean it measures fragging, not aggression.
2. **Predict-accuracy**, leave-one-out, against the stated bar — but see the caveat below.
3. **Sensitivity in house format** — sweep each λ, report ρ and players moving ≥3 ranks,
   now interpretable against S2's noise floor. **Append the new knobs to
   `SENSITIVITY_KNOBS`**, which is a hardcoded list; a knob absent from it is silently
   unmeasured.
4. **The causal test** (crossover, above) — the only one that tests the *hypothesis*
   rather than the model.
5. **Human ranking.** Sample only player pairs where the old and new models *disagree* —
   agreement cases carry no information. Check inter-rater agreement before adjudicating
   anything; if raters do not agree with each other, the test cannot settle the question.

---

## Corrections to `KTPR_TICK_ACCUMULATION.md`

Carry these forward; the parent document is stale on each.

| Claim there | Reality |
|---|---|
| "periodic point-occupancy sampling — not captured"; the poll "discards everything it does not need" | The **HUD** poll emits `flag_zone_players` every 0.5s and it **is persisted** to `hud_events` — 2,609 of 8,997 events in the production fixture. Only *per-player attribution* and a *typed table* are missing. The `ktp_stats_capture.inc` poll is a different, unmerged one. |
| `ktp_stats_capture.inc` is the 0.5s poll | That file is **not checked out anywhere** — it exists only as a blob on three unmerged KTPAMXX branches. The deployed equivalent is `KTPHudObserver.sma:1779`. |
| "~350,000 rows for one evening" | A KTP half is 1200s, not 2400s (`ktpbasic.cfg:54`). The figure is **2× too high**, and irrelevant at 5s alive-gated: ~13,800 player-samples/night. |
| "77.8% is the number to beat" | 77.8% is the **`new_v3`** figure. The live `[profiles.new]` carries `break_smooth_k = 0.5`, which costs **77.8% → 74.1%**. Also `ktpr_output/predict_accuracy.md`, cited in three places as the writeup, **does not exist**. |
| "cap the tick contribution the way `flag_cap` and `death_cap` already bound their terms" | `flag_cap` is **not used** by the live team formula — only by `compute_excel` for the frozen `old`/`current` profiles. |
| "no other KTP map has bot waypoints yet" | 93 waypoint files are installed covering the real pool. `dod_anzio` is only the script default. |
| Per-player attribution needs `dodx_get_user_origin` "or extending DODX" | Neither framing is right. See §1 above — ReAPI `get_entvar` on `CA_edict`, no C++ change, and the C++ route ships known-bad data. |
| `docs/ktpr_mcp/IMPLEMENTATION_PHASES.md` | Path is wrong; the only copy is at the repo root. |

**And the one that matters most for anyone picking this up:** `G:\GIT\ktpr_mcp` and
`G:\GIT\ktpeffort` hold **byte-identical, two-generations-stale** copies of the engine.
`ktpeffort\ktpr_engine.py` has no `compute_prediction_accuracy` at all, and its
`[profiles.new]` is `tw_kd = 1.50` — the 70.4% profile. **The live engine is
`KTPInfrastructure/docs/ktpr_mcp/`.** All work belongs there.

---

## What not to do

- **Do not replace the existing profiles.** Add `new_v5`; `old`, `current` and
  `new_v1..v4` are frozen deliberately so redesigns can be compared.
- **Do not add `breaks` and contest-denial presence together.** They measure the same
  contribution and would double-count the model's most volatile dimension. Replace.
- **Do not raise the sample rate to fix a resolution problem.** Depth is a ratio of rates
  — halving the interval changes no rating bit. If resolution seems short, the fix is
  event enrichment, not sampling.
- **Do not un-exclude `player_state`.** It is 4 Hz, socket-only by design, and the
  largest payload on the wire. Add a separate purpose-built low-rate event.
- **Do not route position through the HL log path.** Silent truncation at 1,023 B.
- **Do not design the heatmap first.** It is the most attractive part and the least
  load-bearing for a rating. Depth and occupancy carry the value.
- **Do not expose zone AABBs to re-derive occupancy.** The existing design principle
  stands (`KTPHudObserver.sma:1769-1771`): the engine's trigger-touch logic is the source
  of truth. Use AABBs for the spatial reference frame, and assert per-player membership
  against `CA_num_allies`/`CA_num_axis` as free ground truth.

---

## Definition of done for this plan's successor

- [ ] `get_entvar` proven on the fleet, or the plan re-costed without it
- [ ] half attribution reconciled between HUD and HLstatsX
- [ ] `map_geometry` populated for the full map pool, with `spine_fit` reported per map
- [ ] σ sign verified by the H1/H2 congruence check
- [ ] side-balance correction and SEM published alongside the board
- [ ] incremental-validity gate passed before any λ is tuned
- [ ] new knobs present in `SENSITIVITY_KNOBS`
- [ ] a stated position on what got worse, with the re-ranked players named
