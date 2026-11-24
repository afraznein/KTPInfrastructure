### Added
- A health-check leg in `scripts/ktp-data-server-health.sh` for the AC review digest, which is
  the only thing that routes the review backlog to a person and was watched by nothing.

  Its cadence marker in `ktp_ac_config` advances **only on a delivered post** — the digest
  service rolls it back on every other outcome, deliberately, so that a session appearing after
  a quiet stretch surfaces at the next tick rather than in a week. One consequence is that a
  single marker value covers both "nothing to report" and "has not reached anyone in weeks",
  and the only place those differ is the service's own log: it posts, stays quiet, or logs at
  error level that it did not post and nobody was told. Nothing read that log on a schedule, and
  `ktp-ac-api` is `active` through all three, so no unit-level alert covers any of it.

  - `ac-review-digest:failed` counts the failure line over a trailing window, latched warn 1 /
    clear 1. The clear floor stays at or above 1 for the same reason the upload-abort leg's
    does: at 0 the mid-band test is true for every count and the item never clears again.
  - `ac-review-digest:loop-silent` fires when a digest is overdue and the service logged **no
    outcome of any kind**, which is the background loop not ticking. It is gated on the marker
    being overdue because between digests the service returns before logging anything, so
    silence inside the period is normal and must not page.
  - Both quiet answers are reported as `unmeasurable` rather than as a clean zero: an
    unreadable marker, and a journal that does not reach back across the window. That journal
    is size-bounded rather than time-bounded, so the floor is derived per run instead of
    assumed — a window it cannot cover would otherwise score "no failures" out of absent lines.

  The window spans several of the service's own ticks on purpose. A rolled-back marker is
  retried at the next one, so a broken digest keeps re-logging rather than falling silent, and
  a window far shorter than the digest period is still sound — which is also what keeps the
  journal floor an easy bar to clear.

  The three log literals are a contract with the API's digest service: a reword there makes
  this leg blind in the quiet direction, leaving only `loop-silent`, so
  `tests/unit/test_health_review_digest.py` pins them and asserts that a renamed literal stops
  matching. Six mutations killed on their own messages — dropping either `unmeasurable` leg,
  dropping the overdue gate, the clear floor at 0, counting a quiet tick as a failure, and
  widening the window default — with a dead anchor that could not apply and the suite green
  before and after.

  ⚠️ Merged is not fielded: `/usr/local/bin/ktp-data-server-health.sh` is installed separately
  and the live copy is already behind this file, so the leg starts reporting on an install.
