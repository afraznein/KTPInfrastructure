### `sql` / `tests`: the epoch-zero and orphan definitions reach all five producer streams, and the detection is now tested (2026-10-09)

`sql/integrity/position_corpus_integrity.sql` (merged 2026-10-08) pins one re-runnable
definition per defect over `ktp_position_samples`, and closes by naming four streams that
carry the identical `int($event_epoch // 0)` expression and saying it does not measure them.
Nothing else measured them either. Both definitions are per-table with no cross-table part,
so extending them is a copy rather than a new design.

- **`sql/integrity/producer_clock_corpus_integrity.sql`** reports the same two defects, the
  same way — counts and watermarks, no percentage, a one-year floor rather than an equality —
  over `ktp_position_samples`, `ktp_shot_events`, `ktp_move_census`, `ktp_aim_vis` and
  `ktp_flag_state_events`, one row per stream so the five are comparable in one reading. It
  keeps the position file's preflight discipline: a missing column and an invisible
  `ktp_matches` each halt on a sentinel instead of returning a confident wrong number, and the
  missing-column list is printed on a clean run as well as a dirty one. Each stream has its own
  `@since_*` watermark, because each has its own id space.
- **The writers are not symmetric, and one of them is still open.** Measured on `KTPHLStatsX`
  `origin/main` at `11f608c5`: four of the five handlers are gated airtight by construction —
  `ktpCaptureContextKey` refuses a matchid outside
  `/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/`, so a handler that reached its manifest check holds an
  explicit producer matchid, which makes `ktpHasExplicitProducerContext` true, runs
  `ktpResolveValidatedProducerEventContext` and **returns** on a clock error, and
  `ktpValidateProducerEventClock` refuses zero. The legacy `elsif` under each of those four is
  unreachable. `doEvent_KTPFlagState` has **no manifest gate of any kind** — `flag_state` is not
  in `ktpCaptureManifestAuthorizes`' permitted event-type list and the dispatch site carries no
  authorisation call — and on a clock error it warns and **falls through** to the receipt-time
  `$g_ktpMatchContext` branch rather than returning. So that one row is written with
  `event_time = FROM_UNIXTIME(0)` and a `match_id` from daemon memory, with a line in the log
  and the row stored anyway. Section C's flag-state watermarks are therefore reading for
  accrual, not for history. The handler change belongs to `KTPHLStatsX` and is not in this PR.
- **The sixth site** is `doEvent_KTPFlagPosition`, writing `last_event_epoch` on
  `ktp_flag_positions`. It has the same `// 0` and no `FROM_UNIXTIME` beside it, so it cannot
  produce the counting defect — it gets its own short section as a provenance read.
- **`tests/unit/test_corpus_time_window_integrity.py`** runs the shipped statements, read out of
  both SQL files rather than re-implemented, against a stdlib-sqlite3 fixture. The translator
  handles only the constructs these files use and raises on anything else, so a section
  rewritten into an unsupported shape fails instead of returning a plausible zero. The fixture
  seeds rows on **both** sides of the epoch floor, in three different renderings of
  `FROM_UNIXTIME(0)`, and separately seeds a B1 orphan, a B2 orphan half, a case-variant id,
  the by-design NULL population and an empty-string id — with named assertions that each of
  those populations is non-empty, so a one-sided or emptied fixture fails by name rather than
  passing while testing nothing. Each of the five streams gets a different row count, so a
  UNION branch pointed at the wrong table returns another stream's number.
- The clean-zero is reproduced rather than described: on the same fixture the guessed
  `event_time = '1970-01-01 00:00:00'` finds fewer rows than the floor does, and once the rows
  stored in that one rendering are removed it finds **none** over a table that still holds
  defective rows. The withdrawn null-or-zero orphan test is reproduced the same way, scoring the
  by-design population as defects.
- 22 mutations — of the floor literal, the floor's direction, the orphan guards, the `BINARY`
  comparison, each preflight manifest entry, the stream labels, the ENGINE line, a semicolon in
  a comment, a percentage, and five mutations of the fixture itself — each redden a named leg,
  with none left green and none vacuous. Two earlier cuts were thrown away for being vacuous and
  saying so: `SUM(...) + 0` is arithmetically a no-op, and a stream-label mutation matched the
  preflight manifest at line 185, which this module deliberately does not execute.
- **`event_time` is not UTC and nothing here re-stamps it.** It is
  `FROM_UNIXTIME(producer epoch)` rendered in the MySQL session zone, which is `SYSTEM` on an
  `America/New_York` host, while `created_at` is a `TIMESTAMP`. Readers that already window on
  it — `scripts/mmr/momentum_fetch.py`, `sql/analytics/capture_credit_timeline_fact.sql`,
  `player_half_fact.sql`, `player_match_fact.sql` — compare it against other columns from the
  same clock and are self-consistent. The one-year floor is immune to the offset in both
  directions, which is the second reason it is a floor.
- ⛔ **Nothing here is a measurement of the live corpus.** Production reads are not available
  from this seat. The counts above are the fixture's, and the real reading is one `sudo mysql`
  command, written in each file's header.
