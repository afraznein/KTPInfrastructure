### Lane B: why the voice-menu check never sees a subtitle (2026-11-18)
- Documented, no behaviour change: `dod.so` sends no `#Voice_subtitle_*` TextMsg for a voice
  pick, bot or human. `menuselect` on an open voice menu runs `CDoDTeamPlay::VoiceCommSelect`
  -> `CBasePlayer::VoiceCom`, which emits only a `pfnPlaybackEvent` with the voice index (any
  subtitle is client-side); `gmsgTextMsg` is written only by `ClientPrint` /
  `UTIL_ClientPrintAll`, and no code reads the subtitle strings. Read from the shipped
  `dod.so`, CRC32 `1BEDADC8`, the binary Lane B loads. Neither cause the waiver recorded
  (fake-client speaker, no non-fake recipient) holds, so `voice_menu_slots` stays
  `not_exercised` in any lane; the waiver stands.
- The slot table is confirmed against the same binary: stats_logging's `g_kscVoiceMenuSlots`
  equals `s_VoiceCommands[1..27]` in order, with VoiceCommSelect's `(menu - 1) * 9 + slot` index.
- Updated `tests/e2e_stats/voice_menu_scenario.py` and `docs/handover/CI_CD_LANE_B.md` § 5.
