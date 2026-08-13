# Recovered match-1 stats — full breakdown (2026-08-13)

Source: `tests/e2e_stats/fixtures/regression-2026-08-13-match1/` — a full
2-half `dod_anzio` match, replayed offline from a captured game log through
`hlstats.pl` after the live 4-match Lane B series lost its DB to a
WSL/Docker restart mid-run. See `PRODUCTION_ROLLOUT_STATUS.md` for how this
was recovered. This is real bot-driven play, not synthetic/scripted data.

## Volume

| Table | Rows |
|---|---|
| Players | 17 (17 bot) |
| Frags | 352 (half 1: 190, half 2: 162) |
| Assists (`PlayerPlayerActions`) | 57 |
| Cap breaks (`PlayerActions`) | 3 |
| Damage events | 877 |
| Suicides | 15 |
| Flag positions | 5 |

## Per-player leaderboard

| Player | Kills | Deaths | Suicides | K:D | Assists | Headshots | HS% | Last-flag-defense kills |
|---|---|---|---|---|---|---|---|---|
| Ferro | 42 | 20 | 0 | 2.10 | 3 | 4 | 9.5 | 11 |
| Claire | 30 | 12 | 1 | 2.50 | 4 | 3 | 10.0 | 9 |
| Ash | 25 | 23 | 3 | 1.09 | 3 | 2 | 8.0 | 3 |
| Bishop | 25 | 25 | 2 | 1.00 | 4 | 2 | 8.0 | 3 |
| Burke | 24 | 26 | 2 | 0.92 | 9 | 3 | 12.5 | 2 |
| Dallas | 24 | 26 | 2 | 0.92 | 4 | 2 | 8.3 | 3 |
| Hicks | 23 | 26 | 1 | 0.88 | 0 | 4 | 17.4 | 2 |
| Cutter | 21 | 25 | 1 | 0.84 | 5 | 4 | 19.0 | 2 |
| Dracula | 19 | 13 | 0 | 1.46 | 3 | 1 | 5.3 | 5 |
| Lambert | 19 | 27 | 0 | 0.70 | 1 | 3 | 15.8 | 4 |
| Hudson | 18 | 26 | 0 | 0.69 | 3 | 2 | 11.1 | 4 |
| GLaDOS | 17 | 12 | 0 | 1.42 | 3 | 0 | 0.0 | 1 |
| Crash | 16 | 10 | 0 | 1.60 | 3 | 2 | 12.5 | 8 |
| Kane | 15 | 27 | 1 | 0.56 | 4 | 4 | 26.7 | 2 |
| Ripley | 12 | 32 | 1 | 0.38 | 4 | 1 | 8.3 | 1 |
| Pyramid | 11 | 11 | 1 | 1.00 | 2 | 1 | 9.1 | 5 |
| Parker | 11 | 11 | 0 | 1.00 | 2 | 3 | 27.3 | 1 |

Note: `hlstats_PlayerNames.headshots` itself stays 0 for every player (a
known daemon-side gap — the frag_context marker technique updates the
`Frags` row directly via SQL, bypassing the in-memory stat accumulator that
column reads from). The headshot counts above come from
`hlstats_Events_Frags.headshot`, which is correct and is what all Phase 5–7
tooling checks.

## Damage — the 100-cap in action

877 hits logged, capped raw damage at avg 59.7 / max 500. **104/877 (11.9%)**
exceeded 100 raw and were capped for stats purposes.

| Weapon | Hits | Avg raw | Max raw | Avg capped | Over-cap count |
|---|---|---|---|---|---|
| scopedkar | 32 | 160.8 | **400** | 86.4 | 22 |
| spring | 26 | 150.4 | **400** | 94.8 | 23 |
| garand | 46 | 108.2 | 300 | 89.9 | 16 |
| kar | 18 | 105.3 | 400 | 71.9 | 10 |
| k43 | 45 | 92.2 | 300 | 80.2 | 9 |
| 30cal | 40 | 83.9 | 212 | 69.9 | 5 |
| mg34 | 34 | 74.9 | 212 | 68.3 | 2 |
| bar | 79 | 64.9 | 212 | 59.2 | 4 |
| mortar | 39 | 43.1 | 288 | 34.8 | 6 |
| grenade2 | 19 | 48.8 | 83 | 48.8 | 0 |
| grenade | 27 | 45.6 | 79 | 45.6 | 0 |
| spade | 5 | 201.0 | **500** | 81.0 | 3 |
| bayonet | 1 | 200.0 | 200 | 100.0 | 1 |
| k43butt | 1 | 150.0 | 150 | 100.0 | 1 |
| mp44 | 93 | 41.5 | 125 | 40.9 | 2 |
| colt | 38 | 34.6 | 100 | 34.6 | 0 |
| m1carbine | 82 | 32.4 | 100 | 32.4 | 0 |
| luger | 42 | 32.2 | 100 | 32.2 | 0 |
| greasegun | 77 | 36.3 | 100 | 36.3 | 0 |
| mp40 | 126 | 30.0 | 100 | 30.0 | 0 |
| thompson | 3 | 30.0 | 30 | 30.0 | 0 |
| mg42 | 3 | 63.0 | 63 | 63.0 | 0 |
| amerknife | 1 | 60.0 | 60 | 60.0 | 0 |

