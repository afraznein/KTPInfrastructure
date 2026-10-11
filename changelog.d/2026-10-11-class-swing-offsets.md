### `scripts`: KTPR's swing component is corrected for the player's class (2026-10-11)

`flag_swing` attributes flag control, and a sniper's job is to hold mid without
standing on it, so the component was reading the role as absence.

#### The measurement

Handed to this lane by `infra-hidden-value-plays` (coordination `9dd648b`),
raised by drew from a 0.84 KTPR gap between two snipers. Both sniper classes sit
several standard errors below zero on the swing component, while the overall
rating gap is **not** significant across eight classes because positive output
partly offsets it — so the correction belongs to the component, not the rating.

Reproduced before accepting, and the numbers had already drifted with matches
played, which is why the fit is a committed artifact rather than a constant.

That the deficit is *attribution* rather than lower contribution was the one
thing the handover assumed. Measured within player, which controls for skill:
across the 44 players who played sniper in some officials and another class in
others, sniping costs **0.568 sigma of swing (−5.19 SE)** while the team's win
rate does not move (**+0.034, +0.70 SE**). Same player, same result for the
team, lower measured swing.

#### The correction

`config/class_swing_offsets.json`, fitted by
`scripts/fit_class_swing_offsets.py` (`--write` / `--check`, mirroring
`fit_map_coefficients.py`). `ktpr_v2` subtracts the player's class offset from
the swing z and then **re-centres**, so the component still averages zero —
`normalization: per_match_z_scores` is published metadata and a consumer once
applied a second z-transform after reading it (keep-the-prac #679/#691), so the
claim has to stay exactly true.

Structure reused rather than invented: `own_offset` beside the shrunk `offset`
with `shrinkage_weight = n / (n + k)`, as `map_coefficients.json` does. The
pooled target is zero because a class offset is already a deviation from the
league mean, so a thin class keeps the league value on its own — class 2 at
n=2 shrinks +0.372 to +0.057.

`k` is derived, not chosen. The maps' k=20 counts half-games while n here counts
match-players, so copying it would barely shrink anything; instead the
empirical-Bayes ratio sigma²/tau² from how separated the classes measurably
are. Current fit: **k=11.06**, `within_class_sd` 0.9697 (≈1, the sanity check
that the units are right), class 14 −0.5018 → **−0.4202**, class 5 −0.4404 →
**−0.3298**.

#### What it does not do

**It does not close the match that raised it.** Both players there were class
14, so a class offset moves them together and the 0.84 gap survives untouched.
That gap is `kast_f`: nicholson went 2–6 across the ten flag fights with 3
openings lost against nightmare's 7–4 with none, under a 1.50 whole-match K/D.
Recorded here because the class fix will otherwise look like an answer to it.
