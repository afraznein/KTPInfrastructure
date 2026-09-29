# Schema 26: shot-row `hitgroup` and the per-shot rewind record

Status: **design only, no code.** Build work is tracked in the coordination repo under
`infra-stat-capture` (box "schema 26: hitgroup + per-shot rewind"). Nothing here ships
until schema 25 is verified live on the daemon and the fleet: stats_logging 1.26.x on 24/24,
schema-25 manifests accepted, `ktp_score_events.round_time_left` populated. One undeployed
schema bump is never stacked on another.

All code references were read from `origin/main` on 2026-09-29:
KTP-ReHLDS `d9880f6`, KTPAMXX `84190c3dd`, KTPHLStatsX `ae30057`, KTPInfrastructure `13d68b4`.

**Why this file lives here.** `docs/handover/` is where this repo keeps cross-repo capture
contracts (`TELEMETRY_SCHEMA22_PREPROD_PROMOTION.md`, `STATS_SCHEMA_AUDIT.md`,
`SPIKE_ENTVAR_GEOMETRY.md`). Schema 26 touches all four repos, and this is the only public repo
they share. The earlier expansion plan (`ENGINE_STATS_EXPANSION_PLAN_20260909.md`) lives outside
any repo, and a public design cannot point readers at a private coordination file.

---

## 1. What schema 26 adds, and why the two items ship together

| item | what the shot row gains | why it waited |
|---|---|---|
| hitgroup | the studio hitgroup the shot's trace resolved on | The wave-0 shot stream left it out on purpose. The value lived only in the geometry stash, and that stash has one destructive reader, the AC ledger's `dodx_get_shot_geom`. See the "No target/hitgroup field" note above `ksc_emit_shot` in `plugins/dod/ktp_stats_capture.inc`. It was deferred, not dropped. |
| per-shot rewind | how far lag compensation actually rewound for this shot, how far it wanted to go, and whether the `sv_maxunlag` ceiling clamped it | The engine only reports 10 s window aggregates, and those cannot answer the 0.3 s vs 0.5 s question (§6). |

Both items widen the same shot line and the same table, and both touch dodx's shot stash, so they
share one wire change, one migration, one daemon release and one producer release. That is one
deploy cycle instead of two.

---

## 2. Fields

All four are new nullable columns on `ktp_shot_events`. On the wire they are new `%d` properties
appended to the end of the `triggered "shot"` line. Wire and column names match, as they already
do for `shot_ping`, `net_lerp` and the others.

| column | type | unit | producer sentinel | NULL means |
|---|---|---|---|---|
| `hitgroup` | `TINYINT UNSIGNED` | studio hitgroup (0 generic, 1 head, 2 chest, 3 stomach, 4–7 limbs, as the game DLL assigns them) | `-1` | the shot has no target state (it missed, the stash belonged to another dispatch, or the weapon is not a hitscan firearm), the value was outside 0–99, or the producer predates schema 26 |
| `rw_flags` | `TINYINT UNSIGNED` | bitfield, below | `-1` | no rewind record belongs to this shot's usercmd: a bot shooter, an engine without the rewind API, a module without the native, or a producer before schema 26 |
| `rw_depth` | `SMALLINT UNSIGNED` | ms, `realtime - targettime` as `SV_SetupMove` computed it (after the `sv_maxunlag` clamp) | `-1` | `rw_flags` is NULL, or bit0 is clear (lag compensation was not attempted, so there is no target time) |
| `rw_want` | `SMALLINT UNSIGNED` | ms, the same arithmetic run on the **pre-clamp** latency | `-1` | same as `rw_depth` |

`rw_flags` bits:

| bit | name | set when |
|---|---|---|
| 0 | `attempted` | every lag-compensation gate passed: `pfnAllowLagCompensation`, `sv_unlag`, `cl_lw`, `cl_lc`, `maxclients > 1`, client active |
| 1 | `reached` | the frame history reached the target time and positions moved. Clear with bit0 set means a **rewind miss**: the shot was judged against present-time positions. |
| 2 | `clamped` | pre-clamp latency `>= sv_maxunlag`. The engine uses `>=`, so a shot exactly at the ceiling counts as clamped with 0 ms excess, the same as `maxunlag_hits`. |
| 3 | `hardcap` | the raw latency estimate exceeded the engine's fixed 1.5 s cap, so `rw_want` is a floor rather than the true figure |
| 4 | `pushed` | the target time was clamped to `realtime` (`sv_unlagpush`), so the depth is 0 by construction |
| 5 | `estimator` | `sv_unlag_estimator` was on for this packet (see §7) |
| 6 | `interp_adjusted` | the interp term was capped at 0.1 s or floored at `next_messageinterval` |

