# Production rollout status — reconciled 2026-08-13

Merges two independent audits of the same six/seven-phase stats-capture work
(`krod` = Drew, this session's git identity — `drewkrodleman@gmail.com`):

1. **This session's work**: Lane B (Docker, ephemeral MySQL, bot-driven)
   implementation + verification of Phases 5–7, plus a live-run regression
   pass on 2026-08-13.
2. **A colleague's independent production-rollout audit**, delivered as an
   artifact ("Stats-Capture Rollout"), which checked the *actual* production
   daemon and *actual* current git state — not Lane B — and found two traps
   that Lane B testing structurally cannot catch, plus one real defect in
   code this session verified.

Read this before touching production, and before opening or merging any of
the PRs in `PR_SEQUENCING.md` for Phases 5–7.

---

## The one thing to fix before anything else ships — DONE, 2026-08-13

**Fixed, committed, pushed.** `feat/break-context-parse` @ `f376724`
(KTPHLStatsX). PR not yet opened — this environment has no `gh`/GitHub API
write access; someone with credentials needs to open
`feat/break-context-parse` → `main` (this is M3 below).

**The `frag_context`/`break_context` marker+UPDATE pattern — used throughout
Phases 5 and 7 (`frag_context`, `break_context`, and the dead
`headshot_kill` code path) — had a real correctness bug.** Not found by any
Lane B run this session ran, because Lane B doesn't drop UDP lines; found by
reading the actual failure mode.

The handler matches on `serverId + killerId + victimId + weapon`, `ORDER BY
id DESC LIMIT 1`, with **no time bound and no rowcount check**. GoldSrc log
delivery is fire-and-forget UDP. If a frag line is lost but its follow-up
context line survives, the `UPDATE` silently rewrites the *previous* matching
frag row — potentially from an earlier match — with the wrong prone/scope/
ammo/position/`is_last_flag_defense` data. Silent, additive corruption, not
a crash and not a logged error.

**What shipped**: bounded every one of these `UPDATE`s to
`eventTime >= FROM_UNIXTIME($ev_unixtime - 60)` — **not** `NOW()`, which was
the first attempt and false-tripped immediately: `eventTime` is written from
`$ev_unixtime`, the event's own parsed-log-time clock basis, which diverges
from real wall-clock `NOW()` during any replay and would drift under a live
processing backlog too. `execNonQuery` (`HLstats.plib`) now returns its own
DBI affected-row count so the three call sites can check it directly and log
`KTP_NO_ROW_MATCHED` when it's legitimately zero — additive only, every
existing caller already ignores the return value.

**Validated with two Lane B replay controls, not production:**
- (a) frag + context together → row updates normally. Verified
  column-by-column against the source log's own `k_clip`/`k_ammo`/position
  values, not just a row count.
- (b) context with the frag deliberately dropped, **against a log
  constructed so a genuinely older matching row exists to corrupt** (an
  early control attempt used a killer/victim/weapon combo that had never
  appeared before, which would have "passed" even pre-fix — not a real
  test). Replayed against the **pre-fix** daemon first to confirm the
  defect is real: the old row's `headshot`/`k_prone`/`k_clip`/`k_ammo`/
  position were all silently overwritten from the orphaned marker 7 minutes
  later. Replayed again against the **fixed** daemon: the old row was
  untouched, and `KTP_NO_ROW_MATCHED` fired. Control (b) is the one that
  can't false-green — it's the only proof the guard actually does
  something, and reproducing the actual corruption first (not just
  asserting "0 rows") is what makes this a real proof rather than a
  plausible-sounding one.

This gates Waves B, C, and D below. It does **not** gate Wave A (assists /
cap-breaks / positions never emit `frag_context`).

## Two traps found in production/git state, invisible from Lane B

### Trap 1 — deploying "the stats stack" as-is would silently revert live production

Production is currently running **0.3.5** from KTPHLStatsX branch
`feat/unresolved-action-visibility` @ `0047f53` — **pushed, never merged**.
The Phase 5–7 stats work lives on entirely different branches. `main` has
neither change. They are disjoint.

| artifact | `Actions loaded for game` (0.3.5) | `frag_context` (new) |
|---|---|---|
| live `/opt/hlstatsx/…/hlstats.pl` | 1 | 0 |
| `origin/main` | 0 | 0 |
| `origin/feat/break-context-parse` | 0 | 3 |
| `0047f53` | 1 | 0 |

A deploy built from the stats branches alone removes `ktpAssertActionsSeeded`
— the startup assertion every seed gate in this project's testing depends
on. Nothing errors. The daemon comes up clean and the *verification itself*
quietly stops existing.

**Fix:** merge `feat/unresolved-action-visibility` → `main` **first** (step
M2 below), then the stats stack. A `git merge-tree` dry run predicts zero
conflicts — re-run it at actual merge time, not now.

**Gate to run on the deployed file before any restart, in production:**
```
grep -c "Actions loaded for game" hlstats.pl   # >0  0.3.5 present
grep -c "frag_context"            hlstats.pl   # >0  new handlers present
grep -c "zzq_not_a_real_marker"   hlstats.pl   #  0  proves the probe works
```
Verify identity by **normalised diff** against
`git show origin/main:scripts/hlstats.pl` — never byte size (the plib is
CRLF-vs-LF and got *smaller* on a change that only added lines) and never
mtime.

### Trap 2 — the old integration plan's SHA pins still verify, while pointing at superseded work

`STATS_CAPTURE_INTEGRATION_PLAN.md` §2 rows 6–8 pin three KTPAMXX branches
(`stats-assists`, `stats-cap-breaks`, `stats-positions`) by SHA. All three
**still match exactly**. They are also the **stale lineage** — based on a
commit `master` is now 23 commits ahead of. A matching SHA proves a branch
hasn't moved; it proves nothing about whether it's still the right branch.
The plan's own re-verification section returns green on all three anyway.

| lineage | branches | base | state |
|---|---|---|---|
| stale | `stats-assists` / `stats-cap-breaks` / `stats-positions` | `a052f7d9` (08-08) | 23 behind |
| live | `stats-frag-context` / `stats-damage-ledger` / **`stats-break-context`** | `9758f4db` (08-11) | = current master |

**Deleting the stale three loses nothing** — Phase 1–3 plugin content is
byte-identical across both lineages (`5f0e5379` and `989c8f4f` share blob
SHAs for both plugin files; the divergent patch-IDs are packaging, not
content). This session's Lane B evidence for phases 1–3 carries over
verbatim.

Also invisible to the old plan: six branches and three migrations it
mentions zero times, all created 08-11/08-12, after it was written.

**Cleanup (no production impact, do any time, ping Drew first):**
```
git tag archive/stats-assists-superseded-20260813    30da9b71
git tag archive/stats-cap-breaks-superseded-20260813 d0e88885
git tag archive/stats-positions-superseded-20260813  5f0e5379
git push origin --tags
git push origin --delete feat/stats-assists feat/stats-cap-breaks feat/stats-positions
```
Then in the plan doc: strike §2 rows 6–8, mark §4 spent, and add to §9 —
*always also check* `git rev-list --count origin/<branch>..origin/<default>`
*— a growing behind-count is the staleness signal, and it fails
informatively (unlike a SHA pin, which fails silently).*

## Merge sequence (Track M) — one PR per repo from the tip, not stacked

Stacked PRs already bit this project once — PR #2/#3 only auto-retargeted
because its base got deleted. Use `git worktree` per branch; never
`git add -A`. Public repos take no Claude co-author trailer.

| id | repo | action | gate |
|---|---|---|---|
| M1 | Infrastructure | Merge open **#54** (5 lines, inert) and **#55** (docs) | pins re-verified; approval |
| M2 | HLStatsX | **`feat/unresolved-action-visibility` → main** — codifies the deployed 0.3.5 | must land before M3 |
| M3 | HLStatsX | Push the frag_context fix (above) onto `feat/break-context-parse`; PR tip → main | fix validated; 0 conflicts |
| M4 | KTPAMXX | Push a buffer fix onto `feat/stats-break-context`; PR tip → master | footprint check; record wave refs |
| M5 | Infrastructure | `tier2-bot-lane-stats-e2e`: rebase → merge → *then* delete 3 stray docs | byte-identity of strays first |
| M6 | KTPAMXX | `lane-b-fakeclient-players` — **operator reads personally** (touches `meta_api.cpp`) | operator read; re-run merge-tree |
| M7 | Infrastructure | `lane-b-synthetic-match` — **this session's branch — do not merge, ping Drew** (no pushes in 3 days per the colleague's check) | Drew's call |

