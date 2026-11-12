### `scripts`: the fleet-audit gate stops counting a config path `servers.json` excludes on every target (2026-11-12)

Per the operator's ruling of 2026-11-12. `listip.cfg` is in the distributor's watch
patterns and in `excludePatterns` on all 24 game targets, so the key-drift check compares
it against nothing and reports it uncompared. Leg 11 of the gate counted that every week,
so the weekly fleet-audit issue could not close on a run with nothing else in it.

- `scripts/audit-config-key-drift.py`: the headline gains `ruled-excluded: N`, the
  uncompared paths that parse and that every target names in `excludePatterns`. Also
  recorded as `ruled_excluded` in the state file. Scope and the report table are
  unchanged; the path is still listed by name.
- `scripts/fleet-audit-gate.sh`: leg 11 subtracts that count and nothing else. A path
  that falls out only through `includePatterns`, is absent from the source, or does not
  parse still fires. A count that is not a subset of `excluded-everywhere` is ignored,
  and an artifact without the field reads it as 0, so both fail loud.
- `docs/runbooks/CONFIG_KEY_DRIFT.md`: decision 4 amended; the headline section
  describes the new count.
