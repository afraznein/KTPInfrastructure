### `lane-b`: the image carries `dod_thunder2`, so the door-hold scenario can run (2026-11-18)

The door-hold scenario (`tests/e2e_stats/door_hold_scenario.py`) changes to
`dod_thunder2` and reports `not_exercised` when the map is missing. It is not a stock
map, so steamcmd never installed it and the scenario could not run anywhere.

- `build/lane-b/Dockerfile` installs `maps/dod_thunder2.bsp` from FastDL
  (`https://fastdl.ktpdod.com/dod/`), each file pinned by sha256. A mismatch fails the
  build. The bsp's md5 is `68d6c078e63d7c32e75cc3de1ca5793f`, the build the scenario
  checks for. It matches the fleet copy on every instance read and the workstation
  copy.
- It also installs `models/mapmodels/flo_tree.mdl` and `models/mapmodels/m3_parkbench.mdl`.
  The server precaches every `env_model`, and a model missing at precache stops the
  changelevel. These two are the map's only server-side references absent from
  `scripts/data/dod-depot31-stock-paths.txt`. Its sounds, sprites, sky and overview are
  stock or client-only, and both models are self-contained (textures embedded, one
  sequence group).
- If the base image already has one of these files, the build checks it against the pin
  and refuses to overwrite it when it differs.
- `lane-b-stats-e2e.yml` now caches these files with the two archives. The list is read
  from the Dockerfile's `install_pinned` lines, so adding a file there caches it, and the
  cache key covers every pin. The key format changed, so the first run in each calling
  repo is a cache miss and fetches all five files once.

No image publish is involved. The Lane B image is built in each run from
`build/lane-b/Dockerfile` on top of `ktp-runtime-test-base`, so the map arrives as
soon as a run uses a ref that carries this change.

⚠️ **Verified with unit tests that run the install layer and both workflow steps
under a shell with a fake `curl`, and with six mutations, not with an image build.**
This workstation has no Docker. The first real build is this change's own
`corpus / Lane B` run, which should take the cache-miss path.
