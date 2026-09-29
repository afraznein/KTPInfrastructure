# Spike results: `get_entvar` on DoD

**Spec:** `SPIKE_ENTVAR_GEOMETRY.md` (step S0 of `KTPR_SPATIAL_PLAN.md`).
**Run:** 2026-09-29, local Docker only. No fleet host, no production rcon.
**Plugin:** `tests/e2e_stats/diagnostics/KTPEntvarSpike.sma`, every line prefixed `[ENTVAR]`.

## Verdict

**`get_entvar` works on DoD in extension mode. Spatial KTPR can proceed without a C++ change.**

- T1 passes: 12/12 live bots, byte-for-byte equal to `dodx_get_user_origin`.
- T2 fails its own pass criterion, and the native is not the reason. Entity 0 has no
  bounds in GoldSrc, so it cannot give map extents (details below).
- T3 passes on the read itself: all 18 capture areas across 9 maps are bit-identical to
  `dodx_area_get_bounds`, which reads the same field in C++. Two of the spec's sanity
  checks are wrong, though, and many flags have no capture area at all.
- T4: the AABB membership test against the engine's own `CA_num_allies/axis` has a
  lag-tolerant mismatch rate of **0.0% on dod_anzio, 6.1% on dod_avalanche and 3.4% on
  dod_kalt**. Only avalanche's error is geometric over-coverage. Kalt's is the engine
  holding a stale count.

Neither fallback in the spec's "If it fails" section is needed. Fallback 1, a DODX native
that reads `absmin/absmax`, already exists as `dodx_area_get_bounds` /
`dodx_get_user_bounds` (KTPAMXX `cd58f0e6a`, 2026-08-23). It was written after the spike
doc, and this spike used it as the independent ground truth.

## Setup

| | |
|---|---|
| Sources | origin/main: KTPAMXX `b3bc4767`, KTPReAPI `80b33ad`, KTPReHLDS `d9880f6`, KTPhlsdk `fae0a01`, KTPInfrastructure `ac6102d` |
| Bot server | `ktp-gameserver-bots` image (`build/bots/`): Metamod-R hosts new_bot only, and ktpamx is a `KTP_LANE_B_FAKECLIENTS` build loaded through `extensions.ini`. Lane B stamp `b3bc4767…-558219abf63b` |
| Control server | `ktp-gameserver` image (production topology, no Metamod, no bots). Used for T2, T3 and the negative controls, so those results do not depend on the Metamod bot layer |
| Modules | `reapi` and `dodx` only (`reapi_ktp_i386.so` md5 `f1b9f972b03d517b2126482112016332` on both servers) |
| Plugins | only the spike plugin; `plugins.ini` holds that one line |
| Compiler | Lane B checkout's `amxxpc` (md5 `59980edc99fc2c5ea6d6f13ed58ecda3`); ReAPI includes from KTPReAPI origin/main. It compiled with no warnings |
| Bots | new_bot 0.2.2, `target_players 12`, `flag_priority_percent 100`, `wait_for_cap_percent 100`, `bot_skill 3` |

Both servers ran as their own containers with their own compose project, image tag
(`wxentvar`) and ports (27046/27047). Nothing touched the shared `ktp-game-1/2`
names or ports.

## T1: a live player

```
[ENTVAR] T1 id=1 name=Natla alive=1 cls=player(rc=-94636033) get_entvar_origin=(226.524 -28.682 -405.456) rv=1 dodx_origin=(226.524 -28.682 -405.456) dr=1 match=1 negctl_angles_match=0 pev_team=2 get_user_team=2
[ENTVAR] T1 end tested=12 match=12 zero_vectors=0 negctl_discriminated=12/12
```

This result was the same on all three maps. `var_team` agrees with `get_user_team` on
every bot.

**Negative control:** `var_angles` compared against the same origin never matched (12/12
discriminated), so the comparison can fail.

**Trap:** on a string member the return value is not a length (`rc=-94636033` for
`var_classname`). The buffer is correct. Do not use that return value.

