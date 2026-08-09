# Stats-capture end-to-end test lane — Design (2026-08-09)

**Status:** design + Phase 0 spike only. No assertions written yet, on purpose
— see "Why this doc lands before the tests" below.

Goal: prove the stats-capture branches (assists, cap breaks, positions — see
`docs/ktpr_mcp/KTPR_DEPLOYMENT_PLAN.md`) actually land rows in MySQL, on a
throwaway server driven by bots, before any of it reaches the fleet.

## Why the existing Tier 2 lane cannot cover this work

Tier 2 boots a real `hlds_linux` and asserts against it, so "spin up, drive,
tear down" is already solved. What it cannot do is put a **player** in the
world, and every emit path in the new capture code is hard-gated on exactly
that. From `KTPAMXX/plugins/dod/ktp_stats_capture.inc`:

| Path | Guard |
|---|---|
| `ksc_on_death` | `if (killer < 1 \|\| killer > MAX_PLAYERS \|\| !is_user_connected(killer)) return` |
| `ksc_emit_break` | `if (!is_user_connected(breaker)) return` |
| assist loop | `if (!is_user_connected(a)) continue` |
| `ksc_origin_str` | `is_user_connected(id)`, then `dodx_get_user_origin(id, origin)` |

So `dodx_test_dispatch_client_death(1, 2, …)` on an empty server returns at the
first guard and emits nothing. **A synthetic-dispatch test of this code would
pass while proving nothing** — the most expensive kind of test there is.

The cap-break detector is worse. Its entire input is a 0.5s poll of
`dodx_area_get_data(f, CA_num_allies / CA_num_axis / CA_owning_team /
CA_is_capturing)` — live zone-occupancy state. No dispatch primitive fakes it,
and the four negative cases the deployment plan calls for (completed capture,
off-point kill, voluntary walk-off, round restart) are *timing behaviours of
real bodies in real zones*. Those negatives are the ones that catch
false-positive breaks, which is the failure mode that silently inflates a
player's objective rating. They are not reachable synthetically.

Positions need real in-world origins by definition.

Conclusion: this work needs connected, on-team, in-world players. That is a
genuine new capability for the test infrastructure, not a variation on the
existing lane.

## Environment findings that changed the plan

### 1. Sturmbot cannot be used on a Linux runner

The operator's first choice was Sturmbot. It does not work here:

- Sturmbot's current release (1.9, Oct 2019) ships a **Windows installer
  only**. No Linux `.so` on the downloads page.
- A legacy Linux Sturmbot exists (1.5.1) but targets **DoD 3.1B, not 1.3**,
  and modern glibc/loader versions break essentially all legacy bot `.so`
  binaries.
- Per sturmbot.org's own Linux guide, the Linux-viable DoD 1.3 bots are
  **Marine Bot** and **new_bot** (0.2.0+). Both load as Metamod plugins via
  `+localinfo mm_gamedll <bot>/<bot>.so`.

**Chosen: Marine Bot**, as the one with a maintained modern Linux build
confirmed loading under SteamCMD HLDS. `new_bot` is the documented fallback
and is interesting for a second reason — it can load and convert Sturmbot
waypoints, so the large Sturmbot waypoint corpus is reachable if Marine Bot's
per-map coverage turns out to be thin.

The bot layer is therefore built behind a **thin adapter** (`bot_driver.py`):
which bot, which `.so`, which waypoint dir, and the add/fill commands are
config, not structure. Swapping Marine Bot → new_bot is a config change, not a
rewrite. This is deliberate — the bot is the least-certain component in the
design and the most likely thing to be replaced.

Known extra step on newer distros: glibc 2.41+ refuses shared libraries
needing an executable stack unless the main binary does too, fixed with
`execstack -c` on `amxmodx_mm_i386.so`. Whether the runner needs this is a
Phase 0 question.

### 2. The runner is deliberately Docker-free, so "ephemeral MySQL" is not a container

The operator asked for ephemeral MySQL per run. But `TEST_INFRASTRUCTURE_PLAN.md`
records the Tier 2 runner as **Docker-free** on the data server, and
`help.md` confirms it. Pulling Docker in for this would be a real
infrastructure change to a box that also runs production HLStatsX.

