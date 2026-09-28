### `.github`: the coordination gate stops blocking a PR on itself (2026-09-28)

`coordination-check-reusable.yml` picked a workstream's Blocked-by cell with
`grep "^| <repo> |" | head -1` — the **first** row for the repo, whatever PR was under test.
In `infra-hidden-value-plays` that first row is **#548's**, whose blocker is **#547**, so the
gate run for #547 read someone else's row and reported:

> `Blocked by PR https://github.com/afraznein/KTPInfrastructure/pull/547, which is not merged yet (status: unknown).`

#547 was blocked by #547 and could never pass. Every other `KTPInfrastructure` PR in that
workstream inherited #548's blocker too. The data was right; the lookup was wrong. Measured
across the 33 state files: 13 carry a repo with several rows, and two of those have a blocker
in the first one.

The row is now selected by the **PR under test**, matched against the PR cell only — a
Blocked-by cell holds PR urls as well, so a whole-row match finds the *blocker's* row instead
of the blocked one. Selection is also confined to the `## Repos in scope` section, and the PR
number is refused unless it is digits rather than compiled into a dynamic regex.

Behaviour for a PR with **no** row is now stated rather than accidental. One row for the repo:
that row applies, exactly as before, blocker included. Several rows and none of them blocked:
nothing to enforce, and the run says so. Several rows with a blocker among them and no match:
**refused** — which block applies is undecidable, and guessing is how this started.

Three further mouths of the same class were open in the same step, and are closed here:

- **`gh pr view --json merged` is not a gh field.** The list carries `mergedAt` and `mergedBy`,
  no bare `merged`, so that branch answered `unknown` for every PR reference ever passed to it
  and **no PR block could ever clear** — the `status: unknown` in the message above. It reads
  `state` now, and #548's blocker resolves to `OPEN` instead of a shrug.
- **`GH_REPO`** is set from the caller. Nothing checks the caller out, so gh had no remote to
  infer a repo from and a bare `547` or `#547` could not resolve. A full URL still wins over
  it, which is how a cross-repo blocker works.
- **Some cells hold a sentence, not a reference** ("the operator's retail-client
  confirmation…"). Word-splitting one into gh lookups produced `Blocked by PR the, which is not
  merged yet` — the same nonsense the `dpl-` ids made before they got their own arm. The whole
  cell is judged once now, and a human-stated block is quoted back rather than mangled.

`scripts/test-coordination-row-select.sh` **extracts** the awk and the ref guard from the
workflow between markers and runs them against fixtures shaped like the real state files, so
the test cannot pass while the shipped gate says something else; a moved marker fails loudly
instead of testing nothing. It runs unconditionally in `config-tests.yml`, because a path
filter would let an edit to the workflow skip the only thing that checks it.

⚠️ **This is a reusable workflow and seven other repos pin it by SHA.** `KTPInfrastructure`
calls it by local path and picks the fix up on merge; `KTPAMXX`, `KTPMatchHandler`,
`KTPCvarChecker`, `KTPAntiCheat`, `KTPHLStatsX`, `KTPDoDServerConfig` and `KTPDiscordRelay`
each need re-pinning in a follow-up. Deliberately not done here.
