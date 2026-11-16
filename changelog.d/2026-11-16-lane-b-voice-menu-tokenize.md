### Lane B: the voice-menu drive now reaches the game (2026-11-16)

- `ktp_vm_run` sent `voice_menuN` and `menuselect K` through `amxclient_cmd`, which under
  extension mode fires the plugin forward with its own arguments while `dod.so` reads whatever
  line the engine tokenized last (no `Cmd_Argv` override outside Metamod). So the plugin logged
  all 27 picks and the game never opened a voice menu, which by itself explains why the all-bot
  lane has never seen a `#Voice_subtitle_*`. The drive now tokenizes each line with
  `server_cmd` + `server_exec` first, the same step the own-weapon drop took in #892.
- The `voice_menu_slots` waiver is unchanged. It comes off only after a full-lane run shows
  subtitles arriving; if they still do not, the two candidates already documented in
  `tests/e2e_stats/voice_menu_scenario.py` (fake speaker, fake recipients) are what is left.
