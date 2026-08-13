# Handover: get the full test suite running nightly

**For:** an AI agent or engineer building out CI/CD.
**Repo:** `KTPInfrastructure`.
**Deliverable:** `.github/workflows/lane-b-stats-e2e.yml` running green on a
schedule, with the full Lane B suite, artifacts, and a job summary someone will
actually read.

Read [`tests/e2e_stats/NEXT_PHASES.md`](../../tests/e2e_stats/NEXT_PHASES.md)
first — this is the actionable version of its CI half.

---

## What exists today

The workflow file exists and **has never run**. It was written before the lane
worked and is stale in ways that would fail immediately:

| It does | Reality |
|---|---|
| runs `scripts/spike_bot_lane.py` | that is the Phase 0 probe; the suite is `scripts/lane_b_e2e.py` |
| defaults `bot: marinebot` | marinebot never worked; new_bot is baked into the image, SHA-pinned |
| fetches a bot kit from `LANE_B_BOT_KIT_URL` | obsolete — the Dockerfile installs new_bot at build time |
| passes `ktp_schema.sql` as `--schema` | that file **cannot run on MySQL at all** and is an overlay, not a base schema |
| knows nothing about the daemon tree | `hlstats.pl` needs seven upstream libs the fork does not vendor |
| knows nothing about the patched ktpamx | without it AMXX cannot see bots and the lane measures an empty server |

**Keep** its header reasoning, which is still correct and non-obvious:
GH-hosted runner (never the Tier 2 box, which sits on the data server and keeps
a fleet-matching tree with a drift tripwire), no `pull_request` trigger,
non-gating, 06:00 UTC between the base-image build (04:30) and Tier 2's nightly
(09:00).

---

## The pipeline you are building

```
resolve refs
  ├─ build/restore patched ktpamx        (cached — action already written)
  ├─ assemble daemon tree                 (upstream libs + KTP delta)
  ├─ build Lane B image                   (FROM ktp-runtime-test-base)
  └─ compile plugin artifacts from refs   (git show <ref>:<path> + amxxpc)
        ↓
   lane_b_e2e.py  →  ephemeral MySQL 8 + hlds + new_bot + hlstats.pl
        ↓
   verdicts → job summary + artifacts
```

## Tasks

### 1. Wire in the cached ktpamx — already done, just use it

`.github/actions/build-ktpamx-laneb/action.yml` exists and is tested locally in
both directions (cache hit on an unchanged recipe, miss when the recipe
changes).

```yaml
- name: Lane B ktpamx
  id: ktpamx
  uses: ./.github/actions/build-ktpamx-laneb
  with:
    ref: feat/lane-b-fakeclient-players
    out: build/lane-b-artifacts/ktpamx_i386.so
```

The key is `ktpamx-laneb-<os>-<sha>-<hash of scripts/build_ktpamx_laneb.sh>`.
The script hash is in there on purpose: it carries the toolchain image and the
configure flags, so a recipe change with no source change must not restore a
binary that no longer matches how it would be built today.

**Do not add a fallback that continues without the binary.** The action fails
hard if it is missing or if its stamp disagrees with the resolved ref, because
a lane that cannot see bots goes green having measured nothing.

### 2. Assemble the daemon tree

```yaml
- run: scripts/assemble_daemon_tree.sh <KTPHLStatsX checkout> build/lane-b-artifacts/daemon
```

Needs network (it fetches a pinned upstream commit). Publish the resulting
`PROVENANCE` file as an artifact — it records whether the run used production's
own libs or the pinned-upstream reconstruction, and today every run says
`RECONSTRUCTION`.

Why it is needed: KTPHLStatsX is a **delta-only fork of three files**, and
`hlstats.pl` requires seven more by absolute path. Production's
`/opt/hlstatsx/scripts/` is that same composition; this reproduces it.

### 3. Commit `base-schema.sql` — the real blocker

The runner has no production access, and the base schema is currently a local
artifact taken by hand.

**Recommendation: commit it to the repo.** It is 64 `CREATE TABLE`s and **0
`INSERT`s** — DDL only, no rows, no credentials. `scripts/fetch_base_schema.sh`
produces exactly that and now includes both reconstruction fixes
(`rcon_password`, collation). Committing it also makes the lane reproducible
instead of dependent on one laptop's `~/lane-b-out`.

A secret or a fetched artifact buys nothing here and adds a failure mode.

**Ideally re-take it with `--from-production` first** so the committed copy is
production's own DDL. That needs SSH to the data server. Until then the
harness's `repair_reconstructed_schema` patches the two known gaps at load
time, and the run is still valid — just note it.

### 4. Replace the run step

