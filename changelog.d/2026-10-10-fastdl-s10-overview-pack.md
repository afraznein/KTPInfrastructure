### `scripts`: one archive of the current pool's command-map overviews (2026-10-10)

`ktp-fastdl-indexes.py` now publishes `overviews/ktp-s10-overviews.zip` beside the assets it
packs, and lists it with the per-map pair on the `/dod` page. The overviews have been served
over HTTPS the whole time; what was missing is that a player had to fetch a `.txt` and a `.bmp`
per map and then work out where they go, which is the step that loses people. Unzip into
`dod\overviews\` and the pool is covered, with nothing to rename.

- **The ini is the spec, read at build time.** The pool comes from the seasonal block of
  `/home/dod/distribute/addons/ktpamx/configs/ktp_maps.ini` -- the fleet's own copy, which the
  distributor sends to all 24 instances -- and the block is found by its `MAPS` heading rather
  than by any list of map names. **Three S10 stems were re-cut mid-season** (`dod_saints2_b3e`
  became `_b5e`, `dod_armory_b6` became `_b7`, `dod_railroad2_s9a` became `_s10a`), so an
  archive assembled from a pool written down anywhere else ships names no BSP carries and the
  player gets a blank overview rather than an error. The re-cut case is a test: both stems sit
  on disk and only the one the ini names may ship.
- ⛔ **Not a listing of the whole docroot.** The overview directory carries more `.txt` than
  `.bmp` -- every unpaired stem measured is a test or beta name -- so a page or an archive built
  from "everything present" renders entries that cannot work, and carries stems nobody asked for.
  Pool-only avoids both.
- **Both halves or neither.** A stem missing either file is not shippable, and a partial archive
  is worse than none: the page promises every pool map, so the gap surfaces in game on the one
  map the player was about to play. An incomplete pool leaves whatever is already published
  alone rather than replacing it -- the site links this URL, and turning a stale pack into a 404
  is the worse of the two failures.
- **Byte-deterministic**, so "rewrite only when it changed" is a comparison rather than a claim:
  members carry their source mtime, never the build clock. The job runs hourly; stamping now()
  would hand every visitor a fresh download of identical assets and churn the mtime that makes
  a conditional request a 304.

Tests: `tests/unit/test_fastdl_overview_pack.py` builds its own docroot and ini, and covers the
re-cut stem, the off-pool control, flat member names (the "without renaming anything"
criterion), byte-stability across two runs, a half-missing pair, an incomplete pool over a
published archive, a missing seasonal heading and a missing ini.
