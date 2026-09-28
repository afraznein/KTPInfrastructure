### `analytics`: the commentary index — cast commentary as a parallel label channel (2026-09-28)

- `caster_align.py --emit-index <tsv>` writes one row per spoken segment with the
  half and game_time it lands on. It makes no judgement and reads no detector
  output: commentary is a channel in its own right, not a consumer of priced
  rows (ruled 2026-09-28). Two humans then describe the same timeline without
  coordinating — a player files what happened, the caster narrates it live with
  no idea what is priced — and whatever reads both can ask what neither answers
  alone: did anyone notice.
- `caster_weekly.py run` emits the index alongside the readable report.
- A segment is assigned to the half whose **epoch window** contains it, read from
  `halves.tsv`. Assigning by game_time range does not work: the halves' ranges
  overlap, so it resolves by iteration order and put most of one match in the
  wrong half.
- A **delayed** cast pauses between halves, so a single anchor places only the
  half it was read from. The index now emits that half and counts the rest out
  rather than inventing times for them. A live cast runs on continuous real time
  and places both halves normally.
- `halves.tsv` is now merged, not overwritten. Writing only the current run's
  matches silently removed every earlier one, which broke the alignment of any
  delayed cast anchored on a half exported in a previous week.
- Corpus: 11 matches indexed, ~4,100 placed segments.
