### Added
- Lane B registers KTPHLStatsX `sql/migrate_051_own_weapon_kill_action.sql` after 050: `own_weapon_kill`, a player-vs-player action like `assist`. Both lanes count
  `triggered "own_weapon_kill"` and add the exact carried check against PlayerPlayerActions.
- New `tests/e2e_stats/own_weapon_scenario.py` + `KTPAssistDrive ktp_ow_run`: teammate A dies for real,
  teammate B presses drop and is put on A's gun, every `dod_client_weaponpickup` the game fires for B is
  logged, then a dispatched teamkill of A with A's gun must log exactly one `own_weapon_kill` naming B,
  A and the gun. A teamkill so no `frag_context` no-row diagnostic is produced. If the game hands B
  nothing in 5 s the plugin's handler is called directly: the ledger is still checked but the verdict
  is not_exercised, never a pass.
