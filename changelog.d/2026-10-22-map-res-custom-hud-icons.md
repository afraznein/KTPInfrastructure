### `scripts`: a map's custom HUD icons reach its `.res`, and the sort matches RESGen (2026-10-22)

`dod_solitude2`'s two middle control points rendered blank flags for any client
that did not already have six sprites. The sprites were on all 24 instances, in
`/home/dod/distribute`, and on FastDL over both schemes with matching hashes.
They were missing from one place only: `dod_solitude2.res`, the list that tells a
client to fetch them. So the symptom was per-player rather than per-server, which
is why it read as one host having a problem.

RESGen is not blind to the entity keys you would reach for. It harvests any
entity *value* that looks like a path, which is why `point_reset_model`,
`point_*_capsound` and `area_hud_sprite` were already covered — a sweep of every
path-shaped value in both affected maps found nothing missing. A
`point_hud_icon_*` value is an **integer**, so there is no path in the BSP for it
to find. The files are reachable only through the index, and from the index only
by listing the directory.

`build_one` now parses the whole entity lump after RESGen runs, and where any
`point_hud_icon_*` is at or above 18 it adds that map's own
`sprites/obj_icons/<map>/` files, drops anything the DoD client already ships
(`scripts/data/dod-depot31-stock-paths.txt`), merges case-insensitively and
re-emits the `// .res entries (N):` count. `read_worldspawn` stops at the first
entity by design, so this needed a separate full-lump reader rather than a tweak
to it.

⛔ The filenames are **listed, never computed from the index.** The obvious
arithmetic reproduces `dod_solitude2` and `dod_saints` exactly and then fails on
`dod_falaise`, with no slot for the `_brit` variants `dod_zalec` ships or
`dod_flugplatz`'s `icon_obj_custom2_alliesusgreen.spr`. The authoritative
index-to-filename table lives in the client.

A map that uses custom indices with no non-stock file beside it is now a
**problem**, naming the directory it searched, rather than a quietly short list —
silence there is what shipped the blank flags.

`dod_saints` is in the same position and needs nothing: it is a stock map and all
nine of its icons are in the depot manifest, so the stock filter declines them.
A test pins that against the manifest rather than leaving it as a remark.

Also fixed, found on the way: `check_res` asserted ascending order
case-**sensitively** while RESGen sorts case-insensitively, so the fleet's own
`dod_saints.res` failed the project's own self-check on
`sound/ambience/Opera.wav` — as would any map with a mixed-case asset.
