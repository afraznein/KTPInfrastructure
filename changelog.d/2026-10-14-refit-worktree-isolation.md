### The weekly refit no longer moves the serving checkout (2026-10-14)

`ktp-map-coefficients-refit.sh` ran `git checkout -B map-coefficients/<date>` in
`$REPO` — `/opt/ktp-reports/KTPInfrastructure`, which **serves**: report jobs read
that tree. It changed back on exactly two paths, the clean exit and the last line,
and the script is `set -euo pipefail`. So every step between them aborts
immediately: a failed fit, a failed commit, a full disk under `format-patch`, an
unreadable path. Any of those left the serving checkout parked on a dated branch,
and **nothing said so** — the next reader of that tree gets a plausible-looking
repo on the wrong ref.

Measured, by running the old script against a throwaway repo on a branch called
`serving`:

- A fit that fails after `--check` leaves `$REPO` on `map-coefficients/2026-10-14`.
  `git branch --list` shows it as the **current** branch.
- And it is not only the failure path. A probe inside the fit — the only window
  where this is observable — records `$REPO` on `map-coefficients/2026-10-14` at
  every invocation of a **successful** run. The fit is the slow part, so that is
  precisely when a report job is most likely to read the tree.

A `trap` would have closed the first half and not the second, because moving a
serving checkout at all is the defect. **So the move is gone instead.** The refit
takes a worktree of its own off `origin/main`, `$REPO` keeps whatever ref it was
on, and the trap only removes that scratch tree.

- `--detach`, so no dated local branch is created in `$REPO`'s refs either — a
  failed run leaves nothing that reads as work in progress. The push names
  `HEAD:refs/heads/$BRANCH` accordingly, since there is no local branch to resolve.
- Cleanup runs on `EXIT`, swallows its own errors so it cannot turn a finished
  refit into a failure, and calls `worktree prune`, which is what makes a crashed
  previous run self-healing rather than permanently blocking the next one.
- The worktree path is fixed rather than `mktemp`, for the same reason: a crashed
  run leaves a registration behind and a fixed path is one the next run can find
  and clear. ⛔ Never a glob — this repo has other registered worktrees and a sweep
  would unregister them, so the cleanup names one path and a test asserts it.

Nothing about the review model changes: still no write to `main`, still no merge,
still best-effort push with the proposal written to `/var/lib/ktp-map-coefficients`
when the host has no push rights.

**Tests:** 16 pass, and they were mutation-checked against the old script — 9 fail
on it, including both behavioural ones. The static asserts read **code lines only**,
because the header comment quotes the removed `git checkout -B` in order to forbid
it and a whole-file grep would fire on the explanation instead of a regression.
