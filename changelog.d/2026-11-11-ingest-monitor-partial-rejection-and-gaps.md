### Added
- `hlstatsx-ingest-monitor.py` reports a half that rejected more than one go-live snapshot as
  *found 0 event-time match intervals* (more than 50 rows or more than 3 streams), and any
  `frag_context` or `damage` health row with an open `sequence_gap_count`. A half whose start the
  daemon stamped late behind an ingest backlog loses only its first rows on each stream, so it
  never reaches the total-loss floor. On 2026-11-10 a 25 s backlog cost one NY1 half 282 rows over
  12 streams, and dropped 27 frag and 47 damage lines over UDP, and nothing reported either.
  Halves that are already a total loss are left to that check. Both alarms are interim. Once
  KTPMatchHandler sends `event_epoch` on `KTP_MATCH_START` and the daemon writes it
  (KTPMatchHandler#67, KTPHLStatsX#196), alarm on the start delay itself.
  ⚠️ Not fielded until the script is reinstalled on the data server.
