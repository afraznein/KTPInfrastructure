# Preprod and production branch policy

> 🔻 **RETIRED FOR THIS REPOSITORY, 2026-09-19.** KTPInfrastructure no longer keeps a
> `preprod` branch; everything here targets `main`. The ruling and its evidence are in
> `ktp-coordination` `state/infra-mmr-ratings.md` — nothing deploys from `preprod`, and 54 of
> the last 80 merges went straight to `main` already. The tip is preserved as the tag
> `archive/preprod-retired-20260919` (`08ccdfaf`).
>
> ⚠️ **The policy below still applies to KTPAMXX, KTPMatchHandler and KTPHLStatsX**, whose
> `preprod` branches are live and genuinely diverged from their `main`. Read every paragraph
> that follows as being about those repositories, not this one.
>
> 🔑 One consequence worth carrying, because it is what made the retirement a three-repo
> change rather than a branch delete: `preprod` was not only a merge route, it was a **harness
> lineage pointer consumed cross-repo**. KTPAMXX and KTPHLStatsX passed `infrastructure_ref:
> preprod` as a literal, a guard pinned `LINEAGE = "preprod"`, and the branch name appeared
> inside a **required status context name**. Deleting the branch first would have blocked every
> PR in both repos with no author-side fix.

## The preprod reconciler, and why it is gone

`.github/workflows/reconcile-preprod.yml` kept `preprod` a superset of `main` without anyone
hand-rolling a reconcile PR — five of those got made by hand in three days before it existed.
It was deleted with the branch. Its three attempts are recorded here because each one hid the
next, and the same trap is waiting for anyone automating a push to a protected branch:

1. **Fast-forward push, immediately** — rejected with *"2 of 2 required status checks are in
   progress"*. Read at the time as *a protected branch refuses a direct push*. It does not; the
   checks simply had not finished yet. ⚠️ The error names the wrong cause.
2. **Open a PR + auto-merge** — `gh pr create` refused outright: *"GitHub Actions is not
   permitted to create or approve pull requests"*. Repo auto-merge was disabled besides, so the
   PR would have sat open anyway.
3. **Wait for the checks, then fast-forward** — what shipped.

🔑 The asymmetry that made a merge commit impossible, which is the part worth carrying:
`integration` fires on a push to `main` and on a `pull_request`, and on nothing else. **A fresh
merge commit pushed to a topic branch can never earn that check**, so it could never be pushed
to a branch requiring it. A fast-forward sidesteps it by reusing `main`'s own already-green sha.
✅ It also failed safe on its own subject: its last run, on `main`'s tip after the retirement,
annotated *"No preprod branch; nothing to reconcile."* and exited 0 rather than painting an
ordinary push red.

## Policy

Every KTP repository uses a permanent `preprod` branch as the integration
gate before its production branch (`main`). Contributors open PRs into
`preprod`; after those changes pass the same automated checks used for
production, a separate `preprod` PR promotes them into `main`.

Cross-repository changes must first be collected on a consistently named
feature branch in every affected repository. Finish and validate the whole
bundle against immutable repository SHAs before opening the coordinated PRs
to `preprod`. Do not merge a component PR merely because that repository is
green in isolation. Open and review all bundle PRs together, then merge them in
a short dependency-safe window and rerun the cross-repository gate on the
resulting `preprod` SHAs. This preserves the `preprod` integration gate while
avoiding a partially assembled feature on it.

KTPAMXX's normalization from `master` to `main` is complete. The GitHub
default branch is `main` — confirmed both via `gh repo view afraznein/KTPAMXX
--json defaultBranchRef` and independently via `git ls-remote --symref origin
HEAD` (the two can disagree; check both). `master` is not merely superseded
as the default, it no longer exists as a ref at all: `git ls-remote origin
'refs/heads/*'` lists `main` and `preprod` plus the active feature branches,
and no `master`.

The hard stats-capture gate is deterministic corpus replay. It replays the
committed logs under `tests/e2e_stats/corpus/` through an ephemeral MySQL
database and compares exact results with `expected.json`. It starts no game
server and runs no bots.

The live Lane B bot match remains informational. It runs only inside an
ephemeral container on a GitHub-hosted runner. `new_bot` and Marine Bot must
never be installed on or connect to a persistent KTP server, including NY1 or
the Tier 2/data-server host.

An on-demand playable preprod server is deliberately parked pending an
ephemeral-infrastructure design. Do not reuse a production fleet slot without
an explicit operator decision.

## Implemented state (2026-08-13 ET)

`preprod` existed in the five repositories where `andsmit9` had write access
as of this date:

- `KTPInfrastructure`
- `KTPAMXX`
- `KTPAMXXCurl` (renamed from `KTPAmxxCurl`)
- `KTPHLStatsX`
- `KTPMatchHandler`

**Stale as of 2026-08-26 ET** — see "Access blockers resolved" below.
`andsmit9` now has write access to three more repositories, and all three now
carry `preprod`, so the live count is eight, not five.

