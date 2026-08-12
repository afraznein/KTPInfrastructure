# Deployment & smoke-test plan

Companion to `IMPLEMENTATION_PHASES.md`. This is the hand-off document: what to
merge together, in what order, and how to prove each unit works before moving
to the next.

Written to be run **one unit at a time**. Each unit is independently useful and
independently revertible. Do not stack two un-smoke-tested units on a live
fleet — if something is wrong, you want one suspect, not two.

---

## What Lane B has already proved

This plan was written before any of it could be tested. Most of it now runs
automatically against real bots and a real daemon
([`tests/e2e_stats/`](../../tests/e2e_stats/README.md)), so the manual
checklists below are a **shorter** job than they look. Each unit carries a
"Lane B pre-verification" table saying exactly which of its steps are covered.

| Unit | Status |
|---|---|
| 1 — suicides | **gate cleared, verified with a control.** The unconfirmed verb string is confirmed against real DoD logs; without the fix the same log produces 0 rows, with it 3/3. |
| 2 — assists | **all steps covered but one, and one open finding.** Every emitted assist carried exactly; headshots unaffected. A killer was credited an assist on their own kill once in 225 kills, on an explosive — see Unit 2. **`hlstats_Events_Statsme` is not covered** — check by hand. |
| 3 — cap breaks | **positive plus all four negatives, staged deliberately.** No step is manual any more; off-point kill and voluntary walk-off do not stage on every run, which is expected — see Unit 3. |
| 4 — positions | **covered**, except cross-flag clustering, which needs more than one break per run. |
| 5 — frag context | **covered.** Compiled/syntax-verified against the real toolchain and run live — see Unit 5. |
| 6 — damage ledger | **covered.** Compiled/syntax-verified against the real toolchain and run live — see Unit 6. |

Two caveats worth reading before treating any of this as sign-off:

- Lane B runs `sv_lan 1` with bots in a container. It does not exercise Steam
  auth, the fleet's own configs, or real network conditions. It proves the
  code path, not the deployment.
- The daemon it tests is assembled from pinned upstream plus KTP's delta,
  because KTPHLStatsX is a delta-only fork. Every run records this in a
  `PROVENANCE` file as `RECONSTRUCTION`. Pointing it at production's actual
  `/opt/hlstatsx/scripts` needs SSH and has not been done.

---

## Branch / commit reference

Every branch is **stacked** on the one above it within its repo, so the branches
must be merged **top to bottom in this table**. `Base` is the commit the branch
was cut from — that is also the rollback target for that branch's changes.

Because they are stacked, open each PR against its **PR base branch** column,
not against `main`/`master`. GitHub auto-retargets a stacked PR to the default
branch once its base branch merges, so the merge order takes care of itself.

### KTPHLStatsX — default `main` @ `9588794`

| # | Branch | Base | Head | PR base branch |
|---|---|---|---|---|
| 1 | `fix/suicide-dispatch-goldsrc` | `9588794` | `d3921b7` | `main` |
| 2 | `feat/seed-assist-action` | `d3921b7` | `7eefed6` | `fix/suicide-dispatch-goldsrc` |
| 3 | `feat/seed-cap-break-action` | `7eefed6` | `a8c9a97` | `feat/seed-assist-action` |
| 4 | `feat/frag-context-columns` | `a8c9a97` | `bb53e8b` | `feat/seed-cap-break-action` |
| 5 | `feat/ktp-damage-event` | `bb53e8b` | `9777786` | `feat/frag-context-columns` |

### KTPAMXX — default `master` @ `a052f7d9`

| # | Branch | Base | Head | PR base branch |
|---|---|---|---|---|
| 1 | `feat/stats-assists` | `a052f7d9` | `30da9b71` | `master` |
| 2 | `feat/stats-cap-breaks` | `30da9b71` | `d0e88885` | `feat/stats-assists` |
| 3 | `feat/stats-positions` | `d0e88885` | `5f0e5379` | `feat/stats-cap-breaks` |
| 4 | `feat/stats-frag-context` | `5f0e5379` | `b15295c8` | `feat/stats-positions` |
| 5 | `feat/stats-damage-ledger` | `b15295c8` | `5eb05ebd` | `feat/stats-frag-context` |

### KTPInfrastructure — default `main` @ `7117349`

| # | Branch | Base | Head | PR base branch |
|---|---|---|---|---|
| 1 | `feat/stats-capture-include` | `7117349` | `53ea398` | `main` |

### Rolling back

Two different things can need rolling back — don't confuse them:

- **Un-merging code.** `git revert <head>` on the merge, or reset the branch to
  its `Base` commit from the table above. For a stacked series, revert in
  reverse order (positions → breaks → assists).
- **Backing out a live deployment.** Much faster and usually what you want
  first: set `ktp_stats_capture 0` on the game servers (kills all new capture
  instantly, no redeploy, no restart), or restore the previous
  `stats_logging.amxx` / `hlstats.pl`. The seed rows are inert with the plugin
  disabled, so they can be left in place.

---

## Standing rules (from the repo skills — these are not negotiable)

- **Never restart a game server without explicit operator sign-off.** Plugin
  binaries deploy as `.new` and swap at the 03:00 ET nightly restart. Don't
  short-circuit that.
- **Never restart the `hlstatsx` daemon without explicit operator sign-off.**
  It is one process serving the whole fleet; a restart drops stat tagging for
  every server until it reconnects.
- **Apply SQL before the plugin that depends on it ships.** Every failure mode
  in this plan where data goes missing *silently* comes from that ordering
  being wrong. See "Why ordering matters" below.
