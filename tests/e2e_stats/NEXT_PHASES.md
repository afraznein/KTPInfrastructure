# Lane B — next phases

## Deferred, deliberately

These are real gaps with an owner-less status. They are parked rather than
forgotten, and each says what would make it worth picking up.

### KTPMatchHandler HEAD fails to compile against the image's amxxpc

Found 2026-08-13 running a full Units 1–6 regression with real match
tagging. `KTPMatchHandler` `main` (`c24b1b5`) fails with `undefined symbol`
on `dodx_get_aim_stats`/`dodx_get_aim_window`/`dodx_reset_aim_stats` — three
natives that genuinely exist in KTPAMXX's current `dodx.inc`. Bisected: the
problem is not the include path (pointing the compiler at KTPAMXX's own
fresh includes doesn't fix it) but the long `/** ... */` doc comments
immediately preceding those three natives in `dodx.inc` — stripping them,
nothing else, fixes it. A doc-comment parser bug in the image's `amxxpc`
2.7.26.1, not a missing declaration.

**Why it is parked:** it isn't Lane B's bug to fix — it's in
`KTPMatchHandler`/`dodx.inc`, repos this project consumes, not owns. Lane B
worked around it for the regression checkpoint by pinning `KTPMatchHandler`
to `7db55e5` (the commit before the one that introduced those natives), via
`git archive`, not by touching the branch.

**When to pick it up:** before the next time `KTPMatchHandler` needs to be
compiled against current `main` for anything besides a quick Lane B check —
the pin is a workaround for testing, not a fix, and it means Lane B is not
actually exercising `KTPMatchHandler`'s latest fixes (`0.10.157`'s
"refuse to run a half with no match id," `0.10.158`'s weapon stats reset,
the buffer/retention work) until this is resolved.

**How, in one line:** either shorten/restructure the three doc comments in
KTPAMXX's `dodx.inc` around `dodx_get_aim_stats`/`dodx_get_aim_window`/
`dodx_reset_aim_stats`, or rebuild the base image with a newer `amxxpc`.
`scripts/lane_b_e2e.py`'s `compile_sma()`/`build_test_mode_matchhandler()`
now take an `include_dir` override (`--matchhandler-includes`) so a fresh
KTPAMXX checkout's natives are always visible — that wasn't the cause here,
but it was a real gap in its own right and is fixed regardless.

### The bazooka assist mis-attribution

A killer was credited an assist on their own kill, once in 225 kills, on a
bazooka. Full write-up in `KTPR_DEPLOYMENT_PLAN.md` under Unit 2.

**Why it is parked:** the bazooka is not available on most maps, so the
exposure in real matches is much smaller than one-in-225 suggests. Three
subsequent full 20-minute matches produced **zero** attribution violations,
which is consistent with that.

**When to pick it up:** before Phase 8 has KTPR consume assists. A killer
collecting both the frag and an assist for the same death is double-credited,
and a rating that reads assists will inherit it.

**How, in one line:** replay a rocket death through
`dodx_test_dispatch_client_death` with a known killer index and log what
`ksc_on_death` actually receives — the hypothesis is that DODX reports a
different index for splash damage than the engine credits in the log line.
`log_invariants.check_assist_attribution` already detects the symptom.

### Waypoints for the KTP competitive maps

See the section below. Parked because it is potentially large — waypointing is
manual, in-game work — and nothing currently blocked depends on it.

**When to pick it up:** before Phase 7 (break context: contester count,
last-flag defence, ninja caps). That work is position- and layout-aware, and
validating it only on `dod_anzio` would prove very little about the maps KTP
actually plays.

## Backlog: waypoints for the KTP competitive maps

Lane B can only run `dod_anzio` as a KTP match. The image ships 22 stock DoD
maps that have new_bot waypoints, but **none of the KTP competitive rotation**
— `dod_armory_b6`, `dod_harrington`, `dod_railroad2_s9a`, `dod_railyard_b6`,
`dod_lennon5_b1` (see `KTPMatchHandler/ktp_maps.ini`) — are among them. They
are custom maps, so they have neither a BSP in the image nor a `.wpt`.

