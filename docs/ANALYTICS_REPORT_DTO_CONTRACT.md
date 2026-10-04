# Analytics report DTO contract

`scripts/analytics_report_dto.py::sanitize_report` turns one internal match
report (`scripts/match_analytics.py::build_report`) into the payload stored in
the website's `ktp.match_report.payload`. This file describes the blocks whose
meaning is not obvious from their names.

## Versions

| `contract_version` | report `schema_version` | Change |
|---|---|---|
| `analytics-report-dto-v1.0.0` | 7-9 | Box score, trades, multikills, recap speed, ratings, lane analytics, spatial layers |
| `analytics-report-dto-v1.1.0` | 10 | Adds `in_game_result`, `player_halves`, `lane_analytics.depth_profiles.units`; always carries `ratings.ktpr_v2.display_scale` |
| `analytics-report-dto-v1.2.0` | 11 | Adds `kill_streaks`, `weapon_sides`, `duels_by_side`, `player_classes`, `players[].best_streak`, `player_halves.rows[].side` and `.best_streak`; cap breaks in `player_halves` take the producer half |
| `analytics-report-dto-v1.3.0` | 12 | Adds `score`, `points_per_minute`, `grenade_kills`, `grenade_damage`, `grenade_damage_taken` to `teams[]`, `players[]` and `player_halves.rows[]`; `map_profiles` (season aggregate) adds `kills_per_minute` and `points_per_minute` |
| `analytics-report-dto-v1.4.0` | 16 | Adds top-level `key_moments`: the match's highlight windows ranked on flag swing, names only |
| `analytics-report-dto-v1.5.0` | 17 | Adds top-level `progression` (cumulative per-player series per half: kills, deaths, damage; per-team flag differential) and `box_score_scale` (fill-bar denominators and match-best names per `players[]` field) |
| `analytics-report-dto-v1.6.0` | 18 | Adds top-level `plays` (each player's best plays and the match's top three; the worst play — the dunce — is computed but stays private), valued on `flag_swing_v1` with excursions from positions. `flag_swing` cap credit now joins per-credit rows within ±3 s of wall clock; caps had been uncredited in every production report before this |
| `analytics-report-dto-v1.7.0` | 19 | `map_control` and `progression`'s `teams[]` (flag differential) are now translated to report-team convention — both were silently backwards in half 1 of every two-half match, since DoD swaps Allies/Axis at halftime and these blocks carried raw engine side. Adds top-level `capouts` (completed cap-outs: one side owning every flag, `{half, game_time, team}`) |
| `analytics-report-dto-v1.8.0` | 20 | `progression` gains `cap_breaks` and `cap_participation` player metrics. Neither needed new capture: `hlstats_Events_PlayerActions` has carried a producer clock for cap breaks since `migrate_021_capture_observability.sql` (KTPHLStatsX), this pipeline had just never probed for it; `cap_participation` reuses `credit_timeline` (the per-credit rows `capture_credit_timeline_fact.sql` already computes for `flag_swing`'s cap-credit join, v1.6.0) — no second query |
| `analytics-report-dto-v1.10.0` | 23 | `assists`, `cap_breaks`, `capture_credits` and `kda_ratio` are `null`, not `0`, where the match predates the producer (see below). No key is added or removed |

Minor versions only add keys. A consumer that matches the
`analytics-report-dto-v1.` prefix keeps working; one that needs the new blocks
checks for them, because a v1.0.0 row never has them. A breaking change is a
new major version.

`ratings.ktpr_v2.display_scale` is the exception to that rule: it was added
while the contract still read v1.0.0, so a v1.0.0 row may or may not carry it.
Every v1.1.0 row does.

The report `schema_version` changes whenever `build_report` output changes, and
`report_service generate` regenerates every in-season match that has no report
at the current schema. `report_sync` then inserts those as new rows.

## `in_game_result`

The game engine's own team score (`source: engine-team-score-v1`, relayed by
KTPHudObserver). **It is not the league result.** The league result is the
captain-reported `ktp.match.home_score` / `away_score`, which this pipeline
cannot see and which can differ (forfeits, rulings, replays). `authority` is
always `in_game_team_score`, and `notice` says the same in words.

