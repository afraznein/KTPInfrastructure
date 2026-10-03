### `scripts`: the data-server health check watches the AC weapon-context store (2026-10-01)

The AC API began persisting weapon-timeline sidecars to
`/opt/ktp-ac-api/weapon-context` on 2026-10-01. For any session whose database rows
have been swept, that directory holds the only copy, and its hit records carry
victim SteamIDs. Nothing watched it.

`ktp-data-server-health.sh` now reports, as fixed-token down items:

- `weapon-context-store=absent`: the root is missing.
- `weapon-context-store=too-open`: the root has any mode bit outside `0750`.
- `weapon-context-store=not-root-owned`: the root is not owned by root.
- `weapon-context-store=stale-tmp`: a file in `tmp/` is older than an hour, meaning a
  write died between its write and its rename.
- `weapon-context-store=stale` / `never-written`: session bundles kept arriving
  after the newest sidecar (or after the store was created) and none followed.
  This needs both at least 7 days since that point and at least 20 bundles older
  than a 2h recompute grace. A quiet week or an off-season uploads nothing, so it
  can never fire on age alone.
- `weapon-context-store=unmeasurable`: the uploads directory is missing, so the
  freshness leg has no input. That is reported rather than read as healthy.

Thresholds are env-overridable (`WEAPON_CONTEXT_*`). Tested in
`tests/unit/test_health_weapon_context.py` against the shipped block, extracted by
marker.
