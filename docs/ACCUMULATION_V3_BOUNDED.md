# Bounded accumulation v3

Status: experimental shadow. This is an accumulation ledger, not KTPR.

## Design rules

1. No event produces negative points. Teamkills, suicides, deaths, failed
   pushes, and lost flags remain descriptive facts.
2. Each enemy death has a fixed 100-point base budget when reliable
   victim-life damage exists.
3. Each unique capture has one fixed pool, regardless of how many player-credit
   rows were emitted.
4. Context bonuses are positive, capped, explainable, and backed by event IDs.
5. One combat event can convert into only the highest applicable objective
   outcome. A capout supersedes an overlapping middle/ordinary capture.
6. Missing evidence disables context or selects an explicit fallback. It is
   never silently inferred as zero or fabricated.
7. Individual movement stays private. Only derived `position_points` may enter
   the shareable report.

The executable profile is
`config/analytics/accumulation_v3_bounded.toml`; the engine is
`scripts/accumulation_v3.py`.

## Combat budget

For each enemy death:

```text
60 points -> killer's confirmation/finisher award
40 points -> divided by capped effective damage to that victim in that life
```

| Effective damage | Killer | Contributor | Total |
|---|---:|---:|---:|
| Killer 100 | 100 | 0 | 100 |
| Killer 50, teammate 50 | 80 | 20 | 100 |
| Killer 30, teammate 70 | 72 | 28 | 100 |
| Killer 1, teammate 99 | 60.4 | 39.6 | 100 |

The assist label remains descriptive and currently requires at least 50 damage.
It does not create another independent score on top of the damage share.

If victim-life or per-hit damage evidence is unavailable, the report records a
warning and uses the explicit interim fallback:

```text
100 * kills + 50 * assists + 0.02 * opponent damage
```

Team/self damage is never included.

## Sustained streaks and shutdowns

Only the 60-point finisher portion receives the death-free streak premium:

```text
finisher streak bonus = 60 * 0.10 * min(streak_index - 1, 5)
```

The finisher values are 60, 66, 72, 78, 84, and 90 from the sixth kill onward.
A streak resets on death, suicide, half change, or full reset. A teamkill does
not score and cannot create a streak bonus.

Ending a streak longer than three creates a small positive shutdown award:

```text
shutdown = min(25, 5 * (enemy_streak - 3))
```

Nothing is subtracted from the player whose streak ended.

## Fast personal chains

Personal enemy kills no more than five seconds apart are collapsed into one
maximal chain. Overlapping 2k/3k windows cannot stack.

| Chain | Bonus |
|---:|---:|
| 2k | 10 |
| 3k | 25 |
| 4k | 45 |
| 5k+ | 70 |

## Captures and objective conversion

Every unique capture has a 100-point pool split evenly over the credited
cappers. Two credited players receive 50 each; three receive 33.33 each.

Recent combat contribution can also earn one fixed conversion pool:

| Highest outcome within 30 seconds | Pool |
|---|---:|
| Ordinary flag | 25 |
| Reviewed middle flag | 50 |
| Validated capout | 150 |

The pool is distributed by the players' effective combat contributions, with
linear time decay. A contribution immediately before the objective has full
weight; at 30 seconds it has zero weight. Fast personal chains receive a small
weighting preference inside the fixed pool, but never enlarge it.

Three or more qualifying deaths from at least two killers are labeled as a
coordinated team push. Their common conversion pool is shared rather than
credited to one arbitrary player.

Middle classification requires reviewed map topology. Capout classification
requires trustworthy ownership state. When those gates fail, the capture is
treated as ordinary and the unavailable higher pool is not awarded.

## Contextual cap breaks

A break begins at 25 points and can gain bounded positive context:

- up to 35 for stopping an imminent capture;
- up to 20 for multiple contesters; and
- 20 for a validated prevented capout/last-flag loss.

The event maximum is 100. Missing break context uses only the 25-point base.

## Position

Position remains a private calculation with a shareable derived total. The v3
profile adds diminishing value for consecutive unopposed samples near the same
objective:

- first 30 seconds: 1.00x;
- 30–90 seconds: 0.50x;
- beyond 90 seconds: 0.25x.

Active contest, leaving the radius, or changing objective resets the run.
Territory, active-contest, attacking/holding, last-flag, and per-half cap rules
remain configured rather than hard-coded.

## Accumulation versus efficiency

Every report publishes total points and points per observed minute. Total
points measure match contribution; points per minute supports substitute and
partial-match comparisons. Neither is an official skill rating.

## Model comparison

`scripts/compare_accumulation_models.py` emits the legacy v2, immediate
damped/no-penalty fallback, and bounded v3 side by side. A rank change is a
review prompt, not automatic evidence that a weight is correct.
