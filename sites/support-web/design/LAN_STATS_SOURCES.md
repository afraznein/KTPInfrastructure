# LAN Stats Page — Data Source Audit

**Date:** 2026-08-06. Evidence-based survey of what per-player stats exist in HLStatsX vs the
HUD observer, and what actually exists for the Philly LAN weekend (2026-08-01/08-02). All row
counts and samples were measured live on the data server (`<DATA_SERVER_IP>`, MySQL `hlstatsx`,
`/opt/hud-observer`, `/opt/ktp-lan-archive`) — not read off schema docs.

---

## Headline findings

1. **The data server's HLStatsX has NOTHING for 08-01/08-02** — confirmed independently across
   Frags, Statsme, PlayerActions, TeamBonuses, Chat, Connects, ktp_matches (daily counts jump
   from 07-31 straight to 08-03). The LAN box ran its own HLStatsX.
2. **The LAN box's HLStatsX database IS recoverable**: a full dump is archived at
   `/opt/ktp-lan-archive/philly-2026/lanbox-hlstatsx-20260806.sql.gz` (1.5 MB, dumped 08-06
   07:19). It contains **all 100 LAN matches** (`1785…-KTP[1-5]` IDs matching
   `KTPAntiCheat/docs/reviews/lan-match_index-2026-08-06.csv`), 59,207 frags (49,818
   match-tagged), 25,385 per-weapon Statsme rows (10,702 match-tagged), and aggregated
   `ktp_match_stats` for 93 matches.
3. **Assists are NOT derivable from HLStatsX** (fleet or LAN) — see the verdict below. The only
   assist sources are the HUD observer (fleet only, **no LAN matches**) and, for the fleet only,
   the per-hit `ktp_ac_weapon_hits` table (also **no LAN rows**). For the LAN weekend, assists
   can only come from re-parsing the 1,257 archived HLTV demos — there is no tabular source.
4. **Objective captures are MISSING for the LAN**: the LAN dump has **zero**
   `hlstats_Events_PlayerActions` / `hlstats_Events_TeamBonuses` inserts (the `hlstats_Actions`
   seed table was never populated on the LAN box, so the daemon dropped every capture event).
   The archived LAN logs are AMXX plugin logs only — no HLDS `dod/logs/` engine logs, and
   KTPScoreTracker was not running (0 log lines). LAN per-player caps exist only in the demos.

---

## 1 · What HLStatsX actually records (fleet DB, measured)

Every `hlstats_Events_*` INSERT carries `eventTime, serverId, map, match_id` (the daemon
injects `match_id` into **all** event tables — `hlstats.pl` `buildEventInsertData()`/
`recordEvent()`), and match rows are tagged only while a round is live (freeze-time and
inter-half events get NULL by design).

Row counts, live fleet DB (2026-08-06):

| Table | Rows | Populated? | Key columns |
|---|---|---|---|
| `hlstats_Events_Frags` | 1,233,057 | ✅ | `killerId, victimId, weapon, headshot, killerRole, victimRole, half, match_id, map` (pos_* NULL for DoD) |
| `hlstats_Events_Statsme` | 312,549 | ✅ | per-weapon per-flush: `playerId, weapon, shots, hits, headshots, damage, kills, deaths, half, match_id` |
| `hlstats_Events_Statsme2` | 312,074 | ✅ | per-weapon hitbox spread: `head, chest, stomach, leftarm, rightarm, leftleg, rightleg` (no `half` column) |
| `hlstats_Events_StatsmeLatency` | 56,318 | ✅ | avg `ping` per player, logged at disconnect |
| `hlstats_Events_StatsmeTime` | 56,334 | ✅ | connection `time` per player, logged at disconnect |
| `hlstats_Events_PlayerActions` | 534,159 | ✅ | `actionId` → `hlstats_Actions.code`: `dod_control_point` (128,584), `dod_capture_area` (97,539), `kill_streak_2..12` |
| `hlstats_Events_TeamBonuses` | 1,615,281 | ✅ | per-player team bonus for `dod_capture_area` / `dod_control_point` |
| `hlstats_Events_Teamkills` | 31,267 | ✅ | killer/victim/weapon/half/match_id |
| `hlstats_Events_ChangeRole` | 86,363 | ✅ | class selection per player |
| `hlstats_Events_ChangeTeam` / `Connects` / `Entries` / `Disconnects` / `Chat` | 421k / 44k / 393k / 33k / 254k | ✅ | roster/session reconstruction; `Connects.eventTime_Disconnect` gives session spans |
| `hlstats_Events_Suicides` | **0** | ❌ empty | suicides are simply never recorded (fleet-wide; `ktp_match_stats.suicides` SUM = 0 too) |
| `hlstats_Events_PlayerPlayerActions` | **0** | ❌ empty | the assist-shaped table exists but nothing ever writes to it for DoD |
| `hlstats_Events_Latency` / `Rcon` / `Admin` | 0 | ❌ empty | — |

