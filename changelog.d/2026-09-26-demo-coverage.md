### `scripts`: measure how much of its half a demo actually contains (2026-09-26)

An HLTV demo is not a complete record of its half. The proxy broadcasts 60 s behind live and
the demo client writes the delayed stream (`DemoClient::SendDatagram` reads
`GetFrameByTime(GetSpectatorTime())` whenever a delay is set), so the last minute of a level
exists only in the world's frame buffer — and `World::NewGame` frees that buffer when the next
level's `svc_serverinfo` arrives. An idle map rotation hides it, because the server sits at
intermission long enough for the spectator clock to catch up; a match `changelevel` at half end
does not. Every official half's recording therefore ended short.

`scripts/demo_coverage.py` is the re-runnable form of the measurement that found it, and the
acceptance check for the proxy-side fix (KTP-ReHLDS `Proxy::FlushDemoBuffer`). It reads playback
length from the `.dem` directory entry — two reads, and for a published demo two HTTP range
reads rather than a transfer — and compares it against the half's own clock from the engine
feed: `ktp_life_events.reason='context_live'` is the moment the half went live, and a half runs
1200 s from there. `--max-loss` turns it into a gate.

Over 35 official halves filed in the 14 days to 2026-09-26 the loss is tightly clustered at
44.1-45.2 s (median 44.5). Two shapes of outlier are visible in the output rather than hidden,
and both are the 1200 s half model failing rather than the demo: a half with no `context_live`
row reports no loss at all, and a half that ran long (pause, overtime) reports a negative one.
Read a negative loss as "this half was not 1200 s", not as a demo that over-covered.