## T2: entity 0

```
[ENTVAR] T2 world cls=worldspawn model=maps/dod_anzio.bsp solid=4 modelindex=1 absmin=(-1.0 -1.0 -1.0) absmax=(1.0 1.0 1.0) r=1,1 mins=(0.0 0.0 0.0) maxs=(0.0 0.0 0.0) origin=(0.0 0.0 0.0)
```

The same values came back on all 9 maps and all 10 map loads. **Index 0 is accepted and
the read is correct.** Classname, model, `solid=SOLID_BSP` and `modelindex=1` are exactly
what `SV_SpawnServer` writes (KTPReHLDS `rehlds/engine/sv_main.cpp:6913-6916`). The
engine never sets the world's bounds. `SV_LinkEdict` returns early for `edicts[0]`
(`world.cpp:510-511`), so its abs box is never computed.

**So "entity 0's AABB as map extents" does not work, on any engine.** Two replacements
reachable from Pawn with no C++ change:

| map | union of in-use entities' origins/abs boxes (extent) | allies spawns (n, centroid) | axis spawns (n, centroid) |
|---|---|---|---|
| dod_anzio | 4848 × 7819 × 890 | 20, (-248 -2628 -589) | 20, (2391 3268 -487) |
| dod_avalanche | 3011 × 5059 × 1315 | 20, (604 -1428 -327) | 25, (76 1903 247) |
| dod_kalt | 3352 × 6012 × 1091 | 15, (1350 1587 35) | 14, (922 -2801 35) |
| dod_flash | 6547 × 5027 × 683 | 18, (-2236 -1170 10) | 18, (2270 276 52) |

The spawn centroids come from a classname scan (`info_player_*` and
`info_initial_player_*`) through `get_entvar`. That gives S3 its poles at runtime as well
as from the BSP parser. The entity union is a lower bound on the playable volume, not the
BSP bounds. For exact extents, read BSP model 0's mins/maxs in the existing parser
(`DODX_LoadBSPEntityLump`), or bin on observed positions.

## T3: capture zones