**Why M2 before M3:** the PR diff and the deployed artifact must both read
as main-plus-everything. The reverse order makes M3's review diff show a
phantom revert of 0.3.5.

Wave build refs, recorded at M4: `W-A 989c8f4f` · `W-B b15295c8` ·
`W-C 5eb05ebd` · `W-D` merge tip incl. buffer fix.

## Production data-server steps (Track S2) — one restart, not three

1. **Window check** — operator calendar clear, plus frags in the last 20
   minutes ≈ 0.
2. **Backups** — `hlstats.pl.bak-pre-0.4.0-<date>` and a DDL-only
   `mysqldump --no-data`.
3. **Apply migrations 005, 006, 007** — idempotent,
   `information_schema`-guarded. No GRANTs needed
   (`hlstatsx@localhost` already holds database-wide `ALL PRIVILEGES`). No
   restart needed for this step — new columns are invisible to the running
   daemon until it restarts.
4. **Migration verify**, with paired positive/negative controls (below) —
   an unpaired "expect 0" is not a passing test.
5. **Deploy `hlstats.pl` + both plibs from `origin/main`** — run the Trap 1
   two-marker gate here, on the file about to go live.
6. **Restart** (operator permission in the moment) → expect
   `Actions loaded for game 'dod': 16`. **Still 16** — migrations 005–007
   seed no new actions. Anything else, stop and explain before continuing.
