### `scripts`: scope `stage-runner.py --show`'s manifest/disk warning, and write down what staging does not do (2026-10-30)

`MANIFEST DISAGREES WITH DISK` fired unscoped. The Tier-2 workflow compiles its own copy of the
plugins it gates on and installs each over whatever was staged, baking a fresh per-minute
`BUILD_TIME` every run — so for those artifacts the staged md5 can never match disk and the warning
was guaranteed noise, on the one tool whose job is to say what the runner holds.

- The flag now distinguishes a workflow-rebuilt artifact from one nothing rebuilds. The scope is
  derived from `.github/workflows/tier2-integration.yml` by its install destinations, not listed in
  the script: this file already carries one hand-kept mirror of a fact owned elsewhere and says so.
  An unreadable workflow returns a value distinct from "rebuilds nothing", so it keeps the warning
  and says why it could not scope it — the scope is an improvement on the warning, not a
  precondition for it.
- `tests/unit/test_stage_runner_show_flags.py` pulls in both directions: the noise class suppressed,
  and a real disagreement still reported for an artifact the workflow leaves alone. The parse is
  tested in the over-matching direction too, which is the dangerous one — a pattern that also
  matched the workflow's `test -f` verify step would claim artifacts the workflow never installs and
  silence the only line worth printing.
- The module docstring now carries the fact that the runner's plugins tree is **not** what the
  Tier-2 gate tests, and that env outranks this manifest in the suite's version resolution. That had
  been established while repairing a gate pinned to a superseded build, and lived only in that pull
  request's description — so the next reader of this script could not find it.
