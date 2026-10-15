### `scripts`: the map-coefficient refit produced a proposal and then threw it away (2026-10-15)

Three more defects in the weekly refit, all found the only way they could be —
by letting it run. `#711` fixed the three that stopped it starting; these are the
three that stopped it *finishing*. The first real run (2026-10-14 21:43 EDT,
started by hand so its timing was chosen rather than inherited from a missed
Monday) fitted for 2h08m, wrote the new table, and exited 128 with nothing kept.

**1. The commit could not name an author.** `ktpreports` is a `nologin` account
whose home directory does not exist; there is no `~/.gitconfig`, no
`/etc/gitconfig`, and the unit sets no environment. So `git commit` ended the run
with *"Author identity unknown"* — after the expensive part had succeeded. Fixed
with `-c user.name=… -c user.email=…` on the commit itself, the same pattern
`.github/workflows/mmr-weekly.yml` already uses, so the script carries its
identity instead of depending on state the box does not have.

**2. A five-second failure discarded two hours of fitting.** The proposal was
copied out of the scratch worktree *after* the commit, and the `EXIT` trap
removes that worktree whether the run succeeded or not. One failed git step
therefore took the table, the diff and the patch with it: `/var/lib/ktp-map-coefficients`
was empty afterwards and `refit.log` was the only surviving record of what had
been proposed. The fit now lands outside the worktree **before** the first git
step.

**3. One run made three full passes over the corpus, against a 3h cap.** `--check`
to decide whether to bother, `--write` to produce the table, then `--check` again
to render the diff — and each pass re-queries the labels and reloads every half.
Measured: ~64 minutes a pass, so a *successful* run needed ~3h10m and would have
been killed at `TimeoutStartSec=3h`. The run that failed stayed inside the cap
only because it died early. It is one pass now: `--write` leaves the table
untouched when no coefficient moved, which makes `git diff` on that file the
whole "is there anything to propose" test, and its own output is the diff.

🔑 **The third defect also fixed a review-integrity bug.** `diff.txt` came from a
*third, later* query, so the diff a human reviewed need not have described the
table being committed — and the corpus demonstrably moves mid-run: pass one saw
689 labelled halves, pass two saw 695 an hour later.

🔻 **Corrects `#711`.** That entry reasoned from ~5.4s/half over one pass and
concluded 3h left "room for a season's growth". The rate was right; the pass
count was never counted. 3h is now genuinely ample — against ~64 minutes rather
than ~3h10m — but for a different reason than it claimed, and the unit's comment
says so, because re-adding a pass puts the job back over the cap.

**Tests:** 11 new or re-premised across three files, each defect individually
mutation-checked.

⚠️ **The suite could not have caught the first one, and that is the lesson.** It
already had a case called *"a real proposal commits, pushes and writes the
artifacts"* — passing. Its fixture wrote a git identity into the test repo and
pointed `GIT_CONFIG_GLOBAL` at it, manufacturing the one condition the data
server lacks. The fixture now points git's user *and* system config at a file
that does not exist and strips `GIT_AUTHOR_*`/`GIT_COMMITTER_*`, so that
pre-existing case fails too when the identity is taken back out of the script.
