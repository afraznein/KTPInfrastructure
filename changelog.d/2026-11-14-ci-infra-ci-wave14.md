### ci: smoke slow path off the docker 29.4.2 runner; unit shell tests find Git Bash on Windows (2026-11-14)

- `smoke-callable.yml`'s slow path (`use_base_image: false`) builds `runtime/Dockerfile`, whose
  steamcmd step is i386. On `ubuntu-latest` (26.04, docker 29.4.2) the default seccomp profile
  refuses `socketcall(2)` inside a build, the failure #879 fixed for the nightly publish. That path
  now runs on `ubuntu-24.04` and starts with the same docker-version check. The fast path every
  caller uses stays on `ubuntu-latest`: its only 32-bit socket is the boot, which already runs
  under `ci/seccomp/lane-b-i386.json`. Lane B (`lane-b-stats-e2e.yml`) needs nothing: its image
  build runs no 32-bit network code and its boot uses the same profile.
- `tests/unit/conftest.py`: on Windows with `KTP_TEST_BASH` unset, the shell-script tests now use
  a Git Bash that can see the repo. A bare `bash` there is WSL's, which cannot open `C:/` paths,
  so every case failed with exit 127 (for example all 9 in `test_health_precache_freshness.py`).
  Linux CI is unchanged.
