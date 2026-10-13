## Why

#693 fixed four payload arrays and **deliberately held four consumers** that read a `killer_team` from their own feeds: `positional_shadow`, `accumulation_v3`, `damage_conversion`, `flag_fights`. Nobody had measured them. All four are measured here, read-only against production.

Three were wrong, `accumulation_v3` was already correct, and the enriched feeds turned out to reach **seven** analyzers rather than four.

The root cause is one line short of #693: `sql/analytics/frag_context_fact.sql` and `sql/analytics/damage_timeline_fact.sql` join their team columns to `ktp_match_players` exactly as `frag_timeline_fact.sql` does, and only the last of those was restamped.

| consumer | verdict |
|---|---|
| `accumulation_v3` | ✅ **already correct** — recorded so nobody re-checks it |
| `damage_conversion` | raw on **both** feeds, and **loses rows** |
| `positional_shadow` (`overextension`) | raw **cross-space**; no rows lost, every value wrong in a swapped half |
| `flag_fights` | raw **cross-space** in three places; clutches and entries resolve to the wrong side |

Specimens: `1789952635-NY1` (the one `scripts/roster_teams.py` is written against — half 1 is **12 of 12 players on the opposite side**, 0 agreeing) and `1790728388-NY5`, chosen because `damage_conversion` actually publishes there. **Half 2 is the terminal half and is the built-in control in every measurement below: it must not move.**

### `accumulation_v3` is already correct — do not re-check it

Its production path is `report_service.load_accumulation_scorer` → `lane_b_match_report.build_facts` → `accumulation_v3.score_match`. `build_facts` sets `killer_team` from `_stable_and_side_teams`, a per-`(half, player)` answer off `ktp_position_samples.team` — the true per-half side, not the roster label. On `1789952635-NY1` its feed yields **0** frags reading same-team where the roster label yields **67**, so `_enemy_frag` discards nothing. Nothing is owed.

### `damage_conversion`: rows leave the denominator, on both feeds

`_normalize_damage` drops a row whose two sides read the same team as `self_or_team`, and `_normalize_frag` drops one classified `explicit_same_team` — so a half-leaver's damage and frags left the denominator rather than landing on the wrong side of it.

On `1790728388-NY5`, where the block is `available`:

| | before | after |
|---|---|---|
| damage rows excluded `self_or_team` | 144 | **67** |
| frag rows usable | 522 | **574** |
| `damage_total` | 66,245 | **72,284** (+6,039, +9.1%) |
| `damage_to_own_kill` | 56,697 | **62,325** |
| players whose conversion fields move | — | **8 of 13** |

Same-team damage rows by half: **{1: 101, 2: 43} → {1: 24, 2: 43}**. The terminal half does not move, and the 67 that remain are real friendly fire — the guard still fires.

On `1789952635-NY1` the same restamp recovers **67 frags and 102 damage rows**, but that match's `damage_conversion` is `insufficient_source_data` both before and after (8 frag rows carry no producer half, which trips the block's own completeness gate) — so nothing publishes there either way. Verified against the published report: `insufficient_source_data` at schema 23, 28 and 30. **Corpus-wide the block is `available` on 103 of 250 latest-schema reports**, which is where this is visible.

### `positional_shadow`: a report team fed into engine-side geometry

`depth` resolves a player's own end per half from `orient`, built from `ktp_position_samples.team` — engine side. The sample loop passes each row's own side and is correct. The frag loop passed `frag_context`'s **roster** label, so in a swapped half every frag was measured from the opponent's end and mirrored against the wrong frontline.

**This is not a leaver-only defect** — it is wrong for every player in half 1 of every two-half match.

On `1789952635-NY1`:

| | half 1 (swapped) | half 2 (control) |
|---|---|---|
| `kills_ahead` | 145 → **66** | 80 → **80** |
| `deaths_ahead` | 127 → **88** | 80 → **80** |
| `kills_located` | 283 → **283** | 282 → **282** |

