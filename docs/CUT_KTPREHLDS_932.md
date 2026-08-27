# The `.932` cut — KTP-ReHLDS incidentals filed as their own cut

**Filed 2026-08-26**, re-derived against `KTP-ReHLDS` `origin/main` at `c459c6de` (current tip — the
commit the just-staged hitreg-telemetry wave ships from, one ahead of the activated 3.22.0.969-dev ABI
wave). This is not a build; nothing here has been compiled or staged.

## Why "`.932`" and why it's not a real version number

The name is inherited from the RH-08 / RA-01 ABI-hold card, written when the live engine self-reported
commit count **931**. Since then two waves have shipped past it — the coordinated ABI wave
(3.22.0.969-dev, `da27ce9e…`, activated 2026-08-26 03:00) and the hitreg-telemetry wave
(3.22.0.976-dev, `99d31a79…`, staged, activates 2026-08-27 03:00) — neither of which carries any of
the four items below. There is no commit sitting at count 932 to cut from anymore; a build of this cut
today would self-report whatever `git rev-list --count` returns at that point (≥ 977). Treat "`.932`"
as this cut's *name*, not its *version*.

## What it contains

Four items, all confirmed **still unlanded** against `origin/main` `c459c6de` (2026-08-26) — i.e.
re-derived from the source, not taken from the ride-along list's prior claim:

### 1. Clamp `ktp_profile_spike_phase_share` at read

`rehlds/engine/sv_main.cpp:7287` declares the cvar (`default "0.25"`); `:9206` uses it unclamped:

```cpp
double spike_phase_floor = full_frame_time * ktp_profile_spike_phase_share.value;
```

every `[KTP_SPIKE_*]` detail line is gated on `phase_time >= spike_phase_floor`. A value `> 1.0` makes
the floor exceed every phase (no phase can exceed the frame it's a fraction of), so **every detail line
stops firing** while the umbrella `[KTP_SPIKE]` line keeps going — the profiler's only rollback lever
fails closed, and it looks like a quiet frame rather than a disabled one. Fix: clamp the value to
`[0, 1]` at cvar read (or on the `CVAR_CHANGE_CALLBACK`, if one exists for it — none does today).

### 2. `Con_DebugLog`'s off-thread race on `s_cached_fd`/`s_cached_fp` / `s_cached_file`

`rehlds/engine/sys_dll.cpp` — both the `_WIN32` branch (~1591-1601) and the non-Windows branch
(~1608-1618) cache a file handle in unsynchronized `static` storage, read and written from whatever
thread calls `Con_DebugLog`. Confirmed present and unchanged.

**This is a carry, not a required fix.** It was dispositioned "not a `.931` regression" — before that
gate the call site was a bare `if (sv_redirected)`, so an off-thread print with no redirect active
already took this branch; the race predates the ABI wave entirely and compounds with the dormant RH-09.
Include it in this cut only if the operator wants it addressed now; otherwise it stays carried on the
ride-along list, unfixed, at no additional risk.

### 3. RH-33 — `SteamRefresh_Enqueue` / `sv_tags` divergence from upstream

`rehlds/engine/sv_steam3.cpp:164` (`SteamRefresh_Enqueue`) and `:857-863` (the tag-change comparison)
diverge from upstream's handling of `sv_tags`. Confirmed present, unchanged.

**Re-verified live, not just at source, 2026-08-26:** `sv_tags` is set in **0 of 24** fleet
`dodserver.cfg` files (`grep -c '^sv_tags'` across all five hosts, all zero), against a positive
control of `grep -c '^hostname'` returning 5/5/5/5/4 (24) on the same sweep — the grep reads the files;
the cvar is simply never set. The divergence is real but inert on this fleet today, same as the
ride-along list said.

### 4. The standing question — `afraznein/KTP-ReHLDS`#3, merged and undeployed

PR #3 (`feat/hltv-status-spectator-clock`, merged `2f92266`, 2026-08-19) touches only
`rehlds/HLTV/Proxy/src/Proxy.cpp`: initializes `outputbuf[0]` so an rcon reply isn't silently truncated
by an uninitialized stack byte, and exposes the broadcast serve clock via `status`. **Confirmed merged
to source. Confirmed zero deploy path.**

`build_linux.sh` builds via the top-level `cmake` (`build.sh`), whose `CMakeLists.txt:17` already does
`add_subdirectory(rehlds/HLTV)`, which builds the Proxy target
(`rehlds/HLTV/Proxy/CMakeLists.txt:110`, `add_library(proxy SHARED …)`, `OUTPUT_NAME proxy`) — so the
fixed binary exists in every `build.sh` run today. `build_linux.sh` simply never looks for it: its
staging gate only searches `build/` for `engine_i486.so` and `hlds_linux`
(`ENGINE=$(find build -name "engine_i486.so" …)` / `HLDS=$(find build -name "hlds_linux" …)`). The
Proxy build output is silently discarded on every run.

The live artifact is `proxy.so` at `/home/hltvserver/hlds/proxy.so` on the data server
(`docs/LAN_SETUP.md:155`), shared by **all 24** HLTV proxy instances — the templated `hltv@%i` unit's
`WorkingDirectory=/home/hltvserver/hlds` (`provision/provision-lan-dataserver.sh:401`) is the same
directory for every port, so this is one binary, not 24 copies. It has been running the pre-fix build
since before 2026-08-19 — over a week as of this filing.

## What it depends on

**Nothing from the ABI wave.** All three engine incidentals (1-3) are self-contained reads/writes of
engine-local state — a cvar clamp, an off-thread log cache, a Steam3 tag string — none of them touch
`IRehldsHookchains` or `REHLDS_API_VERSION_MINOR`. This is **not** an ABI-coupled change and does
**not** need the RH-08/RA-01 coordinated multi-artifact swap: it is a normal single-artifact
`engine_i486.so` + `hlds_linux` nightly, the same shape as the just-staged telemetry wave.

**Item 4 is a separate artifact on a separate host.** `proxy.so` never touches the 24 game instances
`stage-wave.py` targets — it deploys once, to the data server. It has no dependency on items 1-3 and no
dependency on the ABI wave; it has been buildable and undeployed independently of both.

**Not gated by W1.** The grenade-ammo soak gate (see the ABI-wave review addendum) is specific to the
dodx/`KTPGrenadeLoadout` pairing. Nothing in this cut touches dodx, grenades, or any plugin — W1 has no
bearing on when this cut can ship.

## What gates it

- **Items 1-3 (engine):** none of them individually justifies a cut — each was dispositioned "won't-do
  alone" against the real cost of an engine cut (review, tier-2 smoke, a nightly, a 24-instance stage, a
  morning verify, and churning a reviewed md5 on a fleet with no rollback copies). Filing them **together**
  as one deliberate cut is what makes that cost worth paying, rather than letting each one ride some
  future unrelated engine wave silently (which is exactly how W2 in the ABI review — `stats_logging.amxx`
  quietly not being built — happened to a different artifact). Once bundled, gate it the normal way: the
  Module/Engine checklist in `docs/RELEASE_CHECKLISTS.md` (commit before build, md5 identity from the
  build not the banner, CHANGELOG entry, `stage-wave.py`, post-activation verify). No coordinated-wave
  discipline required.