Derived values, so nothing redundant goes on the wire:

- **applied depth** = `bit1 ? rw_depth : 0`. On a rewind miss nothing moved, whatever the target was.
- **clamp excess** = `rw_want - rw_depth` when bit2 is set, otherwise 0. The interp and push terms
  are identical in both figures, so the difference is exactly the latency the ceiling removed.
- **would a candidate ceiling C have served the shot?** Yes when `excess < C - sv_maxunlag`, which
  at today's 0.3 s means `excess < 200 ms` for C = 0.5 s. This needs the `sv_maxunlag` in force on
  that instance on that date. Open question 3 asks whether to carry it per half.

**NULL semantics, all four columns.** A schema 21–25 row has none of these properties and the
daemon stores NULL, the same absent-to-NULL rule it already applies to `round_time_left` and the
wave-1 fields. A producer sentinel (`-1`) is stored as NULL, never as data. 0 is always a real
value (hitgroup 0 is "generic", depth 0 is "not rewound"). Presence keys:

- `hitgroup` is gated on `$has_target` (`tgt_dead` in {0,1}), exactly like the rest of the target
  group, because it is stamped in the same first-wins window.
- `rw_*` get their own key, `$has_rw`: `rw_flags` is an integer 0–127. They cannot share
  `$has_target`, because a miss has no target state but does have a rewind record, and misses are
  half of what §6 needs. `rw_depth` and `rw_want` are additionally NULL unless bit0 is set.

---

## 3. Producers, layer by layer

### 3.1 Where the values exist today

**Hitgroup.** `KTPCaptureShotGeom` (KTPAMXX `modules/dod/dodx/moduleconfig.cpp`) runs from dodx's
`PF_TraceLine` post-hook when a player's trace hits a player. It already writes
`sg.hitgroup = ptr->iHitgroup`, but into the **geometry** stash, which `dodx_get_shot_geom`
consumes for KTPMatchHandler. The **target** stash that stats_logging reads through
`dodx_get_shot_target2` is filled a few lines later in the same function, in the same first-wins
window, and does not carry it. ReHLDS already traces real studio hitboxes, so the value comes
free. No engine work is needed for this item.

**Rewind.** KTP-ReHLDS `rehlds/engine/sv_user.cpp`:

- `SV_ParseMove` calls `SV_SetupMove` **once per packet**, runs every usercmd in that packet
  (replayed `lastcmd`s for dropped commands included), then calls `SV_RestoreMove`. Every trace
  fired by any cmd in the packet runs against the one rewind that `SV_SetupMove` set up.
- In `SV_SetupMove`, `ktp_latency_preclamp` (after the 1.5 s cap, before `sv_maxunlag`) already
  exists for the shadow ceiling. So do the clamp decision, `cl_interptime` with its
  capped/floored flags, `targettime`, and the miss exits (`i >= SV_UPDATE_BACKUP`,
  `targettime - senttime > 1.0`).
- Nothing records any of this per shot. The `KTP_Rewind*` and `g_ktp_net_*` accumulators are
  per-interval aggregates behind `g_ktp_profiling_enabled`, emitted as `[KTP_PROFILE] net:` and
  `rewind:` to the profile aggregator, not to the stats pipeline.

### 3.2 Engine (KTP-ReHLDS)

- Keep one **current-rewind record**: owner slot, packet `incoming_sequence`, open/closed, the
  flag bits, depth, want. `SV_SetupMove` writes it on **every** exit, including the early
  not-attempted returns and both miss exits, and marks it open. `SV_RestoreMove` marks it closed,
  including on its `nofind` early return. A fakeclient never reaches `SV_SetupMove`
  (`SV_ParseMove` skips it), so a bot's cmds always find the record closed or owned by someone
  else. The honest answer for a bot is "no rewind record", and that is what it gets.
- The write is **unconditional**, not behind `g_ktp_profiling_enabled`. It must not depend on a
  profiling toggle, and it costs a handful of stores per packet on values the function has already
  computed. At fleet packet rates that is noise on the 1 ms grid. No new arithmetic runs on the
  frame path.
