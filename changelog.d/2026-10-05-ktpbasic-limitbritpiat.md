### `config`: `ktpbasic.cfg` limits the PIAT with the cvar the game registers (2026-10-05)

`config/local/dod-configs/ktpbasic.cfg` set `mp_limitpiat 0`, which the DoD game DLL does not
register, so the line did nothing and the PIAT was unlimited. It is now `mp_limitbritpiat 0` (none
allowed), matching `/home/dod/distribute/configs/ktpbasic.cfg` on the fleet since 2026-10-05.
`tests/config_parse/test_class_limit_cvars.py` rejects any other PIAT-limit name in a shipped config.
