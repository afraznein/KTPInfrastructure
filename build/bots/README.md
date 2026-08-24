# Local bot server (`ktp-game-2`)

A DoD server with bots in it, so the local stack can exercise things the mocker
structurally cannot: a real go-live, the mass-respawn stat re-wipe, reinforcement
wave clocks, cap-break attribution, the halftime side swap.

**This is not a production topology and is not evidence about production.** Read
[Not a control](#not-a-control) before trusting a result from it.

## Quick start

```sh
make local-bots-amxx      # one-off, ~10 min: patched ktpamx + dodx
make local-bots-plugins   # KTP_TEST_MODE KTPMatchHandler + HUD plugin
make local-bots-build     # the image
make local-bots-up
make local-bots-match     # fill 6v6 with bots and take it LIVE
```

Run `local-bots-match` **before** joining the server — `.testmatch` refuses to
start while a human client is connected. HLTV is exempt and may stay.

## Why any of this is necessary

Three constraints, none of them optional:

**DoD ships no bot AI.** Stock `addbot` makes a fake-client slot that never joins
a team and never spawns. A third-party bot mod is required, and the only
Linux-viable DoD 1.3 ones are Metamod plugins.

**The KTP stack is Metamod-free.** ReHLDS extension mode loads ktpamx through
`addons/extensions.ini`, and `liblist.gam` keeps `gamedll_linux` at
`dlls/dod.so`. There is no Metamod for a bot plugin to load into.

**AMXX cannot see bots in extension mode.** There is no code path registering a
fake client as a player — `Connect()` / `PutInServer()` / `++g_players_num` never
run — so `is_user_connected()` is false for every bot and every AMXX-level plugin
is blind to them.

## The topology

```
engine  -> addons/extensions.ini -> ktpamx_i386.so   <- UNCHANGED, as production
engine  -> liblist.gam           -> metamod_i386.so
metamod -> plugins.ini           -> new_bot_mm.so    <- bot ONLY
metamod -> +localinfo mm_gamedll -> dlls/dod.so
```

Metamod hosts **the bot only**. ktpamx keeps loading through `extensions.ini`
exactly as it does on the fleet, so plugins still run in extension mode.

Letting Metamod host ktpamx as well **segfaults**: ktpamx logs "ReHLDS extension
mode detected" even when Metamod loaded it, and installs ReHLDS hookchains from
inside Metamod's chain as well as at the engine layer. Three boot attempts
upstream, three SIGSEGVs. See `tests/e2e_stats/PHASE0_FINDINGS.md`.

## The silent failure this is built around

A server running an unpatched ktpamx with bots on it looks **completely healthy**:
`status` lists the bots, the map plays, nothing errors — and no plugin emits
anything at all.

Upstream shipped an A/B differential that reported "no interference, 8/8" while
AMXX was entirely blind, because the fingerprint compared module and plugin
*loading* and never measured player visibility.

So `runtime/entrypoint-bots.sh` **refuses to boot** without the patched core
rather than warning. The acceptance test is likewise not "`status` shows a
player" — it is "the HUD backend logged a `player_connect` for `BOT_<n>`".

## Keeping it in sync with `ktp-game-1`

The invariant worth holding is **not** "matches the fleet" — neither server does.
`build/amxx/Dockerfile` COPYs your local KTPAMXX working tree, so game-1 is
whatever you have checked out. The invariant is:

> **game-2 = game-1, plus `KTP_LANE_B_FAKECLIENTS`, plus the Metamod bot layer.**

`make local-bots-amxx` therefore points `scripts/build_ktpamx_laneb.sh` at the
**local** KTPAMXX checkout at its current HEAD. The script's own default is to
clone `preprod` from GitHub, which is exactly what would inject skew.

It refuses on a dirty KTPAMXX tree, because `make build-amxx` bakes the *working
tree* into game-1 while this builds a *committed SHA* for game-2 — a dirty tree
means the two servers silently run different source.

`make local-bots-up` warns when the recorded SHA and KTPAMXX HEAD disagree. Same
shape as the existing `check-artifacts` warning, and the same honest scope: it
answers "were these built from the same commit", nothing about the fleet.

## Not a control

- **`fakemeta` is reachable here and is not on the fleet.** Several of this
  stack's constraints exist *because* extension mode lacks it. A fakemeta
  dependency passes here and fails on all 25 servers.
- **Bot stats are not human stats** — bot weapon counters needed explicit
  carve-outs upstream (KTPAMXX #21/#22).
- **Cap-breaks are luck.** A few-minute run produces one about half the time.
  Absence is "not exercised", not a failure.
- **The custom competitive pool has no waypoints at all.** new_bot 0.2.2 ships
  94 `.wpt` files covering stock maps. Verified in the built image:

  | have waypoints | do NOT |
  |---|---|
  | `dod_anzio` `dod_flash` `dod_donner` `dod_kalt` `dod_avalanche` `dod_merderet` `dod_jagd` | `dod_saints2_b3e` `dod_railyard_s9d` `dod_armory_b6` `dod_halle` `dod_thunder2` `dod_lennon5_b1` `dod_railroad2_s9a` |

  This bounds the feature more than anything else here. In particular
  **cap-break testing on `saints2_b3e` / `railyard_s9d` is not possible** —
  those are the maps where cap-breaks concentrate (one area-brush flag of five),
  and they are exactly the ones with no bot coverage. An unwaypointed map gives
  bots that connect and stand still, which reads as a broken pipeline rather
  than an unwaypointed map. List what is available with:

  ```sh
  docker run --rm --entrypoint bash ktp-gameserver-bots:$VERSION \
      -c 'ls /opt/hlds/dod/new_bot/waypoints'
  ```
- **Neither server tracks the fleet.** Deploy truth is CHANGELOGs + SSH.

## Redistribution

The image contains new_bot and Metamod-R, neither ours to redistribute. It is a
local build artifact — **never push `ktp-gameserver-bots` to a registry**. The
fleet consumes no images at all, so nothing here can reach production by accident.

Both downloads are SHA-256 pinned: a changed or replaced upstream artifact fails
the build rather than silently swapping the bot. The pins are duplicated from
`build/lane-b/Dockerfile` on purpose — if one moves, move both.
