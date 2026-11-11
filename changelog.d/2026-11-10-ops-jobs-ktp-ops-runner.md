### `ci`: fleet-audit and report-regeneration move to the `ktp-ops` runner (2026-11-10)

The four root-needing jobs (`fleet-audit.yml` collect, notify and promote, and
`report-regeneration.yml` regenerate) now run on `[self-hosted, ktp-ops]`, a root runner
that serves no pull-request workflow. The tier-2 runner keeps only
`tier2-integration.yml`, which is what lets it drop root.

`tests/unit/test_self_hosted_runner_split.py` holds the split: the ops workflows run only
on `ktp-ops` and have no pull-request trigger, no pull-request workflow names `ktp-ops`,
and only `tier2-integration.yml` uses `ktp-tier2`. Against the previous workflows two of
its five tests fail.

**Merge only once the `ktp-ops` runner is registered and online**
(`docs/runbooks/TIER2_RUNNER_NONROOT_CUTOVER.md` § A); before that the jobs queue with no
runner to take them.
