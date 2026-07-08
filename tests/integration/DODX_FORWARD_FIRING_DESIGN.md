# DODX Forward-Firing Test — Design (Tier 2 wedge, 2026-05-04)

**Status (updated 2026-05-05):** **All phases (1, 2, 2b, 3, 3b, 4) shipped.**
KTPWitness 1.6.0 + DODX module (4 new `dodx_test_dispatch_*` natives) +
KTPMatchHandler 0.10.124 (test-mode `cmd_test_end_match` now calls
`dodx_flush_all_stats()`) cover all 10 forward-firing tests end-to-end —
all env-conditional, no decorator skips remaining. Production 3-module
set (`amxxcurl + reapi + dodx`) unchanged — the test natives extend the
existing DODX module rather than loading a new one (per operator policy
2026-05-05).

## What this is

DODX exposes 19 Pawn forwards that downstream KTP plugins hook to react to
in-game events:

| Forward | Trigger | Production consumers |
|---|---|---|
| `client_damage` | Player takes damage | KTPHLStatsX (kill/assist attribution) |
| `dod_damage_pre` | Pre-damage hook (return modified dmg) | KTPGrenadeDamage |
| `client_death` | Player killed | KTPHLStatsX, KTPMatchHandler |
| `client_score` | Player score changed | KTPScoreTracker |
| `dod_client_changeteam` | Team switch | KTPMatchHandler (.confirm flow) |
| `dod_client_changeclass` | Class switch | KTPMatchHandler (mid-match audit) |
| `dod_client_spawn` | Player spawn | KTPPracticeMode (grenade auto-refill) |
| `dod_client_scope` | Sniper scope toggle | (none currently) |
| `dod_client_weaponpickup` | Weapon pickup | KTPHLStatsX |
| `dod_client_prone` | Prone toggle | (none currently) |
| `dod_client_weaponswitch` | Active weapon change | (none currently) |
| `dod_grenade_explosion` | Grenade detonation | KTPPracticeMode (auto-refill) |
| `dod_rocket_explosion` | Rocket detonation | KTPPracticeMode (auto-refill) |
| `dod_client_objectpickup` | Flag/objective pickup | KTPMatchHandler (cap state) |
| `dod_client_stamina` | Stamina change | (none currently) |
| `dod_stats_flush` | HLStatsX stats flush trigger | KTPMatchHandler ↔ HLStatsX |
| `controlpoints_init` | Map-load CP discovery | KTPHLStatsX |
| `dod_control_point_captured` | Flag captured | KTPMatchHandler, KTPScoreTracker |
| `dod_score_event` | Verbose scoring tick | KTPScoreTracker |

## Why this test matters

These forwards have failed silently before — memory entry
`ktpamxx_2.7.13_dodx_fix_2026-04-23.md` documents one such incident:
DODX forwards stopped firing entirely under specific circumstances
(KTPAMXX 2.7.12 with FNullEnt mishandling on the world entity), and the
regression went unnoticed in production until manual investigation. Test
coverage on "forward X actually fires when event Y happens" is the
missing link.

Tier 2 spine (Session 2) already proves cross-plugin forward dispatch
works for `ktp_match_start` / `ktp_match_end` (KTPMatchHandler emits, a
witness plugin records the dispatch). The DODX forward-firing test
extends the same witness pattern down to engine-level forwards.

## Two design options surveyed

### Option 1 — Diagnostic cvar exposed by DODX-test-mode build

Add a `-DKTP_TEST_MODE` flag to KTPAMXX/dodx module. In test-mode build,
each forward dispatch increments a per-forward counter accessible via a
new `dodx_test_get_counter <forward_name>` rcon (or via cvar reads).

**Pros:**
- Pure DODX-side; no plugin extension needed
- Counters survive plugin restarts
- Direct (no log-tail latency)

**Cons:**
- Requires a custom KTPAMXX build path (test-mode binary distinct from
  production). Production deploys must NEVER load the test-mode build —
  same risk class as the existing test-mode KTPMatchHandler binary, which
  is already mitigated via `compiled/test/` separation.
- Adds maintenance overhead to a C++ module. Test code in C++ is harder
  to maintain than test code in Pawn/Python.
- Doesn't capture forward ARGUMENTS — only counts. Tests like "the
  damage forward fired with attacker=PLAYER1, dmg=50" need argument
  introspection, which counters can't give.