Mirror what `run_e2e.sh` does locally. Arguments that matter:

```
python3 -u scripts/lane_b_e2e.py \
    --ktpamx-so  <cached .so> \
    --plugin     <artifacts>/stats_logging.amxx \
    --config-dir config/local \
    --hlstats    <daemon tree>/hlstats.pl \
    --schema     base-schema.sql \
    --seed       migrate_003_assist_action.sql migrate_004_cap_break_action.sql \
    --play-seconds 240
```

Delete the bot-kit fetch step and the `LANE_B_BOT_KIT_URL` secret dependency.

Also run the unit suite — it is fast and catches harness regressions before the
expensive part:

```
python3 -m pytest tests/e2e_stats -q     # ~20s, 106 tests
```

### 5. Make the three-way verdict survive a pass/fail system

This is the part most likely to be got wrong, and getting it wrong silently
undoes the design.

`lane_b_e2e.py` reports three outcomes per check:

| Verdict | Meaning | CI should |
|---|---|---|
| `ok` | rows == emitted | pass |
| `pipeline` | emitted but not carried, or rows in the wrong table | **fail the job** |
| `not_exercised` | the scenario never happened — bot luck | **not fail**; warn and record |

`not_exercised` exists because a 240s run produces a cap_break about half the
time. Failing on it teaches people to ignore the lane; passing silently on it
reports "green" for a run that tested nothing.

So:

- fail on any `pipeline` verdict, any assertion failure, any daemon SQL error
- for each gap: `::warning::` plus a line in `$GITHUB_STEP_SUMMARY`
- put the emitted-vs-recorded table in the step summary too — it is the first
  thing anyone wants and should not require downloading an artifact

**Add a floor.** If *nothing* carried and *no* scenario staged, fail. That is a
broken lane, not a quiet one, and it is the state that would otherwise sail
through as green forever. The JSON report has everything needed:
`report["carried"]`, `report["break_scenarios"]`, `report["failures"]`,
`report["coverage_gaps"]`.

### 6. Artifacts

| File | Why |
|---|---|
| `lane-b-e2e.json` | every verdict and count |
| `lane-b-e2e.log` | **the important one** — every diagnosis in this project started here, and `replay_daemon.py` can re-run the daemon leg from it without bots, so a nightly failure is reproducible from its own artifact |
| `hlstats-e2e.out` | the daemon's own `(IGNORED) <reason>` output |
| `daemon/PROVENANCE` | which daemon libs were used |

30-day retention, `if: always()`.

---

## Traps that have already cost time

These are all documented in `tests/e2e_stats/PHASE0_FINDINGS.md`; the ones that
will bite a CI author specifically:

- **The first hlds boot in a fresh container dies in `SteamAPI_Init`.** The
  second with identical arguments succeeds. `lane_b_e2e.py` retries three times
  and reports the attempt count. Do not treat attempt 1 failing as a lane
  failure.
- **Two concurrent runs share the game log** and produce nonsense scenario
  verdicts. The `concurrency:` group already prevents this; keep it, and keep
  `cancel-in-progress: false`.
- **`amxx modules` / `amxx plugins` return nothing over rcon** in extension
  mode. Anything that fingerprints the stack must read the server log.
- **The base image ships no `modules.ini`/`plugins.ini`.** Without them AMXX
  loads zero modules and zero plugins and two empty stacks compare equal.
  `--config-dir config/local` supplies them.
- **A run takes ~15-25 minutes** with the match, the staged scenarios and their
  retries. The existing 60-minute timeout is fine; do not tighten it to 20.

---

## Sequencing

1. **Phase B½ first** (the synthetic match — see `NEXT_PHASES.md`). It changes
   what CI runs, so building CI first means writing it twice.
2. Commit `base-schema.sql`.
3. Rewrite the workflow once, against the finished lane.
4. `workflow_dispatch` it by hand until it passes.
5. Let the schedule take over.

If you are told to do CI before Phase B½, it still works — just expect to
revisit step 4 when the match driver lands.

## Definition of done

- [ ] `workflow_dispatch` run is green end to end on a GH-hosted runner
- [ ] a second run restores ktpamx from cache (check the action's `cache-hit`)
- [ ] the job summary shows the emitted-vs-recorded table and any coverage gaps
- [ ] a deliberately broken input (e.g. drop the `assist` seed) **fails** the job
- [ ] a run with no cap_break **does not** fail, but says so
- [ ] artifacts include the game log, and `replay_daemon.py` reproduces the
      daemon leg from it locally
- [ ] the schedule has fired at least once unattended

The fourth and fifth bullets are the ones worth doing deliberately. A CI job
nobody has watched fail is a CI job nobody knows works.
