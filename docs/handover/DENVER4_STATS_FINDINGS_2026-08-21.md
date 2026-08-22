# Denver 4 live-stat findings — 2026-08-21

## Scope

Match `1.3-6574-DEN4` was a 12-player, two-half live test on
`dod_thunder2`. This review used read-only production queries and the local
evidence bundle under `artifacts/den4-1.3-6574-20260821`; it changed no live
data.

## What worked

| Source | Result |
|---|---:|
| Enemy frags | 549 |
| Contextualized frags | 548 |
| Generic assists | 86 |
| Damage events | 946 |
| HP-capped damage | 70,057 |
| Position samples | 4,796 |
| Capture-credit rows | 26 |
| Unique capture transitions | 11 |
| Flag-state rows | 22 |
| Cap-break credits | 5 |

Damage reconciled exactly with the match aggregate. Position samples landed
at 243 distinct game times per half, approximately one snapshot every five
seconds. The 548 spatially complete kills support weapon-distance analysis:
122 close, 219 medium, 183 long, and 24 very-long engagements under the
current 512/1024/2048-unit bands.

## What was not live-validated

- Producer match/half/game-time/epoch coverage was 0/549 frags and 0/946
  damage events.
- `ktp_life_events` and `ktp_assist_events` contained no rows for this match;
  both tables were empty globally at review time.
- Therefore life-aware revenge, canonical timed assists, producer-clock
  damage conversion, and other strict timed joins were not validated by this
  match. KTPAMXX PR #45 is the producer-side dependency for the clock fields.

Schema presence must not be treated as proof that a producer is active. The
canary evidence gate now measures per-match activation separately.

## Objective-classification warning

The five observed flag indexes had initial ownership rows, but only the
central flag changed ownership, the four outer flags appeared neutral, and no
static `ktp_flag_positions` rows existed for this server/map. All five
cap-break credits were consequently tagged `is_capout=1`, while 133/549 kills
were tagged `is_last_flag_defense=1`.

Raw ownership, capture, and position evidence remains useful. Capout and
last-flag-defense must be suppressed unless static positions cover every
observed flag and each half's timeline demonstrates a complete, non-neutral
two-team partition. This permits legitimate all-neutral map starts while still
rejecting the incomplete central-only state observed here.

## Cap-break grain

The five cap-break credits represented three observable incidents: two
grenade multikills produced two credits each, and one single kill produced one
credit. Existing rows lack victim, flag, and incident identifiers, so these
figures must be labeled separately:

- `cappers_stopped`: 5
- `break_incident_lower_bound`: 3

The lower bound groups the best currently available event time, player, and
position fields. A later producer/schema change should add victim ID, flag ID,
and a stable incident ID.

## Delivery state

The coordinated follow-up remains local in two repositories:

- KTPInfrastructure `feat/den4-data-quality-gates`, based directly on the
  post-PR-#131 `preprod` tip. It adds only read-only report checks and tests.
- KTPAMXX `fix/den4-objective-topology-gate`, stacked temporarily on the
  still-open PR #44 tip. It changes the shared capout predicate and bumps
  `stats_logging` to 1.16.2.

Neither branch performs database or fleet writes. After KTPAMXX PR #44 merges,
rebase its Denver branch onto the resulting `preprod` tip, run the exact
two-repository Lane B bundle, and only then open the two preprod PRs together.
