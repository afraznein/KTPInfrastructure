### `analytics`: align a match cast to the match, and use it to check what `plays.py` prices (2026-09-26)

- New `scripts/caster_align.py`: given a cast's transcript and a match's event
  exports, puts the commentary next to every priced play, score event and flag
  change. Live casts align on `event_epoch` plus the broadcast delay, measured
  constant at +60 s across four matches and three casts. Delayed casts — the
  match re-cast later from a recording — have no epoch relationship, and
  correlating spoken names against that player's frags does not recover one
  (~57% of mentions coincide at any offset; best margin 2 points of 60). The
  half end does: two per match, rare, marked out loud with the halftime score
  read aloud, so `--anchor MM:SS` fixes the offset exactly.
- New `scripts/caster_recall.py`: measures whether priced plays draw more
  reaction than a random window in the same match, by class. On 25 plays, deep
  collapses lift 1.77 and attempts 1.78, while cap-out denials draw a median
  reaction of exactly zero. A human watching does not register a denial at all,
  which is a reason to price them, not to discount them.
- Reaction language alone does NOT find plays the pricing missed: excitement
  tracks kills, which happen every ~20 s, and the lift of priced windows over
  random ones was 1.02. Recorded in both headers so it is not rebuilt.
- Inputs are text only and live outside this public repo, under
  `KTP_CASTER_TEXT_DIR`, `KTP_CASTER_EVENTS_DIR` and `KTP_CASTER_CASTS`. No
  caster, stream or player name is in the code. Audio is transcribed once and
  deleted; consent comes first. Docs: `scripts/README-caster-alignment.md`.