### Option 2 — Staging MySQL row written by witness plugin

Extend `KTPWitness.amxx` (already used by Session 2 spine tests) to hook
each DODX forward and write a row to a new `ktp_witness_dodx` MySQL
table on every dispatch. Tests query the table.

**Pros:**
- Pure Pawn extension; reuses existing witness infrastructure
- Captures full argument lists per dispatch
- MySQL row is durable across plugin reloads
- Existing witness.jsonl pattern (file-tail-based) extends similarly

**Cons:**
- MySQL write per forward dispatch in HOT paths (e.g. `client_damage`
  fires hundreds of times per minute on a busy server). Either need to
  toggle off in production (witness plugin already test-only, so this is
  fine) OR batch writes.
- Pawn ↔ MySQL via amxxcurl HTTP POST is the existing pattern, but a
  burst of forward dispatches at high cadence would overwhelm even
  amxxcurl's async queue. Need a bounded ring buffer.

### Option 3 (recommended) — Witness extension writing to JSONL (existing pattern)

Extend `KTPWitness.amxx` to hook each DODX forward and append a row to
the existing `addons/ktpamx/logs/witness.jsonl` file (no new MySQL
table). Tests poll witness.jsonl the same way Session 2 tests do for
`ktp_match_start`.

**Pros over Option 2:**
- Zero MySQL footprint. JSONL writes are a single `fputs` (no network).
- Reuses the EXACT polling pattern Session 2 spine tests use
  (`log_tail.wait_for_witness_event`).
- Witness plugin already confined to test-mode deploys; no production
  risk.

**Pros over Option 1:**
- No DODX C++ test-mode build needed
- Captures full argument lists via JSONL serialization
- Pure Pawn — easier to maintain alongside the rest of the test suite

**Cons:**
- File I/O per forward dispatch in hot paths. JSONL append is O(1) but
  on a fully-populated 12-player server `client_damage` could fire
  thousands of times per minute. **Mitigation:** witness's hooked
  forward set is opt-in via cvar (`witness_capture_forwards "damage,death,
  controlpoints_init"`) — operator narrows to the forwards a given test
  actually asserts on, all others stay no-op. Per-test session typically
  needs <5 forwards hooked.

**Recommendation:** Option 3. Smallest delta from existing
infrastructure, smallest production risk surface, best matches the test
pattern Session 2 already established.

## Phased rollout

### Phase 1: One forward, deterministic trigger ✅ SHIPPED 2026-05-05

`controlpoints_init` is now hooked in KTPWitness 1.1.0 and
`test_controlpoints_init_fires_on_map_load` is unblocked. Below describes
the design as shipped; subsequent phases inherit the same pattern.

Pick `controlpoints_init` as the first hook. Reasons:
- Fires exactly once per map load — deterministic, no flake potential
- No client/player interaction needed — tests can run with 0 connected
  clients on a freshly-booted hlds
- Already firing in production today (KTPHLStatsX is a consumer); a
  regression here would be high-impact

Test contract:
```python
def test_controlpoints_init_fires_on_map_load(hlds):
    """controlpoints_init forward fires exactly once when hlds loads a
    DoD map. KTPWitness records the dispatch; we assert via witness.jsonl.
    """
    sf = _serverfiles()
    if sf is None:
        pytest.skip("requires KTP_HLDS_SERVERFILES for witness.jsonl read")

    witness_baseline = witness_count(sf)
    hlds.rcon("changelevel dod_anzio")
    row = wait_for_witness_event(sf, "dod_controlpoints_init", timeout=30.0,
                                 after_count=witness_baseline)
    assert "cp_count" in row  # forward had no args, but witness adds map-context
```

Implementation work:
1. KTPWitness.amxx: add `register_forward FM_RegisterCvar` no — wait,
   DODX forwards register via `register_forward(FORWARD_*, "handler", post)`
   in production. Witness must do the same and write a JSONL line.
2. New witness JSONL schema: `{"forward": "dod_controlpoints_init",
   "ts_unix": ..., "args": {}}` with per-forward args-shape.
3. Compile + stage to test serverfiles tree.
4. Integration test as above.

### Phase 2: Player-interaction forwards ✅ SHIPPED 2026-05-05 (partial)