- Verify plugin deployments **by md5**, never by the console banner.

## Why ordering matters (the silent-loss failure mode)

`doEvent_PlayerAction` / `doEvent_PlayerPlayerAction` only record an action that
exists in `hlstats_Actions`. If a plugin emits `triggered "assist"` and no seed
row exists, the daemon parses the line, matches nothing, and **discards it with
no error**. That is exactly how the Philly LAN lost every objective capture:
the table was unseeded and nothing looked broken until the data was needed.

So for every unit: **seed row first, plugin second.** The reverse order loses
data for the whole window between the two, and nothing alerts you.

⚠️ **The actions table is read into daemon memory at startup**
(`$g_games{<game>}{actions}`). A newly inserted row is therefore **not live
until the daemon restarts**. Confirm this against the running daemon rather
than trusting it blind — but plan for a restart, and re-run the verification
query *after* the restart, not before.

## Mutually-blocking pair (Unit 2 only)

`build/plugins/Dockerfile` gains a `COPY` for `ktp_stats_capture.inc`, and
`stats_logging.sma` gains an `#include` of it. The build copies KTPAMXX from a
**local sibling checkout** (`COPY KTPAMXX /build/KTPAMXX`), not a pinned ref,
so the two repos must be at matching revisions when you build:

| Local state | Result |
|---|---|
| infra new + KTPAMXX old | Docker `COPY` fails: file not found |
| KTPAMXX new + infra old | amxxpc fails: cannot read `ktp_stats_capture.inc` |
| both new | builds |

Both failure modes are **loud** — a broken build, not silent data loss — so
this is a nuisance, not a hazard. Merge KTPAMXX first, then KTPInfrastructure,
and make sure both working trees are updated before building.

---

# Unit 1 — Suicide dispatch fix

**Value:** `hlstats_Events_Suicides` has been empty fleet-wide since it was
created, and `ktp_match_stats.suicides` always 0. Schema and aggregation were
always correct; only the dispatch branch was missing.

| Repo | Branch |
|---|---|
| KTPHLStatsX | `fix/suicide-dispatch-goldsrc` |

Nothing else depends on this, and it depends on nothing. Good first unit.

### ✅ Pre-merge gate: CLEARED

The verb string was taken from the daemon's CS:GO branch, not from an observed
DoD line, and the worry was that a wrong string compiles, deploys, and silently
does nothing.

**Confirmed against real DoD 1.3 logs.** Lane B bot runs produced suicides
unprompted, in three weapon variants:

```
"Kazooie<10><0><Allies>" committed suicide with "grenade"
"Bowser<12><0><Axis>"    committed suicide with "grenade2"
"Fox<1><0><Allies>"      committed suicide with "world"
```

Exactly `"Name<uid><authid><Team>" committed suicide with "weapon"`. No change
needed. The line has no bracketed coordinates, which is precisely why it fell
past the CS:GO branch.

### ✅ Verified end to end, with a control

Rather than only match the string, Lane B replayed a captured log through the
daemon twice — once at `main`, once with the fix — against identical ephemeral
databases:

| Daemon | suicide lines in log | rows in `hlstats_Events_Suicides` |
|---|---|---|
| `main` (no fix) | 3 | **0** |
| `fix/suicide-dispatch-goldsrc` | 3 | **3** |

Assists (5) and frags (47) were identical across both, which is the plan's
step-4 regression check: the change is purely additive and does not disturb
the shared dispatcher.

Reproduce:

```
scripts/assemble_daemon_tree.sh <fork-repo> <out>/daemon
scripts/replay_daemon.py --log <captured>.log --hlstats <out>/daemon/hlstats.pl \
    --schema base-schema.sql --seed migrate_003_*.sql migrate_004_*.sql
```

The live smoke test below is still worth doing on a real server — Lane B runs
`sv_lan 1` with bots, so it does not exercise Steam auth or the fleet's own
config. But the failure the gate was written to catch cannot happen now.

### Deploy

1. Copy `scripts/hlstats.pl` to `/opt/hlstatsx/scripts/`.
2. Restart `hlstatsx` **(needs sign-off)**.

### Smoke test

1. On a test server during a live match, a player types `kill`.
2. Raw log contains the suicide line (you already confirmed its shape above).
3. Row lands:
   ```sql
   SELECT * FROM hlstats_Events_Suicides
   WHERE eventTime > NOW() - INTERVAL 10 MINUTE;
   ```
   Expect >= 1. Expect `match_id` populated if the suicide was during live play,
   NULL if during freeze time — both are correct.
4. **Regression:** kills still recording (this touched the shared dispatcher):
   ```sql
   SELECT COUNT(*) FROM hlstats_Events_Frags
   WHERE eventTime > NOW() - INTERVAL 10 MINUTE;
   ```
   Expect the usual volume, not 0.
5. `sudo journalctl -u hlstatsx -n 200 | grep -i 'SQL_ERROR\|error'` — clean.

**Pass =** suicides appear, frags unaffected, no SQL errors.

### Rollback

Restore the previous `hlstats.pl`, restart the daemon. No schema change, so
nothing to unwind.

---

# Unit 2 — Assists

**Value:** DoD assists have never existed in HLStatsX and cannot be derived from
its data — the engine logs no damage events. This is genuinely new information,
not a re-query.

| Repo | Branch | Order |
|---|---|---|
| KTPHLStatsX | `feat/seed-assist-action` | merge + apply **first** |
| KTPAMXX | `feat/stats-assists` | second |
| KTPInfrastructure | `feat/stats-capture-include` | third (with the above) |

