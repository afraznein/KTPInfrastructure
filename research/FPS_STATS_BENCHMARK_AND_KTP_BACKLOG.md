# FPS statistics benchmark and KTP exploration backlog

**Snapshot date:** 2026-08-19

**Status:** research and prioritization only; this branch changes no capture,
schema, rating, API, or public page

**Baseline:** KTPInfrastructure `preprod` at
`1e62f2e61f5242b509c10d87a39f851738bcc5ac`

## Resume here

KTP already captures enough canonical data to explore several useful statistics
without changing a game-server plugin. The next safe step is to run the P0
prototypes below against one real, completed human canary match, keep the output
private, and have players review whether it tells the truth about the match.

Do **not** add any candidate to KTPR or publish it merely because it can be
calculated. Definitions, source coverage, sample size, role/map bias, and
continuous-respawn semantics must be validated first.

This document is the current decision snapshot. The older
[`KTPR_STAT_CAPTURE_CATALOG.md`](../docs/ktpr_mcp/KTPR_STAT_CAPTURE_CATALOG.md)
remains useful as an exhaustive idea catalog, but its opening statement that
nothing is implemented is no longer current. Since that catalog was written,
KTP has added damage, capture, position, ownership, and kill-context telemetry.

## What other FPS products emphasize

The useful lesson is not to copy one game's scoreboard. Different products
repeatedly separate five questions:

1. Did the player win fights?
2. Did the player contribute damage or enable someone else's kill?
3. Did the player advance or defend the objective?
4. Did the player perform the job implied by their weapon or role?
5. Was the performance repeatable, or one exceptional event?

| Product/ecosystem | Officially exposed examples | KTP lesson |
|---|---|---|
| Counter-Strike competitive ecosystem | FACEIT exposes match/player statistics; ESEA MVP criteria explicitly call out kills, average damage per round (ADR), and headshot percentage. Valve match history uses player-created authentication/share codes. | Damage and headshots complement kills. Preserve consent and access boundaries for player-specific history. “Per round” must not be copied literally into roundless, continuous-respawn DoD. |
| Battlefield 2042 | Kills, assists, deaths, ping, tickets/objective progress, K/D, revives, accuracy, shots fired, damage assists, smoke/EMP assists, healing, resupply, repair, destroyed equipment, captures/defends, objective score, ribbons, and personal bests. | A team FPS should show objective, combat, and enabling/support contribution separately. Personal bests are understandable without inventing one opaque rating. |
| Call of Duty | Combat Record views include recent matches, eliminations/death, loadouts, mode/match performance, total eliminations, and a large medal taxonomy for streaks, multikills, combat, equipment, scorestreaks, and modes. | Event-derived highlights and recent form can make stats engaging. Keep medals explainable and avoid turning every event into noisy achievement spam. |
| Halo Infinite | Accuracy, assists, callout/driver/EMP/impulse/passenger assists, damage, headshots, K/D, KDA, melee kills, objective time, power-weapon kills, vehicle destroys, betrayals, and self-destructions. Career Rank is explicitly progression, not skill. | Separate participation/enabling assists by cause where the game can support them. Never present activity/progression as competitive skill. |
| Overwatch | Weapon and critical accuracy, final blows, eliminations, solo kills, damage, objective kills/time, contest time, assists, streaks, eliminations per life, and per-10-minute rates. | Normalize counting stats for time played. Distinguish participation from the final action. Objective presence and contest time can reveal value that kill totals miss. |
| Rainbow Six Siege | Career win rate, kills, assists, KOST, and splits by operator, playlist, and season. Official esports match pages also expose entry differential, KOST, kills/round, headshots, survival, clutches, multikills, objective actions, trade kills, and deaths that were traded. | Entry results, trade symmetry, survival, and role/context splits are strong competitive explanations. KOST needs a DoD-specific life definition rather than a blind port. |
| VALORANT | Riot exposes match data while requiring player opt-in for player-specific stats. Its policy permits post-game reflection but rejects pre-game scouting and real-time advice that changes player behavior. | Product/privacy constraints belong in the stat design. KTP should favor retrospective analysis and avoid live opponent profiling. |

## Current KTP evidence inventory

### Canonical or source-level data already captured

- Match and half boundaries, map, server, match type, and roster snapshot.
- Enemy frags and deaths, weapon, headshot, event time, half, killer/victim
  positions, team/role, prone/scoped state, clip/ammo context, and
  last-flag-defense context.
- Teamkills and suicides. Suicide position context is currently missing.
- Per-hit attacker/victim/weapon, raw and HP-capped damage, hit location, and
  game time. Per-hit positions are **not** captured.
