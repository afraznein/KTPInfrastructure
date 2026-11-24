# Overview descriptor corrections

`docs/OVERVIEW_CORPUS_AUDIT.md` measured, for every complete overview triple, the transform a
correct render must go through to land on the shipped `.bmp`. That transform **is** the
misplacement: a player dot drawn through the descriptor lands that far from where the picture
says the player is.

This is the other half — moving the descriptor onto the picture. Seven descriptors are
corrected here; three candidates from the audit's table are **declined**, with the measurement
that rejects them. Everything below was measured on the **fleet's** copies, pulled from Dallas
`dod-27015` on 2026-09-15, and every `.txt` and `.bmp` involved is byte-identical across all 24
instances (one md5 per file, 240 map-instance rows covering the `.txt` and the `.bmp`, no drift).

⛔ **Nothing here has been deployed.** The corrected files are in `config/overviews/`; the
deploy is § Runbook and is the operator's.

## Why the descriptor and not the image

The `.bmp` is what players have read for seasons and re-cutting one needs the renderer. The
`.txt` is four numbers. Where the picture is geometrically sound and only mis-declared — which
is every map below — editing the text is the whole fix, and it is reversible by editing it back.

The exception is a map whose *image* is wrong. `para_glider` and `para_hedgerow` are that case
and are not fixed here; see § Declined.

## The derivation

`scripts/correct_overview_descriptor.py` does this, and `tests/unit/test_correct_overview_descriptor.py`
holds it to it on both ROTATED branches. The audit's transform takes the render to the shipped
image about the image centre `C`:

    target = C + scale*(src - C) + (dx, dy)

and the projection is (scale `s = zoom/8`, one overview pixel is `8/zoom` world units):

    ROTATED 0   px = W/2 - s*(world_y - origin_y)   py = H/2 - s*(world_x - origin_x)
    ROTATED 1   px = W/2 + s*(world_x - origin_x)   py = H/2 - s*(world_y - origin_y)

Matching coefficients gives `zoom' = scale * zoom` and an origin moved by `d/s'` **world**
units:

    ROTATED 0   origin_x' = origin_x + dy/s'   origin_y' = origin_y + dx/s'
    ROTATED 1   origin_x' = origin_x - dx/s'   origin_y' = origin_y + dy/s'

⚠️ **A pixel `dx` is not a world x.** The axes are swapped and negated against world x/y, and
which one a pixel axis carries flips with ROTATED. Reading `dx` onto `origin_x` produces a file
that looks corrected and is wrong on both axes. All seven maps here are ROTATED 0, so the
rotated branch is exercised by the unit test rather than by an asset.

`ORIGIN`'s third component is the overview camera's pivot height and never reaches the
projection, so it is left exactly where its author put it.

## What ships

`baseline` is the IoU as the engine lays them today. `predicted` is what the audit's search
said the transform reaches. `achieved` is a **re-render through the written file**, scored
against the shipped image with no transform at all — the number a reader can reproduce from
`config/overviews/`.

| map | ZOOM | ORIGIN x, y | baseline | predicted | achieved | anchors on drawn pixels |
|---|---|---|---|---|---|---|
| `dod_anzio2_test3` | 1.03 → **0.77** | 404, −76 → **393.61, −86.39** | 0.391 | 0.948 | **0.929** | 29/50 → **50/50** |
| `dod_anzio_test4d` | 1.03 → **0.77** | 404, −76 → **393.61, −86.39** | 0.361 | 0.785 | **0.761** | 29/50 → **50/50** |
| `dod_anzio3_b1` | 1.03 → **0.77** | 404, −76 → **393.61, −86.39** | 0.362 | 0.784 | **0.760** | 29/51 → **51/51** |
| `dod_schwetz` | 0.99 → **1.04** | −608, −76 → **−615.69, −83.69** | 0.882 | 0.990 | **0.980** | 98/100 → **100/100** |
| `dod_railroad2_s9a` | 1.30 (unchanged) | 136, −337.31 → **136.00, −189.62** | 0.671 | 0.765 | **0.767** | 34/39 → **39/39** |
| `dod_rr2_test` | 1.30 (unchanged) | −8, 2 → **133.54, −188.77** | 0.589 | 0.769 | **0.765** | 32/39 → **39/39** |
| `dod_aleutian2_test3` | 1.33 → **1.32** | 738, 24 → **731.94, 17.94** | 0.892 | 0.935 | **0.923** | 31/33 → **32/33** |

