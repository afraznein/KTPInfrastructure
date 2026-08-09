# KTPR — Specification & Source of Truth

This document replaces the 40-line Excel cell formula as the authoritative
definition of KTPR. The runnable implementation is [ktpr_engine.py](ktpr_engine.py);
all tunable numbers live in [weights.toml](weights.toml).

---

## 1. What KTPR is

A per-player performance rating for the LAN. Every variant shares one skeleton:

```
KTPR = SCALE
     × [ min(K/D, kd_cap) × (Kills/Half ÷ median_regulars(Kills/Half)) ]   # core skill
     × ( 1 + flag_bonus )                                                  # objective reward
     × ( 1 − death_penalty )                                               # death punishment
```

- **Core skill** — capped K/D ratio multiplied by how your kill production
  compares to the median *regular* player. This is the backbone of the score.
- **Flag bonus** — a diminishing log term `log(flags+1)/log(base)` plus a
  relative term (your flags/half vs the median), capped.
- **Death penalty** — how far your deaths/half exceed the regulars' median,
  scaled and capped. Below-median deaths become a small *bonus* (penalty < 0).
- **Regular player** — anyone whose `Matches ≥ MAX(part_floor, MAX(Matches)×0.66)`,
  i.e. played at least 66% of the most-attended player's matches. Medians used
  for normalization are computed over regulars only, so casual players don't
  distort the baseline.

## 2. Column contract

The engine reads these columns (letters = Excel column, matching `Book1.csv`):

| Col | Field        | Role in KTPR                                  |
|-----|--------------|-----------------------------------------------|
| A   | Players      | row identity / blank-row guard                |
| C   | KTPRn        | the sheet's output — used only to verify us   |
| D   | Matches      | participation → regular-player filter         |
| I   | K/D Ratio    | capped skill baseline                         |
| K   | Kills/Half   | kill production (normalized to regulars)      |
| M   | Deaths/Half  | death penalty                                 |
| O   | Flags/Half   | objective bonus                               |

New columns to be sourced from MySQL for the redesign: **assists**, **damage**,
**breaks** (all per-half, alongside the existing per-half rates).

## 3. The three variants

| Knob                | old   | current | Meaning                                  |
|---------------------|-------|---------|------------------------------------------|
| `scale`             | 0.80  | 0.75    | final multiplier                         |
| `flag_w_regular`    | 0.50  | 0.30    | relative-flag weight (regulars)          |
| `flag_w_nonregular` | 0.30  | 0.20    | relative-flag weight (non-regulars)      |
| `flag_cap`          | 0.40  | 0.35    | flag-bonus ceiling                       |
| `death_w` / cap     | 0.20 / 0.15 | 0.20 / 0.15 | death penalty (unchanged)         |
| `part_floor`        | 0.00  | 0.34    | floor on participation threshold (legacy)|
| `guard_zero_median` | off   | on      | divide-by-zero + `→ "-"` guards          |

**Verified against two real datasets:**
- `old` profile reproduces `Book1.csv`'s `KTPRn` exactly (max diff 0.0075, pure
  rounding — the CSV stores 1–2-decimal inputs while Excel used full precision).
- `current` profile reproduces `ktps9.csv`'s `KTPR` exactly (max diff 0.0086).
  `ktps9.csv` has 14 non-regulars out of 47, so this also confirms the
  non-regular branch and the participation filter are correct.

Both Excel formulas are therefore faithfully reimplemented in code.

### 3a. The `artifact` datapoint (a different formula shape)

A separate, earlier KTPR someone else built is **additive**, not multiplicative:

```
KTPR = [ (K/D / avg) + (kills/half / avg) + 0.25 * (flags/half / avg) ] / 2.25
```

It averages per-dimension ratios to the population **mean** (the Excel formulas
divide by the **median** of regulars and multiply factors together). It is
implemented as `formula="additive"` under `[profiles.artifact]` and kept purely
as a comparison datapoint. Verified shape against the Saturday leaderboard
(`saturday_leaderboard.csv`): reproduces its KTPR to ~0.01 for full-attendance
players; the larger residuals are high-flag/low-attendance players, confirming
the real formula normalizes **per-half** (the leaderboard only exposes totals).

