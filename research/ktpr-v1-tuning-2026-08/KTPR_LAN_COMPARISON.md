# KTPR Comparison — Philly LAN 2026 (tournament)
Old vs Current vs New KTPR over the **Sat+Sun `match_type=0` tournament matches** (55 matches; Friday's for-fun games and warmups excluded), aggregated per player from `hud_player_stats`. Names from `roster.csv`.
- **Players:** 61  ·  **Max matches by any player:** 13
- **Source of truth for the math:** [ktpr_engine.py](ktpr_engine.py); all weights in [weights.toml](weights.toml). Scope in `ktpr_mysql.py`.
- **Note:** old/current are the Excel formulas (multiplicative); **new** is the redesigned team-contribution formula (see §New). Old/current were tuned on season-long gold data, so read them for the *relative* picture.

---

## How the Excel KTPR works (old & current)
The two Excel formulas are **multiplicative** — a core skill term, scaled up for objectives and down for dying, times a constant. (**New** uses a different, additive team-contribution structure — see §New.)
```
KTPR = SCALE
     x [ min(K/D, 1.1) x (Kills/Half / median_regulars(Kills/Half)) ]   # core
     x ( 1 + flag_bonus )                                              # objectives
     x ( 1 - death_penalty )                                           # dying
```
- **Regular player** = played >= `MAX(floor, 0.66 x max_matches)` matches; medians are taken over regulars so casuals don't skew the baseline.
- **flag_bonus** = `log(flags/half + 1)/log(25)` + a relative term vs the median, capped.
- **death_penalty** = how far deaths/half exceed the median, scaled & capped (below-median dying becomes a small bonus).

**Baselines used here (current profile, over 48 regulars, threshold = 8.58 matches):** median Kills/Half = 24.16, Deaths/Half = 22.41, Flags/Half = 3.92, Damage/Half = 3751, Breaks/Half = 0.24.

---

## The three calculations

### Old KTPR
| knob | value | meaning |
|---|---|---|
| SCALE | 0.8 | final multiplier |
| K/D cap | 1.1 | ceiling on the skill ratio |
| flag weight (regular / non) | 0.5 / 0.3 | relative-flag reward |
| flag cap | 0.4 | max objective bonus |
| death weight / cap | 0.2 / 0.15 | death penalty |
| participation floor | 0.0 | floor on the regular threshold |

### Current KTPR
| knob | value | meaning |
|---|---|---|
| SCALE | 0.75 | final multiplier |
| K/D cap | 1.1 | ceiling on the skill ratio |
| flag weight (regular / non) | 0.3 / 0.2 | relative-flag reward |
| flag cap | 0.35 | max objective bonus |
| death weight / cap | 0.2 / 0.15 | death penalty |
| participation floor | 0.34 | floor on the regular threshold |

### New KTPR (team-contribution formula)
A different shape from old/current: a **weighted average of normalized contributions** (1.0 = average tournament player), so support stats can substitute for kills and one-dimensional fraggers normalize toward the middle. Judged **within each role** (Rifle/Sniper/Heavy/SMG).

| knob | value | meaning |
|---|---|---|
| scale | 1.0 | average player scores ~1.0 |
| kill_exp | 0.8 | <1 = diminishing returns on kill volume |
| tw_kill / tw_kd | 1.0 / 1.5 | kill volume vs K/D efficiency |
| tw_assist / tw_damage | 1.0 / 0.5 | assist & damage contribution |
| tw_flag / tw_break | 0.7 / 1.0 | objective contribution (breaks valued high) |
| dmg_interaction / assist_interaction | 1.2 / 1.2 | how much low kills amplify the damage & assist terms |
| ratio_floor / ratio_cap | 0.55 / 2.5 | one weak/strong stat can't drag/spike too far |
| class_normalize | True | compare each player to their own role's median |
| role_weights | {'Rifle': 1.0, 'Sniper': 1.0, 'Heavy': 1.0, 'SMG': 1.0} | per-role final multiplier |

---

## Worked example — #1 by New KTPR: **dicE[: :]stealthlol**
Raw per-half: K/D=1.15, Kills/Half=24.81, Deaths/Half=21.65, Assists/Half=1.32, Damage/Half=3752, Flags/Half=3.27, Breaks/Half=0.24 over 13 matches.

- **Excel core** = min(1.15, 1.1) x (24.81 / 24.16) = 1.10 x 1.03 = **1.130**
- **Old** = core x flag/death factors x 0.8 = **1.24**
- **Current** = core x (lower flag reward) x 0.75 = **1.15**
- **New (team)** = weighted average of their kill/K-D/assist/damage/flag/break contributions vs the **Sniper** median, x death adjust = **1.30** (a different structure — see §New).

---

## Full ranked comparison (sorted by New KTPR)
`Δ` = rank change Current→New (＋ = moved up under New). **Style** = KTPR quality tier + playstyle (profile vs global median).

| # | Player | role | M | K/D | KDA | K/H | D/H | A/H | Dmg/H | Fl/H | Br/H | Old | Cur | **New** | Δ | Style |
|--:|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| 1 | dicE[: :]stealthlol | Sniper | 13 | 1.15 | 1.21 | 24.8 | 21.7 | 1.3 | 3752 | 3.3 | 0.2 | 1.24 | 1.15 | **1.30** | +14 | Ace Fragger |
| 2 | [bb] bR0M ＃4BIGDAWG | Rifle | 8 | 1.10 | 1.31 | 24.4 | 22.1 | 4.5 | 4078 | 6.3 | 0.5 | 1.25 | 1.13 | **1.29** | +15 | Ace Flagger |
| 3 | [NATO] baiko ＃gubbe.se | Rifle | 12 | 1.12 | 1.37 | 25.0 | 22.3 | 5.6 | 4473 | 4.2 | 0.5 | 1.28 | 1.16 | **1.28** | +11 | Ace All-rounder |
| 4 | iH.hildebrand? | Sniper | 11 | 1.69 | 1.77 | 23.6 | 14.0 | 1.0 | 3864 | 3.6 | 0.1 | 1.29 | 1.17 | **1.27** | +8 | Ace Sharpshooter |
| 5 | ßℓυ†н \| TillJim | Rifle | 12 | 1.11 | 1.31 | 26.2 | 23.7 | 4.7 | 4256 | 3.3 | 0.7 | 1.30 | 1.20 | **1.26** | +6 | Ace Flagger |
| 6 | ßℓυ†н \| nicholson | Rifle | 12 | 1.05 | 1.23 | 21.1 | 20.1 | 3.6 | 3483 | 3.3 | 0.9 | 1.03 | 0.94 | **1.25** | +27 | Ace Flagger |
| 7 | NoSo ! arachnid | Sniper | 12 | 1.13 | 1.18 | 24.4 | 21.6 | 1.2 | 3546 | 2.2 | 0.2 | 1.02 | 1.03 | **1.19** | +17 | Ace Fragger |
| 8 | NoSo ! Savage¬ | Rifle | 12 | 1.21 | 1.36 | 27.2 | 22.6 | 3.5 | 4372 | 3.8 | 0.4 | 1.39 | 1.25 | **1.12** | -3 | Ace All-rounder |
| 9 | ßℓυ†н \| patten | Sniper | 12 | 1.09 | 1.17 | 22.6 | 20.8 | 1.8 | 3741 | 2.5 | 0.1 | 1.00 | 0.99 | **1.12** | +18 | Ace Fragger |
| 10 | iH.Seanality | Rifle | 11 | 1.25 | 1.49 | 26.5 | 21.2 | 5.0 | 4618 | 6.7 | 0.1 | 1.37 | 1.24 | **1.12** | -3 | Ace All-rounder |
| 11 | ßℓυ†н \| p12 | Rifle | 12 | 0.85 | 1.09 | 21.9 | 25.7 | 6.0 | 3757 | 4.5 | 0.3 | 0.84 | 0.76 | **1.12** | +35 | Veteran All-rounder |
| 12 | [bb] Polak | Rifle | 9 | 1.15 | 1.31 | 25.2 | 21.8 | 3.4 | 4022 | 6.1 | 0.3 | 1.29 | 1.17 | **1.11** | +1 | Veteran Flagger |
| 13 | dicE[: :]player | Heavy | 13 | 1.18 | 1.38 | 26.3 | 22.3 | 4.5 | 3737 | 4.8 | 0.5 | 1.34 | 1.21 | **1.10** | -3 | Veteran Flagger |
| 14 | [bb] cK- ＃phillylan2026 | Rifle | 10 | 1.02 | 1.18 | 28.0 | 27.4 | 4.4 | 4516 | 4.6 | 0.4 | 1.26 | 1.14 | **1.10** | +2 | Veteran Flagger |
| 15 | b.   steve | Sniper | 8 | 0.93 | 0.95 | 24.4 | 26.2 | 0.5 | 3665 | 3.0 | 0.4 | 0.99 | 0.92 | **1.09** | +22 | Veteran Flagger |
| 16 | iH.kanguhhh?! | Heavy | 11 | 1.17 | 1.45 | 23.8 | 20.4 | 5.8 | 3749 | 4.5 | 0.3 | 1.24 | 1.12 | **1.09** | +3 | Veteran All-rounder |
| 17 | [bb] piff ＃4Monty | Heavy | 10 | 1.15 | 1.34 | 30.8 | 26.8 | 5.2 | 4599 | 6.2 | 0.5 | 1.51 | 1.36 | **1.08** | -15 | Veteran All-rounder |
| 18 | [$] billbsod | SMG | 12 | 0.73 | 0.86 | 22.1 | 30.4 | 4.0 | 3315 | 6.5 | 0.5 | 0.69 | 0.63 | **1.08** | +34 | Veteran Flagger |
| 19 | ****JTM   LaNGoNdd<3vt | Rifle | 11 | 1.30 | 1.53 | 24.6 | 19.0 | 4.3 | 3981 | 2.4 | 0.2 | 1.10 | 1.10 | **1.07** | +2 | Veteran Generalist |
| 20 | dicE[: :]m00cat :D | Heavy | 13 | 1.05 | 1.28 | 22.3 | 21.2 | 4.9 | 3275 | 3.5 | 0.5 | 1.10 | 0.99 | **1.05** | +6 | Veteran Flagger |
| 21 | ****JTM   jules | Heavy | 11 | 1.38 | 1.56 | 28.5 | 20.5 | 3.5 | 4202 | 4.4 | 0.4 | 1.48 | 1.33 | **1.05** | -18 | Veteran All-rounder |
| 22 | [NATO] Sq =))) | Rifle | 12 | 1.02 | 1.17 | 21.3 | 20.8 | 3.0 | 3563 | 3.2 | 0.3 | 1.00 | 0.93 | **1.02** | +14 | Veteran Generalist |
| 23 | iH.monday | Heavy | 11 | 1.19 | 1.41 | 24.0 | 20.1 | 4.4 | 3500 | 5.7 | 0.2 | 1.25 | 1.13 | **1.02** | -5 | Veteran Flagger |
| 24 | [bb] reppoĦ | Heavy | 10 | 0.87 | 1.06 | 20.1 | 23.1 | 4.2 | 3164 | 4.5 | 0.5 | 0.81 | 0.73 | **1.01** | +24 | Veteran Flagger |
| 25 | iH.vertex | Rifle | 11 | 1.38 | 1.56 | 30.2 | 21.9 | 4.0 | 4696 | 4.5 | 0.1 | 1.55 | 1.40 | **1.01** | -24 | Veteran Fragger |
| 26 | ****JTM   ihatealiceglass | Heavy | 11 | 1.09 | 1.31 | 24.3 | 22.3 | 4.9 | 3304 | 3.7 | 0.4 | 1.23 | 1.11 | **1.00** | -6 | Regular Generalist |
| 27 | [NATO] Hub | Heavy | 12 | 0.96 | 1.15 | 25.2 | 26.2 | 5.0 | 3968 | 3.9 | 0.5 | 1.08 | 0.98 | **1.00** | +1 | Regular All-rounder |
| 28 | dicE[: :]element | Rifle | 13 | 1.14 | 1.30 | 28.8 | 25.4 | 4.3 | 4764 | 4.4 | 0.2 | 1.43 | 1.29 | **1.00** | -24 | Regular Generalist |
| 29 | [$] cory <3 liah,jkimbro,rdk | Rifle | 12 | 0.99 | 1.14 | 26.2 | 26.5 | 4.1 | 4383 | 4.2 | 0.3 | 1.16 | 1.05 | **1.00** | -6 | Regular Generalist |
| 30 | [NATO] NoName^ | Rifle | 12 | 1.30 | 1.51 | 26.0 | 20.0 | 4.1 | 4293 | 3.7 | 0.1 | 1.36 | 1.23 | **1.00** | -22 | Regular Fragger |
| 31 | iH.s i k <3 n a t | Rifle | 11 | 1.21 | 1.44 | 26.3 | 21.7 | 5.0 | 4499 | 3.5 | 0.1 | 1.35 | 1.22 | **0.99** | -22 | Regular All-rounder |
| 32 | NoSo ! CrankinHawg | Heavy | 12 | 1.06 | 1.25 | 23.8 | 22.5 | 4.5 | 3532 | 3.2 | 0.4 | 1.12 | 1.05 | **0.98** | -10 | Regular Generalist |
| 33 | ßℓυ†н \| kroD- | Heavy | 12 | 0.91 | 1.08 | 25.9 | 28.3 | 4.6 | 3815 | 5.7 | 0.5 | 1.04 | 0.94 | **0.98** | +1 | Regular Flagger |
| 34 | ****JTM   ddorito | Rifle | 11 | 1.18 | 1.37 | 27.3 | 23.2 | 4.6 | 4528 | 3.0 | 0.2 | 1.30 | 1.25 | **0.97** | -28 | Regular Generalist |
| 35 | dicE[: :]Gorilla[bc] <3Cooper | Rifle | 13 | 0.99 | 1.15 | 24.6 | 24.9 | 4.1 | 3903 | 3.7 | 0.2 | 1.10 | 0.99 | **0.95** | -10 | Regular Generalist |
| 36 | [NATO] Ho0liii <3 nakk | Sniper | 12 | 0.90 | 0.96 | 19.8 | 21.9 | 1.3 | 3170 | 4.0 | 0.0 | 0.84 | 0.76 | **0.95** | +11 | Regular Fragger |
| 37 | NoSo ! Bausch | Rifle | 12 | 0.97 | 1.17 | 22.8 | 23.5 | 4.7 | 4065 | 3.4 | 0.2 | 1.00 | 0.91 | **0.95** | +1 | Regular Support |
| 38 | dicE[: :]warchyld[dd] | Rifle | 13 | 0.69 | 0.85 | 17.5 | 25.3 | 3.9 | 3069 | 5.5 | 0.2 | 0.55 | 0.49 | **0.94** | +18 | Regular Flagger |
| 39 | [NATO] nightmare＃old | Heavy | 12 | 1.04 | 1.24 | 22.0 | 21.1 | 4.1 | 3500 | 3.3 | 0.3 | 1.06 | 0.97 | **0.94** | -9 | Regular Generalist |
| 40 | ****JTM   mogers 4ky <3h | Rifle | 11 | 0.99 | 1.21 | 19.3 | 19.5 | 4.4 | 3346 | 3.2 | 0.1 | 0.88 | 0.82 | **0.93** | +3 | Regular Generalist |
| 41 | ****JTM   ian | Sniper | 11 | 1.24 | 1.30 | 21.6 | 17.4 | 1.0 | 3324 | 2.2 | 0.0 | 0.94 | 0.95 | **0.93** | -10 | Regular Fragger |
| 42 | b.   e p y o n | Heavy | 8 | 0.99 | 1.16 | 21.9 | 22.2 | 3.9 | 3209 | 5.3 | 0.2 | 1.00 | 0.91 | **0.93** | -2 | Regular Flagger |
| 43 | NoSo ! Khoi | Rifle | 12 | 0.70 | 0.88 | 18.9 | 26.8 | 4.8 | 3161 | 6.1 | 0.1 | 0.59 | 0.54 | **0.93** | +11 | Regular Flagger |
| 44 | [bb] pb_ | Rifle | 10 | 0.94 | 1.10 | 25.1 | 26.8 | 4.5 | 4134 | 4.7 | 0.2 | 1.05 | 0.95 | **0.93** | -12 | Recruit Generalist |
| 45 | NoSo ! yayme | Heavy | 12 | 1.00 | 1.20 | 21.6 | 21.6 | 4.3 | 3233 | 4.2 | 0.2 | 1.01 | 0.91 | **0.91** | -6 | Recruit Generalist |
| 46 | [bb]3SidedQuarter | Sniper | 9 | 0.87 | 0.91 | 19.9 | 22.8 | 0.8 | 2941 | 4.2 | 0.1 | 0.80 | 0.72 | **0.91** | +3 | Recruit Generalist |
| 47 | b.   hey hi <3 dustbin | Rifle | 8 | 0.88 | 1.04 | 23.7 | 26.9 | 4.2 | 4020 | 5.6 | 0.1 | 0.93 | 0.84 | **0.91** | -6 | Recruit Flagger |
| 48 | ßℓυ†н \| incite[bc] | Heavy | 12 | 0.76 | 0.96 | 21.3 | 28.0 | 5.7 | 3405 | 3.3 | 0.3 | 0.70 | 0.64 | **0.90** | +3 | Recruit Generalist |
| 49 | b.   sTarK_ x_0 <3＃77 | Heavy | 8 | 0.85 | 1.02 | 24.8 | 29.2 | 5.1 | 3576 | 4.3 | 0.3 | 0.91 | 0.82 | **0.88** | -7 | Recruit Generalist |
| 50 | b.   o[bb]y | Rifle | 8 | 0.78 | 0.87 | 26.0 | 33.3 | 2.9 | 4400 | 4.2 | 0.3 | 0.85 | 0.77 | **0.87** | -5 | Recruit Flagger |
| 51 | [$] nomistizzle | Rifle | 12 | 0.93 | 1.07 | 26.8 | 28.9 | 4.2 | 4422 | 3.6 | 0.2 | 1.08 | 0.98 | **0.86** | -22 | Recruit Generalist |
| 52 | [$] hypnotik_ 0_x | Heavy | 12 | 0.64 | 0.80 | 18.4 | 28.6 | 4.5 | 2883 | 5.7 | 0.2 | 0.52 | 0.47 | **0.82** | +6 | Recruit Flagger |
| 53 | uR[TM]* HLAH | Sniper | 8 | 0.85 | 0.90 | 21.2 | 25.1 | 1.2 | 3334 | 2.2 | 0.0 | 0.72 | 0.70 | **0.82** | -3 | Recruit Fragger |
| 54 | uR[TM]* Kevs Dolmetscher | Rifle | 8 | 0.63 | 0.80 | 16.0 | 25.4 | 4.3 | 2739 | 3.5 | 0.1 | 0.45 | 0.41 | **0.81** | +7 | Recruit Generalist |
| 55 | [$] nein_ | Heavy | 12 | 0.69 | 0.85 | 20.5 | 29.7 | 4.6 | 3197 | 4.4 | 0.1 | 0.62 | 0.56 | **0.79** | -2 | Recruit Generalist |
| 56 | [$] tokih | Sniper | 12 | 0.87 | 0.91 | 22.8 | 26.1 | 0.9 | 3607 | 2.7 | 0.0 | 0.79 | 0.78 | **0.79** | -12 | Recruit Fragger |
| 57 | b.   тωὶﮐт | Rifle | 8 | 0.70 | 0.84 | 18.5 | 26.3 | 3.6 | 3134 | 3.7 | 0.1 | 0.58 | 0.53 | **0.78** | -2 | Recruit Generalist |
| 58 | uR[TM]* Ke:>^1.de | Heavy | 8 | 0.86 | 0.98 | 28.8 | 33.3 | 3.8 | 4504 | 4.6 | 0.3 | 1.04 | 0.94 | **0.78** | -23 | Recruit Flagger |
| 59 | uR[TM]* Jee＃minou.exe | Heavy | 8 | 0.61 | 0.75 | 18.2 | 29.6 | 3.9 | 2704 | 2.9 | 0.4 | 0.47 | 0.44 | **0.78** | +1 | Recruit Flagger |
| 60 | uR[TM]* zamp0lit | Rifle | 8 | 0.65 | 0.75 | 19.2 | 29.5 | 2.9 | 3264 | 3.8 | 0.2 | 0.54 | 0.49 | **0.77** | -3 | Recruit Flagger |
| 61 | uR[TM]* SirSnipeys | Rifle | 8 | 0.60 | 0.68 | 19.8 | 33.0 | 2.8 | 3307 | 4.8 | 0.1 | 0.50 | 0.45 | **0.71** | -2 | Recruit Flagger |

