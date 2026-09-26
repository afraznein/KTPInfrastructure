# Aligning a match cast to the match, and using it to check the pricing

`scripts/plays.py` and `scripts/excursions.py` price plays whose value is not in kills or damage —
a solo cap, a cap-out denial, a collapse into the enemy spawn. Nothing in the data says whether a
human watching thought those mattered, or how much. A cast does: it is a continuous human judgement
over the same timeline. These two scripts attach one to the other.

- `caster_align.py` — put the commentary next to every priced play, plus score events and flag
  changes, for reading.
- `caster_recall.py` — measure whether priced plays draw more reaction than a random moment in the
  same match, by play class.

Both are stdlib-only and make no network calls.

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

| Class | n | Lift over baseline |
|---|---:|---:|
| Deep collapse / spawn pressure | 3 | 1.77 |
| Attempt, reached the flag | 2 | 1.78 |
| Solo run-through cap | 8 | 0.98 |
| Sneak cap | 5 | 1.01 |
| Cap-out denial | 7 | **0.00** (median reaction zero) |

A human watching registers a player bleeding into the enemy spawn and does not register a cap-out
denial at all. That zero is a finding, not a gap: low salience is the reason these plays need
pricing. Class-specific language (someone arriving unseen, someone holding alone) fires on 9 of 25
including 4 of the 7 silent denials — denials get narrated calmly rather than shouted.

**The sample is small.** Twenty-five plays over four matches shows existence, never a rate. Only
matches that were actually cast can be checked this way, so this calibrates against a subset; it
will never label a whole season.
