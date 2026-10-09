### config: the dev profile's `ktp_maps.ini` now carries the fleet's bindings (2026-10-09)

- **`config/local/ktp_maps.ini` bound three maps to configs that exist in no repo.** `dod_lennon2_b1`,
  `dod_lennon_b2` and `dod_lennon_b3` named `ktp_lennon2_b1.cfg`, `ktp_lennon_b2.cfg` and
  `ktp_lennon_b3.cfg`. In the dev stack that exec is a silent no-op, so clan mode would never arm on
  those maps. The fleet was never affected: on 2026-10-09 all 24 instances carried one `ktp_maps.ini`
  (md5 `da411a1d0a6ac65b899d0636fa2b1e21`), byte-identical to `afraznein/KTPDoDServerConfig`'s, with no
  lennon2 sections.
  - Below its local-dev header, the file is now a copy of that one: 20 sections instead of 32. The
    fleet's copy is CRLF and this repo stores `config/local/ktp_maps.ini` as `eol=lf`, so the two
    match byte for byte only with CR stripped (`6dbf6b00e473d4727356c9bcc69ef051` both ways). The
    2026-09-15 decision to keep the extra entries is reversed, because the pool moved on (`dod_armory_b7`,
    `dod_saints2_b5e`, `dod_railroad2_s10a`) and the old names were what the spatial registry ranked.
  - `config/analytics/spatial_maps/registry.json` re-keys `dod_armory_b6` to `dod_armory_b7` and
    `dod_saints2_b3e` to `dod_saints2_b5e`. That has to land in the same change: the registry gate
    errors on an override naming a map with no binding, so either half alone turns it red.
  - New test: every `config =` in the dev profile has to name a file under `config/local/dod-configs/`.
    It fails on the previous file and names the three missing configs.