| Key | Meaning |
|---|---|
| `status` | `complete`, `partial` (published, with a flag), or `unavailable` (no score) |
| `flags` | Why a result is partial or unavailable |
| `team1_score`, `team2_score` | Total at the whistle, in report team numbers |
| `winner` | `1`, `2`, `"draw"`, or `null` when unavailable |
| `halves[]` | `half`, `team1_points` / `team2_points` scored in that half, `team1_cumulative` / `team2_cumulative` at its close, `team1_side` / `team2_side` (`Allies` / `Axis`) played that half |

Team numbers match `players[].team`: the side the team held in the terminal
half, since `ktp_match_players.team` is overwritten each half. Use
`halves[].team1_side` for the side in an earlier half.

Reading rule:

- Scores carry across halves. A half's close is its last `final` row, and the
  match total is the terminal half's close. Points in a half are its close
  minus the previous close.
- The scoreboard resets to 0/0 just after a half opens, before the carry is
  restored. That dip is not a close and is ignored.
- Half 1's baseline is recorded at match start and can still hold warmup
  points. The stream counts as complete only if it contains the 0/0 clear;
  without it the observer joined mid-half and the result is `late-stream-start`.
- `ktp_match_end` states the total in half-1 side terms and is checked that
  way.

Flags:

| Flag | Status |
|---|---|
| `match-end-missing` | partial |
| `observer-root-not-configured`, `observer-stream-missing`, `observer-stream-invalid`, `observer-context-mismatch`, `no-closed-halves`, `replay-source`, `not-in-report` | unavailable |
| `no-score-rows`, `half-set-mismatch`, `side-mapping-unknown`, `missing-half-start`, `missing-half-final`, `late-stream-start`, `half-carryover-mismatch`, `score-regression`, `match-end-disagreement` | unavailable |

The stream is bound to the match by match id, map, match type and the closed
half set in `ktp_matches`. It is read from the observer's settled
`<observer-root>/<match_id>/events.jsonl`, never from a live file.

## `player_halves`

| Key | Meaning |
|---|---|
| `status` | `available` or `unavailable` |
| `reconciled` | `true` when every player's halves add up to `players[]` for every additive column |
| `mismatched_columns` | Columns that did not add up |
| `rows[]` | `name`, `team` (match team number, as above), `half`, `duration_seconds`, and the box-score columns for that half |

A player with no events and no position samples in a half has no row for it.
Assists have no half column at the source and are placed by event time; cap
breaks use their producer half when the archive has one, else event time.
Damage columns are `null` for legacy matches without per-hit damage.

From v1.2.0 each row also carries:

| Key | Meaning |
|---|---|
| `side` | `Allies` / `Axis`: the side the player held that half, from the life ledger. `null` when the ledger has no row for the player in that half, or shows two sides |
| `best_streak` | That half's `kill_streaks` value, `null` when unavailable |

A player's side is constant within a half, so any `player_halves` column split
by `side` is a per-side split.

## `score` / `points_per_minute` (v1.3.0)

`score` is DoD's own objective score (`ktp_match_stats.score`), **not** a
capture count. A capture is worth 1 or 2 points depending on the flag's own
player requirement, so a player with 4 captures on a 2-point flag shows
`score: 8`. See `dod-objective-score-semantics` for the per-map point values.
`points_per_minute` is `score * 60 / duration_seconds`, `null` when duration
is 0.

`teams[].score` is the sum of its players' `score`; `teams[].kills_per_minute`
and `.points_per_minute` divide the team total by the match's own
`duration_seconds` (not summed per player, since every player shares the same
match clock). `map_profiles[].kills_per_minute` / `.points_per_minute` do the
same across every match played on that map: total kills or points across all
matches, divided by their total duration.

`score` and the three `grenade_*` columns are **not** included in
`player_halves.reconciled` -- unlike the columns that are, they compare a
per-half sum against `ktp_match_stats` half=0, which the daemon writes as its
own independently pre-summed total rather than deriving it the way this
report derives the half rows, so a mismatch there would not mean what a
kills/damage mismatch means.

## `grenade_kills` / `grenade_damage` / `grenade_damage_taken` (v1.3.0)

