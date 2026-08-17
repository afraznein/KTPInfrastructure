# Spike: prove `get_entvar` on DoD

**For:** whoever starts `KTPR_SPATIAL_PLAN.md`. This is step S0 and it gates the rest.
**Size:** hours, not days.
**Outcome:** a yes/no that decides whether spatial KTPR needs a C++ change.

---

## Why this exists

The spatial plan rests on reading capture-zone geometry without touching C++:

```
ent = dodx_area_get_data(i, CA_edict)
get_entvar(ent, var_absmin, mins)
get_entvar(ent, var_absmax, maxs)
```

Everything in the chain is verified **in source**:

| Fact | Cite |
|---|---|
| `CA_edict` returns a real Pawn-usable entity index, not an opaque handle | `modules/dod/dodx/NCP.cpp:283-284` — `return ENTINDEX_SAFE(mObjects.obj[index].pAreaEdict)` |
| The `dod_capture_area` edict is located by `target`→`targetname` then classname match | `modules/dod/dodx/dodx.h:419-432` (`GET_CAPTURE_AREA`) |
| ReAPI is loaded on the fleet — first module, all three configs | `KTPInfrastructure/config/{online,lan,local}/modules.ini` |
| `get_entvar` is registered **unconditionally**; only `ReGameVars_Natives` is stubbed without ReGameDLL | `branches/KTP-ReAPI/reapi/src/natives/natives_members.cpp:923-930`; `EngineVars_Natives` at `:880-898` |
| It reads only `edict_t::v` — no mod, no gamerules | `natives_members.cpp:352-406` |
| Offsets are `offsetof`-derived at compile time, not hand-guessed | `reapi/src/member_list.cpp:17` (`STRUCT_MEMBERS`) |
| `var_absmin` / `var_absmax` / `var_mins` / `var_maxs` exist on both sides of the ABI | module: `member_list.cpp:531-534`; plugin: `plugins/include/reapi_engine_const.inc:446, :454, :462, :470` |
| Extension mode is explicitly handled — engfuncs/gpGlobals pulled from KTPAMXX before `api_cfg.Init()` | `reapi/src/main.cpp:21-57` (`#ifdef REAPI_NO_METAMOD`) |

**The gap: zero in-tree plugins call `get_entvar` on DoD.** A sweep of every `.sma` found
no caller. The code path is unconditional and the reasoning is sound, but it is unproven
on the fleet, and this project's own history says untested natives in extension mode are
where the surprises live — `dodx.inc:311-314` warns that *`set_member`* throws runtime
error 10 on DoD. That is the ReGameDLL-gated family, a different table, but it is
plausibly why nobody has tried the neighbour.

Cheaper to prove than to design around.

---

## Tests, in order

Run on a local or LAN server, not production. Each test is a few lines in a throwaway
plugin; stop at the first failure and record it.

### T1 — the native exists and does not throw

```
get_entvar(1, var_origin, o)   // a live player
```

**Pass:** returns a plausible world origin matching `dodx_get_user_origin(1, …)`.
**Fail modes to record:** runtime error 10 (native not registered / stubbed), a zero
vector, or a silent AMXX error in the log. Distinguish "not registered" from
"registered but returns nothing" — they have different implications.

### T2 — it works on a non-player edict

```
get_entvar(0, var_absmin, mn)   // entity 0 = the world model
get_entvar(0, var_absmax, mx)
```

**Pass:** an AABB spanning the map. This also confirms index 0 is accepted
(`CHECK_ISENTITY` rejects on `< 0`, not on `== 0`) and gives world bounds for free —
useful for grid binning later.

### T3 — the real target

```
n = dodx_objectives_get_num()
for i in 0..n-1:
    ent = dodx_area_get_data(i, CA_edict)
    get_entvar(ent, var_absmin, mn)
    get_entvar(ent, var_absmax, mx)
    log(i, name, mn, mx)
```

**Pass:** `n` distinct, non-degenerate, non-overlapping-ish boxes at sane world
coordinates. Run on at least `dod_anzio` and one other map from the pool.

**Sanity checks that catch a plausible-looking wrong answer:**
- Each box should contain the corresponding `CP_origin_x/y`
  (`dodx_objective_get_data(i, CP_origin_x/_y)` — note these are `(int)`-cast and have
  **no z**, `NCP.cpp:59-62`).
- Box volumes should be capture-zone sized, not world sized and not zero.
- Boxes should be roughly ordered along the map's long axis.

### T4 — the ground-truth assert, and the one that actually matters

Inside the existing zone poll, for each flag, compare per-player AABB membership against
the engine's own count:

```
mine = count of connected players whose origin falls in the AABB, by team
assert mine.allies == CA_num_allies(i) and mine.axis == CA_num_axis(i)
```

**This is the whole spike in one test.** `absmin`/`absmax` is the *axis-aligned* bound of
the trigger brush, so a non-box brush over-covers and a player just outside a diagonal
trigger gets counted in. The engine's count is free ground truth for exactly that error.

**Record the mismatch rate per map.** It is not a pass/fail — it is a calibration number
that decides whether per-player zone attribution is trustworthy on that map, and it
should ship as a persisted data-quality field rather than a log line. A map whose brushes
are too irregular should disable the term, not silently corrupt it.

---

## If it fails

In preference order:

1. **A new DODX native reading `pEdict->v.absmin/absmax`** — correct data, but a C++
   change under the `cpp-dev` discipline, plus staging and md5-verifying a `.so` across
   the fleet at the 03:00 restart.
2. **Fall back to no zone geometry.** The depth coordinate does **not** require it — the
   spine needs only spawn centroids and flag origins, both reachable via the existing BSP
   parser. What is lost is per-player *zone* attribution, i.e. cap participation and
   contest-denial presence (S7). Depth re-pricing (S6) survives intact.

**Do not** expose `pd_dca.mins/maxs` via a new `CA_VALUE` key. Those fields are
documented in-tree as unreliable — `moduleconfig.cpp:1933-1936` already bypasses the
pdata origin offsets because they read as `(0, world_x)` on `dod_anzio`, and only the
region from `cap_mode` onward was re-aligned against gamedata offsets. The nine geometry
floats sit in the unvalidated part of the struct. That option ships known-bad data and is
strictly worse than doing nothing.

---

## Also worth grabbing while you are in there

Cheap, and it de-risks S3:

- `get_entvar(ent, var_classname, buf, len)` — confirms the entity is what you think it is
- Whether `var_origin` on `CP_edict` (`NCP.cpp:40-41`) gives a **float** control-point
  origin **with z**, which `CP_origin_x/y` does not
- Entity 0's AABB as map extents (T2), for grid binning

---

## Done when

- [ ] T1–T3 pass, or the failure is recorded precisely enough to choose a fallback
- [ ] T4 mismatch rate measured on ≥2 maps and written down
- [ ] a one-paragraph verdict appended to `KTPR_SPATIAL_PLAN.md` §1
