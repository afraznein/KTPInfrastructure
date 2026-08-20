# Handover: merging the stats-capture work into the default branches

**For:** whoever opens and merges the PRs.
**Goal:** get `main`/`master` across three repos to what has been verified
locally.
**Verified against remotes on 2026-08-10.** If you read this much later,
re-run the commands in [Appendix A](#appendix-a--re-verify-the-state) first.

---

## The shape of it

**Eleven branches, three repos, four deployment units.** Most are *stacked* —
each contains the one before it — so they must merge in order within their
repo, and the order also matters *across* repos.

The units and their gates are in
[`docs/ktpr_mcp/KTPR_DEPLOYMENT_PLAN.md`](../ktpr_mcp/KTPR_DEPLOYMENT_PLAN.md).
That document now carries a "Lane B pre-verification" table per unit saying
exactly which of its smoke-test steps have already been proved automatically
and which still need a human. **Read those before running any manual step** —
most of the checklist is already done.

## The one rule that matters most

> **The database seed must land, and the daemon must restart, BEFORE the
> plugin that emits the matching lines ships.**

`hlstats.pl` reads `hlstats_Actions` into memory **at startup**. A line whose
action row does not exist is parsed and silently discarded — no error, no log,
nothing to notice. Getting this backwards is what lost every objective capture
at the Philly LAN.

So within Units 2 and 3: **KTPHLStatsX merges and deploys first, KTPAMXX
second.**

---

## Current state

| Repo | Default branch | At |
|---|---|---|
| KTPHLStatsX | `main` | `6c9567d` |
| KTPAMXX | `master` | `abd3e1b3` |
| KTPInfrastructure | `main` | `06de9d0` |

### KTPHLStatsX — a clean stack of three

```
main (6c9567d)
 └─ fix/suicide-dispatch-goldsrc      d3921b7   1 commit    Unit 1
     └─ feat/seed-assist-action        7eefed6   2 commits   Unit 2
         └─ feat/seed-cap-break-action a8c9a97   3 commits   Unit 3
```

### KTPAMXX — a clean stack of three, plus one independent

```
master (abd3e1b3)
 └─ feat/stats-assists         30da9b71   1 commit    Unit 2
     └─ feat/stats-cap-breaks  d0e88885   2 commits   Unit 3
         └─ feat/stats-positions 5f0e5379 3 commits   Unit 4

master (abd3e1b3)
 └─ feat/lane-b-fakeclient-players  c1408a48  1 commit   test-only, no unit
```

### KTPInfrastructure — three independent branches

```
main (06de9d0)
 ├─ docs/stats-capture-plan-branch-status  14a68be   1 commit,  1 file
 ├─ feat/stats-capture-include             53ea398   1 commit,  5 lines
 └─ feat/tier2-bot-lane-stats-e2e          8fedbbc  17 commits, 41 files
```

---

## Merge order

Numbered so you can work straight down. Do not batch two un-smoke-tested units
onto the fleet — if something is wrong you want one suspect, not two.

| # | Repo | Branch | PR base | Notes |
|---|---|---|---|---|
| 1 | KTPHLStatsX | `fix/suicide-dispatch-goldsrc` | `main` | Unit 1. Gate cleared — see below. |
| 2 | KTPInfrastructure | `feat/stats-capture-include` | `main` | 5 lines. Do it early: the plugin build needs the `.inc` to be copied, and it is harmless on its own. |
| 3 | KTPHLStatsX | `feat/seed-assist-action` | `fix/suicide-dispatch-goldsrc` | Unit 2, DB half. **Apply the seed SQL and restart the daemon before step 4.** |
| 4 | KTPAMXX | `feat/stats-assists` | `master` | Unit 2, plugin half. |
| 5 | KTPHLStatsX | `feat/seed-cap-break-action` | `feat/seed-assist-action` | Unit 3, DB half. **Seed + restart before step 6.** |
| 6 | KTPAMXX | `feat/stats-cap-breaks` | `feat/stats-assists` | Unit 3, plugin half. |
| 7 | KTPAMXX | `feat/stats-positions` | `feat/stats-cap-breaks` | Unit 4. No SQL, no daemon change. |
| 8 | KTPInfrastructure | `docs/stats-capture-plan-branch-status` | `main` | Docs only. |
| 9 | KTPInfrastructure | `feat/tier2-bot-lane-stats-e2e` | `main` | The Lane B test infrastructure. **Rebase onto `main` after step 8** — see the conflict note. |
| 10 | KTPAMXX | `feat/lane-b-fakeclient-players` | `master` | Test-only. Optional, but Lane B cannot run without it — see below. |

**Open each stacked PR against its parent branch, not against `main`.** GitHub
auto-retargets a stacked PR to the default branch once its base merges, so the
order takes care of itself and each PR shows only its own diff.

---

## Per-PR notes

### 1 — `fix/suicide-dispatch-goldsrc` (Unit 1)

`hlstats_Events_Suicides` has been empty fleet-wide since it was created. One
`elsif`; the handler, schema and aggregation were always correct.

**Its pre-merge gate is cleared.** The plan flagged that the verb string
`"committed suicide with"` was copied from the CS:GO branch and never seen in a
DoD log — if wrong, the fix would compile, deploy and do nothing. It is now
confirmed against real DoD 1.3 logs in three weapon variants, and verified with
a control: the same log through the old daemon gives 3 suicide lines → **0**
rows, through the fixed one → **3**. Frags and assists identical across both.

### 2 — `feat/stats-capture-include`

Five lines in `build/plugins/Dockerfile` so the plugin image copies
`ktp_stats_capture.inc`. Inert until a plugin `#include`s it, which is why it
can merge before the plugin branches.

### 3, 5 — the KTPHLStatsX seeds

`INSERT IGNORE` of one row each into `hlstats_Actions`. The flags are
**opposite between them and both are load-bearing**:

| code | `for_PlayerActions` | `for_PlayerPlayerActions` |
|---|---|---|
| `assist` | `0` | `1` |
| `cap_break` | `1` | `0` |

Setting both on either would record every event twice and apply its reward
twice — a silent rating corruption with no error anywhere. Verify after
applying:

```sql
SELECT code, for_PlayerActions, for_PlayerPlayerActions, reward_player
FROM hlstats_Actions WHERE game='dod' AND code IN ('assist','cap_break');
```

`reward_player` must be `0` on both: these feed KTPR's own rating, and a
non-zero HLStatsX skill reward would re-rate the whole ladder as a side effect.

### 9 — `feat/tier2-bot-lane-stats-e2e`

17 commits, 41 files: the Lane B test lane, its scripts, its docs, and the
`build/lane-b/` image. **Nothing here ships to the fleet** — no plugin, no
daemon, no production config. Low-risk merge, large diff.

**Conflict note.** Both this and branch 8 edit
`docs/ktpr_mcp/KTPR_DEPLOYMENT_PLAN.md`, and neither contains the other. A
`git merge-tree` dry run predicts **no conflict**, but rebase this branch onto
`main` after step 8 anyway rather than relying on that.

### 10 — `feat/lane-b-fakeclient-players`

**Read this one properly before merging.** It touches core client registration
in `amxmodx/meta_api.cpp`.

- It is **compile-time gated** behind `KTP_LANE_B_FAKECLIENTS`, off by default.
  An ordinary build — including the production Docker build — is byte-for-byte
  unchanged, so the fleet cannot inherit it by deploy accident.
- The build prints a `*** NOT FOR PRODUCTION ***` banner when it is on.
- Same shape as KTPMatchHandler's existing `-DKTP_TEST_MODE`.

**Why it exists:** in ReHLDS extension mode, KTPAMXX has no code path that
registers a fake client as a player, so `is_user_connected()` is false for
every bot — and every emit path in `ktp_stats_capture.inc` is gated on it. Lane
B without this measures an empty server and reports green. Full write-up in
`tests/e2e_stats/PHASE0_FINDINGS.md`.

It is independent of the stats stack and can merge any time, or never — but
Lane B does not function without it.

---

## What is already proved, and what is not

Do not re-run the whole smoke-test checklist by hand. The plan's per-unit
tables say what is covered. Summary:

| Unit | Automated | Still needs a human |
|---|---|---|
| 1 suicides | verb string confirmed; 3 lines → 3 rows, with a control | live server run (Steam auth, fleet config) |
| 2 assists | every emitted assist carried exactly; both attribution negatives; headshots 13/13; kill switch | **`hlstats_Events_Statsme`** — Lane B loads no statsme module |
| 3 cap breaks | positive + off-point and voluntary-walk-off negatives, all staged deliberately | clean-cap and round-restart negatives |
| 4 positions | non-NULL, varied, in-bounds; no dropped lines | cross-flag clustering (needs several breaks in one run) |

### One open finding — not a blocker

A killer was credited an assist on their own kill, **once in 225 kills**, on a
bazooka:

```
14:38:43  "Claire<9><0><Allies>" killed "Pyramid<2><0><Axis>" with "bazooka"
14:38:45  "Claire<9><BOT><Allies>" triggered "assist" against "Pyramid<2><BOT><Axis>"
```

`ksc_on_death` does exclude the killer, and the single sample is an explosive,
so the suspicion is that DODX reports a different index for splash damage than
the engine credits. **That is a hypothesis from one sample, not a root cause.**

It is pre-existing behaviour of the capture rule, not something these branches
introduce, and it is rare — so it does not block Unit 2. It double-credits a
killer, so it should be understood before Phase 8 has KTPR consume assists.
Details and a suggested next step are in the plan under Unit 2.

---

## Deploy steps that need sign-off

Merging is not deploying. Each unit's `### Deploy` section in the plan lists
what to copy where. Two things need explicit sign-off and are called out there:

- **restarting `hlstatsx`** on the data server (Units 1, 2, 3)
- **distributing plugins to the fleet** — artifacts stage as `.new` and swap at
  the 03:00 ET restart, per `docs/DEPLOYING.md`

The rollback lever for everything plugin-side is `ktp_stats_capture 0` on the
server console: instant, no redeploy. It has been exercised — 10 kills during
`ktp_stats_capture 0` produced 0 assists, and 5 once re-enabled.

---

## Appendix A — re-verify the state

```bash
# In each repo:
git fetch origin
git log --oneline -1 origin/main          # or origin/master for KTPAMXX

# Commits a branch adds, and whether the stack still holds:
git rev-list --count origin/main..<branch>
git merge-base --is-ancestor <lower> <higher> && echo stacked || echo diverged

# Conflict dry-run between two branches:
git merge-tree $(git merge-base A B) A B | grep -c '^<<<<<<<'
```

If a stack has diverged from what this document says, prefer rebasing the
higher branch onto the lower one over merging out of order. The order exists
because of the seed-before-plugin rule, not for tidiness.
