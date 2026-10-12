### Fixed
- `trades`, `fast_multikills` and `recap_speed` disagreed with the report's own `players[].team` in
  every half the sides were swapped, and `trades`/`fast_multikills` lost rows rather than mislabelling
  them. `sql/analytics/frag_timeline_fact.sql` joins `killer_team`/`victim_team` to
  `ktp_match_players`, which is the side a player held in his LAST half — so a half-time leaver
  carried the opponent's label there exactly as he did in `players[]` before `apply_canonical_teams`.
  Both sides of his frags then read the same team, `_frag_classification` called every one an explicit
  team kill, and the trade and multikill analyzers never saw them. Measured on `1789952635-NY1`
  (the specimen `scripts/roster_teams.py` is written against): **68 of 586 frags, 11.6% of the match,
  discarded as team kills; trades 99 → 120, fast multikills 87 → 109, `deaths_traded` 99 → 120, the
  team-death response rate 0.1911 → 0.2048, per-team trade kills (1: 41, 2: 58) → (1: 55, 2: 65).**
  `_frag_classification`'s own comment calls an explicit same-team row a source-contract violation,
  because `hlstats_Events_Frags` already excludes teamkills — the violation was ours.
- `scripts/roster_teams.py` gains `restamp_frag_teams`, which stamps the frag feed from the already
  corrected `players` rather than re-deriving a team. One place decides a player's team and this reads
  its answer.
- `fast_multikills[].objective_conversion` compared the killer's report team against the capture's
  ENGINE SIDE (`objective_timeline_fact.sql` maps the team name onto 1 = Allies / 2 = Axis), so in a
  swapped half it matched the OPPONENT's captures: a conversion was credited to the wrong side of the
  kill and denied to the right one. `translate_objective_timeline` moves the capture feed into
  report-team convention first. On `1789952635-NY1` half 1 goes from **12 of 34 sequences converted to
  31 of 56**, and half 2 — the terminal half, where the two conventions agree by construction — does
  not move at all.
- `recap_speed` is keyed on `ktp_flag_state_events.owner_team`, the engine side that owned the flag,
  and the page renders both `events[].team` and `teams[].team` as a report team. So every half-1 recap
  was labelled with the opponent, and `teams[]` — summing across halves BY SIDE — was a mixture of the
  two rosters rather than either one's figure: **(side 1: 47, side 2: 39) where the report teams really
  took 44 and 42.** `translate_recap_speed` relabels each event and re-aggregates `teams` from the
  translated events, because averaging engine-Allies across two halves belonging to different report
  teams was never a meaningful number.
- `duels` was measured and is **already reconciled** — recorded so nobody re-checks it. The DTO's
  `duels` array carries no `team` at all (`{killer, victim, kills}`), and `build_duel_matrix` takes its
  `cross_team` from the corrected `players`, not from the frag feed.
- No contract or schema bump: `team_convention` and `engine_side` stay inside the internal report and
  the DTO's shape is unchanged. The published values change, which is the point — reports regenerate
  with them.
