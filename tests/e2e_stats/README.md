# Lane B — stats-capture end-to-end (bots + ephemeral MySQL)

Proves the assist / cap-break / position capture actually lands rows in MySQL,
by putting bots on a throwaway server and querying a throwaway database.

Design and rationale: [`../integration/STATS_CAPTURE_E2E_DESIGN.md`](../integration/STATS_CAPTURE_E2E_DESIGN.md).
What it verifies: [`../../docs/ktpr_mcp/KTPR_DEPLOYMENT_PLAN.md`](../../docs/ktpr_mcp/KTPR_DEPLOYMENT_PLAN.md).

**Status: end to end, green, and covering all four deployment units.** One live
run:

```
  assist       ok   5/5 carried          kills 66 -> 66 frags
  cap_break    ok   1/1 carried          players 16 (16 bot)
  suicide      ok   2/2 carried          assist positions: 5 rows, 5 distinct
  headshot     ok   13/13 carried        break  positions: 1 row, max_abs 1207
  kill_switch  ok   10 kills produced 0 assists while off; 5 once re-enabled
  attribution  0 violations
``` What each leg cost to get there is in
[`PHASE0_FINDINGS.md`](PHASE0_FINDINGS.md) — read it before debugging anything
here.

Two entry points:

| Script | What it proves | Cost |
|---|---|---|
| `scripts/replay_daemon.py` | daemon → MySQL, from a captured log | seconds, deterministic |
| `scripts/lane_b_e2e.py` | the whole chain, bots included | ~5 min, bot-dependent |

Use the replay while iterating. It is deterministic because the input is a file
someone already captured, so a red result is always a real change — and it can
reproduce a nightly failure from its artifact without re-rolling the dice on
bot AI.

Both need a daemon tree assembled first (`scripts/assemble_daemon_tree.sh`):
KTPHLStatsX is a delta-only fork of three files, and `hlstats.pl` requires
seven more that only exist on production or upstream.

## Why this lane exists

Every emit path in `ktp_stats_capture.inc` is gated on `is_user_connected()`,
and the cap-break detector's only input is a live poll of
`dodx_area_get_data(...)` zone occupancy. So the deterministic Tier 2 lane
cannot reach this feature at all: a synthetic `dodx_test_dispatch_client_death`
on an empty server returns at the first guard and emits nothing. A test built
that way would pass while proving nothing.

Real bodies in real zones are the only way. That is what this lane buys, and
it is why it is separate from — not a replacement for — Tier 2.

## The containerised path is the primary one

`build/lane-b/` builds an image `FROM ghcr.io/<owner>/ktp-runtime-test-base`
adding MariaDB, the Perl DBI stack, and the 32-bit runtime a bot `.so` needs.
Run it on a GitHub-hosted runner via
[`.github/workflows/lane-b-stats-e2e.yml`](../../.github/workflows/lane-b-stats-e2e.yml),
or locally with `build/lane-b/docker-compose.lane-b.yml`.

This supersedes most of the original host-based design, for four concrete
reasons:

1. **`amxxpc` is already in the base image** at
   `/opt/hlds/dod/addons/ktpamx/scripting/amxxpc`, and `smoke-callable.yml:324`
   already compiles plugins by `docker run`-ing it. The "no AMXX toolchain"
   problem was self-inflicted.
2. **The container filesystem is ephemeral and isolated by construction**, so
   there is no fleet-matching tree to contaminate — hence `EphemeralTree.in_place()`,
   which skips the copy entirely. Copying 2 GB inside a container that is itself
   thrown away buys nothing.
3. **It pins glibc to Ubuntu 22.04's 2.35**, below the 2.41 threshold where the
   loader refuses shared libraries needing an executable stack. That is the most
   likely reason a 20-year-old DoD bot `.so` fails on a modern host, so
   controlling glibc is a real advantage rather than a side effect.
4. **It runs nowhere near production.** The Tier 2 runner is on the data server,
   which also runs production HLStatsX and is deliberately Docker-free.
   GH-hosted has Docker, no production anything, and no route to the fleet.

⚠️ **What the image does not give you.** It is a *reconstruction* of the fleet
built from repo refs. The real fleet is bare metal — 5 hosts, artifacts staged
as `.new` and swapped at the 03:00 ET restart (`docs/DEPLOYING.md`). So green in
Lane B means "this branch's code works against this branch's stack", which is
what you want when testing a branch. It does **not** mean "works against what is
currently deployed". That question still belongs to the Tier 2 runner's
fleet-matching tree and its drift tripwire, and nothing here retires either.

