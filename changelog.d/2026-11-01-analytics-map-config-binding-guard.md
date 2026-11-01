### `tests`+`scripts`: nothing cross-checked a map's analytics config against the binding the map list uses (2026-11-01)

`map_flag_facts.json` names the config each map plays under, `map_scoring.json`
carries the tick model under that name, and `ktp_maps.ini` says which cfg the
servers actually exec. The first two were checked against each other and against
the config tree; neither was ever checked against the third. A disagreement there
scores every match on that map against the wrong tick values, and it does it
silently, because both analytics files stay internally consistent while they do it.

That is the Saints case: `b3e`/`b4e` pointing at `saints_b1` (allies 10202 / axis
12020) while the servers exec `ktp_saints.cfg` (20011 / 21100). It was corrected in
`10392a2` and then re-raised from a held note eight days later, because the only
thing that had ever settled it was somebody reading both files by hand.

- **`tests/config_parse/test_analytics_map_config_binding.py`** asserts the join in
  four directions, for maps present on both sides: the curated `config` equals the
  binding minus its filename shape; a map the list binds is not left `config: null`
  (right for an aim map, wrong for a bound one); a named config has a `map_scoring`
  entry; and the served `maps_by_name` view agrees with the binding too — that view
  is generated, so it agrees by construction only as of the last generator run, and
  a stale commit of it passes every other leg here.
  ⛔ **Orphan direction deliberately NOT asserted**: a `map_scoring` entry no map
  points at is a config file that exists, and the generator's own docstring says
  pruning one deletes a fact.
  The parse control runs first and fails with *the probe is broken* rather than
  passing on an empty join. Mutation-checked: a changed binding reddens two legs, a
  nulled config reddens two, a renamed `map_scoring` entry reddens the orphan leg, a
  disagreeing `maps_by_name` entry reddens the served leg, and breaking the ini
  key name reddens the control. A change to a map the list does **not** bind stays
  green, which is the scope this test claims.
- **`map_scoring_facts.py` gains `CONFIG_FILE_PREFIX` + `map_config_name()`.** The
  `ktp_<name>.cfg` ↔ `map_config` rule was inline in the generator, and the test
  reads it from there rather than restating it — two spellings of one naming rule
  disagree eventually, and the disagreement would look like a drifted config.
- ⚠️ **Scope:** `config/local/ktp_maps.ini` is a copy of the fleet's map list and its
  own header says it is not kept in sync, so a red here is a statement about this
  repo's two analytics files, not about what an instance execs tonight.
