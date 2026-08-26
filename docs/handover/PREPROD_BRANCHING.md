# Preprod and production branch policy

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

`preprod` exists in the five repositories where `andsmit9` has write access:

- `KTPInfrastructure`
- `KTPAMXX`
- `KTPAMXXCurl` (renamed from `KTPAmxxCurl`)
- `KTPHLStatsX`
- `KTPMatchHandler`

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

## Remaining access blockers

`andsmit9` currently has no write access to:

- `KTP-ReAPI`
- `KTP-ReHLDS`
- `KTPDiscordRelay`

After write access is granted, create `preprod` directly from each repository's
current `main` tip. Do not infer the tip from a stale local clone.

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
- After access is granted, verify `preprod` exists in all three blocked repos.
- ~~Confirm KTPAMXX reports `main` as its GitHub default branch.~~ Confirmed
  2026-08-26 via `gh repo view --json defaultBranchRef` and `git ls-remote
  --symref origin HEAD` (both report `main`); `master` no longer exists as a
  remote ref.