The bot is **not baked into the image** — Marine Bot / new_bot are third-party
and not ours to redistribute, and an image pushed to GHCR would publish them. It
is mounted at run time (`-v ./bot-kit:/opt/bot-kit:ro`), which also keeps the
image publishable and bot-free.

The host-based modules below still work and are still tested; use them when
running without Docker. `EphemeralTree.build()` (copy + integrity guard) is the
default everywhere outside the container, and `in_place()` must never be pointed
at a fleet-matching tree.

## Three hard constraints, and how they are met

**1. Do not contaminate the fleet-matching tree.** `help.md` requires
`/opt/ktp-tier2-runner/serverfiles` to match the live fleet; drift is tripwired
and re-sync is manual. A bot `.so` in there is that drift.
→ `ephemeral_tree.py` copies the tree per run and overlays the bot in the copy.
Read its module docstring before editing: hardlink copies make a naive
`open(path, "w")` write *through* to the source, and there is an integrity
check that fails the run loudly if that ever happens.

**2. The runner is Docker-free.** So "ephemeral MySQL" is a second `mysqld`
with a private datadir/socket/port, not a container — `ephemeral_mysql.py`.
It runs as an unprivileged user, is loopback-only, uses `--no-defaults` so it
cannot inherit `~/.my.cnf` (which on the data server points at the **live**
server), and is deleted on teardown.

**3. The bot must never reach production.** Quarantine, all five of these:

| Rule | Mechanism |
|---|---|
| Bot lives outside any fleet-matching tree | `bot-kit/` root, passed via `--bot-kit` |
| Not committed here | `.gitignore` covers `bot-kit/` and `*.so` under it |
| Not in any deploy manifest | KTPFileDistributor and the Docker plugin build have no path to it |
| Nothing *in* the tree enables it | loads via command-line `+localinfo mm_gamedll`, never `plugins.ini` — so a copy of the tree booted normally has no bot |
| Doesn't outlive its run | ephemeral tree deleted on teardown |

## Sturmbot does not work here — use Marine Bot

Sturmbot was the first choice but is not viable on a Linux runner:

- current release (1.9, Oct 2019) is a **Windows installer only**
- the legacy Linux build is 1.5.1 targeting **DoD 3.1B, not 1.3**, and modern
  glibc/loader versions break essentially all legacy bot `.so` binaries

Per sturmbot.org's own [Linux DoD-with-bots guide](https://sturmbot.org/index.php/marine-bot/132-linux-dod-dedicated-server-setup-on-a-lan-with-bots),
the Linux-viable DoD 1.3 bots are **Marine Bot** and **new_bot** (0.2.0+), both
loaded as Metamod plugins via `+localinfo mm_gamedll <bot>/<bot>.so`.

Marine Bot is primary (maintained modern Linux build). `new_bot` is the
fallback, and can convert Sturmbot waypoints if Marine Bot's per-map coverage
turns out thin. Swapping between them is one `--bot` flag; see `bot_driver.py`.

### new_bot 0.2.2 is installed by the image

