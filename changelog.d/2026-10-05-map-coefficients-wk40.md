### Map coefficients refitted after week 40; anzio joins the table (2026-10-05)

Week 40 put 11 officials on the board, 9 of them on **dod_anzio** — a map that
had no officials at all and so had been pricing on the league-wide 2.0 prior
despite 82 half-games of practice volume. It now has a fitted coefficient.

| map | ships | own fit | official halves | weight | was |
|---|---|---|---|---|---|
| dod_anzio | **1.362** | 1.213 | 18 | 0.47 | — (2.0 fallback) |
| dod_harrington | 1.636 | 1.793 | 18 | 0.47 | 1.673 |
| dod_lennon5_b1 | 1.188 | 0.909 | 22 | 0.52 | 1.240 |
| dod_thunder2 | 2.728 | 4.097 | 18 | 0.47 | 2.779 |

Pooled 1.4956 over 76 halves, up from 1.5923 over 54.

**The existing maps barely moved.** harrington's own fit went 1.773 → 1.793,
lennon5's 0.888 → 0.909, thunder2's unchanged (it gained no new officials). A
per-map fit that is stable week to week is the evidence that it is measuring the
map rather than the week — and it is a sharp contrast with the interruption
bands, which moved a great deal on comparable sample growth. Coefficients are
fit on thousands of samples a map; bands have tens of events a cell.

Practice is still rejected, and by a wider margin than last week: held-out loss
on officials is 0.6517 alone, 0.6539 with 12-mans, 0.6532 with all practice.

Schema 24 → 25 so the corpus regenerates onto the new values.
