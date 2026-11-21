### `lane-b`: the image loads the fleet's game DLL, `dlls/dod_i386.so` (2026-11-20)

Every Lane B run so far loaded the stock `dlls/dod.so` from Steam's depot. The fleet's
`liblist.gam` loads `dlls/dod_i386.so`, a different build that steamcmd cannot supply. So
Lane B was testing a game DLL the fleet does not run, and the engine's door reversal guard
refused to arm in it (`not the build it was written for`).

- `build/lane-b/gamedll/dod_i386.so` is committed beside the Dockerfile. It is the fleet
  file: md5 `4f4727b2390d3a0ed6f5ad862dd6d4be`, sha256
  `c6090f0cb2b8b64cd1df11d473be82d031d1ecfee26a63a54992b9347369a9d3`, CRC32 `C76CE69D`.
- `build/lane-b/Dockerfile` copies it to `/opt/hlds/dod/dlls/dod_i386.so`, checks it
  against `GAMEDLL_SHA256` (a mismatch fails the build), and points `liblist.gam`'s
  `gamedll_linux` at it. This runs before the Metamod layer snapshots
  `liblist.gam.production`, so `restore_production()` restores the fleet path too.
- `tests/e2e_stats/metamod.py` passes `+localinfo mm_gamedll dlls/dod_i386.so` by default
  (`FLEET_GAMEDLL`).
- The strict GameRules preflight in `scripts/lane_b_e2e.py` now requires the server CRC
  line to name `dod/dlls/dod_i386.so` with CRC32 `C76CE69D`. A run on any other game DLL
  fails the preflight instead of passing.
- The voice-menu claims in `tests/e2e_stats/voice_menu_scenario.py` were re-read from
  `dod_i386.so` and all hold: the 27-name slot table, `(menu - 1) * 9 + slot`, no
  `#Voice_subtitle_*` TextMsg from the server.

The file is in the build context, so it never passes through the vendor cache and the
cache key does not need to change. No base-image publish is involved: the Lane B image is
built per run on top of `ktp-runtime-test-base`.

⚠️ **Verified with unit tests that run the new install layer under a shell, with five
mutations, not with an image build.** This workstation has no Docker. The first real build
is this change's own Lane B run.
