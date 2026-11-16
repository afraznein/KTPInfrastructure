### docs: five operating traps written into the docs they belong to (2026-11-16)
- `docs/runbooks/REPORT_PIPELINE_INSTALL.md`: a corpus-wide regeneration does not fit the
  service's start timeout; run `generate` once as a transient unit with the timer paused.
- `docs/CI_SETUP.md`: on a failure the diff cannot explain, compare `Image Release:` with the
  last green `main` run first.
- `docs/DEPLOY_MANIFEST.md`: a bundle clone's origin is the bundle filename, so `--record-only`
  from it needs `--source-repo`, and `--report` does not flag the mislabel.
- `docs/runbooks/CI_INSTALL_ALLOWLIST.md`: a change to `ktp-ci-install` always owes a person
  install, and `outside-list` stays red until it happens.
- `scripts/mmr/README.md`: Elo out-orders OpenSkill; `tau` and `beta` are already refuted as causes.
