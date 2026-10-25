### Added
- Lane B registers KTPHLStatsX `sql/migrate_049_voice_menu_actions.sql` after 048: the 27 voice-MENU
  picks as their own `voicemenu_*` family, so the stats keep bound key vs menu. Both lanes count
  `triggered "voicemenu_` and add the prefix carried check.
- New `tests/e2e_stats/voice_menu_scenario.py` + `KTPAssistDrive ktp_vm_run`: bots open each voice menu
  and pick all 27 slots; every logged `voicemenu_*` is checked against the `#Voice_subtitle_*` TextMsg
  the game sends for that pick (nation variants normalised). A wrong slot is a pipeline failure naming
  it; no subtitles at all is not_exercised, never a pass.
