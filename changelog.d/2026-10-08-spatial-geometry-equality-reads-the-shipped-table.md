### `tests`: the spatial geometry equality now reads the website's table instead of restating it (2026-10-08)

`test_reproduces_the_matrices_the_website_ships` compared the derivation against matrices typed
into the test as literals and commented "Hand-derived", while a comment three lines above named
the real source: `src/features/public-match-report/fixtures/map-geometry.json` in
`searse/keep-the-prac`. So the regression that was supposed to prove the generator can replace
the hand-maintained table was comparing it against a transcription of that table. All three
copies could drift together and still agree, and a mistyped matrix was invisible. A tripwire
that restates a contract is not checking it.

Both sides are now read. Generator inputs come from `config/analytics/spatial_maps/`; the
expected output comes from `tests/fixtures/site_map_geometry/map-geometry.json`, a byte-for-byte
copy of the site's fixture, with `PIN.json` recording its upstream repo, path, commit, blob and
sha256.

- The comparison covers both matrices and the dimensions, not `world_to_pixel` alone, and uses a
  relative tolerance because the site rounds `pixel_to_world` while shipping `world_to_pixel`
  unrounded.
- A credential is the reason this is vendored rather than fetched: this repo is public, the site's
  is private, and `config-tests.yml` runs `tests/unit/` with no network and no auth. `PIN.json`
  states which drift directions that catches and which it does not, rather than implying it
  catches all of them. Drift in our own table, a tampered reference copy and a shrinking fixture
  each fail at PR time; a hand edit made upstream is the one residual hole and is named as such.
  The deployable table stays authoritative over the payload.
- Non-vacuity is asserted, not assumed: the map set is pinned, every descriptor is checked for
  both 3x3 matrices, and the comparison must cover every overview block this repo deploys. An
  emptied or shortened fixture fails a named assertion instead of quietly comparing less.
- Proceeding on `dod_anzio` and `dod_thunder2` only, per the 2026-10-08 ruling. ⚠️ Equality is
  not endorsement and reads like one: `registry.json` marks every review flag true for
  `dod_anzio` alone, so on `dod_thunder2` — review flags at their false defaults, no matches —
  the equality proves the shipped table matches the generator and **not** that either is right
  for that map. `dod_lennon5_b1` ships on the site with no config here; it is asserted as
  shipped-but-unconfigured rather than skipped, and stays deferred until a capture exists.
- The pool maps the equality does not cover are named as pending rather than left silently absent:
  `registry.json`'s set of maps with no `spatial_config` is pinned, each is asserted to claim no
  review, and the configured set must equal the set actually compared. The `dod_thunder2` caveat is
  pinned the same way, so it is a checked fact rather than prose — if that map is reviewed later the
  test says so instead of letting a stale warning stand.
- Version strings are still not compared. The site's `geometry_version` carries this scheme's
  prefix and a digest nothing in either repo computes, so it reads like a derived identity and is
  not one; re-measured against the fact set and seven serialization variants, none reproduces it.
  The test asserts the prefix and says why that is the limit.

The guard was shown to fail before it was trusted: perturbing a matrix element in the vendored
copy, perturbing an overview block in our own config, tampering with the reference without
refreshing the pin, emptying the fixture, and dropping a map from it each redden the suite, with
the tree verified back to green between them.