- Assists and cap breaks; breaks include position, contester count, time
  remaining, and capout context when enrichment succeeds.
- Per-player capture credits and discrete flag-ownership transitions, including
  the initial ownership baseline.
- Alive-player position samples and static two-dimensional flag positions.
- StatsMe weapon shots/hits and StatsMe2 hit-zone aggregates.

### Already derived or prototyped

- K/D, KDA, headshot rate, raw accuracy, damage dealt/taken/differential,
  damage per minute, assists, captures, cap breaks, and weapon totals.
- Fast multikills, basic time-window trade kills, opening duel, head-to-head
  matchups, and the next objective capture after a multikill. These remain
  private shadow timelines.
- Positional accumulation near flags, ownership-aware attack/defense context,
  last-flag defense, and private heatmap-like aggregates.

### Material caveats

- `ktp_match_players` does not encode half in its key. A player changing teams
  between halves can be misclassified until the roster model is normalized.
- Damage rows have no coordinates. Kill distance is available; damage distance
  is not.
- Position sampling observes alive locations at intervals, not exact area
  entry/exit or line of sight.
- StatsMe shots/hits are aggregate flushes, not a canonical shot event stream.
  “Raw accuracy” also needs a DoD weapon caveat, especially for Garand chamber
  clearing.
- A DoD half is not a CS/R6 round. ADR, KOST, entry, survival, and clutch terms
  must be translated to continuous respawns and objective flow.
- Synthetic Lane B proves plumbing and invariants, not competitive validity.

## Candidate backlog

Priority meanings:

- **P0:** query/prototype from existing data; private shadow output first.
- **P1:** a small, justified capture/schema extension unlocks the metric.
- **P2:** high-volume, engine-sensitive, ambiguous, or privacy-heavy; research
  before implementation.

Confidence is confidence that the named source supports the calculation, not
confidence that the metric measures player skill.

| Priority | Candidate | Question answered | Current inputs | New capture | Confidence / cost | Initial visibility |
|---|---|---|---|---|---|---|
| P0 | Damage pace by half and minute | Who applied sustained effective pressure? | Capped damage, half/match duration | None | High / low | Private, then descriptive public stat |
| P0 | Damage conversion | How much damage became kills or assists, and how much was unconverted? | Damage ledger, frags, assists, time | None; agree attribution/window definition | High source / low compute | Private shadow |
| P0 | Kill participation | How often was a player the killer or credited assister on team kills? | Frags, assists, roster/team | None, after per-half roster fix or guarded same-team inference | Medium / low | Private shadow |
| P0 | Deaths that were traded and trade efficiency | Was a player's death promptly answered, and did the player trade teammates? | Existing basic-trade timeline, frags, roster | None for time-window version | High / low | Private shadow; label “basic trade” |
| P0 | Opening impact by half | Who won/lost the first duel, and did that team gain the next objective? | Opening duel, ownership/capture events | None | High / low | Private shadow |
| P0 | Revenge response | Did a victim later answer the same opponent, and how quickly? | Ordered frags and head-to-head pairs | None | High / low | Private shadow/highlight |
| P0 | Multikill objective conversion | Did a burst of kills precede a same-team capture or capout? | Existing multikill and ownership/capture timelines | None; retain non-causal wording | High / low | Private shadow/highlight |
| P0 | Kill engagement distance | At what ranges is each weapon/player effective? | Killer and victim coordinates on frags | None | High / low | Private until map-coordinate sanity checks pass |
| P0 | Weapon/role profile | What does a player contribute with each weapon/role? | Frags, damage, shots/hits, hit zones, scope/prone/ammo context | None for current profile | Medium-high / medium | Private, then descriptive splits |
| P0 | Objective proximity/pressure | Who spent time near friendly, neutral, enemy, or contested flags? | Position samples, flag positions, ownership timeline | None for sampled proximity approximation | Medium / medium | Aggregate only; never public raw paths |
| P0 | Last-flag and break quality | Who stopped the most dangerous captures, not merely the most captures? | Last-flag defense, break timer/contesters/capout, position | None | High / low | Private shadow |
| P0 | Personal bests and recent form | Is this performance exceptional for this player? | Historical match facts | None | High / low | Public only with minimum sample size |
| P0 | Consistency and floor/ceiling | Is output repeatable across maps and matches? | Historical normalized match facts | None | High / low | Private until minimum samples and map/role controls exist |
| P1 | Explicit life boundaries | What happened per life: survival time, kills/assists per life, and KAT/KAST-like coverage? | Existing deaths plus new spawn/life events | Emit durable spawn/life start with match/half context | High value / low-medium volume | Private shadow |
| P1 | Objective contest sessions | Who was actually contesting, for how long, and with what outcome? | Captures, breaks, positions plus new start/end participant events | Contest start/end and participant set | High value / medium volume | Private shadow |
| P1 | Canonical raw score event | Can cached player score be rebuilt and audited? | Current in-memory/end aggregate | Emit durable score facts | High operational value / low volume | Internal/audit |
| P1 | Per-half roster/team membership | Which side and role did a player represent in each half? | Current roster snapshot | Normalize roster key/history by half | High operational value / low volume | Internal foundation |
| P1 | Suicide context | Where and under what weapon/context did avoidable self-deaths occur? | Suicide event | Add position and tactical context | Medium / low volume | Private/descriptive |
| P1 | True fire/reload/switch events | What are time-to-first-shot, reload-death, burst, and weapon-switch patterns? | StatsMe is insufficient | Explicit events; establish a volume budget first | Medium / high volume | Private research only |
| P2 | Opportunity-adjusted accuracy | How accurate was the player when an enemy was actually visible/engageable? | Positions are insufficient | Visibility/line-of-sight engine work | Low-medium / high | Research only |
| P2 | Suppression/near misses | Did fire constrain enemies without hitting? | Not captured | Projectile/trace proximity and target state | Low / very high | Research only |
| P2 | Reaction/aim/turn telemetry | How quickly and smoothly did a player acquire a target? | Not captured | High-frequency view/shot/enemy context | Low / very high | Do not pursue without a concrete use case |
| P2 | Voice/callout assists | Did communication enable the play? | Not captured | Voice/comms analysis | Low / privacy cost unacceptable by default | Do not collect without explicit consent and governance |

