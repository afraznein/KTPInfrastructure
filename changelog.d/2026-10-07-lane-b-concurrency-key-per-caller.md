### Fixed
- `lane-b-stats-e2e.yml`'s concurrency group was the constant `lane-b-stats-e2e`, so every nightly,
  push, PR and dispatch queued in one repo-wide group. With `cancel-in-progress: false` GitHub keeps
  at most one PENDING run per group and drops it when the next arrival lands, so a run could die
  seconds after creation — two dispatches were measured dying seventeen and nineteen seconds in. The
  key is now per caller, event and ref (`github.workflow` / `github.event_name` / `github.ref`,
  which a called workflow inherits from its caller), so the 06:00 UTC nightly on `main` no longer
  shares a queue with a merge or a PR. `cancel-in-progress` stays `false`: a Lane B run boots hlds
  and takes most of an hour, and cancelling in progress would throw away the only evidence the
  scheduled lane produces.
- `lane-b-corpus-main.yml`'s own key is per ref and was documented as isolating the `main` verdict
  from a PR. It did not: the called workflow's constant key outranked it. The comment now says that
  both keys have to discriminate or neither isolates. #627 documented the shared key; nothing had
  changed it.

### Added
- `tests/unit/test_lane_b_concurrency_keys.py` asserts the property rather than a spelling: the
  called workflow's group must reference `github.event_name`, `github.ref` and `github.workflow`,
  must still serialise rather than cancel, and must not equal a caller's group. It carries a control
  that the workflow exists and declares a block at all, since every other assertion passes
  vacuously on a typo'd path. Verified in both directions against the pre-fix constant key.
