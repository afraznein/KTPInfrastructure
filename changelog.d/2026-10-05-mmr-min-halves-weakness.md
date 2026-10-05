### `scripts/mmr`: README records the `min_halves` weakness (2026-10-05)

Documents that a per-map scoring fit passing the `min_halves=12` gate can still be wildly ill-conditioned (bootstrap p99 error 34.6%, max 1304%, with no guard firing), why the `max(0, ...)` clamp hides it, and the two candidate fixes. Docs only; the choice is the module owner's.
