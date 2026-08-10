# Phase 0 findings — Lane B, 2026-08-09/10

What a real run established, in the order it was learned. Everything here was
observed, not reasoned.

## Summary

Bots work. The stack tolerates them. The capture code still emits nothing, and
the reason is a deliberate early-return in KTPAMXX's extension-mode client path
that makes AMXX blind to fake clients.

| Question | Answer |
|---|---|
| Can bots connect, fight, capture? | **Yes** — 12–16 bots, 50 kills, 12 CP captures |
| Do DODX forwards fire for bots? | **Yes** — 107 `client_damage`, 53 `client_death` |
| Does Metamod perturb the stack? | **No measurable difference** in modules/plugins |
| Does the capture code emit? | **No** — 0 assists where 7 were owed |
| Why? | AMXX cannot see bots at all (below) |

## The root cause

`KTPAMXX/amxmodx/meta_api.cpp:1160`, in the ReHLDS extension-mode client path:

```c
if (pEntity->v.flags & FL_FAKECLIENT)
    return;
```

The function returns before `pPlayer->Connect()`, before
`pPlayer->PutInServer()`, and before `++g_players_num`. So in extension mode
AMXX never registers a bot as a player.

Measured directly with a diagnostic plugin (`KTPTeamProbe`), while six bots were
demonstrably in the world fighting and capturing:

```
[TEAMPROBE] get_players reports 0
[TEAMPROBE] slots with any presence: 0     ← swept ids 1..32
```

Not one slot reported `is_user_connected`, `is_user_connecting`, or even a
non-empty `get_user_name`.

**Every emit path in `ktp_stats_capture.inc` is gated on that native:**

| Path | Guard |
|---|---|
| `ksc_on_death` | `if (!is_user_connected(killer)) return` |
| assist loop | `if (!is_user_connected(a)) continue` |
| `ksc_emit_break` | `if (!is_user_connected(breaker)) return` |
| `ksc_origin_str` | `if (!is_user_connected(id)) return false` |

One early-return, every zero explained — assists, cap-breaks and positions
alike.

DODX is unaffected because it keeps its **own** player array keyed off
`FL_FAKECLIENT` (`modules/dod/dodx/moduleconfig.cpp:1113`), which is why its
forwards fire perfectly while AMXX sees nobody. The comment at
`meta_api.cpp:1827` — "DODX extension hooks handle bot connect/putinserver
elsewhere" — is true of *DODX's* tracking and not of AMXX's player list. That
distinction is the whole bug.

## Proof it is not "the scenario never happened"

The obvious alternative explanation — assists need two attackers, breaks need a
capper killed mid-capture, so maybe neither occurred — was ruled out by
replaying the witness capture through the actual rule
(`scripts/../replay_assists.py` methodology):

```
deaths observed:                      53
deaths with a non-killer contributor:  8
assists the rule would emit (>=50):    7

  victim=13 killer=11 {5: 60}
  victim=1  killer=11 {14: 90}
  victim=9  killer=11 {7: 81}          ...
```

Seven qualifying assists, zero emitted. Friendly fire was off, so every
recorded damage row is enemy damage (`TA: 0` throughout) — the team check
cannot account for it.

## What this means

**Bot-driven testing of AMXX-level plugin logic is not possible in extension
mode without a KTPAMXX change.** Anything gated on `is_user_connected`,
`get_players`, `get_user_team`, `get_user_name` or `dodx_get_user_origin` will
see an empty server no matter how many bots are playing.

Three ways forward, in the order I would try them:

1. **Let fake clients through the extension-mode connect path.** A targeted
   KTPAMXX change at `meta_api.cpp:1160`, ideally behind a cvar or build flag so
   production behaviour is untouched. The Metamod path already has the
   equivalent `else if (pPlayer->IsBot())` Connect-emulation branch — the
   comment at `:1827` says so explicitly — so the shape of the fix already
   exists in the same file.
2. **Run ktpamx under Metamod for Lane B only**, where that bot-connect
   emulation already exists. Blocked today: the combined topology segfaults
   during plugin init, because ktpamx detects ReHLDS and installs hookchains
   even when Metamod is what loaded it, hooking at two layers at once.
3. **Restrict Lane B to DODX-level assertions.** Forwards fire correctly, so
   `test_dodx_forward_firing.py`'s five `BOT_AI_REQUIRED_REASON` skips can be
   un-skipped today. That does not reach the stats-capture code.

Option 1 is the smallest change and the only one that unblocks the original
goal. It is a KTPAMXX decision, not an infrastructure one.

## Topology: what works and what does not

```
WORKS (--split-layers):
  engine  → addons/extensions.ini  → ktpamx_i386.so    (unchanged from production)
  engine  → liblist.gam            → metamod_i386.so
  metamod → plugins.ini            → new_bot_mm.so     (bot only)
  metamod → +localinfo mm_gamedll  → dlls/dod.so

SEGFAULTS (metamod hosts both):
  metamod → plugins.ini → ktpamx_i386.so + new_bot_mm.so
```

ktpamx logs "ReHLDS extension mode detected" even when Metamod loads it, so in
the combined topology it installs ReHLDS hookchains from inside Metamod's chain.
Three boot attempts, three SIGSEGVs.

The A/B differential over the working topology reports **8/8, no differences**:
same three modules, same plugin count, nothing failed. Metamod's presence does
not disturb what production depends on — but note the fingerprint compares
module and plugin *loading*, and player visibility is a functional difference it
does not measure. That gap is how a "no interference" pass coexisted with a
completely blind AMXX.

## Environment facts worth not rediscovering

- **The first hlds boot in a fresh container dies in `SteamAPI_Init`**; the
  second and third with identical arguments succeed. Isolated by running the
  same command three times in one container. The harness retries 3× and reports
  the attempt count.
- **`amxx modules` / `amxx plugins` return nothing over rcon in extension
  mode.** With the server fully up, `status` returned 230 characters while both
  `amxx` commands returned 0, and the log showed "Completed initialization".
  AMXX is fine; its console output does not reach rcon's redirect buffer. The
  fingerprint reads the server log instead.
- **The runtime base image ships no `modules.ini`/`plugins.ini`** — the
  production entrypoint copies them from a mounted `/config`. Without them AMXX
  loads zero modules and zero plugins, and two empty stacks compare *equal*.
- **Use `config/local`, not `config/online`** — it is the `sv_lan 1`,
  no-Steam-auth profile and ships the full `.ini` set.
- **The docker snap has a private `/tmp`** and cannot see `/mnt/<drive>`
  (`removable-media` disconnected). Everything must live under `$HOME` on ext4.
- **Git Bash rewrites POSIX paths in `-v` arguments** when invoking `wsl.exe`,
  silently pointing mounts at `G:\...`. Run docker from a script executed inside
  WSL.

## Verified inventory

| Component | State |
|---|---|
| Lane B image (Ubuntu 24.04, glibc 2.39, MySQL 8.0.46) | builds |
| `stats_logging.amxx` from `feat/stats-positions` | compiles, 0 warnings, md5 `018b1744` |
| Ephemeral MySQL + production schema + seeds | 5/5, flags verified |
| new_bot 0.2.2 + 93 waypoints | installed, attaches, 692 waypoints on anzio |
| Metamod-R 1.3.0.149 | installed, split-layer topology boots |
| A/B differential | 8/8, no interference measured |
| Bots: connect / fight / capture | yes / 50 kills / 12 captures |
| DODX forwards under bots | all fire |
| **Capture code emitting** | **blocked — see root cause** |
| `hlstats.pl` → MySQL rows | not reached |
