# Stats-capture + Lane B integration & scheduling plan

**Written:** 2026-08-10 (Mon), from read-only investigation.
**Scope:** how the 11-branch stats-capture body of work (krod's handover set) plus the Lane B
test lane integrates into KTP, against a deploy cadence of one fleet wave per nightly, a full
queue through Wed 08-12, and a hard freeze Thu 08-13 – Fri 08-14 (S10 registration deadline).
**Companions:** `docs/PR_SEQUENCING.md`, `docs/CI_CD_LANE_B.md`, `docs/MYSQL_VS_MARIADB.md`
(krod's handovers — currently untracked strays at `docs/`; the canonical copies land at
`docs/handover/` when `feat/tier2-bot-lane-stats-e2e` merges),
`docs/ktpr_mcp/KTPR_DEPLOYMENT_PLAN.md` (per-unit deploy + smoke detail — on that branch, not
yet on `main`), `tests/e2e_stats/NEXT_PHASES.md` (same).

**Nothing in this plan was executed.** Every stage, restart, merge and push below is a proposal
gated on the operator, except the items explicitly listed as agent-unattended in §8.

---

## 0. What was independently verified today vs. taken on krod's word

Verified against the remotes / working tree on 2026-08-10 (commands in §9):

- All branch SHAs match `PR_SEQUENCING.md` **except**: KTPInfrastructure
  `feat/tier2-bot-lane-stats-e2e` is now `73ccf85` (doc says `8fedbbc`) — the newest commit adds
  the ktpamx build cache action and the three handover docs (at `docs/handover/`).
- **A 12th branch exists that the handover does not mention:**
  `origin/feat/lane-b-synthetic-match` @ `378c5c2`, stacked on `feat/tier2-bot-lane-stats-e2e`,
  pushed by krod (Drew) **today 12:55 ET** — it is Phase B½ (the synthetic match) already in
  flight: `lane_b_match_series.py`, `containment.py`, `KTPMatchDrive.sma`, and a diagnosis of a
  second-half-zero-kills issue (production halftime is a map change, not a pause). Phase B½ is
  therefore **started, not owed from scratch** — and it is active work by another contributor;
  coordinate, don't fork it.
- KTPAMXX `master` has moved to `72fc4824` (the DODX 2.7.27 approval/changelog commits) since
  krod's doc pinned it at `abd3e1b3`. The stats branches' true merge-base is `a052f7d9` (older
  than krod's diagram implies). **`git merge-tree` re-run today: 0 conflicts** for
  `feat/stats-assists` vs current master and for `feat/lane-b-fakeclient-players` vs master.
- The stats stack (`a052f7d9..feat/stats-positions`) touches **only**
  `plugins/dod/stats_logging.sma`, `plugins/dod/ktp_stats_capture.inc`, `CHANGELOG.md` — no
  module code, no `product.version`. The fleet-facing artifact of Units 2–4 is exactly one
  plugin: `stats_logging.amxx`.
- The three stray docs at `KTPInfrastructure/docs/*.md` are **byte-identical** to the branch's
  `docs/handover/*.md` copies. They are duplicates at a different path: after the branch merges
  they must be **deleted**, not committed (⚠️ the working tree is currently on
  `feat/hltv-viewer-logging` with PR #50 in flight — a careless `git add -A` there would commit
  them into an unrelated PR).
- The stale-workflow claims spot-check true: `.github/workflows/lane-b-stats-e2e.yml` on the
  branch still defaults `marinebot`, still fetches `LANE_B_BOT_KIT_URL`, cron `0 6 * * *`,
  `concurrency` with `cancel-in-progress: false`, `timeout-minutes: 60`.
- `sql/ktp_schema.sql` header on `main` confirms the MariaDB-only defect and — worth noting —
  its 2026-07-20 production verification lists `match_id` present on "Frags / Teamkills /
  PlayerActions" and **does not name `hlstats_Events_Suicides`**. Before Unit 1 ships, verify
  that column exists in production (§5, gate S-0) — a missing column turns every suicide INSERT
  into a per-row SQL error.
- `stats_logging.amxx` is **not** in the tier-2 drift checker's `PLUGINS_STRICT` or
  `PLUGINS_TESTMODE` lists (`scripts/ktp-tier2-stack-drift.py`), so a fleet bump of it will not
  trip the runner tripwire. Decision for the operator: add it to `PLUGINS_STRICT` once Unit 2
  ships (§8).
- No `PUSH HOLD` in `TODO.md` today (grep re-run; the ReAPI push in §6 still re-checks first).

Taken on krod's word (plausible, consistent with artifacts, but **not** independently
reproducible from this machine — the run outputs live in krod's `~/lane-b-out`):

- All Lane B live-run figures (5/5 assists carried, 13/13 headshots, kill-switch counts, the
  suicide 3→0/3→3 control, the staged cap-break negatives).
- The cache action having been "tested locally in both directions".
- `fetch_base_schema.sh --from-production` behavior and the two reconstruction fixes.
- "Production Docker build byte-for-byte unchanged" for `feat/lane-b-fakeclient-players`
  (stated as verified in today's briefing; the compile-time gate is visible in the diff —
  `AMBuildScript` + `amxmodx/meta_api.cpp` only).

None of these need re-proving to *merge*; the ones that guard a *deploy* are re-proved by the
gates in §5 (live smoke on real matches), which is where they belong anyway — Lane B proves the
code path, not the deployment (`sv_lan 1`, bots, no Steam auth, reconstructed daemon).

---

## 1. The shape of the problem

Three kinds of work travel together but deploy on completely different risk surfaces:

| Kind | Items | Production contact |
|---|---|---|
| **Merges** | 12 branches, 3 repos | none — merging is not deploying here (no auto-deploy path exists; fleet artifacts are staged by hand via `stage-wave.py`) |
| **Data-server deploys** | Unit 1 `hlstats.pl` fix; migrate_003 + migrate_004 seeds; one `hlstatsx` restart | daemon serving all 24 instances; restart loses all UDP log traffic while down and NULLs match_id for a half if it lands mid-match |
| **Fleet waves** | `stats_logging.amxx` × 3 versions (Units 2, 3, 4); plus the two displaced artifacts KTPAmxxCurl 1.3.16 and KTPReAPI `.366`+`.367` | one wave per nightly, 03:00 ET activation, attribution gate refuses stacking |
| **Test-lane / CI** | Phase B½, base-schema commit, `ktp_schema.sql` fix, workflow rewrite | none — GH-hosted runner only, never the Tier 2 box |

The binding resource is **nightlies**: 5 artifacts want fleet slots (3 stats waves + AmxxCurl +
ReAPI) and zero slots exist before Sat 08-15. The freed resource is **everything else**: merges
and the entire Lane B/CI track can run through the freeze week without touching production.
That asymmetry is the plan: *front-load all non-production work into the freeze week, batch the
data-server work into a single restart on Mon 08-17, then spend the following week's nightlies
one artifact at a time.*

### Decomposition decisions, with reasoning

**D1 — One daemon restart, not three.** Units 1, 2 and 3 each nominally want a daemon change +
restart. Batched instead: apply `migrate_003` **and** `migrate_004`, deploy the Unit 1
`hlstats.pl`, restart **once**. Safe because seed rows are inert until a plugin emits the
matching lines (both plugins ship later, each behind its own gate), and each piece is verified
by its own query (§5), so attribution survives the batch: the only *code* in the restart is the
one-`elsif` suicide fix, and the seeds are data proven by SELECT. This turns three
match-window-constrained, sign-off-requiring restarts into one, and clears the
seed-before-plugin precondition for Units 2 **and** 3 in a single move.

**D2 — Units 2, 3, 4 ship as three separate single-artifact waves, in stack order.** The
alternative (one combined wave, since Lane B pre-verified most of all three) was considered and
rejected: Unit 3's detection is timing-based with two negatives (clean-cap, round-restart) that
can only be observed on live matches *after* it activates, and a false-positive cap break is a
silent, additive corruption. One unit per wave keeps one suspect per night and lets each unit's
live evenings gate the next. The extra cost is two nightlies — cheap. (If the operator wants to
compress, the defensible batch is Unit 3+4 — Unit 4 is purely additive and Lane-B-covered — at
the price of two suspects on the same wave; not recommended.)

**D3 — Merge everything mergeable during the freeze week, except KTPAMXX.** KTPHLStatsX and
KTPInfrastructure merges touch no fleet artifact. KTPAMXX merges are held until **after the
DODX 2.7.27 + KTPMatchHandler 0.10.157 pair is staged Tue 08-11 PM** (activates Wed): pins are
re-derived from fresh builds at stage time, and a master that moved under the pair invites
rebuilding from the wrong tree — the known `.amxx`-pin failure mode ("a shared repo moving
under you"). Merging Wed after the pair's activation verify costs nothing and removes the trap
entirely.

**D4 — Because the units merge before they ship, each unit's fleet artifact builds from its
merge commit, not from branch tips.** After Wed's merges, master's `stats_logging.sma` carries
all three units. The Unit 2 wave builds at the *merge commit of `feat/stats-assists`* (call it
M2), Unit 3 at M3, Unit 4 at tip — each is committed, reviewed source, satisfying
"commit before the build you ship". Record M2/M3/M4 SHAs at merge time. Additionally, run a
Lane B pass against the exact commit being shipped before each stage (Lane B compiles plugin
artifacts from arbitrary refs) — a pre-stage gate that costs one GH-runner hour and no
production contact.

**D5 — The displaced artifacts interleave; they do not queue behind the stats work.**
KTPAmxxCurl 1.3.16 (approved, pushed, CI green) takes the first post-freeze nightly, ReAPI
`.366`+`.367` (approved, **unpushed**) takes the Thu slot — both fill nights the stats track
cannot use anyway because it is waiting on live-match smoke evidence. See §6.

**D6 — Lane B CI is built in krod's stated order** (Phase B½ → base-schema → workflow rewrite →
manual dispatches → schedule), because the workflow must be rewritten regardless and B½ changes
what it runs. Phase B½ is already in flight on `feat/lane-b-synthetic-match`; the agent-side
contribution during the freeze is the base-schema commit, the `ktp_schema.sql` fix, and the
workflow rewrite *behind* B½ — not a parallel reimplementation of it.

---

## 2. Merge plan (Track M — no production impact)

Krod's order stands, with three amendments: the moved tier2 branch SHA, the deferred-KTPAMXX
rule (D3), and the 12th branch appended. Open stacked PRs against their parent branch (GitHub
auto-retargets on base merge).

| # | Repo | Branch @ verified SHA | PR base | When | Notes |
|---|---|---|---|---|---|
| 1 | KTPHLStatsX | `fix/suicide-dispatch-goldsrc` @ d3921b7 | `main` | Mon 08-10 | Gate cleared per krod (verb string + 0→3 control). Merge now. |
| 2 | KTPInfrastructure | `feat/stats-capture-include` @ 53ea398 | `main` | Mon 08-10 | 5 lines, inert until a plugin `#include`s the `.inc`. ⚠️ The Docker plugin build COPYs from the **local sibling KTPAMXX checkout** — after this merges, any plugin-image build needs both local trees current, or it fails loudly (nuisance, not hazard). |
| 3 | KTPHLStatsX | `feat/seed-assist-action` @ 7eefed6 | branch #1 | Mon–Tue | Merging ≠ applying; the SQL applies Mon 08-17 (§5). |
| 4 | KTPHLStatsX | `feat/seed-cap-break-action` @ a8c9a97 | branch #3 | Mon–Tue | Same. |
| 5 | KTPInfrastructure | `docs/stats-capture-plan-branch-status` @ 14a68be | `main` | Mon–Tue | Docs only. |
| 6 | KTPAMXX | `feat/stats-assists` @ 30da9b71 | `master` | **Wed 08-12, after the pair's activation verify** | Record merge commit **M2**. merge-tree vs today's master: 0 conflicts (re-verify at merge time — master will have moved again if the pair re-cut). |
| 7 | KTPAMXX | `feat/stats-cap-breaks` @ d0e88885 | branch #6 | Wed 08-12 | Record **M3**. |
| 8 | KTPAMXX | `feat/stats-positions` @ 5f0e5379 | branch #7 | Wed 08-12 | Record **M4**. |
| 9 | KTPAMXX | `feat/lane-b-fakeclient-players` @ c1408a48 | `master` | Wed 08-12 | Touches `amxmodx/meta_api.cpp` — **operator reads this one** (krod's own instruction). Compile-gated `KTP_LANE_B_FAKECLIENTS`, off by default; Lane B is blind without it. ⚠️ Do not rebuild the live AMXX core "to check" — per-minute timestamp churns the shipped md5. |
| 10 | KTPInfrastructure | `feat/tier2-bot-lane-stats-e2e` @ **73ccf85** | `main` | Wed–Thu, after #5 | **Rebase onto main after #5 merges** (krod's instruction; merge-tree predicts clean but don't rely on it). Then **delete the three stray `docs/*.md`** — the branch lands them at `docs/handover/`. |
| 11 | KTPInfrastructure | `feat/lane-b-synthetic-match` @ 378c5c2+ | branch #10 | when B½ meets its DoD | **krod's active branch — do not merge out from under him.** Merges when the synthetic match is green (Statsme assertion, containment assertions, halftime map-reload handled). |

Not in the table: nothing in Track M requires a nightly, a restart, or fleet contact.

---

## 3. Lane B / CI plan (Track L — GH-hosted only, freeze-proof)

Runs continuously through the freeze. Standing rules carried from the handover, all adopted:
GH-hosted runner **never** the Tier 2 box; no `pull_request` trigger; non-gating; 06:00 UTC
slot; keep `concurrency` with `cancel-in-progress: false`; keep the 60-minute timeout; MySQL
8.0.46 in the image, never MariaDB.

### L-1. Base schema → committed (decision: agree with krod, with content gates)

Commit `base-schema.sql` to KTPInfrastructure. It is DDL-only and reproducible; a secret or
fetched artifact adds a failure mode and protects nothing. **Gates before the commit lands:**

```bash
grep -c 'CREATE TABLE' base-schema.sql        # expect 64
grep -ciE '^INSERT|^REPLACE|VALUES *\(' base-schema.sql   # expect 0
grep -inE 'identified by|:.*@|password *=' base-schema.sql # expect 0 hits
# NB a hit on the *column name* rcon_password is expected and correct —
# it is one of the two reconstruction fixes. Column names are not secrets.
```

Ideally re-take with `fetch_base_schema.sh --from-production` first (read-only `mysqldump
--no-data` over SSH to the data server) so the committed copy is production's own DDL and
`PROVENANCE` stops saying `RECONSTRUCTION`. That needs operator-approved SSH (§8); until then
the reconstruction + `repair_reconstructed_schema` is valid and the commit should not wait on
it — note the provenance in the commit message and swap the file when the dump is taken.

### L-2. `ktp_schema.sql` MySQL/MariaDB fix (decision: option 1 now, option 3 later)

Evaluated krod's three options:

| Option | Verdict |
|---|---|
| 1 — `information_schema`-guarded ALTERs via prepared statements | **Do this now.** Plain SQL, no new privileges, keeps the file idempotent in both directions, **changes nothing in the operator runbook** (fresh provision is still "run `ktp_schema.sql`"), and a working in-repo reference exists (`hlstats_daemon.py` `repair_reconstructed_schema`). |
| 2 — self-dropping stored procedure | Rejected: needs `CREATE ROUTINE`, which the migration account may not have — an unverified privilege dependency in exactly the disaster-recovery path where nobody wants surprises. |
| 3 — numbered one-way migrations + applied-state tracking | **Right long-term direction** (matches migrate_002/003/004 house style) but it **changes the operator runbook** (fresh provision becomes "apply migrations in order") and restructuring needs maintainer sign-off per krod. File as a follow-up, blocked on that sign-off. |

Verification, both directions, in Lane B (never production): apply the fixed file to an
**empty** MySQL 8.0.46 (must create everything — the fresh-provision path), then re-apply to a
database that already has it (must no-op — the path production actually takes; this is the leg
a naive "delete IF NOT EXISTS" fix breaks). Use `LANE_B_APPLY_KTP_SCHEMA=1`; do **not** make
Lane B apply it by default (krod's "one thing not to do" — kept).

This is repo-only and production-inert (the file only runs at fresh provision); it can merge
any time this week. It is nonetheless the **real** production defect in the set — the next LAN
provision or DR rebuild silently loses match attribution without it.

### L-3. Workflow rewrite (after B½ lands)

Rewrite `.github/workflows/lane-b-stats-e2e.yml` once, against the finished lane, per
`CI_CD_LANE_B.md` §§1–6: cached ktpamx action (no continue-without-binary fallback — a lane
that cannot see bots goes green having measured nothing), daemon-tree assembly with
`PROVENANCE` published, `base-schema.sql` as `--schema`, the unit suite (`pytest`, ~20s) before
the expensive leg, delete the bot-kit fetch + secret.

### L-4. Three-way verdict → binary CI (the part most likely to be got wrong)

Adopted mapping, with the anti-false-green floor:

| Lane B verdict | CI behavior |
|---|---|
| `ok` | pass |
| `pipeline` (emitted but not carried / wrong table), any assertion failure, any daemon SQL error | **fail the job** |
| `not_exercised` (bot luck — e.g. no cap_break this run, ~50% of 240s runs) | pass, but `::warning::` per gap + a line in `$GITHUB_STEP_SUMMARY`; emitted-vs-recorded table in the summary |
| **floor:** nothing carried AND no scenario staged | **fail** — that is a broken lane, not a quiet one, and it is the state that otherwise sails through green forever |

**Definition of done includes two deliberately-induced results** (these are the gates that
cannot produce a false green, and they must be *watched*, not assumed): (a) drop the `assist`
seed from a dispatch run → the job **must go red** with a `pipeline` verdict; (b) a run with no
cap_break → **must stay green** and must *say so* in the summary. Plus: second run restores
ktpamx from cache (`cache-hit` true), artifacts include the game log, `replay_daemon.py`
reproduces a failure from its own artifact locally, and the schedule has fired unattended once.

### L-5. Assist self-credit finding — disposition

**Does not gate Units 2–4.** It is pre-existing behavior of the capture rule (not introduced by
these branches), observed once in 225 kills, and its blast radius today is one spurious
`PlayerPlayerActions` row — `reward_player=0`, so no HLStatsX skill effect, and KTPR does not
consume assists yet. **It hard-gates Phase 8** (KTPR consuming assists for rating): a killer
double-credited on their own kill is small, silent, and systematic on explosive kills if the
hypothesis holds. Work order, freeze-week-compatible (all in Lane B / tier-2 style harnesses):
replay a bazooka/grenade death through `dodx_test_dispatch_client_death` with a known killer
index and log what `ksc_on_death` receives; add a staged explosive-kill scenario to Lane B so
the frequency stops being one anecdote. Track on TODO under the KTPR band with the Phase 8 gate
stated on the card. Treat the splash-inflictor mechanism as **hypothesis, not root cause**,
until the replay shows the index.

---

## 4. Day-by-day schedule

Existing queue items (not this plan's to move) in *italics*. All activations 03:00 ET. All
staging via `stage-wave.py` with re-derived `--expect` pins — never a pin copied from a doc.

### Freeze week — production untouched by this plan

| Day | This plan | Gates |
|---|---|---|
| **Mon 08-10** | Open PRs 1–5 (§2); merge 1, 2 when approved. Track L: base-schema gates + commit prep; `ktp_schema.sql` fix branch. krod continues B½. | PR approvals only. |
| **Tue 08-11** | *(6-plugin wave activates; that card owns its verify.)* Merge PRs 3–5. Track L continues. | — |
| **Wed 08-12** | *(DODX 2.7.27 + MH 0.10.157 pair activates; its card owns the verify + runner restage.)* **After that verify passes:** KTPAMXX merges 6–9 in order, record M2/M3/M4; then infra 10 (rebase → merge → delete stray docs). | Pair activation verified 24/24 per artifact (D3). |
| **Thu 08-13 – Fri 08-14** | **FROZEN — no fleet or data-server contact.** Track L only: workflow rewrite behind B½; Lane B pre-stage run against M2; build Unit 2 artifact dry-run (md5 recorded as evidence a clean build exists, re-derived at stage time regardless). Prepare the §5 runbook text. | — |
| **Sat–Sun 08-15/16** | Default **quiet** (operator may release: ReAPI push + `--preflight-only` Sun PM, earliest stage Sun PM → Mon 03:00). Confirm with operator whether the post-deadline weekend has league events that argue for quiet — unknown from here. | Operator call (§8-Q2). |

### Deploy week — one artifact per nightly, each gated on the last

| Day | Action | Gates (verified how — see §5 for exact commands) |
|---|---|---|
| **Mon 08-17, 10:00–15:00 ET** | **Track S batch:** backup → apply migrate_003 + migrate_004 → verify rows → pre-check Suicides columns → deploy Unit 1 `hlstats.pl` → **restart `hlstatsx`** (sign-off) → post-restart verify. | S-0..S-5. No-live-match check passes; operator sign-off on the restart. |
| **Mon 08-17 PM** | Stage **KTPAmxxCurl 1.3.16** → Tue 03:00. Mon evening's matches double as Unit 1 live smoke (no plugin change needed — `kill` already logs). | `--preflight-only` clean (Wed's `.new` long consumed); pin re-derived. |
| **Tue 08-18 AM** | Verify AmxxCurl 24/24 + cores + CLAUDE.md row + runner module sync. Run Unit 1 smoke queries against Mon evening's data. | F-1; S-6. |
| **Tue 08-18 PM** | Stage **Unit 2** — `stats_logging.amxx` built at **M2** → Wed 03:00. | S-6 passed (suicides landing, frags normal, journal clean) **and** post-restart seed verify S-4 green **and** Lane B pass against M2. |
| **Wed 08-19 AM** | Verify wave 24/24; evening matches generate assist data. | F-1. |
| **Thu 08-20 AM** | **Unit 2 live smoke** on Wed evening's data — including the one check Lane B structurally cannot do: `hlstats_Events_Statsme` non-zero after a real match end. | U2-1..U2-6. |
| **Thu 08-20 PM** | Push (after PUSH-HOLD grep) + stage **KTPReAPI `.366`+`.367`** (one binary, one artifact) → Fri 03:00. | U2 smoke evaluated (ReAPI is independent, but a red U2 morning means human attention goes there — slip ReAPI rather than split focus). |
| **Fri 08-21 AM/PM** | Verify ReAPI 24/24 + runner stack re-sync. **Fri PM: stage Unit 3** at **M3** → Sat 03:00. | F-1 for ReAPI; U2 smoke green. |
| **Sat–Sun 08-22/23** | **Unit 3 live smoke over weekend match volume** — positives, and the two negatives only production can show: clean-cap (no phantom breaks after completed caps) and round-restart (no burst at capout), plus count-sanity vs. what players/casters saw. ⚠️ Judge by killer attribution or a ±10s no-death window, never by "was there a break around then" (krod's bot false-positive lesson). | U3-1..U3-5. |
| **Sun 08-23 PM or Mon 08-24 PM** | Stage **Unit 4** at tip → next 03:00. | U3 smoke green (two evenings minimum). |
| **Tue 08-25 AM →** | Unit 4 smoke (positions non-NULL, varied, in-bounds; cluster check when a night produces multiple breaks). Then flip CLAUDE.md rows, close out. Phase 8 (KTPR consumes assists) remains gated on L-5. | U4-1..U4-2. |

**Slip rule:** any red smoke consumes the next nightly for its own rollback/repair; everything
downstream shifts by at least one night. The order never changes — the seed-before-plugin and
stack-order invariants are why the sequence exists (krod's closing line, kept).

**Explicitly landing after the freeze:** everything in Track S and Track F — both seeds, the
suicide fix, the daemon restart, all three stats waves, AmxxCurl, ReAPI. Nothing
production-facing from this body of work moves before Sat 08-15 at the absolute earliest, and
the default plan's first production contact is **Mon 08-17 midday**.

**The one schedule alternative worth naming:** the Track S batch *could* run Wed 08-12 midday
(the freeze forbids Thu/Fri activations, not Wednesday data-server work), pulling every stats
wave ~3 days earlier. Rejected as default — it puts a daemon restart and a novel wave sequence
inside deadline week for zero correctness gain (the stats are not deadline-relevant), and Wed
AM is already spoken for by the pair verify. Offered as operator option §8-Q1.

---

## 5. Gates, with the verification that backs each one

Every gate is a command or query. Where a check can false-green, the control that prevents it
is stated. Run queries as the `hlstatsx` user on the data server unless noted.

**S-0 — Suicides table is deploy-ready (before anything else on 08-17):**
```sql
SELECT COUNT(*) FROM information_schema.columns
WHERE table_schema='hlstatsx' AND table_name='hlstats_Events_Suicides'
  AND column_name IN ('match_id','half');
-- expect 2. Positive control (proves the probe works):
SELECT COUNT(*) FROM information_schema.columns
WHERE table_schema='hlstatsx' AND table_name='hlstats_Events_Frags'
  AND column_name IN ('match_id','half');   -- expect 2
```
If 0/1: apply the guarded ALTERs from the fixed `ktp_schema.sql` (L-2) first. The 07-20 header
note names three tables, not four — this is exactly the unverified corner.

**S-1 — No live match window:** operator confirmation, plus
```sql
SELECT COUNT(*) FROM hlstats_Events_Frags WHERE eventTime > NOW() - INTERVAL 20 MINUTE;
```
≈0 in the 10:00–15:00 window. (Frag traffic is a proxy; the operator's knowledge of the match
calendar is the real gate. UDP log delivery has no retry — everything during the restart is
simply lost, which is why the window matters even with no match live.)

**S-2 — Backups before touching anything:**
```bash
cp /opt/hlstatsx/scripts/hlstats.pl /opt/hlstatsx/scripts/hlstats.pl.bak-pre-suicidefix-20260817
mysqldump hlstatsx hlstats_Actions > /root/hlstats_Actions-pre-seed-20260817.sql
```

**S-3 — Seeds applied and flags correct (the double-record trap):**
```sql
SELECT code, reward_player, for_PlayerActions, for_PlayerPlayerActions
FROM hlstats_Actions WHERE game='dod' AND code IN ('assist','cap_break');
-- expect EXACTLY two rows:
--   assist    0  '0'  '1'
--   cap_break 0  '1'  '0'
-- STOP if either flag pair is not opposite, or reward_player != 0
-- (non-zero reward re-rates the ladder; both-flags-set records every event twice).
```

**S-4 — Daemon restarted and the seeds are actually live** (the table is read into memory at
startup — a row inserted after start is invisible): re-run S-3 **after** the restart, plus
```bash
systemctl is-active hlstatsx
journalctl -u hlstatsx --since "-15 min" | grep -ci 'SQL_ERROR'   # expect 0
journalctl -u hlstatsx --since "-15 min" | wc -l                  # expect >0 — the positive
# control: an empty journal makes the grep above a false clean (wrong unit name, wrong window).
```
Also verify the deployed file is the merged one, not a stale copy:
`md5sum /opt/hlstatsx/scripts/hlstats.pl` vs `git show origin/main:scripts/hlstats.pl | md5sum`
in KTPHLStatsX.

**S-5 — hlstats.pl regression, same evening:** frags still flowing at normal volume after
19:00 (`COUNT(*)` on `hlstats_Events_Frags` last hour, nonzero and plausible), 0 SQL_ERROR.

**S-6 — Unit 1 smoke (Tue AM, from Mon evening's organic data):**
```sql
SELECT COUNT(*) FROM hlstats_Events_Suicides WHERE eventTime > NOW() - INTERVAL 18 HOUR;
-- expect >0 after a normal evening (players type kill / nade themselves routinely; if the
-- evening genuinely had zero suicides this is inconclusive, not red — check the raw log for
-- 'committed suicide' lines first: log lines present + 0 rows = red; 0 lines = wait a day).
```
That log-vs-rows comparison is the control that separates "fix broken" from "nothing happened".

**F-1 — Every fleet wave, morning after (identical shape each time):** `.new` consumed and md5
uniform 24/24 per artifact (via `ktp-verify-deploy.py` / the stage-wave epilogue command);
`find /tmp -maxdepth 1 -name 'core.*' -mtime -1` on all 5 hosts (never the game trees — the
game-tree probe matches core.so/core.ini/core.wav and looks clean whether or not anything
crashed); 0 stray `.new`; flip the root `CLAUDE.md` row **by fleet md5**; runner sync where the
artifact class requires it (module → stack re-sync; `PLUGINS_STRICT` plugin → byte-identical
copy).

**Pre-stage, every wave:** `stage-wave.py --preflight-only` clean; pin re-derived from the
artifact being staged (never from this document — five pins died this way in the last week);
`--expect` gate proven non-vacuous once per session (a deliberately wrong md5 must be refused);
after any local compile, check the auto-staging folder for unrelated artifacts before staging.

**U2 — Unit 2 smoke (Thu AM, from Wed evening):** the six queries from
`KTPR_DEPLOYMENT_PLAN.md` Unit 2, of which the load-bearing ones:
```sql
-- assists recorded, victim-attributed:
SELECT COUNT(*) FROM hlstats_Events_PlayerPlayerActions ppa
JOIN hlstats_Actions a ON a.id=ppa.actionId
WHERE a.code='assist' AND ppa.eventTime > NOW() - INTERVAL 18 HOUR;   -- >0
-- NOT double-recorded (what for_PlayerActions='0' buys):
SELECT COUNT(*) FROM hlstats_Events_PlayerActions pa
JOIN hlstats_Actions a ON a.id=pa.actionId WHERE a.code='assist';     -- exactly 0
-- THE MANUAL GAP — statsme still flows (Lane B is 0 here by construction, so only
-- production can green this):
SELECT COUNT(*) FROM hlstats_Events_Statsme WHERE eventTime > NOW() - INTERVAL 18 HOUR;  -- >0
-- headshot marker path unregressed:
SELECT COUNT(*) FROM hlstats_Events_Frags
WHERE headshot=1 AND eventTime > NOW() - INTERVAL 18 HOUR;            -- >0
```
Plus AMXX logs clean of `[KTP-STATS] dropped` (buffer sized for real match volume — Lane B's
16 bots are not a league match), and optionally one live kill-switch exercise
(`ktp_stats_capture 0` → no new rows → back to 1).

**U3 — Unit 3 smoke (weekend):** positive break rows in `PlayerActions` (0 in
`PlayerPlayerActions` — flags are the mirror of assist); clean-cap negative (completed caps →
no break rows in the surrounding window); round-restart negative (no burst at capout);
count-sanity vs. humans. Attribution discipline per krod's warning (named killer or ±10s
no-death window). Tuning knobs if needed: `KSC_BREAK_WINDOW`, `KSC_ZONE_POLL_SECS`,
`KSC_BREAK_QUEUE_MAX` — a knob change is a new build and a new wave, not a hot edit.

**U4 — Unit 4 smoke:** `pos_*`/`vpos_*` non-NULL on new assist/break rows; not all `0 0 0`
(the guard emits NULL on failed reads specifically so zeros mean something else); varied;
|coord| < 16384; per-flag clustering when a night yields multiple breaks. Dropped-line check
again — this unit grew the line length 288→384.

**CI gates:** the two deliberate results in L-4, watched, before the schedule is trusted.

---

## 6. The two displaced artifacts

- **KTPAmxxCurl 1.3.16** — approved, pushed, CI green; module, so it was never part of a
  plugin wave. Slot: **first post-freeze nightly** (default Mon 08-17 PM → Tue 03:00). Rationale:
  it is the readiest artifact in the queue, it occupies a night the stats track cannot use
  (Unit 2 is waiting on Unit 1's evening of smoke data), and putting the known-quantity module
  first means the fleet's first post-freeze change is the boring one. Runner stack re-sync +
  CLAUDE.md row flip morning after.
- **KTPReAPI `.366`+`.367`** — approved but **unpushed** (`2ad888d` local). One binary, one
  artifact, staged once. Slot: **Thu 08-20 PM → Fri 03:00**, between Unit 2's smoke and Unit 3's
  stage. Prerequisites: grep TODO.md for a PUSH HOLD immediately before pushing (none exists
  today; verify at push time), push, CI green, pin from a fresh build (ReAPI builds are
  deterministic, but re-derive anyway — it is the habit that keeps working). If Unit 2's smoke
  goes red Thu AM, ReAPI slips rather than sharing the week's attention.

Both orderings can be swapped by the operator without breaking any gate — neither module
interacts with the stats stack. What must **not** happen: either module sharing a nightly with
a stats wave.

---

## 7. Risks and rollback levers

| # | Risk | Lever |
|---|---|---|
| 1 | Seed/daemon ordering inverted or restart skipped → emitted lines silently discarded (the Philly LAN failure) | Prevented structurally: one batch, S-3 **re-run after restart** (S-4). Detection: U2 first-evening assist count 0 while raw log shows `triggered "assist"` lines → restart daemon (the seed row exists; only the in-memory copy is stale). Lost window is bounded to that evening. |
| 2 | Seed flags wrong → every event double-recorded + double-rewarded, silently | S-3 exact-match gate with STOP condition. If discovered late: fix the row, restart, delete the dup rows by `actionId` + time window; `reward_player=0` means no ladder re-rate to unwind. |
| 3 | Daemon restart lands mid-match → NULL match_id for the rest of that half | S-1 window + operator calendar. Self-heals at next match start; no repair path exists (UDP, no retry) — accept and note. |
| 4 | `hlstats.pl` fix regresses the shared dispatcher | S-5 same-evening frag-volume check. Rollback: restore `.bak-pre-suicidefix-20260817`, restart (no schema to unwind). |
| 5 | Unit 2/3/4 plugin misbehaves on real match volume (dropped lines, attribution, false-positive breaks) | **`ktp_stats_capture 0`** — instant, per-instance rcon, no redeploy (exercised: 10 kills → 0 assists while off). ⚠️ It is one switch for assists **and** breaks — a breaks-only disable does not exist; killing breaks costs assists too until a split ships. Full revert: previous `stats_logging.amxx` as `.new`, next nightly. Stack-order reverts only (positions → breaks → assists). |
| 6 | Cap-break false positives inflating objective ratings silently | Bounded **now**: `reward_player=0` and KTPR does not consume yet — which is exactly why Unit 3 ships before Phase 8, not after. U3 negatives + count-sanity are the detection; rows are deletable by action + window if a bad night lands. |
| 7 | KTPAMXX master moves under the Tue pair pins → wrong-tree rebuild | D3: no KTPAMXX merges until the pair's activation is verified Wed AM. |
| 8 | Wrong `stats_logging` build shipped (all units at once instead of one) | D4: build at recorded M2/M3/M4; Lane B pre-stage run against the same ref; md5 pin per wave. |
| 9 | Lane B CI goes silently green (`not_exercised` collapsed, or the blind-lane state) | L-4 mapping + floor + the two watched deliberate results. The floor is the specific guard against "green forever having measured nothing". |
| 10 | Fresh-provision schema loss (the MariaDB defect) fires at the next LAN/DR build | L-2 fix, verified both directions in Lane B. Until merged, the hazard stands documented in the file's own header. |
| 11 | Assist self-credit contaminates Phase 8 ratings | L-5: Phase 8 explicitly gated on root cause; measure-only until then. |
| 12 | Stray handover docs committed into an unrelated PR (working tree sits on `feat/hltv-viewer-logging`) | No `git add -A` in KTPInfrastructure until step 10 merges and the strays are deleted; `git status -uall` before any commit there. |
| 13 | Daemon-side rollback needed after Unit 2/3 are live (restore old `hlstats.pl`) | Seeds can stay (inert with the plugin disabled — krod, agreed); only the `.pl` reverts. Kill switch first, daemon revert second, plugin revert third — cheapest lever first. |

---

## 8. Decisions needing a human operator vs. agent-unattended work

**Operator (blocking decisions):**

1. **Q1 — Track S window:** Mon 08-17 midday (default) or the aggressive Wed 08-12 midday
   option. Also: standing sign-off rule means the restart itself needs explicit approval on the
   day, whichever is chosen.
2. **Q2 — Weekend 08-15/16 policy:** fully quiet, or release Sun PM for the AmxxCurl stage
   (pulls the whole deploy week one day earlier). Depends on post-deadline league calendar,
   which this investigation cannot see.
3. **Q3 — Slot order** AmxxCurl / ReAPI vs. stats units (§6 default stands unless overridden).
4. **Every `stage-wave.py` invocation** (per standing rules), and every daemon restart.
5. **Q4 — PR merges**, especially #9 (`feat/lane-b-fakeclient-players` — core `meta_api.cpp`;
   krod's own note says read it properly before merging).
6. **Q5 — `ktp_schema.sql` fix shape:** confirm option 1 now; separately, whether to authorize
   the option-3 restructure (changes the fresh-provision runbook).
7. **Q6 — SSH for `fetch_base_schema.sh --from-production`** (read-only dump; upgrades the
   committed base schema from reconstruction to production DDL).
8. **Q7 — Assist finding disposition:** accept "ships now, gates Phase 8" (L-5).
9. **Q8 — Add `stats_logging.amxx` to `PLUGINS_STRICT`** after Unit 2 activates, so future
   drift trips the wire like the other production plugins.
10. **Q9 — Coordination with krod:** who owns the CI rewrite vs. Phase B½ (his branch moved
    today; two people rewriting the same lane is the clobber pattern the doc-set git exists to
    catch).

**Agent-unattended (no production contact, reversible, or read-only):**

- Opening the PRs with correct stacked bases; re-running merge-tree dry-runs at merge time;
  recording M2/M3/M4.
- All of Track L: base-schema content gates + commit, `ktp_schema.sql` option-1 rewrite +
  both-direction Lane B verification, workflow rewrite, `workflow_dispatch` runs, the two
  deliberate red/green results, verdict-mapping implementation.
- Lane B pre-stage runs against M2/M3/M4.
- Building artifacts and deriving md5s (staging excluded).
- All morning-after **read-only** verification sweeps (md5 24/24, cores, journal, the S-/U-
  queries) — reporting results to the operator, who owns any go/no-go that follows.
- TODO.md + board updates (`ktpdocs.sh save` before/after; re-render; republish with `url=`),
  and the root `CLAUDE.md` row flips **after** fleet-md5 verification.
- The L-5 diagnostic replay work (test harnesses only).

---

## 9. Appendix — re-verification commands (all read-only)

```bash
# Branch state (per repo; KTPAMXX uses origin/master):
git fetch origin && git log --oneline -1 origin/main
git rev-list --count origin/main..<branch>
git merge-base --is-ancestor <lower> <higher> && echo stacked || echo diverged

# Conflict dry-run:
git merge-tree $(git merge-base A B) A B | grep -c '^<<<<<<<'

# The stats stack's true footprint (KTPAMXX):
git diff --name-only a052f7d9 origin/feat/stats-positions
#  -> CHANGELOG.md, plugins/dod/ktp_stats_capture.inc, plugins/dod/stats_logging.sma

# Stray-doc identity check (KTPInfrastructure):
git show origin/feat/tier2-bot-lane-stats-e2e:docs/handover/PR_SEQUENCING.md | diff - docs/PR_SEQUENCING.md

# Fleet preflight / post-activation: stage-wave.py --preflight-only ; ktp-verify-deploy.py ;
# cores:  find /tmp -maxdepth 1 -name 'core.*' -mtime -1   (per host, never the game trees)
```
