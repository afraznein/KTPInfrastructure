# Run 4, replayed with migrate_009 applied — first fixture with real flag captures

Same source log as `regression-2026-08-13-run4-position5s/game.log.gz` (the
real 16-bot Lane B match validating the 5s position-broadcast interval),
replayed deterministically through the daemon a second time
(`scripts/replay_and_dump.py`) after `migrate_009_flag_captures.sql` and its
`doEvent_KTPFlagCapture` handler landed, seeded this time.

Same reason the original run wasn't just re-dumped in place: the daemon code
changed after the original run finished, so getting `ktp_flag_captures` rows
means re-feeding the same log through the new code, not re-querying the old
DB (which never had the table). Deterministic replay is exactly what it's
for — no bots, no dice-rolling, same log in, same rows out.

`hlstatsx-fixture.sql.gz`: full schema + data dump, 3594 INSERTs (up from the
original match-1 fixture's 1731 — now also carries `ktp_damage_events`,
`ktp_position_samples`, and `ktp_flag_captures`, none of which existed when
that one was taken). 38 `ktp_flag_captures` rows — same count validated
against the raw log when `migrate_009` was built (38/38, zero loss).

Used to validate `scripts/composite_v2.py`'s move from raw-log regex parsing
to querying `ktp_flag_captures` directly:

```
=== capture events by half/team ===
  half 0: {'Allies': 1}  winner=Allies
  half 1: {'Allies': 8, 'Axis': 9}  winner=Axis
=== flag weights (inverse frequency, mean=1.0 across CONTESTED flags only) ===
  POINT_ANZIO_PLAZA: captured 10x -> weight 0.9
  POINT_BRIDGE: captured 8x -> weight 1.125
```

Half 0's stray Allies capture is a pre-match warmup capture — correctly
tagged `half=0`/`match_id NULL` by the daemon's own round-live gating, not a
parsing artifact. Per-player `flag_caps` counts in the score table (Samus 5,
Denton 2, Cloud 5, etc.) match real per-player participation in the 18
capture completions in the raw log — 16 with two simultaneous cappers, 2
with three (zero solo captures in this particular run; whether any of
`dod_anzio`'s 5 points allow a solo cap isn't something this one match's
data can answer).