## Recommended next five explorations

### 1. Symmetric trade analysis

Extend the existing basic trade output with both sides of the event:

- `trade_kills`: teammate deaths the player answered;
- `deaths_traded`: player deaths a teammate answered;
- `trade_opportunities`: teammate deaths inside the agreed time window;
- `trade_conversion_rate = trade_kills / trade_opportunities`.

Start with the existing five-second, same-half definition. Add distance later
using frag positions, but keep the name “basic trade” until line of sight and
true eligibility are available. Test 3/5/7-second sensitivity rather than
choosing a window from intuition alone.

### 2. Damage conversion and enabling contribution

Prototype:

- capped damage per minute and per half;
- capped damage per kill;
- damage followed by the attacker's kill;
- damage followed by a credited assist;
- unconverted damage at victim death, life reset, or an agreed timeout;
- share of team capped damage.

Use `damage_capped`, never nominal raw damage. Do not call damage per half
“ADR”: a KTP half is much longer and mechanically different from a CS round.
Damage-to-outcome correlation needs ordered timestamps and an explicit timeout;
it is not proof that one hit caused a later objective.

### 3. Objective pressure and contest participation

Use sampled positions plus flag ownership to estimate time near:

- a friendly flag under attack;
- a neutral or enemy flag while attacking;
- a last flag while defending;
- the location of a capture/break shortly before the event.

The first version is a sampled proximity estimate, not literal “objective
time.” Report coverage and sampling interval with every result. Exact contest
time and participant attribution belongs in P1 explicit contest sessions.

### 4. Weapon and engagement profile

For each weapon and role, combine kills, capped damage, headshot/hit-zone mix,
StatsMe shots/hits, kill distance bands, scoped/prone state, and ammo remaining
at the kill. This can answer whether a player creates value at expected ranges
without collapsing rifle, automatic, sniper, rocket, and MG jobs into one
unfair accuracy leaderboard.

Only kill distance is currently exact enough to derive. Per-hit damage distance
would require positions on damage events or a carefully bounded join to nearby
position samples.

### 5. Life-boundary capture and a DoD-native KAT metric

Add a low-volume spawn/life-start event. That unlocks average/longest life,
kills and assists per life, life survival, death rate, and a KOST-inspired
coverage metric.

Call the initial version **KAT coverage**: the percentage of completed lives in
which the player recorded a kill, assist, or had the death traded. Consider a
survival term only after life starts/ends are proven reliable. This avoids
pretending that “survived the round” has a clear analogue in a respawn game.

## Suggested prototype output contract

Every experimental field should carry enough metadata to prevent accidental
promotion:

```json
{
  "metric": "basic_trade_conversion_rate",
  "value": 0.42,
  "unit": "fraction",
  "definition_version": 1,
  "parameters": {"trade_seconds": 5},
  "source_coverage": {"frags": true, "roster": true, "positions": true},
  "confidence": "medium",
  "visibility": "private_shadow_only",
  "rating_effect": false
}
```

