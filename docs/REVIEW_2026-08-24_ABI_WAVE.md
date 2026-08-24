# Code review — the six-artifact coordinated ABI wave

**Reviewed 2026-08-24. Verdict: NOT-APPROVED for staging as-is.** Both blockers are configuration and
staging hygiene, not code.

> ⚠️ **This is a snapshot, not a standing fact.** Every measurement below was true on 2026-08-24 against
> the commits named. Re-derive at source before acting on any of it — several claims here exist precisely
> because an earlier document's figures had rotted.

## What was reviewed

| artifact | md5 | self-reports |
|---|---|---|
| engine (`KTPReHLDS`) | `da27ce9e8f22fff6e731852a42fb73c0` | `3.22.0.969-dev`, bakes commit `8550a3a`, no `-dirty` |
| ktpamx core | `1af525252f5aa9db94333b8deb3fe944` | `2.7.32.5683` |
| dodx | `2afd9348de21048d95a1c521c338fd6c` | `2.7.32.5683` |
| reapi (`KTPReAPI`) | `f1b9f972b03d517b2126482112016332` | `5.29.0.368-ktp` |
| `KTPGrenadeLoadout` | `3cadb7367ec604af7d5a87dabc344aa9` | 1.0.12 |
| `KTPPracticeMode` | `6a640395806764504ab660b5bc17c7a6` | 1.4.9 |

Identity was re-derived rather than accepted: `git rev-list --count 8550a3a` = 969 and `bce3ff25a` = 5683,
both matching the self-reported build numbers. All three module repos had clean worktrees, and every build
base is reachable from its `origin/main`. The engine base is 6 commits behind `origin/main`, but that diff
touches **only `.github/workflows/ktp-ci.yml`** — no engine-code drift.

Ranges: `KTPReHLDS` `8e00046..8550a3a` (24 commits) · `KTPAMXX` live-2.7.28 → `bce3ff25a` · `KTPReAPI`
through `f535b92`.

---

## Blockers

### C1 — `dodx.ini pdata_offset = 4` reinstates the off-by-one this wave removes the recovery for

2.7.32 **deleted the runtime auto-detect entirely** — `DODX_DetectPdataOffset` appears once at the 2.7.28
base (`d76104f74`) and **zero** times in the current tree. The compiled default moved 4 → 5
(`modules/dod/dodx/moduleconfig.cpp:35`), which is correct: `PDOFFSET_AMMO_BASE 280` + 5 = int 285 =
byte `0x474`, and `m_rgAmmoLast` at `0x4F4` is exactly 128 bytes / 32 ints later, so `DODX_MAX_AMMO_SLOTS
32` and the base both check out.

**But `dodx.ini` still overrides the default** (`moduleconfig.cpp:988-999`). With `pdata_offset = 4`,
`DODX_GrenadeAmmoCell` computes `284 + 9 = 293` = `m_rgAmmo[8]` — the wrong ammo type. `KTPAMXX/CHANGELOG.md`
names that exact off-by-one as the fleet-wide grenade failure. Under 2.7.28 an absent or wrong ini
self-corrected; **2.7.32 removes that rescue.**

**Fleet measured 2026-08-24: CLEAN, 24/24 carry `= 5`.** Positive control — the configs directory lists
31–33 files per host, and 24 `dodx.ini` were found (5+5+5+5+4, Chicago running four instances).

**The residual is the provisioning path, and it is not hypothetical.**
`provision/clone-ktp-stack.sh:601-605` *creates* `dodx.ini` with `pdata_offset = 4`. `git log -S` dates
that block to `fcd4265` (2026-02-22, the New York / Chicago provisioning commit). **Fix the script and its
`.example` — 4 → 5, or delete the block** — or the next provisioned instance is born broken with no
auto-detect to save it.

⚠️ `docs/LAN_SETUP.md:633` asserts *"The production fleet ships no `dodx.ini` and auto-detects `+5`
correctly."* That is a doc claim, not a measurement, and it is **false** — all 24 instances ship one. It is
harmless only because the value happens to match the new default.

### C2 — five decoy binaries sit where a staging sweep would reach