`kills_located` is identical, so **no row was ever lost** — the values were wrong. 11 of 13 players' rates change. `map_control` and `depth_profiles` are sample-fed and come out byte-identical, which bounds the change to `overextension`.

### `flag_fights`: an engine side weighed against report teams, three times

`ktp_objective_attempt_events.capturing_team` is the engine side. This module compares it against a frag's killer team **and** against the corrected roster — both report-team convention — so in a swapped half every window was judged against the opponent:

1. `opening.won_by_capturing_team` inverted. Half 1 **True=7 → True=13**; half 2 holds at **True=11**.
2. `build_clutch_shadow` derives its winner from `capturing`, so `winner_alive` / `losers_alive` swap: a real 1vX goes unrecorded and a false one can appear.
3. `build_entries_shadow`'s filter is `teams[pid] != capturing: continue` — it picked its entrant from the **defenders**.

`interruptions.py` reads the same column correctly, by resolving a frag's side from the life feed for that half, and documents this exact trap — so it deliberately keeps the untranslated feed.

## What changed

- `roster_teams.restamp_damage_teams` for the `attacker`/`victim` prefix pair, sharing one implementation with `restamp_frag_teams`.
- `report_team_convention.translate_objective_attempts` (engine `capturing_team` → report team, keeping `engine_side`) and `engine_side_for_report_team` (the inverse, for geometry). `report_team1_engine_side` remains the only thing that decides a side — **no second resolver**.
- `match_analytics.build_report` restamps `frag_context` and `damage_timeline` beside the existing `frag_timeline` call, hands `flag_fights` the translated attempt feed while `interruptions` keeps the raw one, and passes `team1_engine_side` into `build_positional_shadow`.
- `build_positional_shadow` translates the frag actor's team before touching `depth`. The guard is `is not None`, not truthiness: an **empty** side map means the life feed resolved nothing, and falling back to the raw label there is the defect. Measured first — of the 247 published reports where this block is available, every one has a life feed, so this is not a coverage trade.

**No contract or schema bump.** No DTO shape moves; `team_convention`/`engine_side` stay inside the internal report. The published *values* change, which is the point.

### Also found on the way (same un-restamped feed, not carded)

`progression`'s per-player kill series, `life_exploration` and `weapon_engagement` each drop a same-team row on their own guard, and `spatial_layers` emits the raw label in its kill vectors. All four are fixed by the `frag_context` restamp. `build_kill_streaks`, `build_player_classes` and `flag_swing` read no team off these rows; `flag_swing` and `interruptions` resolve sides from their own feeds.

## Verification

CI's own unit command in a dedicated worktree, baseline first on `origin/main` (`30ecd4f`), the four `pwd`-importing files excluded on both sides:

- **base**: 391 failed, 2694 passed, 186 skipped
- **head**: 391 failed, **2719** passed, 186 skipped — **+25 passed, +0 failed**, and the two `FAILED` lists are **byte-identical** (same md5, `comm` empty both ways)

`tests/e2e_stats` is not in that command, so it was baselined separately (`test_report_generated_at_mysql.py` excluded — it cannot collect on Windows):

- **base**: 43 failed, 498 passed, 1 skipped, 10 errors
- **head**: 43 failed, **503 passed**, 1 skipped, 10 errors — **+5 passed, +0 failed**, FAILED/ERROR lists identical both ways

The 391 are pre-existing and environmental on this box (`pwd`-only imports and `charmap` decode errors from a Windows locale); they are untouched and green on CI's Linux runner.

New tests pin each verdict with its terminal-half control: 6 on `restamp_damage_teams` (including that real friendly fire is still excluded), 9 on the two new translators (including a round-trip proving the two directions agree, so neither is a second resolver), 6 on `positional_shadow`'s report-team space, 4 end-to-end through `build_damage_conversion` recovering the dropped rows, and 5 on `flag_fights` covering the opening duel, the clutch winner and the entry filter.

## Floor

Merging this changes nothing anyone sees. **Every already-published report keeps its old numbers until an operator regenerates them** — the same floor #693 and the weapon-stats sibling sit at.

Coordination-Workstream: infra-half-side-correction

