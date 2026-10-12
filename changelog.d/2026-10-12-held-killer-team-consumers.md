### Fixed
- The four consumers held back from the `restamp_frag_teams` change (`positional_shadow`,
  `accumulation_v3`, `damage_conversion`, `flag_fights`) are now measured. Three were wrong, one was
  already correct, and the enriched feeds turned out to reach **seven** analyzers rather than four:
  `sql/analytics/frag_context_fact.sql` and `sql/analytics/damage_timeline_fact.sql` join their team
  columns to `ktp_match_players` exactly as `frag_timeline_fact.sql` does, and only the latter was
  restamped. Measured read-only on `1789952635-NY1` (half 1: **12 of 12 players on the opposite side**,
  0 agreeing) and on `1790728388-NY5`, with the terminal half as the built-in control throughout.
- `match_analytics.build_report` now restamps `frag_context` and `damage_timeline` from the corrected
  roster beside the existing `frag_timeline` call. Four of the seven consumers DROP a row whose two
  sides read the same team, so a half-time leaver's rows left the denominator rather than landing on
  the wrong side of it: `damage_conversion` (on both feeds), `progression`'s per-player kill series,
  `life_exploration` and `weapon_engagement`, each on its own same-team guard.
- `damage_conversion` understated every total on a match with a half-leaver. On `1790728388-NY5`,
  where the block publishes (`available`): damage rows excluded as `self_or_team` **144 → 67**, frag
  rows usable **522 → 574**, `damage_total` **66,245 → 72,284 (+6,039, +9.1%)**, `damage_to_own_kill`
  **56,697 → 62,325**, and 8 of 13 players' conversion fields move. The same-team damage rows by half
  go **{1: 101, 2: 43} → {1: 24, 2: 43}** — the terminal half does not budge, which is the control.
  `scripts/roster_teams.py` gains `restamp_damage_teams` for the `attacker`/`victim` prefix pair,
  sharing one implementation with `restamp_frag_teams`.
- `positional_shadow`'s `overextension` fed a REPORT team into ENGINE-side geometry. `depth` resolves
  a player's own end per half from `orient`, which is built from `ktp_position_samples.team`, while the
  frag loop passed `frag_context`'s roster label — so in a swapped half every frag was measured from
  the opponent's end. This is not a leaver-only defect: it is wrong for **every player in half 1 of
  every two-half match**. On `1789952635-NY1`, half 1 `kills_ahead` **145 → 66** and `deaths_ahead`
  **127 → 88**, while half 2 holds at **80/80** both ways; `kills_located` is **565 in both**, so no
  row was ever lost — the values were wrong. 11 of 13 players' rates change. `build_positional_shadow`
  takes `team1_engine_side` and translates through the one existing resolver via
  `report_team_convention.engine_side_for_report_team`; `map_control` and `depth_profiles` are
  sample-fed and come out byte-identical.
- `flag_fights` compared an ENGINE-side `capturing_team` against report teams in three places, so
  every window in a swapped half was judged against the opponent: the opening duel's
  `won_by_capturing_team` inverted, `build_clutch_shadow` resolved the winner to the other side (so a
  real 1vX went unrecorded and a false one could appear), and `build_entries_shadow`, whose filter is
  `teams[pid] != capturing: continue`, picked its entrant from the **DEFENDERS**. On
  `1789952635-NY1`, half 1 `won_by_capturing_team` goes **True=7 → True=13** while half 2 holds at
  **True=11**. `report_team_convention.translate_objective_attempts` moves the attempt feed into
  report-team convention, and the clutch and entry builders inherit it through `flag_fights`' own
  windows. `interruptions.py` keeps the untranslated feed on purpose — it resolves a frag's side from
  the life feed itself and documents this exact trap — so the two read the same column in the spaces
  they each expect.
- `accumulation_v3` was measured and is **already correct** — recorded so nobody re-checks it. Its
  production path is `report_service.load_accumulation_scorer` →
  `lane_b_match_report.build_facts` → `score_match`, and `build_facts` sets `killer_team` from
  `_stable_and_side_teams`, a per-`(half, player)` answer off `ktp_position_samples.team`, not from the
  roster. On `1789952635-NY1` its feed yields **0** frags reading same-team where the roster label
  yields **67**, so `_enemy_frag` discards nothing. Nothing is owed here.
- No contract or schema bump: every change is to values inside the internal report, and no DTO shape
  moves. Published reports keep the old numbers until an operator regenerates them.
