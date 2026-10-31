### `monitoring`: a nightly, public own-weapon kill report (2026-10-31)

A fun stat drew asked for: how often a player is killed with their own gun, one they spawned with,
dropped (death or the drop key), and someone else picked up. Teammates count. `stats_logging` 1.35.0
logs each one as `own_weapon_kill` and KTPHLStatsX migration 051 stores it in
`hlstats_Events_PlayerPlayerActions` with `match_id`; coordination `stats-own-weapon-kills` is the lane.

- **`scripts/own_weapon_kills.py`** reads every `own_weapon_kill` row in a tracked match since the season
  floor and takes the gun from the frag at the same second with the same killer and victim (a match in
  `hlstats_Events_Teamkills` marks a teammate). Boards per scope (official 0/4, every type): most robbed
  (owners) and biggest thieves, each with teammate count, per match, top opponent and top gun; then
  repeat thief/owner pairs, the latest 25, and kills per gun. Per match divides by matches the player
  appeared in on a server running a producer that logs the line (capture manifest `producer_version`
  >= 1.35.0). Names are league aliases where the website knows the player. Imports `voice_taunts.py`
  from its own directory for the MySQL reader, the alias index and the version parser.
- **Public by decision**, unlike voice taunts: `--website` upserts the snapshot into
  `ktp.own_weapon_kill_snapshot` (anon-readable; the table and page are keep-the-prac's). Exit 3 =
  only that upsert failed.
- **`ktp-own-weapon-kills.{service,timer}`** run it daily at 06:15 local into
  `/var/lib/ktp-own-weapon-kills/latest.md` with a dated copy, under `ktp-run-record.sh`, with the
  on-failure dropin. The timer is in `CRITICAL_TIMERS`: install the units before or with the health
  script, or the sweep reports a timer that does not exist.