KTP aggregate tables (fed by the daemon at `KTP_MATCH_END`):

| Table | Rows | Contents |
|---|---|---|
| `ktp_matches` | 3,311 | one row per match **per half**: `match_id, server_id, map_name, half, start_time, end_time` |
| `ktp_match_players` | 19,996 | `match_id, player_id, steam_id, player_name, team, joined_at` |
| `ktp_match_stats` | 46,909 | per player per half (0=match total, 1/2=halves, 3+=OT): `kills, deaths, headshots, team_kills, suicides, damage, score` — damage/score verified populated (33,068 / 33,142 rows > 0) |

Sample (fleet match `1.3-6399-DEN1`, player 25): half 0 → 89 K / 60 D / 11 HS / 15,184 dmg /
23 score; halves 1+2 sum to the half-0 row. This is exactly the per-map, per-half shape the
LAN page needs — **for fleet matches**.

Provenance: the `damage`/`shots`/`hits` numbers come from DODX via `stats_logging.sma`
`weaponstats`/`weaponstats2` log lines, flushed by `dodx_flush_all_stats()` at match start
(warmup flush), half end and match end, and at disconnect — so match-tagged Statsme rows are
clean per-half per-weapon aggregates. Headshot flags on frags come from the KTP
`headshot_kill` marker event (`stats_logging.sma` → daemon UPDATE of the matching frag row).

### Which stats HLStatsX gives you, per player per map

| Stat | From HLStatsX? | Where | Notes |
|---|---|---|---|
| Kills / deaths | ✅ | `ktp_match_stats.kills/deaths` or `COUNT(*)` over `Events_Frags` by `match_id` | per half via `half` |
| Headshot kills | ✅ | `ktp_match_stats.headshots` / `Events_Frags.headshot=1` | |
| Per-weapon kills | ✅ | `Events_Frags.weapon`, `Events_Statsme.kills` | |
| Damage dealt (total) | ✅ | `ktp_match_stats.damage`, or `SUM(Events_Statsme.damage)` per weapon | aggregate only — no victim attribution |
| Accuracy (shots/hits) | ✅ | `Events_Statsme.shots/hits` per weapon per half | |
| Hitbox distribution | ✅ | `Events_Statsme2` (head/chest/…) | not half-split (no `half` column) |
| Objective captures | ✅ (fleet) | `Events_PlayerActions` where action ∈ {`dod_control_point`, `dod_capture_area`}, with `match_id`, `map`, `pos_*` | **absent for LAN** (see §4) |
| Score (DoD points) | ✅ | `ktp_match_stats.score`, `Events_Statsme` score is folded in by daemon | |
| Kill streaks | ✅ | `Events_PlayerActions` `kill_streak_2..12` | |
| Class/role | ✅ | `Events_Frags.killerRole/victimRole`, `Events_ChangeRole` | |
| Teamkills | ✅ | `Events_Teamkills`, `ktp_match_stats.team_kills` | |
| Time played | ⚠️ partial | `StatsmeTime` (at disconnect), `Connects.eventTime_Disconnect`, `ktp_match_players.joined_at` | session-grained, not seconds-in-match; good enough for "played in match X" |
| Ping | ✅ | `StatsmeLatency` | avg at disconnect |
| Rounds | ❌ | — | DoD flag maps have no discrete rounds; the unit is the **half** (`half` column). Neither source records anything finer. |
| Suicides | ❌ | table empty fleet-wide | |
| **Assists** | ❌ | — | see verdict |
| **Damage taken** | ❌ | — | Statsme damage is dealt-only |

## 2 · Verdict on assists: **not derivable from HLStatsX**

An assist needs *(attacker, victim, damage amount, timestamp)* per damage event, so you can ask
"did X damage V within N seconds before someone else killed V". HLStatsX retains none of that:

- `hlstats_Events_Statsme.damage` is an **aggregate per weapon per flush** (a whole half, or a
  connect-to-disconnect span). No victim, no per-event timestamp. Measured sample:
  `(playerId 88, 'bar', shots 276, hits 35, dmg 2675, …, match '1.3-6399-DEN1', half 2)` — one
  row for the entire half.
- `hlstats_Events_Frags` has killer/victim/weapon/time — but only for the killing blow.
- `hlstats_Events_PlayerPlayerActions` (the only attacker→victim event table) has **0 rows**.
- The GoldSrc DoD engine does not log damage events at all; the daemon never sees them.

No heuristic over these tables can recover assists; the information is destroyed before it
reaches the database. Two real assist sources exist, both fleet-only:

1. **HUD observer** — the plugin computes assists itself (50+ enemy damage to a victim since
   their last spawn, killed by someone else) and both streams per-hit `damage` events
   (~1,100–1,500 per match, verified in `events.jsonl`: `attacker_id, victim_id, damage,
   weapon, hitplace, victim_health`) and emits `assists` in `player_score` /
   `player_stats_summary`.
2. **`ktp_ac_weapon_hits`** (MySQL, 113,573 rows since 07-07) — per-hit
   `match_id, attacker_steam_id, victim_steam_id, weapon_id, hit_at_ms, damage, hitplace,
   team_attack`. Covers **all 12–13 rostered players** of each covered fleet match (verified:
   distinct attackers = roster size for the last 10 matches), 261 distinct matches. An assist
   recompute is possible from this table + `Events_Frags` — for fleet matches it covers.

Neither has a single LAN row (`match_id LIKE '%-KTP%'` → 0 in both).

## 3 · What the HUD observer holds

`hud-observer.service` on the data server runs the Node backend from `/opt/hud-observer`
(ingest :9000, REST :3001, Socket.IO :4000). It **does persist**: `MatchRecorder` writes
`matches/{matchId}/events.jsonl` (append-only, every event) + `metadata.json`. Measured:

- **520 match directories, 2.0 GB**, earliest `1.3-5806-NY1` started 2026-04-23 — nothing is
  pruned; history goes back ~3.5 months.
- Per-match event census (sample `1.3-6398-CHI1`, 12,576 events): `kill` (732, with
  `assist_ids`, headshot, prone flags, kill_class gun/nade), `damage` (1,331 per-hit),
  `player_score` (1,677 rolling per-player snapshots), `player_stats_summary` (half/match end
  boards), `flag_captured`/`flag_cap_started`/`cap_break`, `player_spawn` (class + weapons),
  `team_score`, `half_start`/`half_end`, `user_say`, prone_change, flag_zone_players.
- `player_stats_summary` rows carry, per player: `kills, deaths, assists, damage, hs_kills,
  nade_kills, gun_kills, hits, hs_hits, obj_score, caps, cap_breaks, best_streak` — i.e. the
  HUD is the **only** source of assists, caps-as-a-player-stat with cap_breaks, nade-vs-gun
  kill split, and best streak.
- `round_start`/`round_end` never occur in real matches (checked last 5: all 0) — halves are
  the only boundary, same as HLStatsX.

**HUD-only stats** (exist nowhere in HLStatsX): assists, per-hit damage ledger, damage-taken
(derivable from `damage` events by victim), cap breaks, nade/gun kill split, best streak,
prone/deployed time, kill feed ordering with ticks.

**Limitation:** the HUD's stat accumulators are half-scoped and its summaries are per-half —
fine for the page's per-map/per-half needs — but only matches whose server had
KTPHudObserver enabled ever reach it. And **no LAN station posted to it: zero `-KTP` match
dirs**; the only 07-31→08-02 entry is `1785535037-NY1` (a fleet NY server, eventCount 1).

## 4 · The LAN weekend: what exists and what is definitively missing

Confirmed missing on the data server's live DB (independent daily counts, 07-25→08-06):
**no rows dated 08-01 or 08-02 in any `hlstats_Events_*` or `ktp_*` match table**; 07-30/07-31
rows are fleet warmup only (213/1,139 frags, 0/737 match-tagged — the tagged 07-31 rows are
fleet server IDs). `hlstats_Servers` lists exactly the 24 fleet instances (serverIds 1–25
contiguous, no LAN entries, none deleted/renamed). Only 7 `hlstats_Players` have
`last_event` in the LAN window, all fleet activity.

What **does** exist — `/opt/ktp-lan-archive/philly-2026/` (assembled 08-06):

