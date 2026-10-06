### `tests`, `scripts`: the tier-2 test server's rcon password comes from the runner, not the repo (2026-10-05)

`scripts/curl_smoke.py` hardcoded the rcon password of the tier-2 runner's own test server, and the Tier 2
conftest staged `tests/smoke/fixtures/test_server.cfg` onto the runner with the same public value. That
server binds 127.0.0.1 only, so this was low severity, but a value in public history stays public; the
runner's password has been rotated and the new one lives only on the runner box.

- `tests/smoke/boot_subprocess.py`: `resolve_test_rcon_password()` reads `KTP_TEST_RCON_PASSWORD` and raises
  when it is unset or empty. `booted_subprocess()` uses it when no password is passed, before anything is
  spawned. `cfg_with_rcon_password()` sets the single `rcon_password` line of a staged cfg, since that cfg
  runs after the CLI arg and its value is the one the server keeps.
- `tests/integration/conftest.py` and `tests/smoke/_proof.py` stage the fixture with the resolved value and
  boot with it. The fixture keeps its placeholder for the Lane B containers, which pass it themselves.
- `scripts/curl_smoke.py` exits non-zero naming the variable when it is unset; there is no literal left.
- `tier2-integration.yml`: a new step reads the value from `/etc/ktp/tier2-test-rcon.env` (root 600 on the
  runner, the same pattern as the relay creds), masks it, and exports it to the pytest step. It fails the
  job when the file or the line is missing.
- `tests/unit/test_tier2_test_rcon_password.py` covers the resolver, the staging helper, the curl smoke's
  refusal and the workflow step order.
- Deploy: the runner needs `/etc/ktp/tier2-test-rcon.env`, the rotated value in its `dod/dodserver.cfg`
  and `dod/test_server.cfg`, and this `curl_smoke.py` installed at `/opt/ktp-tier2-runner/curl_smoke.py`.
