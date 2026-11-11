### `scripts`: official `ktp` demos kept permanently; `12man` and `scrim` cut to 30 days (2026-11-10)

Two operator rulings, both 2026-11-10, applied to the HLTV demo archive and the HUD
observer's match archive alike.

Official `ktp` match demos are never retired. `ktp-demo-retention.sh` no longer
enrolls `ktp/` in its `RETENTION` table, and the script already leaves any
unenrolled subdirectory alone, so `ktp/` demos drop out of the daily delete pass,
the `DRY_RUN` counts and the Sunday preview. The preview loop now skips a tier with
no retention entry instead of reading an unset key under `set -u`.

`12man/` and `scrim/` drop from 90 days to 30; `draft/` stays at 180. Neither short
tier is copied offsite, so what the first run after install removes is gone for
good. Measured on the live archive the night of the ruling, that first run frees
about 124.5 GB: 78.6 GB of `12man` and 45.9 GB of `scrim` older than 30 days.

`ktp-hud-archive-retention.sh` follows the demo archive tier for tier: `12man` and
`scrim` at 30 days, and a tier with no `RETENTION` entry is kept, which is where
`ktp` (match types `ktp` and `ktpOT`) now sits. Those matches are logged in the
`skipped:` line as `kept`, a reason of their own, distinct from `untyped`. A
`player_state.jsonl` inside a kept match still goes on its own 30-day clock.

The tests that used `ktp` as their deletable tier now use `draft`, the 90-day
boundary cases move to 30, and new cases pin that a `ktp` demo and an official HUD
match past every window survive a delete run and appear in neither the dry-run
counts nor the preview, and that a `12man` or `scrim` item older than 30 days is
deleted while a 29-day one is not.