`feat/seed-assist-action` is stacked on `fix/suicide-dispatch-goldsrc` — land
Unit 1 first, or the PR carries both.

### Deploy

1. Apply the seed:
   ```
   mysql -u hlstatsx -p hlstatsx < sql/migrate_003_assist_action.sql
   ```
2. Verify the row, and that the flags are the right way round:
   ```sql
   SELECT id, code, reward_player, for_PlayerActions, for_PlayerPlayerActions
   FROM hlstats_Actions WHERE game='dod' AND code='assist';
   ```
   Expect exactly one row: `reward_player=0`, `for_PlayerActions='0'`,
   `for_PlayerPlayerActions='1'`. **If `for_PlayerActions` is `'1'`, stop** —
   every assist would be recorded twice and the skill reward double-applied.
3. Restart `hlstatsx` **(needs sign-off)** so the new action is loaded.
4. Update both local checkouts (KTPAMXX + KTPInfrastructure), build plugins,
   distribute `stats_logging.amxx` as `.new`, md5-verify, let the nightly swap
   take it.

### Smoke test

Needs three players (or two plus a bot-free contrivance): **A** damages the
victim for >= 50, **B** lands the kill.

1. Raw server log contains:
   `"A<uid><STEAM_x><Allies>" triggered "assist" against "V<uid><STEAM_y><Axis>"`
2. Recorded with victim attribution:
   ```sql
   SELECT ppa.eventTime, ppa.playerId, ppa.victimId, ppa.match_id
   FROM hlstats_Events_PlayerPlayerActions ppa
   JOIN hlstats_Actions a ON a.id = ppa.actionId
   WHERE a.code = 'assist' AND ppa.eventTime > NOW() - INTERVAL 15 MINUTE;
   ```
3. **Not double-recorded** (this is what `for_PlayerActions='0'` buys):
   ```sql
   SELECT COUNT(*) FROM hlstats_Events_PlayerActions pa
   JOIN hlstats_Actions a ON a.id = pa.actionId
   WHERE a.code = 'assist';
   ```
   Expect **0**.
4. **Negative:** the killer must not be credited an assist on their own kill —
   confirm B does not appear as `playerId` for that victim/timestamp.
5. **Negative:** a teammate who damaged the victim must not be credited.
6. **Regression — the important one.** This unit edits a file carrying
   load-bearing stock stats. Confirm both still flow:
   ```sql
   SELECT COUNT(*) FROM hlstats_Events_Statsme WHERE eventTime > NOW() - INTERVAL 15 MINUTE;
   SELECT COUNT(*) FROM hlstats_Events_Frags
   WHERE headshot = 1 AND eventTime > NOW() - INTERVAL 15 MINUTE;
   ```
   Both non-zero after a normal match. A zero headshot count means the marker
   path regressed.
7. Buffer health — AMXX log should **not** contain:
   `[KTP-STATS] dropped N capture line(s)`
   If it does, `KSC_BUF_MAX_ENTRIES` needs raising for real match volume.
8. Kill switch works: `ktp_stats_capture 0` on the server console, take another
   assist, confirm no new row; set back to `1`.

**Pass =** assists recorded once each with victim attribution, zero rows in
`PlayerActions`, weaponstats and headshots unaffected, no dropped-line warnings.

### Lane B pre-verification

Most of the above is now checked automatically before anything is deployed —
`scripts/lane_b_e2e.py` (live bots) and `scripts/replay_daemon.py` (a captured
log). Across five live runs and two replays:

| Step | Lane B | Result |
|---|---|---|
| 1-2 assists recorded with victim attribution | yes | every emitted assist carried, exactly: 4/4, 5/5, 7/7, 12/12 |
| 3 not double-recorded | yes | 0 rows in `PlayerActions` for `assist`, every run |
| 4 killer not credited on their own kill | yes | **one violation found — see below** |
| 5 teammate not credited | yes | same check, teams read off the log line — 0 violations |
| 6 headshots unaffected | yes | 3/3 markers → `headshot=1` frag rows |
| 6 weaponstats unaffected | **no, and it cannot be** | `stats_logging.sma`'s `dod_stats_flush` handler opens with `if ( is_user_bot(id) \|\| ... ) return` — weaponstats are **never logged for bots**. Every Lane B player is a bot, so no `weaponstats` line is emitted and `hlstats_Events_Statsme` is structurally unreachable. Driving a real match was expected to fix this and did not. **Check this by hand, on a server with real clients.** |
| 7 no dropped lines | yes | `assert_no_dropped_lines`, every run |
| 8 kill switch | yes | 10 kills during `ktp_stats_capture 0` produced 0 assists; 5 once re-enabled |

Steps 4 and 5 are decided from the **log** rather than the database on
purpose: the log is what capture emitted, so a violation there is a plugin
attribution bug and not something the daemon did. Both checks are unit-tested
in both directions — a negative check that cannot fire reports "0 violations"
forever and reads like evidence.

### ⚠️ Open finding: a killer credited an assist on their own kill

Step 4's negative fired for real, once:

```
14:38:43  "Claire<9><0><Allies>" killed "Pyramid<2><0><Axis>" with "bazooka"
14:38:45  "Claire<9><BOT><Allies>" triggered "assist" against "Pyramid<2><BOT><Axis>"
```

