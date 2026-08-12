# Handover: merging the stats-capture work into the default branches

**For:** whoever opens and merges the PRs.
**Goal:** get `main`/`master` across three repos to what has been verified
locally.
**Verified against remotes on 2026-08-12 (re-checked same day, after the
first three PRs merged).** If you read this much later, re-run the commands
in [Appendix A](#appendix-a--re-verify-the-state) first — or just run
`check_pr_status.ps1` at the repo root (one level up from
`KTPInfrastructure`): `powershell -File check_pr_status.ps1`.

**Merged as of 2026-08-12: KTPHLStatsX PRs
[#1](https://github.com/afraznein/KTPHLStatsX/pull/1) (suicide fix),
[#3](https://github.com/afraznein/KTPHLStatsX/pull/3) (cap-break seed) and
[#4](https://github.com/afraznein/KTPHLStatsX/pull/4) (assist seed, the
final merge into `main`).** That's all of Units 1–3's DB half. Their
KTPAMXX plugin halves (Units 2–4) still have no PR open.

**Open, not yet merged:**
[KTPInfrastructure #54](https://github.com/afraznein/KTPInfrastructure/pull/54),
[#55](https://github.com/afraznein/KTPInfrastructure/pull/55).

**Pushed but no PR opened yet** (rebased onto the post-merge `main` the same
day the merge landed, per the rule below, then pushed): KTPHLStatsX
`feat/frag-context-columns`, `feat/ktp-damage-event`; KTPAMXX
`feat/stats-frag-context`, `feat/stats-damage-ledger`. All four are ready for
a PR to be opened whenever — nothing blocks it.

**Branches with an open PR should not be rebased or force-pushed** until that
PR merges or is explicitly abandoned — rewriting history mid-review is more
disruptive than the staleness it would fix. Branches with no PR yet are safe
to rebase onto current main/master at any time; do that once, right before you
open the PR, not continuously.

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

KTPHLStatsX `main` moved twice since 2026-08-10: once from unrelated work
(a `ktp_schema.sql` MySQL/MariaDB fix), then again from **PRs #1/#3/#4
merging Units 1–3's DB half in**. KTPAMXX `master` and KTPInfrastructure
`main` only moved from unrelated work (dodx territorial-scoring-clock;
hltv logging, a tier2 manifest-pin fix, stage-runner versioning, docs) — none
of it overlaps these branches' files, checked directly, not assumed.

| Repo | Default branch | At |
|---|---|---|
| KTPHLStatsX | `main` | `e2b6e7b` (was `86621f2` before PRs #1/#3/#4) |
| KTPAMXX | `master` | `9758f4db` |
| KTPInfrastructure | `main` | `39bc74a` |

### KTPHLStatsX — Units 1–3 merged; the stack continues from `main`

```
main (e2b6e7b) — Units 1, 2, 3 all in: fix/suicide-dispatch-goldsrc,
                 feat/seed-assist-action, feat/seed-cap-break-action
 └─ feat/frag-context-columns 19650f7  2 commits  Unit 5  (no PR yet, pushed)
     └─ feat/ktp-damage-event 757ac96  1 commit   Unit 6  (no PR yet, pushed)
```

Rebased onto the post-merge `main` and pushed on 2026-08-12, same day the
merge landed — content-identical to the pre-rebase versions, verified by
diff-stat parity before push. No PR existed for either at rebase time, so
this was safe per the rule below.

### KTPAMXX — a clean stack of five, plus one independent

```
master (9758f4db)
 └─ feat/stats-assists          776ce9fe  1 commit    Unit 2  (no PR yet)
     └─ feat/stats-cap-breaks   f73d0282  2 commits   Unit 3  (no PR yet)
         └─ feat/stats-positions 989c8f4f 3 commits   Unit 4  (no PR yet)
             └─ feat/stats-frag-context b15295c8 4 commits Unit 5 (no PR yet, pushed)
                 └─ feat/stats-damage-ledger 5eb05ebd 2 commits Unit 6 (no PR yet, pushed)

master (9758f4db)
 └─ feat/lane-b-fakeclient-players  684d3af1  1 commit   test-only, no unit (no PR yet)
```

KTPAMXX's `master` hasn't moved, so nothing here needed rebasing — pushed
as-is on 2026-08-12.

### KTPInfrastructure — three independent branches, plus the Lane B work-in-progress

```
main (39bc74a)
 ├─ docs/stats-capture-plan-branch-status  14a68be   1 commit,  1 file        (PR #55, open)
 ├─ feat/stats-capture-include             53ea398   1 commit,  5 lines       (PR #54, open)
 └─ feat/tier2-bot-lane-stats-e2e          806a365  18 commits, 45 files      (no PR yet, rebased 2026-08-12)
     └─ feat/lane-b-synthetic-match        fef92da  10 commits on top         (active work-in-progress, not ready for PR)
```

---

## Merge order

Numbered so you can work straight down. Do not batch two un-smoke-tested units
onto the fleet — if something is wrong you want one suspect, not two.

| # | Repo | Branch | PR base | Notes |
|---|---|---|---|---|
| 1 | ~~KTPHLStatsX~~ | ~~`fix/suicide-dispatch-goldsrc`~~ | ~~`main`~~ | **MERGED**, PR #1. Unit 1. |
| 2 | KTPInfrastructure | `feat/stats-capture-include` | `main` | 5 lines. Do it early: the plugin build needs the `.inc` to be copied, and it is harmless on its own. PR #54, open. |
| 3 | ~~KTPHLStatsX~~ | ~~`feat/seed-assist-action`~~ | ~~`fix/suicide-dispatch-goldsrc`~~ | **MERGED**, PR #4. Unit 2, DB half. |
| 4 | KTPAMXX | `feat/stats-assists` | `master` | Unit 2, plugin half. **Apply step 3's seed and restart the daemon before this ships** — already true even though step 3 is merged; the daemon still needs its own restart, separate from the merge. No PR yet. |
| 5 | ~~KTPHLStatsX~~ | ~~`feat/seed-cap-break-action`~~ | ~~`feat/seed-assist-action`~~ | **MERGED**, PR #3. Unit 3, DB half. |
| 6 | KTPAMXX | `feat/stats-cap-breaks` | `feat/stats-assists` | Unit 3, plugin half. Seed already merged; still needs the daemon restart before this ships. No PR yet. |
| 7 | KTPAMXX | `feat/stats-positions` | `feat/stats-cap-breaks` | Unit 4. No SQL, no daemon change. No PR yet. |
| 8 | KTPInfrastructure | `docs/stats-capture-plan-branch-status` | `main` | Docs only. PR #55, open. |
| 9 | KTPInfrastructure | `feat/tier2-bot-lane-stats-e2e` | `main` | The Lane B test infrastructure. **Rebase onto `main` after step 8** — see the conflict note. No PR yet. |
| 10 | KTPAMXX | `feat/lane-b-fakeclient-players` | `master` | Test-only. Optional, but Lane B cannot run without it — see below. No PR yet. |
| 11 | KTPHLStatsX | `feat/frag-context-columns` | `main` | Unit 5, DB half. Base is `main` directly now (was `feat/seed-cap-break-action`, merged 2026-08-12) — **rebased and pushed already**. **Apply the seed SQL and restart the daemon before step 12.** No PR yet. |
| 12 | KTPAMXX | `feat/stats-frag-context` | `feat/stats-positions` | Unit 5, plugin half. Retires the old `headshot_kill` marker — see below. Pushed, no PR yet. |
| 13 | KTPHLStatsX | `feat/ktp-damage-event` | `feat/frag-context-columns` | Unit 6, DB half. Creates `ktp_damage_events` — **apply before step 14**, though unlike other units a backwards deploy here fails loudly (daemon `INSERT` errors) rather than silently. Pushed, no PR yet. |
| 14 | KTPAMXX | `feat/stats-damage-ledger` | `feat/stats-frag-context` | Unit 6, plugin half. Damage capped at 100 — see below. Pushed, no PR yet. |

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

### 11 — `feat/frag-context-columns`, 12 — `feat/stats-frag-context` (Unit 5)

Eight new columns on `hlstats_Events_Frags` (prone/scope/clip/ammo, killer and
victim) plus a new daemon handler for a `frag_context` marker fired on every
kill. **This retires `stats_logging.sma`'s old dedicated `headshot_kill`
marker** — headshot itself needs no new column, it already existed from that
marker, which is why this unit adds 8 columns, not 9.

Same ordering rule as Units 2/3, but the failure mode if you get it backwards
is different and milder: an unseeded `hlstats_Actions` row silently drops
data with no error (the Philly LAN failure mode). Missing *columns* instead
makes the daemon's `UPDATE` fail loudly against a table that doesn't have
them — noisy, not silent. Still land the seed first; there's no reason to
take the noisy failure over no failure.

**Widest-blast-radius plugin change in the whole stack.** `client_death` in
`stats_logging.sma` — which every other unit's kill-time capture also flows
through — now does nothing but dispatch into `ksc_on_death`. Re-run Units
2/3/4's smoke tests after this one, not just Unit 5's own.

Compiled against the KTP fork's `amxxpc` (0 warnings) and `hlstats.pl`
syntax-checked with `perl -c`, both inside the Lane B image, before this was
written up — see Unit 5 in `KTPR_DEPLOYMENT_PLAN.md` for the live-run numbers.

### 13 — `feat/ktp-damage-event`, 14 — `feat/stats-damage-ledger` (Unit 6)

A new standalone table, `ktp_damage_events`, plus a `damage` marker fired on
every `client_damage` hit — enemy, team, and self alike. **First unit that
doesn't extend a stock `hlstats_Events_*` table** — it's a direct-`INSERT`
handler, same shape `KTP_MATCH_*` already uses, not the generic
`recordEvent`-batched mechanism.

**Damage is capped at 100 in a second column, `damage_capped`.** DoD's raw
per-hit value is the nominal weapon value with multipliers applied
(headshot, wallbang) and is not clamped to a player's actual 0-100 HP pool —
a single hit can log 400+. Live run: max raw value observed was 212,
18/216 rows exceeded the cap and were correctly clamped to 100. Raw is kept
alongside the capped value — nothing discarded — but **any KTPR-facing
consumer should read `damage_capped`, not `damage`.** Same convention CS2
uses, prompted directly by user feedback during this phase.

No colleague sign-off needed on ordering risk the way Units 1-3 have it: a
backwards deploy here (plugin before table) fails loudly — the daemon's
`INSERT` errors against a missing table — rather than silently discarding
data the way an unseeded `hlstats_Actions` row does. Still land the seed
first; a noisy failure beats depending on that distinction.

Compiled against the KTP fork's `amxxpc` (0 warnings) and `hlstats.pl`
syntax-checked with `perl -c`. Live run: 216/216 damage markers carried, 0
cap violations, 0 dropped buffer lines at the new 128-entry size (up from
48 — this event type fires far more often than any prior capture),
zero regressions on Units 2-5 — see Unit 6 in `KTPR_DEPLOYMENT_PLAN.md`.

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
