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

### Re-cut
- `#632` carried this and was **closed unmerged** 2026-10-07T01:54:52Z with no recorded reason, so
  the content was re-cut onto `main` on 2026-10-14 rather than guessed at. It is the same change:
  a clean cherry-pick of `fac8f879`, no conflicts, `+181/−11` across the same three files, because
  `main` had not touched the checker or its test in the 236 commits since — the installed copy and
  `origin/main` both still read md5 `b75d3aac32dae3b19f3a1bc93f2c7e0b`.
- **Verified by effect on the data server without installing anything**, by staging the re-cut copy
  to a scratch path and running it bare: the installed pre-fix copy exits **2** with
  `cannot read: ... /usr/local/bin/hltv-api.py.example`, while the re-cut exits **0** and prints both
  the `reference:` line and `hltv-api: no drift (409 lines, secrets redacted before compare)`. The
  scratch copy was removed and the installed copy is byte-unchanged.
- That run also shows why the provenance line is the point rather than a nicety. The figures above
  were measured on 2026-10-06 and have moved a long way: the reference now reports **313 commits
  behind** the checkout's own `origin/main` ref, which had itself not been fetched since
  2026-10-13 23:13. The "agreement by luck rather than by construction" this entry describes has
  widened by two orders of magnitude, and until now nothing printed it.
