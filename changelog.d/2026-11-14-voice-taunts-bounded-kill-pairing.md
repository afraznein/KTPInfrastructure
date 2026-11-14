### `scripts/voice_taunts.py`: kill pairing no longer re-reads each speaker's all-time frags per press (2026-11-14)

The nightly `ktp-voice-taunts` run went 390 s → 414 s → 463 s over 11-12..14 against a
`TimeoutStartSec` of 10 min. Its one query `LEFT JOIN`ed `hlstats_Events_Frags` per press on
`killerId` plus an `eventTime` range, and `killerId` is indexed alone, so every press read its
speaker's whole frag history (EXPLAIN: ~6,300 rows per press). Measured read-only on one-day
replays, the old query cost about 70 ms per press, which at the season's ~6,000 presses is the
observed runtime. Separately, the untagged-press branch let MySQL walk every `match_id IS NULL`
PlayerActions row (107k) once per voice action type instead of using the `actionId` index the
comment said it used.

- Presses are read on their own (`FORCE INDEX (actionId)` on the untagged branch), then **one**
  sequential pass reads the speakers' frags from the first press minus `LOOKBACK`
  (`IGNORE INDEX (killerId)`), and victim names come from one `hlstats_Players` lookup. Python
  pairs each press with its own kills in `[press - LOOKBACK, press]` and emits the same fan-out
  rows the `LEFT JOIN` did, so `nearest()` and everything after it is unchanged.
- Full season, measured read-only 2026-11-14: presses 5.2 s, frags 7.5 s (143,943 rows),
  names 0.1 s, pairing 1.4 s — about 14 s against 463 s. The frag pass is a table scan, so it
  grows with the table, not with presses times history.
- **Identical output on replay:** six match days (10-22, 10-23, 10-24, 10-26, 11-05, 11-14),
  old query vs new path as `ktp_ro`: fan-out row multisets equal, events, snapshot and rendered
  markdown sha256 equal on every day. (The old query was run with the `actionId` hint added so it
  fit the 10 s read cap; an index hint changes the plan, never the result.)
- Kill ties within one second are now ordered by frag id instead of whatever order the join
  returned; no replayed day had a tie that changed a victim.