Frags and damage whose weapon is `grenade`, `grenade2` or `mills_bomb`.
`grenade_damage` / `grenade_damage_taken` only count damage between opposing
teams, matching `damage_dealt` / `damage_taken`; a grenade kill or damage
instance against your own team is not counted in either (it lands in
`team_damage` alongside every other friendly-fire source instead). Both
`_taken` columns are `null` wherever `damage_taken` is (legacy matches with
no per-hit damage).

Grenade-kill *locations* are not a new field here: `spatial_layers.frag_vectors`
already carries `weapon` per line and has been public since 2026-09-09 --
filter it to the three grenade weapon names for a kill-location map, using
the same attacker/victim coordinates and team/half/game_time every other
frag vector carries.

## `key_moments` (v1.4.0)

`definition: highlight_windows_v1`. The match's highlight windows: clusters of
kills and flag events on the `flag_swing_v1` timeline, ranked by the momentum
they moved. A coarse, derived list — at most `parameters.top_n` windows — and
the single source every consumer should read: the report page's key-moments
section, the HLTV viewer's deep links (a window's `start` is the game time the
anchor converts to demo time), the post-match message's "best moment", and the
clip pipeline. Re-ranking on the site means the site and the report disagree.

It is not the event stream. The per-event timeline stays private; this block
carries no ids, no positions, and no per-kill detail.

| Key | Meaning |
|---|---|
| `status` | `available` / `unavailable` (flag swing unavailable or timeline empty) |
| `definition`, `definition_version`, `parameters` | Ranker settings as run: `merge_gap`, `pad_before`/`pad_after`, `min_len`/`max_len`, `max_cameras`, `multikill_bonus`, `objective_bonus`, `top_n`; `ranker: flag_swing_v1`; `clock: producer_game_time` |
| `windows_total` | Windows found before `top_n` truncation |
| `windows[]` | `rank`; `half`; `start`, `end`, `duration`, `peak_at` (game seconds within the half); `kinds` (`frag`, `flag`); `events`; `swing` (sum of \|delta\|), `peak_delta`, `score` (swing plus bonuses); `summary` (e.g. `4k by SILVERBACK cK-, 5 flag events`); `involved[]` |
| `windows[].involved[]` | Up to `max_cameras` players by `name`, `team`, `involvement` (kills 1.0, deaths 0.4). The first entry is the window's dominant killer and the camera the reel uses. **Empty for flag-only windows** — flag events carry no player ids; consumers fall back to a director view. |

Ranking is on uncalibrated `flag_swing_v1` deltas, so order is comparative,
not absolute. A window longer than `max_len` is centred on its peak event
rather than truncated from the start.

## `plays` (v1.6.0)

`definition: plays_v1`. Each player's two or three most valuable plays and
the match's top three. The dunce — the single worst decision of the match —
is computed in the private block and deliberately **not published**: it is
end-of-season material, not a match-page label.
`key_moments` answers "what were the big moments"; this answers "what did each
player do that mattered". Same currency (`flag_swing_v1` deltas, signed from
the player's side: kills and credited caps for them, their own deaths against
them), plus one thing the timeline cannot see: **excursions** — stretches of a
life spent alone behind the enemy's lines, from position samples — which
become plays of their own, merged with whatever events fall inside them and
charged an exposure cost for the time the team played a man down
(`parameters.absence_rate` per minute).

| Key | Meaning |
|---|---|
| `status` | `available` / `unavailable` (flag swing unavailable or timeline empty). Excursions missing (no positions, replay mode) leaves plays available without excursion-based entries. |
| `definition`, `definition_version`, `parameters`, `caveats` | As run: `merge_gap`, `excursion_slack`, `absence_rate`, `per_player`, `match_top`, `dunce_floor`, `sneak_seconds`, `attempt_distance`; `valuer: flag_swing_v1` |
| `plays_total` | Plays built before ranking (positive and negative) |
| `match_top[]` | The `match_top` highest-value plays across all players, `rank` 1..n |
| `per_player[]` | `name`, `team`, `plays[]` — that player's positive-value plays, best first, at most `per_player`; empty when they have none |
| play | `name`, `team` (report team), `side` (engine side that half), `half`, `start`/`end`/`duration`/`peak_at` (game seconds), `value` (= `event_value` + `exposure`), `kills`, `deaths`, `caps`, `capout_denials`, `excursion` (`duration`, `min_teammate_distance`, `closest_flag`, `closest_flag_distance` — or `null`), `tags`, `summary` |
| `tags` | `cap`, `solo cap`, `sneak cap` (excursion ≥ `sneak_seconds` before the touch), `cap-out denial` (the flag was taken from a side holding all but one), `Nk` (N ≥ 3), `collapse` (excursion with ≥2 kills, no cap), `attempt` (excursion within `attempt_distance` of a rear flag, no cap), `loiter` (excursion, nothing), `death`, `died for nothing` |