`achieved` sits a little under `predicted` on the scaled maps because the search's prediction is
a nearest-neighbour resample of the render and the shipped value is a real render at a
two-decimal zoom. Every one of the 72 descriptors the fleet ships carries exactly two decimals;
the third digit is worth under 0.01 IoU on every map here (`dod_anzio2_test3` peaks at zoom
0.765 with 0.937 against 0.929 at 0.77, and the anchor test cannot tell them apart).

**`dod_rr2_test` and `dod_railroad2_s9a` are the same picture** (`689528e8…`) under two
descriptors that disagreed by 144 units in x and 339 in y. The audit read that as "neither
matches it, so the image belongs to a third revision". Corrected independently, from their own
BSPs, they land on **(133.54, −188.77)** and **(136.00, −189.62)** — 2.5 and 0.9 units apart on
a map 4000 units across. Two independent solutions converging on one origin is the strongest
single piece of evidence in this document.

## How each correction was checked

The IoU search is one measurement and it can be fooled, so each correction had to survive two
others that are not derived from it.

**1. Per-axis footprint extents.** If a picture is genuinely drawn at `k` times its declared
zoom, the bounding box of its opaque footprint is `k` times the render's **on both axes**. A
wanted scale that does not show up in the extents is the search trading scale against offset
along a ridge.

**2. Entity anchors on drawn pixels.** Spawns, capture points and objectives stand on the map.
Project them through a descriptor onto the shipped image: a descriptor that describes that
picture puts them on drawn pixels, a wrong one puts them on the transparent key. This tests
*content*, which a silhouette IoU cannot — the audit's own limits section says the comparison
"is blind to anything drawn inside a filled region", and this is what sees inside it.

⚠️ **The anchor rate is only evidence next to the image's drawn fraction.** On a mostly-painted
image everything scores high. Measured against a deliberately-wrong control (the same
descriptor shifted 100 px):

| map | drawn fraction | shipped | shifted 100 px | zoom ×1.3 |
|---|---|---|---|---|
| `dod_anzio2_test3` | 0.201 | 0.580 | 0.400 | 0.100 |
| `dod_aleutian2_test3` | 0.290 | 0.939 | 0.242 | 0.182 |
| `dod_rr2_test` | 0.439 | 0.821 | 0.538 | 0.308 |
| `dod_schwetz` | 0.511 | 0.980 | 0.640 | 0.430 |
| `para_hedgerow` | 0.510 | **1.000** | 0.560 | 0.700 |
| `dod_overlord` | 0.742 | **1.000** | **0.951** | 0.815 |
| `dod_dog1` | 0.770 | **1.000** | 0.787 | 0.613 |

On `dod_overlord` a descriptor wrong by 100 px still scores 0.951, so the test is nearly blind
there and a high rate proves little — but a rate that *falls* still means something.

**3. The ceiling-cut control.** `render_overview_bmp.py` cuts geometry above the highest
floor-anchored entity plus headroom, and a cut that removes peripheral geometry shrinks the
render's footprint and makes the search ask for a scale it otherwise would not. Re-measured
with `no_cut=True`, **all ten transforms reproduce** — same scale to 0.005, same offsets within
one pixel. The cut is not manufacturing any of these.

## The anzio decision

`dod_anzio2_test3.bmp`, `dod_anzio3_b1.bmp` and `dod_anzio_test4d.bmp` are byte-identical
(`d1b852ea…`), all three declare zoom 1.03 from origin (404, −76), and the picture is drawn at
0.745 of that. At the correction the image reaches **0.929** on `anzio2_test3` and only ~0.76 on
its two siblings, so the picture is geometrically right for `anzio2_test3` and approximate for
the others.

**The trade-off the audit anticipated does not exist.** Sweeping zoom per map, all three peak
at the same value and all three hold a 100% anchor rate across 0.76–0.775:

| zoom | `anzio2_test3` | `anzio_test4d` | `anzio3_b1` |
|---|---|---|---|
| 0.760 | 0.916 | 0.752 | 0.752 |
| 0.765 | **0.937** | **0.763** | **0.762** |
| 0.770 | 0.929 | 0.761 | 0.760 |
| 0.780 | 0.891 | 0.733 | 0.734 |

There is nothing to trade between the three maps: one descriptor is simultaneously optimal for
all of them. The residual on the siblings is **their own geometry**, not the projection — their
BSPs are later revisions than the one the picture was cut from, and the footprint extents say
so directly (`anzio2_test3` matches the wanted 0.745 on both axes, 0.744 and 0.747; the two
siblings match on the wide axis, 0.744, and disagree on the other, 0.595).

