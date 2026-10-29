### Fixed
- `audit-config-key-drift.py` names *why* a config path was not compared. One sentence --
  "on no covered instance, or unparsable on all 24" -- was printed for three causes and did
  not name the fourth and commonest one: a path in the distributor's watch patterns that no
  target accepts, which parses fine. `listip.cfg` has been in that state since the
  2026-10-05 `servers.json` edit (mtime `2026-10-05 11:30:11 -0400`, 24 occurrences in
  `excludePatterns`, measured 2026-10-28), so the weekly issue title said "could not be
  parsed" of a file with nothing wrong with it and pointed the operator at a malformed file
  that does not exist. The other three causes each also raise a finding or an absent-source
  line, so this was the only silent one.
- `fleet-audit-gate.sh` leg 11 says "could not be compared" and counts the
  accepted-by-no-target paths out separately, off the check's own headline rather than by
  recounting. An artifact predating the new `excluded-everywhere:` field defaults it to 0,
  so the leg still fires on the total.
- `ktp_config_kv.classify()` refuses a sectioned INI by name (`sectioned`) instead of by the
  side effect of `mixed`. The two live sectioned files were already refused only because
  their `[section]` headers happen to be the only lines without `=` (measured: 26 content
  lines / 23 with `=` / 3 without for `grenade_loadout.ini`, 78 / 58 / 20 for
  `ktp_maps.ini`, and in both files every line without `=` is a bracketed header). Strip the
  entries out and the remainder classified as `list` with three keys literally named
  `[allies]`, `[axis]`, `[british]` -- which `config/local/grenade_loadout.ini` is. Comparing
  that against a populated copy would have compared invented keys against real ones, the
  same class as the `;`-read-as-a-key bug the module header records. Control:
  `hostname "[KTP] Dallas 1"` still classifies `cvar`, and `dodserver.cfg.example` still
  parses to 115 keys.
- A `file-missing-instance` shape is now `partial` or `absent` against the instances that
  **accept** the path rather than against all 24. No path is partially accepted today, so
  nothing moves; a path excluded on half the fleet and absent on the rest would have read
  `partial`, inventing a half that was never asked.

### Changed
- The gate's config-key transition baseline includes `KEYDRIFT-INCONCLUSIVE:` lines. One
  path gaining a reader while another loses one left the count unchanged and the text
  byte-identical, so the swap itself was not in the signal. ⚠️ The first run after this
  change re-baselines and reports "changed since last run" once.
- `excluded-everywhere` is reported in the headline and in the state file as a **subset** of
  `inconclusive`, never subtracted from it: moving those paths out would return exit 0 on a
  run that compared nothing for them.

### Fixed (docs)
- `docs/runbooks/CONFIG_KEY_DRIFT.md` no longer promises that an `excludePatterns` entry
  "takes a path out of this check's scope". It does not -- `scope` comes from
  `matches_watch_patterns` and is never intersected with `accepts` -- so applying the
  documented remedy is what turned a true `file-missing-instance` finding into a permanent
  weekly nag, and the runbook's own "the gate nags until it is zero" was unachievable by the
  route it recommended. `paths_in_scope` is 100, exactly the count of watched `.ini`/`.cfg`
  in the tree.
- Both runbooks' standing-findings tables mark the `listip.cfg` row superseded; it has been
  reported by neither check since 2026-10-05. `DISTRIBUTE_DRIFT.md` names the three
  remaining `absent` map files.
- Two operator decisions restated rather than carried forward: what a key is in a sectioned
  file (`allies.garand` or `garand`, which collides across sections), and whether `scope`
  should intersect `accepts` -- with the blind spot that trade buys, and two alternatives.
