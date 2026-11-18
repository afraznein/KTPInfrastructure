### Lane B: rotating-door hold scenario for the engine reversal guard (2026-11-18)
- New opt-in scenario `door_hold_reversal_guard` (`--door-scenario`; workflow input
  `door_scenario`, default `false`). After everything else on the server it changes to
  `dod_thunder2` and drives door 241 (hinge `-152 -920 -66`) with one bot through three legs,
  each judged on `push:` `blocked_ms` between the drive's markers: guard off facing 180 must
  hold (at least 80% of an interval blocked), guard off facing 0 must release (at most 10 ms),
  and `ktp_door_reversal_guard 1` facing 180 must release with `guard=` counting the re-target.
- `KTPAssistDrive` gains `ktp_dd_run <yaw>`: opens the door from the north with a push into the
  leaf, stands the bot south of it in the closing arc with its yaw held by `fixangle`, and logs
  a door/bot sample every 0.5 s for 16 s. Positions and facings come from the KTP-ReHLDS
  `design/rotating-door-holds/doorsim.py` model on the `68d6c078` build of the map.
- `not_exercised`, never a failure: the map missing from the image or a different build, a run
  without `engine_ref` (no `push:` telemetry), an engine without the cvar or one that refused it
  on another game DLL, a drive abort, or the bot moving or turning. Those are printed and kept
  out of the coverage gaps, so asking for the scenario never reds a run by itself; only a
  `pipeline` verdict (the door did the wrong thing) does. The scenario changes the map, so
  post-match log counters in a run that asks for it are not comparable with a normal run.
