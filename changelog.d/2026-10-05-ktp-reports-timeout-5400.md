### `systemd`: `ktp-reports.service` start timeout raised to 5400 s (2026-10-05)

The data server already runs with `TimeoutStartSec=5400` through the drop-in
`/etc/systemd/system/ktp-reports.service.d/10-timeout.conf`; the repo unit still said 1800, so a
reinstall from the repo would have cut a full re-stamp off at 30 minutes. The unit now carries 5400,
and `tests/unit/test_reports_unit_timeout.py` holds it there. Once this unit is installed the
drop-in is redundant and can be removed.
