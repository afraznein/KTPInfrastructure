### Added
- `ktpr_engine.compute_reliability` and the `reliability_report` MCP tool: the KTPR error bar
  from `KTPR_SIDE_CORRECTION.md` S2b. Each player's two halves of a match are paired and
  correlated (`r_halves`, double-entry so half order cannot matter), stepped up to a full match
  with Spearman-Brown (`r_full`), and turned into `SEM = sd(KTPR) * sqrt(1 - r_full)` plus a
  rank-equivalent (median number of players within one SEM, each side). A player-match with one
  half or with overtime halves is counted and left out, not guessed at; fewer than ten pairs, or
  a non-positive `r_halves`, publishes no SEM and says why. The values are NOT side-adjusted:
  S2a is descoped by ruling, so the side effect counts as noise and the SEM is conservative —
  the result carries `side_adjusted: false` so that cannot be lost. Nothing existing changes;
  `ktpr_mysql.py` and `weights.toml` are untouched.
