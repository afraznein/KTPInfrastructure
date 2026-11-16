### `analytics`: anzio's spatial config follows its re-cut overview (2026-11-16)

The S10 overview pack re-cut `dod_anzio` to the worldspawn model's bounds (`ZOOM 1.01`,
`ORIGIN 402 -14`), but `config/analytics/spatial_maps/dod_anzio.json` still carried the camera
from before the re-cut (`1.11`, `307.06 372.72`). The site's matrix is generated from that block,
so it sat 116 px away from the picture the site now draws under the heatmaps, and the site
withheld the art rather than misplace it.

Re-checked against real positions rather than by restating the formula: 435,793 live-player
census samples from the 40 most recent anzio matches, projected onto the shipped BMP's
non-key pixels. The re-cut camera puts 100.00% of them on the art; the old camera 81.78%. The
same measure gives 100.00% on every map whose art already matched, and a 512-unit origin shift
drops each of them to 58–90%.

- `overview` in `dod_anzio.json` moves to the shipped camera; `geometry_version` becomes
  `goldsrc_spectator_v1-529c9d687b9b`.
- The vendored site table and `PIN.json` move to the upstream bytes that carry the new anzio
  matrix and `dod_lennon5_b1`'s re-cut matrix (still unconfigured here, still deferred).
- `registry.json`'s review flags for anzio are unchanged; the census measurement is recorded
  in `PIN.json`'s coverage note as what the new block rests on.
