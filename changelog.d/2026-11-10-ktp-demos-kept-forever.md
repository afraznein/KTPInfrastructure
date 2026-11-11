### `scripts`: official `ktp` demos and HUD replays are kept permanently (2026-11-10)

By operator ruling, official `ktp` match demos are never retired.
`ktp-demo-retention.sh` no longer enrolls `ktp/` in its `RETENTION` table, and the
script already leaves any unenrolled subdirectory alone, so `ktp/` demos drop out of
the daily delete pass, the `DRY_RUN` counts and the Sunday preview. The preview loop
now skips a tier with no retention entry instead of reading an unset key under
`set -u`. `draft/` stays at 180 days, `12man/` and `scrim/` at 90.

`ktp-hud-archive-retention.sh` follows the demo archive tier for tier: a tier with no
`RETENTION` entry is kept, and `ktp` (match types `ktp` and `ktpOT`) has none. Those
matches are logged in the `skipped:` line as `kept`, a reason of their own, distinct
from `untyped`. A `player_state.jsonl` inside a kept match still goes on its own
30-day clock.

The tests that used `ktp` as their deletable tier now use `draft`, and new cases pin
that a `ktp` demo and an official HUD match past every window survive a delete run
and appear in neither the dry-run counts nor the preview.