Every capture area that dodx resolves matches `dodx_area_get_bounds` exactly (compared
with `==`, no tolerance), and every one satisfies `absmin == origin + mins - 1` (the
engine's 1-unit link padding):

```
[ENTVAR] T3 cp=1 name=POINT_BRIDGE area_ent=169 dup=0 cls=dod_capture_area model=*134 solid=1 target=bridge_flag absmin=(877.9 -361.9 -393.9) absmax=(1209.9 -109.9 -245.9) size=(331.9 251.9 147.9) dodx_bounds=(877.9 -361.9 -393.9)-(1209.9 -109.9 -245.9) br=1 exact_match=1 origin+mins-1=1
[ENTVAR] T3 cp=1 CP_origin=(1040 -288) in_box_xy=1 cp_edict=114 cp_cls=dod_control_point cp_var_origin=(1039.99 -287.99 -358.99) r=1 cp_origin_xy_agrees=1
```

| map | CPs | `dod_capture_area` entities | resolved via `CA_edict`, exact match | CPs with no area | CP_origin inside its box (xy) |
|---|---|---|---|---|---|
| dod_anzio | 5 | 2 | 2 | 3 | 2/2 |
| dod_avalanche | 5 | 5 | 5 | 0 | 5/5 |
| dod_kalt | 5 | 3 | 3 | 2 | 3/3 |
| dod_donner | 5 | 1 | 1 | 4 | 1/1 |
| dod_merderet | 5 | 2 | 2 | 3 | 1/2 |
| dod_jagd | 3 | 1 | 1 | 2 | 0/1 |
| dod_charlie | 4 | 8 | 4 | 0 | 0/4 |
| dod_flash | 5 | 0 | 0 | 5 | — |
| dod_caen | 6 | 0 | 0 | 6 | — |

That is 18/18 exact matches. Classname is always `dod_capture_area`, `solid=1`
(`SOLID_TRIGGER`) and the model is a brush (`*N`). Volumes are zone-sized
(28–772 units on a side). The spec asked for the read to work on "at least `dod_anzio`
and one other map". It did on 7.

What T3 shows about the spec's own sanity checks:

1. **"Each box should contain `CP_origin_x/y`" is not a valid check.** It fails on jagd,
   charlie and one merderet flag, with the reads verified exact. This is the property the
   `dodx_area_get_bounds` doc comment warns about: the flag prop and its trigger are not
   co-located.
2. **"`n` distinct boxes" does not hold on most maps.** 25 of the 43 CPs across these 9
   maps have no `dod_capture_area` at all (flash and caen have none), so they are capped
   another way. No entity scan found an area for them either, so there is no zone
   geometry to read and none to miss. Per-player zone attribution (S7) simply does not
   exist for those flags.
3. **A flag can have more than one area.** dod_charlie has 8 `dod_capture_area`
   entities for 4 CPs, and `CA_edict` returns one per CP. A classname scan with
   `get_entvar` finds the rest. S7 needs that scan, not `CA_edict` alone, on maps like
   this.

**Also worth grabbing (done):** `var_origin` on `CP_edict` returns a float origin with
z, e.g. `(1039.99 -287.99 -358.99)` against `CP_origin=(1040 -288)`. It agrees with the
int-cast xy on every CP. The `CP_edict` abs box is the 2×2×2 flag prop, not a zone.

## Negative controls (control server)

| case | result |
|---|---|
| `get_entvar(-1, var_origin, v)` | `[ReAPI] get_entvar: invalid entity index -1` → `Run time error 10`, callback aborted |
| `get_entvar(100000, …)` | `invalid entity index 100000` → `Run time error 10` |
| `get_entvar(1, EntVars:99999, …)` | `unknown member id 99999` → `Run time error 10` |
| `get_entvar(900, …)`, a free slot | **returns 1 with a zero vector and no error** |

The native registers and errors loudly on a bad index or member. **A freed or unused edict
reads as zeros without complaint.** Any consumer has to confirm that the entity exists
(non-empty classname) before trusting the numbers. The bot server logged no native errors
at all over about 45 minutes of polling.

`get_entvar` also kept working across 10 `changelevel`s on the control server and 3 on
the bot server. `g_pEdicts` is refreshed in `ExtHook_SV_ActivateServer`
(`reapi/src/extension_mode.cpp:203`), so it is not left pointing at the previous map's
edict array.

## T4: AABB membership against the engine's count

**Ground truth:** `CA_num_allies/CA_num_axis` (`m_nNumAllies/m_nNumAxis`), polled every
0.2 s alongside each alive player's position. The engine decides membership as
`BoundsIntersect` (player abs box against trigger abs box) followed by an exact hull test
against the brush (`SV_TouchLinks`, KTPReHLDS `world.cpp:322`). The AABB test is exactly
that first stage, so its only geometric error is over-coverage.

**Methods compared.** Each map ran about 7 minutes, 12 bots, 2,100 polls. "Occupied" means
the engine or any method counted at least one player.

- `origin_pt`: the player's origin inside the AABB.
- `bbox`: the player's abs box overlaps the AABB. This is the engine's first stage.
- `bbox_lagtol`: `bbox`, but a sample counts as a mismatch only if the engine's count
  equals none of our counts over the previous 10 polls (2 s). The engine updates on its
  own schedule, and the death decrement is 0.2–2.5 s late in production
  (`KTPHudObserver.sma` break-queue comment).
- `NEGCTL`: the AABB shifted 4096 units on x, which has to disagree whenever a zone is
  occupied.

| map (areas) | occupied samples | `origin_pt` | `bbox` | **`bbox_lagtol`** | NEGCTL (must be high) |
|---|---|---|---|---|---|
| dod_anzio (2) | 2464 | 248 (10.1%) | 238 (9.7%) | **0/2455 (0.0%)** | 2431 (98.7%) |
| dod_avalanche (5) | 3529 | 1572 (44.5%) | 842 (23.9%) | **216/3515 (6.1%)**: 209 persistent over, 7 under | 3049 (86.4%) |
| dod_kalt (3) | 1193 | 442 (37.0%) | 355 (29.8%) | **40/1184 (3.4%)**: 40 persistent under | 1128 (94.6%) |

An earlier pass had no lag-tolerant counter. Its instantaneous `bbox` rates were close
(anzio 11.7%, avalanche 24.3%, kalt 32.5%), so these numbers are stable run to run.

Per flag, `bbox_lagtol`:

- **avalanche:** cp0 57/859, cp1 5/426, cp2 69/784, cp3 79/748, cp4 6/712.
- **kalt:** cp0 38/186, cp2 2/992, cp4 0/15.
- **anzio:** cp1 0/993, cp3 0/1471.

What the numbers say:

- **Use the player's bounding box, never the origin.** The origin test under-counts
  heavily (avalanche 44.5%, most of it "under"), which is the reason `dodx_get_user_bounds`
  exists.
- **Most instantaneous disagreement is timing, not geometry.** On anzio every mismatch
  cleared within 2 s.
- **Avalanche is real AABB over-coverage.** The misses are persistent and all "over": a
  live player's box overlaps the AABB but not the brush, typically at the edge. cp3, for
  example, shows `bbox=0/1` against `engine=0/0` for consecutive polls with the origin
  outside the box.
- **Kalt is engine-side staleness, not geometry.** At cp0 the engine reports
  `engine=1/0` while no player, alive or dead, has a box anywhere in the AABB:
  `origin_pt=0/0 bbox=0/0 bbox_incl_dead=0/0`. The ground truth itself holds a count for
  more than 2 s after anyone has left. A geometric test cannot fix that, and it should
  not be scored as AABB error.
- **The engine counts the owning team too.** A variant that drops the flag's owner is far
  worse on every map (anzio 841 against 238). So `CA_num_*` includes defenders, and it is
  usable ground truth for contest-denial presence (S7).
- **The player box read is exact.** `get_entvar(id, var_absmin/absmax)` equalled
  `dodx_get_user_bounds` in all 75,960 reads over the three maps.

**For the spec's calibration field:** ship the lag-tolerant `bbox` mismatch rate per map
and per flag as the data-quality number, not the instantaneous one. Instantaneous
disagreement is mostly engine update latency. Anzio would pass any threshold. Avalanche
cp0, cp2 and cp3 (about 7–10%) are the case where the term should be gated per flag. Kalt
cp0 shows that the persisted field should keep "ours over" (geometry) apart from "engine
over, nobody present" (a stale engine count), because only the first is AABB error.

**Not a control:** bots are not humans. They walk to flags and stand on them, and their
movement and flag behaviour are new_bot's. Rates on human play will differ. The waypoint
limit (`build/bots/README.md`) keeps the custom competitive pool out of T4 entirely.
T1–T3 do not depend on bots except T1, and T2/T3 were confirmed on the production-topology
control server.

## Reproducing

```sh
# images: build/docker-compose.yml (ktp-base, ktp-rehlds, ktp-amxx, ktp-reapi),
# scripts/build_ktpamx_laneb.sh, then docker-compose.local.yml ktp-game-1 / ktp-game-2
# config: config/local with modules.ini = reapi,dodx; plugins.ini = KTPEntvarSpike.amxx; "log on"
rcon entvar_static                 # T1-T3 + extras
rcon entvar_neg 1|2|3|4            # negative controls, one per call
rcon entvar_reset; rcon entvar_poll 0.2
rcon entvar_summary; rcon entvar_stop
```

Output goes to `addons/ktpamx/logs/ktp_entvar_spike.log` and the game log. Extension mode
keeps plugin globals across map changes, so run `entvar_reset` on every map.
