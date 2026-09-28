### flag_swing can be fitted per map (2026-09-28)

The league plays one map a week, and the maps are not the same game. Fitted on
54 labelled S10 halves, the flag coefficient comes out 1.76 on harrington, 1.51
on lennon5_b1 and **4.52 on thunder2**, against a pooled 1.99 — which itself
lands almost exactly on the hardcoded 2.0 prior, so the league-wide value is
not wrong so much as it is an average nobody plays on. A two-flag lead of five
reads p=0.69 under the pooled model and p=0.86 on thunder2.

It agrees with the other measurement from the opposite direction: thunder2 is
where flags rarely turn over (0.33 cap-outs per half against harrington's 3.88),
so holding them decides more.

`FlagSwingConfig.for_map()` resolves a map's coefficients from
`MAP_COEFFICIENTS`, and `build_flag_swing_shadow` takes `map_name`. An explicit
config still overrides the table, so the fit driver can score one vector across
every map.

**The table ships EMPTY, so this changes nothing yet** — no schema bump, no
regeneration. `fit_team_score_labels.py` now emits `map_coefficients` ready to
paste in; filling the table is a separate, deliberate commit once the fit has
run on the production path.

Shrinkage, not independent fits: a map arrives with 16-20 halves, and held out
over halves, per-map fits LOST to pooled on harrington (0.0038) and lennon5
(0.0029) while winning on thunder2 (0.0347). `PRIOR_HALVES = 20` is the weight
at which a map earns half its own fit. Shrinkage weighs halves rather than
samples: samples inside a half share one label, so counting them would let one
long half pose as independent evidence.
