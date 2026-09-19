### `monitoring`: the spike thresholds' rationale comments no longer cite counts that have since moved (2026-09-18)

No threshold changed. `SPIKE_MIN_COUNT` and `SPIKE_ABS_CEILING` each justified their value against a
dated count in a comment, and S10's first official match night superseded both: re-derived read-only
from `ktp_spike_daily`, the worst whole-fleet day is now 14 (2026-09-13, was 13 on 2026-07-12) and the
worst per-host day is 4 (2026-09-13, nyc:27016, was 3) — so `SPIKE_MIN_COUNT`'s *"no single host
exceeded 3"* and `SPIKE_ABS_CEILING`'s *">16x the worst observed host-day (3)"* were both false, and
the floors' stated headroom read larger than it is.

Both comments now state the property and name the table to re-derive from, rather than carrying a
number no test holds true. The values 10 and 50 are unchanged and still correct: `SPIKE_ABS_CEILING`
has never fired, and 50 remains an order of magnitude above any observed host-day.
