# Session 3 Discord-Emission Audit (KTPMatchHandler 0.10.122)

**Status:** Audit deliverable for Session 3 Phase 2. Maps every Discord-post site
in KTPMatchHandler to the match-flow event that triggers it, identifies which
event each Session 3 test should target, and gives the unskip-each-test plan.

This doc is the prereq for unskipping `test_match_flow_discord.py:test_9*` —
once the audited paths below are confirmed (each in turn), removing the skip
mark on the corresponding test is a one-line change.

## Discord helpers (defined in `KTPMatchHandler/ktp_matchhandler_discord.inc`)

| Helper | Signature | Purpose | POST shape |
|---|---|---|---|
| `send_discord_simple_embed(title, desc, color)` | line 149 | Generic one-shot embed | New message with title + description + color |
| `send_discord_disconnect_embed(name, sid, team)` | line 813 | Player-disconnect notification | New message; auto-DC paired with `.nodc` cancel |
| `send_match_embed_create()` | line 674 | First match embed of a match cycle | New persistent message with roster + status; **stores message ID in `g_discordMatchMsgId`** for subsequent edits |
| `send_match_embed_update(status)` | line 726 | Edit the persistent match embed in-place | Patches `g_discordMatchMsgId`'s content with new status string |

Two send-vs-edit modes is critical for test design:
- **`create`** generates a NEW relay POST; FakeRelay sees it as `received[N]`.
- **`update`** PATCHes an existing message via `g_discordMatchMsgId`. The relay's `/reply` route may handle this differently — TBD whether the mock receives this as a POST too. **Need to verify against production relay's actual edit-message wire format** before committing test-9b assertions.

## All emission sites (16 total)

Categorized by match-flow event for direct mapping to test phases:

### Match start (test 9)

| Line | Helper | Path |
|---|---|---|
| 7414 | `send_match_embed_create()` | `task_deferred_discord_fwd()` for h1 — fires ~200ms after `advance_live(half=1)` |
| 7416 | `send_match_embed_update("2nd Half - Match Live")` | Same task for h2 — edit, not new POST |
| 7412 | `send_match_embed_update("OVERTIME ROUND N - Match Live")` | Same task for OT rounds — edit |

**Test 9 unskip plan:** drive `setup_match(COMPETITIVE) → advance_pending → advance_live(half=1)`. Sleep ≥200ms for `task_deferred_discord_fwd()`. Assert `discord_relay.assert_post_count(1)` and `received[0].embeds[0]` contains identifying content (e.g., a roster reference). The fixture writes `discord_channel_id_competitive=...` to the test discord.ini ONLY IF KTPMatchHandler honors a per-match-type channel (see "Per-match-type config" section below — needs verification).

### Half transition: 1st-half complete → 2nd-half live (tests 13/14)

| Line | Helper | Path |
|---|---|---|
| 1010 | `send_match_embed_update("1st Half Complete - Score: %d-%d")` | Half-end transition; fires when half-1 timer expires + scores save |
| 7416 | `send_match_embed_update("2nd Half - Match Live")` | h2 advance_live as above |

**Tests 13/14 unskip plan ✅ SHIPPED 2026-05-05:** KTPMatchHandler 0.10.125 added `amx_ktp_test_end_first_half <s1> <s2>` (the 6th driver rcon). MatchDriver gained `end_first_half(s1, s2)` helper. Tests 13 + 14 are now env-conditional (run end-to-end when `KTP_HLDS_SERVERFILES` is set with KTPMatchHandler 0.10.125+ test-mode build staged). Test 13 asserts the half-1-end embed update has "1st Half Complete - Score: X-Y" with the supplied scores; test 14 chains end_first_half → advance_live(half=2) and asserts the second /edit has "2nd Half - Match Live".

### Tech pause / unpause (tests 10/11)

| Line | Helper | Path |
|---|---|---|
| 1302 | `send_match_embed_update("…- Match Live")` | Unpause-resume path: status string rebuilt from `g_currentHalf`/`g_inOvertime`. Fires when `.tech` resolves (timer expires or `.unpause` confirmed) |

