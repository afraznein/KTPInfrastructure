### Added
- `ktp_config_kv.parse_sectioned_text()` reads a sectioned INI with **section-qualified**
  keys (`allies.garand`), so `grenade_loadout.ini` and `ktp_maps.ini` are compared by the
  weekly config-key drift check instead of being refused. Ruled by the operator 2026-10-29;
  it was the last thing `afraznein/KTPInfrastructure#723` was open on.

  The bare form is wrong rather than merely incomplete, and the reason this repo recorded
  for that was measurably false. The runbook, the issue thread and the module all said the
  bare form "collides across the three sections, which set the same weapon slots" --
  measured read-only against the distributor source 2026-10-30, the three nation sections of
  `grenade_loadout.ini` share **no** entry name at all (8 / 10 / 5 names, empty
  intersection). The collision is entirely in the other file: `ktp_maps.ini` puts **61
  entries onto 3 bare names** (`name` x21, `type` x21, `config` x19) across 21 sections, so
  a bare reader would compare three keys where sixty-one exist **and report agreement on
  every entry it dropped** -- which is the one outcome `audit-config-key-drift.py`'s own
  header exists to prevent.

  A sectioned file the qualified reader cannot place is still refused, and refused as
  `sectioned` rather than collapsed to `mixed`: an entry outside any `[section]`, a repeated
  section, a repeated key, or an entry that is not `key = value`. The remedy for those is a
  fix in the file, not a new reader, and the weekly reason text now says so.

  The entry-less dev stub `config/local/grenade_loadout.ini` now parses to an **empty key
  set** rather than to three keys literally named `[allies]`, `[axis]`, `[british]`. An
  empty set is a real answer -- against a populated instance every key there is named --
  which is the same rule the module already applies to an emptied flat source.

### Changed
- `docs/runbooks/CONFIG_KEY_DRIFT.md` decisions 3 and 4 are marked **ruled** rather than
  open, with the deciding reason for each, and the standing-findings row for the two
  sectioned files is superseded.
- Decision 4, ruled: `scope` does **not** intersect `accepts`, and such a path keeps its own
  bucket -- because an out-of-scope path never prints its name, so intersecting is not
  reversible by inspection and every future path that falls out of `servers.json`'s
  `includePatterns` would report clean by default. No code change was owed: the
  `excluded-everywhere` count added 2026-10-28 is that bucket.

### Verification
- `--selftest` green, and its sectioned legs now assert the qualified keys plus both
  refusals. Red-tested: with only `ktp_config_kv.py` reverted, 5 of 30 unit tests fail
  (the four new sectioned cases and the selftest subprocess) and the four refusal cases stay
  green -- correct, because a refusal does not depend on the reader.
- Fleet state, read-only 2026-10-30: both files are **one md5 on 24/24**, equal to the
  distributor source (`grenade_loadout.ini` `f9e0069d0798082515b946c121c95e9b`,
  `ktp_maps.ini` `c87f68c34864c7d732abd1c10e68be8b`). A third config in the same directory
  is the positive control and also reads one md5 on 24/24; a nonsense filename is absent on
  all 24, so the `md5sum` path is real. Identical bytes mean identical keys under any
  convention, so the first run that compares these two yields **zero** key findings -- the
  finding burst the ruling accepted does not exist at today's fleet state, and is a risk
  only if the fleet diverges first.