Values are comparative, not absolute, and today a kill is worth far less than a
cap (the baseline's alive term divides by the full roster), so cap plays
dominate. The deposit/payout momentum ledger and counterfactual denial pricing
(coordination workstream `infra-hidden-value-plays`) are the intended upgrade:
they change the numbers and the ranking, not the shape of this block.

The private `shadow_explorations.plays.dunce` (the worst play: by preference a
wasted excursion that took no flag, else a death costing more than
`dunce_floor`) exists for an end-of-season reel. Do not surface it per match.

## Reports built before schema 18

`plays` reads `unavailable`; `key_moments` and everything older is unchanged.
Reports regenerated at schema 18 also carry corrected `ratings.flag_swing`
player credit for caps (see the version table).

## `progression` (v1.5.0)

`definition: progression_v1`. Cumulative series over each half — the data
behind a kills-over-time chart — computed once here so the site, the HUD and
any post-match message draw the same line. The site must not re-derive these
from events; it never has the events.

Three per-player metrics and one per-team metric. `players[]` rows are
`{name, team, half, metric, points}`; `teams[]` rows are `{team, half, metric,
points}`. `points` is `[[game_time, cumulative], ...]`, always starting at
`[0, 0]` (for `flag_differential`, starting at the kickoff differential).

**The x-axis is `game_time` within the half.** Each half is its own map load
and the producer clock restarts, so halves are separate panels (or one axis
with a marked boundary). There is no round index; DoD has none, and none is
invented.

| Metric | Counts |
|---|---|
| `kills` | Frags with a producer clock where the killer is on the other team — team kills and suicides excluded, matching the box score's `kills` |
| `deaths` | Every frag with a clock where the player is the victim |
| `damage` | `damage_capped` dealt to the other team, from per-hit rows; only when per-hit damage with a clock was captured (`available.damage`) |
| `flag_differential` (team) | Flags held by team 1 minus team 2, seeded with the same spawn ownership `flag_swing_v1` uses; team 2's series is the negation. Translated to report-team convention (v1.7.0) — computed in raw engine side, then re-keyed per half through `scripts/report_team_convention.py` before this block is stored; a half the resolver can't decide is dropped, not mislabeled |

| Key | Meaning |
|---|---|
| `status` | `available` / `unavailable` (no timed source captured) / `timed_metrics_suppressed` (replay-sourced) |
| `available` | Per metric, whether its source was captured for this match. A missing metric is absent from `players[]`, never a flat zero series |
| `coverage` | `frags_with_clock` / `frags_total`, `damage_with_clock` / `damage_total`. A final point can trail the box score when some events carry no clock; this says how many |
| `metrics`, `team_metrics` | The metric names present in this version |

Every rostered player gets a series for every available metric in every half
seen, even when it is only `[[0, 0]]` — zero kills is data, a missing series
would read as no data.

**Not in v1, deliberately:** cap participation (its per-event rows are keyed
on wall clock, not game time) and cap breaks (no fact query loads per-event
break rows). Both are additive follow-ups.

## `capouts` (v1.7.0)

Completed cap-outs — a flag transition that leaves one side owning every
flag on the map. Distinct from `plays`' `cap-out denial` tag (a cap that
broke an *imminent* one): this is the completed event. Report-team
convention.

| Key | Meaning |
|---|---|
| `status` | Follows `flag_swing`'s own status — capouts is a byproduct of its event stream, same availability |
| `events[]` | `{half, game_time, team}`, one per completed cap-out. A half with more than one round can have more than one |

## Half 1's `map_control` and `progression.flag_differential` before v1.7.0

