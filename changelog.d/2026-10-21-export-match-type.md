### `analytics`: the exporter sends `matchType`, so a scrim can no longer bind a league fixture (2026-10-21)

`decideLink` carried for weeks the premise that match type is "structurally absent from the
game data" — true when written, false since. `hlstatsx.ktp_matches.match_type` is populated
and authoritative, and `scripts/report_scope.py` already filters publication on it. The
signal was being dropped one layer upstream of the decision: `GameMatchForCorrelation`
carried `gameMatchId`, `startedAt`, `mapName`, `sideA`, `sideB` and no type, so the one
field that settles a scrim-versus-fixture contest never reached the code that needed it.
`searse/keep-the-prac`#1007 made it a required field and reads it through
`isOfficialMatchType`; migration `20261028090000` added `ktp.game_match.match_type` and was
applied 2026-10-20. Nothing observable changed, because this script is the only producer
and it sent no type. This is that last leg.

- `fetch_matches` selects the type on BOTH paths, and the `--match-id` path is the point.
  The 48-hour window already filters `match_type in (0, 4)`, so the nightly path never
  carried a scrim to begin with; `--match-id` has no type predicate by design — an operator
  asking for one match by id means that match, whatever it is — and that is the recovery
  path a scrim reaches the site through. The site's gate is what covers it, and a gate
  cannot read a field nobody sends.
- `ktp_matches` is per HALF, so a match can in principle carry two types: a half typed by
  mistake and corrected. A disagreement resolves to the NON-official type, because the
  correlator is built to fail to an admin queue and a false bind is the one outcome it must
  not reach. All halves untyped stays NULL, which the site reads as "allowed" — refusing on
  absence would queue every row staged before today and the 21 S9-era league matches with
  no `ktp_matches` row at all.
- Measured against the live database, read-only: no `match_id` in the table carries two
  distinct types and none mixes official with non-official, so the rule above is a guard
  against a case that has not happened rather than a correction of one. The nine half-set
  cases were exercised in MySQL — `(1,0)` picks 1, `(2,4)` picks 2, `(null,0)` picks 0,
  all-null picks null. A real 12-man by id now reports type 2, and `1790817171-ATL3`
  reports 0.
- `matchType` is in `payload_hash` on both sides, so the first run after install re-POSTs
  the whole export window once and the site re-stages it. That is an upsert plus a player
  replace — idempotent, not a loss — and it is the one-time cost the migration header
  already anticipated.
- ⚠️ Installing this is an operator act: the live copy is `/usr/local/bin/ktp-stats-export.py`
  on the data server, tracked as `dpl-40a9` leg 3. Until it is installed the column stays
  NULL on every row and the correlator behaves exactly as it does today.
