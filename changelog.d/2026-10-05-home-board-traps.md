### `provision`, `docs`: console-log retention and two board-only traps get a repo home (2026-10-05)

Instance configs written by `install-linuxgsm.sh` and `clone-ktp-stack.sh.example` now set `logdays="21"`, matching the live fleet; `_default.cfg` still carries 7. `docs/LINUXGSM.md` records the trap, `docs/LIVE_SCRIPT_INVENTORY.md` records the `hltv-api` restart timing decision, and two redaction limits plus two stale `plugins.ini` comments are corrected in place.
