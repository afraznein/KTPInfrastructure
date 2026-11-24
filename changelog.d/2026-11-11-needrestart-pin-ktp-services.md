### `ops`, `docs`: data server pins `ktp-ac-api`, `nginx` and `hltv@*` out of needrestart's automatic restarts (2026-11-11)

Ubuntu's needrestart APT hook restarts any daemon mapping a replaced library, and on
2026-11-04 an unattended security upgrade bounced the AC API, nginx and every HLTV proxy
mid-morning. Per the operator's ruling, those units are now deferred: upgrades still land,
and the services are restarted by hand outside match time.

- `ops/data-server/needrestart/conf.d/50-ktp-no-auto-restart.conf` (new): three
  `override_rc` entries, added to the stock hash rather than replacing it.
- `docs/runbooks/DATA_SERVER_CONFIG_TRAPS.md`: why a timer/cron grep cannot find this
  restart path, and the list-mode check for what is pending.
- `tests/unit/test_needrestart_pin.py` (new): the pinned units match, prefix
  neighbours (`hltv-api`, `hltv-demo-renamer`) do not, and Perl evaluates the file the
  way needrestart does.
- Not applied by this change; install steps are in the PR.
