### `analytics`: `caster_weekly.py` — the cast intake as one command (2026-09-27)

- `scan` lists casts newer than the store already knows (bounded per channel;
  entries with no start time are skipped, since they can be neither placed nor
  aligned), `status` shows what each cast is waiting for, and `run` transcribes
  with the match roster as the decoding prompt, exports the match's events, and
  aligns live casts at +60 s or delayed ones at their half-end anchor.
- Audio is deleted in the same step that transcribes it, inside a `finally`, so
  a run that fails partway still leaves text only.
- Nothing is downloaded unless the store carries a `_consent` line saying who
  agreed to be transcribed and when.
- It deliberately will not place a cast against a match, or find the half end in
  a delayed cast: both were measured wrong when automated, so it stops and names
  the casts waiting on a human rather than guessing.
- Configured entirely through the environment; no channel, caster or player name
  is in the repo. Docs: `scripts/README-caster-alignment.md`.