**Tests 10/11 design-skipped 2026-05-05:** the "audit gap" was actually the feature not existing — `cmd_tech_pause` and the unpause path do NOT call `send_match_embed_update` or any other Discord-side primitive. Pause status is a HUD-only feature in production design (ReHLDS `RH_SV_UpdatePausedHUD` real-time HUD updates per CLAUDE.md § Pause System). Tests 10/11 as originally specified would assert on an embed update that never fires. They could be repurposed as negative-path tests ("pause does NOT produce a /edit POST") if a future regression added an unwanted Discord notification — but that's a different test contract. Skip-marked with `PAUSE_NO_DISCORD_REASON` in `tests/integration/test_match_flow_logs.py`; reopen if the operator decides to wire pause-state Discord notifications.

### Match end (tests 15/16)

| Line | Helper | Path |
|---|---|---|
| 776 | `send_match_embed_update("MATCH COMPLETE - Final: %d-%d - %s")` | Normal match-end via `cmd_end_match` flow |
| 4130 | `send_match_embed_update(status)` | Disconnect-driven match-end (auto-DC threshold met) |
| 4284 | `send_match_embed_update("MATCH ENDED (2nd half) - 1st half: %s %d - %d %s")` | 2nd-half abandon |
| 4327 | `send_match_embed_update(abandonedStatus)` | Similar abandon path |
| 4444 | `send_match_embed_update(finalStatus)` | Final-status fallthrough |

