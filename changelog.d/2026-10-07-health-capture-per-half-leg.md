### `monitoring`: a single lost match-half now fires on its own (2026-10-07)

`capture-loss:<event_type>` sums a flat trailing 24 hours and warns at 5%. On 2026-10-07 a
match-half had **100% of eleven event types rejected** and that headline stayed under the
threshold, because a dead half divided by a day of healthy traffic is a rounding error. The
alert existed, ran hourly, and said nothing. Two legs added **beside** it, not in place of it
— the average still answers *is the daemon healthy*, the new legs answer *did any half not
happen*:

- **`capture-half-loss`** — every `(half, event_type)` in `ktp_capture_health` over the
  window is scored, and the worst one is reported. Scored per half **and** per event type:
  aggregating the eleven types inside a half would re-commit the same dilution one level
  down, since `position` outnumbers `frag` about twenty to one.
- Loss is **`emitted - daemon_accepted`**, not `rejected / received`. The ratio the average
  uses is blind to the worst case available: a half whose stream was lost in transit has
  `daemon_received` 0, so `rejected/received` is 0/0 and the row is discarded by the floor
  instead of paging. `emitted` is the producer's own count in the same row, so a half that
  arrived as nothing scores 100%.
- **`capture-half-unreconciled`** — halves whose `ktp_capture_manifests` row arrived and
  whose health rows never did, after a settling grace so a half still being played is not an
  alert. No rate test can see this; a missing row is not a 100% rate, and health rows travel
  the same one-way UDP path as the events they account for.
- **One constant alert key each**, with the offending half in the alert body. A key carrying
  the half's identity would age out of the trailing window and the set comparison would
  announce a recovery for a half that never recovered — the same bug as the bucketed
  `disk-growth` keys.
- `tests/unit/test_health_capture_half.py` runs both reducers and the real latch with no
  database. The headline test puts one dead half among forty healthy ones and asserts that
  the sibling's 24h reducer reads 3% on the same events while this leg reads 100%.

⚠️ **`CAPTURE_HALF_LOSS_WARN_PCT=50` / `CLEAR=25` are PROVISIONAL.** They are bracketed, not
measured: KTPHLStatsX migration 035 measured ~0.1% transit loss per stream and the 10-07 half
measured 100%, so 50 is provably above known-normal and below the known fault — but the band
between them has never been looked at, and a per-half rate is a different distribution from a
24-hour average, so the sibling's 5% is evidence for nothing here. The query that reads the
real top of the distribution sits at the constant. `test_the_shipped_threshold_can_actually_fire`
goes red if anyone pushes the default out of reach, because **an alert threshold above
everything ever observed is an alert that cannot fire**, and one has already shipped on this box.

⚠️ **Known false positive on `capture-half-unreconciled`**: an abandoned half (map change
mid-half, `.forcereset`, crash) never sends health either. Raise `CAPTURE_HALF_UNRECONCILED_WARN`
if that proves common; do not drop the leg — a watcher that can go blind has to say so.

⛔ **Merging this does not field it.** `ktp-data-server-health.sh` is installed at
`/usr/local/bin/`, no workflow in this repo deploys `scripts/`, and `docs/LIVE_SCRIPT_INVENTORY.md`
pins the live copy to `cf93488405` (2026-08-30). The check starts working when someone installs it.