---

## Biggest movers, Current → New
| Player | Cur rank | New rank | Δ | why |
|---|--:|--:|--:|---|
| ßℓυ†н \| p12 | 46 | 11 | +35 | rewarded by assists/damage/breaks |
| [$] billbsod | 52 | 18 | +34 | rewarded by assists/damage/breaks |
| ****JTM   ddorito | 6 | 34 | -28 | leaned on kills/flags the new stats discount |
| ßℓυ†н \| nicholson | 33 | 6 | +27 | rewarded by assists/damage/breaks |
| [bb] reppoĦ | 48 | 24 | +24 | rewarded by assists/damage/breaks |
| iH.vertex | 1 | 25 | -24 | leaned on kills/flags the new stats discount |
| dicE[: :]element | 4 | 28 | -24 | leaned on kills/flags the new stats discount |
| uR[TM]* Ke:>^1.de | 35 | 58 | -23 | leaned on kills/flags the new stats discount |
| [$] nomistizzle | 29 | 51 | -22 | leaned on kills/flags the new stats discount |
| [NATO] NoName^ | 8 | 30 | -22 | leaned on kills/flags the new stats discount |
| iH.s i k <3 n a t | 9 | 31 | -22 | leaned on kills/flags the new stats discount |
| b.   steve | 37 | 15 | +22 | rewarded by assists/damage/breaks |

---

*Regenerate anytime: `python make_report.py` (via PowerShell). Tune weights in `weights.toml` and re-run to see rankings shift.*
