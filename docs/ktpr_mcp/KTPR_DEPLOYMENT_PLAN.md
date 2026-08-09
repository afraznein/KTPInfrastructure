# Deployment & smoke-test plan

Companion to `IMPLEMENTATION_PHASES.md`. This is the hand-off document: what to
merge together, in what order, and how to prove each unit works before moving
to the next.

Written to be run **one unit at a time**. Each unit is independently useful and
independently revertible. Do not stack two un-smoke-tested units on a live
fleet — if something is wrong, you want one suspect, not two.

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

### KTPAMXX — default `master` @ `a052f7d9`

| # | Branch | Base | Head | PR base branch |
|---|---|---|---|---|
| 1 | `feat/stats-assists` | `a052f7d9` | `30da9b71` | `master` |
| 2 | `feat/stats-cap-breaks` | `30da9b71` | `d0e88885` | `feat/stats-assists` |
| 3 | `feat/stats-positions` | `d0e88885` | `5f0e5379` | `feat/stats-cap-breaks` |

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

### ⚠️ Do this before merging

The verb string in the fix (`"committed suicide with"`) was taken from the
daemon's existing CS:GO branch, **not from an observed DoD log line** — no
sample existed in any repo. If DoD words it differently, the fix compiles,
deploys, and silently does nothing.

Confirm first: on any DoD server, have a player type `kill` in console, then
grep the raw HLDS log for that player's name around that timestamp and read the
actual line. If it is not `"Name<uid><STEAM_x><Team>" committed suicide with "weapon"`,
adjust the string in `hlstats.pl` before merging.

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

### Rollback

`ktp_stats_capture 0`, or previous `.amxx`. Reverting to `d0e88885` leaves
Units 2 and 3 intact and working — positions were purely additive.

---

# After all four units

Once breaks and assists are landing cleanly, `ktpr_mcp` can start reading them
(Phase 8 in the implementation plan) — `hlstats_Events_PlayerPlayerActions` for
assists, `hlstats_Events_PlayerActions` for breaks, both already carrying
`match_id` and `half` from the daemon's own tagging.

Still outstanding and **not** covered by these units: frag context
(prone/scope/ammo at kill), the per-hit damage ledger, and break context
(contester count / capout / last-flag defense / ninja caps). See
`IMPLEMENTATION_PHASES.md` for the plan and `CONTINUATION_NOTES.md` for the
detail needed to pick that work up cold.
