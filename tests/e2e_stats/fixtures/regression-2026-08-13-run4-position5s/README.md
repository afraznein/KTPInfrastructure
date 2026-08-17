# Lane B run 4 — position-broadcast 5s regression

Real bot-driven Lane B match (16 bots, `dod_anzio`, KTPAMXX `feat/stats-break-context`
@ 848beb28, KTPHLStatsX `feat/break-context-parse` @ 1e6c55b), run to validate
`KSC_POSITION_BROADCAST_SECS` 30s -> 5s end to end, not just by compile.

## Result

- `position_sample`: 2246 emitted, 2246 landed (`ktp_position_samples` direct-INSERT
  path, no loss — unlike the UPDATE-based markers below, this isn't exposed to the
  frag-row race).
- `assist` 20/20, `cap_break` 1/1, `kills`/`frags` 156/156, `suicide` 10/10 — all
  exact matches once a clean (data-free) schema was used. An earlier attempt reused
  a fixture dump that still had 1731 rows of unrelated historical data in it as the
  "base schema," which inflated every count and produced 6 false-positive failures —
  not a real defect, a test-setup mistake. Fixed by stripping the fixture to
  DDL-only before reuse.
- `headshot`: 13 markers, 12 landed. Root-caused via the daemon's own
  `KTP_NO_ROW_MATCHED` tripwire (added earlier this session as part of the
  frag-row-corruption fix): a genuine ordering race under Lane B's artificial
  bot-combat density (far higher kills/sec than real human play), where a buffered
  `frag_context` marker reached the daemon before its own primary kill line had
  been inserted yet. Correctly discarded rather than misattributed to the wrong
  row — this is a third, real-world validation of the corruption fix (the first
  two were synthetic replay controls), not a new defect. See KTPHLStatsX's
  CHANGELOG.md `[Unreleased]` section for the full writeup.

## Environment notes worth keeping

- This run needed a full from-scratch Lane B environment rebuild on a machine that
  had none of it: WSL had no gcc (fixed via `wsl -u root` — no sudo password
  needed for root), Docker Desktop had no images, no bot-kit. Turned out the
  bot-kit path in `lane_b_local.sh`/this file's own older sections is **stale** —
  see `docs/handover/CI_CD_LANE_B.md`: `new_bot` is baked into the image at build
  time, no external bot-kit needed. `--ktpamx-so` needs a real C++ build
  (`KTP_LANE_B_FAKECLIENTS=1`, via `scripts/build_ktpamx_laneb.sh`'s recipe) — that
  one does need a toolchain, but a self-contained Docker one, not the host's.
- **Docker Desktop on Windows + WSL2 bind mounts are not safe for anything
  amxxpc reads, or for a live-tailed, actively-appended file.** Found twice: (1)
  `amxxpc` fails `fatal error 100: cannot read from file` on a file another
  process just wrote to the same bind mount, even though the file demonstrably
  exists with correct content/permissions — a write-visibility race across
  processes on the 9p transport, not a real permissions issue. Worked around by
  staging all amxxpc inputs onto the container's own filesystem via `docker cp`
  before compiling, never compiling directly off a live bind mount. (2)
  `hlstats_daemon.py`'s log-tailing thread crashed with `OSError: [Errno 61] No
  data available` on a blocking `readline()` against a bind-mounted `--log` path
  that the game server was actively appending to — same transport, different
  syscall pattern. Fixed by pointing `--log`/`--out` at a native container path
  during the run and copying the finished files out afterward.
- **Never bind-mount a live, actively-used working tree for a long-running
  test.** Two of this session's live repos (`KTPAMXX`, `KTPInfrastructure`) had
  their checked-out branch changed out from under a live bind mount by
  concurrent CI/deploy tooling on the same machine, mid-run, which is what broke
  two of the four attempts here (files vanishing mid-flight, wrong branch
  content). Fixed by cloning each repo into an isolated scratch copy pinned to
  the exact commit needed, immune to whatever the live checkout does afterward.
  Nothing of the session's own work was ever at risk — commits are safe
  regardless of what a working tree currently has checked out — but the test
  run itself needs a stable filesystem snapshot to run against.
