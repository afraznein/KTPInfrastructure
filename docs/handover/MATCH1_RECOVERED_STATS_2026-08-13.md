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

## Candidate composite score — v2, weights still unvalidated

v1 (first pass, same-day) used `kills + assists*0.5 + headshots*0.25 +
lfd*1.0 + breaks*2.0 - deaths*0.5` — raw damage unweighted, deaths a flat
subtraction, no flag-capture credit. Revised per feedback:

- **Damage is now normalized by half win/loss**, not raw. Each player's
  capped damage that half is multiplied ×1.2 if their team won that half,
  ×0.8 if they lost, ×1.0 on a tie. Team-per-half comes from the majority
  `killerRole` on their frags that half (`ktp_match_players`/
  `ktp_match_stats` are both empty in this fixture — those KTP aggregation
  tables aren't populated by an offline Perl-only replay, only by
  KTPMatchHandler live in-game — so there's no stored team/winner column to
  read instead). Half winner = the team with more flag captures that half.
  **This is a derived proxy, not a captured ground truth** — flagging that
  plainly rather than presenting it as measured fact.
- **Flag captures are now counted and weighted.** Not in the DB yet —
  `dod_capture_area` is a stock DoD engine event, already flowing through
  the log, but nothing in this project's schema seeds an `hlstats_Actions`
  row for it, so the daemon currently drops it silently. Parsed directly
  from the raw log for this exploration instead (`scripts/composite_v2.py`).
  Each capture is credited in full to every participating player (a 2-person
  cap isn't split — both genuinely contributed presence), weighted by that
  flag's value.
  - **On "which flags should count more":** this match only ever contested
    2 of the 5 flags (`POINT_BRIDGE`, `POINT_ANZIO_PLAZA` — 23 captures
    each, tied exactly). The other 3 (`LAUNDRY`, `STREET`, `HILL`) are
    presumably home/uncontested flags and never generated a capture event
    at all. With only 2 data points, tied, **this one match's data can't
    support real per-flag value differentiation** — that needs either your
    own knowledge of `dod_anzio`'s actual flag topology, or capture-count
    data pooled across more matches to see which flags are genuinely rarer
    to take. Implemented the mechanism (inverse-frequency weighting,
    mean 1.0) so it's ready to differentiate the moment there's a real
    signal; today it's a no-op tie.
- **Deaths no longer subtract anything.** Replaced with an additive
  `efficiency` term = `kills / (deaths + 1)`, weighted separately (×3.0
  here). This only ever adds, never subtracts, and specifically rewards a
  high kill:death ratio as its own signal — a 20-kill/5-death game now
  scores meaningfully higher than a 20-kill/25-death game with identical raw
  kills, without ever penalizing the second player's honest kill count.
- **Floor is naturally 0**, not enforced — every term in the sum is
  non-negative (kills, assists, headshots, lfd, breaks, weighted flag caps,
  win/loss-scaled damage, and kills/(deaths+1) can't go below 0), so the
  only way to score exactly 0 is to have contributed literally nothing —
  no kill, no damage, no assist, nothing. A player who only dealt damage and
  never got a kill still scores above 0 from the damage term alone.

Draft weights: `kill=1.0, assist=0.5, headshot=0.25, lfd=1.0, cap_break=2.0,
damage_per_100=0.5, flag_cap=1.5, efficiency=3.0` — all still first-guess,
not tuned against any target distribution.

| Player | Kills | Deaths | Assists | HS | LFD | Breaks | Flag caps | Norm. dmg | Efficiency | Score |
|---|---|---|---|---|---|---|---|---|---|---|
| Ferro | 42 | 20 | 3 | 4 | 11 | 0 | 12 | 5134.4 | 2.00 | **105.17** |
| Claire | 30 | 12 | 4 | 3 | 9 | 0 | 4 | 3955.0 | 2.31 | **74.45** |
| Burke | 24 | 26 | 9 | 3 | 2 | 0 | 10 | 3666.0 | 0.89 | 67.25 |
| Ash | 25 | 23 | 3 | 2 | 3 | 0 | 7 | 3669.2 | 1.04 | 61.97 |
| Dallas | 24 | 26 | 4 | 2 | 3 | 1 | 5 | 2920.6 | 0.89 | 56.27 |
| Cutter | 21 | 25 | 5 | 4 | 2 | 0 | 8 | 2343.8 | 0.81 | 52.64 |
| Bishop | 25 | 25 | 4 | 2 | 3 | 0 | 4 | 2573.0 | 0.96 | 52.25 |
| Hicks | 23 | 26 | 0 | 4 | 2 | 1 | 7 | 2129.6 | 0.85 | 51.70 |
| Dracula | 19 | 13 | 3 | 1 | 5 | 1 | 4 | 2710.0 | 1.36 | 51.37 |
| Lambert | 19 | 27 | 1 | 3 | 4 | 0 | 6 | 2730.0 | 0.68 | 48.94 |
| GLaDOS | 17 | 12 | 3 | 0 | 1 | 0 | 8 | 2425.0 | 1.31 | 47.55 |
| Crash | 16 | 10 | 3 | 2 | 8 | 0 | 2 | 2017.0 | 1.45 | 43.45 |
| Hudson | 18 | 26 | 3 | 2 | 4 | 0 | 3 | 2359.6 | 0.67 | 42.30 |
| Kane | 15 | 27 | 4 | 4 | 2 | 0 | 6 | 1939.8 | 0.54 | 40.31 |
| Parker | 11 | 11 | 2 | 3 | 1 | 0 | 6 | 1270.4 | 0.92 | 31.85 |
| Ripley | 12 | 32 | 4 | 1 | 1 | 0 | 5 | 1042.2 | 0.36 | 29.05 |
| Pyramid | 11 | 11 | 2 | 1 | 5 | 0 | 1 | 1400.0 | 0.92 | 28.50 |

What changed vs. v1, concretely:
- **Ripley no longer goes negative** (v1: -0.75) — floor is genuinely 0 now,
  and Ripley's real damage/assist contribution puts them at 29.05, last
  place but honestly positive, not punished into the negatives for a bad
  K:D on top of already contributing less.
- **Burke jumps from 7th (v1: 18.25) to 3rd (67.25)** — 9 assists and 10
  flag captures were nearly invisible in v1's formula (assist weight 0.5,
  no flag-cap term at all) but are real, substantial team contributions
  once counted properly.
- **Ferro's lead widens** (v1: 45.50, roughly 1.27x runner-up Claire's
  35.75; v2: 105.17, roughly 1.41x Claire's 74.45) — Ferro's damage,
  efficiency (best K:D at 2.00), and flag-cap count (12, tied-highest) all
  point the same direction, so a formula that credits more signals agrees
  with kills-only more strongly here, not less.

## Reproduce this

```
scripts/explore_fixture.py tests/e2e_stats/fixtures/regression-2026-08-13-match1/hlstatsx-fixture.sql
```
prints the per-player breakdowns (kills, assists, damage, headshot rate,
last-flag-defense) and the v1 composite.

```
scripts/composite_v2.py tests/e2e_stats/fixtures/regression-2026-08-13-match1/hlstatsx-fixture.sql \
    tests/e2e_stats/fixtures/regression-2026-08-13-match1/match1-raw.log.gz
```
prints the v2 composite above, including the half win/loss derivation and
flag-capture weighting. Both run inside the `ktp-lane-b:dev` image with
`tests/`/`scripts/` mounted. Edit either script's weight dict to try
different values against this same real dataset without needing Lane B
running again.

## Known gap this composite surfaces: flag captures aren't persisted

`dod_capture_area` events are real, frequent (144 lines / ~46 discrete
capture events in this one match), and currently going nowhere — no
`hlstats_Actions` row is seeded for them in this project's migrations, so
the daemon's dispatcher finds no matching action and drops the line
silently (same dispatch mechanism that already handles `cap_break`, just
missing the seed for this specific action). Formalizing this as a real
Phase (its own migration + daemon wiring, following the exact pattern
`migrate_004_cap_break_action.sql` already established) is the natural next
step if flag-capture counting is wanted as a persistent stat rather than a
log-parsed one-off for exploration.