Until that is fixed, every fixture and every staged scenario is anzio-shaped.
That is a real limitation for anything position-aware: the cap-break detector,
`pos_x/y/z`, and later the last-flag-defense and ninja-cap work in Phase 7 all
behave per map layout.

Two pieces of work, in order: get the KTP map BSPs into the Lane B image, then
generate waypoints for them (new_bot has an in-game waypoint editor; the
alternative is sourcing community `.wpt` files where they exist).



Written after Phase B closed. Two pieces of work, in this order:

1. **Phase B½ — the synthetic match.** Rows that carry `match_id` and `half`,
   driven by a match that is real to every part of the stack that reads it and
   invisible to everything outside the container.
2. **CI wiring.** Get the nightly running on GitHub.

**Order matters.** The CI workflow has to be rewritten anyway (it is stale), and
the synthetic match changes what CI runs. Doing CI first means writing it twice.

---

# Phase B½ — the synthetic match

## Why this is the biggest untested surface

Every row Lane B has ever produced has `match_id NULL`.

Match tagging is the entire reason KTPHLStatsX is a fork. `%g_ktpMatchContext`,
freeze-time exclusion, per-half attribution — none of it has been exercised
once, and KTPR reads exactly those match-scoped stats. A `NULL` match_id is
*correct* for warmup, which is why nothing has complained; it also means the
feature is at 0% coverage.

Concretely, `recordEvent` (hlstats.pl:331-338) injects `match_id` **only while
`round_live`**, and `half` lands on `Frags`, `Suicides`, `Teamkills` and
`Statsme`. `PlayerActions` / `PlayerPlayerActions` carry `match_id` alone. So
the assist and cap-break rows Lane B already proves are, today, all untagged.

## Most of this already exists

| Piece | State |
|---|---|
| `amx_ktp_test_*` rcons in KTPMatchHandler | **built**, 16 commands, behind `-DKTP_TEST_MODE`, compiles to zero bytes without it |
| `tests/integration/match_flow.MatchDriver` | **built**, wraps every rcon, raises `MatchDriverError` with the server's own reason |
| `tests/e2e_stats/match_runner.py` | **written, never run.** Composes MatchDriver + bots + the ordering, and already documents why `fire_match_start_log` and `end_match` are load-bearing |
| Daemon side | **built.** Parses `KTP_MATCH_START` / `_END` / `KTP_HALF_END` / `KTP_ROUND_FREEZE` / `KTP_ROUND_LIVE` |

So this phase is mostly *wiring*, not new machinery. The one genuinely new
thing is the containment work below.

## Work

### 1. A test-mode KTPMatchHandler build

The image ships `KTPMatchHandler.amxx` compiled **without** `KTP_TEST_MODE`, and
no `.sma` sources, so the rcons are absent — they are zero bytes in that binary.

Mirror the pattern already used for `KTP_LANE_B_FAKECLIENTS`
(`scripts/build_ktpamx_laneb.sh`): check out KTPMatchHandler, compile with
`amxxpc -DKTP_TEST_MODE` inside the image, overlay the result. Production builds
are untouched and cannot inherit it by deploy accident.

Cheaper than the ktpamx build — one `.sma` through `amxxpc`, seconds, not a full
C++ compile.

### 2. Containment — "nothing reaches the mothership"

Today nothing escapes, but **by accident**: Discord and HLTV URLs happen to be
blank in `config/local`, and the HUD observer happens to POST at an unreachable
`localhost`. Accidental safety is not safety. A config that later grows a URL
would have CI posting to a real Discord channel with no warning.

Make each one positive:

| Surface | Now | Make it |
|---|---|---|
| Discord (`discord.ini`) | blank by convention | **asserted blank at run start**; abort the run if any `discord_*_url`/webhook is set |
| HLTV (`hltv_recorder.ini`) | blank by convention | same assertion |
| HUD observer | POSTs to `localhost`, fails with `code 7`, floods the log with hundreds of lines | **drop `KTPHudObserver.amxx` from the Lane B plugin list.** It is a local-dev addition, not production's set, and its noise buries real output |
| Match identity | `<systime>-TEST` already | **assert the `-TEST` suffix** on the driven match_id, so a Lane B match can never be mistaken for a real one in any database it somehow reaches |

Worth evaluating, as belt and braces: run the container with `--network none`.
Nothing in the lane needs egress — MySQL is a unix socket, hlds binds loopback,
rcon is same-container, and Steam init already fails. If it works it turns
"we blanked the URLs" into "it is not physically possible". Needs testing;
loopback behaviour under `--network none` is the thing to check.

### 3. Wire `match_runner` into `lane_b_e2e`

Replace the current `add_bots` → `play` with the documented ordering:

```
fill bots → setup_match → advance_pending → advance_live(1) → fire_match_start_log
          → PLAY  → end_first_half
          → advance_live(2) → PLAY → end_match → drain
```

Two things in there are load-bearing rather than tidy, and `match_runner.py`
already says why:

- `fire_match_start_log` — production emits `KTP_MATCH_START` from a task gated
  on the engine's `RoundState=1`, which never fires without a real round.
- `end_match` — calls `dodx_flush_all_stats()`, which fires the
  `dod_stats_flush` forward.

  > **Correction.** This was predicted to close the one Unit 2 gap by
  > populating `hlstats_Events_Statsme`. It does not, and driving a real match
  > proved it: zero rows, and zero `weaponstats` lines in the game log to
  > produce them from. `stats_logging.sma`'s handler opens with
  > `if ( is_user_bot(id) || ... ) return PLUGIN_CONTINUE` — **weaponstats are
  > never logged for bots**. Every Lane B player is a bot, so the table is
  > structurally unreachable here and no amount of match driving changes that.
  > Unit 2 step 6 still needs a human on a server with real clients.

Keep the kill-switch window and the staged break scenarios; they slot in around
the play windows.

### 4. New assertions

The point of the phase. Each is exact, because match tagging is deterministic —
unlike bot behaviour, the daemon either tags a row or it does not.

| Assertion | Catches |
|---|---|
| Frags during live play carry the driver's `match_id` | match context never established |
| `half` ∈ {1,2} and matches the half being played | half tracking wrong or stale |
| **Kills during `KTP_ROUND_FREEZE` carry `match_id NULL`** | the fork's central claim — freeze-time kills excluded by design |
| Assists and cap-breaks during live play carry non-NULL `match_id` | the new stats are not match-attributable, which is what KTPR needs |
| Rows after `KTP_MATCH_END` are untagged again | context not cleared; every later warmup kill would join the last match |
| `weaponstats` lines, if any, become `Statsme` rows | Unit 2 step 6 — **cannot fire on an all-bot lane**; reported `not_exercised` with the reason rather than passed |
| `match_id` ends in `-TEST` | containment |

The freeze-time one is the sharpest: it is the difference between "match stats"
and "everything that happened near a match", and it has never been checked.

### 5. Known unknowns

Flagging these because they are where the estimate could be wrong:

- **Does the halftime swap survive bots?** `end_first_half` → `advance_live(2)`
  may restart the round and reshuffle teams; new_bot's reaction is unknown.
- **Does `match_runner` still match the current MatchDriver?** It was written
  against it but never executed together — expect at least one signature drift.
- **Ordering against the daemon.** `KTP_MATCH_START` has to arrive after the
  daemon has resolved the server row, or the context attaches to nothing. Same
  class as the action-seed ordering trap, and it should be enforced in code the
  same way rather than left to luck.

---

# CI wiring

## Current state: exists, never run, and stale

`.github/workflows/lane-b-stats-e2e.yml` was written before the lane worked. It
still:

- runs `scripts/spike_bot_lane.py` (the Phase 0 probe) rather than
  `scripts/lane_b_e2e.py`
