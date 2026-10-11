### Changed

- `docs/LIVE_SCRIPT_INVENTORY.md` — re-pinned the `ktp-hltv-liveness.sh` and
  `ktp-data-server-health.sh` rows from a read on the data server, closing both
  rather than re-dating them. Each row's live `md5sum` equals the blob at its new
  pin, which is also the tip of that path on `main`, and
  `check-live-script-inventory.py --live-md5` verifies both live claims. The
  health row also drops `UNVERIFIABLE-PIN`: it was pinned to a commit reachable
  from no ref, so nobody who cloned this repo could check it at all.
  A note records the trap that made it worth doing — a mute row was cited as the
  live revision in one direction and, later, as proof that nothing had been
  installed in the other, while the host's own `ktp-install --report` had the
  answer the whole time.