KTPInfrastructure `preprod` contains:

- the selected Lane B and stats-capture work;
- Tier 2 PR triggers for both `main` and `preprod`;
- nightly Tier 2 coverage for `preprod`, serialized on the self-hosted runner;
- nightly Lane B coverage for `preprod`;
- a reusable `lane: corpus` workflow that assembles the delta-only HLStatsX
  daemon, derives zero-data base DDL from the committed production fixture,
  and replays the deterministic corpus.

The scheduled `main` legs are intentionally paused while the preprod suite is
proven. PR gates continue to run for both `main` and `preprod`. Re-enable the
`main` nightly legs only as an explicit production-readiness change. GitHub
Actions schedules execute the workflow copy on the default branch, so this
preprod-only schedule takes effect after the workflow is promoted to `main`.

The caller workflows were merged through green PRs:

- KTPAMXX PR #17 -> `preprod`
- KTPHLStatsX PR #5 -> `preprod`

The observed required-check context is
`corpus-regression / Lane B (corpus, preprod)`. Both live verification runs
passed on 2026-08-13 ET.

KTPHLStatsX PR #6 also merged into `preprod` after that gate passed. It makes
`ConnectAnnounce` fail closed and adds migration 009, which explicitly sets
`ConnectAnnounce=0` for every registered server. This preserves stats
collection while preventing rank/points connect messages in game chat.

## Required branch protection

An administrator must:

1. Mirror each repository's existing `main` protection onto `preprod`.
2. Require `corpus-regression / Lane B (corpus, preprod)` on both `main` and
   `preprod` in KTPAMXX and KTPHLStatsX.
3. Require `Tier 2 Integration / integration` on KTPInfrastructure `preprod`
   in the same way it is required on `main`.
4. Require PR review and disallow direct pushes where that matches the
   repository's existing `main` policy.

The current token has push but not admin access, so it cannot create or change
these rules.

## Access blockers resolved (2026-08-26 ET)

This section previously said `andsmit9` had no write access to `KTP-ReAPI`,
`KTP-ReHLDS` and `KTPDiscordRelay`. That is no longer the case — access was
granted, and `preprod` has since been created in all three (this is a
documentation-only correction; the grant itself was an operator action, not
made from this doc).

Verified 2026-08-26 ET, per repository:

```
gh api repos/afraznein/KTP-ReAPI/collaborators/andsmit9/permission        -> "permission":"write"
gh api repos/afraznein/KTP-ReHLDS/collaborators/andsmit9/permission       -> "permission":"write"
gh api repos/afraznein/KTPDiscordRelay/collaborators/andsmit9/permission  -> "permission":"write"

gh api repos/afraznein/KTP-ReAPI/branches/preprod        -> 200, branch exists
gh api repos/afraznein/KTP-ReHLDS/branches/preprod       -> 200, branch exists
gh api repos/afraznein/KTPDiscordRelay/branches/preprod  -> 200, branch exists
```

Control for both checks: the same calls against a nonexistent user
(`.../collaborators/nonexistentuser99999xyz/permission`) and a nonexistent
branch name (`.../branches/this-branch-does-not-exist-xyz`) both correctly
return 404, so the three 200/`write` results above are not a probe that
returns success unconditionally.

Note the repo names are hyphenated on GitHub — `KTP-ReAPI` and `KTP-ReHLDS`
— even though the local directories are `KTPReAPI`/`KTPReHLDS`. A slug built
from the directory name 404s and reads as "repo not found," not as "no
access."

KTPAMXX's GitHub default branch has been changed to `main` (re-verified
2026-08-26). `master` has since been deleted from the remote outright, rather
than left in place pending a downstream-consumer audit as this section
originally planned — so any consumer still assuming a `master` ref needs to
be repointed to `main`, not merely notified of the default-branch change.

## Release notes

Merging is not deployment. In particular, applying KTPHLStatsX migration 009
to a server database must be followed by an in-place daemon configuration
reload:

```bash
mysql -u hlstatsx -p hlstatsx < sql/migrate_009_disable_connect_announcements.sql
systemctl kill -s HUP hlstatsx
```

The reload does not disable event ingestion or historical skill calculation;
it disables only the player-facing connect announcement.

## Verification still pending

- After the workflow is promoted to the default branch, confirm the first
  scheduled Tier 2 and Lane B runs each show a `preprod` leg and no `main` leg.
- After branch protection is installed, verify a failing corpus replay blocks
  merges into both `preprod` and `main`.
- ~~After access is granted, verify `preprod` exists in all three blocked repos.~~
  `preprod` existing in `KTP-ReAPI`, `KTP-ReHLDS` and `KTPDiscordRelay` was
  confirmed 2026-08-26 ET — see "Access blockers resolved" above.
- ~~Confirm KTPAMXX reports `main` as its GitHub default branch.~~ Confirmed
  2026-08-26 via `gh repo view --json defaultBranchRef` and `git ls-remote
  --symref origin HEAD` (both report `main`); `master` no longer exists as a
  remote ref.