So we have three reference formula shapes to triangulate a redesign from:
**old** (mult., median), **current** (mult., median, hardened), **artifact**
(additive, mean).

## 4. The redesigned `new` variant — the `team` formula

The redesign is a **fourth formula shape** (`formula="team"`, `compute_team`),
built to reward team contribution rather than raw fragging. It is a **weighted
average of normalized contributions**, where 1.0 = an average tournament player:

```
kill_term = (Kills/Half / median) ** kill_exp          # concave -> normalize fraggers
dmg_term  = (Damage/Half / median) * amplifier(kills)  # amplifier > 1 when kills are low
score     = Σ w_i * contribution_i  /  Σ w_i           # kills, K/D, assists, damage, flags, breaks
KTPR      = scale * score * death_adjust               # death: gentle, capped normalization
```

Why this shape (vs the multiplicative Excel one): because contributions **add**,
a low-kill/high-support player is *lifted* by the assist/damage/flag/break terms
instead of being crushed by a small multiplicative core. A one-dimensional
fragger is pulled toward the middle (normalized, not punished) because they are
below average on the other contributions.

Design decisions baked in (all tunable in `[profiles.new]`):
- **Assists, damage, flags, breaks are first-class contributions**, not small
  bonuses — support can substitute for kills.
- **`kill_exp` < 1** gives kills diminishing returns so high-*volume* fraggers
  normalize toward the pack.
- **`tw_kd`** rewards fragging *efficiency* (K/D) so elite-efficiency players stay
  competitive even with little support.
- **`dmg_interaction` / `assist_interaction`** amplify the damage *and* assist
  terms when kills are low — they reveal contribution the kills didn't capture.
  (Strengthened during tuning so low-kill/high-support players get a real lift.)
- **`ratio_floor`** stops any single weak stat from dragging a specialist down
  ("normalize, don't punish").
- **`role_weights`** a per-role final multiplier (e.g. `Heavy = 1.05`) to float a
  whole role up/down; elite members of a boosted role gain the most in absolute
  KTPR.
- **`class_normalize = true`** judges each player against the median of their own
  **role** (Rifle / Sniper / Heavy / SMG), so a great sniper ranks high among
  snipers despite the role producing few assists/flags. Role comes from each
  player's most-spawned `hud_spawns.class_id` (`ROLE_BY_CLASS` in `ktpr_mysql`).
- **`break_smooth_k = 0.5`** (added 2026-08-08) smooths the breaks ratio only —
  breaks have a near-zero median, so a plain ratio let a modest absolute break
  count outweigh a player's real leads on every other stat combined (a
  user-reported bug, confirmed on 3 player pairs).
- **`death_kill_relief = 1.5`** (added 2026-08-08) softens the death penalty
  for above-median killers only — dying while also fragging above the pack
  is aggression, not failure, so it shouldn't be penalized the same as a
  low-kill player dying for nothing. Below-median killers are untouched. The
  cleanest change in the tuning history: Spearman rho 0.993 vs. the
  pre-change weights, only 2/61 players moved ≥5 ranks.