The wave was built with `KTP_NO_STAGE=1`, so the correct artifacts exist **only** at their build-output
paths. Meanwhile the local tree holds: the **superseded 2.7.31** dodx (`ac8d4e39…`, which the tracker
already says not to stage), the three **currently-live** artifacts (`8b06d8a2…` / `ea5f1801…` /
`eedfc99e…` — staging those is a silent rollback), and stale engine and reapi builds, two of the latter
**under the wrong filename** for the fleet (`reapi_amxx_` vs `reapi_ktp_`).

With `mv -f` and no host-side rollback, staging from a wrong path costs a full nightly cycle to detect and
another to fix. **Stage by explicit absolute path with a per-file md5 assert. Do not glob.**

⚠️ `build_linux.sh`'s *"Nothing has been staged"* does **not** mean the staging tree is clean — the
freshness gate refuses to copy but never removes, so a failed build leaves the prior artifact md5-verifying
perfectly.

---

## The ABI finding — this wave changes no vtable layout at all

This is the most useful durable result of the review, and it is narrower than the wave's own framing
assumed.

- `rehlds_api.h` across all three repos differs by **version-number-and-comment only** (5 lines each). No
  public engine header other than `rehlds_api.h` is touched in `8e00046..8550a3a`.
- The `IRehldsHookchains` pure-virtual lists are **byte-identical between KTPReHLDS and KTPReAPI, 69
  entries**. KTPAMXX carries 67 and is an **exact prefix** — the only difference is the two tail slots
  `SV_Rcon` (67) and `Host_Changelevel_f` (68), and KTPAMXX never calls either. The header's
  "deliberately a 67-entry prefix" claim is true. Positive control: the same extractor found
  `SV_UpdatePausedHUD` at slot 42 in all three copies.
- **No consumer outside these three repos reads the vtable.** KTPAmxxCurl has zero references to
  `rehlds_api` / `IRehldsHookchains`, and `.amxx` plugins cannot reach it.

So `MINOR 15 → 16` is a **detectability** change, not a compatibility one, and neither partial-swap
direction corrupts silently:

- **Engine lands, a module does not** — the guard is `minorVersion < MINOR`, so old modules pass against a
  new engine and the layouts are identical. Behaves as today. Benign.
- **A module lands, the engine does not** — all three refuse cleanly. AMXX prints `FATAL: ReHLDS API
  rejected` and registers zero extension hooks (`meta_api.cpp:2932-2937`); ReAPI prints and returns false
  (`mod_rehlds_api.cpp:68-73`); dodx sets `g_pRehldsHookchains = nullptr` and returns false
  (`moduleconfig.cpp:2158-2164`). Each refusal path was traced for a post-refusal NULL-deref and none
  exists. A hard, loud, **safe** outage: server up, no AMXX.

⚠️ **dodx's gate is fail-open if the core is old.** It reads `MF_GetRehldsApi`, resolved by name via
`REQFUNC_OPT` and registered by a `REGISTER_FUNC("GetRehldsApi", …)` call added *inside this wave*
(`5d58ac421`). If dodx 2.7.32 swaps but the core does not, that symbol is NULL and the gate never runs.
Enforcement therefore needs **core + dodx together**, not merely engine + dodx.

---

## The `pd_dcp` +1 int — correct, and the recorded risk was pointed at the wrong thing

The offset arithmetic was re-derived element by element rather than taken from the comment. On Linux (no
`iunk_1`), with five extras, `owner` lands at **376**, and every subsequent field matches
`gamedata/common.games/entities.games/dod/offsets-ccontrolpoint.txt` exactly — **fifteen consecutive field
alignments across 2.5 KB**, through `iunk_623` at 2508 = `m_bActive`. The cited gamedata file does exist.
The fix is right.

Three claims on record, sharpened:

- **"`dodx_objective_set_data` has zero `.sma` callers"** — still true. Swept all nine plugin repos plus
  `KTPAMXX/plugins`: zero. The write path (`NCP.cpp:161` → `CObjective::UpdateOwner` → `CMisc.cpp:701`) has
  exactly one caller in all of C++. Dormant. Worth knowing the semantics *change* if it ever wakes:
  pre-fix that write landed on offset 372 = `m_sMaster` (a `string_t`); post-fix it writes `m_iTeam`.
