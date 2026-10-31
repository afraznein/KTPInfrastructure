### Fixed
- Lane B's nightly gets the narrow i386 seccomp profile. `inputs` is empty on a `schedule`
  event, so an input `default:` never reaches a scheduled run -- which is why every value in
  the job's `env:` block carries its own literal fallback. `LANE_B_SECCOMP` kept the `''` it
  was given when the input was an experiment whose default was also `''`, so making the
  narrow profile the input default armed `workflow_dispatch` and `workflow_call` and left
  the one trigger nobody dispatches running under docker's default filter. Measured on the
  2026-10-30 06:09Z scheduled run (`41012439582`, head `a32499fd`): `seccomp=default`,
  `LANE_B_SECCOMP_RESOLVED` empty, `socket: Function not implemented` on all three boot
  attempts, `server never booted in 3 attempts`. Same shape on the four scheduled runs
  before it (10-26 `40319953289`, 10-27 `40459816924`, 10-28 `40642170501`, 10-29
  `40827559145`); the 10-24 and 10-25 scheduled runs predate the kernel roll and booted.
  `''` is a meaningful value here -- docker's own filter, which the probe job needs -- so the
  fix branches on the event rather than using `||`, which would override a caller that asked
  for it.
- Both `seccomp` input descriptions. They still said "Empty (the default) is docker's
  default profile, i.e. today's behaviour" under a first line saying the opposite, and they
  did not say that the default stops at `workflow_dispatch` / `workflow_call` -- which is
  the whole defect above.

### Added
- `tests/unit/test_lane_b_scheduled_input_defaults.py`. The property, not the one line: no
  `env:` expression may fall back to `''` while the input it reads declares a non-empty
  default, because a scheduled run then gets neither. `engine_ref` is the deliberate
  empty-default case and is asserted empty, so the rule cannot be relaxed by a parse that
  reads it wrong. The three copies of the profile path (two input blocks, one env fallback)
  are asserted equal and the file asserted present. Mutation-checked, 5/5: restoring
  `inputs.seccomp || ''`, drifting the scheduled profile path, dropping the literal fallback
  from `LANE` or `PLAY_SECONDS`, and giving `engine_ref` a real default while its fallback
  stays `''` each fail a test. Regex rather than a YAML parse because tier-1 CI does not
  install PyYAML and an `importorskip` would make the file skip in the only job that runs
  it.