- **`team_placement_weight = 0.15`** (added 2026-08-08) is a final per-player
  multiplier keyed to each team's REAL final tournament placement (not
  round-robin win rate) — 1st place +15%, last place +0%, linear between. A
  deliberate design addition, not a bug fix; unvalidated (a single LAN's
  placement data can't be leave-one-out tested the way the core weights were).

See `KTPR_KNOBS.md` for the full knob-by-knob reference, including exact
before/after numbers for all three 2026-08-08 changes.

Tuning harness: `python tune_new.py` (via PowerShell) → `NEW_KTPR_TUNING.md`,
which tags each player's role + archetype and shows Current→New movement.

### 4b. Player styles (`classify_styles`)

Each player gets a `<tier> <archetype>` label (e.g. **"Ace Sharpshooter"**):
- **Tier** = overall KTPR percentile (role-aware, matches the score), military
  flavor: **Ace** (top 15%) / **Veteran** / **Regular** / **Recruit**
  (edit `STYLE_TIERS` in `ktpr_engine.py` to rename).
- **Archetype** = profile *shape* vs the **global** median (absolute playstyle,
  not role-relative), across three axes — fragging (`0.5·K/D + 0.5·kills`),
  objective (`0.7·flags + 0.3·breaks`), support (`0.6·assists + 0.4·damage`):
  **Sharpshooter** (efficient fragger), **Fragger** (volume), **Flagger**,
  **Support**, **All-rounder** (≥2 axes strong), **Generalist** (flat profile).

Styles are descriptive metadata (shown in the reports); they do not feed back
into the KTPR value.

## 4a. Scope — what counts as a "tournament match"

KTPR is computed over the **Sat + Sun `match_type = 0`** matches only (55 of them
— the main-play games). Determined from the `ktp_match_end` event's JSON
`match_type`. Excluded: Friday's for-fun games (`match_type` 1/2/3) and the 7
incomplete/warmup matches with no `ktp_match_end`. This filter is the default in
`load_players_from_mysql(tournament_only=True)` (constants `TOURNAMENT_MATCH_TYPES`,
`TOURNAMENT_DAYS`). After filtering: 61 players, 55 matches.

## 5. MySQL data model (hlstatsx_lan)

Access: `ssh $KTPR_SSH_HOST` (key in `~/.ssh`, loaded into the Windows
ssh-agent), then `mysql hlstatsx_lan`. The code path is [ktpr_mysql.py](ktpr_mysql.py),
which runs queries over SSH (no local driver needed).

**Two telemetry systems (by design).** The DB carries two independent stat
pipelines. KTPR uses **HLstatsX as the authoritative spine** and **augments it
with HUD-only stats** (they will be reconciled in a future release):

| KTPR input | System | Source |
|---|---|---|
| kills | **HLstatsX** | `hlstats_Events_Frags` where `killerId = player` (enemy frags only; teamkills are separate) |
| deaths | **HLstatsX** | `hlstats_Events_Frags` where `victimId = player` + `hlstats_Events_Teamkills` victim |
| flags | **HLstatsX** | `hlstats_Events_PlayerActions` with action code `dod_capture_area` / `dod_control_point` |
| matches / halves | **HLstatsX** | distinct `match_id` / `(match_id, half)` where player was killer or victim |
| assists *(new)* | **HUD** | `hud_player_stats.assists` (is_final) |
| damage *(new)* | **HLstatsX** | `ktp_match_stats.damage`, `half > 0` (repointed 2026-08-09 — see below) |
| breaks *(new)* | **HUD** | `hud_player_stats.cap_breaks` |

**Damage moved off the HUD on 2026-08-09.** The daemon's `KTP_MATCH_END` handler
already aggregates `hlstats_Events_Statsme` into `ktp_match_stats` per player per
half, so damage never needed the HUD — and unlike the HUD it is gated to live
match time, the same as kills and flags. It is now divided by the **HLstatsX**
half count rather than the HUD's, which also takes it out of the HUD
missing-snapshot denominator problem. ⚠️ `half = 0` is the whole-match total and
duplicates halves 1..n exactly; every query must exclude it.

Validated offline against the LAN dumps before the change: scoped to the same 56
matches, HLstatsX damage runs **+5.5%** against the HUD (consistent with the
~4–6% HUD undercount documented below), with 59 of 61 players inside 0.90–1.25×.
The team-kill-damage theory for the remaining outliers does **not** hold —
correlation between the per-player ratio and team-kill count is **0.044**. The
shape instead matches HUD missing snapshots, i.e. HLstatsX is the fuller record.
⚠️ Scope the comparison before reading it: run unscoped (70 matches vs 56) the
same figure reads **+27.9%**, which is an artifact, not a finding.

Why not just HUD: the HUD `is_final` snapshot **undercounts** kills/deaths by
~10% vs the raw log (missing snapshot rows for subbed players + the summary
firing just before match end). HLstatsX is the canonical frag record, and its
population K/D correctly comes out **below 1.0** (0.98 — deaths include
teamkills/suicides that aren't enemy frags), as it should.

**Identity bridge:** HLstatsX `killerId/victimId` → `hlstats_PlayerUniqueIds.playerId`
→ `uniqueId` (e.g. `1:748805`); our steam_id = `"STEAM_0:" + uniqueId`. HUD and
`roster.csv` are keyed on that `STEAM_0:` form.

Per-half rates all use the **HLstatsX half count** as the single participation
basis: `rate = total / halves`. Implemented in `load_players_from_mysql`
(HLstatsX-spine); the older HUD-only aggregation is unused.

**Gotchas:**
- **Identity is `steam_id`**, not name. `hlstats_PlayerUniqueIds` maps
  `playerId → uniqueId` (used for the join above), but the display-name table
  `hlstats_Players.lastName` is not usable, and the HUD `name` field is chaotic
  (one steam_id had 11 tag/suffix variants). So steam_id is the only stable key;
  clean display names come from `roster.csv`.
- **Night** is derivable from the `match_id` epoch prefix:
  `DATE(FROM_UNIXTIME(SUBSTRING_INDEX(match_id,'-',1)))`. The event ("Philly LAN
  2026") spans 4 nights, ~31 matches / ~62 players / ~6 matches-per-player each.
- **Collation**: joining `hud_player_stats.match_id` to `ktp_matches.match_id`
  throws "illegal mix of collations" — derive the night from the prefix instead,
  or add an explicit `COLLATE`.

## 6a. Fixed teams and match context (`team_impact`, `clutch_report`, `map_report`, `side_report`)

There is **no explicit team-roster table** in `hlstatsx_lan`. `ktp_match_players.team`
(1/2) is only a per-match side slot, and `hlstats_Clans`/`hlstats_ClanTags` are
unpopulated on this server. Both new analyses reconstruct what they need from
raw match data instead (`ktpr_mysql.py`):

- **Team rosters (`_infer_teams`)** — `ktp_match_players.team` is stable across
  both halves of a match (DoD swaps Allies/Axis at halftime, not the
  roster-to-slot mapping), so clustering players who repeatedly shared a
  `(match_id, team)` slot recovers the real fixed rosters. Pairs are
  union-find-merged only above a minimum shared-match threshold (`min_weight`,
  default 6), so a one-off substitute who played a match for two different
  teams doesn't bridge them into one cluster. Verified on the live 2026 event:
  10 clean 6–7-player teams, matching the `[bb]` / `ßℓυ†н` / `[NATO]`-style
  name-tag clusters in `roster.csv` exactly. Each cluster is labeled with its
  members' most common name tag (cosmetic only — a fallback `Team-<id>` is used
  if no tag is extractable).
- **Match winners (`_match_results`)** — **do not read `ktp_match_end`'s
  `axis_score`/`allies_score`**: that event's payload has those two fields
  *swapped* relative to the real score. Confirmed two ways: (1) ground-truthed
  against a known result — team `[$]` actually went 3-9, but `ktp_match_end`
  at face value inverts that to 9-3; (2) mechanistically — cross-checking
  `ktp_match_end` against the last `team_score` event of the same match (which
  is internally consistent tick-to-tick and matches `half_end`) shows the
  fields swapped in **100% of the 55 tournament matches**. Not a coincidence,
  a bug in that one event. Fix: use the last `team_score` event of the match's
  final half as the real score (ordinary "higher wins"), mapped to a physical
  team via whichever side it occupied in that half — ordering that query by
  `(half, tick)`, not `tick` alone, matters, since tick resets to a small
  number at the start of half 2. ~98% match-result coverage (54/55 tournament
  matches; the rest drop when a team can't be resolved for that match, e.g.
  all-substitute lineups).
- **`team_impact`** (idea: sub-out impact) — `ktpr_engine.compute_sub_impact`.
  Replacement value for a player is the **median KTPR of other regular players
  in the same role** (falls back to the global regular pool if the role has
  too few). `team_avg_delta_if_subbed` is the swing to team average from
  swapping that one player for the replacement.
- **`clutch_report`** (win/loss + margin + opponent strength + consistency) —
  `ktpr_engine.compute_match_splits`, fed by `ktpr_mysql.load_match_player_stats`
  (per-match, not per-tournament, aggregation). Each match's KTPR is computed
  against **season-wide role medians** (via `compute_team`'s new
  `baseline_for` param), not medians re-derived from that single match — a
  single match is too small a sample to normalize against itself. Four cuts:
  - `clutch_diff = avg_ktpr(win) − avg_ktpr(loss)`.
  - `close_vs_blowout_diff` — matches split at the tournament-wide median
    `|margin_ratio|`, where `margin_ratio = (my_score − opp_score) / (my_score
    + opp_score)` (−1..1, computed from the corrected `_match_results` scores,
    so it needed the same fix as the winner). Normalizing to a ratio matters:
    raw score totals vary wildly by match (from ~20 to ~700+), so an absolute
    point-margin threshold would be meaningless across matches.
  - `opponent_adjusted_diff` — matches split at the median **season** team
    KTPR of the opponent faced (a lightweight strength-of-schedule proxy, no
    prior-event history needed).
  - `ktpr_consistency` — sample stdev of per-match KTPR across all matches
    played (lower = steadier).
- **`map_report`** (role x map performance) — `ktpr_engine.compute_map_splits`,
  same per-match rows as `clutch_report`, grouped by `(role, map_name)` instead
  of by player — an individual player rarely has enough matches on one map to
  be meaningful, but a role usually does (7 maps, 55 matches, min 3
  matches/cell to report). `ktp_matches.map_name` is a match-level attribute
  (same map both halves).
- **`side_report`** (axis vs allies performance) — `ktpr_engine.compute_side_splits`,
  fed by `ktpr_mysql.load_half_player_stats`. Needs **per-half**, not
  per-match, rows: side flips between the two halves of a match, so a
  per-match row can't carry one `.side` value. Each half-row already IS one
  half's worth of raw counts (no division needed, unlike the other loaders).
  One wrinkle: `hlstats_Events_PlayerActions` (the authoritative HLstatsX flag
  source elsewhere in this codebase) has no `half` column, so flags at this
  one granularity are sourced from `hud_flag_events` instead (steam_id-keyed,
  half-aware, same underlying capture events) — a deliberate, scoped exception
  to the "HLstatsX is authoritative" rule, not an oversight.
  Finding: **72% of players (44/61) score better on Allies than Axis**
  (mean `side_diff` −0.053 across the tournament) — a real, consistent skew
  worth a look at the map pool/spawn balance, not sampling noise.

### Data-quality audit (2026-08-07)

Before building the above, re-verified the pieces the match-result fix didn't
already touch, using the same "cross-check against an independent source"
method that caught the `ktp_match_end` bug:
- `half_end` vs. the last `team_score` event of half 1: **matches exactly on
  all 55 matches** — confirms the swap bug is isolated to `ktp_match_end` and
  nothing else in the score pipeline needs the same fix.
- `ROLE_BY_CLASS` (class_id → role) checked against `hud_spawns.weapon_primary`
  (actual weapon names, not just class_id numbers): every mapping confirmed
  correct (garand/kar/k43→Rifle, spring/scopedkar→Sniper, bar/mp44→Heavy,
  thompson/mp40/carbine→SMG). class_id 27 ("none", 78 rows, unmapped) is noise
  — spawn events with no weapon assigned yet.
- Role-assignment confidence: grouping by role (not raw class_id) puts 55/61
  players ≥70% in their dominant role; the other 6 are genuinely flexible
  players, not a mapping problem.
- Team clustering: all 61 players landed in a team cluster — zero dropouts to
  `team="?"` on the current dataset.

### Known data gap: matches missing `ktp_match_end`

12 of the 100 total logged match_ids never fired a `ktp_match_end` event, so
they're invisible to every tool (`_tournament_match_ids()` derives `match_type`
from that event's payload — no event, no match_type, can't be scoped in).
Checked all 12 for signs of a real, fully-played match (two `ktp_matches` rows
with real start/end timestamps, `half_end` present, meaningful kill counts):
11 are genuinely aborted/warmup (5–30 seconds of real time). **One is not**:
`1785715972-KTP1` (`dod_harrington`) has full ~20-minute timestamps for BOTH
halves and a normal `half_end` for half 1 — but half 2 has zero logged
telemetry (no kills, no team_score), so the match's true result is
unrecoverable from the database (server/plugin apparently stopped logging
mid-match). Found while investigating a ground-truth mismatch (a team's
real-world record didn't match `clutch_report`'s count). No code fix is
possible here — flagging it as a standing gap. The fix is a manual-override
mechanism (a small `match_overrides.json` the code checks before falling back
to computed results) for exactly this class of problem, not yet built —
pending the actual result of this one match.

## 6b. Formula validation (`predict_accuracy`, `match_avg_vs_season`, `shrunk_ktpr`, `map_adjusted_ktpr`, `weight_sensitivity`)

Everything in §6a reports what KTPR *says*. These five ask whether KTPR is
*good* — whether the formula (weights, aggregation choice, sample handling)
holds up, independent of any one player's story. Shared plumbing:
`ktpr_mysql.load_raw_match_stats` returns RAW (undivided) per-(player, match)
counts — the other loaders divide into per-half rates immediately, which
makes "season total minus one match" impossible after the fact; leave-one-out
validation needs the un-divided numbers so a match's contribution can be
subtracted by plain arithmetic. `ktpr_engine.RawMatchStats` is the row shape,
`_season_totals_by_player` / `_player_snapshot` turn a list of raw rows into
season or leave-one-out `Player` snapshots.

- **`predict_accuracy`** — `ktpr_engine.compute_prediction_accuracy`. For each
  resolved match, predicts the winner as the team with the higher average
  KTPR, computed from each player's season totals with *that match's own
  contribution subtracted out first* (using season totals as-is would let a
  match's own result help predict itself — circular). Role medians are held
  fixed at the season-wide value (not recomputed leave-one-out) since one
  match's effect on a ~60-player median is negligible; the real leakage risk —
  a player's own numerator — is what's actually removed. Compared against a
  naive raw-K/D-ratio baseline computed the same leave-one-out way, on the
  same 54 matches, to test whether KTPR's extra machinery (assist/damage/flag/
  break weighting, role normalization, `kill_exp`, interaction terms) earns
  its complexity over "who has the better K/D."
  **Result on the live 2026 event: KTPR 77.8% vs. K/D baseline 70.4%.**
  (Originally an exact 70.4%/70.4% tie; the 2026-08-07 `tw_kd`/
  `assist_interaction` coordinate-search pass — see `weights.toml`
  `[profiles.new]` — closed that gap: ßℓυ†н, a 6-6 team, had been rating as
  the tournament's #1 team ahead of iH.hildebrand? (10-1); reweighting
  fragging efficiency vs. low-kill support fixed the ordering.)

  **2026-08-08 follow-up — is there more room?** An exhaustive search (16
  knobs, 2-pass coordinate descent + a joint 2D grid on the two most
  sensitive knobs `tw_kd`/`tw_break`) found **no combination beats 77.8%**.
  A calibration check explains why: accuracy tracks KTPR's own predicted
  margin almost perfectly — matches where the leave-one-out team-KTPR gap is
  >= 0.10 are called correctly 96% of the time (22/23), but 27 of the 54
  matches have a gap under 0.05 (near-coin-flip by the model's own measure),
  and that band is where nearly every miss lives (59% accuracy there). The
  one confident-but-wrong exception — `1785721189-KTP1`, [NATO] beating a
  10-1 iH.hildebrand? 338-195 on `dod_anzio` — is a genuine single-match
  upset by the tournament's best team; no season-average rating can predict
  that without overfitting on it. **Conclusion: 77.8% is close to the
  practical ceiling for a season-average predictor on this 54-match sample**
  — the residual error is irreducible noise, not a fixable formula bias, so
  further hand-tuning against this exact leave-one-out set risks fitting
  noise. The search wasn't wasted, though: it surfaced `kill_exp` 0.80 ->
  0.65 as a free improvement on a *different* metric (team season-KTPR-vs.
  -win-rate Spearman rho 0.830 -> 0.891, stable across the whole 0.55-0.65
  range), with zero cost to `predict_accuracy` and almost no movement in
  individual player rankings (0/61 players moved >=5 ranks). See
  `ktpr_output/predict_accuracy.md` for the full writeup.

  **2026-08-08 second follow-up — median/map-adjusted team strength, and a
  smooth-loss overfitting check.** Two candidate replacements for "team
  strength = mean of leave-one-out player KTPR" were tried and both
  underperformed: **median** team strength (more robust to one hot/cold
  performer) scored 72.2%, and **map-adjusted** team strength (each match
  scored against its own role x map medians instead of season-wide role
  medians) scored 70.4% — both worse than plain mean's 77.8%. Useful negative
  results, kept as permanent comparison columns in `predict_accuracy`.
  Separately, since accuracy is a coarse step function (54 matches, ~1.85%
  per flip), re-ran the same 16-knob search against a smooth surrogate loss
  (softplus on each match's signed KTPR margin) instead of raw accuracy —
  and it *did* break the 77.8% plateau, reaching 81.5%. **Rejected**: getting
  there required moving 14 of 16 knobs at once, several drastically
  (`kill_exp` 0.65->0.35, `tw_kill` halved, `ratio_cap` 2.5->1.5), and the
  blast radius on individual rankings was severe — Spearman rho 0.865 vs.
  the production weights (every prior accepted pass stayed >=0.96), 40 of 61
  players moved >=5 ranks, one player fell 27 places. Trading two-thirds of
  the field's ranking for 2 more correct match calls out of 54 is fitting
  noise in this one sample, not finding a better formula. This is a useful
  result in the other direction from the plateau finding above: it confirms
  77.8% isn't a search artifact of the step-function objective — the only
  way past it costs far more than it's worth.
- **`match_avg_vs_season`** — `ktpr_engine.compute_match_avg_ktpr`. Season
  KTPR is computed from summed season totals (a sum-of-sums), so a couple of
  heavy matches can dominate it; this compares that against the mean/median of
  each player's *per-match* KTPR, which weights every match equally. Players
  with the largest gaps are the ones whose rating shape most depends on which
  aggregation you trust.
- **`shrunk_ktpr`** — `ktpr_engine.compute_shrunk_ktpr`. Empirical-Bayes-style
  shrinkage toward the player's role median, weighted by matches played
  (`shrink_matches`, default 3 — "how many matches' worth" of role-average
  prior gets blended in). Addresses that a 3-match player and an 11-match
  player currently read as equally confident under plain KTPR.
- **`map_adjusted_ktpr`** — `ktpr_engine.compute_map_adjusted_ktpr`. Unlike
  `map_report` (which reports the map effect as a separate cut), this bakes it
  into the rating: each match is scored against its own role x map medians
  (falling back to the season-wide role median when a cell is too small —
  `min_role_map_matches`, default 3), then averaged per player.
- **`weight_sensitivity`** — `ktpr_engine.compute_weight_sensitivity`. Perturbs
  each core `team`-formula weight ±10% and measures the Spearman rank
  correlation (and count of players moved ≥3 ranks) vs. the unperturbed
  ranking, over the 10 knobs in `SENSITIVITY_KNOBS`. **Result: all rho ≥
  0.997** — the ranking is quite robust to small weight changes (0–2.5
  players move ≥3 ranks on average per knob). `tw_break` and `tw_kd` are the
  (mildly) most sensitive; `tw_damage`/`kill_exp`/`dmg_interaction` the least.
  This is reassuring in the other direction from `predict_accuracy`: the
  formula isn't fragile around its hand-tuned values, even though those
  values aren't (yet) shown to be optimal for prediction.

## 6. How to run

```
python ktpr_engine.py Book1.csv               # show sheet / old / current / new
python ktpr_engine.py Book1.csv --profile new # show one profile
```

Editing weights never requires touching code — change `weights.toml` and re-run.