- Expose it through a **named plugin API**, `ktp_rewind_v1`, which the engine registers with its
  own `Rehlds_RegisterPluginApi` at API init, before any extension attaches. The interface struct
  goes in a **new** header, `rehlds/public/rehlds/ktp_rewind_api.h`: a leading `size` field and one
  function, `bool GetCurrent(int slot, ktp_rewind_sample_t *out)`, which returns false unless the
  record is open and owned by `slot`.
- `rehlds_api.h` is **not touched**: no vtable slot, no `RehldsFuncs_t` entry, no
  `REHLDS_API_VERSION_MINOR` bump. §4 explains why that matters.
- The name is the version. A layout change is registered as `ktp_rewind_v2`, never as an in-place
  edit to v1. This is the same rule dodx follows for natives ("a new field group gets a NEW native
  name").

### 3.3 Module (KTPAMXX dodx)

- Resolve the API lazily: `GetPluginApi("ktp_rewind_v1")` through the ReHLDS funcs table, cached
  on first successful lookup and re-tried at server activate. `GetPluginApi` is mid-struct in the
  bundled prefix copy of `rehlds_api.h`, so dodx can reach it today without a header change.
  NULL (an older engine) leaves every rewind read at `-1`.
- **Rewind stash**: a new, independent seq/consume pair in `KTPShotGeom` (`rwSeq`, flags, depth,
  want), stamped in the PreThink hook body right after `cmdSeq++`. That runs inside `SV_RunCmd`,
  inside the packet's `SV_SetupMove`/`SV_RestoreMove` window, so the record `GetCurrent` returns
  is the one this cmd's traces run against. It is stamped for **every** cmd, not only
  player-hitting traces, because misses need it (§6).
  - Why not stamp at trace time? The capture hook only fires on traces that hit a player, so a
    miss would carry no record, and that biases the clamp analysis toward hits.
  - Why not read at emit time? The fire forward runs one cmd later (the ordering note at the top
    of `KTPShotGeom.h`), possibly in the next packet, after a different `SV_SetupMove`. Reading
    there would attribute the next packet's rewind to this shot.
- **Target stash**: add `tgtHitgroup`, stamped next to `tgtEntIndex` in `KTPCaptureShotGeom`.
  Values outside 0–99 are stored as `-1`, which keeps the wire bound provable without inventing a
  hitgroup.
- **Natives**, each under a new name, never a widened array (the `dodx_get_shot_target` block
  comment explains the skewed module/plugin corruption this rule prevents):
  - `dodx_get_shot_target3(id, weapon, target[22])` returns target2's 21 cells in the same order,
    plus `[21] = hitgroup`. `dodx_get_shot_target2` stays, byte-identical, for older plugins.
  - `dodx_get_shot_rewind(id, rw[3])` returns `{ flags, depth_ms, want_ms }`, 1 when a sample
    belongs to the calling cmd (`rwSeq == cmdSeq`) and 0 otherwise. It has the same destructive,
    cmd-paired read discipline as its siblings and needs no weapon argument, because the record
    belongs to the cmd, not to a weapon.
- Clamps at the capture site: depth and want to 0–9999 ms (the real maximum is about 1.6 s: the
  1.5 s cap plus 0.1 s of interp), flags to 7 bits.

### 3.4 Plugin (KTPAMXX stats_logging, 1.27.0, `KSC_SCHEMA_CONTRACT 26`)

- `ksc_emit_shot` switches to `dodx_get_shot_target3`, declared as `target[22]`, and adds a
  `dodx_get_shot_rewind` read under the same `ksc_shot_detail_enabled()` gate. The rewind read is
  **not** under the hitscan-firearm gate that guards target state, since every cmd has a rewind.
  Analysis filters on `weapon_id` instead.
- Four properties appended: `(hitgroup "%d") (rw_flags "%d") (rw_depth "%d") (rw_want "%d")`,
  with `-1` when unpopulated.
- The plugin references two natives an older dodx lacks, so a new plugin on an old module
  **fails to load**. That is the intended loud failure, and it is why the module ships no later
  than the plugin (§5).

### 3.5 Daemon (KTPHLStatsX `hlstats.pl`)

- `ktpValidateCaptureManifestPayload`: accept `26`. Required capabilities are unchanged; no stream
  is added.
- The shot event branch passes the four new properties, and the shot row builder writes them with
  the presence keys from §2. An absent property is NULL (schema 21–25 producers). A `-1` is NULL.
  A `rw_flags` outside 0–127, or a non-integer, is NULL for the whole rw group.
- The batch INSERT names the four columns, so **the migration must be applied before this daemon
  runs**, or every shot batch fails and the queue is discarded.

### 3.6 Storage (KTPHLStatsX `sql/migrate_040_shot_hitgroup_rewind.sql`)

- Four `ADD COLUMN ... DEFAULT NULL` with `COMMENT`s carrying the unit and the NULL meaning,
  guarded per column through `information_schema`. It is idempotent, the same shape as
  migrations 032/039.
- 040 is the next free ordinal at the time of writing. Take whichever is free at implementation
  time; nothing here reserves it.
- No index. The analyses in §6 scan by `match_id`/time, which the existing keys already serve.

---

## 4. Options considered for getting the rewind to dodx

| option | attribution | cost | ABI / deploy coupling | verdict |
|---|---|---|---|---|
| **A. Engine keeps a current-rewind record, exposed through the named plugin API `ktp_rewind_v1`; dodx stamps it per cmd** | exact: the record read in the cmd's PreThink is the one its traces ran against, replayed cmds included | a few stores per packet (engine), one indirect call and a 12-byte copy per cmd (dodx) | none on `rehlds_api.h`; the engine and dodx deploy in either order, and a missing API degrades to NULL | **recommended** |
| B. New `IRehldsHookchains` entry (post-`SV_SetupMove` hook) | exact, if the hook signature carries the clamp internals | a hookchain dispatch per packet | vtable append, `REHLDS_API_VERSION_MINOR` 16 → 17 in three header copies, the prefix gate from KTP-ReHLDS#27 edited. And dodx's attach gate **refuses to register any hook** when the engine's minor is below its header's, so a dodx built against 17 on a 16 engine loses every stat, not just this one. That forces a lockstep engine+core+reapi+dodx wave. | rejected: deploy coupling far out of proportion to four fields |
| C. Append a `GetClientRewind` to `RehldsFuncs_t` | exact | same as A | struct-offset append with the same minor bump and the same all-or-nothing dodx gate as B | rejected for the same reason |
| D. Engine emits its own per-shot log line, joined to the shot row by slot and time | inferred: the engine rewinds per **packet** and does not know which packet held a shot, so the join is a nearest-timestamp guess, the attribution weakness the dodx stash design exists to remove | one line per packet per player at ~100 packets/s: an order of magnitude more log volume than the shot stream itself | goes to the profile aggregator, not the stats pipeline, so it needs a second ingest path | rejected |
| E. dodx recomputes the rewind from `client_t` (latency, lerp, `sv_maxunlag`) | approximate | cheap | none | rejected: a copy of the engine's arithmetic is a second opinion, not a measurement. It cannot see the miss exits or the frame history, and it drifts the first time the engine function changes (the estimator already did once). |
| F. Stamp at trace time only (in `KTPCaptureShotGeom`) | exact for hits | cheapest | as A | rejected as the **only** stamp: misses would carry nothing, which biases every clamp-vs-hit comparison. Hitgroup is stamped there, rewind per cmd. |

---

## 5. Deploy order

Merge order, as for every capture change: **harness → daemon → producer.** The harness must
register migration 040 before daemon Lane B sees a daemon ref that carries it.

Deploy order:

1. **Prerequisite:** schema 25 verified live, as in the status line at the top.
2. **Migration 040** applied to prod (root migration queue, recorded in `APPLIED.md`). Schema ahead
   of code is inert.
3. **Daemon accepting 26** deployed, and a schema-25 half confirmed to still ingest cleanly.
   🔴 **The daemon has to go before any schema-26 producer.** `ktpValidateCaptureManifestPayload`
   refuses an unknown schema, and a refused manifest de-authorises **every** gated stream for that
   half, not just the shot stream. A plugin ahead of the daemon loses the whole half's capture
   silently.
4. **Engine** (KTP-ReHLDS with `ktp_rewind_v1`). This step is independent of 2 and 3: nothing
   reads the API until step 5 ships, and dodx treats a missing API as NULL. It goes through the
   engine's own release checklist and the 03:00 ET swap.
5. **dodx module** (`target3`, `rewind` natives). It must land **no later than** the plugin; the
   same nightly swap is fine, since both `.new` files activate together.
6. **stats_logging 1.27.0** (schema 26), last.

If the engine lags steps 5–6, schema-26 rows carry `rw_*` NULL and hitgroup is still populated.
That is harmless, and it is visible: `rw_flags IS NULL` on human rows.

Before step 6, KTPInfrastructure must already accept 26 (§8), or schema-26 halves fall out of
analytics.

---

## 6. The ruling this enables: 0.3 s vs 0.5 s `sv_maxunlag`

**Why the window aggregates cannot answer it** (fleet measurement, 2026-09-14):
`shadow_hits == maxunlag_hits` by construction (both count exactly the shots the 0.3 s clamp
caught), and `shadow_worst_ms = min(excess over 300 ms, 200)` saturated at 200 in about 40 % of
clamped windows. So the table cannot say how many *shots* 0.5 s would still clamp, and it cannot
say anything about hits at all.

With per-shot rows, restricted to human shooters, hitscan firearms and `bit0` set:

1. **Incidence.** Share of shots with `bit2`, per match and per shooter. This also shows
   concentration: is the clamp a fleet-wide effect, or a few high-latency connections?
2. **What 0.5 s would change.** Among clamped shots, the distribution of clamp excess.
   `excess < 200 ms` would be fully served at 0.5 s. `excess >= 200 ms` would still be clamped,
   by `excess - 200`. `bit3` marks shots where even the want is a floor. This is the number the
   saturating `shadow_worst` could not give.
3. **Does the clamp cost hits?** "Hit" means the shot's trace resolved on an enemy's hitbox
   (target state present, `tgt_team != shooter_team`). `hitgroup` adds a head-share view on the
   same rows.
   - Compare within-shooter hit share on clamped vs unclamped shots, never pooled across shooters,
     because shooters differ in skill far more than any rewind effect.
   - The cleaner cut is **at the ceiling itself**: shots whose pre-clamp latency sits just under
     300 ms (fully served) against shots just over it (clamped by a few ms). Pre-clamp latency is
     `rw_want - (rw_depth - 300)` on clamped shots and the served latency on unclamped ones.
     Latency changes smoothly across that line, and the rewind does not. If hit share is
     continuous across it, small clamps are not costing hits. A step down means they are.
4. **What 0.5 s would cost the victim.** Every shot with `0 < excess < 200` is a shot that 0.5 s
   would rewind 300–500 ms deep: the "shot behind cover" exposure. Count those per victim and per
   match. The ruling then weighs hits recovered for the shooter (3) against deep-rewind exposures
   for the target (4), and the operator makes it.

⚠️ Caveats the analysis has to carry:

- **The data must span competitive play.** Practice and official populations differ (the 2026-09-14 hit-registration
  re-run measured them apart).
- **Pin `sv_maxunlag` per instance and date** from config history before deriving excess.
- **A rewind miss (`bit0` and not `bit1`)** is a separate population: judged at present time,
  whatever the ceiling.
- **Lane B cannot exercise any of this** (§8): bots never produce a rewind record. The first
  evidence is the first human half on the canary.

The ruling itself stays deferred. Keep 0.3 s until this data answers it. This bump builds the
instrument, not the decision.

---

## 7. Estimator interplay (`sv_unlag_estimator`)

On an instance with the estimator on, `SV_CalcClientTime` returns the steadied estimate (median of
five, slew-limited), and `SV_SetupMove` rewinds by **that**. So `rw_depth`, `rw_want` and `bit2`
there describe the rewind *input* the estimator produced, not the shooter's raw round trip. A
smoother estimate clamps less often simply because it spikes less.

Consequences:

- **The per-shot rewind fields are not an A/B comparison metric across the two arms.** A lower
  clamp rate or a shallower depth on the estimator arm is a property of the estimator, not a
  result. The A/B judges by within-shooter hit share only, as the engine docs already say for
  `latzero` / `latency_worst` / `jitter_worst`.
- `bit5` marks estimator shots per row, so the 0.3/0.5 analysis in §6 either runs on
  estimator-off shots only or stratifies by `bit5`. It never pools the two, and it never needs a
  join to config history to tell them apart.
- Within one arm, the §6 method is valid: the ceiling acts on whatever latency that arm produced.

---

## 8. Analytics, Lane B and tests

**KTPInfrastructure (harness; merges first):**

- `scripts/match_analytics.py`: add 26 to `CAPTURE_SCHEMAS` and `POSITION_PROVENANCE_SCHEMAS`.
  `match_readiness.py` imports the former. Without this, schema-26 halves are silently excluded
  from analytics and readiness.
- `tests/e2e_stats/artifacts.py` and `tests/e2e_stats/test_artifacts.py`: register
  `sql/migrate_040_*` in apply order.
- Lane B: a new `check_shot_hitgroup_and_rewind` modelled on `check_hit_registration`, which
  checks plumbing only, never a rate:
  - Probe `information_schema` for the table **and** columns first. The daemon corpus lane replays
    a hardcoded schema list, and an unconditional column reference broke Lane B before.
  - On bot halves, `hitgroup` is non-NULL wherever `tgt_dead` is non-NULL and is NULL wherever it
    is NULL.
  - `rw_flags`, `rw_depth` and `rw_want` are NULL on **every** bot row. That is the negative
    control: bots never pass through `SV_SetupMove`, so a non-NULL value there would be fabricated.
  - The manifest reads schema 26, and emitted == received == accepted on the shot stream.
  - No assertion on depth, clamp or hit share. That would be a physics claim on a bot lane.

**KTPHLStatsX:**

- Selftests: manifest 26 accepted and 27 refused; a schema-25 shot line stores NULL in all four;
  a schema-26 line with `rw_flags -1` stores the rw group NULL; bit0 clear stores depth and want
  NULL; out-of-range `rw_flags` stores the group NULL; a miss (target `-1`) keeps a populated rw
  group.
- Migration 040 applied twice is a `DO 0` the second time.

**KTPAMXX:**

- `test_shot_wire_line_fits_shot_buffer`: add the four `int_literal` bounds (`hitgroup` 99,
  `rw_flags` 127, `rw_depth`/`rw_want` 9999). They are provable from the capture-site clamps.
- Contract tests: `target3` is `target2` plus one cell; `dodx.inc` declares `target[22]`; the
  plugin never calls a widened `target2`.
- Build against the real `amxxpc`. A green corpus lane does not compile the plugin.

**KTP-ReHLDS:**

- Unit tests beside the existing lag-comp tests:
  - every `SV_SetupMove` exit writes the record;
  - `SV_RestoreMove` closes it on both paths;
  - `GetCurrent` refuses a closed record and a foreign slot;
  - clamp, hardcap, push and interp bits match the inputs that set them;
  - `want == depth` whenever `bit2` is clear.
- Header drift: `ktp_rewind_api.h` gets a byte-mirror check into KTPAMXX, like the ReAPI copy of
  `rehlds_api.h`.

---

## 9. Wire budget: a claim this bump has to state

The shot line is bounded by ReHLDS's `Log_Printf` (a 1024-byte buffer minus the timestamp
prefix), which is why the test's ceiling is 970, not by the plugin's 960-byte ring. Measured with
the test's own derivation against today's format string:

| wire | worst case | vs 970 |
|---|---:|---:|
| today (schema 25) | 878 | 92 free |
| + `hitgroup` only | 894 | 76 free |
| **+ schema 26 as designed (4 fields)** | **946** | **24 free** |
| + a fifth field, raw latency | 962 | 8 free |
| schema 26 + the zero-spread counterfactual (`spread_x`/`spread_y`/`spread_class`, 57 B) | 1004 | **34 over** |

The 92 B freed by schema 25 is already claimed in writing by the zero-spread counterfactual
(`infra-shot-attribution`; the `KSC_SHOT_BUF_LINE_LEN` comment says anything spending it first
"should say so"). **This design says so: schema 26 spends 68 of those 92 bytes.** Both cannot
land as written. Ways to reconcile them, for the owners of both lanes to choose (open question 1):

- Retire `trace_start_off` (0 on every stored sample, already recorded as a dead end, 26 B), and
  give `yaw`/`pitch` a provable producer-side clamp so the test can bound them tighter (about
  14 B). Together that is about 964 B with both bumps landed.
- Reshaping schema 26 does not help: shipping clamp excess instead of `rw_want` costs the same
  4-digit bound. The lever is retiring dead fields, not renaming live ones.

The raw-latency field is left out on purpose. `bit3` already says when the want is a floor, and
that field is the 16 B the budget cannot spare.

---

## 10. Open questions for the operator

1. **Wire budget against the zero-spread counterfactual** (§9). Retire `trace_start_off` and
   tighten `yaw`/`pitch` as part of 26, or as part of the counterfactual's own bump? The
   recommendation is inside 26: it is the bump that spends the bytes.
2. **Ordinal.** The counterfactual lane planned "its own bump" after 25. This design takes 26. Is
   that the intended sequence, with the counterfactual at 27?
3. **`sv_maxunlag` per half.** Should the manifest carry the ceiling in force (stats_logging can
   read the cvar), so §6 needs no config-history join? That is one more manifest field, and it
   changes no stream.
4. **Estimator bit.** Is `bit5` wanted, or will estimator arms always be identified from instance
   config? It costs nothing on the wire, since the flags literal is 3 digits either way.