| Artifact | Contents (measured) |
|---|---|
| `lanbox-hlstatsx-20260806.sql.gz` | Full LAN-box `hlstatsx` DB. `hlstats_Servers`: 5 rows, serverIds **26–30** = "KTP LAN 1–5" (10.70.10.30:27015-19). `ktp_matches`: 190 half-rows / 100 distinct LAN match_ids. `ktp_match_players`: 1,144 rows / 95 matches. `ktp_match_stats`: 3,273 rows / **93 matches** (halves 0/1/2; damage populated in 3,187 rows, score in 3,104). `Events_Frags`: 59,207 (49,818 match-tagged, with map + half — verified sample `'dod_railroad2_s9a','1785558420-KTP1',…,half=1`). `Events_Statsme`: 25,385 (10,702 match-tagged, per-weapon shots/hits/damage). `Statsme2` 25,384. Teamkills 1,250. Connects/Entries/ChangeRole/ChangeTeam/Chat present. 66 players with SteamIDs (`hlstats_PlayerUniqueIds`). |
| | ⚠️ **No `hlstats_Events_PlayerActions`, no `hlstats_Events_TeamBonuses`, and no `hlstats_Actions` inserts at all** → LAN objective captures never reached the DB (unseeded actions table = daemon dropped them). Also 0 Suicides (as on fleet). |
| `demos/` + `demos_parsed.json` + `demos_index.tsv` | 1,257 HLTV demos (`auto_lan[1-5]-…dem`) with parsed start/end/map per demo. |
| `match_windows.json`, `match_index.csv`, `match_demos.txt`, `port_to_lan.json` | Match skeleton (same content as the reviews CSV: id, type, map, port, half timestamps, close, score) + demo mapping. |
| `logs/lan-logs-20260806.tgz` | 428 MB, 618 files — **AMXX plugin logs + LinuxGSM logs only; no HLDS `dod/logs/`**. KTPMatchHandler event lines give team score timelines (`SCORE_FROM_DODX allies=.. axis=..` every 2 min) and match lifecycle, but no per-player kill/capture lines. KTPScoreTracker: 0 lines (not running at LAN). |
| `repair-1785715972-KTP1-discarded-h2-joinrows.tsv` | evidence of one already-repaired match. |

So for the Saturday/Sunday split (58 `ktp` matches: 31 on 08-01, 27 on 08-02):

- **Available after importing the LAN dump** (into a separate schema — serverIds 26–30 and
  playerIds collide with nothing, but Frags `id`s overlap fleet ranges; keep it in its own
  database): kills, deaths, headshots, per-weapon accuracy + damage, hitbox spread, teamkills,
  score, class, per-half splits, roster with SteamIDs, match/map/date. That covers 93 of 100
  matches with finished aggregates; the rest can be aggregated from the match-tagged event rows
  ("(no close)" matches lack `KTP_MATCH_END` aggregation but their frags are tagged).
- **Definitively missing for LAN, with no tabular source anywhere**: assists, per-hit damage,
  damage taken, objective captures / cap breaks per player, streaks. The only remaining carrier
  of that information is the demo archive (a demo parser would have to extract caps; assists
  would additionally need damage inference, which POV-less HLTV demos only partially support).
  If per-player caps are a hard requirement for the LAN page, that is demo-parsing work;
  otherwise the page should omit those columns for LAN matches.

## 5 · Raw quantities available per player per map for a KTPR rating

Quantities available **today for both fleet and LAN** (i.e. safe to build the rating on):

- kills, deaths, headshot kills (per half and per match) — `ktp_match_stats` / `Events_Frags`
- damage dealt — `ktp_match_stats.damage` / `Events_Statsme.damage`
- shots, hits (accuracy), per weapon — `Events_Statsme`
- hitbox distribution — `Events_Statsme2`
- teamkills — `Events_Teamkills` / `ktp_match_stats.team_kills`
- DoD score points — `ktp_match_stats.score`
- team, roster, SteamID, map, half, match type/date — `ktp_match_players` + `ktp_matches` +
  match index CSV
- team-level half scores — match index / `match_windows.json` (LAN) and KTPMatchHandler logs

Available **fleet-only** (a rating term using these would be uncomputable for the LAN
weekend): assists, per-hit damage / damage taken, objective caps & cap breaks per player,
kill streaks (fleet has `kill_streak_*` actions + HUD `best_streak`), nade/gun kill split,
prone metrics, time-in-match at second granularity.

There are no rounds in either source; "per half" is the finest game-state denominator.
Minutes-played can be approximated from half start/end times + connect/disconnect spans.

## 6 · Not determined / caveats

- **KTPR formula**: not found in any repo (as the tasking suspected); nothing here contradicts
  any candidate formula, but any term needing assists, ADR-vs-victims, caps or rounds cannot be
  computed for the LAN weekend from tabular data.
- **Why LAN captures were dropped**: inferred from the dump (no `hlstats_Actions` seed rows →
  `doEvent_PlayerAction` inserts nothing). Not verified against the LAN box itself (box not
  probed; it may be offline post-event).
- **LAN box residual state**: the dump is dated 08-06 and contains all 100 matches, so it
  post-dates the event and appears complete; whether anything further lives only on the LAN box
  (e.g. HLDS logs that were never archived) was not verifiable from the data server.
- **`ktp_ac_weapon_hits` coverage semantics**: it covers full rosters for the matches it has
  (verified last 10), but only 261 matches since 07-07 — which fleet matches are excluded and
  why was not established.
- Fleet `Events_Frags.map` is populated; the LAN dump's **warmup** frags have `map=''` (match-
  tagged LAN frags do carry the map). Joins for LAN should go through `match_id` →
  `ktp_matches.map_name`, not the event `map` column.
