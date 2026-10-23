### `monitoring`: a nightly, hidden voice-taunt report (2026-10-23)

Players asked how often voice commands are used; drew asked which are taunts. Migration 045 +
`stats_logging` 1.28.0 (inside 1.30.0) land every voice-menu press as a `hlstats_Events_PlayerActions`
row with `match_id`; coordination `infra-voice-taunts-report` is the lane.

- **`scripts/voice_taunts.py`** reads every voice press in a tracked match since the season floor,
  finds the speaker's nearest own kill within 10 s, and calls a press a taunt when that kill is
  <= `--window` (5) s before it, naming the kill's victim. Presses by one speaker in one logged
  second collapse to one (nine in one second was measured on the first night); leaderboards count
  taunts and show presses. Two boards (official 0/4, every type), most-taunted, one section per
  speaker with their victims, and a shape block (per type, per line, seconds-after-kill histogram).
  Per match divides by matches the speaker appeared in (`ktp_match_players`) on a server whose
  plugin could record a voice line (capture manifest `producer_version` >= 1.28.0), not every match of
  the season and not only matches with a taunt. `--tsv` keeps every distinct command with its delta so the window can move without a new
  query. Read-only over the local socket, no credentials.
- **`ktp-voice-taunts.{service,timer}`** run it daily at 06:10 local into
  `/var/lib/ktp-voice-taunts/latest.md` with a dated copy, under `ktp-run-record.sh`; on-failure
  dropin posts the embed. Hidden by construction: a file on the data server, read over SSH. If the
  shape earns it, it moves to the website later.
- Names are the league's where the league knows the player: `ktp.player.alias` through
  `player_steam.steam_id64`, the same index `report_sync.py` applies to reports, fetched from PostgREST
  with `/etc/ktp/reports.env`'s credentials (`EnvironmentFile=-`). Unknown players keep the alias they
  played under; a failed lookup degrades to in-game names and says so in the header, never a failed run.
- **`scripts/ktp-coord-publish.sh`** pushes the night's three files into the PRIVATE coordination repo
  (`research/infra-voice-taunts-report/`, dated file + `latest.md` + TSV) with a write deploy key at
  `/etc/ktp/coordination-deploy.key`, scoped to that one repo. No key yet = prints NOT PUBLISHED and
  exits 0 (a known gap, not a fault); key present and the push fails = exit 1 and the embed. Generic:
  any later hidden report reuses it. Nothing of this kind is ever committed to this public repo.
- Health script lists the timer as critical; `UNIT_RUN_RECORDS.md` and `ALERT_COVERAGE.md` carry the rows.