**Tests 15/16 unskip plan:**
- **Test 15 ✅ SHIPPED 2026-05-05:** `test_15_tied_match_end_emits_tied_winner` drives `setup → live → end_match(42, 42)` and asserts the /edit embed has the "Match tied" winner phrasing (end_match's tied-score branch builds "Match tied!" winner string per cmd_test_end_match line 7817). Distinct from test 9b which uses 100-50 to validate the non-tied winner branch.
- **Test 16 PENDING** — abandon-path coverage. The 5 abandon-path lines (4130, 4284, 4327, 4444, plus auto-DC 776) share a `send_match_embed_update` helper but with different status strings ("MATCH ENDED (2nd half)", abandonedStatus, finalStatus). Currently no test rcon drives the abandon code paths; would need either an `amx_ktp_test_abandon_match` rcon or extending `cmd_test_end_match` with an `abandon=1` flag to take one of those branches. Structural assertion ("any /edit with `MATCH ENDED` in status") would be straightforward once a trigger exists.

### Cancel / abort paths (NOT in spec'd test 7-17 set; document only)

| Line | Helper | Trigger |
|---|---|---|
| 6324 | `send_discord_simple_embed("Match Cancelled", desc, RED)` | Operator cancel mid-flow |
| 6407 | `send_discord_simple_embed("Match Setup Cancelled", desc, ORANGE)` | Cancel during setup phase |
| 6693 | `send_discord_simple_embed("Server Force Reset", desc, ORANGE)` | `.forcereset` admin command |
| 6852 | `send_discord_simple_embed("2nd Half Restarted", desc, ORANGE)` | `.restarthalf` admin command |

Future Session 4 (admin recovery tests) will exercise the latter three.

### Player disconnect (NOT in spec'd test 7-17 set; document only)

| Line | Helper | Trigger |
|---|---|---|
| 2838 | `send_discord_disconnect_embed(name, sid, team)` | `client_disconnected` hook for connected, post-pre-start players |

## Tests 7 + 8: independent of Discord helpers

These don't go through `send_discord_*` paths — they use different observability surfaces:

- **Test 7 (DODX context propagation)** — assert `dodx_set_match_id(g_matchId)` was called at advance_live. Observable via DODX state-readback or via `KTPMatchHandler.sma:7427` log line `event=FWD_MATCH_START match_id=...`. Use `log_tail.wait_for_log_event(serverfiles, "FWD_MATCH_START", ...)` — same pattern as Session 2 test 6.
- **Test 8 (HLStatsX KTP_MATCH_START line)** — assert the HLStatsX-format log line lands in the AMXX log file. Same `log_tail` pattern. Independent of discord_relay.

## Test 17: AC match/end API (separate from Discord)

`KTPMatchHandler.sma:785` calls `send_ac_match_end(g_matchId)` — that's an HTTP POST to the AC API (port 8088 on data server in production), distinct from Discord. The AC API endpoint shape is documented in `KTPAntiCheat/docs/INTEGRATION_PLAN.md`.

**Test 17 unskip plan:** the existing FakeRelay only routes `/reply`. Either:
- **Option A:** extend FakeRelay to also route `/api/match/end` (or whatever AC uses) and treat AC traffic as a separate captured-list (`relay.ac_received`).
- **Option B:** spin up a SECOND FakeRelay-like mock specifically for the AC API. Cleaner separation; one mock per backend.

Recommend Option A for v1 — shared mock infrastructure is one less moving part. Bump scope from a `/reply`-only mock to a `/<route>`-pattern mock + per-route capture-lists.

## Per-match-type config (audit gap)

`g_disableDiscord` defaults to `false` at line 142 init AND is reset to `false` on every match-start command (lines 4205, 5540, 5551, 5566, 5615, 5625). So COMPETITIVE / SCRIM / 12MAN / DRAFT / KTP_OT / DRAFT_OT match types all have Discord enabled by default.

**Open question:** does KTPMatchHandler read `discord_channel_id_12man` / `discord_channel_id_draft` etc. as DIFFERENT keys per match type, or does it always use the base `discord_channel_id`? If per-type, the test fixture's discord.ini must include `discord_channel_id_competitive` (or whatever key COMPETITIVE uses) — currently it only writes the base key. Lines 6070, 6089 in KTPMatchHandler reference `discord_channel_id_12man` and `discord_channel_id_draft`, suggesting per-type keys exist.

**Action item:** read `load_discord_config()` (line 852 in `ktp_matchhandler_discord.inc`) to enumerate every config key the plugin recognizes, update `_discord_ini_setup` fixture to write all per-type keys.

## Concrete unskip plan (priority order)

1. **First:** verify `_discord_ini_setup` writes all needed config keys. Read `load_discord_config()`. Update fixture to write all keys (each pointing at the same `discord_relay.reply_url`).
2. **Test 9** (h1 match-start): unskip; expect 1 POST captured. Sleep 250ms after `advance_live(half=1)` to absorb the `task_deferred_discord_fwd` ~200ms defer.
3. **Test 9c** (bad-auth): unskip after 9 green; need `amx_ktp_test_reload_discord_config` rcon (NEW test-mode rcon to add to KTPMatchHandler) OR rely on the changelevel-induced plugin_init re-fire (slower but works without plugin changes).
4. **Test 9b** (match-end): unskip; expect ≥2 POSTs (start + end). The first is `create`, the second is `update` — verify FakeRelay sees both equivalently.
5. **Tests 13/14 (half transition)** + **15/16 (match end)**: similar pattern to 9 + 9b.
6. **Tests 10/11 (tech pause)**: locate pause-start `send_match_embed_update` callsite first; may need new test-mode rcons.
7. **Tests 7 + 8** (DODX / HLStatsX log lines): independent — can land in parallel via `log_tail` helper.
8. **Test 17 (AC API)**: extend FakeRelay or add second mock. Largest scope of the remaining set.

## Effort re-estimate

Original "Session 3 fill-out (~6h)" → revised based on this audit:

| Step | Estimate |
|---|---|
| Audit `load_discord_config` + update fixture for per-type keys | 0.5h |
| Unskip + verify test 9 | 0.5h |
| Add `amx_ktp_test_reload_discord_config` rcon (or use changelevel) | 0.5h |
| Unskip + verify tests 9b, 9c | 0.5h |
| Unskip + verify tests 13/14 (may need `end_first_half` rcon) | 1h |
| Unskip + verify tests 15/16 | 0.5h |
| Locate pause-start callsite + add tech-pause rcons + tests 10/11 | 1h |
| Tests 7 + 8 (DODX + HLStatsX log assertions) | 0.5h |
| Extend FakeRelay for AC API + test 17 | 1h |

**Total ~6h confirmed.** Phasing breaks naturally into Phase 2a (basic match-flow tests 9/9b/9c/13/14/15/16, ~3h), Phase 2b (tech pause + 7+8, ~1.5h), Phase 2c (AC API test 17, ~1h).

## Cross-references

- `KTPMatchHandler/KTPMatchHandler.sma:142` — `g_disableDiscord` init
- `KTPMatchHandler/KTPMatchHandler.sma:7395-7419` — `task_deferred_discord_fwd()`
- `KTPMatchHandler/ktp_matchhandler_discord.inc:674` — `send_match_embed_create`
- `KTPMatchHandler/ktp_matchhandler_discord.inc:726` — `send_match_embed_update`
- `KTPMatchHandler/ktp_matchhandler_discord.inc:852` — `load_discord_config` (NEEDS REVIEW for per-type keys)
- `tests/integration/test_match_flow_discord.py` — test stubs, currently skip-marked
- `tests/integration/conftest.py:_discord_ini_setup` — config-write fixture (may need extension)
