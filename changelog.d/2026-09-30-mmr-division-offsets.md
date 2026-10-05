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

---

**Update, same day — seeding is now ON by default** (drew's ruling: *"this is just seeding, as
matches proceed and seasons finish this will become more and more accurate"*). `--no-division-seed`
turns it off, and that flag is how you get the un-seeded ladder for validating promotion and
relegation, which a seeded one cannot do without circularity.

Two things changed to make enabling it safe:

**The labels are built in the ladder's own player-id space.** The first cut read
`division_history.json`, which keys on **hlstatsx** ids and needs the data server's identity
bridge — but in CI the ladder keys on the **website's** player_id, so seeding would have matched
nobody and silently done nothing. Labels are now built inside the roster loop in
`build_league_matches`, from `season_team.division_id` the run already fetches, using whichever
pid that loop resolved. Most recent season wins, so a promoted player is seeded where they play
now.

**Whether a run was seeded is a published fact.** `weekly_summary.json` carries
`division_seeded` and `division_offsets`, and the `rating_methodology` payload carries
`mmr.division_seeding` — enabled, the offsets, how many players were labelled, and a plain-English
caveat. Seeded, it says the ordering is *"a prior, not a measurement of this player"* and that
these ratings cannot serve as independent evidence for promotion. Unseeded, it says ratings from
different divisions are **not on a common scale** and should not be compared. A reader looking at
bottom-gold against mid-silver is entitled to know which of those they are seeing.

Missing offsets now skip seeding rather than failing the run — the file is committed, so absence
means an old tree, not a misconfigured season — and the skip is visible in the published summary
rather than only in a log line.
