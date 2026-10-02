### `scripts`: capture authorization reads schema-24+ sequence counters per stream (2026-10-01)

`match_analytics.evaluate_capture_authorization` treated `sequence_gap_count`
and `duplicate_or_reordered_count` as one half-wide value stamped into every
event type's row, took `max()` across the half, and subtracted the sum of every
stream's emitted/received shortfall. That stopped being true with the schema-24
producer: each stream is numbered from its own sequence (`g_kscTypeSequence`)
and the daemon tracks gaps per stream (`ktpObserveCaptureMarker`), so the rows
of one half now carry different counters. Against that shape the old residual
was weak in both directions:

- a stream whose gap its own counters could not explain still published
  whenever a sibling's larger shortfall absorbed the gap;
- when the residual did fire, it withheld every stream in the match for
  evidence that belongs to one.

Schema 24 and later now charge each row's gap against that row's own shortfall
(clipped at zero, because tail loss leaves a shortfall and no gap), and a
duplicate or unexplained gap withholds only that stream. Schema 22/23 halves
keep the half-wide residual, which is still what their counters mean.

Match-level `authorized` is unchanged: any gap or duplicate still fails it.
