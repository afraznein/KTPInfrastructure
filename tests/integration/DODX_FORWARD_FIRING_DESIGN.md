# DODX Forward-Firing Test — Design (Tier 2 wedge, 2026-05-04)

**Status:** Design phase. One stub test landed alongside this doc
(`test_dodx_forward_firing.py`); execution awaits witness extension +
DODX-test-mode build flag work spec'd below.

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

### Phase 1: One forward, deterministic trigger

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

### Phase 2: Player-interaction forwards

Hook `client_death`, `dod_client_spawn`, `dod_client_changeteam`,
`dod_client_changeclass`. These need synthetic clients — BUT we cannot
use fakemeta (`CreateFakeClient`) per memory `extension_mode_no_fakemeta.md`.

Options:
- **Live test client.** Spawn a real DoD client process inside a docker
  container, connect to the test hlds. Heavy but realistic. Aligns with
  Session 5's docker-compose plan.
- **Bot pseudo-client.** DoD's built-in bots (`addbot`) have limited
  AI but DO trigger spawn/death/team-change forwards. Probably the
  cheapest path. Constraint: bot AI is unpredictable so test can't
  assert exact counts; instead asserts "forward fires ≥N times in T
  seconds with K bots".

### Phase 3: Hot-path forwards

`client_damage`, `dod_grenade_explosion`, `dod_score_event`. These fire
at cadences where witness.jsonl will produce hundreds of lines per
minute. Tests assert *occurrence + shape* not exact counts; rate-test
the witness path itself for I/O regression.

### Phase 4: Match-flow-coupled forwards

`dod_control_point_captured`, `dod_stats_flush`. These tie back to the
match-flow state machine — trigger via `amx_ktp_test_*` rcons (already
exposed for the spine tests) and assert both the state-machine
transition AND the DODX forward dispatch land.

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