- **"no `.sma` reads `CP_index`"** — true, but **misdirected**. `CP_index`, `CP_owner` and
  `CP_default_owner` all read `mObjects.obj[]`, the module's own tracked struct, **not pdata**
  (`NCP.cpp:44-49`). They are unaffected by the +1 int regardless of callers.
- **The genuinely reachable pdata read is `DODX_InitCPFromEntities`** (`moduleconfig.cpp:2603-2610`), which
  runs on every map in extension mode. Nobody had named it. Its blast radius is bounded: `owner` and
  `default_owner` are re-seeded from the BSP immediately after (`:2657-2661`), `index` is overwritten by
  `bspCPs[si].point_index` when the reorder succeeds (`:2746`), and the first matching `InitObj`
  repopulates everything. So behaviour changes **only** where the BSP path fails — `dod_saints2_b3e` and
  `_b2` are named in the code as exactly that case — and there `index` goes from `m_iDefaultOwner` (0/1/2,
  collapsing CPs onto duplicate indices) to `m_iIndex` (distinct). An improvement, not a regression.

---

## Warnings

**W1 — the mandatory soak gate. The grenade-ammo read *source* moved**, on the one plugin that runs at
every spawn of every match on all 24 instances. `CHANGELOG.md` states the old getter's offset "has no
ammo-indexed array anywhere near it… the getter had been reading an unrelated field on *every* map", so
`dodx_get_grenade_ammo` returns a **different number** after this wave, and the old code's three writes
(64 / 294 / 326) become one (294). Dropping the base-59/61 write is deliberate, but the changelog only
establishes it is not an *ammo array* — not that it is inert to the weapon's own logic. **Soak must
confirm, per class and for both teams: correct spawn grenade count, HUD number matching, grenades
throwable — including a British-Allies map (classes 21–25) where ids 13/36 share a slot.**

**W2 — the wave does not deliver what its changelog headlines.** `stats_logging.amxx` was **not built**:
`configure.py --no-plugins` means `build_linux.sh` never builds it, and `plugins/compile.sh` globs only
`plugins/*.sma`, never `plugins/dod/`. The repo copy and the staged copy are the same stale Mar 11 build
(`becc037a…` both). The source *is* genuinely fakemeta-free now — the full 31-file transitive closure has
zero deny-list hits, with `fakemeta.inc` / `fakemeta_util.inc` as the positive control — but PR #53's two
new bounds natives ship **with no consumer** and the capture-zone containment work stays dark. Not a
safety problem; do not announce it as shipped.

**W3 — KTPAMXX's `rehlds_api.h` copy is outside the header-drift CI gate.** `KTPReHLDS`'s workflow diffs
KTPReHLDS ↔ KTPReAPI only; KTPAMXX has no drift workflow at all. Yet its copy is a live vtable consumer
whose safety rests on an unenforced *prefix* property. A future mid-vtable insert would break AMXX silently
with nothing checking. The append-only rule needs a third leg.

**W4 — `public/resdk/engine/rehlds_api.h.bak` is tracked** and carries `MINOR 6` with a 57-entry vtable.
Referenced by nothing, so inert for the build — and a landmine if ever restored. Delete it.

**W5 — ReAPI 5.29.0.368 is not a version-only change.** `engine_api.cpp` is now wrapped in
`#ifndef REAPI_NO_METAMOD`, and `precompiled.h:4` includes `extension_mode.h`, which defines it
unconditionally. The TU compiles to nothing, so the `.so` **loses `GetEngineFunctions_Post` and
`meta_engfuncs_post`**. Safe in extension mode — nothing calls them — but it is a real exported-symbol
delta the version bump does not advertise.

**W6 — `SWAP_FAILED > 0` should abort, not log.** `ktp-scheduled-restart.sh:277-295` does a per-file
`mv -f`, logs `FAILED to swap`, increments the counter, and **continues into the server start**. All four
deploy paths are glob-covered so no artifact is orphaned, but partial activation is the one outcome six
coupled artifacts cannot tolerate quietly.

**W7 — `MF_LogError` makes a documented return contract unreachable.** `dodx_area_get_bounds`
(`NCP.cpp:388-392`) raises `AMX_ERR_NATIVE` on an out-of-range index, which **aborts the calling Pawn
public**. `dodx.inc:867` documents only "1 on success, 0 if no area or the box is degenerate". Since Pawn
globals persist across map changes in extension mode, a plugin caching a flag count from the previous map
hits this. Same shape as the known `dodx_set_team_score` issue.