7. **Same-evening regression** — frag volume normal after 19:00 local, zero
   `SQL_ERROR`, suicides still landing.

Journal greps need a non-empty positive control — an empty journal makes
"zero SQL_ERROR" a false clean.

## Four rollout waves (phases 1–3 bundled, then one suspect per night)

Bundled because Wave A's code is byte-identical to what Lane B already
exercised live and its smoke queries are per-action (attribution survives
bundling). Kept 4/5/6 separate because each adds a genuinely distinct daemon
failure mode: UPDATE-rewrite risk (frag context), insert volume (damage
ledger), timing/attribution (break context).

No branch re-cutting needed — all four refs are in `master`'s history after
M4. Build each in a throwaway worktree so the main tree stays undisturbed:
```
git worktree add ../KTPAMXX-wave <ref>
wsl bash -c "cd '/mnt/n/.../KTPAMXX-wave' && KTP_NO_STAGE=1 bash compile.sh"
md5sum <artifact>    # record, then: git worktree remove ../KTPAMXX-wave
```
**Never rebuild a shipped ref** — AMXX bakes a per-minute `BUILD_TIME`, so a
rebuild churns the pinned md5 and the wave can no longer be verified against
what was actually reviewed.

| wave | ref | carries | needs first |
|---|---|---|---|
| A | `989c8f4f` | assists · cap-breaks · positions | nothing — daemon side live since 08-12 |
| B | `b15295c8` | frag context | Track S2 + the frag_context fix |
| C | `5eb05ebd` | damage ledger | smoke B green |
| D | merge tip | break context + buffer fix | smoke C green |

Rejected: tip-only in one wave (a red smoke can't name its phase; a
mis-rewritten frag is silent corruption, additive to the noise). Defensible
alternative: six waves for maximum attribution, at the cost of two more
nightlies.

