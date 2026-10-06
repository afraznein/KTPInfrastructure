### `scripts`: demo coverage says whose clock the loss is measured against (2026-10-06)

`demo_coverage.py`'s own docstring said the half's clock "comes from the engine feed". It does not.
`ktp_life_events.reason='context_live'` is written by the `stats_logging` producer —
`ksc_sync_life_context` queues that row from a 0.5 s poll and retries whenever the dedicated life
buffer is full — so **`loss` is a difference between a producer-written row and a demo, and a
producer change that moves the first `context_live` row of a half moves `loss` by the same amount
with no change to any demo.**

That matters because this script is the acceptance check for the proxy-side flush fix, and a
producer regression was read off it fleet-wide. "The producer regressed demo tail coverage" and
"the producer moved this reference point" are not separable by `loss` alone. The discriminating
control needs no new demos: compare `MIN(game_time) WHERE reason='context_live'` for the same
halves across the two producer versions.

So the output now carries a `live_at` column and a footer naming the half clock's source, instead
of folding both inputs into one number. Nothing about the demo-side read changed.

The 1200 s half length was already known to be a model rather than a measurement — this file's
2026-09-26 entry says a negative loss means "this half was not 1200 s", not a demo that
over-covered — but nothing let you override it, so an overtime or short half could only be
discounted by hand. It is now `--half-seconds`, threaded through `measure()` into every row, and
the module docstring says it is an assumption. Outliers in both directions remain that model
failing rather than a demo's.

Both halves are pinned by tests that fail without the change: one asserts a later `context_live`
with an unchanged `track_time` worsens `loss` by exactly the shift, one asserts the assumed half
length moves `loss` by exactly its own change, and one asserts the flag reaches the rows rather
than only `--help`.
