# KTPWitness — test-only forward observer

An AMX plugin that registers as a CONSUMER of forwards under test and writes
one JSONL line per fire to `addons/ktpamx/logs/witness.jsonl`. As of 1.6.0
(all 4 phases shipped — 11 forwards covered):

1. **Match-flow multi-forwards** from KTPMatchHandler:
   `ktp_match_start`, `ktp_match_end`.
2. **DODX engine forwards** (11 forwards across Phases 1-4):
   - **Phase 1:** `controlpoints_init` (deterministic on map load)
   - **Phase 2:** `dod_client_spawn`, `dod_client_changeteam`,
     `dod_client_changeclass` (player-interaction; driven by `addbot`)
   - **Phase 2b:** `client_death` (driven by `amx_witness_kill <slot>`
     rcon, which calls core `user_kill()`)
   - **Phase 3 + 3b:** `client_damage`, `dod_grenade_explosion`,
     `client_score`, `dod_score_event` (driven by
     `amx_witness_dispatch_damage/grenade/score` rcons, which call
     test-only `dodx_test_dispatch_*` natives that fire forwards via
     `MF_ExecuteForward`).
   - **Phase 4:** `dod_stats_flush` (driven by full match-flow chain
     ending in KTPMatchHandler 0.10.124's `dodx_flush_all_stats()`
     call), `dod_control_point_captured` (driven by
     `amx_witness_dispatch_cp_captured` rcon).

3. **Test-only rcons** registered by the witness:
   - `amx_witness_kill <slot>` — calls core `user_kill(slot, 0)`.
   - `amx_witness_dispatch_damage <attacker> <victim> <damage> <wpnindex> <hitplace> <TA>`
     — calls `dodx_test_dispatch_damage` (DODX module 2026-05-05+).
   - `amx_witness_dispatch_grenade <slot> <x> <y> <z> <wpnid>`
     — calls `dodx_test_dispatch_grenade_explosion`.
   - `amx_witness_dispatch_score <id> <score_delta> <total> <cp_index>`
     — calls `dodx_test_dispatch_score` (fires both `client_score`
     and `dod_score_event` in tandem, matching production pattern).
   - `amx_witness_dispatch_cp_captured <cp_index> <new_owner> <old_owner>`
     — calls `dodx_test_dispatch_cp_captured`.

   Test-only — never wired into any production plugin.

**Module-set audit:** The 3 production modules (`amxxcurl + reapi + dodx`)
are unchanged. `user_kill`/`register_concmd`/`read_argv`/`str_to_num`/
`str_to_float` are all core AMXX (bundled in `ktpamx_i386.so`).
`dodx_test_dispatch_*` are added to the existing DODX module rather
than loaded as a new module (per operator policy 2026-05-05 — "if we'd
need a new base AMX module, implement the equivalent in DODX instead").

## Why this exists

The Tier 2 match-flow integration tests need a way to assert "the forward
fired with these args." Options considered:

1. **Scrape `log_ktp` `event=HALF_START` / `event=MATCH_END` lines.** Rejected
   because those are state-transition events emitted from KTPMatchHandler's
   internal codepaths — they fire at the same time as the forward but they
   don't *prove* the forward fired. A regression where ExecuteForward runs
   but a consumer crashes before its handler returns would pass a log-based
   assertion incorrectly.

2. **Add a test-only diagnostic native to KTPAMXX that reads forward-fire
   counts.** Heavyweight; touches the engine bridge for a test concern.

3. **Witness plugin (chosen).** Lightweight, lives entirely in the AMXX
   plugin layer, never touches production code. As a real consumer it
   exercises the same forward-dispatch path as KTPHLTVRecorder.

## Output format

`addons/ktpamx/logs/witness.jsonl` — one JSONL row per forward fire:

```jsonl
{"event":"ktp_match_start","ts":1777677796,"matchId":"1777677796-ATL2","map":"dod_anzio","matchType":0,"half":1}
{"event":"ktp_match_end","ts":1777678450,"matchId":"1777677796-ATL2","map":"dod_anzio","matchType":0,"score1":5,"score2":3}
{"event":"dod_controlpoints_init","ts":1777678451,"args":{}}
```

Two row shapes:

- **Match-flow rows** (`ktp_match_start` / `ktp_match_end`) inline forward
  args as top-level fields (`matchId`, `map`, `matchType`, `half` /
  `score1` / `score2`). Historical shape; preserved for compatibility with
  existing match-flow tests.
- **DODX rows** (event prefix `dod_*`) nest forward args under `args`.
  Empty dict `{}` is preserved when the forward has no args (e.g.
  `controlpoints_init`) so tests can rely on key presence rather than
  branching on absence.

Field reference (common):

| Key | Type | Source |
|---|---|---|
| `event` | string | Witness's labelled name (`ktp_match_start`, `ktp_match_end`, `dod_controlpoints_init`, ...) |
| `ts` | int | `get_systime()` at fire time (Unix epoch, server clock) |

Match-flow row fields:

| Key | Type | Source |
|---|---|---|
| `matchId` | string | KTPMatchHandler's `g_matchId` |
| `map` | string | Current map name |
| `matchType` | int | `MatchType` enum: 0=COMP, 1=SCRIM, 2=12MAN, 3=DRAFT, 4=KTP_OT, 5=DRAFT_OT |
| `half` | int | (start only) `1`/`2` for regulation, `101+` for OT rounds |
| `score1` | int | (end only) Final team1 score |
| `score2` | int | (end only) Final team2 score |

DODX row fields:

| Key | Type | Source |
|---|---|---|
| `args` | object | Forward-specific arg map. `{}` for `controlpoints_init`; populated for forwards with args (Phase 2+). |

## Compile

```bash
bash compile.sh
# → compiled/KTPWitness.amxx
```

No `KTP_TEST_MODE` flag needed — this plugin is itself the test-mode artifact.

## Production safety

This binary **must never** appear in any production server's `plugins.ini`.
The integration-test docker-compose setup will mount it into the test
container's plugins directory only. The `.amxx` lives under
`KTPInfrastructure/tests/integration/witness/compiled/` which is not a
production deploy path.

If the witness ever appears on a production host:
- Symptoms: `addons/ktpamx/logs/witness.jsonl` accumulates indefinitely
- Operational impact: minimal (each fire is a few-hundred-byte file append).
- Removal: `rm` the .amxx + remove from plugins.ini + `restart-all-servers.sh`

## See also

- `KTPInfrastructure/TEST_INFRASTRUCTURE_PLAN.md` § Tier 2 — full integration-test roadmap
- `KTPMatchHandler/CHANGELOG.md` 0.10.122 — test-mode build flag this depends on
- `KTPHLTVRecorder.sma` — production consumer example using the same forward-handler pattern
