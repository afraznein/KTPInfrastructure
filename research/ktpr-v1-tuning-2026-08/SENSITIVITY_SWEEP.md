# KTPR Team-Formula — Sensitivity Sweep

Each section varies ONE knob; all others stay at the `weights.toml` baseline. **ρ** = Spearman rank-correlation vs the baseline board (1.0 = identical order). Columns show each anchor player's **rank** at that setting. `*` marks the current baseline value.

Anchors: hildebrand, TillJim, nicholson, billbsod, piff, s i k <3

## `kill_exp`

| value | ρ | hildebrand | TillJim | nicholson | billbsod | piff | s i k <3 | top 5 |
|---|---|---|---|---|---|---|---|---|
| 0.5 | 1.00 | 1 | 5 | 6 | 21 | 10 | 27 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |
| 0.6 | 1.00 | 1 | 5 | 6 | 22 | 10 | 26 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |
| 0.7 | 1.00 | 1 | 5 | 6 | 22 | 9 | 26 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |
| 0.8 * | 1.00 | 1 | 5 | 6 | 23 | 9 | 26 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |
| 0.9 | 1.00 | 1 | 5 | 6 | 23 | 9 | 26 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |
| 1.0 | 1.00 | 1 | 5 | 6 | 23 | 9 | 26 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |

## `tw_kd`

| value | ρ | hildebrand | TillJim | nicholson | billbsod | piff | s i k <3 | top 5 |
|---|---|---|---|---|---|---|---|---|
| 1.0 | 0.99 | 4 | 5 | 6 | 17 | 8 | 32 | dicE[:, [bb], [NATO], iH.hildebr, ßℓυ†н |
| 1.3 | 1.00 | 2 | 5 | 6 | 19 | 9 | 30 | dicE[:, iH.hildebr, [bb], [NATO], ßℓυ†н |
| 1.6 * | 1.00 | 1 | 5 | 6 | 23 | 9 | 26 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |
| 2.0 | 1.00 | 1 | 5 | 6 | 26 | 10 | 25 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |
| 2.5 | 0.99 | 1 | 5 | 6 | 32 | 11 | 23 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |

## `tw_break`

| value | ρ | hildebrand | TillJim | nicholson | billbsod | piff | s i k <3 | top 5 |
|---|---|---|---|---|---|---|---|---|
| 0.4 | 0.97 | 1 | 6 | 15 | 32 | 7 | 21 | iH.hildebr, [bb], iH.Seanali, [NATO], dicE[: |
| 0.6 | 1.00 | 1 | 5 | 7 | 27 | 8 | 24 | iH.hildebr, [bb], dicE[:, [NATO], ßℓυ†н |
| 0.8 * | 1.00 | 1 | 5 | 6 | 23 | 9 | 26 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |
| 1.0 | 0.99 | 2 | 5 | 6 | 20 | 9 | 31 | dicE[:, iH.hildebr, [bb], [NATO], ßℓυ†н |
| 1.2 | 0.98 | 5 | 3 | 6 | 17 | 10 | 34 | dicE[:, [bb], ßℓυ†н, [NATO], iH.hildebr |

## `tw_flag`

| value | ρ | hildebrand | TillJim | nicholson | billbsod | piff | s i k <3 | top 5 |
|---|---|---|---|---|---|---|---|---|
| 0.4 | 0.99 | 1 | 4 | 6 | 30 | 9 | 26 | iH.hildebr, dicE[:, [NATO], ßℓυ†н, [bb] |
| 0.6 | 1.00 | 1 | 5 | 6 | 25 | 10 | 26 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |
| 0.8 | 1.00 | 1 | 5 | 6 | 22 | 9 | 26 | iH.hildebr, [bb], dicE[:, [NATO], ßℓυ†н |
| 1.0 | 0.99 | 1 | 5 | 7 | 19 | 8 | 27 | iH.hildebr, [bb], dicE[:, [NATO], ßℓυ†н |

## `tw_assist`

| value | ρ | hildebrand | TillJim | nicholson | billbsod | piff | s i k <3 | top 5 |
|---|---|---|---|---|---|---|---|---|
| 0.4 | 1.00 | 1 | 5 | 6 | 22 | 9 | 28 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |
| 0.7 * | 1.00 | 1 | 5 | 6 | 23 | 9 | 26 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |
| 1.0 | 1.00 | 1 | 5 | 6 | 24 | 9 | 26 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |
| 1.3 | 0.99 | 1 | 5 | 6 | 22 | 10 | 26 | iH.hildebr, dicE[:, [NATO], [bb], ßℓυ†н |

## `dmg_interaction`

| value | ρ | hildebrand | TillJim | nicholson | billbsod | piff | s i k <3 | top 5 |
|---|---|---|---|---|---|---|---|---|
| 0.0 | 1.00 | 1 | 5 | 6 | 23 | 8 | 26 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |
| 0.3 | 1.00 | 1 | 5 | 6 | 23 | 9 | 26 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |
| 0.6 * | 1.00 | 1 | 5 | 6 | 23 | 9 | 26 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |
| 0.9 | 1.00 | 1 | 5 | 6 | 22 | 10 | 26 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |

## `assist_interaction`

| value | ρ | hildebrand | TillJim | nicholson | billbsod | piff | s i k <3 | top 5 |
|---|---|---|---|---|---|---|---|---|
| 0.0 | 1.00 | 1 | 5 | 6 | 24 | 8 | 26 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |
| 0.3 | 1.00 | 1 | 5 | 6 | 23 | 9 | 26 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |
| 0.6 * | 1.00 | 1 | 5 | 6 | 23 | 9 | 26 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |
| 0.9 | 1.00 | 1 | 5 | 6 | 22 | 10 | 26 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |

## `ratio_floor`

| value | ρ | hildebrand | TillJim | nicholson | billbsod | piff | s i k <3 | top 5 |
|---|---|---|---|---|---|---|---|---|
| 0.4 | 1.00 | 1 | 5 | 6 | 23 | 9 | 32 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |
| 0.55 * | 1.00 | 1 | 5 | 6 | 23 | 9 | 26 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |
| 0.7 | 1.00 | 1 | 5 | 6 | 24 | 9 | 25 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |

## `role_weights.Heavy`

| value | ρ | hildebrand | TillJim | nicholson | billbsod | piff | s i k <3 | top 5 |
|---|---|---|---|---|---|---|---|---|
| 1.0 * | 1.00 | 1 | 5 | 6 | 23 | 9 | 26 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |
| 1.05 | 0.98 | 1 | 5 | 7 | 27 | 6 | 31 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |
| 1.1 | 0.94 | 1 | 7 | 10 | 29 | 4 | 33 | iH.hildebr, dicE[:, [bb], [bb], [NATO] |
| 1.15 | 0.89 | 2 | 9 | 11 | 32 | 1 | 35 | [bb], iH.hildebr, dicE[:, dicE[:, ****JTM |

## `class_normalize` (within-role normalization)

| value | ρ | hildebrand | TillJim | nicholson | billbsod | piff | s i k <3 | top 5 |
|---|---|---|---|---|---|---|---|---|
| True | 1.00 | 1 | 5 | 6 | 23 | 9 | 26 | iH.hildebr, dicE[:, [bb], [NATO], ßℓυ†н |
| False | 0.80 | 13 | 5 | 7 | 25 | 1 | 28 | [bb], dicE[:, [bb], [NATO], ßℓυ†н |
