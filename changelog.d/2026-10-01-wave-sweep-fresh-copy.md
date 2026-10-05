### `scripts`: the workstation wave sweep runs a ledger the freshness guard can prove current (2026-10-01)

The scheduled sweep on the operator workstation has exported `ktp-wave-ledger.py`
and its siblings from `origin/main` into `~/.ktp/_from-main` since 2026-09-21, and
run them there. `ktp_script_freshness.py` refused that every night with *"it is not
under <checkout>"*, the wrapper reported rc 2, and the sweep has been blind since.
The guard was right: a copy outside any checkout has no provenance.

`scripts/ktp-wave-sweep.py` is now tracked here. It used to exist only in the
project root. It keeps a dedicated clone (`~/.ktp/wave-sweep-tree`, used for
nothing else) and, on each run:

1. fetches `origin main`;
2. refuses if any tracked file in the clone was edited, keeping the edit;
3. checks out `origin/main` detached and asserts `HEAD` and `scripts/` match it;
4. runs the ledger from inside the clone, so the guard verifies it for real.

`KTP_FRESHNESS_BYPASS`, `_OFFLINE`, `_REPO` and `_REF` are stripped from the
child's environment, so a scheduled run cannot inherit one. The guard is
unchanged. `tests/unit/test_wave_sweep.py` runs the real guard against a
throwaway upstream: an exported copy and a stale checkout are still refused,
and the dedicated tree runs.
