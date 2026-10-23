### Added
- Lane B registers KTPHLStatsX `sql/migrate_048_hand_signal_actions.sql` in apply order, after 047:
  the 16 DoD hand signals (`signal_yes`, `signal_grenade`, ...) as generic `hlstats_Actions` rows,
  the voice-command family's twin (045). `replay_daemon.py` and `lane_b_e2e.py` count
  `triggered "signal_` lines and report the carried verdict (`check_carried(..., prefix=True)`);
  `KTPAssistDrive`'s `ktp_vc_run` now has two more bots give a hand signal through `amxclient_cmd`,
  so the e2e lane exercises both families. Plugin side: KTPAMXX `stats_logging` 1.32.0.
