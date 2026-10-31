### Fixed
- `ktp-verify-deploy.py` refuses, with its own exit code, when a credential it needs is not
  configured. It used to resolve both secrets at import and `sys.exit(<message>)`, which
  ends the process with status **1** -- the same status a run returns when it has walked all
  24 instances and found drift. Every wave is signed off against this script's verdict, so a
  run that contacted no host was one trusted exit status away from being read as a verdict
  about the fleet. Hit on 2026-10-26: the overdue 03:00 verify printed
  `fleet SSH password not configured` and ended, and nothing in the status said so.
  The exit codes are now stated in the module docstring and distinct: `0` GREEN, `1` not
  GREEN, `2` fatal (reference unreachable or empty manifest), `3` refused before starting.
  The refusal says `NO HOST WAS CONTACTED AND NO VERDICT WAS REACHED`.
- Every missing credential is named in one pass instead of the first one only. The rcon
  password's own absence was reachable only after supplying the SSH password, which is a
  second round trip against a fleet already waiting on a verdict.
- `--check-runtime` is opt-in, so its credential is too. A disk-only run no longer demands
  `$KTP_RCON_PASSWORD`, and `--help` is readable with nothing configured at all -- the
  import-time exit ran before `argparse`, so the help text could not be printed.
- `ssh_connect` raises on an unresolved password rather than falling through to key auth,
  and `collect_runtime_versions` raises rather than sending an empty rcon password. Both
  fallbacks were unreachable only because the import-time exit came first; with that gone,
  the SSH one would have become the quiet path by which a bare run contacts nothing.
- The refusal names `$KTP_FLEET_SSH_KEY` when it is set, because this script does not read
  it and `run-fleet-script.py` stops importing a password once a key is present -- a
  key-only environment otherwise looks configured and is not.

### Added
- `tests/unit/test_verify_deploy_credentials.py`, asserting **both** directions: absent
  credential refuses with the dedicated code and reaches nothing that contacts a host, and a
  configured run still calls the verification and still exits 0 on a GREEN fleet. A guard
  that refuses in both states would be worse than the defect. Mutation-checked: removing the
  refusal, giving it the GREEN exit code, reporting only the first missing credential,
  demanding the rcon password unconditionally, restoring either fallback, or moving
  resolution back to import each fail a test. The home directory is redirected to a tmp path
  and one test writes the dotfile there, so the fixture is shown to be able to find a
  credential rather than being vacuously empty.
