### `stats`: the spatial registry counts `human_matches` and refuses a typed one (2026-10-09)

`scripts/spatial_map_registry.py` used to read `human_matches` straight from
`config/analytics/spatial_maps/registry.json`. Nothing updated the field, so every map read 0
against a gate of 20, including the one reviewed reference map, while the fleet had played dozens
of matches on each.

- With `--database` (and optionally `--defaults-extra-file`, `--since YYYY-MM-DD`), the count is
  distinct match ids per map in `ktp_capture_manifests`. A bound map with no manifest is a counted
  0.
- Without `--database` the count is `null`, rendered as `—`, and no map can be
  `competitive_ready`. An unknown count no longer reads as a measured zero.
- A `human_matches` key anywhere in the registry JSON is now a validation error. The two typed
  zeros are removed.
- `docs/MATCH_REPORT_READINESS.md` § Cross-map readiness now says human_matches is derived, never
  hand-entered.
- Production read, 2026-10-09, `--since 2026-09-15`: anzio 73, harrington 70, lennon5_b1 60,
  saints2_b5e 40, armory_b7 27, thunder2 13.
