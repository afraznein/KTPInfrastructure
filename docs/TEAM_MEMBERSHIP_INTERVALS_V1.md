# Team membership intervals v1

## Private collection contract

One row represents one authoritative participant/team transition within a match
half. Consumers derive contiguous intervals by ordering a player's transitions;
the raw ledger never overwrites prior evidence.

| Field | Rule |
|---|---|
| `server_id`, `match_id`, `half`, `player_id` | Private source join key; the producer match and half must resolve to exactly one persisted match interval. |
| `team`, `old_team` | New/previous DODX team: `0` unassigned, `1` Allies, `2` Axis. A `0` transition closes a derived playing interval. |
| `game_time`, `event_epoch` | Producer `get_gametime()` and `get_systime()` values, validated against the exact persisted match-half interval. |
| `producer_sequence` | Per-producer monotonic sequence; equal replay is idempotent and a lower transition sequence is rejected while the context is live. |
| `source` | `authoritative_team_transition_v1`; no inference from position samples. |

The persistence table is append-only. `ktp_match_players.team` remains a
convenience roster snapshot and must not be used as interval evidence.

## Producer and daemon protocol

The AMXX capture plugin emits a buffered `team_membership` marker whenever a
connected player enters Allies or Axis, changes side, or leaves a playing side.
It includes explicit `matchid`, `half`, `event_epoch`, `game_time`, `team`, and
monotonic `sequence`. The daemon validates the source event against the exact
server/match/half time interval before it writes an interval transition.

The daemon persists only validated raw transitions; interval closure is a
deterministic private query operation, never a receipt-time daemon guess.
Replayed markers leave the ledger unchanged. Unknown, out-of-order, or
cross-match transitions are rejected and make team-dependent analytics
unavailable—not assigned to a prior team.

Schema 21 is a deliberately partial producer contract: it authorizes only
`team_membership` transitions and their health reconciliation. Schema 22 adds
the richer objective/grenade streams required by positional and objective
metrics. A schema-21 match must therefore remain ineligible for those metrics,
even when its team-transition ledger is healthy.

## Acceptance tests

- Initial 6v6 membership records twelve playing-side transitions.
- A mid-half side switch records one transition whose `old_team`/`team` pair
  yields exactly two derived intervals.
- Disconnect to unassigned closes a derived open interval; reconnect opens a new one.
- Duplicate and out-of-order producer markers are idempotent/rejected respectively.
- A marker whose map, half, or event time does not resolve to the producer match is rejected.
- Lane B facts expose only aggregate interval quality and set team-dependent positional metrics to `unavailable` on invalid coverage.

This is private ingestion metadata. No public artifact may contain the match
key, participant key, individual interval, source time, source path, or raw
team transition event.