➡️ **So all three get the same corrected descriptor, and the anchor test says that is enough**:
every spawn and capture point on all three maps lands on drawn map, where a third of them did
not before. Re-cutting a picture per revision would raise the two siblings' IoU and would not
move a single dot that this does not already move. It needs the renderer and it is not worth it.

## Declined

The audit flagged `dod_overlord` (scale 1.18) and `dod_dog1` (1.34) as **candidates, not
conclusions** — "a big scale with a modest gain can also be a search finding a broad, flat
optimum rather than a real defect". Re-measured, that is exactly what they are, and
`para_hedgerow` fails a different way.

| map | wanted | extent ratio, wide axis | extent ratio, other axis | anchors shipped → corrected |
|---|---|---|---|---|
| `dod_overlord` | scale 1.175, dx +67, dy −12 | 1.170 | **1.007** | 81/81 → **72/81** |
| `dod_dog1` | scale 1.34, dx −9, dy +3 | 1.323 | **1.013** | 155/155 → **91/155** |
| `para_hedgerow` | scale 1.065, dx −11 | 1.017 | 1.000 | 50/50 → **49/50** |

**`dod_overlord` and `dod_dog1` want a scale on one axis only.** A zoom change scales both; a
16% and a 31% disagreement between the axes is not a zoom. The correction derived from it
*removes* anchors from drawn map — `dod_dog1` drops to 0.587, worse than the deliberately-wrong
100-px-shifted control at 0.787. The scale profiles agree: both are plateaus, not peaks
(`dog1` moves 0.005 IoU across 1.30–1.375, and its best offset jumps from dx +45 to dx −32
between scale 1.200 and 1.225 — the search switching branch, which is what a ridge looks like).
For contrast, `dod_schwetz`, which is corrected, peaks sharply: 0.894 at 1.000, **0.981** at
1.050, 0.930 at 1.075.

**`para_hedgerow` is the renderer over-painting, and its descriptor is already right.** Its
footprint extents match to within 1.7% on both axes while the *area* ratio is 1.263 — we paint
much more of the open terrain than the picture does, which is the `para_glider` gap the audit
describes, on a map where the anchor test is discriminating (a 100-px shift costs 0.44) and the
shipped descriptor scores a clean 50/50. Nothing is misplaced; there is no descriptor edit that
helps.

## Two things found while measuring

**⚠️ Four descriptors name an image that is not their own file.** The `.bmp` filename is a
convention; the engine loads the path in the layer block's `IMAGE`. On all 24 instances:

| descriptor | draws | exists |
|---|---|---|
| `dod_rr2_test` | `overviews/dod_railroad2_test.bmp` | yes — and byte-identical to `dod_rr2_test.bmp` |
| `dod_anzio2_test` | `overviews/dod_anzio.bmp` | yes |
| `dod_anzio2_test1i` | `overviews/dod_anzio.bmp` | yes |
| `dod_lennon4` | `overviews/dod_lennon2.bmp` | yes |

None is broken today and `dod_rr2_test`'s alias happens to resolve to the same bytes the audit
scored, so its result stands. ⛔ **But an audit that reads `<map>.bmp` is not reading what the
engine loads**, and a future corpus pass should follow `IMAGE` rather than the stem.

**⚠️ Chicago carries 71 overview descriptors where the other four hosts carry 72.** Counted
per instance across all 24; the four Chicago instances agree with each other. Not chased here.

## Runbook — deploying these

⛔ **Nothing below has been run.** Every hazard in it was measured today.

### The correction has to land in two places, and they are not connected

| copy | path | who reads it |
|---|---|---|
| game instances | `~/dod-<port>/serverfiles/dod/overviews/<map>.txt` on all 24 | fed from `distribute/`; the server itself does not draw the overview |
| FastDL | `/var/www/fastdl/dod/overviews/<map>.txt` on the data server | **the client**, which is what actually changes what a player sees |

Both currently hold the same bytes (verified by md5 for all seven maps). **Nothing syncs one to
the other** — the only unit touching `/home/dod/distribute` is `ktp-file-distributor.service`,
which pushes to the game hosts, and the only cron mentioning it is
`/etc/cron.d/ktp-fastdl-prune-configs`. Updating the game hosts alone changes nothing a player
sees.

### Hazards on `/home/dod/distribute/`

- ⛔ **It is a live deploy path.** `ktp-file-distributor.service` pushes any created or changed
  file to all 24 instances (~25 s for one small file, longer for a map batch), and **syncs deletions** — a `rm` there removes the file
  from 24 hosts. Edit outside the tree and copy in (`cat new > file`, never `rm`/`mv`), and keep
  backups somewhere else entirely.
