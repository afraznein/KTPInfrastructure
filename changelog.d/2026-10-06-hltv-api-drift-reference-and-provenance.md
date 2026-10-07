### Fixed
- `scripts/check-hltv-api-drift.py` searches for its reference instead of assuming one beside the
  script, and reports the reference's git provenance on every run including the clean one. The only
  default was `dirname(__file__)/hltv-api.py.example` — true in a checkout, never true for the copy
  installed at `/usr/local/bin`, so a bare run on the data server exited 2 with
  `cannot read: [Errno 2] ... /usr/local/bin/hltv-api.py.example` and no hint about what to pass.
  Measured there 2026-10-06: the same installed binary reports `no drift (409 lines)` the moment it
  is handed `--example /opt/ktp-infra/scripts/hltv-api.py.example`. The error now names the
  candidate locations, so the fix is actionable from the message alone.
- The reference is a checkout on a box that is deliberately never auto-pulled, so `no drift` against
  it is not `no drift` against `origin/main`. Measured the same day: `/opt/ktp-infra` sits at
  `dc7a1e7 2026-10-05 11:10` while its own `origin/main` ref is `d8a2d67 2026-10-05 15:06` — the
  reference was already behind a ref that is itself only as fresh as the last fetch. The provenance
  line states both, and `UNKNOWN` is printed out loud rather than omitted, because a vanishing line
  leaves the report reading as though it had been measured against `main`.

### Added
- Seven cases in `tests/unit/test_hltv_api_drift.py` covering an explicit missing reference (exit 2,
  candidates named), the search falling through an absent candidate, no candidate at all, the
  in-checkout default still resolving, provenance present on the clean path, `UNKNOWN` outside a
  checkout, and no exception when `git` is unavailable. Mutation-checked: dropping the provenance
  line and reverting the search to a single default each redden a different case.
