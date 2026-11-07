### `scripts` + `docs`: the "no wave artifact is byte-reproducible" claim, in the four places the 2026-11-01 correction deliberately left (2026-11-07)

`stage-wave.py --help` was corrected on 2026-11-01 to name three artifact
classes instead of claiming none of them reproduces. That PR named the other
homes of the same sentence and left them alone, because one of them is a status
string pinned by a test assertion. This is the follow-up, and it found two homes
the earlier note did not list.

- `ktp-wave-ledger.py`'s module docstring, its `record_wave()` docstring, and
  its `NO_BASE` status string -- **the last of these is where a reader actually
  meets the claim**, since `ktp-wave-ledger.py status` prints it per artifact
  with no recorded base.
- `ktp_script_freshness.py`'s docstring, in the paragraph explaining why a stale
  stager skipping `--pull-live` costs something.
- `docs/RELEASE_CHECKLISTS.md` and `scripts/README.md`, neither of which the
  earlier note listed.

Each now says that recovery depends on the artifact class: KTPAMXX's in-tree
plugins (`stats_logging.amxx`, `admin.amxx`) bake neither a sha nor a timestamp
and DO rebuild byte-identically from their commit -- **against the same
`amxxpc`, which no commit pins** -- while a plugin built by its own repo's
`compile.sh` bakes a per-minute `KTP_BUILD_TIME` and the C++ side bakes a
build-id and `__DATE__`, so for those a rebuild returns a mismatch for the
correct base.

`scripts/fetch_engine_artifact.py` and its test keep the unqualified claim: they
are about the engine, where it is true.

`--base` stays required for every class. No gate, default, exit code or output
path moves.
