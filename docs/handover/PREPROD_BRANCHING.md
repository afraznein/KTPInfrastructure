# Preprod and production branch policy

## Policy

Every KTP repository uses a permanent `preprod` branch as the integration
gate before its production branch (`main`). Contributors open PRs into
`preprod`; after those changes pass the same automated checks used for
production, a separate `preprod` PR promotes them into `main`.

KTPAMXX is being normalized from `master` to `main`. Both refs currently
exist, but the GitHub default remains `master` until an administrator changes
it.

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
- nightly Tier 2 matrices over `main` and `preprod`, serialized on the
  self-hosted runner;
- nightly Lane B matrices over `main` and `preprod`;
- a reusable `lane: corpus` workflow that assembles the delta-only HLStatsX
  daemon, derives zero-data base DDL from the committed production fixture,
  and replays the deterministic corpus.

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

An administrator must also change KTPAMXX's GitHub default branch after
confirming `main` still matches the intended `master` tip:

```bash
gh api -X PATCH repos/afraznein/KTPAMXX -f default_branch=main
```

Leave `master` in place until downstream consumers have been audited.

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

- Confirm the first scheduled Tier 2 and Lane B runs after these changes each
  show separate `main` and `preprod` legs.
- After branch protection is installed, verify a failing corpus replay blocks
  merges into both `preprod` and `main`.
- After access is granted, verify `preprod` exists in all three blocked repos.
- Confirm KTPAMXX reports `main` as its GitHub default branch.