**W8 — `dodx_send_ammox` still does not bound `ammo_slot`** while `dodx.inc:569` tells callers to feed it
`dodx_get_grenade_ammo_index()`, whose documented failure return is −1 (`WRITE_BYTE(-1)` → 255 on the
wire). **Confirmed dormant for this wave**: zero callers of either symbol across all nine plugin repos —
both plugins dropped their manual AmmoX. Latent, cheap to fix, not blocking.

**W9 — comment-vs-code drift on the exact mechanism this wave is built around.** `modules.cpp:2065` says
"no in-tree consumer yet" for `GetRehldsApi` while `moduleconfig.cpp:2155` **is** that consumer, and is the
load-bearing version gate.

**W10 — `docs/LAN_SETUP.md:628-630`'s healthy-case diagnostic goes stale with this wave.** It teaches the
reader to look for `[DODX] Auto-detected pdata offset +5`, a line 2.7.32 no longer emits. The wrong-case
line survives; the new healthy line is `[DODX] Using m_rgAmmo pdata offset +N`.

**W11 — `KTPHudObserver` consumes a native whose contract and value source both change.** It calls
`dodx_get_grenade_ammo`. The local source handles the −1 correctly, but the deployed artifact is an
external build with no local copy to compare, so provenance is unverifiable from here. Worst case is
cosmetic. Named because it is a live consumer nobody would think to check. Out of scope for review by
policy — externally maintained.

**W12 — the header-drift gate on `main` shows a stale red on an already-resolved condition.** A post-merge
run failed comparing main-vs-main 61 s before KTP-ReAPI's counterpart landed; nothing re-triggers it, and
`push` runs gate nothing (branch protection is PR-only). The gate is sound — it does `exit 1` on a real
diff — but **the next genuine drift will look identical to this known-stale red.** Re-run it via
`workflow_dispatch` before staging so the signal is clean.
⛔ Do **not** "fix" it by normalising line endings: the two blobs are `i/crlf` and `i/lf`, but KTPReAPI's
`.gitattributes` pins `eol=crlf`, so they materialise identically on the runner.

**W13 — `build_linux.sh` gating.** Piped to `| head`, the script dies on SIGPIPE at 141 **with no banner at
all**. Gate on the *presence* of `[KTP-BUILD] OK`, never on the *absence* of `FAILED`, and fix the in-file
comment implying otherwise.

**W14 — CI hardening in `ktp-ci.yml`.** A step output is interpolated directly into a `run:` body; pass it
via `env:` instead. And on fork pull requests the counterpart ref is selected from an attacker-controllable
branch name, so a name collision with a stale KTP-ReAPI branch yields a green comparison against the wrong
tree. Pin the compared ref rather than deriving it from `github.head_ref`. A fork PR appears in this very
commit range, so this path is exercised in practice.

**Not reachable by this wave, but blocking whenever `stats_logging.amxx` is next cut:**
`ktp_stats_capture.inc` registers a task in `controlpoints_init` that `KTPAMX_ReloadPlugins`'s
`g_tasksMngr.clear()` destroys before it fires (hook ordering verified: the core registers
`SV_ActivateServer` first, dodx later at equal priority, and equal priorities run in registration order);
a duplicate ownership baseline from `controlpoints_init` firing twice per map; and a persistent
`g_kscFlagCount` that on a zero-CP map drives `MF_LogError` — a Pawn public abort — twice a second. That
last one has a trap in its own fix: resetting in `plugin_init` runs *after* `controlpoints_init` on a map
change and would wipe the fresh value. Re-read `dodx_objectives_get_num()` in the poll instead.

---

## What holds up well

- **The `pd_dcp` +1 int is right**, derived twice independently — published offsets plus a production
  observation — and confirmed by fifteen consecutive field alignments.
- **All ammo-slot arithmetic is bounded.** `WeaponList` (`usermsg.cpp:421`) and `ObserveGrenadeAmmoIndex`
  (`moduleconfig.cpp:206`) both clamp to `[0, 32)`; `DODMAX_WEAPONS` is 47 on both the C++ and Pawn sides;
  every write lands inside `m_rgAmmo`. No out-of-bounds.
