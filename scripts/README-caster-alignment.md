# Aligning a match cast to the match, and using it to check the pricing

`scripts/plays.py` and `scripts/excursions.py` price plays whose value is not in kills or damage —
a solo cap, a cap-out denial, a collapse into the enemy spawn. Nothing in the data says whether a
human watching thought those mattered, or how much. A cast does: it is a continuous human judgement
over the same timeline. These scripts attach one to the other, and keep doing it weekly.

- `caster_weekly.py` — the standing job: find new casts, transcribe, export, align, clean up.
- `caster_align.py` — put the commentary next to every priced play, plus score events and flag
  changes, for reading.
- `caster_recall.py` — measure whether priced plays draw more reaction than a random moment in the
  same match, by play class.

All three are stdlib-only. Only `caster_weekly.py` reaches the network, and only by shelling out to the tools named below.

## Inputs live outside this repo

This repository is public. No transcript, no cast-to-match mapping and no caster, stream or player
name belongs in it. Point the scripts at a local working directory:

| Variable | Default | Holds |
|---|---|---|
| `KTP_CASTER_TEXT_DIR` | `caster/text` | `v<cast_id>.json` — whisper.cpp `-oj` output |
| `KTP_CASTER_EVENTS_DIR` | `caster/events` | per-match `frags` / `flag_state` / `score` / `priced` TSVs, plus `halves.tsv` |
| `KTP_CASTER_CASTS` | `caster/casts.json` | the cast-to-match mapping (`caster-casts.json.example`) |

**Audio is not an input and is not kept.** A recording is transcribed once and deleted in the same
step; only text is retained. Get consent from whoever is speaking before any of this runs.

The event TSVs are straight exports, e.g.

```sql
SELECT f.event_epoch, f.game_time, f.half, f.eventTime,
       k.player_name AS killer, v.player_name AS victim, f.weapon, f.headshot, f.is_last_flag_defense
FROM hlstats_Events_Frags f
LEFT JOIN ktp_match_players k ON k.match_id = f.match_id AND k.player_id = f.killerId
LEFT JOIN ktp_match_players v ON v.match_id = f.match_id AND v.player_id = f.victimId
WHERE f.match_id = ? ORDER BY f.event_epoch, f.id;
```

`<match>.priced.tsv` is `n, half, game_t, seek, class, who, detail` — one row per priced play.

## Alignment: two cases

**Live cast.** `cast_seconds = event_epoch - cast_start + offset`. The offset is the broadcast
delay, measured at a constant **+60 s** across four matches and three casts, so `--offset 60` is a
default rather than a per-cast fit.

```
python scripts/caster_align.py <match_id> <cast_id> --vod-start <epoch> --map dod_lennon5_b1 --offset 60
```

**Delayed cast** (the match re-cast later from a recording). There is no epoch relationship.
Correlating spoken player names against that player's frags does not recover one: with ~580 frags
over ~45 minutes a given player frags about once per 28 s, so at a 16 s window roughly 57% of name
mentions coincide at *any* offset. Measured best margin was 2 points out of 60 — flat.

What works is the **half end**. There are two per match, they are rare, and commentary marks them
out loud and reads the halftime score. Find that moment in the transcript, check the numbers read
aloud against the data, and pass it:

```
python scripts/caster_align.py <match_id> <cast_id> --vod-start <epoch> --anchor 26:01
```

`--anchor-what` selects which boundary (`h1end` by default) and is read from `halves.tsv`.

## What the reaction channel can and cannot do

`caster_align.py` also scores reaction language and merges it into bursts, flagging bursts with no
priced play nearby. Treat that list with suspicion: measured, excitement tracks **kills**, which
happen every ~20 s, while the plays priced here are quiet by construction. Lift of priced windows
over random windows in the same match was **1.02** — nothing. Stream chatter is filtered and
multi-kill-explained bursts are subtracted, and it still mostly surfaces highlights.

The useful direction is the reverse, which is `caster_recall.py`: not "were the loud moments
priced plays" but "do priced plays get noticed, and by how much". Scored that way on 25 plays:

| Class | n | Lift, 25 plays (09-24) | Lift, 36 plays (09-27) |
|---|---:|---:|---:|
| Cap-out denial | 10 | 0.00 | **0.00** |
| Solo run-through cap | 9 | 0.98 | 1.10 |
| Deep collapse / spawn pressure | 6 | 1.77 | **1.06** |
| Attempt, reached the flag | 6 | 1.78 | **0.00** |
| Sneak cap | 5 | 1.01 | 1.01 |

**Two of those moved enough to retract.** Deep collapse and attempt were measured at 1.77 and 1.78
on n=3 and n=2, and both collapsed when the delayed casts brought them to n=6. Neither was ever
evidence. What has held across both samples is the cap-out denial zero, now on n=10: a human
watching does not register these at all.

### Class-specific language is a dead end too

Phrases like "on his own", "quietly" or "in behind" looked like the channel that catches denials:
in-sample they fire on 9 of 36 priced windows against a 16% baseline, lift 1.56. That number is
circular — the phrases were chosen by looking at the same windows they were scored on. Evaluated
**leave-one-cast-out**, choosing the list on four casts and scoring it on the fifth, it fires on
**0% of held-out priced windows against a 10% baseline**. The strong-looking phrases were single
occurrences; only "cap out" clears selection at all, and it does not generalise.

The phrase scan is kept for reading what was said around a play. It is not a signal.

**The sample is small and it shows.** Only matches that were actually cast can be checked this
way, so this calibrates against a subset and will never label a whole season. Because of that,
`--record <path.tsv>` appends every run's per-class lift and reports what moved since the last
one: the stopping rule here is "the numbers stopped changing", which is unanswerable from memory.
The first two recordings are exactly why — see the retraction above.


## The weekly job

`caster_weekly.py` is the whole intake in one command, so nobody has to remember six steps in
order:

```
caster_weekly.py scan      # casts newer than the store knows; writes stubs, downloads nothing
caster_weekly.py status    # what is placed, fetched, aligned, and what is waiting on you
caster_weekly.py run       # transcribe + export + align everything that is ready
```

`run` fetches audio, transcribes it with that match's roster as the decoding prompt, **deletes the
audio in the same step** (in a `finally`, so a run that dies partway still leaves only text),
exports the match's events, and aligns. `--dry-run` prints the plan and touches nothing.

### Two steps it will not take for you

Both were measured wrong when automated, so the job stops and says what it needs instead of
guessing.

1. **Placing a cast against a match.** Title and time give a shortlist; the transcript settles it.
   Live versus delayed decides which anchor applies, and guessing wrong aligns the commentary to
   the wrong match entirely.
2. **Finding the half end in a delayed cast.** See the alignment section above — name correlation
   does not converge. A human reads the transcript for where the score is called and sets `anchor`.

`status` lists exactly which casts sit in those two states. Everything else `run` handles.

### Consent is enforced, not assumed

The store must carry a `_consent` string naming who agreed to be transcribed and when. Without it
nothing downloads. It is someone's voice, and the check exists so the rule cannot quietly lapse.