Same intent, Docker-free realisation: **a second `mysqld` instance** with its
own `--datadir` under the run's temp dir, its own `--socket`, and a high
`--port`, initialised empty per run and deleted on teardown. The data server
already has MySQL; a second instance needs no root and cannot see the
production schema. It keeps every property that was actually wanted —
isolation, repeatability, and proving the migration SQL applies to an empty
database — without touching the box's container story.

Production `hlstatsx` is never a target. The daemon under test is a
**separate `hlstats.pl` process** started by the harness, pointed at the
ephemeral socket and the throwaway server's log.

### 3. The bot stack must not contaminate the fleet-matching tree

`help.md` is explicit: the runner's `serverfiles/` must match the live fleet,
drift is tripwired, and re-sync is deliberately manual. A bot `.so` in that
tree is exactly the drift the tripwire exists to catch.

So the harness **never touches `/opt/ktp-tier2-runner/serverfiles/`**. It
copies it to a per-run ephemeral tree and overlays the bot there. The
fleet-matching tree stays pristine and the tripwire stays meaningful.

Quarantine rules for the bot, per the operator's requirement that it never
reach production:

1. Bot binaries + waypoints live **outside** the fleet-matching tree, under a
   dedicated `bot-kit/` directory the harness reads and only ever copies *from*.
2. They are **not committed to this repo** and **not in any deploy manifest**
   — `KTPFileDistributor` and the Docker plugin build have no path to them.
3. The bot loads via a **command-line** `+localinfo mm_gamedll`, not via
   `plugins.ini`. Nothing persisted in the tree under test enables it, so a
   copy of that tree booted normally has no bot.
4. The ephemeral tree is deleted on teardown, so a bot-enabled tree does not
   outlive the run that made it.
5. `.gitignore` covers `bot-kit/` so a stray local install cannot be committed
   by accident.

## Two lanes, different jobs

Keeping one lane would force a bad tradeoff: bot AI is non-deterministic, and a
non-deterministic test cannot gate merges without becoming the "disable the
integration test to merge the urgent fix" antipattern the plan already warns
about.

| | Lane A — deterministic | Lane B — bot lane |
|---|---|---|
| Drives | dispatch primitives, rcon, witness JSONL | Marine Bot playing a real match |
| Asserts on | forward dispatch, plugin logic, log-line **shape** | MySQL rows written by `hlstats.pl` |
| Runs | every PR | nightly + on-demand |
| Gates merges | **yes** | **no** |
| Flake posture | zero tolerance | tolerated; assertions are existence + plausibility |

Lane A is where a regression gets caught fast and cheap. Lane B is where
"does this actually work against the real engine" gets answered. Neither can
do the other's job.

Because the emit paths are `is_user_connected`-gated, Lane A's reach into the
new capture code is limited to what can be asserted without a body in the
world — buffer behaviour, the cvar kill switch, the log-line format helpers.
That is worth having and cheap, but it is not coverage of the feature. Lane B
is the coverage. This asymmetry is the whole reason this doc exists.

## Lane B shape

```
ephemeral_tree.py    copy fleet-matching serverfiles → per-run tmp tree,
                     overlay bot kit + test plugins + seeded configs
ephemeral_mysql.py   second mysqld on a private socket/port/datadir;
                     load schema + migrations + hlstats_Actions seed rows
hlstats_daemon.py    run scripts/hlstats.pl against that socket, tailing the
                     ephemeral server's log
bot_driver.py        bot adapter: stage .so + waypoints, fill teams, wait for
                     the bots to actually be in-world and fighting
match_driver.py      reuse the existing test-mode rcons to run a real match
                     (setup → live → play → end → flush)
assertions.py        query the ephemeral DB for assists / breaks / positions
```

Run shape: bring up MySQL → seed → bring up server with bots → confirm bots
are actually playing → drive a match → end + flush → wait for the daemon to
drain → assert on rows → tear everything down → emit a report JSON.

### Assertion posture

Existence + plausibility, never exact counts. Bot AI decides how many kills
happen; the test's job is to prove the pipeline carries them.

- assists: `≥1` row in `hlstats_Events_PlayerPlayerActions` for `code='assist'`,
  **and exactly 0** in `hlstats_Events_PlayerActions` for the same code (the
  double-record check the deployment plan calls for — this one *is* exact,
  because it is a flag-correctness invariant, not a volume question)
- breaks: `≥1` row, `match_id` non-NULL on rows from live play
- positions: non-NULL, **varied**, and inside map world bounds. "All rows are
  `0 0 0`" is the specific failure the `ksc_origin_str` guard exists to make
  visible, so assert against it directly rather than merely non-NULL.
