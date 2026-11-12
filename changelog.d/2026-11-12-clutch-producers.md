### `scripts`: the two ruled clutch stats get producers and public keys (2026-11-12)

Both definitions were ruled on 2026-10-05: ship both, shown separately, never summed
(#783). Analytics report schema 41, DTO contract v1.19.0.

- `scripts/outnumbered_kills.py` (new): `outnumbered_kill_v1`, enemy kills made while
  living enemies outnumbered the killer's side, killer included, by 2 or more. Read just
  before the kill instant from the life ledger, per player-half, with `lower_bound` for a
  censored or unplaceable kill. 4,491 of 24,763 evaluated kills (18.1%) on 40 two-half
  matches, against the proposal's 17.2% on five.
- `scripts/flag_fights.py`: `fight_clutch_v1` stops censoring every window of a half
  because a roster member was absent from it. A player with no boundary in the half, or
  whose first one is a later spawn, is not alive; only a first boundary that is a later
  death still censors. Censored windows on the same 40 matches: 104 of 1,493 before, 4
  after. The envelope's visibility is now `public_dto`.
- `scripts/analytics_report_dto.py`: top-level `outnumbered_kills` and `fight_clutches`,
  `players[].outnumbered_kills` and `players[].fight_clutches`, each with a glossary
  entry that says never to add the two. A `fight_clutches` envelope from before schema 41
  reads `unavailable`.
- `docs/ANALYTICS_REPORT_DTO_CONTRACT.md`: both blocks, with the reason they stay apart.

Not in this change: the site wiring, and any storage beyond the existing report payload.