Four handlers landed in KTPWitness 1.2.0:

- `dod_client_spawn(id)` — args `{id}`
- `dod_client_changeteam(id, team, oldteam)` — args `{id, team, oldteam}`. Team values: 1=Allies, 2=Axis, 3=Spectators.
- `dod_client_changeclass(id, class, oldclass)` — args `{id, class, oldclass}`. Class IDs 1-6 per side; oldclass=0 on initial pick.
- `client_death(killer, victim, wpnindex, hitplace, TK)` — args `{killer, victim, wpnindex, hitplace, TK}`. Witness label: `dod_client_death` (forward name itself has no `dod_` prefix in dodx.inc; we add it for namespace clarity).

Driver path chosen: **bot pseudo-client via `addbot` rcon**. A single
`addbot` deterministically triggers a forward sequence — bot connects,
auto-joins a team, picks a class, spawns. The first three forwards (team /
class / spawn) all fire within ~10s of `addbot`. Tests assert occurrence +
structural shape per the design contract ("forward fires ≥N times in T
seconds with K bots").

Three tests now unblocked (env-conditional, will run when
`KTP_HLDS_SERVERFILES` is set):

- `test_dod_client_spawn_fires_on_bot_join`
- `test_dod_client_changeteam_fires_on_bot_join`
- `test_dod_client_changeclass_fires_on_bot_join`

**Phase 2b ✅ SHIPPED 2026-05-05** — kill-trigger rcon added directly to
the witness plugin (KTPWitness 1.2.0 → 1.3.0). The new `amx_witness_kill
<slot>` rcon validates the slot, calls `user_kill(slot, 0)`, and returns
PLUGIN_HANDLED. user_kill dispatches the death event → DODX raises
`client_death` → witness's existing 1.2.0 handler records the row.

Test sequence for `test_client_death_fires_on_kill`:

  1. `addbot` rcon → wait for `dod_client_spawn` row (proves bot is in-world).
  2. Capture the bot's slot from the spawn row's `args.id`.
  3. `amx_witness_kill <slot>` rcon → `user_kill` → `client_death` dispatch.
  4. Wait for `dod_client_death` row, assert shape + `args.victim` matches
     the killed bot slot.

Choice rationale (kill primitive in witness vs separate plugin / amxx_admin):

  - In-witness keeps the test surface in one source-controlled artifact —
    no separate "test admin tools" plugin to maintain.
  - `user_kill` is core AMXX (no new module load).
  - `register_concmd` is the same registration pattern KTPMatchHandler uses
    for its `-DKTP_TEST_MODE` rcons; proven extension-mode-safe.
  - Witness plugin is already test-only with strong production-safety
    docs; kill rcon inherits the same boundary.

Live-client option (real DoD client in a docker container) was surveyed
but rejected for Phase 2 — heavy infrastructure for a test surface where
bots cover 3 of 4 forwards cleanly. Revisit if a future phase needs
multiplayer interactions that bots can't drive.

Options surveyed (kept for record):
- **Live test client.** Spawn a real DoD client process inside a docker
  container, connect to the test hlds. Heavy but realistic. Aligns with
  Session 5's docker-compose plan.
- **Bot pseudo-client.** DoD's built-in bots (`addbot`) have limited
  AI but DO trigger spawn/team-change/class-change forwards. Cheapest
  path; chosen above. Constraint: bot AI is unpredictable so tests
  assert occurrence + shape, not exact values.

### Phase 3: Hot-path forwards ✅ HANDLERS SHIPPED 2026-05-05 (tests pending Phase 3b)

Four handlers landed in KTPWitness 1.4.0:

- `client_damage(attacker, victim, damage, wpnindex, hitplace, TA)` — args
  `{attacker, victim, damage, wpnindex, hitplace, TA}` (6 ints). Witness
  label `dod_client_damage`.
- `dod_grenade_explosion(id, Float:pos[3], wpnid)` — args
  `{id, pos: [x, y, z], wpnid}`. pos serialized with `%.2f` precision (DoD
  map limits ±16384 per axis; %.2f precision sufficient for spatial assertions).
- `client_score(id, score, total)` — args `{id, score, total}`. Witness
  label `dod_client_score`. score is the delta; total is the post-change
  running score.
- `dod_score_event(id, score_delta, total_score, cp_index)` — args
  `{id, score_delta, total_score, cp_index}`. cp_index is the CP that
  triggered the score, or -1 if not CP-related.

**(Historical — superseded by the header: as of KTPAMXX 2.7.19's dispatch
primitives + commit `674add1`, these run via synthetic dispatch, no decorator
skips remain.)** The original rationale, kept for context — `addbot` alone
doesn't reliably trigger any of them within test-suite timing:

- `client_damage` — bot AI may or may not engage in combat within 60s
- `dod_grenade_explosion` — DoD bots rarely throw grenades
- `client_score` — fires on frag credit, requires combat
- `dod_score_event` — same, plus requires CP capture for cp_index>=0

These fire at cadences (hundreds of rows per minute on a populated
production server) where occurrence + shape is the right contract per
the design's "≥N times in T seconds" rule. Tests for these forwards will
need either Phase 3b's deterministic dispatch primitive or a bot-stress
harness with flake-tolerant assertions.

#### Phase 3b ✅ SHIPPED 2026-05-05 — Deterministic dispatch via test-only DODX natives

Three new natives added to `modules/dod/dodx/NBase.cpp` + declarations in
`plugins/include/dodx.inc`:

```
dodx_test_dispatch_damage(attacker, victim, damage, wpnindex, hitplace, TA)
dodx_test_dispatch_grenade_explosion(id, Float:pos[3], wpnid)
dodx_test_dispatch_score(id, score_delta, total_score, cp_index)
    -> fires BOTH client_score AND dod_score_event in tandem,
       matching production dispatch pattern (moduleconfig.cpp:276-278).
```

Each native short-circuits if the relevant forward isn't registered
(`iFDamage < 0`, etc.) and otherwise calls `MF_ExecuteForward(...)`
directly — bypassing the engine usermsg chain but exercising the same
forward-dispatch primitive DODX uses for real engine events. They are
test-only by name + by intent; production plugins must not call them.

Production safety analysis (in `NBase.cpp` § "KTP TEST-ONLY: Forward
dispatch primitives") + safety rationale captured in `dodx.inc` doc
comments. Net behavioral change for production: zero — the natives don't
modify engine state and aren't called from any production plugin.

Witness wraps each native in an rcon (KTPWitness 1.5.0+):
- `amx_witness_dispatch_damage <attacker> <victim> <damage> <wpnindex> <hitplace> <TA>`
- `amx_witness_dispatch_grenade <slot> <x> <y> <z> <wpnid>`
- `amx_witness_dispatch_score <id> <score_delta> <total> <cp_index>`

Tests assert exact value round-trip (deterministic dispatch means the
witness records exactly the values the test passed in via rcon).

Test coverage gain: 4 Phase 3 forwards now exercise the
DODX-side `MF_ExecuteForward` chain end-to-end. The engine→DODX dispatch
chain (engine usermsg/entity-event → DODX hook → `MF_ExecuteForward`) is
still covered separately by Phase 1's `controlpoints_init` (engine-driven
on map change) and Phase 4's `dod_stats_flush` (engine-driven via
KTPMatchHandler's `dodx_flush_all_stats()`).

Test environment requirements:
1. Built `dodx_ktp_i386.so` (sha varies — current `790edc37...`)
2. KTPWitness 1.5.0+ staged in test serverfiles plugins/

Operator deployment note: production fleet redeploy of `dodx_ktp_i386.so`
is **optional** — these natives don't run unless called, and no
production plugin calls them. The test environment needs the new
binary; production fleet can stay on the prior dodx until a separate
redeploy event happens.

### Phase 4: Match-flow-coupled forwards ✅ SHIPPED 2026-05-05

`dod_stats_flush(id)` and `dod_control_point_captured(cp_index, new_owner,
old_owner)` — both engine-driven in production:

- `dod_stats_flush` fires when KTPMatchHandler calls
  `dodx_flush_all_stats()` (CLAUDE.md "Match Flow" — at half/match end).
  KTPMatchHandler 0.10.124 added the call to test-mode `cmd_test_end_match`,
  so `test_dod_stats_flush_fires_on_match_end` drives the FULL match-flow
  chain: addbot → setup_match → advance_pending → advance_live → end_match
  → dodx_flush_all_stats → dod_stats_flush forward → witness row.

- `dod_control_point_captured` fires from DoD's flag-cap usermsg path
  (production: dispatched at `usermsg.cpp:643-644`). Engine timing for
  flag-cap is non-deterministic for a test suite (bot AI capture timing
  is highly variable), so Phase 4 uses the same Phase 3b dispatch
  primitive pattern: `dodx_test_dispatch_cp_captured(cp_index, new_owner,
  old_owner)` test-only native (added to NBase.cpp), wrapped by KTPWitness
  1.6.0's `amx_witness_dispatch_cp_captured` rcon. Real engine flag-cap
  coverage is provided by manual matchday testing.

Tests added in Phase 4:
- `test_dod_stats_flush_fires_on_match_end` — full match-flow drive
- `test_dod_control_point_captured_via_dispatch` — Phase 4b primitive

KTPWitness 1.6.0 adds `public dod_stats_flush` and `public
dod_control_point_captured` handlers, plus the
`amx_witness_dispatch_cp_captured` rcon.

## Open questions

1. **Where does the witness JSONL extension's source live?**
   `KTPInfrastructure/tests/integration/witness/` (alongside
   KTPWitness.amxx) — same directory as the existing match-flow witness.
   Single .sma, registers all DODX hooks behind a `witness_capture_forwards`
   cvar.

2. **Does the witness plugin compile against extension mode?**
   `register_forward` is provided by AMXX core (not DODX module), so
   yes. KTPWitness's existing match-flow hooks already work in extension
   mode. Phase 1 forward (`controlpoints_init`) is registered the same way.

3. **What's the JSONL row shape?**
   `{"forward": "<name>", "ts_unix": <int>, "args": {<per-forward-shape>}}`.
   Each forward's args dict shape is documented in dodx.inc; mirror
   that in the witness handler. e.g.,
   - `dod_grenade_explosion(id, pos[3], wpnid)` →
     `{"forward": "dod_grenade_explosion", "ts_unix": ..., "args": {"id": 5, "pos": [123.0, 456.0, 78.9], "wpnid": 12}}`

4. **Argument validation in tests.** Tests assert specific arg values
   when the trigger is deterministic (controlpoints_init has no args;
   client_death has killer/victim/wpn). Bot-driven hot-path tests assert
   only structural shape (all keys present, types right). Live-client
   tests assert exact values when the test driver controls the client.

5. **Rate-limit witness output.** If a hot forward fires faster than
   `fputs` flush, the witness file could become a write hotspot. Add
   a per-forward rate-limit cvar (`witness_max_per_sec_per_forward 100`)
   that drops on overflow; tests that need exhaustive coverage can bump it.

6. **Build artifact split.** KTPWitness.amxx is already test-only; the
   DODX-extended witness becomes a single artifact (no separate build for
   match-flow vs DODX hooks). Production builds NEVER ship this plugin.

## Cross-references

- `KTPInfrastructure/tests/integration/witness/` — existing
  KTPWitness.amxx source + compile.sh
- Memory `ktpamxx_2.7.13_dodx_fix_2026-04-23.md` — silent-stall incident
  motivating this test
- Memory `extension_mode_no_fakemeta.md` — why we can't use
  `CreateFakeClient` for synthetic clients
- `KTPAMXX/plugins/include/dodx.inc` — full DODX forward inventory
  (lines 41-552)
- `KTPInfrastructure/tests/integration/test_match_flow_spine.py` —
  existing witness-based forward-fire test for `ktp_match_start`
  (the pattern this work extends)

## Effort estimate

| Phase | Estimate | Wedge value |
|---|---|---|
| Witness extension code (Phase 1 hooks for `controlpoints_init`) | 2-3h | high — proves the pattern |
| Phase 1 test (one assertion) | 1h | medium |
| Phase 2 player-interaction (4 forwards + bot driver) | 4-5h | high — covers ~25% of forward set |
| Phase 3 hot-path (3 forwards + rate-limit) | 3-4h | medium — diminishing returns |
| Phase 4 match-flow-coupled (2 forwards) | 2-3h | medium — completes the surface |

**Total ~12-15h** to cover the high-value subset. Original TODO estimate
was 15-20h for full coverage; this design narrows that.

This commit lands ONLY the design doc + a placeholder test (skip-with-
reason pointing here). Phase 1 implementation is the next session's work.