- regression: frags and weaponstats still non-zero
- buffer: no `[KTP-STATS] dropped N capture line(s)` in the AMXX log

### The skip-is-not-green rule applies

`conftest.py` already fails rather than skips when the operator explicitly
points the suite at a server, precisely so a down target cannot read as a
green run. Lane B inherits that: if the bot kit is configured but the bots
never spawn, that is a **failure**, not a skip. The five `addbot` tests that
sat skip-marked for months are the cautionary example — a skip nobody reads
is indistinguishable from coverage.

## Why this doc lands before the tests

The repo has already made this mistake once, and it is worth not repeating.
Phase 2 of `DODX_FORWARD_FIRING_DESIGN.md` was written against the belief that
`addbot` produces a playing bot, and three tests shipped on that basis. They
were skip-marked a day later (`CHANGELOG.md` 1.5.25) when the first real run
showed DoD ships no bot AI at all.

Everything downstream of "the bots actually play" is cheap to write and
worthless if that premise is wrong. So Phase 0 answers the premise first, on
the runner, with a script whose only output is facts.

### Phase 0 — spike (`scripts/spike_bot_lane.py`)

Answers, in order, stopping at the first failure:

1. Does Marine Bot's `.so` load under this Metamod/AMXX/ReAPI stack at all —
   and does `meta list` show it without disturbing the existing 3-module set?
2. Do bots **connect, pick a team, pick a class, and spawn**? (This is the
   exact step `addbot` failed at.)
3. Do they **fight** — does `client_damage` fire, do frags land?
4. Do they **contest and capture flags** — does `dodx_area_get_data` show
   non-zero `CA_num_*` and does `CA_owning_team` ever change?
5. Waypoint coverage: which of KTP's actual map pool has waypoints, and what
   happens on a map without them?
6. Event volume per minute, per forward — the input the damage-ledger phase
   (Phase 6, ~1,100–1,500 damage events/match measured) needs for buffer
   sizing.
7. Can a second `mysqld` be initialised and started as `krodssh` with no root,
   and does `hlstats.pl` connect to it and tag events with a `match_id`?

Only after Phase 0 reports do the assertions get written. If Marine Bot fails
step 2 or 3, `new_bot` is tried before anything else changes.

## Open questions

1. **Which map.** Lane B wants a map with good waypoints *and* flags that bots
   will actually contest. `dod_anzio` is the existing harness default and a
   stock map, so most likely to have waypoints — but Phase 0 should confirm
   bots cap on it, not assume.
2. **Match-hours embargo.** The Tier 2 runner refuses jobs 7pm–midnight ET.
   Lane B is heavier than Tier 2 and shares the box with production HLStatsX;
   it should inherit the embargo and probably run outside the nightly Tier 2
   slot to avoid two hlds processes at once.
3. **Run duration.** Long enough for bots to produce a usable sample, short
   enough to not be a nightly liability. Phase 0's volume numbers decide it.
4. **`hlstats.pl` restart semantics.** The daemon reads `hlstats_Actions` into
   memory at startup, so the harness must seed **before** starting it. This is
   the same ordering trap the deployment plan flags; here it is enforced by
   the fixture order rather than by an operator remembering.
5. **Does the daemon need the suicide verb fix to be observable?** Lane B is
   also the cheapest place to finally answer the open verification debt on
   `"committed suicide with"` — a bot forced to `kill` would produce a real DoD
   suicide line. Worth folding in.

## Cross-references

- `docs/ktpr_mcp/KTPR_DEPLOYMENT_PLAN.md` — the units this lane verifies
- `tests/integration/DODX_FORWARD_FIRING_DESIGN.md` — Lane A's design, and the
  addbot cautionary tale
- `TEST_INFRASTRUCTURE_PLAN.md` — tier framework; lists "24-player synthetic
  load — requires bot tooling" as an explicit non-goal, which this lane
  partially retires
- `CHANGELOG.md` 1.5.25 — the bot-AI reality check
- `KTPAMXX/plugins/dod/ktp_stats_capture.inc` — the code under test
- https://sturmbot.org/index.php/marine-bot/132-linux-dod-dedicated-server-setup-on-a-lan-with-bots
  — Linux DoD-with-bots setup, the source for the bot findings above
