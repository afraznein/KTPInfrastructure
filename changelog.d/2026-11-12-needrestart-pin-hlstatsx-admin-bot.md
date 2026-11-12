### `ops`: needrestart pin adds `hlstatsx.service` and `ktp-admin-bot.service` (2026-11-12)

An unattended `perl` upgrade at 06:07 ET on 2026-11-11 restarted both. The HLStatsX
daemon is one process ingesting logs for the whole fleet, so a restart mid-match loses
log lines. Per the operator's ruling, both are now deferred like the AC API, nginx and
the HLTV proxies.

- `ops/data-server/needrestart/conf.d/50-ktp-no-auto-restart.conf`: two more anchored
  `override_rc` entries.
- `tests/unit/test_needrestart_pin.py`: both are pinned; `hlstatsx-ingest-monitor` and
  `ktp-admin-bot-old` are neighbours that must still restart.
- `docs/runbooks/DATA_SERVER_CONFIG_TRAPS.md`: lists the two units and why.
- Not applied by this change; reinstall steps are in the PR.
