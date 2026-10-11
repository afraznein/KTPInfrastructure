### Changed

- `docs/LIVE_SCRIPT_INVENTORY.md` — re-pinned the `ktp-hltv-liveness.sh` and
  `ktp-data-server-health.sh` rows from a read on the data server, rather than
  re-dating them. Each row's live `md5sum` equals the blob at its new pin, and
  `check-live-script-inventory.py --live-md5` verifies both live claims. The
  health row also drops `UNVERIFIABLE-PIN`: it was pinned to a commit reachable
  from no ref, so nobody who cloned this repo could check it at all.
  A note records the trap that made it worth doing — a mute row was cited as the
  live revision in one direction and, later, as proof that nothing had been
  installed in the other, while the host's own `ktp-install --report` had the
  answer the whole time.
- The liveness row closes outright. The health row keeps **SUPERSEDED**, because
  `ce8989a312` touched that path about seven hours after the read, so the repo now
  sits ahead of the box — the pin is right about what is installed and the token is
  right about the gap. The note now separates the two tokens: `UNVERIFIABLE-PIN` is a
  defect in the row and a host read closes it for good, while `SUPERSEDED` is a claim
  about the box that only an install clears.
