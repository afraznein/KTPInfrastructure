# Public Lane B bot-test reports on GitHub Pages

## Scope and safety boundary

This publication path is only for synthetic Lane B matches containing exactly
12 bots in a 6v6 roster. The public site is a visual check of five example
matches. It is not a production stats host and must never ingest live-server,
production, mixed-roster, or real-player data. Production and real-player
statistics remain on the production stats servers and off GitHub.

The workflow has no SSH, database, fleet, package, or production credentials.
It validates an Actions run, obtains the immutable artifact ID and SHA-256
digest, and downloads only that ID from the source run. The artifact name must
also be exactly:

```text
lane-b-series-comparison-<source_run_id>
```

The five `lane-b-reports-*` artifacts, job logs, database output, daemon output,
and SQL are never downloaded.

Before download, and again afterward, the publisher verifies that the source
run is a successful same-repository `push` run of
`.github/workflows/lane-b-stats-e2e.yml` from a
`lane-b-preprod-series-*` tag. The tag prefix alone is not trust evidence. The
GitHub branch, refs, commits, and compare APIs must prove that `preprod` is
protected and that the exact tested `head_sha` is equal to or an ancestor of
its current tip. Tag protection is useful defense in depth but is not a
substitute for that check.

The helper then verifies all five source manifests, hashes, report-verification
records, `-TEST` match IDs, Lane B source mode, the fixed 360-second requested
play window, 12-bot summaries, 6v6 reports,
quality gates, team-only timelines, and exact bundle provenance. Provenance
must contain the canonical Infrastructure, MatchHandler, AMXX, and HLStatsX
repositories, each requested from `preprod` with a full 40-character commit.
The four-commit map must be identical across all five runs, and the
Infrastructure commit must equal the source run SHA.

Source HTML, SVG, Markdown, report JSON, names, and player identifiers are not
published. The helper constructs every public page from constant templates and
strictly validated numeric data. Players are deterministically relabeled
`Bot 01` through `Bot 12`. External or active HTML, source URLs, forms, scripts,
CSS imports/URLs, individual timing/positions, emails, credentials, and token
patterns fail closed or are omitted.

The exact 18-file public allowlist is:

```text
index.html
series-summary.json
publication-metadata.json
run-1/index.html
run-1/report.json
run-1/timeline.json
...
run-5/index.html
run-5/report.json
run-5/timeline.json
```

No `.nojekyll` file is required or generated. The Pages artifact contains only
this regenerated directory.

### Action supply-chain pins

Every action is from an official `actions/*` repository and is pinned to the
full commit resolved from its release tag through the GitHub API on 2026-08-25:

| Action release | Pinned commit |
|---|---|
| [`actions/checkout` v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1) | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| [`actions/download-artifact` v8.0.1](https://github.com/actions/download-artifact/releases/tag/v8.0.1) | `3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c` |
| [`actions/upload-pages-artifact` v5.0.0](https://github.com/actions/upload-pages-artifact/releases/tag/v5.0.0) | `fc324d3547104276b827a68afc52ff2a11cc49c9` |
| [`actions/deploy-pages` v5.0.0](https://github.com/actions/deploy-pages/releases/tag/v5.0.0) | `cd2ce8fcbc39b97be8ca5fce6e763baed58fa128` |

## Mandatory one-time repository setup

GitHub Pages is currently disabled. After this workflow reaches the default
branch (`main`), a repository administrator must make all settings changes:

1. Open **Settings -> Pages** and set **Build and deployment -> Source** to
   **GitHub Actions**.
2. Open **Settings -> Environments -> github-pages** and configure a
   **Required reviewers** protection rule with at least one user or team.
   Enable **Prevent self-review**. Both controls are mandatory. If the
   repository plan or settings UI does not expose either control, publication
   remains blocked until the plan/settings limitation is resolved.
3. In the same environment, set **Deployment branches and tags** to custom or
   selected policies. Add exactly one **branch** policy named `main`, with no
   wildcard, no tag policy, and no other branch policy. Do not use **Protected
   branches only**.

The required reviewer and prevention of self-review are mandatory for both
operator-requested and automatic publication.
The exact custom default-branch-only deployment policy is also mandatory.
Preparation queries the GitHub repository, refs, commits, environments, and
[deployment branch policies REST APIs](https://docs.github.com/en/rest/deployments/branch-policies)
and fails before packaging unless custom policies are enabled,
`protected_branches` is false, and the sole returned policy has type `branch`
and exactly matches the current repository default branch. It requires
positive API evidence that `prevent_self_review` is exactly `true` inside the
single `required_reviewers` protection rule; missing, null, or false values all
fail closed. The deploy job also targets the protected `github-pages`
environment, so approval remains a platform-enforced gate.

The validator requests GitHub REST API version `2026-03-10`. Under the official
contract, the environment response supplies the `protected_branches` and
`custom_branch_policies` booleans, while the deployment-policy list supplies
each policy's `name` and branch-or-tag `type`; missing type evidence fails
closed.

The workflow never changes repository settings. Do not run either
operator-requested or automatic publication until every setting above is
configured. An earlier dispatch fails closed, and a full deployment cannot be
validated locally.

Automatic publication is separately disabled by default. To opt in:

1. Open **Settings -> Secrets and variables -> Actions -> Variables**.
2. Create `KTP_LANE_B_PAGES_ENABLED` with the exact lowercase value `true`.

Do not create a secret for this toggle. A retroactive repository dispatch is an
explicit operator action and does not require the variable, but it still
requires the protected environment reviewer and prevention of self-review.

There is deliberately no `workflow_dispatch` trigger, so an operator cannot
select a tag or feature-branch copy of the publisher. GitHub documents that a
`repository_dispatch` runs the workflow from the repository default branch,
with `GITHUB_REF` set to that branch and `GITHUB_SHA` set to its last commit.
The helper independently queries the repository, default ref, and commit APIs,
then requires the event action `publish-lane-b-pages`, the exact default-branch
ref, and the live default-branch SHA. A stale or non-default publisher fails
closed. The environment's exact branch policy independently gates deployment.

## Publish the certified 2026-08-25 series

The existing certified bot series is Actions run
[`32866057356`](https://github.com/afraznein/KTPInfrastructure/actions/runs/32866057356).
After the workflow is merged through `preprod`, promoted to `main`, and the
mandatory Pages settings are configured, dispatch **Publish Lane B Bot Reports
to Pages** through the exact repository-dispatch event with numeric
`client_payload.source_run_id` set to `32866057356`.

Equivalent GitHub CLI command:

```powershell
gh api -X POST repos/afraznein/KTPInfrastructure/dispatches `
  -f event_type=publish-lane-b-pages `
  -F 'client_payload[source_run_id]=32866057356'
```

The repository API normally returns HTTP 204 with no response body before the
new Actions run appears in the UI. The source run ID is read only from that
client-payload field and must be a positive decimal integer. A run from a
different repository, fork, workflow, event, unmerged matching-tag commit,
failed conclusion, expired or changed artifact, non-Lane-B roster, provenance
mismatch, or malformed bundle fails closed before a Pages artifact is created.

Approve the `github-pages` environment deployment after reviewing the prepare
job's sanitized `$GITHUB_STEP_SUMMARY`. It lists the source run URL/id/tag/SHA,
immutable artifact id/digest, verified preprod ancestry, all four bundle SHAs,
five aliased test match IDs and pass states, output count, payload-manifest
hash, validation result, and approval instruction. It contains no source player
names or raw report content. The expected site URL is:

```text
https://afraznein.github.io/KTPInfrastructure/
```

## Future automatic publications

With `KTP_LANE_B_PAGES_ENABLED == 'true'`, successful completion of the Lane B
workflow prepares a publication only for a same-repository push whose series
tag starts `lane-b-preprod-series-` and whose tested commit is in current
`preprod`. The exact five-run artifact and every publication contract must
still pass. The mandatory environment reviewer is always the final approval
point. Removing the variable, or changing it to anything other than `true`,
disables the automatic path.

## Concurrency, reruns, and retention

Publication concurrency is latest-wins/coalescing. `cancel-in-progress: false`
does not cancel a running or approval-stalled publication, but GitHub retains at
most one pending run in the concurrency group. A newer repository dispatch can
replace an intermediate pending publication, so not every queued series is
guaranteed to deploy. Create a new repository dispatch explicitly if a
particular series must be published.

The prepared Pages artifact is named
`github-pages-<workflow_run_id>-<workflow_run_attempt>`. The prepare job exposes
that exact name as a job output, and deploy consumes the output rather than
recomputing the name.

- **Rerun failed jobs:** a failed deploy reuses the successful upstream prepare
  job and its stored artifact-name output, even though the workflow attempt has
  advanced.
- **Full rerun:** prepare runs again under the incremented attempt and creates a
  new unique Pages artifact name.
- **New repository dispatch:** a new workflow run ID creates a new unique name.

The Pages artifact is kept for 14 days so an approval wait is not constrained
by one-day retention. If an old attempt no longer has a usable artifact, start
a new repository dispatch rather than trying to reuse the expired deployment
artifact.

GitHub Pages serves only the latest successfully deployed publication at the
repository URL. The workflow does not commit a `gh-pages` branch and does not
provide browsable site history. The original Lane B Actions artifacts remain
the audit history and currently have 30-day retention.

## Local dry run

Use the downloaded series-comparison directory only, never the five raw report
artifacts:

```powershell
python scripts\prepare_lane_b_pages.py prepare `
  --source G:\path\to\lane-b-series-comparison-32866057356 `
  --source-metadata G:\path\to\validated-source-run.json `
  --output G:\path\to\empty-public-directory
```

`validated-source-run.json` must be produced by `validate-run` against the
GitHub API; it is not an operator-authored bypass file. Local preparation can
validate the artifact and render the payload, but it cannot prove final Pages
deployment or perform the environment approval.

To preview the trusted Actions summary after a successful local preparation:

```powershell
python scripts\prepare_lane_b_pages.py write-summary `
  --publication G:\path\to\empty-public-directory\publication-metadata.json `
  --output G:\path\to\step-summary.md
```

The payload-manifest hash covers the 17 non-self-referential public files; the
18th file is `publication-metadata.json`, which records that manifest.