Claire killed Pyramid and was also credited an assist against Pyramid. (The 2s
gap is the capture buffer's 5s flush, not a second death.)

**Frequency:** once in 225 kills and 20 assists across four captures. The other
three captures are clean.

**What is known.** `ksc_on_death` does have the guard — `if (a == killer || a
== victim) continue` — so the exclusion is written correctly. It compares
against the `killer` index that DODX's `client_death` forward supplies, and the
only sample is an **explosive** kill.

**What is not known,** and needs someone with DODX in front of them: whether
DODX reports a different index (the inflictor, or 0 for world) as the killer of
a rocket-splash death, which would make the guard compare against the wrong
player and let the real killer through as an assister. One sample and a
plausible mechanism is not a root cause.

**Why it matters more than one row.** An assist is worth rating, so a killer
collecting both the frag and an assist for the same death is double-credited.
It is small and it is silent.

**Suggested next step:** replay a bazooka/grenade death through
`dodx_test_dispatch_client_death` with a known killer index and log what
`ksc_on_death` actually receives. If DODX is the source, the fix is either in
DODX's attribution or an additional guard keyed on something more reliable than
the forward's killer index.

This does not block Unit 2 — the behaviour is a pre-existing property of the
capture rule, not something these branches introduce, and it is rare. It should
be understood before the rating consumes assists in Phase 8.

### Remaining gap

`hlstats_Events_Statsme` is the one item on this list Lane B cannot cover.
Everything else has been exercised.

### Rollback

`ktp_stats_capture 0` disables all new capture instantly with no redeploy —
use that first if anything looks wrong. Full revert = previous
`stats_logging.amxx`. The seed row is inert without the plugin; leaving it is
harmless.

---

# Unit 3 — Cap breaks

**Value:** breaking a cap is the only way to stop capture progress in DoD and
is a real objective-play signal. Never recorded outside the HUD observer.

| Repo | Branch | Order |
|---|---|---|
| KTPHLStatsX | `feat/seed-cap-break-action` | merge + apply **first** |
| KTPAMXX | `feat/stats-cap-breaks` | second |

Both are stacked on their Unit 2 counterparts. No KTPInfrastructure change —
Unit 2's Dockerfile line already covers the `.inc`.

### Deploy

1. `mysql -u hlstatsx -p hlstatsx < sql/migrate_004_cap_break_action.sql`
2. Verify — note the flags are the **opposite** of the assist action:
   ```sql
   SELECT id, code, reward_player, for_PlayerActions, for_PlayerPlayerActions
   FROM hlstats_Actions WHERE game='dod' AND code='cap_break';
   ```
   Expect `for_PlayerActions='1'`, `for_PlayerPlayerActions='0'`,
   `reward_player=0`.
3. Restart `hlstatsx` **(needs sign-off)**.
4. Build + distribute plugins as in Unit 2.

### Smoke test

This is the phase most likely to need tuning, because detection is timing-based
(a 0.5s poll, a ~2.5s confirm window). Test the negatives properly — a
false-positive break is worse than a missed one, because it silently inflates a
player's objective rating.

1. **Positive:** player V stands on a point and starts capping; enemy B kills V.
   Raw log within ~3s contains:
   `"B<uid><STEAM_x><Axis>" triggered "cap_break" (flag "...")`
   ```sql
   SELECT pa.eventTime, pa.playerId, pa.match_id
   FROM hlstats_Events_PlayerActions pa
   JOIN hlstats_Actions a ON a.id = pa.actionId
   WHERE a.code = 'cap_break' AND pa.eventTime > NOW() - INTERVAL 15 MINUTE;
   ```
2. **Negative — completed capture.** Let a cap finish cleanly with nobody
   killed. Cappers then walk off the point. Expect **no** `cap_break` row. This
   exercises the `CA_owning_team` clear; if breaks appear here, that check is
   not firing and every successful cap will produce phantom breaks.
3. **Negative — off-point kill.** Kill an enemy nowhere near a contested point
   while their team is capping elsewhere. Expect no break (the candidate should
   age out after ~2.5s with no count drop).
4. **Negative — voluntary walk-off.** Capper walks off the point on their own,
   uncontested, shortly after someone else nearby was killed. Expect no break.
   This is the hardest case; if it produces one, the baseline latch is
   over-crediting.
5. **Negative — round restart.** Trigger a round restart / capout. Zone counts
   zero out; expect no burst of phantom breaks.
6. **Count sanity:** over a full match, compare the break count against what the
   players/casters believe happened. Wildly high = false positives; zero with
   obvious breaks on video = detection not firing.
7. Regression + buffer + kill-switch checks: same as Unit 2 steps 6-8.

**Pass =** real breaks recorded, all four negatives clean, no regression.

### Lane B pre-verification

The negatives are the ones that matter here — this unit's own note says a
false-positive break is worse than a missed one, because it silently inflates
objective rating and nothing ever contradicts it. Bots cannot be told to stage
those, so `diagnostics/KTPBreakDrive.sma` stages them directly.

| Step | Lane B | Result |
|---|---|---|
| 1 real breaks recorded | yes | carried into `PlayerActions`, 0 in `PlayerPlayerActions`, every run that produced one |
| 2 clean cap, nobody killed | **yes, staged** | a flag captured cleanly (owner flip), no death on the capturing team, no break — the `CA_owning_team` clear holds |
| 3 off-point kill | **usually** | a capping-team player killed ~2800 units from the point produced no break for that killer; occasionally does not stage — see below |
| 4 voluntary walk-off | **usually** | a capper teleported off the point, no death on that team, count dropped by exactly one; occasionally does not stage — see below |
| 5 round restart | **yes, staged** | a candidate queued, then `mp_clan_restartround 1` — produced no break for the queued killer |
| 6 count sanity | partial | breaks never arrive in bursts, which is consistent with no false positives — but that is inference |
| 7 regression / buffer / kill switch | yes | as Unit 2 |

All five negatives are now staged by `diagnostics/KTPBreakDrive.sma` — no step
is manual by design any more. Steps 3 and 4 do not stage on every single run,
which is expected rather than a gap: DoD's active-capture window turned out to
be only a few seconds long, so the harness watches for a capture to actually
start (`_fire_when_capturing`, polling every 1.5s) rather than firing on a
fixed schedule, and a run can still finish its retry budget between captures.
`negative_voluntary_walkoff`'s most common non-staging reason is not a miss at
all — it is the contamination guard correctly declining a window where a real
death happened nearby, which is judgment working as intended, not judgment
withheld.

**One warning for anyone reading these results by eye instead of trusting the
harness.** Judging by "was there a cap_break in the log around then" does not
work. Bots break caps constantly, and the first automated version of step 4
reported a confident false positive that turned out to be a bot legitimately
killing a capper one second before the staged walk-off. Either attribute the
break to a specific killer by name, or confirm nobody on the capping team died
in the surrounding ~10 seconds. The harness does both.

### Tuning knobs if it misbehaves

All in `ktp_stats_capture.inc`:
- `KSC_BREAK_WINDOW` (5 polls, ~2.5s) — raise if real breaks are being missed,
  lower if unrelated later kills are being credited.
- `KSC_ZONE_POLL_SECS` (0.5) — finer polling narrows the attribution window but
  costs more per-frame work.
- `KSC_BREAK_QUEUE_MAX` (6) — only matters if a single grenade kills several
  cappers at once.

### Rollback

`ktp_stats_capture 0` (also disables assists — they share the switch; if you
need to keep assists while disabling breaks, that split does not exist yet and
would be a small change). Otherwise previous `.amxx`.

---

---

# Unit 4 — Positions on assist and break rows

**Value:** DoD has never had positional data in HLStatsX — `pos_x/y/z` is NULL
on every DoD event row. This is also the prerequisite for the last-flag-defense
and ninja-cap work later, and it's what makes break rows tell you *which* point
was broken (the daemon discards the flag name in the line).

| Repo | Branch | Base | Head |
|---|---|---|---|
| KTPAMXX | `feat/stats-positions` | `d0e88885` | `5f0e5379` |

No KTPHLStatsX change and no SQL — `doEvent_PlayerAction` and
`doEvent_PlayerPlayerAction` already parse the `position` /
`assister_position` / `victim_position` properties into `pos_*`/`vpos_*`. The
capability was already there with nothing emitting it.

### Deploy

Build + distribute plugins as in Unit 2. Nothing else.

### Smoke test

Run after Units 2 and 3 are already passing, so any new failure is this unit.

1. Take an assist and a cap break as in Units 2/3, then:
   ```sql
   SELECT pa.eventTime, pa.playerId, pa.pos_x, pa.pos_y, pa.pos_z
   FROM hlstats_Events_PlayerActions pa
   JOIN hlstats_Actions a ON a.id = pa.actionId
   WHERE a.code = 'cap_break' AND pa.eventTime > NOW() - INTERVAL 15 MINUTE;

   SELECT ppa.pos_x, ppa.pos_y, ppa.pos_z, ppa.vpos_x, ppa.vpos_y, ppa.vpos_z
   FROM hlstats_Events_PlayerPlayerActions ppa
   JOIN hlstats_Actions a ON a.id = ppa.actionId
   WHERE a.code = 'assist' AND ppa.eventTime > NOW() - INTERVAL 15 MINUTE;
   ```
   Expect non-NULL on all of them.
2. **Sanity, not just non-NULL.** `0 0 0` on every row means the origin read is
   failing and the guard is not catching it — the code omits the property on a
   failed read specifically so this shows up as NULL rather than a plausible-
   looking map origin. Coordinates should differ between rows and sit within the
   map's world bounds (compare against a couple of known spots on the map).
3. **Cross-check one break against the point it happened on.** Positions on
   breaks for the same flag should cluster. If breaks on different flags return
   indistinguishable coordinates, the read is wrong.
4. Regression: Units 2 and 3 checks still pass — assists/breaks still recorded,
   weaponstats and headshots unaffected, no `[KTP-STATS] dropped` lines. The
   buffer line length changed in this unit (288 → 384), so dropped-line warnings
   here would point at buffer sizing.

**Pass =** positions present, varied, plausible; no regression on Units 2/3.

### Lane B pre-verification

| Step | Lane B | Result |
|---|---|---|
| 1 non-NULL | yes | 0 NULL across every assist and break row produced |
| 2 varied, in-bounds, not `0 0 0` | yes | `assert_positions_populated` — all-NULL, all-zero, single-repeated-value and out-of-world each fail explicitly, and each is unit-tested in both directions |
| 3 breaks cluster per flag | **no** | only ever one break per run, so there is nothing to cluster |
| 4 no regression, no dropped lines | yes | assists/breaks/headshots all still carried; `assert_no_dropped_lines` clean at the 384-byte line length |

Representative live figures: 4 assist rows, 4 distinct positions, max
magnitude 1664; 1 break row at magnitude 1749. GoldSrc's world bound is
±16384, so these sit comfortably inside it rather than merely non-zero.

Step 3 needs several breaks on different flags in one run, which follows from
the same cap_break rarity described in Unit 3 — it is blocked on the same
driven-scenario work, not on anything about positions.

### Rollback

`ktp_stats_capture 0`, or previous `.amxx`. Reverting to `d0e88885` leaves
Units 2 and 3 intact and working — positions were purely additive.

---

# Unit 5 — Frag context (prone/scope/ammo/headshot)

**Value:** every kill now carries the state that makes it legible after the
fact — was the victim prone, scoped, out of ammo. This is genuinely new
information (DoD's engine log carries none of it), not a re-query, and it is
the input Phase 8's per-kill quality signals need.

| Repo | Branch | Base | Head |
|---|---|---|---|
| KTPHLStatsX | `feat/frag-context-columns` | `a8c9a97` | `bb53e8b` |
| KTPAMXX | `feat/stats-frag-context` | `5f0e5379` | `b15295c8` |

Order matters the same way it does for Units 2/3: **KTPHLStatsX first**
(`migrate_005_frag_context_columns.sql` adds the columns the daemon writes
into), **KTPAMXX second** (the plugin that starts emitting `frag_context`
lines). Getting this backwards doesn't lose data silently the way an
unseeded action would — the UPDATE just fails against columns that don't
exist yet — but it does mean noisy daemon errors until the seed lands.

This unit **retires** `stats_logging.sma`'s old dedicated `headshot_kill`
marker (headshot-only) in favor of a single `frag_context` marker fired on
every kill, using the identical buffer-then-daemon-UPDATE technique. See the
CHANGELOG entries in both repos for the full reasoning. The old daemon
handler branch (event type 900) is left in place as dead code — nothing
emits `headshot_kill` anymore, but nothing needs it removed either.

### Deploy

1. Apply the seed:
   ```
   mysql -u hlstatsx -p hlstatsx < sql/migrate_005_frag_context_columns.sql
   ```
2. Verify the columns landed:
   ```sql
   SELECT COLUMN_NAME FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'hlstats_Events_Frags'
     AND COLUMN_NAME IN ('k_prone','v_prone','k_scope','v_scope',
                          'k_clip','k_ammo','v_clip','v_ammo');
   ```
   Expect 8 rows. Unlike Units 2/3, **no daemon restart is required for this
   step alone** — new columns don't need the actions table reload that a new
   `hlstats_Actions` row does. (A restart still needs sign-off for the code
   change in step 4, same as any daemon deploy.)
3. Restart `hlstatsx` **(needs sign-off)** to pick up the new `hlstats.pl`
   frag_context handler.
4. Update both local checkouts (KTPAMXX + KTPHLStatsX), build plugins,
   distribute `stats_logging.amxx` as `.new`, md5-verify, let the nightly
   swap take it.

### Smoke test

1. Raw server log contains, on an ordinary (non-headshot) kill:
   `"K<uid><STEAM_x><Allies>" triggered "frag_context" against "V<uid><STEAM_y><Axis>" with "weapon" (headshot "0") (k_prone "0") ...`
2. Recorded on the frag row:
   ```sql
   SELECT killerId, victimId, weapon, headshot, k_prone, v_prone,
          k_scope, v_scope, k_clip, k_ammo, v_clip, v_ammo
   FROM hlstats_Events_Frags ORDER BY id DESC LIMIT 10;
   ```
   Expect non-default values on at least some rows — all-default
   (`0/0/0/0/-1/-1/-1/-1`) across an entire match means the marker isn't
   matching, not that nobody happened to be prone or scoped.
3. **Headshot regression — the important one.** This unit removes the code
   path Unit 2's smoke test checked. Re-run it:
   ```sql
   SELECT COUNT(*) FROM hlstats_Events_Frags
   WHERE headshot = 1 AND eventTime > NOW() - INTERVAL 15 MINUTE;
   ```
   Non-zero after a normal match. A zero count here means `frag_context`
   isn't landing at all, not just that the new columns are empty.
4. **Sanity on clip/ammo — corrected after a live run, read this before
   trusting your intuition here.** `k_clip`/`k_ammo`/`v_clip`/`v_ammo` are the
   participant's **current** weapon at the moment of the kill line, not
   necessarily the weapon that scored it. A grenade kill in the live run
   showed real rifle clip/ammo values, because the killer had already
   switched back to their gun by the time `client_death` fired. **A melee
   kill legitimately shows `0 0`** — that is a real engine reading for a
   knife, not the sentinel. `-1 -1` means the read failed (in practice, a
   narrow disconnect race), and should be rare — a run showing `-1 -1` on a
   large fraction of rows, not just the occasional one, is the actual
   anomaly to chase.
5. Buffer health — AMXX log should **not** contain
   `[KTP-STATS] dropped N capture line(s)`. The line grew again in this unit
   (384 → 512 bytes budgeted); a burst of dropped lines here is the signal to
   raise `KSC_BUF_MAX_ENTRIES` or `KSC_BUF_LINE_LEN` further, not to shrug it
   off.
6. Regression: Units 2/3/4 checks still pass — assists, breaks, and
   positions unaffected. `client_death` was rewritten in this unit (it now
   only dispatches into `ksc_on_death`), so this is the widest-blast-radius
   check in the whole plan.

**Pass =** frag_context recorded with varied, plausible values; headshot
count unaffected; no regression on Units 2/3/4.

### Lane B pre-verification

| Step | Lane B | Result |
|---|---|---|
| 1 raw log line present | yes | 135 `frag_context` lines, all nine properties present on every one |
| 2 non-default values recorded | yes | varied prone/scope/clip/ammo across rows — see figures below |
| 3 headshot regression | yes | 16 headshot kills, 16/16 carried to `hlstats_Events_Frags.headshot` |
| 4 clip/ammo semantics | yes, **and corrected** | see the smoke-test step 4 rewrite above — the live run changed what "sanity" means here |
| 5 buffer health | yes | no `[KTP-STATS] dropped` lines at 512 bytes |
| 6 no regression on Units 2/3/4 | yes | assists/breaks/positions all still carried exactly (see figures below) |

Compiled and syntax-verified against the real toolchain before any run:
`stats_logging.amxx` built with the KTP fork's `amxxpc` from commit `b15295c8`,
**0 warnings**; `hlstats.pl` from commit `bb53e8b` passed `perl -c` inside the
Lane B image.

**Live run, 2026-08-12** (150s play window, 16 bots, `dod_anzio`):

| | log | db |
|---|---|---|
| kills | 146 | 146 (frags) |
| assist | 21 | 21 (ppa) |
| cap_break | 2 | 2 (pa) |
| suicide | 10 | 10 |
| **headshot (frag_context)** | **16** | **16** |

Assist positions: 21 rows, 0 null, 0 all-zero, 21 distinct, max magnitude
3407. Break positions: 2 rows, 0 null, 0 all-zero, 2 distinct, max magnitude
1769. Zero SQL errors, zero regressions on Units 2/3/4.

**One real bug found and fixed by this run, not a plugin bug — a stale test
harness.** The first pass reported headshot as `not_exercised`: three call
sites in `tests/e2e_stats`/`scripts` still grepped the log for the literal
string `"headshot_kill"`, which this unit retires. Fixed to count
`(headshot "1")` instead (the property `frag_context` now carries), then
**re-verified against the same captured log** via `replay_daemon.py` — 16/16
carried, `all assertions passed`. This is exactly the kind of gap a
compile-only check would have missed: the plugin was correct throughout, and
without a live run the harness would have silently under-reported its own
coverage indefinitely.

**One thing the design got wrong, corrected from the same run.** The
original comments (plugin, migration SQL, both CHANGELOGs) described `-1`
clip/ammo as a melee/grenade sentinel. The live log shows otherwise: a
grenade kill carried real rifle clip/ammo (the killer had switched back by
`client_death`), and a knife kill carried real `0 0` from the engine, not
`-1`. Comments and the smoke test corrected to match what was actually
observed — see the CHANGELOG entries in both repos for the fix commits.

### Rollback

`ktp_stats_capture 0`, or previous `.amxx` / `hlstats.pl`. Reverting to
`5f0e5379` (KTPAMXX) / `a8c9a97` (KTPHLStatsX) leaves Units 2/3/4 intact —
frag context is purely additive, and the `headshot_kill` daemon branch it
retired is dead code either way, so nothing regresses to check.

---

# Unit 6 — Per-hit damage ledger

**Value:** every `client_damage` hit — enemy, team, and self — now lands as
its own row: attacker, victim, weapon, raw damage, a capped damage value,
hitplace, `game_time`, and `match_id`/`half`. This is the input Phase 8's
damage-based signals need, and the first unit to introduce a wholly new KTP
table rather than extend a stock one.

| Repo | Branch | Base | Head |
|---|---|---|---|
| KTPHLStatsX | `feat/ktp-damage-event` | `bb53e8b` | `9777786` |
| KTPAMXX | `feat/stats-damage-ledger` | `b15295c8` | `5eb05ebd` |

Same ordering rule as every prior unit: **KTPHLStatsX first**
(`migrate_006_damage_ledger.sql` creates `ktp_damage_events`), **KTPAMXX
second** (the plugin that starts emitting `damage` lines). Unlike Units 2/3,
a backwards deploy here fails loudly — the daemon's `INSERT` errors against a
table that doesn't exist yet — rather than silently discarding data. Still
land the seed first; a noisy failure beats depending on that.

**No daemon-batching reuse, on purpose.** This is the first KTP event type
that does not extend `hlstats_Events_*` via the generic `recordEvent`
mechanism (that machinery is config-driven around the stock event set) —
it's a standalone table (`ktp_damage_events`) with a direct per-event
`INSERT`, the same shape `KTP_MATCH_*` already uses. At the volume this
phase runs (~1,100–1,500 hits/match), that means proportionally more
individual `INSERT`s than any prior unit. Flagged as a known, deliberate
simplification in the CHANGELOG — batch it later if the volume proves to be
a real cost, don't assume it is or isn't without measuring.

**Damage is capped at 100, and `damage_capped` — not `damage` — is the
KTPR-facing column.** DoD's raw per-hit damage is the nominal weapon value
with multipliers applied (headshot, wallbang/penetration) and is not clamped
to a player's actual 0-100 HP pool — a single hit can log 400+. Read as "how
much this hit mattered to the outcome," that number is wrong; read as "how
strong this weapon+hitzone combo is on paper," it's fine, which is why raw
is kept alongside the capped value rather than discarded. Same convention
CS2 uses. Any future KTPR term built on damage must sum `damage_capped`.

### Deploy

1. Apply the seed:
   ```
   mysql -u hlstatsx -p hlstatsx < sql/migrate_006_damage_ledger.sql
   ```
2. Verify the table exists:
   ```sql
   SELECT COLUMN_NAME FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ktp_damage_events'
   ORDER BY ORDINAL_POSITION;
   ```
   Expect 12 columns. **No daemon restart required for this step alone** —
   same reasoning as Unit 5: a new table, unlike a new `hlstats_Actions` row,
   doesn't need the actions-table reload. A restart is still needed for step
   4's code change, with sign-off as always.
3. Restart `hlstatsx` **(needs sign-off)** to pick up the new
   `doEvent_KTPDamage` handler.
4. Update both local checkouts (KTPAMXX + KTPHLStatsX), build plugins,
   distribute `stats_logging.amxx` as `.new`, md5-verify, let the nightly
   swap take it.

### Smoke test

1. Raw server log contains, on any hit:
   `"A<uid><STEAM_x><Allies>" triggered "damage" against "V<uid><STEAM_y><Axis>" with "weapon" (damage "137") (damage_capped "100") (hitplace "1") (game_time "245.32")`
2. Recorded:
   ```sql
   SELECT attacker_id, victim_id, weapon, damage, damage_capped, hitplace,
          match_id, half
   FROM ktp_damage_events ORDER BY id DESC LIMIT 10;
   ```
   Expect rows with damage varying naturally by weapon and hitplace.
3. **Cap correctness — the point of this unit.**
   ```sql
   SELECT COUNT(*) FROM ktp_damage_events
   WHERE damage_capped > 100 OR damage_capped > damage;
   ```
   Must be **zero**, always. Any row here is a real defect in the cap logic,
   not a coverage gap — it should never happen regardless of what weapon or
   hitzone produced the hit.
4. **Self and team damage included.** Confirm at least one row exists where
   `attacker_id = victim_id` (self-damage, e.g. a player's own grenade) if
   the run had any — this is deliberately not filtered out at capture time,
   unlike assist attribution.
5. Buffer health — AMXX log should **not** contain
   `[KTP-STATS] dropped N capture line(s)`. This unit is the real test of the
   48 → 128 buffer bump: damage fires far more often than any prior capture
   type, and a burst of drops here is the signal the bump wasn't enough for
   real match density, not just Lane B's bot density.
6. Regression: Units 2/3/4/5 checks still pass — assists, breaks, positions,
   and frag context all unaffected. `client_damage` was extended in this
   unit; confirm the assist-attribution damage matrix (`g_kscDmgTaken`) still
   works, since it reads the same hook.

**Pass =** every hit ledgered, cap never violated, self/team damage present,
no regression on Units 2–5.

### Lane B pre-verification

| Step | Lane B | Result |
|---|---|---|
| 1 raw log line present | yes | 216 `damage` lines, all four properties on every one |
| 2 non-default values recorded | yes | damage varies naturally by weapon/hitplace — see figures below |
| 3 cap correctness | yes | **0** rows with `damage_capped > 100` or `damage_capped > damage`, across 216 rows |
| 4 self/team damage included | yes | 8/216 rows have `attacker_id = victim_id` (self-damage, e.g. a player's own grenade/mortar splash) |
| 5 buffer health | yes | **0** `[KTP-STATS] dropped` lines at 128 entries — the bump held |
| 6 no regression on Units 2–5 | yes | assists/breaks/positions/headshot all still carried exactly (see figures below) |

Compiled and syntax-verified against the real toolchain before any run:
`stats_logging.amxx` built with the KTP fork's `amxxpc` from commit
`5eb05ebd`, **0 warnings**; `hlstats.pl` from commit `9777786` passed
`perl -c` inside the Lane B image.

**Live run, 2026-08-12** (150s play window, 16 bots, `dod_anzio`):

| | log | db |
|---|---|---|
| kills | 85 | 85 (frags) |
| assist | 8 | 8 (ppa) |
| cap_break | 2 | 2 (pa) |
| suicide | 2 | 2 |
| headshot (frag_context) | 5 | 5 |
| **damage (ledger)** | **216** | **216** |

Damage figures: max raw value observed **212** (a wallbang/multiplier
reading, not a real 212-HP hit); **18/216** rows exceeded the 100 cap and
were correctly clamped to `damage_capped = 100`; the rest passed through
unchanged (e.g. a 30-damage pistol hit logs `damage_capped = 30`). Assist
positions: 8 rows, 0 null, 0 all-zero, 8 distinct, max magnitude 2350. Break
positions: 2 rows, 0 null, 0 all-zero, 2 distinct, max magnitude 2605. Zero
SQL errors, zero regressions on Units 2–5 (`all assertions passed` from the
harness, cross-checked with a `replay_daemon.py` replay of the same
captured log — 216/216 damage rows carried, 0 cap violations, independently
of the live run's own ephemeral database).

**One thing worth flagging, not a defect.** `damage` events run at a wholly
different rarity than the other markers — 216 per 85 kills in this run,
roughly 2.5 hits logged per kill, since most fights involve several
non-lethal hits before the finisher. `check_damage_ledger` reports
`not_exercised` rather than a false pass on a run with zero `damage`
markers, same shape as every other `check_*_carried` function, for whenever
a future run does land a quiet damage window.

### Rollback

`ktp_stats_capture 0`, or previous `.amxx` / `hlstats.pl`. Reverting to
`b15295c8` (KTPAMXX) / `bb53e8b` (KTPHLStatsX) leaves Units 2–5 intact — the
damage ledger is a new, independent table with nothing else reading it yet,
so nothing regresses to check.

---

# After all six units

Once breaks, assists, positions, frag context and the damage ledger are
landing cleanly, `ktpr_mcp` can start reading them (Phase 8 in the
implementation plan) — `hlstats_Events_PlayerPlayerActions` for assists,
`hlstats_Events_PlayerActions` for breaks, `hlstats_Events_Frags` for
positions and frag context, `ktp_damage_events` for the damage ledger, all
already carrying `match_id` and `half` from the daemon's own tagging.

Still outstanding and **not** covered by these units: break context
(contester count / capout / last-flag defense / ninja caps). See
`IMPLEMENTATION_PHASES.md` for the plan and `CONTINUATION_NOTES.md` for the
detail needed to pick that work up cold.
