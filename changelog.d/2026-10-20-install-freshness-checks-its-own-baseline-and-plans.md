### `scripts`: the freshness gate checks its own baseline, and can now emit the install step (2026-10-20)

`ktp-install --report --against-ref origin/main` compared installed bytes against a
**remote-tracking ref inside the checkout** and trusted it. Nothing on a live box keeps that
ref current, so the gate was reporting a healthy estate *because* its own reference had gone
stale.

- **Measured, not hypothetical.** On the data server, `/opt/ktp-infra`'s `origin/main` was
  **214 commits behind** GitHub's while its `HEAD` was 236 behind. Every row compared against
  it printed `CURRENT` and the run exited 0. The gate under-reported staleness **silently, in
  the reassuring direction** — the one direction nothing contradicts.
- **It is the same defect one level up from the one this gate exists to catch.** `--report`
  alone asks *"has anyone edited this since install"* and reads identically to *"is this the
  merged version"*; `--against-ref` was added to close that, and then answered *"does this
  match a snapshot of main from some unknown date"* while reading identically to both.
- **Why a convention could not hold it.** The two callers that got this right compensate
  **outside** the tool: `ktp-install-freshness.sh` fetches before reporting, and the `hltv-api`
  drift checker prints its reference's provenance instead of claiming freshness. The common
  caller is a person typing the command, so every figure quoted from a hand-run `--report
  --against-ref` was measured against whatever that checkout happened to hold.

**The fix: the baseline is established rather than assumed.**

- A ref resolving under `refs/remotes/` is this checkout's **cache** of someone else's branch,
  so `git ls-remote` asks the remote whether it is that branch's tip. **No fetch, nothing
  written** — the report stays read-only, including against the never-pulled deploy checkout.
- Not the tip, unreachable, or a cached branch the remote no longer has → `UNTRUSTED`, exit 2,
  **naming both shas** and the fetch that would settle it. No rows are printed at all, so there
  is no `CURRENT` to misquote.
- A 40-hex sha, a tag, `HEAD` or a local branch claims nothing, so it is run and **labelled**
  `pinned` rather than refused. That is also the offline route: name the commit you mean.
- **The first line of every `--against-ref` run is the baseline** — the ref, its resolved sha,
  and how it was settled. A verdict now carries what it was a verdict *against*.
- `ktp-install-freshness.sh` skips that header when building the non-fresh set, and **refuses
  outright when it is missing**: an installed copy predating this check reports `CURRENT`
  against anything, and that would read here as a clean estate. ⚠️ Checked on the output, not
  by grepping the script — a version probe of a tool is a guess about its behaviour.

**And the step that was missing: `ktp-install --plan --repo DIR --against-ref REF`.**

There was no deploy step to add to, which was never about a puller being hard: nothing could say
*what* was owed. `/usr/local/bin` is installed by a person remembering to copy a file, and the
commands were hand-written each time — which is where the mistakes were. One deploy packet named
a PR's merge sha as `--commit` rather than the ref the freshness guard would compare against,
which refuses on every later run.

- It **writes nothing** and prints the `ktp-install` commands for every `STALE` row.
- Each is pinned **twice** to bytes measured in that run: `--expect-md5` to what is on the box,
  so a plan that has gone out of date **refuses instead of clobbering** — including over a
  hotfix applied after it was generated — and `--blob-md5` to what the ref holds, so a file
  staged out of the wrong tree refuses too. A plan can go out of date; it cannot install the
  wrong thing.
- It is reachable **only** through an authenticated baseline, so it cannot emit commands that
  install a stale commit's bytes as though they were current. 🔑 That ordering is the operator's
  own sequencing ruling: the gate is what makes the deploy step safe to generate.
- The emitted `git show` reads the checkout **at a sha, not at a branch**, so how stale that
  tree's refs are does not matter — the bytes either hash to `--blob-md5` or the install
  refuses. That is why a plan may be generated from `/opt/ktp-infra` while installing *from* it
  stays refused.
- Exit `0` nothing owed, `1` a plan was emitted, `2` untrusted. ⚠️ `1` is the productive
  outcome, which inverts the usual reading, and ⛔ never pipe it.

⛔ **Two things it deliberately does not do.** It is **not a dependency order** — an
import-level dependency between two planned files is not derivable from a manifest, and the one
we know (`ktp-verify-deploy` imports `ktp_script_freshness` at module level, so the guard
installs first) is named in the runbook instead of guessed. And it covers the **recorded estate
only**: a file nobody installed with `ktp-install` is in no manifest and cannot be stale here.
`DRIFT`, `MISSING`, `SOURCE-GONE` and `SOURCE-MISMATCH` rows are listed under `NOT PLANNED`
with their reason rather than turned into commands.

⛔ **Nothing is installed by this change, and no privilege is granted.** Writing `/usr/local/bin`
from CI remains an open operator decision; a plan is text a person reads and runs.

**Verified in WSL, and the plan is run rather than inspected.** 71 passed, 1 skipped (56 before).
The end-to-end test generates a plan, executes it through `bash -e` with `ktp-install` on `PATH`,
and asserts the row reports `CURRENT` afterwards — asserting the plan's *shape* would prove
nothing about whether it installs anything. Mutation-checked in both directions: turning the
baseline guard off, inverting its comparison, dropping either pin from the emitted plan, letting
a `DRIFT` row be planned, and suppressing the baseline header each fail tests that pass on the
unmutated script, and the script restored byte-identical after every mutation.
