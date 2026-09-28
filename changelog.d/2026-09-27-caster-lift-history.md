### `analytics`: record per-class lift each run, and retract two numbers that did not survive (2026-09-27)

- `caster_recall.py --record <path.tsv>` appends one row per play class per run
  and reports what moved since the previous recording, including whether the
  three weighted classes have settled. The stopping rule for this work is "the
  numbers stopped moving" rather than a sample size, and that is unanswerable
  from memory.
- It earned itself on the first comparison. Going from 25 priced plays to 36
  (the delayed casts), deep collapse fell from 1.77 to 1.06 and attempt from
  1.78 to 0.00 — both had been measured on n=3 and n=2. Retracted in the module
  header and the README rather than left standing.
- What held: the cap-out denial zero, now on n=10. A human watching does not
  register these at all, which is the reason to price them.
- Class-specific language is a dead end as well. In-sample it fired on 9 of 36
  priced windows against a 16% baseline (lift 1.56), but the phrases were chosen
  by looking at the same windows they were scored on. Evaluated
  leave-one-cast-out it fires on 0% of held-out priced windows against a 10%
  baseline. The phrase scan stays for reading what was said; it is not a signal.
- New `caster_weekly.py coverage`: the cast corpus covers 7 of 24 officials
  since the season opened, 29%. Any verdict drawn from it is about that subset.
- Store keys beginning with `_` (`_consent`, `_channels`) are configuration and
  are no longer read as casts.
