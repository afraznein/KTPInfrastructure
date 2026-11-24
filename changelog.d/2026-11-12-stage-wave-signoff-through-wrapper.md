### `scripts`: the morning-after command stage-wave.py prints is the full verify, through the wrapper (2026-11-12)

`stage-wave.py` ended every wave by printing a bare `ktp-verify-deploy.py --check-runtime`
(plus `--include-engine` on engine waves only). Run as printed on a workstation it has
neither the SSH nor the rcon credential and refuses with exit 4, so the runtime leg ran
only for whoever remembered `run-fleet-script.py`, and a plugin wave's sign-off never
looked at the engine.

- `scripts/stage-wave.py`: the hint is now `morning_after_commands()` and prints
  `python scripts/run-fleet-script.py ktp-verify-deploy.py --scope all --include-engine
  --check-runtime` and `python scripts/run-fleet-script.py ktp-wave-ledger.py reconcile`
  for every wave. The wrapper already supplies the rcon credential to the verify
  (`NEEDS_RCON`), so the printed command is the one that reaches every leg.
- `tests/unit/test_stage_wave_signoff_command.py` (new): the printed commands go through
  the real wrapper, name allowlisted scripts, carry every verify leg, and use only flags
  the verify still accepts. Mutation-checked: dropping `--check-runtime`, or printing the
  verify bare, fails it.
- Proven end to end, read-only, on 2026-11-12: that exact command through the wrapper
  returned `overall=GREEN {'green': 24}`, rc 0, with the rcon leg reporting 10 loaded
  plugins on 24/24 and 0 runtime errors.
