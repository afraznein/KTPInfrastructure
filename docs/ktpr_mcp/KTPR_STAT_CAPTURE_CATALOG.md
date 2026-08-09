# KTP Stat Capture Catalog — ideas for a richer KTPR

**Purpose:** an exhaustive, tiered catalog of stat lines that could be captured
from live KTP DoD 1.3 matches, for feeding a broader/better `ktpr_mcp` rating.
Cataloging only — nothing here has been implemented. Grounded directly in the
KTP source (`KTPHLStatsX`, `KTPMatchHandler`, `KTPAMXX`'s DODX module,
`KTPHudObserver`), not guesswork; entries note the exact native/forward or
table each idea would use. Modern-shooter (CS2-era) stat concepts are included
as a glossary, translated to DoD's mechanics, for stats that aren't obvious
from the DoD side alone.

## Architecture proposal: write canonically at the engine/daemon layer, make KTPHudObserver a reader

Direction under consideration: instead of `KTPHudObserver` being the
*origin* of these stats (compute in the plugin → HTTP POST → Node backend →
`events.jsonl`, with MySQL populated later by a separate, mostly one-off
ETL), push the canonical write into whatever the game server/engine layer
already reliably gets into MySQL *during* the match, and have
`KTPHudObserver`'s live overlay become a *reader* of that MySQL data instead.

**This isn't a new idea for KTP — it's the same move KTP already made once,
for match boundaries specifically.** `KTPMatchHandler` doesn't invent a new
transport to tell the world "the match started" — it logs a
`KTP_MATCH_START` line (`log_message`, standard HL "triggered" format) over
the same UDP `logaddress_add` path every kill/death/action already rides, and
`KTPHLStatsX` is a fork of `hlstats.pl` specifically extended (event types
600–604) to parse it. That's the precedent: extend the daemon, not the HTTP
side, when something needs to be true in MySQL during the match.

### Two mechanisms, not one — they fit different data shapes

**A. Extend `KTPHLStatsX` (log-line → daemon → MySQL) — for discrete,
per-event stats.** Same shape as `KTP_MATCH_START`: the plugin emits a
`"Player<id><steamid><team>" triggered "eventname" (key "val") ...` line (or
a bespoke `KTP_*` marker line for anything not player-attributed), and the
already-forked `hlstats.pl`/`HLstats_EventHandlers.plib` gets a new handler
that inserts it, threaded through `%g_ktpMatchContext` for match_id/half —
the same context-tracking that already closes correctly on every one of
KTPMatchHandler's teardown paths (Phase 2 finding: this is *more* robust than
`KTPHudObserver`'s own separate match-context tracking, which has 4 gaps).
**Good fit**: break context (contester count, time-to-cap), `is_capout`,
last-flag-defense tags, capture completion + captor count/position,
scope/ammo/prone-at-kill, weapon-switch, the flag-position one-time capture.
All of these are exactly what `hlstats.pl` already does for kills/actions —
one row per discrete event, a handful of scalar fields.

