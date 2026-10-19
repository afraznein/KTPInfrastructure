### Added
- Lane B registers KTPHLStatsX `sql/migrate_045_voice_command_actions.sql` in apply order, after 044.
  It seeds the 27 DoD voice-menu commands (`voice_negative`, `voice_grenade`, ...) as generic
  `hlstats_Actions` rows so the lines `stats_logging` 1.28.0 emits land in
  `hlstats_Events_PlayerActions`; without the rows the daemon parses and silently discards them.
- `assertions.count_action` / `check_carried` take `prefix=True`, counting a code family through one
  `LIKE` instead of one call per code. `replay_daemon.py` and `lane_b_e2e.py` count
  `triggered "voice_` lines and report the carried verdict (not_exercised on zero, so the recorded
  corpus stays green).
- `KTPAssistDrive` gains `ktp_vc_run`: three live bots each issue one voice command through
  `amxclient_cmd`, the same server-side path a real pick takes. Bots never do this on their own, so
  without it the voice check would read not_exercised on every run.
