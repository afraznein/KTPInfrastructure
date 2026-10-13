### `scripts`: the estate inventory is a command, not a paragraph (2026-10-13)

The count of every repo's open issues, open PRs and standing branches lived in
prose on the board. It rotted five times between 2026-09-04 and 2026-10-06, twice
within hours of being written, and each rewrite was indistinguishable from a
fresh reading — a figure in prose is a measurement with nothing holding it true.
Four passes re-derived it by hand and the fifth declined, on the grounds that
another inventory on that line was the defect rather than the work.

`scripts/ktp-repo-inventory.py` re-derives it on demand. The repo set comes out
of an owner listing filtered by `--match`, so adding a repo needs no edit here;
the two estate repos under other accounts are the only names the file spells out,
because an owner listing cannot produce them.

It encodes the six traps this answer has been got wrong by, each measured before
it was written down:

- `gh search prs` lags its index and reported a merged PR as open, so every read
  is a per-repo `repos/<o>/<r>/…` call.
- a ref list read from a local checkout over-reports silently, because `git fetch`
  does not prune — three `origin/*` refs locally against one on the remote, in one
  repo. Refs come from the API only.
- an orphan branch makes `compare` answer 404 *"No common ancestor"*, which reads
  as a failed probe rather than the finding it is. Under `--compare` that 404 is
  classified `ORPHAN`.
- `ahead_by > 0` is not evidence of unmerged work: the deploy train squashes, so a
  fully merged branch still reports commits the default branch lacks.
- a repo whose call fails is printed as ERROR and exits 2. It never renders as a
  repo with nothing in it.
- `users/<owner>/repos` omits PRIVATE repos and says nothing about it. The first
  live run read 24 of the estate's 34 and printed a complete-looking table; the
  authenticated `/user/repos` is used instead whenever the owner is the viewer,
  and the public listing is read anyway as a subset check.

Three controls run before any count is printed, and a failure exits 3 rather than
0, because *"I could not tell"* must not read as *"there is nothing there"*: two
names that cannot exist must ERROR rather than answer empty; a branch sweep that
returns no refs at all is a broken probe, since every repo has a default branch;
and the public owner listing must be a subset of the listing actually swept.

What it refuses to imply: nothing here says a branch is safe to delete. That
needs the branch tip tested against the PR's `headRefOid` and then content, and
the deletion itself is operator-only. `--compare` reports; it proposes nothing.
The three refs a naive sweep keeps proposing and must not — `keep-the-prac`
`production` and `deploy/train`, and this repo's bot-written `mmr-ratings` — are
annotated `GUARDED` so they stop being rediscovered.

`--selftest` runs the classification, control and listing layers against fixtures
with no token and no network; `tests/unit/test_repo_inventory.py` is what makes it
run in CI, and one of its checks breaks a fixture on purpose so a selftest wired
to `return 0` cannot pass as a real one.