`build/lane-b/Dockerfile` downloads and installs it at build time from
[the installer page](https://dayofdefeat.home.blog/installer-2/), **pinned by
SHA-256** (`8f659fe1…`) so a changed or replaced upstream artifact fails the
build instead of silently swapping the bot under a lane whose job is trusting
what it ran. Override with `--build-arg NEW_BOT_URL=file:///vendor/...` when the
Drive link rots or the build host is offline.

Installed and verified in the image: `dod/new_bot/new_bot_mm.so` (442 KB, 0755)
and **93 waypoint files**, covering the real KTP pool — `dod_anzio`,
`dod_avalanche`, `dod_jagd`, `dod_donner`, `dod_flash`, `dod_kalt`, `dod_caen`,
`dod_merderet`, `dod_charlie`, `dod_sturm`. Upstream changelog is dated
**13-07-2026**, so this is maintained software, not abandonware.

Because the image now contains a third-party binary that is not ours to
redistribute, **it must not be pushed to a public registry.** It is a local/CI
artifact. The fleet consumes no images at all, so nothing here can reach
production by accident.

`BotSpec.NEW_BOT` now carries **facts read from the shipped `_README.txt` /
`_COMMANDS.txt`**, not guesses — `addbot {team} {class} {skill} {name}` (team
accepts `allies`/`axis`), `target_players {0-32}` to fill, and the objective
knobs `flag_priority_percent` / `wait_for_cap_percent` (defaults 70/75, raised
to 100 so bots go to flags and stay on them, which is what cap-break capture
needs). Two earlier guesses were wrong: the binary is `new_bot_mm.so`, not
`new_bot.so`, and it lives at `dod/new_bot/`, not under `dod/addons/`.

`MARINEBOT`'s command names remain **candidates**; `probe_add_command` tries
them in order and reports which works.

### ✅ RESOLVED: bots run, in a split-layer topology

Phase 0's core premise is verified. Run
`scripts/spike_metamod_ab.py --split-layers`:

```
[PASS] boot-A: 3 modules, 1 plugins          (production topology)
[PASS] boot-B: 3 modules, 1 plugins          (metamod-split)
[PASS] required-modules: amxxcurl + reapi + dodx present under BOTH
[PASS] non-interference: module and plugin sets/statuses identical
8/8 steps ok, exit 0
```

and in ~60s of bot play on `dod_anzio`:

| Evidence | Count |
|---|---|
| `entered the game` / `joined team` / `changed role to` | 12 / 12 / 12 |
| `" killed "` (thompson, luger, mp40, k43) | 10 |
| `triggered a "dod_control_point"` / `"dod_capture_area"` | 10 |
| `Waypoints loaded` | 692 |

**Bots fight and capture flags.** Those are precisely the two inputs the capture
code needs: kills drive assist attribution and cap-break candidacy, and flag
contention drives the `dodx_area_get_data` zone poll.

`[KTP-STATS] 0` is expected — the image still carries the *stock*
`stats_logging.amxx` from the base image, not the branch build. Staging the
compiled one (md5 `018b17442ef4ef352623428eebe93200`) is the next step.

#### The topology that works: split layers

    engine  →  addons/extensions.ini  →  ktpamx_i386.so       (unchanged from production)
    engine  →  liblist.gam            →  metamod_i386.so
    metamod →  plugins.ini            →  new_bot_mm.so        (bot only)
    metamod →  +localinfo mm_gamedll  →  dlls/dod.so

Each loads **once, at its own hook point**. ktpamx still logs "Running without
Metamod - using ReHLDS hookchains", exactly as production.

The obvious topology — Metamod hosting *both* ktpamx and new_bot — **segfaults**,
3 attempts of 3. ktpamx reports "ReHLDS extension mode detected" even when
Metamod loads it, so it installs ReHLDS hookchains from inside Metamod's chain
and hooks at two layers at once. Use `--split-layers`; it is the default for
`enable_metamod(host_ktpamx=False)`.

### Why the bot cannot live inside KTPAMXX

Worth recording, because it looks plausible: AMX Mod X is **not** a fork of
Metamod, it is a Metamod *plugin* (hence `ktpamx_i386.so` exporting
`Meta_Attach`). Its module system is a separate API.
`CModule::queryModule()` does check modules for `Meta_Attach`, but only to label
them `"amxx&mm"` — it still requires `AMXX_Query` and rejects anything else as
`MODULE_NOQUERY`. `new_bot_mm.so` has **0** occurrences of `AMXX_Query` and
**1** of `Meta_Attach`, and the engine says so directly:

```
[AMXX] Couldn't find "AMXX_Query" (file ".../new_bot_mm_ktp_i386.so")
```

So Metamod is required. The split-layer topology is how it coexists.

### Historic blocker (resolved above): new_bot needs Metamod

new_bot's `_mm` suffix is literal. Its README: *"new_bot is a metamod plugin, so
you need to add it to the plugins.ini file in your metamod install and not
config.ini or it will crash."*

The KTP stack is **Metamod-free**. Verified inside the image:

```
/opt/hlds/dod/addons/  →  extensions.ini, ktpamx
extensions.ini         →  addons/ktpamx/dlls/ktpamx_i386.so
liblist.gam            →  gamedll_linux "dlls/dod.so"
find /opt/hlds -iname "*metamod*"  →  (nothing)
```

AMXX loads through ReHLDS's **extension** mechanism, not Metamod — which is
also why `CreateFakeClient` is unavailable and why the DODX tests needed
dispatch primitives. There is no plugin loader for new_bot to register with.

So the files are installed but **deliberately not activated**.
`BotKit.activation_blocker()` reports this as a fact rather than crashing, so a
Phase 0 run says why instead of timing out.

Making it work requires Metamod installed and inserted between the engine and
`dlls/dod.so`, with `ktpamx` still loading via `extensions.ini`. Whether those
two coexist is **unverified** — and it means the bot lane would run a different
loader topology than production. That is a deliberate decision about the stack
under test, not a build detail, so it is not made here.

Possible extra step on newer distros: glibc 2.41+ refuses shared libraries
needing an executable stack unless the main binary does too. Fix is
`execstack -c addons/amxmodx/dlls/amxmodx_mm_i386.so`. Whether this runner
needs it is a Phase 0 finding.

## Layout

```
bot-kit/                     (NOT in this repo — you create it)
  marinebot/
    marinebot.so
    wps/                     waypoints, per map
```

```
tests/e2e_stats/
  artifacts.py         build/collect the artifact set from branch refs
  ephemeral_tree.py    per-run serverfiles copy + bot overlay + integrity guard
  ephemeral_mysql.py   private mysqld, schema/migration/seed loading
  hlstats_daemon.py    hlstats.pl in --stdin mode, fed from the game log
  bot_driver.py        bot adapter: staging, add-command probing, team filling
scripts/
  build_stats_lane_artifacts.py   the build step
  spike_bot_lane.py               Phase 0 — answers the unknowns, asserts nothing
```

## The build step

Lane B tests a *branch*, so it needs that branch's artifacts from two repos:

| Artifact | Repo | Built? |
|---|---|---|
| `stats_logging.amxx` | KTPAMXX (+ `ktp_stats_capture.inc`) | compiled with amxxpc |
| `hlstats.pl` | KTPHLStatsX | no — Perl, copied |
| `ktp_schema.sql`, `migrate_00*.sql` | KTPHLStatsX | no — copied |

Everything is extracted with `git show <ref>:<path>`, never read from a working
tree — "the tests passed" has to mean "passed against this commit". A manifest
records every SHA and md5, so a result is traceable to exact bytes the same way
the deployment plan insists deploys are verified by md5 rather than by console
banner.

```bash
# Daemon + SQL only — needs no AMXX toolchain, runs anywhere
python3 scripts/build_stats_lane_artifacts.py \
    --amxx-repo   ../branches/KTPAMXX       --amxx-ref   feat/stats-positions \
    --daemon-repo ../branches/KTPHLStatsX   --daemon-ref feat/seed-cap-break-action \
    --no-plugin --out build/lane-b

# Full set, compiling the plugin locally
python3 scripts/build_stats_lane_artifacts.py \
    ... --amxxpc ~/ktpamx/scripting/amxxpc \
        --includes ../branches/KTPAMXX/plugins/include
```

Three ways to get the compiled plugin: `--amxxpc` (compile here),
`--prebuilt-plugin` (adopt a Docker-build or CI artifact), `--no-plugin`
(daemon + SQL only). The runner is Docker-free, so the Docker plugin build stays
on a Docker-capable machine or a GH-hosted runner and the artifact is passed in.

Two constraints the builder encodes rather than documents:

- **`stats_logging.sma` and `ktp_stats_capture.inc` must be siblings.** The
  `.sma` includes the `.inc` by relative path; the production Docker build
  needed a dedicated `COPY` line for it, and the mismatched-pair failure is in
  the deployment plan ("amxxpc fails: cannot read ktp_stats_capture.inc").
- **A failed compile is fatal.** `build/plugins/Dockerfile` ends each compile
  with `|| echo "WARNING: $name may have had errors"`, so a broken plugin does
  not fail that image build. Survivable when a human inspects the output;
  useless in a test lane, where the run would proceed against a stale or absent
  plugin. `compile_plugin()` raises — including when amxxpc exits 0 having
  written nothing.

## The daemon step

`hlstats.pl` runs in **`--stdin` mode**, fed by a thread tailing the ephemeral
server's log:

```
hlstats.pl --stdin --server-ip 127.0.0.1 --server-port <port> --db-host localhost;mysql_socket=...
```

Stdin mode disables the UDP listener *and* sets `$g_rcon = 0`, which is worth
having for free — a test daemon that rcons the server under test is a moving
part with no upside. Feeding the log directly also takes UDP loss and reordering
out of a test that exists to prove attribution logic. `--server-ip` and
`--server-port` are mandatory there; the daemon exits 255 without them.

Two prerequisites, both enforced in code because both fail *silently*:

- **`hlstats_Servers` row** matching address+port, or lines have no server to
  attach to (`ensure_server_row`).
- **Action seeds loaded before the daemon starts**, because it caches
  `hlstats_Actions` in memory at boot.

⚠️ **Unverified:** whether stdin mode wants log lines with the engine's
`L 08/09/2026 - 12:00:00: ` prefix intact, and whether `--timestamp` should be
passed. `strip_prefix` and `timestamp_flag` make the answer a config change;
the default feeds lines exactly as the engine wrote them, which is what a UDP
forward would have delivered. Phase 0 settles it.

## Verified so far (2026-08-09, real runs)

The image was built and exercised for real. What is now proven rather than
reasoned:

- **The Lane B image builds** on `ghcr.io/afraznein/ktp-runtime-test-base:latest`
  (which is **public** — no GHCR auth needed). Base is **Ubuntu 24.04.4,
  glibc 2.39** — note that is *not* `build/base/Dockerfile`'s Ubuntu 22.04; the
  runtime image is built separately.
- **`stats_logging.amxx` compiles** from `feat/stats-positions` with the capture
  include — **0 warnings**, md5 `018b17442ef4ef352623428eebe93200`, 9353 bytes.
  This retires open verification debt #2 in `CONTINUATION_NOTES.md`
  ("Nothing is compiled").
- **The private `mysqld` starts** as root inside the container and accepts
  connections.
- **Unit suite passes inside the image**: 40 passed (Linux path, including the
  symlink case that skips on Windows).
- **Artifact md5s are identical on Windows and Linux**, so the manifest is
  meaningful provenance rather than decoration.

### The database half now passes end to end

```
[PASS] mysqld-private-instance: up (MySQL 8.0.46 — same version string as production)
[PASS] schema-load: applied 1 schema + 2 seed file(s) to an empty database
[PASS] schema-tables: 64 tables present
[PASS] seed-assist:    for_PlayerActions=0 for_PlayerPlayerActions=1, reward 0
[PASS] seed-cap_break: for_PlayerActions=1 for_PlayerPlayerActions=0, reward 0
```

Those last two are the deployment plan's most dangerous check — flags the wrong
way round record every event twice and double-apply the reward — now verified
automatically instead of by hand.

### MySQL, not MariaDB — this is load-bearing

The image installs `mysql-server`, matching production's MySQL 8.0.46. That is
not a preference:

`sql/ktp_schema.sql` uses `ADD COLUMN IF NOT EXISTS` / `CREATE INDEX IF NOT
EXISTS`, which is **MariaDB-only syntax**. On MySQL it fails outright:

```
ERROR 1064 (42000) at line 22: ... near 'IF NOT EXISTS match_id VARCHAR(64) ...'
```

aborting before every later statement. The file's own header documents this and
warns the hazard is a *fresh* install — LAN data-server provisioning — where it
"silently applies almost nothing". The lane reproduced that on its first real
run against MySQL. **On the MariaDB build the same run passed**, which is
exactly the false confidence this lane exists to prevent.

Consequence for the project, not just the tests: `ktp_schema.sql` still needs
porting to plain `ALTER`s before any fresh MySQL install relies on it. Its own
header says so.

### Getting the base schema

`sql/ktp_schema.sql` is an **overlay, not a schema** — 8 `ALTER TABLE`, 3
conditional `CREATE TABLE`, 4 indexes, all assuming stock HLStatsX tables
already exist. There is no base schema in any repo, so Lane B takes one from
production:

```bash
scripts/fetch_base_schema.sh              # run on the data server, READ-ONLY
# → ~/base-schema.sql : 64 tables, 0 INSERTs, no credentials
```

Copy it to `$LANE_B_OUT/base-schema.sql` and `scripts/lane_b_local.sh` picks it
up automatically.

Two grant limitations, both legitimate and handled rather than routed around:

- **`hlstats_Servers` is denied** to the read-only account, because HLStatsX
  keeps per-server rcon configuration there. The script reconstructs the table
  from `information_schema` metadata — types, nullability, defaults, indexes —
  reading no values.
- **Views are denied** (`SHOW VIEW`), and mysqldump aborts the moment it walks
  into one, so the table list is enumerated explicitly instead of left to
  mysqldump's discovery.

A production-derived base already carries `match_id`, `half` and `pos_x/y/z` on
the event tables, so `ktp_schema.sql` is redundant on top of it and is **not**
applied by default. Set `LANE_B_APPLY_KTP_SCHEMA=1` to reproduce its MySQL
failure deliberately.

## Phase 0: run the spike first

Do not write assertions before this passes. The reason is on the record: three
`addbot`-based tests shipped on an unverified premise and were skip-marked a
day later when the first real run showed DoD has no bot AI (`CHANGELOG.md`
1.5.25). The spike exists so that cannot repeat.

```bash
python3 scripts/spike_bot_lane.py \
    --serverfiles /opt/ktp-tier2-runner/serverfiles \
    --bot-kit ~/ktp-bot-kit \
    --bot marinebot \
    --map dod_anzio \
    --play-seconds 180 \
    --schema /path/to/hlstatsx-schema.sql \
             /path/to/migrate_003_assist_action.sql \
             /path/to/migrate_004_cap_break_action.sql \
    --out spike-report.json
```

It answers, stopping at the first "no":

1. Does the bot `.so` load without displacing `amxxcurl` / `reapi` / `dodx`?
2. Which add-bot command actually works?
3. Do bots **connect, join a team, pick a class, spawn**? (where `addbot` failed)
4. Do they **fight** — kills per minute?
5. Do they **contest flags** — any cap activity at all?
6. Event volume per minute, per type (the input Phase 6's damage ledger needs
   for buffer sizing, and the check for `[KTP-STATS] dropped` lines)
7. Can a private `mysqld` start as this user, does the migration SQL apply to
   an empty database, and did the seed rows land with the flags the right way
   round?

Useful flags: `--skip-server` (MySQL half only), `--skip-mysql` (bot half
only), `--bot new_bot` (fallback), `--copy-mode full` (slow, immune to
hardlink write-through — use if you suspect tree corruption), `--keep` (leave
the tree and datadir for inspection).

Interpreting a failure at step 3 or 4: try `--bot new_bot` before changing
anything else. If bots connect but never move or fight, suspect **waypoint
coverage for that map** first — the spike reports whether any waypoint file
mentions it.

## Assertion posture, as built

The original plan here said "existence and plausibility, never exact counts",
on the grounds that bot AI decides how many kills happen. Half of that turned
out to be wrong, and the correction is `assertions.check_carried`.

Bot AI decides how many events are *emitted*. It does not get a say in how many
of them reach the database — that should be all of them. Once the log-side
count is in hand, the assertion is **exact**: `rows == emitted`. A minimum-count
check waves through partial loss, and partial loss is the failure mode that
actually happened (39 rows for 47 events, from a flush cut short at shutdown).

So each action gets one of three verdicts, not pass/fail:

| Verdict | Meaning | Gates? |
|---|---|---|
| `ok` | `rows == emitted` | — |
| `not_exercised` | nothing emitted; the pipeline was not tested | no, but the run is **not** green either |
| `pipeline` | emitted but not carried, or rows in the wrong table | yes |

`not_exercised` exists because a 240s run produced one cap_break and the next
produced none. Calling that a defect teaches people to ignore the lane;
calling it a pass is a lie. It is reported separately and the run is labelled
INCOMPLETE.

The flag invariant — rows in the *opposite* event table — is checked in every
case, including `not_exercised`. It is about configuration rather than volume:
both flags set records every assist twice and applies the reward twice, a
silent rating corruption with no error anywhere, and no amount of bot behaviour
produces or hides it.

Also asserted:

- positions: non-NULL, **varied**, within GoldSrc's ±16384. All-zero is called
  out explicitly — `ksc_origin_str` omits the property on a failed read
  specifically so a failure shows up as NULL rather than as a plausible-looking
  map origin, so a table of `0 0 0` means that guard was bypassed.
- regression: frags and players non-zero, checked **players first** — when both
  are zero, no players is the cause and no frags is the symptom.
- buffer: no `[KTP-STATS] dropped N capture line(s)`. A drop turns every other
  count into a lower bound on an unknown quantity, so the run becomes
  uninterpretable even though the pipeline "worked".

**A configured-but-broken lane fails; it does not skip.** `conftest.py`
already applies this rule to an unreachable `KTP_HLDS_HOST`, for the same
reason: a skip nobody reads is indistinguishable from coverage.

## Ordering trap, enforced in code

`hlstats.pl` reads `hlstats_Actions` into memory **at startup**. Seed after the
daemon boots and every emitted line is silently discarded — the failure that
lost every objective capture at the Philly LAN. `EphemeralMysql.prepare()`
therefore runs before the daemon starts, as fixture order rather than as a note
someone has to remember.

## The synthetic match

Lane B drives a **real** match through the real state machine — the same
forwards fire, the same log lines are emitted — using KTPMatchHandler's
`amx_ktp_test_*` rcons. `lane_b_e2e.py` compiles that plugin with
`KTP_TEST_MODE=1` at run time; the image ships the production build, in which
the whole test block is zero bytes.

This is what makes rows carry `match_id` and `half`. `recordEvent` injects
`match_id` server-side and gates it on `round_live`, so before this every row
Lane B produced was `match_id NULL` — correct for warmup, and zero coverage of
the feature the KTPHLStatsX fork exists for.

Verified on a live run:

```
match_frags_tagged     ok   38 of 84 frag row(s) tagged 1786377797-TEST
match_half_set         ok   half values on tagged frags: ['1']
match_context_cleared  ok   38 tagged against 38 in-match kills;
                            33 post-match kills stayed untagged
```

### Containment: it must not reach anything real

Because the match is real, the Discord and HLTV code paths are genuinely
entered. The only thing making that harmless is that their URLs are empty —
and until now nothing checked. `containment.py` turns that into a precondition
that fails before a server boots:

- every `discord_*_url` / `hltv_api_*` in the lane's config must be blank, and
  a config where **none of those keys exist** also fails, because a check that
  matched nothing proves nothing
- `KTPHudObserver` is dropped from the plugin list — it POSTs on a timer and
  buried the log in `[HUD] POST failed (code 7)`
- the driven `match_id` must end in `-TEST`, so if these rows ever reach a real
  database they are recognisable rather than silently joining the season

It does **not** stub or disable the integrations. They load and run against an
empty URL and no-op, which is production's own behaviour for an unconfigured
server — so the lane keeps testing the real path.

### Two things this got wrong before it got them right

**The match window.** Bounding the match by sampling a kill counter around the
play window reported "the context is not being cleared" on a run where nothing
had leaked: 37 rows were tagged and the sampled bound said 36, because kills
land between the state machine going live and the sample being taken.
`log_invariants.match_window` counts between the log's own
`KTP_MATCH_START`/`KTP_MATCH_END` markers instead — no sampling race.

**Statsme.** Production correctly excludes bots from `dod_stats_flush`, so the
first all-bot runs could not exercise `hlstats_Events_Statsme`. Lane B now
compiles only its ephemeral `stats_logging.amxx` with
`KTP_LANE_B_BOT_WEAPONSTATS=1`; the source additionally requires `sv_lan 1`
and `ktp_testmatch_enabled 1`. The match must emit bot `weaponstats` and create
StatsMe rows or the run fails. Production artifacts retain the bot exclusion.

Ownership markers use the same match boundary as periodic position samples.
The objective poll can observe a legitimate control-point change immediately
after `KTP_MATCH_END`; the daemon intentionally rejects it because live match
context is closed. Lane B therefore compares `ktp_flag_state_events` only with
`KTP_FLAG_STATE` markers between the ordered start/end markers. Counting the
whole server log would fabricate a one-row pipeline loss at shutdown.

### V5 report generation is part of the match

The full lane keeps its ephemeral MySQL alive long enough to run
`scripts/lane_b_match_report.py`. The same completed `-TEST` match is extracted into
sanitized normalized facts, scored with `accumulation_v5_momentum`, rendered, and verified
before database teardown. This is a hard pipeline check, not bot-behaviour coverage: Lane B
fails if the report has anything other than 12 players, lacks normalized overall ratings,
does not pass position and momentum gates, leaks raw positional/platform identity fields,
breaks component or momentum-pool conservation, fails a manifest hash, or cannot reproduce
the same semantic result from identical inputs.

The normal full play window is 360 seconds because the v5 profile requires 300 observed
seconds before issuing an overall rating. A shorter manually requested run may still be
useful for capture diagnostics, but it deliberately fails v5 report verification rather than
publishing misleading normalized ratings.

The job summary contains the all-player rating/raw/momentum table. The uploaded
`match-report/` directory contains `report.html` (download and open for the simplest UI),
`report.md`, `report.json`, `momentum.svg`, `facts.normalized.json`, comparison files, the
optional-AI request, manifest, and verification result. Raw player coordinates are used only
in memory for derivation and are neither written to normalized facts nor included in the
public bundle.

### Historical all-bot roster artifact

Early runs used `ktp_match_players.steam_id VARCHAR(32)` while the daemon gives bots a
36-character synthetic ID. Migration 011 widens that identity column, so the current full
lane requires all 12 roster rows and the v5 report requires the same 12 players. Older saved
fixtures can still exhibit the former `Data too long` condition. It was reported as a
coverage gap — never silently dropped, because those rows genuinely did not get
written.

## Staged cap-break scenarios

`diagnostics/KTPBreakDrive.sma` + `break_scenarios.py` drive Unit 3's positive
and negatives on demand, instead of waiting for bots to happen to produce them.

The detector's claim, as something checkable:

> a break is emitted for a flag **iff** a player of the capping team died
> while inside that flag's zone, causing the in-zone count to drop.

| Scenario | Staged by | Must |
|---|---|---|
| `positive_kill_on_point` | kill the capper nearest the flag | emit a break naming that killer |
| `negative_off_point_kill` | kill a capping-team player ≥900 units away | emit no break for that killer |
| `negative_voluntary_walkoff` | teleport a capper off the point, no death | emit no break at all |

### Why it stages rather than simulates

The trigger is a **real** drop in `CA_num_allies`/`CA_num_axis` read from the
game's own capture-area data, so a synthetic forward cannot produce it — the
body has to leave the zone. Only the attribution is injected:

```
dodx_test_dispatch_client_death(killer, victim, ...)   <- queues the candidate
dod_user_kill(victim)                                  <- drops the count
```

Order is load-bearing and mirrors production. The detector reads its baseline
when the candidate is queued, so the dispatch has to happen while the victim is
still standing in the zone. Kill first and the baseline is already the
post-death value, no drop is ever seen, and the scenario silently tests
nothing. `dod_user_kill` alone will not do: it is a self-kill, and
`killer == victim` is rejected — correctly, since a suicide on a point is not
somebody else breaking the cap.

### Attribute, do not count — this cost a false bug report

The first version counted `cap_break` lines in a time window and reported a
confident detector defect. It was wrong: a bot had killed a capper one second
before the staged walk-off, so the break in that window was entirely
legitimate. Two rules came out of it, both tested in
`test_break_scenarios.py` against the exact lines that caused it:

1. **Match the breaker by name.** A staged kill logs the killer it injected,
   and only a break naming that player counts. Unrelated breaks are ignored
   explicitly rather than swept into a count.
2. **Reject contaminated windows.** The walk-off injects no killer and so has
   nothing to match on; instead the window is discarded unless the count
   dropped by exactly the one player moved *and* nobody on the capping team
   died nearby. The lookback is symmetric — the detector holds a candidate for
   ~2.5s, so a kill just **before** the walk-off is precisely what produces a
   legitimate break during it, and a forward-only window would have missed the
   real confound.

## Open finding: a killer credited an assist on their own kill

`check_assist_attribution` fired for real, once in 225 kills across four
captures:

```
14:38:43  "Claire<9><0><Allies>" killed "Pyramid<2><0><Axis>" with "bazooka"
14:38:45  "Claire<9><BOT><Allies>" triggered "assist" against "Pyramid<2><BOT><Axis>"
```

`ksc_on_death` does exclude the killer (`if (a == killer || a == victim)
continue`), and the one sample is an **explosive**, which suggests DODX's
`client_death` may report a different index for splash damage than the engine
credits in the log line. That is a hypothesis from one sample, not a root
cause. Details and a suggested next step are in `KTPR_DEPLOYMENT_PLAN.md` under
Unit 2.

Worth noting as validation of this file: the check found it unprompted, which
is the thing the deployment plan asks a human to spot by eye during a live
match.

## Ordering trap #2, also enforced in code

`hlstats.pl` reads its **per-server config** at startup too, from
`hlstats_Servers_Config`. Three defaults are fatal to a bot lane, and all three
fail identically — the line parses, the daemon says `(IGNORED) ...`, nothing is
written:

| Parameter | Default | Effect here |
|---|---|---|
| `IgnoreBots` | **1** | every Lane B player is a bot; every event dropped |
| `MinPlayers` | **6** | a small debug run records nothing |
| `BonusRoundIgnore` | 0 | fine, but set explicitly so a stray end-of-round window cannot eat the tail |

`HlstatsDaemon.ensure_server_row()` writes all three, before the daemon starts.

## Not yet built

- `match_driver.py` — drive a real match via the existing test-mode rcons
  (`amx_ktp_test_*`), so rows carry a `match_id` and a `half`. Nothing here
  exercises match tagging yet: every row Lane B has produced has
  `match_id NULL`, which is correct for warmup and untested for a live match.
- CI wiring (nightly, non-gating, inheriting the 7pm–midnight ET match embargo,
  and not sharing the nightly Tier 2 slot — two hlds processes on the box that
  also runs production HLStatsX is not a good trade). The workflow file exists
  and has never run on GitHub.
- **A production-sourced daemon tree.** `assemble_daemon_tree.sh` currently
  falls back to pinned upstream, which is a *reconstruction*: the fork does not
  modify those seven files, so they are almost certainly identical, but
  "almost certainly" is not verified. `--from-production` needs SSH to the data
  server. Until then every run's PROVENANCE says RECONSTRUCTION, which is the
  honest label.
- **A cap_break in every live run, without staging one.** Assists arrive every
  time (2, 4, 5, 7, 12); cap_break appears in about half of runs by luck. Two
  hypotheses were checked and eliminated: it is not a shortage of interruptible
  captures (a run with a break had 19 `dod_capture_area` to 7
  `dod_control_point`; one without had 16 to 12), and it is not bots capping in
  packs (`wait_for_cap_percent 0` changed nothing either way). Longer runs did
  not help.

  This is now handled rather than unsolved — `break_scenarios.py` stages the
  scenario deterministically (below), and an unstaged run reports
  `not_exercised` rather than a pass or a defect.