- **The zero-init trap was already caught.** `g_ammoIndexByWeapon` is static storage, where zero is a *real*
  slot, and `OnAmxxAttach` calls `DODX_ClearAmmoRegistry()` with a comment saying exactly that. Per-map
  clears exist on all four paths, including the PreThink last-resort recovery.
- **Every native declared in `dodx.inc` is registered in C++** — 91 declarations, all present among the 134
  registered names, zero missing. No load-time native mismatch.
- **The plugin pair built from an older base is not invalidated.** `dodx.inc` changed additively — its only
  seven deleted lines are doc comments — `dodconst.inc` and `ktp_version_reporter.inc` are unchanged, and
  both `.sma` files are byte-identical to the commits their artifacts were built from.
- **1.0.12 genuinely handles the −1** (`KTPGrenadeLoadout.sma:298-303` gates on `currentCount <= 0`), so the
  pairing requirement that forces it into this swap is real and satisfied.
- **The engine C++ delta is two executable lines** (`Proxy.cpp:707`, `:1528`). No unauthenticated
  `RD_PACKET` redirect exposure: rcon auth failures return before `ExecuteRcon` with no redirect active,
  `SV_BeginRedirect|RD_PACKET` appears zero times in the range, and the reply is far under the 4037-byte
  connectionless cap.
- **The version-consistency gate ported in PR #50 runs a `--selftest` first**, so it proves it can still
  fail before you believe it passes.

## Smaller suggestions

- Cache `dodx_get_match_id` + `get_localinfo` in `ksc_producer_ctx()` — both are constant for a half but
  called per hit *and* per kill inside postthink.
- `Client_WeaponList`'s `static int iAmmoIndex` is not reset by `DODX_ClearAmmoRegistry()`. Harmless today,
  but it is the one piece of registry state outside the per-map reset.
- The pickup probe in `dodx_give_grenade` yields a slot **relative to `PDOFFSET_AMMO_ARRAY`**, while
  `WeaponList` yields the DLL's **absolute** ammo-type index. They are comparable only when the base is
  right — elegant, since the disagreement log fires precisely when C1 has bitten, but undocumented. Say so
  at the comparison site.
- `KTPAMXX/CHANGELOG.md` has a `## Reverted` section sitting above the `# Changelog` H1.
- `BUILD_STAMP` from `mktemp` lands on `/tmp` (ext4) while `build/` is on `/mnt/n` (drvfs); cross-filesystem
  mtime skew makes `-newer` unreliable in the unsafe direction. Use `mktemp -p "$PWD"`.

---

## Conditions for approval

Once **C1 is measured clean** (it is, as of 2026-08-24 — but re-measure at stage time) and **C2 is
controlled**, a single-instance soak is approved. Make **W1** the explicit soak gate. Pull the six live
artifacts off the soak host **before** staging — there is no rollback copy on the box. Treat
`SWAP_FAILED > 0` as an abort condition rather than a log line, and re-run the header-drift gate first so
its stale red cannot mask a real one.

## What this review did not cover

- **No server was touched, queried or measured by the review itself.** Every fleet-side claim in it was
  framed as a check to run. (The C1 fleet sweep recorded above was run separately, by hand, and is dated.)
- Nothing was built or compiled — re-running would churn md5s pinned to this review.
- `NBase.cpp` (379 lines), `NCP.cpp` (50), `dodx.h` (111) and `usermsg.cpp` (78): the grenade/ammo rework,
  the CP natives, the `pd_dcp` struct and `Client_WeaponList` were reviewed in full, but not every hunk.
- `DODX_ReadBSPControlPoints`, `dodx_get_score_tick_*` behaviour on a live map, and the DoD `WeaponList`
  wire format were taken from the code's own disassembly citations rather than re-derived from the binary.
- Conflict resolution inside the eight engine merge commits, and the engine CHANGELOG prose.
- The HLStatsX daemon side (`hlstats.pl` handlers for the new event shapes) — different repo, not read.
- `KTPHudObserver` — externally maintained; call sites were read only to assess cross-artifact impact.
