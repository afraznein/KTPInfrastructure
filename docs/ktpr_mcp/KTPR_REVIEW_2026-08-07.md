# KTPR review — 2026-08-07

Verified `ktpr_mcp.zip` + `KTPR_CALCULATION.md` + `WEIGHTS_GUIDE.md` against live
`hlstatsx_lan`. **The formula is sound and the docs are unusually good** — the four-profile
layout with the Excel formulas frozen as reproducible baselines is the right call, and the
worked examples showing *which term* carries each player are the most useful part.

Everything below was checked independently — re-derived from the raw data rather than by
running your code, so a matching answer means something.

## What checked out

- **Algebra.** All three worked examples re-derived from their own printed raws, without your
  engine. `score`, `death_adj` and `KTPR` reproduce for hildebrand, bR0M and p12 within display
  rounding. The formula in the doc is the formula that produced the numbers in the doc.
- **HLStatsX inputs — 12 of 12 exact.** kills, deaths, K/D and flags per half for all three
  players, over your 55-match set:

  | | kills/h | deaths/h | K/D | flags/h |
  |---|---|---|---|---|
  | hildebrand | 23.59 / 23.60 | 13.95 / 13.95 | 1.69 / 1.69 | 3.59 / 3.59 |
  | bR0M | 24.44 / 24.40 | 22.12 / 22.10 | 1.10 / 1.10 | 6.31 / 6.31 |
  | p12 | 21.92 / 21.90 | 25.71 / 25.70 | 0.85 / 0.85 | 4.54 / 4.54 |

- **Role medians.** Every HLStatsX-derived median reproduces exactly, both roles: Sniper and
  Rifle `kills`, `kd`, `flags`, `deaths` all within 0.2%. Regulars resolve to 48 of 61 at
  `matches >= max(0.34, 0.66 x 13) = 8.58`. Role assignment from most-spawned class lands right.
- **Roster alias overlap — checked, harmless.** `roster.csv` lists `[bb] bR0M ＃wetya` under two
  steam_ids. The second (`STEAM_0:1:961681828`) has **zero** tournament rows, so bR0M's stats
  aren't split across accounts. Worth knowing the overlap is in the file, but it changes nothing.

---

## 1. HUD half-count divergence — this one decides who is #1

`ktpr_mysql.py`'s docstring says *"per-half rates all use the HLstatsX half count (the primary
participation basis)."* The published numbers don't do that.

hildebrand and p12 reproduce exactly on assists/damage/breaks. **bR0M is low by 6.2-6.9% on all
three at once.** A uniform miss across three independent stats is a denominator, not data — and
it resolves exactly: his HUD sums cover **15** halves, his HLStatsX count is **16**.

It isn't one player. **31 of 61 players have fewer HUD halves than HLStatsX halves**, short by
1 to 4 — the HUD is missing `is_final=1` rows for player-halves that HLStatsX recorded.

Applying the documented rule to bR0M:

| | KTPR |
|---|--:|
| bR0M as published (HUD sums ÷ 15) | **1.296** |
| bR0M with HUD sums ÷ 16, per the docstring | **1.255** |
| hildebrand (unaffected — both counts agree) | **1.259** |

That reverses the #1 the doc narrates ("edges out hildebrand"). It also explains the only two
medians that missed: Rifle `assists` −6.3% and `damage` −7.5%, taken over a population with
mixed denominators.

**Neither choice is obviously wrong.** Dividing by HUD halves is a rate over the halves the HUD
actually observed; dividing by HLStatsX halves treats an uncovered half as zero contribution.
It's a real judgment call. But the code, the doc and the leaderboard have to pick the same one,
and right now they disagree silently for half the field — and the disagreement is load-bearing
at the top of the board.

## 2. Keying on `ktp_match_end` silently drops matches

Your selection takes `hud_events` rows where `event='ktp_match_end'` and the payload
`match_type=0`. Three curated tournament matches have a `ktp_match_start` but **never emitted a
`ktp_match_end`**, so they vanish from the input set — that's your 55 against the curated
index's 58.

| match_id | map | frags |
|---|---|--:|
| `1785613505-KTP4` | dod_lennon5_b1 | 1 |
| `1785689132-KTP4` | dod_harrington | 0 |
| **`1785715972-KTP1`** | **dod_harrington** | **539, across 13 players** |

Two are aborted starts and correctly ignored. The third is a real half of play currently absent
from every KTPR number. (It's also the match whose ID was mangled by a map-name quote bug we
repaired on 08-07 — but the missing `ktp_match_end` isn't hiding under the corrupted ID, it
genuinely never fired.)

Excluding an incomplete one-half match may well be right — but worth making it an explicit
completeness filter rather than a side effect of keying on an event that didn't fire. Selecting
from `ktp_match_start` (or from the curated index at
`KTPAntiCheat/docs/reviews/lan-match_index-2026-08-06.csv`) and filtering deliberately would do it.

## 3. Small one: the hildebrand break ratio isn't reproducible from the printed numbers

The example prints breaks `0.09` and a Sniper median of `0.08`, but uses `rb = 1.18`.
`0.09 ÷ 0.08 = 1.125`. The break median is ~0.08/half, so two decimals is too coarse for that
ratio — print breaks to 3-4 places in the examples and it reproduces.

---

## Two traps worth knowing (we hit both verifying)

Your code gets both right; these cost us a round each and both produce a *clean-looking* wrong
answer rather than an error.

- **Deaths must union `hlstats_Events_Teamkills`.** Omitting it made every death rate ~2% low and
  every K/D correspondingly high — *uniformly across all three players*, so it read like a
  plausible baseline difference rather than a bug.
- **Flag captures key on `actionId IN (337,338)`**, not on action code strings. Guessing code
  names returned **0 flags for every player** — which looks like "this player caps nothing".

And one for the data model generally: there are **three** Steam-ID shapes in play and they don't
join to each other — `ktp_ac_*` uses `STEAM_0:Y:Z` (and is *not* uniformly universe 0, one account
is `STEAM_1:`), `ktp_lan.lan_players` was normalised to the same on 08-07, and
`hlstats_PlayerUniqueIds.uniqueId` is bare `Y:Z` with **no universe digit**. The prefix to strip
for HLStatsX is `STEAM_0:`, not `STEAM_`.