Melee (`spade`, `bayonet`, `amerknife`) and one-shot bolt rifles
(`scopedkar`, `spring`, `kar`) supply almost all of the over-cap hits, as
expected — every SMG/pistol/semi-auto weapon in the list has zero.

## Break context (small sample — 3 breaks in one match)

| Player | Contesters | Time remaining | Capout |
|---|---|---|---|
| Dallas | 2 | 0.0s | no |
| Dracula | 2 | 0.5s | **yes** |
| Hicks | 2 | 2.4s | no |

## Flag positions (`dod_anzio`)

| Flag | Name | X | Y |
|---|---|---|---|
| 0 | POINT_ANZIO_LAUNDRY | -1495 | -326 |
| 1 | POINT_BRIDGE | 1040 | -288 |
| 2 | POINT_ANZIO_STREET | 448 | 800 |
| 3 | POINT_ANZIO_PLAZA | -698 | 923 |
| 4 | POINT_ANZIO_HILL | 1375 | 1682 |

## Suicides (15 total)

| Weapon | Count |
|---|---|
| world | 6 |
| grenade | 4 |
| grenade2 | 4 |
| pschreck | 1 |

## Candidate composite score — first draft, weights unvalidated

Not a proposal, a worked example: `kills(1.0) + assists(0.5) +
headshots(0.25) + last_flag_defense_kills(1.0) + cap_breaks(2.0) -
deaths(0.5)`. Damage is deliberately **not** weighted yet — it needs
team-share normalization first (a 500-damage match on the losing side isn't
worth the same as on the winning side), which this single-match dataset
can't establish on its own.

| Player | Kills | Deaths | Assists | HS | LFD | Breaks | Draft score |
|---|---|---|---|---|---|---|---|
| Ferro | 42 | 20 | 3 | 4 | 11 | 0 | **45.50** |
| Claire | 30 | 12 | 4 | 3 | 9 | 0 | **35.75** |
| Dracula | 19 | 13 | 3 | 1 | 5 | 1 | 21.25 |
| Crash | 16 | 10 | 3 | 2 | 8 | 0 | 21.00 |
| Ash | 25 | 23 | 3 | 2 | 3 | 0 | 18.50 |
| Dallas | 24 | 26 | 4 | 2 | 3 | 1 | 18.50 |
| Burke | 24 | 26 | 9 | 3 | 2 | 0 | 18.25 |
| Bishop | 25 | 25 | 4 | 2 | 3 | 0 | 18.00 |
| Hicks | 23 | 26 | 0 | 4 | 2 | 1 | 15.00 |
| Cutter | 21 | 25 | 5 | 4 | 2 | 0 | 14.00 |
| GLaDOS | 17 | 12 | 3 | 0 | 1 | 0 | 13.50 |
| Pyramid | 11 | 11 | 2 | 1 | 5 | 0 | 11.75 |
| Hudson | 18 | 26 | 3 | 2 | 4 | 0 | 11.00 |
| Lambert | 19 | 27 | 1 | 3 | 4 | 0 | 10.75 |
| Parker | 11 | 11 | 2 | 3 | 1 | 0 | 8.25 |
| Kane | 15 | 27 | 4 | 4 | 2 | 0 | 6.50 |
| Ripley | 12 | 32 | 4 | 1 | 1 | 0 | **-0.75** |

Two things worth noting, not conclusions:
- Raw-kills ranking and the composite mostly agree at the top, but **Crash**
  moves from 13th in raw kills into the top 4 once last-flag-defense is
  weighted — the kind of clutch-defense contribution a kills-only board
  hides entirely.
- **Ripley** goes negative — 32 deaths against 12 kills outweighs 4 assists
  and 1 headshot. Whether a negative score is desirable (vs. a floor at 0)
  is a scoring-policy decision, not a data question.

## Reproduce this

```
scripts/explore_fixture.py tests/e2e_stats/fixtures/regression-2026-08-13-match1/hlstatsx-fixture.sql
```
runs inside the `ktp-lane-b:dev` image (needs `tests/` and `scripts/`
mounted) and prints all of the per-player breakdowns above. Edit the query
dict in that script to try different composite weights against this same
real dataset without needing Lane B running again.