### Smoke gates per wave

- **Migrations live**: 005 → 8 new columns on `hlstats_Events_Frags`. 006+007
  → both new tables present. Positive control: `match_id` on Frags → expect
  1. Negative control: `no_such_column` → expect 0.
- **Wave A**: assists present on the player-player path, **exactly zero** on
  the player-action path (the `for_PlayerActions` flag doing its job).
  `hlstats_Events_Statsme` non-zero after a real match end (the one check
  Lane B structurally cannot do). Cap breaks present, with two production-only
  negatives: clean-cap (no phantom breaks after a completed cap) and
  round-restart (no burst at capout) — judge by named killer or a ±10s
  no-death window, never "was there a break around then." Positions
  non-NULL, not all-zero, in-bounds; exercise the kill switch once live as
  the positive control on the rollback lever itself.
- **Wave B**: context columns populated on essentially every kill; journal
  shows *Frag context marked* lines; the new no-row-matched warning ≈ 0,
  each occurrence explainable as UDP loss (meaningful now that control (b)
  above proved the line can actually fire).
- **Waves C & D**: C — rows landing, plausible hits-per-kill ratio,
  non-degenerate hitplace distribution, no daemon backlog, and *measured*
  table growth per evening (feeds the retention decision, D-6 below). D —
  break context populated, flag positions plausible per map, clean-cap
  negative re-run, no dropped-line logs now the buffer has real headroom.

## Rollback levers, cheapest first

| step | lever | note |
|---|---|---|
| Track M merges | `git revert` | nothing deploys on merge; zero exposure |
| Migrations | none needed — leave them | additive, inert without daemon + plugin |
| Daemon deploy | restore the `.bak`, restart in a window | take the kill switch FIRST if any wave is live |
| Any wave | `ktp_stats_capture 0` — instant rcon, no redeploy | covers **all** phases at once; no per-phase disable exists |
| Wave artifact | previous wave's `.amxx` staged as `.new` | stack-order only: D → C → B → A; pin from recorded md5s, never rebuild |
| Bad rewrites | reset context columns for the affected window | frag rows themselves stay intact — the columns are additive |

## Who does what

**Agent, unattended:** every verification sweep and smoke query; pushing the
frag_context fix and buffer fix to feature branches and opening PRs;
merge-tree dry runs; wave builds at recorded refs in worktrees with md5
derivation; the two-control replay validation; TODO/docs/board edits;
CLAUDE.md updates *after* fleet-md5 verification; morning fleet sweeps
(reporting, not deciding).

**Drew, blocking:** every PR merge (M6 personally — it touches
`meta_api.cpp`), every wave-staging invocation, every daemon restart with
its in-the-moment window confirmation.

| id | decision | recommendation |
|---|---|---|
| D-1 | delete the stale branches | yes, after pinging Drew |
| D-2 | bundled or phased rollout | 4 waves — A bundled, 4/5/6 separate |
| D-3 | Wave A timing | Friday PM — best-verified artifact in the set |
| D-4 | AmxxCurl / ReAPI nightly slot order | AmxxCurl first free night; never share a nightly with a stats wave |
| D-5 | add `stats_logging.amxx` to `PLUGINS_STRICT` | yes, after Wave A verifies |
| D-6 | retention policy for the per-hit damage table | decide once Wave C reports real volume |

---

## This session's contribution — where it plugs into the above

- Phases 5–7 (frag context, damage ledger, break context/flag
  positions/last-flag-defense) are implemented, compiled clean, and Lane-B
  live-verified — this is the code the waves above ship. See
  `docs/ktpr_mcp/KTPR_DEPLOYMENT_PLAN.md` and `CONTINUATION_NOTES.md` for
  the phase-by-phase detail and exact branch SHAs (`feat/stats-break-context`
  @ `0af155fe` KTPAMXX, `feat/break-context-parse` @ `0753474` KTPHLStatsX
  — these are the tips M3/M4 above push fixes onto).
