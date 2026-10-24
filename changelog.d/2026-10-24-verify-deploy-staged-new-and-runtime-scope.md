### `docs`: what `ktp-verify-deploy` RED and `--check-runtime` GREEN actually mean (2026-10-24)

Both were read wrong on a live wave, in opposite directions, and neither fact was written anywhere
the reader of the output would meet it.

- **A deliberately staged `.new` scores `overall=RED` on every instance, the reference included.**
  Measured the night before an activation: `drift`, `extra`, `missing` and `missing_partial` all
  zero on 24 of 24 with `new_files` the only cause. The tool is a post-activation gate and the
  docstring said `.new files lingering`, which reads as a failed swap — so correct work looks like
  a fault, and the obvious response is to halt the wave. The docstring and the post-activation
  verify step now say so, and point at the wave ledger.
- **`--check-runtime` is reference-relative.** It does diff loaded version and sha per plugin, so
  the help text's promise holds; what it cannot answer is whether the INTENDED build went live. A
  reference that also failed to swap reads GREEN fleet-wide on the old one. The plugin's own
  version cvar over rcon is the absolute leg, and wants a nonsense-cvar control on the same socket
  so an empty body is distinguishable from a wrong value.
