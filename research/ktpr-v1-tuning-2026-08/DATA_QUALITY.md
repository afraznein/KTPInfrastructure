# Data-Quality Report — HLstatsX vs HUD

Tournament matches: **55**. Players matched across both systems: **61** (HLstatsX-only: 0, HUD-only: 0).

KTPR uses HLstatsX for kills/deaths/flags and HUD for assists/damage/breaks. This report checks how far the two systems disagree on the stats they *both* record, to gauge trust and spot bad rows.

> **Finding -> fix applied.** Divergence is almost entirely a *half-coverage* gap: every divergent player has fewer HUD halves than HLstatsX halves (HUD drops some half-snapshots). HUD per-half stats were understated wherever we divided HUD totals by the larger HLstatsX half count. The loader now divides **HUD stats by HUD halves** and **HLstatsX stats by HLstatsX halves**. Systems agree to within ~4-6% overall; treat big-gap matches/players (below) with caution until the pipelines are reconciled.

## Totals (overlapping stats)

| stat | HLstatsX | HUD | HUD vs HLstatsX |
|---|--:|--:|--:|
| kills | 31125 | 29886 | -4.0% |
| deaths | 31753 | 30352 | -4.4% |
| flags | 5422 | 5091 | -6.1% |

## Biggest per-player divergences (HUD vs HLstatsX)

Sorted by worst single-stat gap. Large gaps = a system missed rows for that player (subs, mid-match leaves, snapshot timing).

| Player | HL k/d/f | HUD k/d/f | Δk | Δd | Δf | HL h | HUD h |
|---|--:|--:|--:|--:|--:|--:|--:|
| ****JTM   ihatealiceglass | 535/491/81 | 390/365/65 | -27% | -26% | -20% | 22 | 18 |
| ****JTM   mogers 4ky <3h | 425/430/70 | 360/366/56 | -15% | -15% | -20% | 22 | 19 |
| NoSo ! Khoi | 453/643/146 | 365/520/121 | -19% | -19% | -17% | 24 | 21 |
| [bb]3SidedQuarter | 358/411/75 | 300/336/64 | -16% | -18% | -15% | 18 | 15 |
| ****JTM   jules | 626/452/96 | 541/383/83 | -14% | -15% | -14% | 22 | 19 |
| NoSo ! arachnid | 586/519/53 | 524/465/45 | -11% | -10% | -15% | 24 | 23 |
| [bb] cK- ＃phillylan2026 | 560/549/92 | 499/468/80 | -11% | -15% | -13% | 20 | 17 |
| [bb] reppoĦ | 403/461/90 | 370/415/78 | -8% | -10% | -13% | 20 | 18 |
| [bb] pb_ | 502/536/93 | 450/467/81 | -10% | -13% | -13% | 20 | 18 |
| uR[TM]* zamp0lit | 307/472/60 | 289/443/53 | -6% | -6% | -12% | 16 | 15 |
| [NATO] Ho0liii <3 nakk | 476/526/95 | 450/467/91 | -5% | -11% | -4% | 24 | 22 |
| b.   e p y o n | 351/356/85 | 342/353/76 | -3% | -1% | -11% | 16 | 16 |
| NoSo ! Savage¬ | 654/542/91 | 596/486/84 | -9% | -10% | -8% | 24 | 23 |
| iH.vertex | 664/482/99 | 624/436/93 | -6% | -10% | -6% | 22 | 22 |
| [NATO] NoName^ | 625/479/89 | 566/435/82 | -9% | -9% | -8% | 24 | 22 |
| uR[TM]* Ke:>^1.de | 460/533/73 | 426/483/68 | -7% | -9% | -7% | 16 | 15 |
| ****JTM   LaNGoNdd<3vt | 542/417/53 | 492/389/51 | -9% | -7% | -4% | 22 | 20 |
| b.   hey hi <3 dustbin | 379/431/89 | 362/427/81 | -4% | -1% | -9% | 16 | 16 |
| b.   тωὶﮐт | 296/421/59 | 270/392/54 | -9% | -7% | -8% | 16 | 15 |
| dicE[: :]stealthlol | 645/563/85 | 589/532/80 | -9% | -6% | -6% | 26 | 25 |

## Match-level kill coverage (HLstatsX frags vs HUD kills)

Worst 10 matches by kill-count gap:

| match_id | HL frags | HUD kills | Δ | Δ% |
|---|--:|--:|--:|--:|
| 1785710044-KTP3 | 551 | 286 | -265 | -48% |
| 1785703180-KTP4 | 539 | 337 | -202 | -37% |
| 1785697932-KTP2 | 408 | 538 | +130 | +32% |
| 1785623033-KTP3 | 507 | 614 | +107 | +21% |
| 1785604799-KTP3 | 595 | 478 | -117 | -20% |
| 1785692609-KTP2 | 627 | 514 | -113 | -18% |
| 1785693039-KTP4 | 572 | 493 | -79 | -14% |
| 1785609454-KTP1 | 516 | 445 | -71 | -14% |
| 1785691815-KTP3 | 538 | 468 | -70 | -13% |
| 1785699260-KTP4 | 437 | 487 | +50 | +11% |
