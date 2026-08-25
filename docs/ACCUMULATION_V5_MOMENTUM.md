# Accumulation v5: team momentum and Impact Index

Status: experimental shadow scoring. It is not KTPR and it applies no penalties.

## What v5 changes

V5 keeps bounded combat, progressive streaks, fast chains, capture pools, cap breaks,
and the four direct per-life positional components from v4. It removes two overlapping
awards—capture conversion and per-life sequence continuity—and replaces both with one
bounded team-momentum swing pool.

The public result has two deliberately separate values:

- **Impact Index** is the readable headline number.
- **Raw audit points** preserve the exact deterministic component calculation.

## Team momentum curve

The engine evaluates one aggregate state every five seconds. Team 1 is positive and
team 2 is negative. Each input is normalized to approximately `-1..+1`:

```text
raw state =
    0.35 × weighted flag territory
  + 0.25 × aggregate team field position
  + 0.20 × recent impactful kills
  + 0.10 × temporary manpower pressure
  + 0.10 × players applying pressure beyond mid

instant momentum = 100 × tanh(raw state)
smoothed momentum = 0.55 × instant + 0.45 × previous
```

Territory values are provisional: middle `1.50`, second flags `1.25`, first flags
`1.00`, with a `1.25×` multiplier for double caps. The scorer uses the reviewed
per-map flag order. Unknown ownership contributes zero and is reported as coverage;
it is never guessed.

Recent combat decays with a 15-second half-life. Consecutive kills within five seconds
receive a small impact weight increase up to `1.45×`. Manpower pressure decays with a
10-second half-life. This makes a quick three-kill opening visible without allowing an
old kill to dominate the remainder of a push.

The shareable curve is downsampled to 15 seconds and contains only half, time, and the
team-level momentum value. Player coordinates, paths, personal heatmaps, and component
timelines remain in the separately classified private audit.

Team identity is stable across halftime. The engine keeps raw Allies/Axis identity for
map direction and flag ownership, while an optional `momentum_team` on private samples
tracks the same six-player roster after sides switch. Without this separation, a graph
would silently change which players its positive line represented at halftime.

## Momentum episodes and player attribution

A candidate episode measures a 40-second swing. Capture-centered windows also compare
20 seconds before with 20 seconds after a capture. Only swings of at least 15 momentum
units qualify. Episodes cannot overlap, and at most 12 are retained per half.

The team-positive point pool is fixed before any player attribution:

```text
episode pool = min(150, max(0, team-positive swing - 15) × 2)
```

The pool is divided by positive evidence from:

- recent kills, weighted slightly toward the end of the swing;
- unique capture credit;
- forward progress during the episode;
- consequential presence beyond mid at the end of the episode.

These signals divide a fixed pool; they never create additional match points. A player
can receive no more than 600 momentum points per match. There are no negative points,
death penalties, or deductions for losing momentum.

This is intended to reward sequences such as defending a threatened flag, producing a
three-kill swing, taking mid, and continuing forward. A defensive player can earn a
meaningful share when the defense actually changes team state; passive defense is not
punished but does not automatically produce a swing award.

## Impact Index

For this experimental iteration, players observed for at least five minutes are
normalized against the qualified-player median raw points per minute:

```text
Impact Index = 75 × (player raw points per minute ÷ reference points per minute)^0.80
```

This places the middle of a match near 75 while allowing the strongest one or two
performances to rise toward or above 100. The `0.80` exponent dampens extreme event
volume without changing rank. It is intentionally not clamped.

The current match-median reference is provisional and **must not be compared between
matches**. Production automation should replace it with a versioned reference learned
from a qualified real-match corpus. The profile already accepts that external reference
as `match.impact_index_reference_ppm`, allowing historical reports to be regenerated
without changing the scoring formula.

## Privacy and automation boundary

Deterministic code owns scores, normalization, gates, and the aggregate SVG. A future
AI checkpoint may add narrative, flag suspicious evidence, and suggest calibration
questions, but it is hash-bound to the report and cannot alter points, privacy, quality
gates, or publication state.

Public artifacts may contain player names and derived score components, but never raw
individual positions. The SVG renderer accepts only the sanitized aggregate curve.

## Current validation

- Unit/scorer integration exercises bounds, attribution conservation, privacy, duplicate
  pool replacement, normalization, and bundle generation.
- The Denver 4 live 12-man produces 24 non-overlapping episodes across two halves,
  793.05 total momentum points, and no player above 114.75 momentum points. Its known
  ownership coverage is only 23.97%, so territory conclusions remain limited.
- Five Anzio bot fixtures produce 428.9–590.7 momentum points per match and keep every
  player below the 600-point cap. Every fixture reaches the 12-episode one-half review
  limit, showing that bot combat is useful for stress testing but not human calibration.

Before production scoring, validate the formula against multiple real matches, approve
a corpus normalization reference, inspect role distributions and episode false positives,
and keep the entire feature shadow-only until human review signs off.
