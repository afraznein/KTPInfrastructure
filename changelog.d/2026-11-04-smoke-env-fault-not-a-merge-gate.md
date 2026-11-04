### Fixed
- Tier 1 Smoke no longer fails a pull request when the runner refuses the game
  server a UDP socket. That signature is reproducible on an unchanged `main`,
  so it was blocking merges in every repository calling the shared workflow
  while saying nothing about the change under test. It now reports as an
  environment fault: a warning plus a step summary that states plainly that the
  plugin assertion did not run, so the result reads as unmeasurable rather than
  green. The discriminator requires the specific errno, not just the syscall,
  and `tests/unit/test_smoke_env_fault_pattern.py` holds it to that.