**B. Direct MySQL from the game server (AMXX's `mysqlx`/`dbi` module) — for
bulky/structured stats that don't fit a log line.** Checked: `mysqlx` exists
as real, vendored AMXX source in `KTPAMXX/modules/mysqlx` (async MySQL, via
`plugins/include/dbi.inc`), but it's commented out in the stock
`configs/dod/modules.ini` template, and **not referenced anywhere in
`KTPInfrastructure/build`** — i.e. not currently compiled or deployed. This
path is technically available but has **no existing KTP precedent**, unlike
(A) — it would need enabling in the build, real credential provisioning on
every server, and new plugin code with no prior art to follow. Reserve this
for what doesn't fit a log line at all: the roster-wide position broadcast
and shot-level telemetry from the sections above are structured/array-shaped
and higher-frequency than anything `hlstats.pl`'s per-line regex dispatch is
built for — trying to force them through (A) risks becoming its own
reliability problem (oversized/malformed log lines) rather than solving one.

### What "update KTPHudObserver to pull from MySQL instead" means concretely

The Node backend's role shifts from *origin of truth via HTTP ingest* to a
*read path sourced from MySQL* for the live overlay — `MatchRecorder`,
`events.jsonl`, and the whole ingest-auth/POST pipeline stop being how the
canonical numbers get written; they'd either go away or narrow to only the
data class that genuinely has nowhere else to live (mechanism B territory, if
that stays HTTP-based rather than direct-MySQL).

**One real tradeoff worth deciding explicitly, not discovering later**:
polling MySQL for a *live broadcast overlay* adds poll-interval latency that
today's push-based Socket.IO doesn't have. Two ways to handle it — pick
based on how much on-screen delay is tolerable: (a) poll frequently enough
that it doesn't matter, accepting the added DB read load, or (b) have
`hlstats.pl` (or `KTPMatchHandler` directly) *also* fire a best-effort live
push to the Node backend at write time — a dual-write (canonical MySQL
insert + optional low-stakes live forward) rather than making the overlay's
responsiveness depend on a poll loop at all.

### The honest reliability comparison

Worth being precise about *why* this is more reliable, since it's not simply
"UDP beats HTTP" — it doesn't; raw HL log lines over UDP have **no delivery
guarantee either**, no ACK, no retry, same class of silent loss as the
current fire-and-forget HTTP POSTs. The actual reliability gain is
architectural, not protocol-level:

1. **One pipe instead of two.** Today, getting a stat into MySQL depends on
   both the HTTP/Node path succeeding *and* a separate ETL step running
   later (in practice, a one-off script, per Phase 2's finding that no
   continuous fleet importer exists). Writing canonically at the daemon
   collapses that into the one pipe that's already proven — the entire
   league's existing kills/deaths/ratings already depend on it working, so
   it's operationally load-bearing already, not a new dependency.
2. **Removes the demonstrated worst failure mode.** The LAN's HUD-observer
   coverage gap (Phase 2: firewalled to fleet IPs, LAN boxes on a different
   subnet, silently never connected) is a failure class specific to "a
   separate service the game server has to reach over HTTP." A log line over
   the same UDP path already required for HLStatsX to function at all doesn't
   have an independent reachability failure mode to begin with.
3. **Inherits the more robust match-context system**, per the Phase 2
   finding above — this alone would have prevented the specific bug class
   already found in `KTPHudObserver`'s own match tracking.

None of that is a delivery guarantee — a dropped UDP packet is still a
dropped stat. The case for this move is "fewer independent things that have
to go right," not "guaranteed delivery."

## Incorporating KTPHudObserver's stats into KTPHLStatsX — concrete, stat-by-stat plan

Scoped down per direction: focus on mechanism A only (extend `KTPHLStatsX`)
for now — reading `KTPHudObserver`'s live overlay from MySQL is a later,
separate problem, and the earlier latency concern doesn't actually apply
(HLTV viewing is already delayed, so poll/push timing isn't the constraint
it would be for a true real-time feed).

Every stat `KTPHudObserver` currently computes that HLStatsX doesn't already
have, sorted by **how it gets into `KTPHLStatsX`**, not by what it is. Two
generic mechanisms carry almost everything, both already proven in
production by DoD's own actions (`dod_capture_area`, kill streaks) and by
the KTP fork itself (`KTP_MATCH_*`):

**Confirmed while checking this**: the generic `PlayerAction`/
`PlayerPlayerAction` handlers (`HLstats_EventHandlers.plib:1613`,
`:1442`) both already accept `(x, y, z)` positional args and write them
straight into `hlstats_Events_PlayerActions`/`PlayerPlayerActions`'
`pos_x/y/z` columns (`recordEvent` calls at `:1802-1810` and `:1529-1541`).
**Any new action routed through either mechanism gets position captured for
free** by just including `(position "X Y Z")` in the log line — no daemon
change needed for that part, for any of the items below.

### Tier A — zero daemon code changes, config + one new log line each

Both of these already have their detection logic fully written in
`KTPHudObserver.sma` today — the only change is emitting a second, HLStatsX-
shaped line alongside (or instead of) the existing `post_event` JSON call,
plus one `hlstats_Actions` seed row.

- **Assists.** `client_death`'s existing assist loop (`:1416-1432`) already
  computes exactly who qualifies. Add, per assist: `"Assister<id><steamid><team>"
  triggered "assist" against "Victim<id><steamid><team>"`, and seed
  `hlstats_Actions` with `game='dod', code='assist', ppaction=1`. Lands in
  `hlstats_Events_PlayerPlayerActions` — the table that's existed the whole
  time and had nothing writing to it (Phase 1 finding). This is the single
  highest-value item in the whole catalog to do this way: it turns HLStatsX's
  long-standing structural gap (no assist source at all) into a solved
  problem using logic that's already written and tested in production.
- **Cap breaks.** `task_poll_zones`'s break-credit loop (`:1868-1899`)
  already detects and confirms breaks. Add: `"Breaker<id><steamid><team>"
  triggered "cap_break" (flag "<name>")`, seed `hlstats_Actions` with
  `game='dod', code='cap_break'`. Lands in `hlstats_Events_PlayerActions` —
  same table `dod_capture_area`/`dod_control_point` already populate, so
  breaks become a first-class HLStatsX action, not a HUD-only stat.

### Tier B — small, precedented daemon extension (same pattern as the existing headshot marker)

`headshot_kill` is already proof this pattern works: `KTPAMXX`'s forked
`stats_logging.sma` logs a separate marker line on a headshot, and the
daemon applies it to the *next* frag via a pending-flag mechanism
(`nextkillheadshot`) rather than trying to modify DoD's own engine-generated
kill line (which the plugin doesn't control). Extending that same
pending-flag mechanism to carry more context is small, contained, and has a
direct precedent to copy:

- Prone state at kill (killer/victim), scope state at kill, clip ammo at
  death — `KTPHudObserver` already tracks or can cheaply read all three at
  `client_death` time. Emit one more marker line per kill (or fold into a
  single richer marker) consumed the same way `headshot_kill` is, extending
  `hlstats_Events_Frags` with the corresponding new columns.

### Tier C — new custom KTP event type (same shape as `KTP_MATCH_START`, real but small new daemon code)

For data that doesn't fit "an achievement-shaped action" or "context on a
kill" — needs its own event type number (605+), its own regex branch, its
own `doEvent_KTP*` handler and table, following the exact template
`KTP_MATCH_START`/`600` already set.

- **Per-hit damage ledger** (attacker, victim, damage, weapon, hitplace,
  tick) — the headline item here. HLStatsX has no per-hit, victim-attributed
  damage anywhere (`Events_Statsme` is aggregate-per-weapon-per-flush only)
  and no generic action shape fits it. Known, bounded volume: the earlier
  audit measured **~1,100–1,500 damage events per match** from the HUD's own
  data — worth having that concrete number going in rather than guessing at
  load.
- **Break-context enrichment** (contester count, time-to-cap-remaining) —
  *if* this needs to be queryable as structured fields rather than living
  only in the break action's free position data. The generic `PlayerAction`
  properties bag isn't parsed generically (checked: `doEvent_PlayerAction`
  only extracts specific named properties it already knows about, mostly
  position-related) — so arbitrary extra scalars need either a small,
  explicit extension to that handler (cheap, but couples cleanly onto Tier A)
  or its own event. Recommend trying the small extension first before a
  whole new event type, given the break itself is already Tier A.
- **`is_capout` / last-flag-defense flags** — same call: likely cheaper as a
  one-property extension to the existing capture/break actions than a wholly
  new event, but flagging as Tier C in case that turns out not to fit.

### Tier D — already covered, or free from existing data, no new capture at all

- **Nade vs. gun kill split** — derivable today by classifying
  `hlstats_Events_Frags.weapon` against a static nade/gun weapon list.
  Query-side only.
- **`best_streak`** — likely already the same metric HLStatsX's daemon
  computes natively and automatically (`endKillStreak`'s `kills_per_life`,
  the same mechanism behind `kill_streak_2..12` actions) — MAX per player per
  match over those actions is probably equivalent. Worth verifying rather
  than assuming, because `KTPHudObserver`'s own numbers are known to diverge
  from HLStatsX's elsewhere (HUD kill totals run ~11% higher because it
  counts teamkills/suicides as kills — documented in `ktpr_mysql.py`'s own
  comments) and KTP's own stated rule is "where both hold a stat, HLStatsX
  wins." If they diverge here too, prefer HLStatsX's version and retire the
  plugin's own streak tracking rather than capturing it twice.
- **Caps / obj_score** — already flowing today via `dod_score_event` into
  the same `hlstats_Events_PlayerActions` pipeline (`dod_capture_area`/
  `dod_control_point`, already at six figures of rows per the Phase 1 audit).
  Per-point (`cp_index`) attribution is the only real gap, and that's a
  one-property addition to an action that's already Tier-A-shaped, not new
  capture.

## The three things this catalog optimizes for

1. **Accuracy** — a stat is only meaningful if it's scoped to *live match
   time*. KTP already has the primitive for this: `KTP_ROUND_FREEZE`/
   `KTP_ROUND_LIVE` events and `dodx_get_match_id()` gate HLStatsX's own
   tagging today. **Every new stat-emitting hook below should check the same
   gate** (non-empty match id + round live) before logging — this is the
   single biggest lever for "accuracy," and it's a pattern that already
   exists, not new infrastructure.
2. **Reliability** — a stat pipeline is only as reliable as its weakest
   hand-off. Two concrete bugs already found in this codebase are worth
   fixing *before* adding stat volume on top of the same pipes (see
   `FINDINGS.md` for full detail):
   - `hlstats.pl`'s suicide-line dispatcher only matches CS:GO's bracketed
     coordinate log format — DoD suicides never reach `doEvent_Suicide`
     despite the table/column/aggregation all being wired and correct.
   - `KTPMatchHandler.sma`'s match-teardown consolidation
     (`ktp_match_teardown_notify`) closes the match for HLStatsX and the
     anti-cheat API on every exit path, but not for `KTPHudObserver`'s
     `ktp_match_end` forward — 4 of 10 teardown paths (`.cancel`,
     `.forcereset`, and two abandoned-match paths) leave HUD observer's match
     context stale.
   Any new capture mechanism added below should route through the *fixed*
   version of this pattern (one teardown call, all sinks notified), not
   replicate the "hand-repeat at every call site" mistake that caused both
   bugs above.
