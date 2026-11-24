### scripts: `run-fleet-script.py` resolves the tier-2 runner and drift-reference hosts (2026-11-13)
- `stage-wave.py --expect-runner` and `sync-runner-stack.py` read `KTP_TIER2_SSH_HOST`,
  `KTP_DRIFT_REF_HOST` and `KTP_TIER2_SSH_KEY`, which the wrapper only passed through. Run
  through it, both stopped on a FATAL that named the variable but not why it was empty, unless
  someone had exported the hosts by hand.
- The wrapper now resolves them the way it resolves the credential: an already-set value wins,
  otherwise `ktp_hosts.SERVERS` (the data server's host and key path, the Atlanta host as the
  drift reference). Nothing is hardcoded and nothing is guessed. Each child gets only what it
  reads: `stage-wave.py` gets the runner host, `sync-runner-stack.py` gets all three.
- If one cannot be resolved, `sync-runner-stack.py` is not started and the message names the
  variable and where to set it. `stage-wave.py` still starts, with a note, because only its
  `--expect-runner` gate needs the host.
- Tests derive each child's host variables from its own source in both directions, check the
  resolved values against a fake `ktp_hosts`, and cover a missing entry and a missing key file.
  Mutation-checked: disabling resolution, over-granting `stage-wave.py`, and dropping the
  refusal each fail tests.