- **2026-08-13 regression run**: a 4-match Lane B series lost its live DB
  to a WSL/Docker restart mid-run (host went away; container state does not
  survive that, by design of `--rm`). The raw game log for the clean,
  complete first match survived (host-mounted, not container-local) and was
  replayed offline through the daemon to reconstruction a full fixture —
  352 kills, 57 assists, 3 cap breaks, 15 suicides, 877 damage events, all
  positions populated. Persisted at
  `tests/e2e_stats/fixtures/regression-2026-08-13-match1/` (SQL dump,
  manifest, gzipped raw log) for offline exploration without needing Lane B
  running again.
- **A finding from that run turned out to be a false alarm, and the false
  alarm itself is now documented in the harness**: querying the live
  ephemeral DB mid-run showed 0 assist rows despite the daemon visibly
  processing 66+ `triggered "assist"` lines. Root cause: `hlstats.pl
  --stdin` mode (which Lane B always uses) gates its periodic 30s flush
  loop behind `if ($g_stdin == 0)`, so assists — which have no explicit
  synchronous flush the way `frag_context`/`break_context` markers do —
  only land at process shutdown (`flushAll(1)` on stdin EOF). Confirmed by
  enabling MySQL's general query log mid-run (zero `INSERT` attempts against
  `PlayerPlayerActions` the whole time) and by the clean 57/57 replay above.
  **This is not the frag_context defect described earlier in this doc** —
  different mechanism, different table, no data corruption, just deferred
  visibility. `HlstatsDaemon.stop()` in `tests/e2e_stats/hlstats_daemon.py`
  already documents this exact symptom and handles it correctly (60s grace
  before dump); the mistake was mine, checking the DB directly instead of
  through the harness's own completion path.
- New script `scripts/replay_and_dump.py` — combines `replay_daemon.py`'s
  offline-replay with a `mysqldump` step, for exactly this recovery
  scenario (a captured log, no live run available). Not yet given a PR.

## What's still needed before the next full handover dump

1. ~~Write and validate the frag_context time-bound fix~~ **DONE 2026-08-13**
   — committed, pushed to `feat/break-context-parse` @ `f376724`. Blocked on
   someone with `gh`/GitHub write access opening the M3 PR (`feat/break-context-parse`
   → `main`) — this environment has neither.
2. **Open PRs generally** — this environment has no `gh` CLI and no GitHub
   API write access, so M1–M4's PR-opening steps are all blocked here
   regardless of code readiness. `feat/stats-frag-context`,
   `feat/ktp-damage-event`/`feat/stats-damage-ledger`, and
   `feat/break-context-parse`/`feat/stats-break-context` are all pushed but
   PR-less, per `PR_SEQUENCING.md`. Needs either credentials in this
   environment or someone to open them manually.
3. **Re-run the interrupted 4-match Lane B regression to completion** —
   this session only recovered match 1 of 4 after the host restart. Matches
   2–4 would extend coverage (more break/assist volume, a second map
   rotation) but aren't blocking; call this "nice to have" unless the
   colleague's audit surfaces a reason to want more volume specifically.
4. **Decide and execute Trap 2 cleanup** (D-1) — low risk, no prod impact,
   just needs Drew's go-ahead on the tag-then-delete sequence.
5. **`KSC_LAST_FLAG_RADIUS` tuning** — still an unmeasured estimate (see
   Phase 7 notes in `CONTINUATION_NOTES.md`); worth resolving before Wave D
   smoke-tests last-flag-defense in production, since a wrong radius would
   silently mis-tag a KTPR-facing stat.
6. **M6's personal `meta_api.cpp` review** and **M7's go/no-go on
   `lane-b-synthetic-match`** are both explicitly Drew's calls, not
   agent-executable — flag them rather than guess.

Once 2 and 4–5 are resolved (3 is optional, 6 is Drew's own action), the
production rollout plan above is executable end-to-end without further
reconciliation work.