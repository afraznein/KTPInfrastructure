### `scripts`: retention for the HUD observer's match archive (2026-11-10)

`/opt/hud-observer/matches` had no pruner at all: one directory per match since
2026-04-22, about 7.8 GB, growing every match day. `ktp-hud-archive-retention.sh`
gives it the demo archive's windows, because a HUD replay is only useful while the
demo it overlays still exists: `ktp`/`ktpOT`/`draft`/`draftOT` 180 days,
`12man`/`scrim` 90 days. A `player_state.jsonl`, if the observer ever persists the
per-tick stream, keeps its own 30-day clock inside a match that is otherwise kept.

The type is not read from `metadata.json` alone. The recorder writes
`matchType 0, half 0` for every match it auto-started, and 0 is COMPETITIVE, so
trusting it would hold most of those pickups for 180 days. A placeholder is
typed from the `match_type` the plugin stamps on its first event; a real
lifecycle start is typed from metadata and refused if its first event disagrees.
Age is the `events.jsonl` mtime, because `metadata.json` is rewritten on reap and
on a count repair.

Nothing outside the windows is touched: a `.noprune` file in a match directory,
an open match, a match whose `sourceServer` is not a fleet game server (LAN boxes
included), an unknown type, and a directory holding any file the script does not
recognise are all skipped and counted in the run's `skipped:` line. `DRY_RUN=1`
lists the delete set and removes nothing; `preview` reports what falls due in the
next week. Failures go to the ops-daily lane, the preview to ops-weekly.

Replayed against a metadata snapshot of the live archive, a dry run selects 555
matches (12man 422, scrim 125, ktp 8; about 2.15 GiB) and skips the one open match.
Not installed: `scripts/ktp-hud-archive-retention.cron` carries the schedule, and
installing it is an operator step.
