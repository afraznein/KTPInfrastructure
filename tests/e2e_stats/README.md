# Lane B — stats-capture end-to-end (bots + ephemeral MySQL)

Proves the assist / cap-break / position capture actually lands rows in MySQL,
by putting bots on a throwaway server and querying a throwaway database.

Design and rationale: [`../integration/STATS_CAPTURE_E2E_DESIGN.md`](../integration/STATS_CAPTURE_E2E_DESIGN.md).
What it verifies: [`../../docs/ktpr_mcp/KTPR_DEPLOYMENT_PLAN.md`](../../docs/ktpr_mcp/KTPR_DEPLOYMENT_PLAN.md).

**Status: Phase 0 (spike) only.** The modules here are built; no assertions are
written yet, deliberately. Run the spike first — see below.

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

### ⛔ Blocker: new_bot needs Metamod, and the KTP stack has none

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

## Assertion posture, once we get there

Existence and plausibility, never exact counts — bot AI decides how many kills
happen, and the test's job is to prove the pipeline carries them.

- assists: `≥1` row in `hlstats_Events_PlayerPlayerActions`, and **exactly 0**
  in `hlstats_Events_PlayerActions` for the same action. That second one *is*
  exact: it is a flag-correctness invariant, and getting it wrong
  double-records every assist and double-applies the reward.
- breaks: `≥1` row, `match_id` non-NULL for rows from live play
- positions: non-NULL, **varied**, within map world bounds. Assert against
  all-zero explicitly — `ksc_origin_str` omits the property on a failed read
  specifically so a failure shows up as NULL rather than a plausible-looking
  map origin, and "every row is `0 0 0`" is the signature of that guard being
  bypassed.
- regression: frags and weaponstats still non-zero
- buffer: no `[KTP-STATS] dropped N capture line(s)`

**A configured-but-broken lane fails; it does not skip.** `conftest.py`
already applies this rule to an unreachable `KTP_HLDS_HOST`, for the same
reason: a skip nobody reads is indistinguishable from coverage.

## Ordering trap, enforced in code

`hlstats.pl` reads `hlstats_Actions` into memory **at startup**. Seed after the
daemon boots and every emitted line is silently discarded — the failure that
lost every objective capture at the Philly LAN. `EphemeralMysql.prepare()`
therefore runs before the daemon starts, as fixture order rather than as a note
someone has to remember.

## Not yet built

- `match_driver.py` — drive a real match via the existing test-mode rcons
  (`amx_ktp_test_*`), so rows carry a `match_id` and a `half`
- `assertions.py` + the tests themselves
- CI wiring (nightly, non-gating, inheriting the 7pm–midnight ET match embargo,
  and not sharing the nightly Tier 2 slot — two hlds processes on the box that
  also runs production HLStatsX is not a good trade)

The assertions are downstream of the spike answering yes. The match driver is
not, and is the next thing to build regardless.
