# Match metric contract v1.0.0

This document is the normative definition of the first KTP match-report metric
set. `MUST`, `MUST NOT`, and `SHOULD` describe compatibility requirements.

The canonical box-score JSON schema is version 3. Spatial-atlas metadata is
version 1. A change to a formula, event window, attribution rule, privacy class,
or unavailable/zero behavior requires a contract version change and a golden
regression update.

## Scope and source precedence

- A row belongs to a match only when its persisted `match_id` equals the
  requested identifier. Time proximity MUST NOT be used to adopt untagged rows.
- Gameplay events MUST have `half > 0`. Invalid half rows are reported and MUST
  NOT be silently reassigned.
- Raw match-tagged event tables are canonical. `ktp_match_stats half=0` is a
  reconciliation cache, not the source of truth.
- Missing optional sources are `unavailable`, never observed zero.
- Replay fixtures preserve event facts but not original duration. Per-minute
  metrics MUST be null when `source_mode=replay`.

## Canonical player and team facts

| Metric ID | Definition | Source/status |
|---|---|---|
| `kills` | Count of match-tagged frag rows by `killerId`. | Canonical. |
| `deaths` | Count of match-tagged frag rows by `victimId`. | Canonical. |
| `assists` | Count of PlayerPlayerAction rows whose DoD action code is exactly `assist`, attributed to `playerId`. No weapon is inferred. | Canonical when action source exists. |
| `headshots` | Sum of frag `headshot=1` by killer. | Canonical. |
| `team_kills` | Count of match-tagged teamkill rows by killer. | Canonical. |
| `suicides` | Count of match-tagged suicide rows by player. | Canonical. |
| `damage_dealt` | Sum of `damage_capped` where attacker and victim are different players on opposing roster teams. | Canonical when per-hit damage exists. |
| `damage_taken` | The same opponent damage attributed to the victim. | Canonical when per-hit damage exists. |
| `team_damage` | Sum of capped damage to a different player on the attacker's team. | Canonical. |
| `self_damage` | Sum of capped damage where attacker equals victim. | Canonical. |
| `capture_credits` | Count of `ktp_flag_captures` rows by credited player. Multiple players may receive credit for one event. | Canonical. |
| `unique_capture_events` | Count after grouping capture credits by match, half, team, flag name, and event time. | Canonical. |
| `cap_breaks` | Count of PlayerAction rows whose DoD action code is exactly `cap_break`. | Canonical. |
| `shots`, `hits` | Sums from StatsMe weapon rows. | Descriptive when available. |

Team totals are sums of additive player facts only. Ratios MUST be recomputed
from team totals rather than averaged across players.

## Derived box-score metrics

| Metric ID | Formula and null rule |
|---|---|
| `kd_ratio` | `kills / deaths`; null when deaths are zero. |
| `kda_ratio` | `(kills + assists) / deaths`; null when deaths are zero. |
| `damage_differential` | `damage_dealt - damage_taken`; null when damage taken is unavailable. |
| `damage_per_minute` | `damage_dealt * 60 / live_duration_seconds`; null for zero duration or replay-compressed input. |
| `damage_per_life` | `damage_dealt / deaths`; null when deaths are zero. Only completed lives are represented, so the unfinished final life is deliberately excluded. |
| `headshot_rate` | `headshots / kills`; null when kills are zero. |
| `raw_accuracy` | `hits / shots`; null when shots are zero. Descriptive only. |

Raw accuracy MUST NOT be used as a player-ranking or KTPR input without weapon
context. In particular, Garand users often discharge a chambered round to
perform a full reload, and the source cannot distinguish that action from a
miss.

## Event-sequence metrics

These metrics are currently aggregate analytical facts, not KTPR points.

| Metric ID | Definition | Confidence boundary |
|---|---|---|
| `opening_duel` | The first coordinate-bearing frag within 45 seconds of an observed half start. | Full-cap resets are excluded until a complete ownership timeline can identify them. |
| `opening_window_frag` | Any coordinate-bearing frag within the first 45 seconds of an observed half. | Same boundary as opening duel. |
| `trade_kill` | Player C kills the prior killer A within 5 seconds, and C is on prior victim B's team. The later frag is the trade kill. | Requires roster team attribution. |
| `fast_multikill_frag` | A frag belonging to a chain where the same killer's consecutive personal kills are no more than 5 seconds apart. | A chain contains at least two kills. |
| `isolated_death` | At death time, no teammate has a position sample within 3 seconds and 768 world units of the victim. | Deaths without enough teammate samples are excluded, not labeled isolated. |

