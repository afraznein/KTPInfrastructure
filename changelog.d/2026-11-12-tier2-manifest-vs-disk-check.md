### `tier2`: the stage manifest is now checked against the runner's disk (2026-11-12)

`stage-runner.py --show` compared the runner's stage manifest with what is on disk and
labelled the two deliberate differences: plugins the Tier-2 workflow rebuilds every run,
and stack files `sync-runner-stack.py` mirrors from the fleet. Nothing acted on the
result. `--show` always exited 0, and `_stage_manifest.staged_md5()` had no callers.

- New `tests/integration/test_stage_manifest_vs_disk.py` runs in every Tier-2 run. It
  fails when a manifest entry differs from disk and neither deliberate class explains it,
  when a manifest entry is missing from disk, or when the workflow or drift checker can't
  be read (so the difference can't be classified). It needs no hlds and skips when no
  manifest is present.
- New `stage-runner.py --check`: the same table as `--show`, but it exits 1 on any
  unexplained row.
- The classification moved to `scripts/runner_manifest.py`, which uses only the standard
  library, so the suite's venv (no paramiko) can use it. The fleet-mirror list is now
  parsed out of `ktp-tier2-stack-drift.py` instead of imported. That script exits at
  import when paramiko is missing.
- A test-mode plugin with no manifest record is now labelled. If the workflow installs
  it, the row says so (`KTPHudObserver.amxx`). If nothing installs it, `--check` fails.
  Before this change, an absent record and a deliberately absent one printed the same
  blank line.