- **Item 4 (HLTV Proxy):** gated on a deploy path existing first, which does not exist today. At minimum:
  (a) `build_linux.sh` (or a sibling script) needs to locate and stage `proxy.so` the way it already does
  `engine_i486.so`/`hlds_linux`, and (b) a delivery step to the data server's
  `/home/hltvserver/hlds/proxy.so`, since `stage-wave.py`'s fleet targeting is the 24 game hosts and does
  not reach the data server at all. Until that exists, this fix "ships never" regardless of which cut it
  rides — the standing question's own framing. It is the most time-sensitive item here (an already-merged
  bugfix sitting undeployed over a week), but it should not block items 1-3 shipping on their own schedule
  — different code, different binary, different host.
- **Explicitly excluded:** RH-08/RA-01 itself (the ABI hold) is not part of this cut — it already shipped
  as the coordinated wave (3.22.0.969-dev). This cut is only the residual items the ABI-hold card
  dispositioned "won't-do-alone."

## Re-derivation commands

```bash
# Items 1-3, source-side (run from a KTPReHLDS checkout on origin/main):
git show origin/main:rehlds/engine/sv_main.cpp   | grep -n "ktp_profile_spike_phase_share"
git show origin/main:rehlds/engine/sys_dll.cpp   | sed -n '1580,1650p'   # unsynchronized statics
git show origin/main:rehlds/engine/sv_steam3.cpp | grep -n "sv_tags\|SteamRefresh_Enqueue"

# Item 3, fleet-side (0 is the expected/current result; positive control must be nonzero):
grep -c '^sv_tags'   ~/dod-*/serverfiles/dod/dodserver.cfg
grep -c '^hostname'  ~/dod-*/serverfiles/dod/dodserver.cfg   # control

# Item 4:
gh pr view 3 --repo afraznein/KTP-ReHLDS --json state,mergedAt,files
grep -n "add_subdirectory(rehlds/HLTV)" CMakeLists.txt
grep -n "ENGINE=\|HLDS=" build_linux.sh   # confirms proxy.so is not in the staging gate
```
