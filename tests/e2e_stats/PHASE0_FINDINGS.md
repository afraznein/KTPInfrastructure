# Phase 0 findings — Lane B, 2026-08-09/10

What a real run established, in the order it was learned. Everything here was
observed, not reasoned.

## ✅ RESOLVED — the capture code emits

With `KTPAMXX@feat/lane-b-fakeclient-players` built using
`KTP_LANE_B_FAKECLIENTS=1`, a 240s bot match produced:

```
kills 47   assist lines 5   cap_break lines 1   dropped 0

"Claire<3><BOT><Allies>"  triggered "cap_break" (flag "POINT_ANZIO_PLAZA") (position "-83 98 -418")
"Jill<15><BOT><Allies>"   triggered "assist" against "Wesker<4><BOT><Axis>"
                          (assister_position "-417 -329 -372") (victim_position "-733 751 -404")
"GLaDOS<16><BOT><Axis>"   triggered "assist" against "Denton<10><BOT><Allies>"
                          (assister_position "2565 2983 -500") (victim_position "1287 1670 -252")
```

AMXX now sees every bot — `connected=1`, correct teams (`team=1` allies,
`team=2` axis), real names. Positions are **varied and plausible**, not the
`0 0 0` the deployment plan warns to check for. The line shapes are exactly what
`doEvent_PlayerAction` / `doEvent_PlayerPlayerAction` parse.

**Remaining unknown:** the authid renders as `BOT`. Whether `hlstats.pl` creates
players for that, or drops the rows, is the next thing to find out — it is a
daemon question, not a capture one.

## Summary of how it got there

| Question | Answer |
|---|---|
| Can bots connect, fight, capture? | **Yes** — 12–16 bots, 50 kills, 12 CP captures |
| Do DODX forwards fire for bots? | **Yes** — 107 `client_damage`, 53 `client_death` |
| Does Metamod perturb the stack? | **No measurable difference** in modules/plugins |
| Did the capture code emit *before* the patch? | **No** — 0 assists where 7 were owed |
| Why? | AMXX was blind to fake clients (below) |
| After the patch? | **Yes** — 5 assists, 1 cap_break, positions included |

## The root cause

**In ReHLDS extension mode, KTPAMXX has no code path that registers a fake
client as a player.** `pPlayer->Connect()` / `PutInServer()` / `++g_players_num`
never run for a bot.

Two `FL_FAKECLIENT` early returns look like the culprit. Neither is, and the
distinction cost real time:

| Location | Why it is not the fix |
|---|---|
| `meta_api.cpp:1160` in `SV_Spawn_f_RH` | Hooks the client `spawn` **command**. Fake clients never send commands, so this hook never runs for a bot at all — removing the return changes nothing. |
| `meta_api.cpp:1830` in `SV_ClientUserInfoChanged_RH` | Unreachable for a bot: `if (!pPlayer \|\| !pPlayer->initialized \|\| !pPlayer->ingame) return;` two lines earlier fires first, and a bot is never initialized or ingame. |

The second function *is* the right place — the engine does call it for fake
clients — but the emulation has to be inserted **above** that guard rather than
by editing the return below it.

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

### The fix, as shipped

`KTPAMXX@feat/lane-b-fakeclient-players` (`c1408a48`) adds the bot
Connect-emulation to `SV_ClientUserInfoChanged_RH` — the extension-mode
counterpart to the Metamod path's `C_ClientUserInfoChanged_Post`, which already
has an `else if (pPlayer->IsBot())` branch doing exactly this. It mirrors that
branch: `Connect` → `Authorize` → `PutInServer` → forwards.

**Placement matters more than the change itself.** The obvious target — the
`if (pEntity->v.flags & FL_FAKECLIENT) return;` at the top of this section — is
not reachable for a bot. Two lines above it,
`if (!pPlayer || !pPlayer->initialized || !pPlayer->ingame) return;` fires first,
and a bot is never either of those. The emulation has to run *above* that guard.
(The same-looking early return in `SV_Spawn_f_RH` is a red herring too: fake
clients never send a `spawn` command, so that hook never runs for them at all.)

**Containment.** Compile-time gated and off by default, so an ordinary build —
including the production Docker build — is byte-for-byte unchanged and the fleet
cannot inherit it by deploy accident. Same shape as KTPMatchHandler's
`-DKTP_TEST_MODE`. Opt in at configure time:

```bash
KTP_LANE_B_FAKECLIENTS=1 python3 configure.py --enable-optimize --no-mysql --no-plugins
```

The build prints a `*** NOT FOR PRODUCTION ***` banner when it is on.
`scripts/build_ktpamx_laneb.sh` does the whole build in a container.

### Alternatives not taken

- **Run ktpamx under Metamod for Lane B**, where the emulation already exists.
  Blocked: the combined topology segfaults during plugin init, because ktpamx
  detects ReHLDS and installs hookchains even when Metamod loaded it.
- **Restrict Lane B to DODX-level assertions.** Forwards fire correctly, so
  `test_dodx_forward_firing.py`'s five `BOT_AI_REQUIRED_REASON` skips can be
  un-skipped regardless of this work. But it never reaches the capture code.

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
| Patched ktpamx (`KTP_LANE_B_FAKECLIENTS`) | builds, bots register as players |
| A/B differential | 8/8, no interference measured |
| Bots: connect / fight / capture | yes / 50 kills / 12 captures |
| DODX forwards under bots | all fire |
| **Capture code emitting** | **yes — 5 assists + 1 cap_break with positions** |
| `hlstats.pl` → MySQL rows | next — open question is whether the daemon accepts `<BOT>` authids |