3. **Breadth** — the rest of this document. Organized in tiers by how much
   new engineering each idea costs, from zero to "not worth it."

## Tier legend

| Tier | Meaning |
|---|---|
| **0** | Already captured today — listed for context/baseline only |
| **1** | Already logged somewhere in the pipeline — needs a query fix, a dispatcher fix, or wiring; no new capture code |
| **2** | Capturable using DODX forwards/natives that **already exist** in KTPAMXX today — pure plugin-side (Pawn) work, no engine/module changes |
| **3** | Needs a new DODX native/forward (C++ module work) or a new HLStatsX daemon action type — moderate engine work |
| **4** | Needs demo parsing, or likely infeasible for DoD 1.3's engine — high effort / low certainty |

---

## Tier 0 — already captured (baseline)

Kills, deaths, assists, damage dealt, flags/caps, cap breaks, role (primary
class), team, headshot kills, per-weapon shots/hits/damage (accuracy),
hitbox/hitgroup distribution, kill streaks (consecutive, capped at 12),
nade-vs-gun kill split, prone flag on kill (killer/victim), DoD score points,
ping, connection time. See `FINDINGS.md` Phase 1/2 for exact source tables.

## Tier 1 — already logged, needs wiring or a bug fix

| Stat | Where it already lives | What's needed |
|---|---|---|
| Suicides | `hlstats_Events_Suicides` (schema + aggregation correct) | Fix the `hlstats.pl` dispatch regex (see above) |
| Damage **taken** (not just dealt) | `hud_damage`, keyed by `victim_id` | Query-side only — nobody reads this direction yet |
| Per-hit damage ledger (attacker, victim, weapon, hitplace, tick) | `hud_damage` | Query-side only |
| Kill-level assist attribution (which kill each assist maps to) | `hud_kill_assists` | Query-side only |
| Teamkills as an attacker-side stat ("how many teammates did you kill") | `hlstats_Events_Teamkills`, currently only folded into victim's deaths | Query-side only |
| Weapon loadout choices over time | `hud_spawns.weapon_primary/secondary` | Query-side only |

## Tier 2 — new stat lines from DODX capability that already exists

Every native/forward cited here is confirmed present in
`KTPAMXX/plugins/include/dodx.inc` today — this is not speculative. The
biggest unlock: `dodx_get_user_origin(id, Float:origin[3])` and
`dodx_get_user_angles(id, Float:angles[3])` can be called from **any** hook,
so full positional/aim data is one native call away at every event below,
even though nothing currently calls it at kill/death/fire time.

### Shot-level telemetry (new capability class — nothing today captures this)

- **`dod_client_weapon_fire(id, weapon, gametime)`** fires on every shot. Combined
  with `dodx_get_user_origin`/`angles` at that instant:
  - True accuracy independent of hit registration lag (shots fired vs. the
    existing hits-registered count)
  - Rate-of-fire per weapon, burst/spray discipline
  - **Reaction time** — gap between spawn (or first enemy-visible tick, if
    ever exposed) and first shot fired
  - Aim-tracking quality proxies (angle delta between consecutive fired shots)

### Positional kill/death data (currently not logged anywhere, fully available)

- Call `dodx_get_user_origin`/`angles` inside the existing `client_death` /
  `client_damage` hooks (KTPHudObserver already hooks these; it just doesn't
  read position today):
  - **Kill-location heatmaps** per player/role/map
  - **Engagement distance** distribution per weapon (close/mid/long) —
    distinguishes a sniper's real effective range from a lucky long shot
  - **Flank-kill detection** — angle between victim's facing and attacker's
    position at time of death (CS2 "flank kill" concept)
  - **Front-line vs. rear-area kill zones** per map (aggression profile)

### Grenade / utility stats

- **`dod_grenade_explosion(id, pos[3], wpnid)`** and **`dod_rocket_explosion`**
  already carry explosion position:
  - Grenade **damage**, not just grenade kills (nade_kills already exists —
    this extends it to partial-damage contribution)
  - Effective-throw rate (exploded within N units of an enemy vs. wasted)
  - Rocket/bazooka accuracy and denial value
  - CS2 analog: utility damage / flash-assist family (DoD has no flashbang;
    grenade area-denial is the closest cousin)

### Scope discipline (sniper-specific)

- **`dod_client_scope(id, value)`**:
  - % of kills landed while scoped vs. unscoped
  - Average scope-in duration before a kill or a death
  - **Scoped-death rate** — died while scoped = held an angle too long, a
    real positioning/discipline signal for the Sniper role specifically

### Weapon economy / loadout behavior

- **`dod_client_weaponpickup`**, **`dod_client_objectpickup`**,
  **`dod_client_weaponswitch`**:
  - Picked-up-support-weapon kills (inherited a dropped MG/BAR and produced
    with it)
  - Weapon-switch frequency under pressure (panic-switch rate)
  - Time-to-rearm after death

### Stamina / physical state

- **`dod_client_stamina(id, stamina)`**:
  - Sprint-usage rate as an aggression proxy
  - **Caught-out-of-stamina deaths** — low stamina at moment of death implies
    predictable, exposed positioning

### Ammo discipline

- **`dod_get_user_weapon(index, &clip, &ammo)`**, read at damage/death time:
  - **"Caught reloading" deaths** — clip==0 at the moment of death is a real
    positioning/awareness signal, not noise
  - Ammo-starved player detection

### Objective micro-stats

- **`dod_score_event(id, score_delta, total_score, cp_index)`** plus the
  existing `dodx_area_get_data`/`dodx_objective_get_data` reads (already used
  for territorial control display):
  - Per-point score contribution breakdown (which specific point a player's
    score came from, not just a match total)
  - **Contest participation** — present in a capture-area fight vs. just
    passing through
  - **Point-hold duration while outnumbered** — a DoD-flavored "clutch,"
    since DoD has no round-based 1vX like CS2

### Movement / map presence

- **`dodx_get_user_origin` polled at interval** (KTPHudObserver already has a
  polling-fallback pattern for prone state — same technique, new field):
  - Time spent per map zone (front/mid/rear) per player
  - Distance traveled per half
  - Aggression-vs-passivity positioning profile over the course of a match

### Pure event-correlation stats (no new hook at all — derived from data already captured or one tier-1 fix away)

- **Traded deaths** — a teammate's death avenged within N seconds (CS2 trade
  kill), computable purely from existing kill timestamps once assists have a
  reliable per-event timeline (`hud_kills`/`hud_damage` already carry `tick`)
- **Revenge kills** — killed the specific player who killed you last life
- **Multi-kill windows** — kills clustered within a short time window (CS2
  2k/3k/4k/5k), distinct from the existing "best_streak" (which is a
  deaths-free streak, not time-windowed)
