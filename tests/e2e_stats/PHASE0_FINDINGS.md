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

## ✅ RESOLVED — the whole chain reaches MySQL

A live run — bots playing, daemon tailing, ephemeral MySQL — lands every row
it should, with nothing in the wrong table:

```
                log   ppa    pa
  assist          4     4     0
  cap_break       1     0     1
  kills          57    57   (frags)
  players 16 (16 bot)
  assist positions: rows 4, null 0, all_zero 0, distinct 4, max_abs 1664
  break  positions: rows 1, null 0, all_zero 0, distinct 1, max_abs 1749
```

Four live runs so far: 57/57, 95/95, 50/50 and 55/55 kills to frags, and every
emitted assist carried (4/4, 12/12, 7/7, 5/5). A replay of the earlier capture
(`scripts/replay_daemon.py`) lands 5/5 assists and 1/1 cap_break.

cap_break appeared in two of the four live runs — see the README; it is
ordinary rarity, and a run without one is reported `not_exercised` rather than
green or broken.

### The `<BOT>` authid question: answered, and it was the wrong question

`botidcheck` (hlstats.pl:1415) accepts `BOT`, `0`, and `00000000:N:0`. A bot is
given a synthetic `BOT:md5(name + server_addr)` uniqueid and created like any
other player. Both shapes Lane B produces are covered — the unpatched stack
logs `<0>`, the patched one logs `<BOT>`.

**The real gate was `IgnoreBots`, which defaults to 1.** Every handler
short-circuits to `(IGNORED) BOT:` when it is set, so the lines parse, nothing
is recorded, and nothing complains. `MinPlayers` (default 6) is the same shape
of trap for a small run. Both are written by `ensure_server_row()`.

One caveat worth knowing: the uniqueid is derived from the **name**, so two
bots sharing a name collapse into one player row. new_bot's roster is unique;
a bot kit that recycles names would produce quietly-wrong attribution.

### Four things that stopped the daemon, none of them capture-side

| Symptom | Cause |
|---|---|
| `Can't locate ConfigReaderSimple.pm` | KTPHLStatsX is a **delta-only fork** — three files. `hlstats.pl` requires seven more by path. Lane B has to reproduce production's composition (`scripts/assemble_daemon_tree.sh`). |
| Exits before printing anything | `use Syntax::Keyword::Try` in upstream's `.pm` files fails at compile time. Now in the Dockerfile and in `preflight()`. |
| `Unknown column 'a.rcon_password'` | MySQL hides from `information_schema.columns` any column the account lacks privilege on, so the reconstructed `hlstats_Servers` is faithful to what a read-only account sees and still missing the one the daemon SELECTs first. |
| `Illegal mix of collations` | The reconstruction takes the *loading* server's default collation; every dumped table carries production's. The first join between them dies. |

Both reconstruction defects are repaired at load (`repair_reconstructed_schema`)
and fixed at source (`fetch_base_schema.sh`), because the dump is taken rarely
and by hand.

### The one that looked exactly like broken capture

47 kills → 39 frags, 5 assists → **0** rows, no error anywhere.

`recordEvent` queues rows and flushes a table only when its queue passes
`$g_event_queue_size`; everything still queued is written by the `flushAll`
that runs when the daemon reaches EOF on stdin. The harness closed stdin and
SIGTERMed in the same breath, pre-empting that flush.

The damage was **selective**, which is what made it convincing: `Frags`
overflowed mid-match and survived, while the low-volume tables — exactly the
ones Lane B exists to check — were still queued and vanished. `stop()` now
waits for the daemon to exit on its own, and says so if it has to force it.

### Diagnostics are unreachable in `--stdin` mode

`printEvent` is gated on `((debug > 0) && (stdin == 0)) || ((stdin == 1) &&
force_output)`. Under `--stdin` — the only mode Lane B uses — `--debug` does
nothing, so `(IGNORED) BOT:` / `NOTMINPLAYERS:` / `NOPLAYERINFO:` never print
and a zero row count carries no explanation at all.

`assemble_daemon_tree.sh` forces that gate open in the scratch tree and records
it in `PROVENANCE`. Print-only, never deployed, `LANE_B_NO_DIAGNOSTICS=1` to
opt out.

Related trap while reading the output: **the PPA branch's `$ev_status` is
overwritten by the PA call that follows it**, so a player-vs-player action is
only ever printed as `E011`. Absence of `E010` proves nothing.

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
| Daemon tree (upstream libs + fork delta) | assembles, boots, PROVENANCE recorded |
| `hlstats.pl` → MySQL rows | **yes — every emitted line carried, across 4 live runs + replay** |
| Full green live run | **yes — 4/4 assists, 1/1 cap_break, 57/57 frags** |
| Assertions | written and unit-tested (78 passed) |

## Assertion posture, as built

`check_carried` returns one of three verdicts rather than pass/fail, because
pass/fail cannot express what a bot-driven run actually knows:

- **ok** — `rows == emitted`. Exact, not `>= 1`. The daemon should carry every
  line, so equality is the invariant — and it is what catches *partial* loss.
  The unflushed-queue bug wrote 39 rows for 47 events; a minimum-count check
  called that a pass.
- **not_exercised** — nothing was emitted, so the pipeline was not tested and
  cannot have passed. A 240s run produced one cap_break; a later 240s run
  produced none. Reporting that as either green or broken is wrong, and
  reporting it as broken is worse, because it teaches people to ignore the lane.
- **pipeline** — lines emitted, rows do not match. The only verdict that should
  stop anybody.

The flag invariant (rows in the opposite table) is checked in every case: it is
about configuration rather than volume, so a run that exercised nothing can
still catch it.
