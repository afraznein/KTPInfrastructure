### Excursions: isolation is per map, not one distance for the league (2026-09-26)

The detector called a player "alone" at a flat 1200 units on every map, which
measured the map rather than the player. Over 87,958 samples taken while past
the enemy rear line, 1200 is exceeded by 18% of samples on lennon5 and 58% on
railroad2 — so the same rule was far too tight on the most-played map in the
pool and far too loose on the widest ones.

`ISOLATION_BY_MAP` now carries the p80 of each map's own distribution, and
`build_excursions` takes `map_name`. A map with no measured value falls back to
the old flat distance, so a new map in the pool degrades to previous behaviour
rather than failing. An explicit `isolation_units` still wins over the table —
that is how the sweep tooling pins one distance across every map to compare
them.

Corpus effect measured before the change: 3,707 excursions become 2,860.
harrington −48%, anzio −46%, thunder2 −45%, saints2 −49%, railroad2 −58%, and
lennon5 **+13%** — the one map where the flat rule was hiding real runs. Both
specimens behind this work survive and sharpen: the ATL2 solo HQ cap tightens
from a 50 s window to the 38 s the runner was genuinely alone for.

Schema 20 → 21, so the corpus regenerates and existing reports pick the new
thresholds up. `parameters.isolation_units_applied` and the block's caveat both
name the distance actually used, so a reader of a report never has to know the
table to know what was applied.