- defaults to `marinebot`, which was never the bot that worked
- applies `ktp_schema.sql` as the schema, which **cannot run on MySQL at all**
  (`ADD COLUMN IF NOT EXISTS` is MariaDB-only) and is an overlay, not a base
- fetches a bot kit from a secret, which is now obsolete — the Dockerfile
  installs new_bot at build time, SHA-pinned
- knows nothing about the daemon tree, which did not exist yet

The good parts to keep, all of which are already reasoned out in the file's own
header: GH-hosted runner (never the Tier 2 box), no `pull_request` trigger,
non-gating, 06:00 UTC between the base-image build and Tier 2's nightly.

## Work

### 1. Replace the run step

Drive `lane_b_e2e.py` with the same arguments `run_e2e.sh` uses locally. Delete
the bot-kit fetch and the `LANE_B_BOT_KIT_URL` secret dependency.

### 2. Add the daemon-tree assembly

`scripts/assemble_daemon_tree.sh` needs network (it fetches pinned upstream) and
must run before the container. Publish `PROVENANCE` as an artifact so every run
records whether it used production libs or the reconstruction.

### 3. Decide where the base schema comes from — the real blocker

The runner has no production access, and `base-schema.sql` is currently a local
artifact taken by hand.

**Recommendation: commit it.** It is 64 `CREATE TABLE`s and **0 `INSERT`s** —
DDL, no data, no credentials. `fetch_base_schema.sh` already produces exactly
that, and now includes the two reconstruction fixes (`rcon_password`,
collation). Committing it also makes the lane reproducible rather than dependent
on one laptop's `~/lane-b-out`.

The alternative — a secret or a fetched artifact — buys nothing, since there is
nothing sensitive in it, and adds a failure mode.

Worth doing at the same time: re-take the dump with `--from-production` so the
committed copy is production's own DDL, and the reconstruction fallback becomes
a documented curiosity rather than the default. That needs SSH.

### 4. Decide how the patched ktpamx gets built

`ktpamx_i386.so` with `KTP_LANE_B_FAKECLIENTS` is currently built by hand
(`scripts/build_ktpamx_laneb.sh`) and copied into `~/lane-b-out`. Without it,
AMXX cannot see bots and the whole lane is blind — this is not optional.

Three options:

| Option | Cost | Note |
|---|---|---|
| Build it in the same job | ~10 min per nightly | simplest, slowest |
| Separate job + `actions/cache` keyed on the KTPAMXX ref | fast after first run | recommended |
| Bake into a published image layer | fastest | another image to keep current; couples the test binary to the image |

Recommend the cached job: the ref changes rarely, so the cache hits almost
always, and a miss is a slow run rather than a broken one.

### 5. Make the three-way verdict survive CI

`lane_b_e2e.py` distinguishes `ok` / `not_exercised` / `pipeline`. GitHub has
only pass/fail for a step, and collapsing the middle one would undo the point of
having it.

- **fail** the job on any `pipeline` verdict or assertion failure
- **do not fail** on `not_exercised`; emit `::warning::` per gap and write them
  into `$GITHUB_STEP_SUMMARY` so the run page says what was not tested
- put the emitted-vs-recorded table in the step summary too — it is the first
  thing anyone will want and it should not require downloading an artifact

A run where everything is `not_exercised` is green today and says nothing. Worth
a floor: if *no* scenario staged and *no* action carried, fail — that is a
broken lane, not a quiet one.

### 6. Artifacts

Report JSON, the game log, the daemon stdout, and `PROVENANCE`. The game log is
the one that matters — every diagnosis in this project so far started there —
and `replay_daemon.py` can re-run the daemon leg from it without bots, so a
nightly failure is reproducible from its own artifact.

## Sequencing

1. Phase B½ (synthetic match), locally, until it is green
2. Commit the base schema
3. Rewrite the workflow once, against the finished lane
4. `workflow_dispatch` it by hand until it passes
5. Let the schedule take over

Steps 1 and 3 are the work; 2 and 4 are small. Step 2 is the only one that could
be blocked on someone else, and only if you want production's DDL rather than
the reconstruction.
