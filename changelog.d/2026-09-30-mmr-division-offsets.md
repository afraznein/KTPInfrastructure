### `mmr`: the cross-division gap is measured, and seeding is wired but OFF (2026-09-30)

League divisions never play each other — zero cross-division league matches in S9, not one team
in more than one division — so each division's rating pool is a disconnected graph anchored at
the model's starting μ by the *prior*, not by evidence. That is why a dominant silver player can
outrank a struggling gold one, and no amount of within-division data fixes it.

`scripts/mmr/division_fit.py` measures the gap on the only thing that bridges the divisions:
12-mans, of which **all 1,305 labelled ones mix divisions**. Per match, each labelled player's
K/D and damage-per-death are z-scored *within that match*, so map, teams, roster quality and era
all cancel. Result, on 4–6k player-matches per division:

| division | z(K/D) | μ offset |
|---|---:|---:|
| Gold | +0.375 | **+1.87** |
| Silver | −0.073 | 0.00 (baseline) |
| Bronze | −0.468 | **−1.64** |

Roughly 0.4σ per step, evenly spaced, and stable — Gold moves 0.007σ between the pre-S10 and
S10 eras, so the S9 labels still predict current play.

The fit runs on the data server and commits `division_offsets.json`, because CI pulls official
results with the public anon key and cannot see 12-mans — the same split as
`momentum_params.json`. Output is one row per division and carries no player rows.

`ladder.seed_from_divisions()` applies it as a **weak** prior: μ is offset, σ is left at the
model's starting value, so a division step is worth ~1.9μ against σ=8.33 and a handful of real
results overwrite it rather than the ordering calcifying. It refuses to touch a player who has
already earned a rating.

**`--use-division-seed` is off by default, and not because it is untuned.** Seeding MMR from
division makes MMR partly an echo of the division it was seeded from. That is fine if MMR is a
common-scale skill number and *circular* if MMR is also the evidence for promotion and
relegation — which is what `seeding_report.py` exists for. That call has to be made before this
is switched on, and the transparency page then has to say the ordering is a prior.

One deliberate asymmetry: a missing `division_offsets.json` or `division_history.json` is a hard
error, not a silent no-op. A seeding run that quietly seeded nobody would publish unseeded
ratings while the digest claimed otherwise.