Store definition versions and parameters with reports. Results calculated with
different trade, multikill, proximity, or conversion windows are not directly
comparable.

## Validation sequence

1. Generate the current canary-evidence bundle for one real human match and
   require a clean source/ownership/roster result.
2. Calculate the five recommended explorations into a separate private report.
3. Show raw supporting events beside each derived highlight so a reviewer can
   disprove it.
4. Compare 3/5/7-second trade windows and at least two objective-proximity
   radii. Record sensitivity, not just the preferred answer.
5. Ask several players, without showing an overall rank, whether the results
   match what happened and where the definitions mislead.
6. Repeat across maps, sides, roles, and at least several official matches.
7. Promote only stable descriptive fields to a public contract. Any rating
   proposal gets a separate review and shadow period.

## Guardrails

- Keep raw player paths and individual heatmaps private. Publish only coarse,
  reviewed aggregates if they become useful.
- Do not offer live opponent scouting or real-time prescriptive coaching.
- Do not collect IP-derived, voice, or communications analytics for this work.
- Display source gaps and minimum sample sizes instead of silently substituting
  zero.
- Keep official, draft, scrim, 12man, and test classifications explicit.
  Retention policy may remove test/scrim raw data after 14 days; experiments
  must not weaken that policy. Draft remains retained under the current policy.
- Separate descriptive achievement, progression/activity, and competitive
  rating. One must not masquerade as another.
- Avoid a single composite score until each input has an understandable
  definition, robust coverage, and role/map normalization.

## Decisions to make after real-data review

- Is the main unit a life, half, match, or rolling time window?
- Which trade window and maximum distance best fit DoD play?
- What radii define objective proximity on each map, and should they vary by
  flag geometry?
- How should side, role, weapon, map, and time played normalize comparisons?
- Which fields may be public, private-to-player, admin-only, or permanently
  research-only?
- What minimum match count and data coverage is required for personal bests,
  trends, and comparisons?
- Should non-official matches inform personal analytics while remaining
  excluded from official leaderboards/ratings?

## Official sources consulted

- EA, [Battlefield 2042 Update #3.3](https://www.ea.com/games/battlefield/news/battlefield-2042-update-notes-3-3)
- EA, [Battlefield 2042 Update #1.2](https://www.ea.com/news/battlefield-2042-update-notes-1-2)
- EA, [Battlefield 2042 Update #4.0](https://www.ea.com/games/battlefield/news/battlefield-2042-update-notes-4-0)
- EA, [Battlefield 2042 Update #4.2.0](https://www.ea.com/en-gb/games/battlefield/battlefield-2042/news/battlefield-2042-update-notes-4-2-0)
- EA, [Battlefield Briefing: Progression and Cosmetics](https://www.ea.com/games/battlefield/news/battlefield-briefing-progression-and-cosmetics)
- Activision, [Black Ops 7 launch progression, challenges, and Combat Record](https://www.callofduty.com/blog/2025/11/call-of-duty-black-ops-7-ready-for-launch-progression-prestige)
- Activision, [Black Ops 6 progression, challenges, and medals](https://www.callofduty.com/ca/en/blog/2024/10/call-of-duty-black-ops-6-launch-progression-leveling-prestiging-challenges-intel)
- Halo Support, [Where to view Halo Infinite player stats](https://support.halowaypoint.com/hc/en-us/articles/30643133470868-Where-to-View-Halo-Infinite-Player-Stats)
- Halo Waypoint, [Career Rank overview](https://www.halowaypoint.com/news/career-rank-overview-season-4)
- Blizzard, [Overwatch Career Profile example](https://overwatch.blizzard.com/en-gb/career/c15fa783fe20cdfabf%7C673b7ba420c26b570ffa9ce3bd79244e/)
- Ubisoft, [Rainbow Six Siege: Operation Daybreak](https://www.ubisoft.com/en-gb/game/rainbow-six/siege/news-updates/seasons/daybreak)
- Ubisoft, [Rainbow Six esports match statistics example](https://www.ubisoft.com/de-de/esports/rainbow-six/siege/match/8500)
- Riot Games, [VALORANT developer policy and APIs](https://developer.riotgames.com/docs/valorant)
- Valve Developer Community, [Counter-Strike match-history access](https://developer.valvesoftware.com/wiki/Counter-Strike%3A_Global_Offensive_Access_Match_History)
- FACEIT, [Data API](https://docs.faceit.com/docs/data-api/data/)
- FACEIT Support, [ESEA regular-season MVP statistics](https://support.faceit.com/hc/en-us/articles/22367691432348-What-are-ESEA-Regular-Season-MVP-awards)
