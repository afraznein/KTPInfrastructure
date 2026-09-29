### Interrupted captures: the flag someone was taking, and who stopped them (2026-09-28)

`shadow_explorations.interruptions` (schema 22 -> 23, private) records captures
that were begun and stopped: a player stood on a flag, got most of the way, and
someone killed them off it. No capture, no objective points, no ownership
change — invisible in the box score and in the flag log alike, which is the
shape of value this workstream exists to find. 231 of them in S10 officials.

**Measured before built.** Asked forward from the event, the way a preventive
class must be — P(the capturing side caps out within 120 s) against that side's
chance at a random moment in the same half:

| interruptions | n | lift |
|---|---|---|
| all | 231 | 0.91 |
| peak ≥ 25% | 45 | 0.64 |
| peak ≥ 50% | 22 | 0.38 |
| peak ≥ 75% | 10 | 0.00 |
| peak < 25% *(control)* | 186 | 0.99 |

The further a capture had progressed, the more stopping it suppresses the
cap-out, and interruptions of captures that barely started sit exactly at
chance. Dose response with a flat control is why this class was built and why
the excursion class was not: fifteen tightenings of that one never beat chance.

**It reports evidence and never a price.** The top bands rest on n=22 and n=10,
so the trend carries the claim and no band is significant alone. A row names
its measured band and carries `measured_lift` with `measured_n` beside it; what
a band is worth is for the ledger in `infra-mmr-ratings`, once more weeks land.

Credit goes to defenders who killed a capturing-side player within 4 s of the
stop — several can share one, and a stop nobody is credited for is still
recorded rather than dropped, because the capper may simply have walked off.
Sides come from the per-half life feed, not the roster, so a half-time leaver
is not credited to the wrong team.

`objective_attempt_timeline_fact.sql` now selects `progress`, `peak_progress`
and `timetocap`; the stream was already plumbed but the column the whole class
turns on was not being read.
