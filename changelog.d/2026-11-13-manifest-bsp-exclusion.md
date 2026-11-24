### `build-game-files-manifest.py`: `maps/*.bsp` is now actually excluded (2026-11-13)

The manifest has always listed `maps/*.bsp` under `excluded_buckets` -- a stated gap on
hashing cost, not a ruling that a BSP edit is harmless -- but no code enforced it. The
`.res` route accepts any listed `.bsp`, so a map whose resource list names itself put its
own world file in scope at severity `violation`. The installed manifest carries three such
entries, chosen by how each `.res` was written rather than by any decision, and a widely
shared build of one of those maps that differs from the server's copy has been scoring as
`modified_game_files`.

- `.bsp` joins `EXCLUDED_EXTENSIONS`, so it is dropped before hashing on the `.res` route.
- `tests/unit/test_bsp_file_exclusion.py`: fixture control, no `.bsp` entry in any case,
  never hashed, the map's own assets stay in scope. Three of its six tests fail with the
  fix reverted.
- Takes effect only when the manifest is regenerated and installed. The scope diff will
  list the `.bsp` paths as removed, and a `--gate-scope` run must count them in
  `--accept-removed` along with anything else that moved since the last build.
