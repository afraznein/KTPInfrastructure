### Added
- `flag_swing.MAP_COEFFICIENT_CARRY_FORWARD` lets a re-cut map inherit its predecessor's fitted
  coefficients until the fitter has halves under the new stem, reported as
  `carried_forward_from:<stem>` so the judgement is visible in the report rather than folded into
  `fitted`. `dod_railroad2_s10b` is the first entry: it replaced `dod_railroad2_s10a` in the pool on
  2026-10-19 and was pricing every `p_allies`, `attributed_swing`, `key_moment` and `terminal_value`
  on the hardcoded `(2.0, 1.0)` prior instead of s10a's fit, on a map that is geometrically
  identical. A real fitted row wins over the table, so an entry goes inert without anyone removing it.
- `config/analytics/map_flag_facts.json` gains s10b's per-flag facts, carried from s10a with the
  provenance in `source`. Without it `map_scoring_facts.py --verify-flags` reports "observed in
  production, absent from the curated file" the first time the map is played.

### Changed
- `SCHEMA_VERSION` 32 -> 33. One report was already stored at 32 with prior-priced values, and the
  generator's only test for "already current" is that constant.
- `config/analytics/map_scoring.json` regenerated from the curated file; the one material change is
  the added `maps_by_name` row.
