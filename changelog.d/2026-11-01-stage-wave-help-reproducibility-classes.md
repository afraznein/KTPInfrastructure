### `scripts`: `stage-wave.py`'s build-base help said no wave artifact is byte-reproducible, which is false for one of the three classes (2026-11-01)

The `--base` gate's help, the `--allow-missing-base` help, the FATAL and WARNING
text and `build_stamp`'s docstring all said *none of these artifacts is
byte-reproducible*, and named `stats_logging.amxx` as unrecoverable for that
reason. `stats_logging.amxx` is the counter-example: it is one of KTPAMXX's
in-tree plugins, and those bake neither a sha nor a timestamp.

Read at source on `afraznein/KTPAMXX` `origin/main`: `plugins/dod/stats_logging.sma`
includes `<ktp_version_reporter>`; `plugins/include/ktp_version_reporter.inc`
defaults both `KTP_BUILD_SHA` and `KTP_BUILD_TIME` to the literal `"unknown"`
under `#if !defined`; and no build script in that repo defines either (the token
resolves in three files there — `CHANGELOG.md`, `CLAUDE.md` and that `.inc` —
against a control in a stamping plugin repo where it resolves in `compile.sh`,
and a nonsense-token control at zero). So a rebuild from the same commit is
byte-identical and rebuild-and-compare does find the base.

Why the wording matters rather than just being imprecise: rebuild-and-compare is
the check that catches a wrong or churned build, and a help text that says it
cannot work for any artifact is a reason not to run it for the class where it
does.

- The help now names three classes: KTPAMXX in-tree plugins (reproducible from
  their commit, **against the same `amxxpc`, which no commit pins**); a plugin
  built by its own repo's `compile.sh` (per-minute `KTP_BUILD_TIME`, not
  reproducible unless the exact UTC minute is known); the C++ side (build-id and
  `__DATE__`, same outcome).
- `--base` stays REQUIRED for every class, including the reproducible one — a
  recorded base is what makes its rebuild-and-compare a one-liner instead of an
  archaeology exercise. No gate, default or exit code moves.
- `build_stamp()` returning `None` is now documented as a class fact rather than
  a lost stamp.

⚠️ **The same claim has three other homes and this PR deliberately does not touch
them**: `ktp-wave-ledger.py`'s module docstring and its `NO_BASE` status string,
`ktp_script_freshness.py`'s docstring, and `tests/unit/test_stage_wave_build_base.py`'s
own docstring. `NO_BASE` cannot be reworded without also editing the assertion in
that test (`"not byte-reproducible" in out`), which is a different kind of change
from a help-text correction.