DoD swaps Allies/Axis at halftime; `map_control` and `flag_differential`
computed in raw engine side (1 = Allies, fixed all match) rather than
report-team convention, so both were silently backwards in half 1 of
every two-half match — report team 1's terminal-half slot is guaranteed
the *other* engine side in half 1. Fixed at v1.7.0 / schema 19 by
translating both at the producer, before `shadow_explorations` is
stored; no website change needed. `flag_swing`'s own math (`p_allies()`
alive term, per-kill `team_sign` attribution) had the equivalent defect
and was fixed separately at schema 17 (2026-09-18, KTPInfrastructure#455)
— this is the remaining presentation translation, not a re-fix of that.

## Reports built before schema 19

`capouts` reads `unavailable`. `map_control` and
`progression.flag_differential` carry the old, backwards half-1 values
(see above) until regenerated.

## `box_score_scale` (v1.5.0)

Fill-bar normalisation for `players[]`, computed once here so a second
consumer cannot drift from the first. Operator ruling 2026-09-16: the
denominator is the max across **all players in the match** (`scope:
all_players`), not within the player's own team.

`fields` has one entry per numeric `players[]` field:

| Key | Meaning |
|---|---|
| `max_in_match` | The bar's denominator: the largest value any player posted. A consumer's fill is `value / max_in_match`. `null` when no player has a value |
| `higher_is_better` | `false` for `deaths`, `damage_taken`, `team_kills`, `suicides`, `grenade_damage_taken`. The bar still scales on the max (it says "how much"), but a full bar is not an achievement and the star goes the other way |
| `best` | Names holding the match-best value — the max, or the min where `higher_is_better` is false. Ties keep every name; empty when no value. A consumer's `is_match_best` is "name in best" |

## `assists`, `cap_breaks`, `capture_credits` before their producers (v1.10.0)

Each of these counts comes from a producer that started partway through the
archive. A match or half that ended before the producer's first event
anywhere in the archive was never measured, so the column is `null` in
`players[]` and `player_halves.rows[]`, and `kda_ratio` is `null` with
`assists`. A `teams[]` total is `null` when every player on that team is.
A covered match with no such events reads `0`, which is a real zero.

Production producer start (first match carrying events, league-local time):
assists, cap breaks, per-hit damage and position samples
2026-08-21 21:10; capture credits (`ktp_flag_captures`) 2026-08-15 16:25.
Kills, deaths, headshots, team kills, suicides, shots and hits come from
tables that predate the whole archive and stay filled.

Only a rebuilt report changes: one built before this keeps its zeros. The
report schema did not move, and `contract_version` is stamped when the DTO is
made, so neither tells an old build from a new one.

## Reports built before schema 11

`kill_streaks`, `weapon_sides`, `duels_by_side` and `player_classes` read
`status: unavailable` with flag `not-in-report`, and `players[].best_streak` is
`null`. Render them as unavailable, never as zero. Matches before the life
ledger existed (all of S9) build at schema 11 with `status: unavailable` and a
source flag.

## Reports built before schema 12

`score`, `points_per_minute` and the three `grenade_*` columns are plain
numeric columns, not a status-wrapped block -- a report built before schema
12 simply has no key for them, so `players[]`, `teams[]` and
`player_halves.rows[]` read `null` for all five rather than `0`. Same
render-as-unavailable rule as above. `report_service generate` only
regenerates a match automatically when it has no report at the current
schema at all; an already-published match keeps its old schema's payload
until explicitly regenerated (`generate <match_id> ...`).

## `kill_streaks`

`definition: kill_streak_v1`. A kill streak is the number of enemy kills a
player makes between two of their own life ends within one half.

- Counts frags (enemy kills). Teamkills never count.
- Resets on every end of the player's life: death to an enemy or a teammate,
  suicide, world death, disconnect. A teamkill BY the player does not reset,
  and a respawn without a recorded death does not reset.
- A half always resets. The match value is the best half.
- A kill landing after the killer's own death (a grenade) counts toward the
  counter as it stands then, which the death has already reset.
- A kill and the killer's own death on the same tick: the kill is first.

| Key | Meaning |
|---|---|
| `status`, `flags` | `available` / `unavailable`. Flags: `source-not-captured`, `no-life-boundaries`, `no-frag-clock`, `not-in-report` (unavailable); `unordered-frags`, `kills-without-life-boundaries` (available) |
| `coverage` | `ordered_frags` (producer clock), `recovered_frags` (time taken from the victim's death within 2 s), `unordered_frags` (left out of runs), `kills_after_own_death` |
| `rows[]` | Per player per half: `name`, `team`, `half`, `side`, `kills` (all frags, unordered included), `best_streak`, `streaks_3_plus` (runs of 3 or more), `lower_bound` |
| `players[]` | Per player: `name`, `team`, `best_streak` (match), `by_side` (`Allies` / `Axis` best, `null` if not played), `lower_bound` |

`lower_bound: true` means a frag of that player's could not be placed in time,
so the published streak may be understated by it. `best_streak` is `null` only
when the player has kills but no life boundary at all in that half.

## `weapon_sides`

Kills, headshot kills, shots, hits and opponent damage per player per half per
weapon, filed under the side the PLAYER held that half, never the weapon's
faction: a picked-up enemy weapon stays on the player's side.

| Key | Meaning |
|---|---|
| `status`, `flags` | as above |
| `reconciled` | `true` when the rows sum back to `weapons[]` for every column |
| `mismatched_columns` | Columns that did not |
| `unsided_kills` | Kills in rows whose `side` is `null` |
| `rows[]` | `name`, `team`, `half`, `side`, `weapon`, `kills`, `headshot_kills`, `shots`, `hits`, `damage_dealt` (`null` for legacy damage) |

## `duels_by_side`

`duels[]` split by the side the killer held. Cross-team cells only, as in
`duels[]`, so the `kills` of cells with the same `killer` and `victim` sum to
that pair's `duels[]` value.

| Key | Meaning |
|---|---|
| `reconciled` | `true` when the split sums back to the duel matrix |
| `unsided_kills` | Kills filed under `killer_side: null` |
| `cells[]` | `killer`, `victim`, `killer_side`, `kills` |

## `player_classes`

One row per player per half per class id, from the class read at spawn.

| Key | Meaning |
|---|---|
| `rows[]` | `name`, `team`, `half`, `side`, `class_id`, `class_code`, `class_name` (`null` when the id is not in the mapping), `lives`, `kills`, `deaths`, `headshot_kills` |
| `coverage` | `lives`, `lives_mapped`, `kills_classed` / `kills_unclassed`, `deaths_classed` / `deaths_unclassed`, `unmapped_class_ids` |

- `lives`: consecutive spawns with no death between them are one life, owned by
  the later spawn's class (the go-live baseline followed by the real spawn, or
  a class-change respawn).
- `kills` and `deaths` use the player's class at their latest spawn at or
  before the frag, so a grenade landing after its thrower died counts to the
  class that threw it. A frag with no time is `unclassed`.
- A class row's kills include picked-up weapons; `weapon_sides` is where
  weapons live.
- No accuracy per class: shots carry no class or time at the source.
- Class ids and labels: `config/analytics/dod_classes.toml`.

## `ratings.ktpr_v2.display_scale`

`parameters` describes the model, including `normalization:
per_match_z_scores`. That is true of `components` but not of the published
`rating`, which is already rescaled. `display_scale` says what each published
field actually is:

| Key | `kind` | Meaning |
|---|---|---|
| `rating` | `floored_index` | `max(floor, center + per_z * z)` with the block's `center` (100), `per_z` (15) and `floor` (50). Render as published; a second transform saturates it. |
| `components` | `raw_z_score` | Per-match z-scores, mean 0, negative below average. A consumer that must not show negatives maps these itself. |

The season aggregate (`report_service aggregate`) carries its own
`display_scale`: `rating` and `sos_rating` are `floored_index` with the same
numbers, and `se` is `raw_z_score` (a spread in z units, not rescaled).

## `lane_analytics.depth_profiles`

`units` names the unit of each player field:

- `mean_depth`, `depth_sd`: a fraction of the lane, the polyline through the
  map's flag origins in flag order. 0 is the player's own end and 1 the enemy
  end for that half. Every sample is clamped to [0, 1], so a value is never
  outside that range, and a player behind their own last flag reads 0. Showing
  it as a percentage of the lane is correct. It is not a fraction of the map.
- `lateral_mean`: mean perpendicular distance from the lane, in world units.
