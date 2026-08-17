# KTP stats schema and duplication audit

Date: 2026-08-16  
Scope: preprod Lane B output and the KTP additions to HLstatsX. No production
schema is removed or mutated by this audit.

## Executive findings

1. Most visible `NULL`s come from dumping the complete legacy HLstatsX schema.
   KTP never populates profile fields such as `email`, `homepage`, `fullName`,
   `icq`, geography, or avatar/ranking compatibility fields. They should not be
   in the regression report.
2. Some `NULL`s are useful evidence and must remain visible. In particular,
   `match_id=NULL` means an event occurred outside the competitive match window.
   The 2026-08-16 Lane B run exposed that test-mode StatsMe flushing happened
   after `KTP_MATCH_END`, unlike production, leaving every StatsMe row untagged.
3. `skill` and `skill_change` are inherited HLstatsX ranking values, not KTP
   match statistics. Kills and rewarded actions add ranking points; deaths,
   teamkills, suicides, and penalties can subtract them. `skill_change` is the
   change over the history/session period and `last_skill_change` is the current
   player row's last recorded delta.
4. `ktp_flag_positions` is reference data, not match/event data. The current
   implementation already uses an idempotent unique key and upsert, so repeated
   map loads do not create duplicate rows. A catalog discovery job is still a
   cleaner long-term owner for this data.
5. The largest real duplication is `ktp_match_stats`: it materializes kills,
   deaths, headshots, teamkills, suicides, and damage that are derived from raw
   event tables. It is also actively consumed and contains score data that is
   currently held only in memory before aggregation, so dropping it now would
   lose data and break consumers. Treat it as a derived cache and reconcile it
   against canonical events.

## What the NULLs mean

| Class | Examples | Interpretation | Action |
|---|---|---|---|
| Unused legacy profile | `hlstats_Players.email`, `homepage`, `fullName`, `icq`, geography | Stock HLstatsX compatibility fields; KTP does not collect them | Omit from Lane B reports; do not drop while the legacy web application remains in use |
| Boundary / not applicable | `match_id`, `half=0` | Warmup, post-match, connect-time, or session-flush data outside a match | Keep visible and assert expected rates |
| Optional enrichment | frag/action positions, contest context | Only event types with a matching KTP context marker receive these values | Keep visible; add event-specific completeness assertions |
| Missing feature | suicide position context | The source log currently has no KTP suicide-context enrichment | Document as a coverage/data gap rather than hiding it |

The report should display SQL `NULL` as `—`, omit known-unused profile columns,
and retain meaningful nullable event context.

## Table lineage and overlap

