# FPS statistics exploration bundle

**Status:** private shadow implementation; not a public statistic or rating input

**Collection branch:** `feat/fps-stats-exploration-bundle` in KTPAMXX,
KTPHLStatsX, and KTPInfrastructure

This bundle implements the first five explorations from
`research/FPS_STATS_BENCHMARK_AND_KTP_BACKLOG.md`. It is intentionally a
cross-repository unit. Do not merge or deploy one repository as a standalone
feature, and do not pull individual commits directly into `preprod`.

## Safety boundary

The new results are read-only, private shadow output:

- no KTPR or other rating input;
- no database writes from the analytics calculation;
- no API or site output;
- no live opponent scouting or in-match advice;
- no raw coordinates, player paths, per-life timelines, or ordered event
  timelines in the aggregate exploration report.

Private per-player aggregates are allowed for review. Raw position, life, and
event facts remain private source data subject to the existing access and
retention policy. Scrim, 12man, and `*-TEST` source rows, including life and
canonical assist rows, remain purgeable after 14 days. Draft and official
matches remain retained.

The pre-existing, separately named `shadow_timelines` diagnostic retains
private event-level kill/objective records. It is not part of the aggregate
`shadow_explorations` output, is never published, and remains rating-neutral.

## Producer-time capture contract

Buffered log delivery makes daemon receipt time unsuitable for life and
damage attribution. Every coordinated match-scoped marker therefore carries
producer-authored:

```text
(matchid "...") (half "...") (event_epoch "...") (game_time "...")
```

`stats_logging` receives MatchHandler's authoritative match-start forward,
caches the normalized database half, and stamps the context only while it
exactly agrees with `dodx_get_match_id()`. Missing, late-load, empty, or
mismatched context fails closed. The daemon validates the explicit producer
match and half against exactly one event-time match interval; it never invents
a half from its receipt-time state.

Life boundaries use a dedicated priority queue so high-volume damage and
position samples cannot consume their capacity. A start is not marked as
recorded unless it was actually queued. Death, spawn, disconnect, transition,
and shutdown drains preserve boundary ordering.

`round_live` remains nullable. MatchHandler's DODX pause state is private and
cannot be truthfully reconstructed from the public `dodstats_pause` cvar.
Physical lives are captured across live/freeze state, and the report explicitly
states that live-versus-freeze classification is unavailable.

## Schema additions

KTPHLStatsX migrations must be applied in order:

1. `sql/migrate_016_life_events.sql` creates `ktp_life_events`.
2. `sql/migrate_017_capture_clocks_and_assists.sql` adds nullable producer
   context/clocks to frags and damage and creates `ktp_assist_events`.

The generic rating-neutral HLStatsX assist action remains intact for the box
score. `ktp_assist_events` is an additive private fact table that supplies the
producer half and clocks needed for timed attribution.

Old rows keep nullable producer fields. Timed exploration code must report
those sources as unavailable or incomplete; it must not fall back to buffered
receipt time.

## Metric definitions

### Symmetric basic trades

A basic trade is an opposing frag answered in the same half within the
configured window (default five seconds) by a teammate killing the original
killer. One reply credits at most one prior death, choosing the most recent
eligible death.

The output credits both sides:

- `trade_kills`: successful replies by the trader;
- `deaths_traded`: fallen teammates whose death received the reply;
- `team_death_response_opportunities`: canonical opposing deaths suffered by
  the team;
- `team_death_response_rate`: successful replies divided by that team-death
  denominator.

The denominator is not an individual player's trade opportunity. The current
facts do not prove that a particular teammate was alive, nearby, had line of
sight, or could respond. Missing roster-team context is surfaced as partial
coverage rather than converted to a false zero.

### Revenge response

A revenge response is a player killing the opponent responsible for the
player's immediately preceding opponent-caused death in the same half. There
is no arbitrary time limit. Any intervening physical death expires the pending
response, including a death that is not present in the canonical enemy-frag
table.

Producer-clock frags and complete life death boundaries are required. Missing
all-death coverage suppresses the result rather than allowing a response to
survive an unobserved suicide or teamkill.

### Damage conversion

Only HP-capped damage is used. A hit is followed within the configured window
(default 15 seconds) until the victim's first physical death boundary. That
death is a hard reset. The damage is aggregated as:

- damage to the attacker's own kill;
- damage to a canonical credited assist;
- damage to a teammate finish without credited assist;
- unconverted damage, including timeout, suicide/teamkill/no canonical finish,
  or an opposing outcome.

The join uses producer half and `game_time` for damage, frag, assist, and life
facts. It is a temporal association, not proof that a hit caused the kill.
Damage per kill counts canonical opposing kills only.

### Sampled objective pressure

Alive-player position samples are classified against static flag positions and
the ownership timeline using two-dimensional map-unit radii. The report
separates friendly-owned proximity, neutral proximity, enemy-owned pressure,
unknown ownership, and sampled contest.

The unit is nominal sampled **player-seconds**. Two players sampled for five
seconds contribute ten aggregate player-seconds. It is not exact capture-volume
time. Confidence requires minimum distinct snapshots, minimum per-player
samples, a bounded maximum sample gap, complete ownership baselines, and—when
match duration is known—minimum nominal temporal coverage. A single timestamp
is partial/low confidence even if every row at that timestamp is valid.

### Weapon kill-time player separation

The weapon profile measures the three-dimensional killer-to-victim endpoint
separation when a successful kill is recorded. It includes aggregate bands,
headshot, scoped, and prone context where available.

This is deliberately not called firing distance or weapon range. For delayed
grenades and projectiles, the killer's location at death time may differ from
the firing origin. The measure also excludes misses, nonlethal engagements,
route distance, and line of sight.

### DoD-native KAT coverage

KAT is the fraction of completed, death-ended physical lives containing at
least one canonical opposing kill, canonical assist, or a death that was
traded. It is not KAST: continuous-respawn DoD has no honest round-survival
analogue, so no survival component is invented.

Disconnect-ended, consecutive-start, and open lives are censored. A
`context_live` start is left-censored and lowers confidence. Every canonical
frag victim must match exactly one death-ended life; incomplete reverse
coverage suppresses the numeric so a dropped start/death pair cannot silently
shrink the denominator. Suicide coverage is inventoried separately because
the canonical enemy-frag feed does not contain it.

## Coordinated validation and promotion

GitHub cannot merge three repositories atomically. Treat the exact immutable
SHAs and one Lane B artifact manifest as the release unit:

1. Finish and test all work locally on the three collection branches.
2. Commit and push all three branches; record their immutable SHAs and the
   frozen KTPMatchHandler SHA.
3. Run deterministic tests and `lane=full` against those exact four SHAs.
   The artifact manifest must record the resolved Infrastructure,
   MatchHandler, AMXX, and HLStatsX SHAs.
4. Require two-half/delayed-marker, saturation, reconnect, daemon-restart,
   late-plugin-load, migration, and aggregate-only contract tests to pass.
5. Open the three PRs to `preprod` together and cross-link the same four-SHA
   manifest and Lane B run. Do not merge any PR until the complete bundle is
   approved and green.
6. Merge in a short dependency-safe window: KTPHLStatsX, then
   KTPInfrastructure, then KTPAMXX.
7. Rerun full Lane B using the resulting three `preprod` SHAs and the frozen
   MatchHandler SHA.
8. Deploy to the designated human canary only after that post-merge run passes.

An ordinary PR corpus check is not sufficient. The AMXX corpus path uses
`--no-plugin`, existing committed corpus logs predate these markers, and full
Lane B historically exercised only half one. The exact-bundle full run and
deterministic transition tests are mandatory evidence.

## Runtime deployment order

1. Back up the data server and apply migrations 016 then 017.
2. Install/restart the updated HLStatsX daemon.
3. Install the newly compiled `stats_logging.amxx` and perform a full HLDS/AMXX
   process restart.
4. Install the updated Infrastructure analytics/retention tooling only after
   both new tables exist.
5. Run a test match, then a real human canary, and review private reports plus
   exact source coverage before considering broader deployment.

A map change or plugin hot-reload is not enough. AMXX multi-forward subscriber
lists are snapshotted when MatchHandler constructs them, so a late-loaded
`stats_logging` may not receive the start forward until a full process restart.

Stop and roll back the plugin/daemon if producer context is missing or
mismatched, life/assist counts do not reconcile, any marker crosses into the
wrong half, KAT reverse coverage is incomplete, or raw coordinates, position
timelines, or reconstructed per-life timelines appear in aggregate output.
Database migrations are additive and can remain in
place during a binary rollback; old emitters leave the new nullable fields
empty and analytics must report the timed sources unavailable.
