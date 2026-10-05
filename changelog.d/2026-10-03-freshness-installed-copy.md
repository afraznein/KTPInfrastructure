### `scripts`: the freshness guard accepts a current installed copy (2026-10-03)

`ktp-verify-deploy` on `origin/main` calls `require_current()`, which refused any file
outside a git checkout. Installed at `/usr/local/bin`, it would exit 3 on every run of
the nightly post-restart and Monday post-matchday soak suites, which shell out to it.

- `ktp_script_freshness.py`: a file outside any checkout is checked through the deploy
  manifest `ktp-install` writes. It must still have the md5 of its last row, and that
  must be the blob at the fetched `origin/main` for the row's `source_path`, in
  `KTP_FRESHNESS_REPO` (default `/opt/ktp-infra`). The fetch writes only
  `refs/remotes/origin/main`. No row, a hand-edit, an old commit, an unreadable
  manifest or another repo all refuse. A copy inside a checkout is checked as before.
- `KTP_MANIFEST` is honoured, as in `ktp-install`.
- Tests in `tests/unit/test_fleet_script_freshness.py`; `test_wave_sweep.py` now
  expects the new refusal reason for an exported copy, which is still refused.
