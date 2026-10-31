### `scripts`: scope `stage-runner.py --show`'s manifest/disk warning, and write down what staging does not do (2026-10-30)

`MANIFEST DISAGREES WITH DISK` fired unscoped, and two classes of artifact on that runner keep their
record somewhere other than this manifest. The Tier-2 workflow compiles its own copy of the plugins
it gates on and installs each over whatever was staged, baking a fresh per-minute `BUILD_TIME` every
run; and `sync-runner-stack.py` mirrors the stack files from the fleet, where byte equality with the
fleet is the point and the manifest is explicitly not the ledger. For both, the warning was
guaranteed noise on the one tool whose job is to say what the runner holds — and one of them got
written up as a three-artifact defect on a healthy runner.

- `--show` now names each case instead of calling either one drift. Both scopes are derived rather
  than listed in the script — the workflow's `install -D` destinations, and the drift checker's own
  `STACK_FILES` / `PLUGINS_STRICT`, read the same way `sync-runner-stack.py` reads them. This file
  already carries one hand-kept mirror of a fact owned elsewhere and says so.
- Either source being unreadable yields a value distinct from "nothing in this class", so it keeps
  the warning and says which scope it could not read. The scope is an improvement on the warning,
  not a precondition for it.
- `tests/unit/test_stage_runner_show_flags.py` pulls in both directions: each noise class
  suppressed, and an artifact in neither class still reporting. The parses are tested in the
  over-matching direction too, which is the dangerous one — a pattern that also matched the
  workflow's `test -f` verify step, or a mirror set that swallowed the test-mode builds, would
  silence the only line worth printing.
- The module docstring now carries the fact that the runner's plugins tree is **not** what the
  Tier-2 gate tests, and that env outranks this manifest in the suite's version resolution. That had
  been established while repairing a gate pinned to a superseded build, and lived only in that pull
  request's description — so the next reader of this script could not find it.