- **Entry kills / entry deaths / opening-duel win rate** — first confirmed
  kill of each half, or of each capture-point contest window — DoD's
  translation of CS2's round-opening-duel stat, using the half/contest
  boundary instead of a round boundary
- **ADR (average damage per half)** — direct port of CS2's ADR; damage dealt
  is already captured, this is just expressing it as a per-half rate metric
  explicitly rather than a season aggregate
- **KAST-equivalent** — % of halves/lives where a player got a Kill, an
  Assist, Survived to half-end, or had their death Traded. Fully composable
  once assists (already captured) and traded-deaths (above) exist — no new
  raw capture, just a derived rating input

## Exact changes required for Tier 2 (verified against the actual source)

Read `KTPHudObserver.sma` in full against `dodx.inc`'s native/forward list and
the backend's ingest route to get this precise, rather than assuming a forward
existing means the data already flows to disk. Two things change the picture:

**Two "exact changes" turned out to already exist in the plugin, but get
discarded before they reach disk.** `dod_client_weaponswitch` is already
implemented (`KTPHudObserver.sma:1662`) and already calls `post_event` with a
`weapon_active` event — but the backend's `SOCKET_ONLY_EVENTS` set
(`backend/src/handler/ingest.ts:25`) explicitly excludes `weapon_active` (and
`player_state`) from `events.jsonl`, by design, to protect the synchronous
`appendFileSync` hot path from a live-UI-only, high-frequency stream. So for
two of the items below, the "exact change" is a **backend one-liner with a
real volume tradeoff**, not new AMXX code.

**No live MySQL importer was found.** The only script that turns
`events.jsonl`-shaped data into the `hud_*` MySQL tables `ktpr_mysql.py`
queries is `KTPInfrastructure/sites/wsdod-lan-2026/lan-stats/load_hud.py` —
which lives under the LAN-specific one-off recovery folder, not anywhere that
looks like a standing service. **Every item below needs "how does this reach
MySQL" answered as its own prerequisite** — right now the honest answer is
"no continuous pipe exists yet," independent of which stat you pick. Confirm
this with whoever knows the live fleet setup before scoping any of this as
"just add a column."

Each item lists: the plugin-side change, the JSON/buffer impact, the
DB/backend change, and — where relevant to the demo question above — whether
it might be obtainable from a demo instead.

### 1. Shot-level telemetry

- **Plugin**: new handler, `public dod_client_weapon_fire(id, weapon,
  Float:gametime)` — doesn't exist today (confirmed: not in the `public `
  function list). Inside: `get_steamid`, `xmod_get_wpnlogname`,
  `dodx_get_user_origin(id, origin)`, `dodx_get_user_angles(id, angles)`,
  build a `weapon_fire` event, `post_event`.
- **Volume risk — the most important caveat in this whole list**: this fires
  on *every bullet*, the highest-frequency event by far, on a transport
  that's fire-and-forget with no retry (Phase 2 finding). This is the item
  most likely to make the existing reliability gap worse, not just add a
  stat. Needs a rate decision before implementing — batch client-side and
  POST periodically, or accept per-shot POSTs only after confirming real EPS.
- **Backend**: new `hud_shots` table (id, match_id, half, tick, steam_id,
  weapon, origin_x/y/z, angle_pitch/yaw) — doesn't exist in `hud_schema.sql`.
- **Demo angle**: partially already there. `dod-tools`' `dod` crate already
  parses `CurWeapon`, documented as firing once per bullet — shot count/timing
  is plausibly demo-derivable with a small `dod-tools` extension, no live
  capture needed. Position/angle at time of fire is not in `CurWeapon` and
  would need someone to dig into the entity-delta stream — unconfirmed.

### 2. Positional kill/death data

- **Plugin**: extend the *existing* `client_death` (`:1377`) and
  `client_damage` (`:1349`) handlers — add `dodx_get_user_origin`/`angles`
  calls for killer and victim, add fields to the existing JSON `formatex`
  calls. Bump `json[1024]` in `client_death` and `json[512]` in
  `client_damage` to cover ~6 extra floats each.
- **Backend**: none — same event types, just more fields.
- **DB**: add `killer_x/y/z`, `victim_x/y/z` (and optionally angles) columns
  to `hud_kills` and `hud_damage`.
- **Demo angle**: plausible but unconfirmed — the `dem`/`dod` crates already
  decode generic `EngineMessage`s (which is where GoldSrc entity-position
  deltas live), but `dod-tools`' `analysis` crate doesn't currently extract
  position from them. Real but unverified extension work.

### 3. Grenade / utility stats

- **Plugin**: new handlers, `public dod_grenade_explosion(id, Float:pos[3],
  wpnid)` and `public dod_rocket_explosion(id, Float:pos[3], wpnid)` — neither
  exists today. Emit `user_id`, `weapon`, `pos`.
- **Important scope note**: grenade *damage* (not just kills) may already be
  Tier 1, not Tier 2 — `client_damage` doesn't filter by weapon type, so if
  `hud_damage` already carries grenade-weapon damage rows, that's a
  query-side win with zero new capture. The new forwards above are only
  needed for *explosion position* (effective-throw-rate, wasted throws) and
  for throws that dealt zero damage, which `client_damage` can't see at all.
- **DB**: new `hud_grenades` table (id, match_id, half, tick, steam_id,
  weapon, pos_x/y/z).

### 4. Scope discipline

- **Plugin**: new handler, `public dod_client_scope(id, value)` — doesn't
  exist. Recommend the same pattern the plugin already uses for prone
  (`g_player_prone[MAX_PLAYERS]`): keep a small `g_player_scoped[MAX_PLAYERS]`
  array updated here, then **read it inside the existing `client_death`
  handler** and add `killer_scoped`/`victim_scoped` booleans to the kill JSON
  — cheaper than a separate scope-event stream and avoids needing timestamp
  correlation downstream.
- **DB**: one or two boolean columns on `hud_kills`, no new table needed.

### 5. Weapon economy / loadout behavior

- **`weapon_active` (weapon-switch) already captured in-plugin, discarded at
  the backend** — see the note above. Exact fix: remove `'weapon_active'`
  from `SOCKET_ONLY_EVENTS` in `ingest.ts:25`, *or* — better, since that
  stream is tuned for a live icon and may fire on auto-equip too, not just
  discretionary switches — keep it socket-only and add a second, coarser
  event for the stat use case (e.g., only log a switch when it's
  player-initiated under fire, if that distinction is available).
- **Plugin, new**: `public dod_client_weaponpickup(id, weapon, value)` and
  `public dod_client_objectpickup(id, objid, Float:pos[3], value)` — neither
  exists today.
- **DB**: a `hud_weapon_events` table, or extend the existing `hud_spawns`
  pattern.

### 6. Stamina / physical state

