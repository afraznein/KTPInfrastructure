### `docs` + `tests`: the `get_entvar` spike (S0 of spatial KTPR) has been run, and it passes (2026-09-29)

`SPIKE_ENTVAR_GEOMETRY.md` gated spatial KTPR on whether ReAPI `get_entvar` works on
DoD in extension mode. It does. It was run on the local bot stack and a
production-topology control server, never on the fleet. A live player's origin matches
`dodx_get_user_origin` exactly, and every capture-area box read across nine maps is
bit-identical to `dodx_area_get_bounds`. Results, log evidence and the per-map T4
mismatch rates are in `docs/handover/SPIKE_ENTVAR_GEOMETRY_RESULTS.md`. The verdict is
appended to `KTPR_SPATIAL_PLAN.md` §1.

Three premises in the spike doc did not hold, and the write-up records each one. Entity 0
has no bounds in GoldSrc, so it cannot give map extents. Most control points on the maps
sampled have no capture area at all. And a flag's origin inside its box is not a valid
check. The diagnostic plugin is `tests/e2e_stats/diagnostics/KTPEntvarSpike.sma`.
