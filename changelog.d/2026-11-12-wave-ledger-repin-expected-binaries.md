### `scripts`: `ktp-wave-ledger.py` checks and re-pins `provision/expected-binaries.conf` (2026-11-12)

The weekly fleet audit runs from a fresh checkout on the data server and compares the
fleet against `provision/expected-binaries.conf`. It cannot read the version rows or the
wave ledger, so that file is a second, hand-kept record of the same md5s, and every
engine/dodx wave left it stale: the 11-02 and 11-09 audits both re-reported the new
hashes as new repo drift and reopened #787.

- `reconcile` and `sweep` now compare the baseline's `[default]` pins against the md5 the
  whole fleet runs and report `EXPECTED_STALE` for any pin the fleet has uniformly moved
  past. Either exits 1. Reconcile still marks the wave reconciled, since the rows agree;
  only the pin is owed, and it changes when a PR merges.
- `repin-expected` reads the fleet and prints the replacement for each stale pin;
  `--write` edits the file in place (comments and line endings untouched) for a PR. A pin
  whose file differs across instances, or is missing on any, is left alone: a partial
  activation is not a baseline.
- `$KTP_EXPECTED_BINARIES` overrides the path. A missing file is reported as not checked,
  never as a pass.
- `hlds_linux` and `libsteam_api.so` are pinned but not in the ledger's fleet read; the
  output names them as unchecked.
- `docs/RELEASE_CHECKLISTS.md`: the re-pin sits next to the row flip.
