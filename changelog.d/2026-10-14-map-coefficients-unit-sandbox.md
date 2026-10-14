### `scripts`: the map-coefficient refit unit could not run the refit (2026-10-14)

Three defects in `ktp-map-coefficients.service`, each of which would have failed
the **first** Monday run. The unit has never been installed, so none of them had
ever fired — they were found while preparing that install (`dpl-e72e`), after the
dry run gave the numbers needed to see two of them.

**1. The sandbox did not cover where the refit writes.** `ProtectSystem=strict`
makes everything read-only except what is granted, and `ReadWritePaths` named only
the repo and `/var/log`. But `#707` moved the fit out of the serving checkout and
into `/var/lib/ktp-map-coefficients` — the proposal, with `.refit-worktree`
beneath it. That directory was neither writable nor present, so `git worktree add`
— *the entire point of `#707`* — would have been denied. Introduced by `#707`,
which moved the writes and left the unit sandboxing the old ones.

**2. `TimeoutStartSec=30min` against a ~61-minute job.** Measured on 2026-10-14: a
`--check` over 680 labelled halves takes about 61 minutes. `Type=oneshot` is killed
at the cap, so every run would have died mid-fit. ⛔ The bound is **raised, not
removed** — its own comment gives the reason it exists (the refit's `git fetch`,
`git push` and `gh pr create` are unbounded network calls, and one wedged run blocks
every later one with nothing failed for anything to report). 3h clears the fit with
room for a season's growth at ~5.4s/half and still catches a wedge well inside the
weekly window.

**3. The log was uncreatable by the service's own user.** `LOG` defaulted to a bare
file in `/var/log`, which is `775 root:syslog` on the data server — `User=ktpreports`
cannot create a file there, verified against a control directory it does own. The
script's *first* action is `exec >>"$LOG"`, so it would have died before doing
anything. Pre-existing rather than from `#707`; nothing had hit it because nothing
had ever run.

Fixed with systemd's own directives rather than a fielding step, so the job
self-provisions on every start: `StateDirectory=ktp-map-coefficients` creates and
chowns `/var/lib/ktp-map-coefficients`, `LogsDirectory=ktp-map-coefficients` does
the same for `/var/log/ktp-map-coefficients/`, and the script logs to `refit.log`
inside it. `ReadWritePaths` keeps the repo, because the refit still registers its
worktree in `$REPO/.git/worktrees`.

**Tests:** 8, and all three defects are individually mutation-checked — reverting
each one reddens the case for it.

🔑 The load-bearing test **derives the script's write paths from the script** and
asserts the unit covers them, rather than restating a list that would drift the
same way this one did. It also counts `StateDirectory`/`LogsDirectory` as granting
`/var/lib/X` and `/var/log/X`, because a test reading only `ReadWritePaths` would
call this fixed unit broken.

⚠️ None of the three is visible by reading the unit on its own: the first needs
`#707`'s diff, the second needs a measured duration, the third needs the box's
filesystem permissions. That is the argument for running the dry run before the
install rather than after.
