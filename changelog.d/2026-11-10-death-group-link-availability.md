### `analytics`: the death-group links get a consumer that can say `unavailable` (2026-11-10)

`docs/TELEMETRY_CAUSAL_LINKS_V1.md` says a missing causal link is `unavailable` and
never a negative contribution, and until now nothing could honour that: the daemon
writes the three link columns from KTPHLStatsX `migrate_054`, and no analytics code
read them. The alternative to `unavailable` is an implicit zero, which in an aggregate
is the silent wrong answer the clause exists to forbid.

- **`match_analytics`** gains a `causal_links` capability (all five columns the
  resolution needs) and a `death_group` block: per half, how many assists and
  producer-stamped frags carry a link and how many of those resolve. Counts only.
  An archive without the columns, and a half in which no link was recorded, read
  `unavailable` with no numbers at all. A half whose links all resolve is
  `available`; one with a link naming nothing is `partial` and says how many.
- **Resolution uses the typed key**, as `migrate_054`'s first trap requires:
  same server, match, half and referent stream, then `producer_sequence`. Sequences
  are per event type and restart each half, so a bare integer names nothing — a
  life-end and a frag in the same half routinely share one. A life link must land on
  a `boundary_kind = 'end'` row. NULL is the honest no-parent of a teamkill, world
  death, suicide or dropped marker, and is neither linked nor unresolved.
- **`match_readiness`** gains a `death_group` metric whose one specific requirement
  is `death_group_link_resolution`. That check is emitted only once a link exists,
  so an archive from before the producer reads `unavailable` rather than `partial`,
  and the overall readiness status of every existing archive is unchanged. A link
  that resolves to nothing FAILs it. `verify_bot_match_telemetry --require
  death_group=available` is then the spec's bot-match acceptance test as written.
- **Not published.** The public DTO is an allowlist and does not carry the block;
  the spec allows aggregate link-availability counts to be published, and that is a
  separate decision.

Schema 38 -> 39: every stored report gains the block, so every report regenerates,
and every match from before the causal-link producer was fielded will read
`unavailable` — which is the correct answer for them, not a regression.
`METRIC_ELIGIBILITY_VERSION` stays at 1: a new metric key is additive, and the one
consumer that compares the version (`verify_bot_match_telemetry`) only reads the
metrics it is asked for.

Verified with twelve new unit tests, three of them mutation-checked (an untyped key,
an always-emitted readiness check, and zero counts in an unlinked half each turn
exactly one red). The SQL itself runs only against MySQL; Lane B applies `migrate_054` and is where it meets a real schema,
and it was not run locally.
