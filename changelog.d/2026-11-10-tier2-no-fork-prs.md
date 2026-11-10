### `ci`: keep fork pull requests off the tier-2 runner (2026-11-10)

Tier 2 Integration no longer runs for pull requests from forks. Its self-hosted
runner is root on the production data server, and `pull_request` runs the workflow
file from the PR's own branch, so a fork could run anything there. Fork PRs now
show the job as skipped; to test one, push its branch to this repo.