`trade_attempt` is not defined in v1 because intent cannot be derived reliably
from kills and five-second position samples alone. It requires a reviewed
combination of proximity, damage, line-of-sight, and timing evidence.

## Spatial metrics

All public spatial products MUST combine players. Individual positional working
data is `PRIVATE_PLAYER_POSITIONAL_ANALYTICS` and MUST NOT appear in the public
API, website, downloadable reports, Discord, or another player's output.

| Metric ID | Definition |
|---|---|
| `occupancy_seconds` | Count of valid position samples in a 256-unit cell multiplied by the configured 5-second interval. |
| `kills_per_occupancy_minute` | Cell kill origins divided by cell occupancy seconds, multiplied by 60. Target cells require at least 15 seconds. |
| `deaths_per_occupancy_minute` | Cell victim locations divided by cell occupancy seconds, multiplied by 60. Target cells require at least 15 seconds. |
| `team_control_differential` | `(Allies occupancy - Axis occupancy) / total occupancy` within a cell. |
| `kill_lane` | Vector from killer cell center to victim cell center. A recurring corpus lane requires at least three identical origin/destination cell pairs. |
| `objective_area` | The 2D circle within 512 world units of a reviewed flag coordinate. |
| `objective_survival` | Objective-area occupancy minutes divided by deaths in the area; null when deaths are zero. |
| `sample_aligned_damage` | Capped damage placed at the attacker's nearest position sample within 3 seconds. It MUST be labeled approximate. |
| `pre_event_window` | Aggregate facts in the 30 seconds ending at a capture, cap break, or reconstructable capout. Overlapping windows may count the same fact once per event. |

Corpus rates require at least 60 aggregate occupancy seconds per cell. A target
comparison MUST use a leave-one-match-out baseline so the target does not
contribute to its own expected value. Bot baselines MUST be labeled synthetic
and MUST NOT be described as competitive norms.

### Confidence and sample size

Display thresholds are versioned in
`config/analytics/metric_confidence.json`; they do not alter the underlying
count or rate. Source completeness MUST be reported separately from statistical
interpretation.

- exact bot facts are `synthetic`, even when every source row reconciles;
- human damage/minute requires five observed minutes for `descriptive`;
- human damage/life requires three completed lives;
- human headshot rate requires five kills;
- human raw accuracy requires 25 shots and remains descriptive only;
- sequence metrics require ten observed events; and
- human map baselines are `emerging` at five matches, `reviewable` at 20, and
  `established` at 50.

Values below a display threshold are `low_sample`, not zero and not missing.
Unavailable inputs remain `unavailable`. Positional accumulation remains
`shadow_only` regardless of sample size until a separate production decision.

## Positional accumulation

The historical positional comparison profile is `accumulation_v2_target10`.
The current local scoring iteration is `accumulation_v3_bounded`, whose fixed
combat/objective budgets, no-penalty rule, contextual bonuses, reliability
gates, and report automation contract are defined in
`ACCUMULATION_V3_BOUNDED.md` and versioned TOML. Both remain shadow-only and
MUST NOT replace KTPR without a separately approved release.

Only the final derived `position_points` and component totals may leave the
private workspace. Per-player cells, coordinates, paths, flag identities,
distances, and sample coverage remain private.

## Momentum and objective conversion

V1 deliberately published timelines rather than a momentum score. Bounded v3
now emits an experimental, capped conversion ledger alongside those timelines;
it remains a shadow component pending human-match calibration. The atlas
may show combat and occupancy during the 30 seconds before captures, cap
breaks, and capouts. A future score may weight fast multikills, trades, middle
captures, and capout conversion, but it MUST be calibrated on human matches,
versioned, and displayed as an explanation with component values rather than
an opaque number.

## Explicitly unavailable in v1

- unused grenades at death: inventory state is not persisted;
- grenade explosion and grenade-damage heatmaps: exact explosion events are
  not persisted;
- wall damage: surface penetration/occlusion evidence is not persisted;
- trade attempts: intent evidence is insufficient;
- full-reset opening duels without complete flag ownership transitions; and
- trustworthy cross-map or competitive baselines before enough human matches
  exist.

These MUST appear as unavailable or deferred. They MUST NOT be approximated
from unrelated events merely to fill a report cell.

## Change control

Any metric change MUST include:

1. the new contract version and rationale;
2. source/schema compatibility notes;
3. a golden-fixture expectation update;
4. privacy classification review;
5. old/new output comparison; and
6. an explicit decision about whether historical reports are recomputed or
   retain their original version.
