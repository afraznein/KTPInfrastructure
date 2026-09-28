### `analytics`: fix `caster_weekly.py scan` silently reporting nothing (2026-09-28)

- A flat playlist listing carries **no timestamp on either channel** — every entry
  comes back `NA`. `scan` skipped undated entries on the grounds that they can be
  neither placed nor aligned, which meant it skipped *everything* and reported
  "0 new casts" for a week while real casts accumulated. Two were missed.
- It now resolves the timestamp per candidate with one metadata call (no
  download), and only for ids the store has never seen.
- Twitch listing ids carry a `v` prefix (`v2885964510`) that the watch URL does
  not take. Left on, the lookup resolved to nothing and the cast looked undated —
  so the newest cast stayed invisible even after the first fix.
- The same cast is often on two channels under different ids. `scan` now skips an
  entry whose title matches a stored cast with a duration within a minute, rather
  than proposing a transcription of something already in the corpus.
- Verified against the live channels: 3 genuinely new casts found, 4 mirrors
  skipped, 5 older than the store's newest skipped.
