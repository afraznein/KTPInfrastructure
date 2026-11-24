### scripts: `run-fleet-script.py` says why it refuses the three scripts it leaves out (2026-11-13)
- New `NOT_RUNNABLE` table. `stage-runner.py`, `ktp_script_freshness.py` and `ktp-install`
  are refused with a reason and the way to run each one, instead of the generic
  not-in-allowlist error. None of them belongs in `RUNNABLE`: `stage-runner.py` reads neither
  the fleet credential nor the version rows, so the wrapper would only hand it a password it
  never uses; the freshness checker's reporting mode reads the `KTP_FRESHNESS_*` variables the
  wrapper strips; `ktp-install` imports `fcntl` and cannot run on Windows.
- Tests hold each reason true against the script's own source, so a script that later starts
  reading a wrapper-supplied credential fails a test instead of staying refused on a stale
  argument. Mutation-checked: removing the refusal fails the refusal test.
