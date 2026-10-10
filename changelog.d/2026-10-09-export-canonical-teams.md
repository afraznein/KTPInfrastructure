### `analytics`: the half-leaver fix reaches the website, not just the report (2026-10-09)

`ktp_match_players.team` is the engine side a player held in the LAST half he appeared in,
and DoD swaps sides at the break — so a player who leaves at half keeps a side that by then
belongs to the other team. `#496` corrected the match report for exactly this and
deliberately stopped there: "nothing moves except the players the roster got wrong;
`game_team` remains the side at match end." But `game_team` is the only team the website
ever reads. `ktp-stats-export.py` shipped `p.team` raw, the site stored it as
`game_match_player.game_team`, derived `player_match_stat.season_team_id` from it, and
rendered that — so https://ktpleague.gg/player/las1k64 went on filing Las1K64 under `uD`,
the team he played against, for two weeks after the producer fix was verified. Worse, the
site's ringer rule then compared that side against his real registration and read the stint
as a RINGER appearance for the opponent. Reported by Drew 2026-10-09.

- The exporter now resolves each player through `canonical_teams` over the per-half life
  feed, the same answer `scripts/roster_teams.py` gives the report. A no-op for everyone
  present at match end — the canonical labels ARE the final half's sides — so `gameTeam`
  keeps its documented meaning and only the rows the roster got wrong move.
- The algorithm is duplicated, not imported: this script deploys standalone to
  `/usr/local/bin` with no package, the same constraint `OFFICIAL_MATCH_TYPES` carries.
  `tests/unit/test_stats_export_canonical_teams.py` fails on any drift by running both
  implementations over 400 generated life feeds.
- The side feed carries the same guards as `sql/analytics/life_boundary_fact.sql`, so the
  exporter and the report cannot reach different answers from the same rows.
- Scope: 16 players across 16 matches since 2026-08-31, one of them official. They re-POST
  by themselves once this is live, because `sent.json` is keyed by a payload hash and
  `gameTeam` is in it — but only the matches inside the 48-hour window. The rest need
  `--match-id` runs, and the site needs keep-the-prac#TBD to rebuild a fixture it has
  already linked.
