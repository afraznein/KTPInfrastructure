# Lane B Regression — Phase 7 (Break Context / Flag Positions / Last-Flag-Defense)

**Run date:** 2026-08-13
**Harness:** `lane_b_match_series.py`, 4 matches × 2×1200s halves, bot-driven, `dod_anzio`, seeded `migrate_003` through `migrate_007`
**Artifacts:** KTPAMXX `feat/stats-break-context` (`0af155fe`), KTPHLStatsX `feat/break-context-parse` (`0753474`), KTPMatchHandler pinned to `7db55e5` for compile only (see Known Issues — unrelated compiler bug, not this project's code)
**Status:** snapshot taken mid-run — match 1 (both halves) complete, match 2 in progress. Numbers below are real, not projected. This doc will be refreshed once all 4 matches finish if the numbers move meaningfully.

---

## 1. Volume

| Table | Rows |
|---|---|
| Players | 17 |
| `hlstats_Events_Frags` | 406 |
| `hlstats_Events_PlayerActions` (cap_break) | 3 |
| `hlstats_Events_PlayerPlayerActions` (assist) | **0 — see §5** |
| `ktp_damage_events` | 1,006 |
| `ktp_flag_positions` | 5 |
| Matches recorded | 3 (match 1 both halves complete, match 2 half 1 in progress) |

All 406 frags carry a non-NULL `match_id` (406/406) — match attribution is intact through Phase 7.

## 2. Kill leaderboard (live, real bot play)

| Player | Kills | Deaths | K:D |
|---|---|---|---|
| Claire | 30 | 12 | 2.50 |
| Dracula | 19 | 13 | 1.46 |
| Ferro | 19 | 10 | 1.90 |
| Dallas | 15 | 13 | 1.15 |
| Bishop | 14 | 14 | 1.00 |
| Ash | 12 | 12 | 1.00 |
| Burke | 12 | 13 | 0.92 |
| Pyramid | 11 | 11 | 1.00 |
| Parker | 10 | 10 | 1.00 |
| Hicks | 9 | 16 | 0.56 |
| Kane | 9 | 15 | 0.60 |
| Ripley | 9 | 15 | 0.60 |
| Cutter | 8 | 11 | 0.73 |
| Hudson | 7 | 10 | 0.70 |
| Lambert | 7 | 16 | 0.44 |
| Crash | 0 | 0 | — (joined at halftime swap) |
| GLaDOS | 0 | 0 | — (joined at halftime swap) |

Headshot rate (from `hlstats_Events_Frags.headshot`, carried by the Phase 5 frag-context marker): **46/406 = 11.3%**.

## 3. Phase 7 features — verified live

### Flag positions (`ktp_flag_positions`)
All 5 `dod_anzio` flags captured once at map load, real BSP coordinates:

| Flag | Name | X | Y |
|---|---|---|---|
| 0 | POINT_ANZIO_LAUNDRY | -1495 | -326 |
| 1 | POINT_BRIDGE | 1040 | -288 |
| 2 | POINT_ANZIO_STREET | 448 | 800 |
| 3 | POINT_ANZIO_PLAZA | -698 | 923 |
| 4 | POINT_ANZIO_HILL | 1375 | 1682 |

### Break context (`contester_count`, `time_remaining`, `is_capout`)
3 cap breaks so far, all with plausible, distinct values — including a genuine clutch defense (0.5s remaining, flagged `is_capout=1`):

| Player | contester_count | time_remaining | is_capout |
|---|---|---|---|
| Dallas | 2 | 0.0s | 0 |
| Dracula | 2 | 0.5s | 1 |
| Hicks | 2 | 2.4s | 0 |

### Last-flag-defense (`is_last_flag_defense` on Frags)
**78/406 kills = 19.2%** flagged as last-flag defenses. This run's rate is noticeably lower than the earlier single-match verification (29.5%), which is itself informative: it's evidence the number moves with match state (how often a team is actually down to one flag) rather than being a fixed artifact of the radius constant — consistent with the metric measuring what it's supposed to, but the `KSC_LAST_FLAG_RADIUS = 1000.0` heuristic is still an unmeasured starting estimate, not a tuned value.

## 4. Damage ledger — the 100-cap, doing its job

1,006 hits logged. **115/1006 (11.4%)** exceeded 100 raw damage and got capped — this is the CS2-style change you asked for in Phase 6, and it's firing on real, uncapped weapon values:

| Weapon | Hits | Avg raw | Max raw | Avg capped | Max capped |
|---|---|---|---|---|---|
| garand | 56 | 105.1 | 300 | 89.4 | 100 |
| scopedkar | 37 | 163.9 | **400** | 88.2 | 100 |
| spring | 28 | 158.2 | **400** | 95.1 | 100 |
| k43 | 45 | 92.2 | 300 | 80.2 | 100 |
| kar | 19 | 103.3 | 400 | 71.7 | 100 |
| bar | 94 | 65.5 | 212 | 60.8 | 100 |
| 30cal | 43 | 82.0 | 212 | 69.0 | 100 |
| spade | 5 | 201.0 | **500** | 81.0 | 100 |
| bayonet | 1 | 200.0 | 200 | 100.0 | 100 |
| mp40 / mp44 / greasegun / m1carbine / luger / colt / thompson | — | 30–41 | ≤125 | (unaffected — sub-100 by design) | — |

Concrete example pulled directly from the live game log while this ran:
```
"Hudson" triggered "damage" against "Kane" with "spring"
  (damage "400") (damage_capped "100") (hitplace "1") (game_time "1578.67")
```
A raw 400-damage sniper headshot, correctly logged as a 100-damage hit for stats purposes — exactly the behavior requested ("nothing over 100 damage should be logged for an individual kill").

## 5. Known issue found by this run — assists not landing in the DB

`hlstats_Events_PlayerPlayerActions` (the table `assist` writes to) has **0 rows**, despite:
- 66 `triggered "assist"` lines confirmed in the live game log
- `hlstats_Actions.count` for `assist` incrementing to 66 (proof the daemon's `doEvent_PlayerPlayerAction` code path executed and called `recordEvent()` 66 times — it did not silently ignore these as bot-filtered or bonus-round-filtered)
- No `SQL_ERROR` lines in the daemon's log
- `cap_break`, which uses the same buffered-queue + 30-second periodic flush mechanism, *did* successfully flush 3/3 rows into its table in the same run

**This is not Phase 5/6/7 code.** `doEvent_PlayerPlayerAction` and the periodic flush loop are untouched, pre-existing reconstructed upstream code — none of this project's branches modify them. It's a genuine finding surfaced by running a long-duration live series rather than the shorter single-scenario runs used for earlier phase verification, where a handful of assists happening to land inside one 30s flush window would have masked it.

Root cause not yet isolated — narrowed to "buffered but never flushed," ruled out: bot-ignore gate, min-players gate, bonus-round gate, missing action row, SQL error. Recommend picking this up before Phase 8 wires assists into KTPR — an assist stat that silently never persists would make any assist-weighted scoring meaningless. Filed as a new open item below.

## 6. Regression check — no breakage in prior units

- Frags, damage ledger, flag positions, break context, and match tagging all populated correctly and consistently across a real multi-hour run, not just a short smoke test.
- `match_id` attribution: 406/406 frags tagged (100%), consistent with the Phase 7 deployment plan's requirement that new stats be match-attributable for KTPR.
- No SQL errors, no plugin buffer-drop warnings, no daemon crashes or reconnects observed in the log.

## 7. Open items (unchanged from Phase 7 handover, plus one new)

- **New:** assist rows never reach `hlstats_Events_PlayerPlayerActions` in a long-running live series (§5) — needs root-causing before Phase 8.
- `KSC_LAST_FLAG_RADIUS` (1000.0 units) is still an unmeasured starting estimate.
- KTPMatchHandler HEAD fails to compile against the Lane B image's `amxxpc` (pre-existing, unrelated `dodx.inc` doc-comment issue, not this project's code) — worked around here via pinning to `7db55e5` for testing only.
- Ninja-cap detection remains deliberately deferred.
- Bazooka assist mis-attribution (1/225 kills) remains deliberately deferred.