- **Plugin**: new handler, `public dod_client_stamina(id, stamina)` — doesn't
  exist. **Do not `post_event` on every call** — this forward almost
  certainly fires near-continuously during sprint/regen, and would be a
  second high-volume stream on top of shot-fire (item 1). Correct pattern:
  just update an in-memory `g_player_stamina[MAX_PLAYERS]` here, and fold the
  current value into the **existing** `task_poll_player_state` 4Hz batched
  snapshot (`:1686`), which already reads per-player live state the same way.
  Also worth reading at `client_death` time for a `victim_stamina` field,
  same pattern as scope above.
- **DB**: extend whatever table/column `task_poll_player_state`'s output ends
  up landing in (see item 9 — it's currently socket-only).

### 7. Ammo / reload discipline

- **Plugin**: no new forward at all — `dod_get_user_weapon(index, &clip,
  &ammo)` is a **native**, not a forward. Just call it inside the existing
  `client_death` handler for both killer and victim, add `killer_clip`/
  `victim_clip` to the kill JSON. The cheapest change in this entire list.
- **DB**: one or two int columns on `hud_kills`.

### 8. Objective micro-stats

- **`dod_score_event` is already hooked** (`:2140`) and already credits
  `obj_score`/`caps` — but checked `emit_player_score` (`:1544`), the
  function it feeds: that's a **cumulative running-total snapshot**, it does
  not carry `cp_index`. Per-point contribution (which specific capture point
  a player's score came from) isn't captured anywhere today. Exact fix: add
  a distinct `post_event` call *inside* `dod_score_event` itself (not routed
  through `emit_player_score`) — a new `obj_capture_credit` event carrying
  `user_id`, `cp_index`, `score_delta`.
- **Point-hold-while-outnumbered**: the raw ingredient
  (`dodx_area_get_data`'s `CA_num_allies`/`CA_num_axis`) is already polled by
  the existing `task_poll_zones` (`:1779`), which already calls `post_event`
  (`:1907`) and is **not** in `SOCKET_ONLY_EVENTS` — meaning this may already
  be Tier 1 (query-side derivation from data already reaching `events.jsonl`)
  rather than needing any new capture. Verify before building anything new.
- **DB**: new `hud_obj_credits` table for the per-point breakdown; the
  hold-duration stat may need no new table if the zones data is confirmed
  already persisted.

### 9. Movement / map presence

- **Plugin**: extend the existing `task_poll_player_state` (`:1686`) — add
  `dodx_get_user_origin` and append x/y/z to each player's JSON entry
  (`pbuf[192]`, currently). Recompute the overflow guard
  (`strlen(ps_json) > BUFFER_SIZE - 384`) against the larger per-player entry
  size.
- **The real blocker isn't the plugin, it's the backend**: `player_state` is
  in `SOCKET_ONLY_EVENTS` *by design* — the original devs explicitly chose
  not to persist a 4Hz × up-to-12-players stream. Adding position to it
  doesn't change that it's discarded before disk. Two real options: (a)
  accept the disk/volume cost and un-exclude it, or (b) — recommended —
  add a **separate, lower-frequency** event (e.g. every 10–15s) purpose-built
  for this stat, decoupled from the 4Hz UI stream, so the persisted volume
  stays reasonable.
- **DB**: new `hud_positions` table, sized around whatever polling interval
  is chosen.

### 10. Pure event-correlation stats (traded deaths, revenge kills, multi-kills, entry duels, ADR, KAST)

- **Zero plugin or backend changes.** These are entirely `ktpr_mysql.py` /
  `ktpr_engine.py` work — new SQL against the *existing* `hud_kills` columns
  (`killer_id`, `victim_id`, `tick`, `match_id`, `half`) doing time-windowed
  self-joins, plus new dataclass fields and a new report function wired into
  `ktpr_mcp.py`. By far the cheapest bucket in this entire list — worth doing
  first regardless of what else gets prioritized.

## What else is exposed — the rest of DODX, and the engine layer beneath it

Everything above used a subset of `dodx.inc`. This is a sweep of what's left
there, plus what's available one layer down — `KTP-ReAPI` (`reapi_ktp`),
which turns out to be the real "from the engine directly" answer on this
stack, since KTPAMXX doesn't have fakemeta compiled (confirmed earlier —
"Fakemeta module not compiled for KTPAMXX... needs AMBuild toolchain," from
the HUD observer's own migration notes). ReAPI's `reapi_engine.inc` is the
substitute, and it goes considerably further than fakemeta ever did.

### The rest of DODX (`dodx.inc`), not yet covered above

- **Identity/loadout reads, usable anywhere, not just in dedicated hooks**:
  `dod_get_user_class`, `dod_get_user_team`, `dod_get_pronestate`,
  `dod_get_user_weapon`, `dod_get_user_score`, `dod_weapon_type`,
  `xmod_get_wpnname`/`xmod_get_wpnlogname`/`xmod_is_melee_wpn` — mostly
  already leaned on elsewhere in the catalog, but worth naming as a group:
  any new hook can cheaply stamp current class/team/weapon/pronestate onto
  its event without needing its own tracking state.
- **Map/round context**: `dod_get_map_info` (map-level metadata — could tag
  stats by game-mode variant if maps differ), `dodx_get_round_time()`
  (elapsed/remaining round time — useful for normalizing "how early in the
  half did this happen" across stats, e.g. was a ninja cap in the opening
  minute or a desperate late one).
- **One unclear native worth flagging, not investigating further**:
  `dodx_get_observed_deaths(id)` — name suggests something about
  spectator-observed deaths, no doc comment in `dodx.inc` clarifies it.
  Possibly irrelevant to stats, possibly not — needs someone to check the
  KTPAMXX C++ source (`NRank.cpp`) rather than guessing from the header.
- **Not data sources — administrative/control natives, don't confuse these
  for capture points**: `dodx_set_user_noclip`, `dodx_give_grenade`,
  `dodx_strip_grenade`, `dodx_send_ammox`, `dodx_set_user_class/team`,
  `dodx_debug_player_state`, `dodx_debug_dump_ammo` — these *write* game
  state or dump debug text, they don't expose anything new to capture.

### ReAPI (`reapi_ktp`) — the actual engine-access layer, and it's substantial

`KTP-ReAPI` is a fork of the (CS 1.6-focused) ReAPI project. Two files
matter differently: `reapi_engine.inc` is engine-level and mod-agnostic —
everything below should apply to DoD identically. `reapi_gamedll.inc` /
`reapi_gamedll_const.inc` looked CS-specific on inspection (`CSGameRules_Members`,
`RebuyHandle`/`set_rebuy` — a CS economy feature with no DoD equivalent) —
flagging as **probably not usable for DoD**, unconfirmed rather than
asserted, since I didn't trace whether KTP's fork strips or ignores it.

- **`get_entvar`/`set_entvar` — full `entvars_t` access, the actual
  fakemeta-`pev()` replacement.** Confirmed via `reapi_engine_const.inc`'s
  `EntVars` enum (partial read, first ~30 members): `var_origin` (redundant
  with `dodx_get_user_origin`), **`var_velocity`** (speed/direction of
  movement — sprinting vs. walking vs. stationary, distinct from and more
  precise than the stamina-based proxy discussed earlier), **`var_v_angle`**
  (true view/aim angle — separate field from body-facing `angles`, meaningful
  for "was this player actually looking toward X" in a way body position
  alone can't answer), `var_punchangle` (recoil kick — a proxy for "just
  fired" independent of the weapon-fire forward), `var_button` (live input —
  is the attack button currently held, ducking, jumping — real-time combat
  engagement state, not inferred), plus (further into the same struct, not
  individually read but present by the same mechanism) waterlevel, deadflag,
  and movement flags (on-ground, ducking).
- **`CheckVisibilityInOrigin(ent, origin, type)` — a real, ready-made
  line-of-sight/visibility check.** This directly upgrades the ninja/last-flag
  work in the section below: instead of inferring "defenders probably didn't
  see the capper" from distance, this can answer **"could this specific
  defender's position actually see the capper's position"** — genuine
  visibility, not a distance proxy. This is the single most valuable new
  capability found in this sweep for sharpening flag-play stats specifically.
- **`RegisterMessage`/`GetMessageData`/`SetMessageData` — raw usermessage
  interception**, independent of DODX's own forwards. Lets the plugin observe
  any message the engine sends to any client (death notices, damage
  indicators, score updates, screen effects) — the same class of data a demo
  parser reconstructs from the network stream, but live and server-side, and
  a fallback path for anything DODX doesn't wrap into its own forward.
- **`get_ucmd`/`set_ucmd` — raw player input commands** (movement axes, view
  angles, buttons, impulses) *before* they're processed into game state. The
  deepest input-level telemetry available on this stack (true reaction time
  to first input, mouse-flick magnitude on a kill) — flagging as a frontier
  capability, not something to build now; likely overkill for KTPR's actual
  needs relative to its complexity.
- **`GetBonePosition`/`GetAttachment`** — precise bone/muzzle-level positions,
  a precision upgrade over player-origin for weapon-fire-origin tracking
  (Tier 2 item 1) if that ever needs to be more exact than "roughly where the
  player was standing."
- **`get_netchan`/`get_netadr`** — lower-level connection data than the
  existing ping stat. Likely redundant; low priority.

### What's genuinely not available

Classic fakemeta idioms (`pev()`, `engfunc()`, `trace_line()` as most AMXX
tutorials document them) don't apply here — fakemeta isn't compiled into this
stack. `get_entvar`/`CheckVisibilityInOrigin` above are the actual
equivalents on KTPAMXX + ReAPI, not a stopgap — worth telling whoever
implements this so they don't go looking for fakemeta examples that won't
compile against `KTPAMXX`.

## Deep dive: breaks, capouts, ninja caps, and flag management

Flag play is where `KTPHudObserver.sma` is most mature — the live territorial
HUD already needs almost everything this section wants, computed in real
time, then mostly **discarded once its one HUD purpose is served**. The
pattern below repeats for all four asks: the hard part (detecting the
condition) is already done; the gap is that the result isn't attached to a
persisted event. This makes these some of the cheapest Tier 2 items in the
whole catalog, not the hardest.

### Breaks — already a first-class stat, richer context is cheap to add

Confirmed how breaks work today: a "break" is specifically *killing an enemy
capper*, which is the only mechanism that stops DoD capture progress (there's
no non-lethal "contest" — presence alone doesn't block a tick). The plugin
already implements this with real rigor: `client_death` queues a kill as a
break candidate (`g_break_q_killer`, `:1511-1538`), and `task_poll_zones`
confirms it by watching for a drop in `CA_num_allies`/`CA_num_axis` over a
confirm window (`:1868-1899`), crediting via `emit_cap_break` (`:1973`) —
replacing an earlier one-shot approach measured at <20% real-break recall
(comment at `:329`).

**The gap**: `emit_cap_break`'s JSON payload today is just `flag_id,
flag_name, reason("kill"), breaker_id, broke_team` (`:1979`) — no context on
*how contested or how close to completion* the cap was. The exact fix is
cheap because the missing values are already local variables a few lines
away in the exact same function that calls `emit_cap_break`:
- `now_count` / `g_break_baseline[f]` (`:1879-1893`) → contester count at
  break time, already computed right there.
- `CA_time_remaining` / `CA_timetocap` (`:1854-1855`, same `task_poll_zones`
  loop) → how close the cap was to finishing when broken — the "clutch break"
  signal (breaking at 95% vs. 5%).

Add these as extra fields to `emit_cap_break`'s JSON and to the
`hud_flag_events`/`hud_kills`-adjacent schema. No new hook, no new forward —
purely passing already-computed local values into an existing call.

### Capouts / last-flag defense and ninja caps — capture-layer/query-layer split

Confirmed direction: **the plugin captures raw, objective facts only — no
"is this a last-flag defense" or "is this a ninja" judgment gets computed
in-engine at all.** Both classifications happen entirely in `ktpr_engine.py`/
`ktpr_mysql.py` after the fact, against persisted data. This also simplifies
the earlier draft of this section, which still had the plugin deciding *when*
to snapshot (e.g., "only at cap start, only if solo") — that's a smaller
judgment call than computing the verdict itself, but it's still logic living
in the engine. Replaced with a plain, unconditional, low-rate capture that
owes nothing to what it'll later be used for.

**Data to capture (all of it already mechanically simple — no new
detection, only new/extended emissions):**

| Fact | Source | Status |
|---|---|---|
| Flag position (`CP_origin_x/y`) | `dodx_objective_get_data(g_cp_dodx_of_dll[f], CP_origin_x/y)` — confirmed exposed, confirmed unread anywhere today | New — one-time per flag, add to the existing map-load flag-init event, not per-kill |
| Flag ownership over time | `flag_captured` events (owner, flag_id, tick) | **Already emitted** (`deferred_emit_cap`) — just confirm it's reaching `events.jsonl` (not in `SOCKET_ONLY_EVENTS`, so it should be) |
| Zone occupancy over time (who's physically in a capture zone, per team, per flag) | `task_poll_zones`'s `flag_zone_players` event (`CA_num_allies`/`CA_num_axis` per flag, `:1802-1807`) | **Already emitted and already persisted** — checked `SOCKET_ONLY_EVENTS` in `ingest.ts`, it only excludes `player_state`/`weapon_active`; `flag_zone_players` isn't in that set. This may need zero plugin/backend changes — verify it's actually landing in `hud_events`/the typed tables today before building anything new here |
| Kill position (killer + victim) | `dodx_get_user_origin` inside `client_death` | New — Tier 2 item 2, already scoped |
| Roster-wide position over time | New: a plain, unconditional position broadcast for all connected players at a fixed, modest interval (independent of any capture activity — no "only when a ninja might be happening" logic) | New — the one item that needs an actual capture-rate decision, but as a flat tunable interval, not event-triggered logic |

**Computed later, query layer only (none of this touches the plugin):**

- *Last-flag defense*: replay `flag_captured` events in tick order to
  reconstruct each team's owned-flag count at any point in the match; for
  each kill, look up the defending team's flag count at that timestamp: if 1,
  compute distance from the kill position to that flag's captured position;
  threshold → tag.
- *Ninja*: for each `flag_captured` event, use the zone-occupancy history to
  confirm zero defenders were ever in that flag's zone during the capture
  window; separately use the roster-wide position broadcasts to check where
  the defending team actually was during that same window, relative to this
  flag vs. wherever `flag_zone_players`/`flag_captured` shows contested
  activity happening elsewhere at the same time. All distance thresholds and
  "how clustered counts as clustered" heuristics live here, tunable against
  real match data without a plugin redeploy.

The position-broadcast interval is the only real dial left to turn, and it's
a volume/fidelity tradeoff to make explicitly rather than bury in an
event-triggered heuristic: coarser (e.g. every 10–15s) is cheap and still
answers "roughly where was everyone," finer costs more but sharpens the
distance/clustering computation. Worth deciding once real EPS/volume data
exists (see the open EPS question flagged in Phase 2 findings) rather than
guessing now.

### Other flag-management stats worth cataloging, roughly by cost

- **Recapture speed / tempo** (how fast a flag flips back) — zero new
  capture: pure derivation from existing `flag_captured` event timestamps
  per `flag_id`, same shape as the "traded deaths" idea in Tier 2 item 10.
- **Cap-attempt-vs-completion ratio per flag** — `emit_cap_started` and
  `emit_cap_stopped` are *already emitted* events (`:1826`, `:1832`,
  `:1838-1839`); correlating starts against completions per team per flag is
  query-side work once those are persisted, not new capture. Note
  `emit_cap_stopped` doesn't currently disambiguate *why* a cap stopped
  (capper died = a break, already tracked elsewhere; capper retreated
  voluntarily = a distinct "denial via retreat" behavior, currently
  unlabeled) — worth a small addition if that distinction matters.
- **Individual defensive presence/hold time (not just kills)** — genuinely
  harder. `CA_num_allies`/`CA_num_axis` are zone-wide *counts*, not
  player-ID lists, so crediting *which specific defenders* held a point
  without getting a kill needs per-player zone presence — i.e., the
  Tier 2 "movement/map presence" work (`dodx_get_user_origin` polled and
  checked against each capture-area's spatial bounds), correlated with
  `g_flag_contested` windows. This is the one flag-management idea that
  isn't already half-built — it depends on work not yet done elsewhere in
  the catalog, not on anything DoD-specific being missing.

## Tier 3 — needs new engine-level (C++ DODX module) work

- **Suppression / pin-down detection** — "took incoming fire but didn't
  return fire" or "stayed prone under fire for N seconds." Borderline: might
  be approximable by polling stamina + prone state + recent-damage-taken
  together (Tier 2), but a clean signal probably wants a dedicated
  `dod_client_suppressed`-style forward.
- **Line-of-fire / opportunity-adjusted accuracy** — "shots that could have
  hit" via a trace, not just shot position logging — needs a hitscan replay
  or trace hook, not exposed today.
- **Sound-cue-based stats** (footsteps heard, etc.) — nothing exposes this
  currently.
- **Tick-rate positional stream** (vs. interval polling) for smooth
  heatmaps/replay-quality movement — the existing interval-poll pattern
  (Tier 2) is probably good enough for zone-level stats; only worth Tier 3 if
  true movement replay is a goal.

## Tier 4 — demo parsing or likely infeasible

- **Full positional replay fidelity** matching HLTV demo playback — the
  archived `.dem` files (1,257 from the Philly LAN alone) are the only source
  for anything not captured *live*. A real open-source starting point exists
  now (`dod-tools`, see Appendix below) rather than a from-scratch parser, but
  it's still only useful for backfilling/validating past events, not for the
  accuracy/reliability goals stated here — those require live capture.
- **Voice comms analysis** — not applicable; DoD 1.3 voice isn't logged.
- **Lag-compensated "what the player actually saw"** reconstructions —
  engine-internal, not exposed via any DODX native.

---

## CS2-era stat glossary → DoD translation quick-reference

| Modern stat | DoD/KTP translation | Tier |
|---|---|---|
| ADR (avg damage/round) | Damage per half (data exists, express as rate) | 2 (derivation) |
| KAST | Kill/Assist/Survived-half/Traded % of lives | 2 (derivation, needs Traded) |
| Headshot % | Already captured | 0 |
| Accuracy % | Already captured (Statsme shots/hits) | 0 |
| Entry kill / entry death | First kill of a half or point-contest | 2 |
| Trade kill % | Traded death correlation | 2 |
| Multi-kill rounds (2k–5k) | Time-windowed kill clustering | 2 |
| Clutch win % (1vX) | Point-hold-while-outnumbered | 2 |
| Utility damage | Grenade/rocket damage (not just kills) | 2 |
| Flash assist | No DoD equivalent (no flashbang) | n/a |
| Impact/Rating composite | Weighted composite of the above — a KTPR design question, not a capture question | — |
| Save rate / econ stats | No DoD equivalent (no round economy) | n/a |
| Opening duel win % | First-contact-of-a-point win rate | 2 |

---

## Appendix: offline demo parsing as a complementary layer (`dod-tools`)

Found and cloned into `ktp_stats/dod-tools/`:
[cgdangelo/dod-tools](https://github.com/cgdangelo/dod-tools) — an actively
maintained, open-source Rust tool that parses GoldSrc DoD `.dem` files
directly (not via replay through a live engine). Verified by reading its
source, not just the README:

- **Architecture**: a generic GoldSrc demo-container parser (`dem` crate, a
  published dependency, v0.2.3) decodes the raw frame/network-message stream;
  a DoD-specific layer (`dod` crate, ~1,564 lines, using `nom` parser
  combinators) decodes DoD's `UserMessage` types on top of that. The
  `analysis` crate folds that event stream into per-player state. This is a
  real net-message decoder, not a wrapper around a real HLDS process — it
  doesn't need the engine at all.
- **What it computes today** (confirmed from `analysis/src/`: `kill.rs`,
  `mortality.rs`, `player.rs`, `round.rs`, `scoreboard.rs`, `clan_match.rs`,
  `time.rs`, plus a sample report in `assets/example_report.md`):
  scoreboard (score/kills/deaths/team/class), per-player **weapon-kill
  breakdown**, and — notably — **time-windowed kill streaks** ("waves": kill
  count, start time, duration, weapons used per wave). That last one is a
  working, shipped implementation of the Tier 2 "multi-kill window" idea
  above, from a source **independent of HLStatsX and HUD observer entirely**.
  `mortality.rs` implies it classifies death types (kill vs. suicide vs.
  teamkill) — potentially a ground-truth cross-check for the HLStatsX
  suicide-dispatch bug found in Phase 1.
- **What it does *not* compute today**: no damage, accuracy, objective/flag
  captures, headshots, assists, or positional data are visible in the module
  list or sample report. That's a current-scope gap, not necessarily a
  format limitation — the underlying `dem`/`dod` decode layer almost
  certainly carries entity-position deltas and more `UserMessage` types than
  the `analysis` crate currently surfaces (DoD's damage/hitbox/capture
  messages are net messages like any other). Since it's open source, adding
  a `damage.rs` or `position.rs` analysis module in the same pattern as
  `kill.rs` is plausible follow-on work, not a rewrite — but unverified until
  someone checks what the `dod` crate's `UserMessage` enum actually exposes.
- **Important caveat, from the README itself**: *"For best results, use on
  POV demos... Demos recorded by HLTV clients... have limited support."* The
  KTP archive's demos (1,257 from the Philly LAN alone, `KTPHLTVRecorder`
  output) are **HLTV-recorded**, not player-POV recordings. This tool's
  compatibility with KTP's actual archive is **unverified** — the first step
  before investing further should be running it against one real KTP `.dem`
  file and checking the output isn't degraded. Flagging this rather than
  assuming it works.
### Could HLTV support be enhanced? — source-level investigation

Read the actual parser code (not just the README) to find out what "limited
support" concretely means and whether it's fixable. Findings, all confirmed
by reading `dod/src/lib.rs` and `analysis/src/*.rs` directly:

- **HLTV handling that already works correctly**: `analysis/src/player.rs`
  explicitly detects the HLTV proxy's own connection slot (`*hltv == "1"` in
  the user-info string) and skips it, so the recording proxy itself is never
  misread as a player. There's also a dedicated `Hltv` and `Spectator`
  `UserMessage` variant already parsed. This isn't a stub — someone already
  did real HLTV-aware work here.
- **The two documented POV-vs-HLTV frequency differences are on
  `ClientAreas`** (the objective-capture HUD icon update — "often in POV,
  once in HLTV") **and a `GameRules`-shaped message** ("1 each spawn in POV;
  once on connection in HLTV?", author's own uncertainty noted with a `?`).
  Neither is a message the `analysis` crate currently uses for anything.
  **`DeathMsg`, `Frags`, and `CurWeapon`** — the messages actually driving
  today's kills/deaths/weapon-breakdown/streak output — have no documented
  POV-only restriction anywhere in the source. Nothing found suggests those
  specific stats break under HLTV recording.
- **The real risk is match/round-boundary detection, not HLTV vs. POV.**
  `ClanMatchDetection` (`analysis/src/clan_match.rs`) and `Round`
  (`analysis/src/round.rs`) — which decide when kill streaks/weapon
  breakdowns reset for a "new match" — are driven entirely by DoD's native
  `RoundState` message (`Reset`/`Start`/`AlliesWin`/`AxisWin`/`Draw`), which
  is DoD's built-in per-objective round loop (capture everything → brief
  reset → replay), not anything KTP-specific. The good news: reading the
  transition logic closely, the initial "match is live" detection only needs
  a `Reset` followed by a `Start` with everyone still scoreless — it does
  **not** require `ClanTimer`/`mp_clan_timer` (a stock DoD cvar KTP's custom
  match system almost certainly doesn't use), so this should fire correctly
  on real competitive play regardless of who's running the match logic. This
  is inference from reading the state machine, not a confirmed test result.
- **Net assessment**: nothing found in the source is a clear HLTV blocker for
  the stats this catalog actually wants (kills, deaths, weapon breakdown,
  streaks). The README's caution is real but may be more conservative than
  the specific KTP/audit use case needs. **Still recommend testing on one
  real KTP demo before trusting this** — code-reading can't substitute for
  running it, especially since KTP's specific match format (continuous
  flag-capture halves under custom `KTPMatchHandler` control, not vanilla
  DoD's round/clan-timer flow) is exactly the kind of thing that's cheap to
  get subtly wrong.

**A concrete, scoped enhancement worth proposing regardless of what testing
finds**: don't rely on in-demo match-boundary *detection* at all — KTP
already has authoritative match/half start-end timestamps elsewhere
(`ktp_matches.start_time/end_time` in the DB, `match_windows.json` from
`KTPInfrastructure/scripts/lan_demo_build.py`, which already maps every demo
file to its match_id/half). The CLI currently has no time-bounding flag
(confirmed — only `DEMO_PATHS` and `--output-format` exist in
`native/src/bin/cli.rs`). Adding a `--start`/`--end` (or tick-range)
argument that trusts an externally-supplied window, fed by KTP's own
already-correct match metadata, sidesteps the whole `ClanMatchDetection`
heuristic — and its dependency on native `RoundState` behaving exactly as
expected — entirely. This is a small, targeted change (a CLI flag plus
gating the existing analyzers on it) rather than a rewrite, and it directly
serves the "accuracy — live match only" goal by construction instead of by
inference from in-game state.

- **Automation potential**: the CLI mode takes a file list and supports
  `--output-format json`, which makes batch processing the whole archive
  straightforward to script (`Get-ChildItem *.dem | dod-tools-cli ... | ...`
  is literally the README's own example) — the same shape of batch job
  `KTPInfrastructure/scripts/lan_demo_build.py` already runs over the same
  demo archive for file organization, so it'd slot into existing tooling
  conventions rather than needing a new pattern.
- **Where this fits relative to the rest of the catalog**: this is
  fundamentally a **post-hoc / offline** source — a demo only exists to parse
  *after* the match is fully recorded, so it cannot serve the "live match
  accuracy" goal directly. Its value is as a **third, independent
  cross-validation and backfill source**: auditing HLStatsX/HUD observer
  numbers against a ground truth that isn't subject to either pipeline's own
  bugs (the suicide dispatch bug, the match-teardown forward gap), and
  potentially recovering stats for matches where live capture is known to
  have failed (e.g. the LAN's lost objective-capture events) — *if* capture
  events turn out to be decodable from the demo, which is unconfirmed for
  this tool's current scope. Recommend treating it as a validation layer
  alongside Tier 1/2, not a replacement data source.

## Suggested sequencing (for whoever implements this)

0. **Validate `dod-tools` against one real KTP demo, in parallel with
   everything else** — cheap, doesn't block or depend on any other step, and
   answers two questions at once: whether HLTV-recorded demos work well
   enough with it to be useful at all, and (via `mortality.rs`) what DoD
   actually logs for a suicide, which would sharpen the Tier 1 fix above.
1. **Fix the two reliability bugs first** (suicide dispatch regex,
   match-teardown forward gap). Everything else inherits their reliability.
2. **Tier 1** — pure query-side wins, cheapest possible stat-line growth.
3. **Tier 2, positional data first** — `dodx_get_user_origin`/`angles` at
   kill/death time unlocks the largest number of downstream stats (heatmaps,
   engagement distance, flank kills) for one small hook change.
4. **Tier 2, event-correlation stats** (trade kills, multi-kills, entry
   duels, KAST) — no new engine hooks at all, pure derivation once the above
   lands.
5. **Tier 3** only if a specific stat (most likely suppression) is judged
   worth new C++ module work.
6. **Tier 4** — deliberately deprioritized; revisit only if a specific
   research question needs historical (not live) fidelity.