| Table/family | Grain and purpose | Canonical or derived | Overlap decision |
|---|---|---|---|
| `hlstats_Events_Frags` | One enemy kill | Canonical event | Keep. Source for match kills, deaths, headshots, kill positions, weapon and tactical context |
| `hlstats_Events_Teamkills` | One teamkill | Canonical event | Keep separate from frags because HLstatsX applies different penalties and consumers already use it |
| `hlstats_Events_Suicides` | One suicide | Canonical event | Keep separate; add position context only if the source can emit it reliably |
| `hlstats_Events_PlayerActions` | One player action such as control point, cap break, or streak | Canonical event | Keep. `dod_control_point` is the point event; it is not the same grain as per-capper capture credit |
| `hlstats_Events_PlayerPlayerActions` | One action relating actor and victim, currently assists | Canonical event | Keep |
| `hlstats_Events_TeamBonuses` | One team-member reward for an objective | Canonical reward event | Keep while HLstatsX ranking is retained; do not interpret as a unique capture count |
| `ktp_flag_captures` | One capping player credited on a completed capture | Canonical KTP event | Keep. Multiple rows can represent one multi-player capture by design |
| `ktp_damage_events` | One hit, with raw and HP-capped damage | Canonical KTP event | Keep. `damage_capped` is the authoritative competitive damage measure |
| `ktp_position_samples` | One alive-player position sample | Canonical telemetry | Keep with retention/partitioning policy; not a duplicate of kill positions because it covers non-kill movement |
| `ktp_flag_positions` | One static flag definition per server/map/index | Reference catalog | Keep for now; migrate ownership to a map-catalog discovery job and map fingerprint |
| `hlstats_Events_Statsme` | One player/weapon accumulator flush | Derived session/half weapon aggregate | Keep for shots, hits, weapon splits, and compatibility. Do not use it as authoritative per-hit or match damage |
| `hlstats_Events_Statsme2` | One player/weapon hit-location accumulator flush | Derived weapon/hitbox aggregate | Keep; it adds a dimension not present in StatsMe or frags |
| `hlstats_Players` | Current lifetime totals, identity, ranking state | Derived current snapshot | Keep for legacy HLstatsX; report only operational columns |
| `hlstats_PlayerNames` | Lifetime totals by player alias | Derived alias snapshot | Keep only while alias/name history is a consumer requirement |
| `hlstats_Players_History` | Daily player snapshots and ranking delta | Derived time-series snapshot | Keep for historical graphs; apply retention rather than merging into current players |
| `hlstats_Maps_Counts` | Lifetime map totals | Derived cache | Keep for legacy UI; reconcile with event facts if used for KTP analysis |
| `ktp_matches` | One row per match half | Match boundary metadata | Keep now. A later normalization can split one match header from per-half rows |
| `ktp_match_players` | Historical match roster snapshot | Canonical match membership | Keep. Current key lacks `half`; team swaps across halves need an explicit per-half roster design |
| `ktp_match_stats` | Player/half aggregate plus total row | Derived cache | Keep but rebuild/reconcile from canonical events. Score must first gain a durable canonical source before this table can become a view |

## Immediate corrections

### Test-mode StatsMe ordering

Production calls `dodx_flush_all_stats()` while match context is still active,
then emits `KTP_MATCH_END`. `.testmatch` did the reverse. Move the test flush
before the end marker so Lane B validates the production contract and StatsMe
rows receive `match_id` and `half`.

### Match damage source

`doEvent_KTPMatchEnd` currently fills `ktp_match_stats.damage` from
`hlstats_Events_Statsme`. The all-bot report demonstrated why that is fragile:
StatsMe is an accumulator flush whose attribution depends on flush timing.
Aggregate `SUM(ktp_damage_events.damage_capped)` by attacker, match, and half
instead. This is the same damage definition used by the composite calculation.

### Cache reconciliation

Lane B should compare every `ktp_match_stats` row with event-derived values:

- kills/deaths/headshots from `hlstats_Events_Frags`;
- teamkills from `hlstats_Events_Teamkills`;
- suicides from `hlstats_Events_Suicides`;
- damage from `ktp_damage_events.damage_capped`.

A mismatch is a failure. This makes the duplicate aggregate verifiable rather
than an independent and potentially divergent source of truth.

## Flag-position catalog recommendation

The user's proposed ownership model is correct: flag coordinates should be a
persistent map catalog populated independently of matches.

Recommended shape:

1. Inventory all installed BSPs on a disposable, network-disabled server.
2. Compute a BSP hash or map-version fingerprint. A map name alone cannot
   distinguish two different custom BSPs with the same filename.
3. Start each map periodically or when its fingerprint changes, collect one
   flag-definition set, validate non-zero coordinates and unique indexes, and
   upsert the catalog.
4. Key catalog rows by `(map_fingerprint, flag_index)`; keep map name as display
   metadata. Associate servers with the fingerprints they currently host.
5. Retain the current map-load upsert temporarily as a self-healing fallback.
   It is idempotent and low-volume, but it should no longer be considered match
   output or counted as newly inserted match data once the catalog is seeded.

## Safe dedup sequence

1. Clean reporting and add lineage/reconciliation assertions.
2. Correct test flush ordering and match-damage derivation.
3. Add a durable raw score event; then consider replacing
   `ktp_match_stats` with a view/materialized refresh owned by one job.
4. Normalize match header, halves, and per-half roster/team membership.
5. Build and seed the fingerprinted map/flag catalog.
6. Only after consumer queries are migrated and dual-read comparisons pass,
   deprecate columns or tables. Do not drop inherited HLstatsX tables while the
   public/legacy stats UI still reads them.