- ⚠️ **It pushes on change and never back-fills.** A file that is not in `distribute/` is simply
  never pushed; Atlanta once sat 123 files behind for exactly this reason. **`distribute/` is not
  a mirror of the fleet**: it carries 138 overview files, and `dod_anzio_test4d` and
  `dod_anzio3_b1` are *not among them* although both are present on all 24 instances and on
  FastDL. Copying those two in creates new files there, which is a deploy, not a repair.
- ⚠️ No restart is needed and none should be taken. Overview files are read by the client at map
  load; the running server does not cache them.

### FastDL

Upload to `/var/www/fastdl/dod/overviews/<map>.txt` — the engine prepends `dod/` to every
request, so a file one level up exists on disk and 404s for clients. Verify with
`curl -sI https://fastdl.ktpdod.com/dod/overviews/<map>.txt` and check the body, not just the
code.

⚠️ **A client that already has the file will not re-download it.** GoldSrc skips a resource it
already has on disk, and there is no hash check on a `.txt`, so the correction reaches new
clients and anyone who clears their `dod/overviews/`. This is stated from engine behaviour and
**was not measured here** — no client was tested.

⚠️ **Two of the seven cannot reach a client at all yet.** `dod_schwetz` has no `.res` file, and
`dod_rr2_test.res` (generated as `dod_railroad2_test.res` by RESGen) lists no overview lines.
Across the fleet, 78 maps have 47 `.res` files of which 35 list an overview. Those two need the
map-bundle/resgen lane before a corrected descriptor is worth uploading for them.

### Verifying

- **Per instance, across all 24** — one host is not the fleet. The sweep that established the
  current state walked `~/dod-*/serverfiles/dod` on all five game hosts and counted 24
  instances and 240 map-instance rows before comparing md5s.
- Compare **md5**, not mtime or size: two of these corrections change the file length and one
  (`dod_railroad2_s9a`) leaves ZOOM untouched.
- Re-run the corpus audit against a corrected instance. `dod_railroad2_s9a` should move to
  `agrees`-adjacent at the identity transform; the two anzio siblings will stay under the 0.85
  floor and bucket `renderer-gap`, which for them is correct and expected.

### Rollback

The pre-change bytes are the md5s below; the originals are recoverable from any instance that
has not been updated yet, and from `/var/www/fastdl/dod/overviews/`.

| map | descriptor md5 before |
|---|---|
| `dod_aleutian2_test3` | `5b7d59a8d972e3b48349878dc42a29b0` |
| `dod_anzio2_test3` | `46d2417a4a76372b009ff09e01680cc8` |
| `dod_anzio3_b1` | `f511ba3e9176a04700846d5bd24500c0` |
| `dod_anzio_test4d` | `5ce98eb43013bdfc34fcb7c68cf1b5a5` |
| `dod_railroad2_s9a` | `938d8b33e052356e75f3bbdb93fdaa76` |
| `dod_rr2_test` | `56b623df88ad3950357e24a064291f25` |
| `dod_schwetz` | `e8a930d8afe850edea843e826dc63b95` |

## Limits

- **Five of the seven files are CRLF** as their mappers wrote them, and two end without a
  trailing newline. The rewriter edits only the ZOOM value and ORIGIN's first two numbers and
  leaves every other byte alone; `config/overviews/*.txt` is marked `-text` in `.gitattributes`
  because `core.autocrlf=input` would otherwise rewrite them on commit.
- **`dod_aleutian2_test3` keeps a header comment reading `Zoom 1.31`** while the file now
  declares 1.32. The comment was already inconsistent — it sat above a ZOOM of 1.33 — and it is
  left as the author's provenance. The measured optimum is 1.315–1.32 (IoU 0.9245 and 0.9231
  against 0.9177 at 1.31), so the comment corroborates the direction without naming the best
  value.
- **`dod_aleutian2_test3` is the weakest correction here.** +0.031 IoU and one anchor of 33, and
  its extent ratios (0.979 and 0.948) bracket the wanted 0.99 rather than agreeing with it. Its
  scale profile is a sharp peak and all three signals point the same way, which is why it ships,
  but it is the one a reviewer should argue with.
- **No rotation was searched**, here or in the audit. A wrongly-set ROTATED would read as a very
  low IoU that no transform improves. None of these look like that.
- None of the seven maps has a `config/analytics/spatial_maps/<map>.json`, so no spatial config
  needs rebuilding. If one is built later it must come from the corrected descriptor — that
  pipeline pins `overview_txt_sha256`, and these corrections change it.
