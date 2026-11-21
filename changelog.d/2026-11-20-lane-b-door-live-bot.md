### `lane-b`: the door-hold scenario adds its own bot (2026-11-20)

Lane B run 44616112409 got the door scenario onto `dod_thunder2`, and then every leg
aborted with `[DD] ABORT need one live player`. The `changelevel` drops every bot: the
engine drops fake clients on a level change (`SV_InactivateClients`, "Dropping fakeclient
on level change"). Nothing added one back.

- `tests/e2e_stats/door_hold_scenario.py` now runs `balance teams off` and
  `addbot allies` after the map change. It waits up to 45 s for a live player before
  the first leg. If none appears, the scenario reports `not_exercised` and the drive never
  runs.
- `KTPAssistDrive.sma` registers `ktp_dd_live`, which answers `[DD] LIVE n=<alive
  players>` over RCON for that wait.

⚠️ new_bot 0.2.2 ships no waypoint file for `dod_thunder2`. Whether `addbot` spawns a bot
on an unwaypointed map has not been observed. If it doesn't, this change turns the abort
into an explicit `not_exercised`. Verified with unit tests only. The first Lane B run with
`--door-scenario` is the real check.
