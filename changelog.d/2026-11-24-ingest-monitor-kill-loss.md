### Fixed
- `hlstatsx-ingest-monitor.py`'s sequence-gap leg watched `frag_context`, which no
  `ktp_capture_health` row has ever carried, so it checked `damage` alone. It now watches
  `frag`, and a new guard reports a watched stream with 0 rows in 7 days (while other streams
  have rows) as a misconfiguration instead of passing.
- The summary-vs-events comparison counted frag rows by `eventTime` over the last 90 minutes,
  which clipped any half that started before the window and produced false "summary ahead of
  tagged events" lines. It now takes each half that ended in the window and counts it whole.

### Added
- Kill-loss leg: per half, frag-stream `emitted` minus `hlstats_Events_Frags` rows. 1-2 lost
  kills warn (`??`, exit 0), 3 or more page, on the same `--gap-warn-max` ceiling as the gap leg.
  ⚠️ Not fielded until the script is reinstalled on the data server.
