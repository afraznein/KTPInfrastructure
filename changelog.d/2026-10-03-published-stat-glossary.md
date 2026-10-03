### `scripts`: every published stat now declares what it is and what unit it is in (2026-10-03)

Public DTO: top-level `glossary`, contract `analytics-report-dto-v1.8.0` ->
`v1.9.0` (additive only; the site accepts any `analytics-report-dto-v1.`
prefix).

### Why

The ratings block has always carried its own `definition` and `display_scale`.
Nothing else did. The box score, `flag_swing` and `accumulation` shipped 36
numbers with no definition a reader could reach, and that has now caused the
same class of misreading twice:

- a displayed KAST of 125 was read as a percentage. It is +1.67 sigma on the
  `max(50, 100 + 15z)` index, and a share cannot exceed 100;
- earlier, a consumer read the model's `normalization: per_match_z_scores`
  metadata as describing the already-scaled published `rating`, applied a
  second z-transform, and flattened every value to exactly 100.0 on every
  match page (keep-the-prac #679/#691).

`KTPR_DISPLAY_SCALE` exists because of the second one. This generalises it:
`unit` is declared for every published field, from a closed vocabulary
(`count`, `share_0_1`, `percent_0_100`, `ratio`, `damage`, `points`,
`seconds`, `per_minute`, `index`, `rank`), so a consumer never infers a unit
from a magnitude. `raw_accuracy` is `share_0_1` and reads 0.28, not 28.

### What it is

`FIELD_GLOSSARY` in `scripts/analytics_report_dto.py`, published per report as
`glossary.fields` alongside `glossary.contract`. Each entry carries `what` (one
reader-facing sentence), `unit`, and `caveat` where the number misleads without
one — `damage_per_life` excludes the unfinished final life of each half,
`score` is DoD's objective score and not a capture count, `impact_index` is
100-centred but is **not** comparable to the KTPR rating, `raw_accuracy` cannot
distinguish a Garand reload discharge from a miss.

Text is transcribed from `docs/MATCH_METRIC_CONTRACT_V1.md`, which stays
normative; this is its machine-readable projection. A hand-maintained glossary
page was the alternative and was rejected: it drifts the moment a coefficient
moves, which is the whole reason the `rating_methodology` payload reads its
numbers from source.

### Guards

`tests/unit/test_analytics_report_dto.py::Glossary` pins that every
`PLAYER_FIELDS` entry and every emitted `accumulation` / `flag_swing` row key
has a definition, so a newly published field cannot ship undefined. Both guards
were verified to fail when the thing they guard is broken, rather than only
observed to pass.

### Found on the way: the multikill window disagrees with its contract

`docs/MATCH_METRIC_CONTRACT_V1.md` defines `fast_multikill_frag` as a chain
whose *consecutive* kills are no more than **5 s** apart. The code
(`scripts/match_timelines.py::_multikills`) clusters kills within
`multikill_seconds` of the chain's **first** kill, and `TimelineConfig`
defaults that to **10.0** — which is what production reports carry
(`shadow_timelines.config.multikill_seconds: 10.0`). So both the window and the
rule differ from the normative document, and `fast_2k` feeds the KTPR v2
multikill component.

This change does not pick a side. The `fast_*k` definitions read the window off
the report rather than restating it, so the published glossary describes the
numbers that were actually built. Reconciling the contract with the code is a
separate decision for the metric owner, and a contract version bump either way.
