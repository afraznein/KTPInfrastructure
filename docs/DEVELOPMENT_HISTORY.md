# KTP Development History

> ## ⚠️ STALE — timeline ends 2026-04-25; ~10 weeks of history missing
> Everything since end-of-April (ReHLDS .925–.927, KTPAMXX 2.7.15–2.7.20,
> KTPAmxxCurl 1.3.9–1.3.13, KTPMatchHandler 0.10.12x–0.10.142, HLTVRecorder
> 1.7.0, the 2026-05-31 credential rotation, Netdata disabled fleet-wide,
> the July assessment waves) is recorded in the root
> `discord-embeds/CHANGES_SUMMARY_*.md` period files, not here. A rewrite/
> append pass is tracked in the root TODO. Banner added 2026-07-07.

> Development timeline for the KTP competitive Day of Defeat server infrastructure — covers the full stack (engine, scripting platform, modules, match-handling plugins, anti-cheat, admin bot, infrastructure).
>
> **Doc home note:** This file (and `technical_guide.md`) used to live in `KTPMatchHandler/` for historical reasons — they predated the existence of `KTPInfrastructure/`. Moved to their proper home 2026-04-25.

| Metric | Value |
|--------|-------|
| **Project Duration** | October 2025 - Present |
| **Total Repositories** | 20 |
| **Estimated Development Hours** | 1430-1800 |
| **Last Updated** | 2026-04-25 |

**Doc convention going forward:** Major releases (architectural changes, root-causes, incident responses) get full prose. Minor/patch releases get one-line entries in component-version tables. Reduces maintenance burden vs. backfilling per-version detail that's already in repo CHANGELOG files.

---

## Table of Contents

- [Monthly Scope Summary](#monthly-scope-summary)
- [Architecture Decision Records](#architecture-decision-records)
  - [ADR-001: Eliminate Metamod (Extension Mode)](#adr-001-eliminate-metamod-extension-mode)
- [October 2025](#october-2025---foundation) - Foundation
- [November 2025](#november-2025---platform-development) - Platform Development
- [December 2025](#december-2025---feature-complete) - Feature Complete
- [January 2026](#january-2026---stability--polish) - Stability & Polish
- [February 2026](#february-2026---bare-metal--performance) - Bare Metal & Performance
- [March 2026](#march-2026---jit--code-review) - JIT & Code Review
- [April 2026](#april-2026---engine-threading-jit-activation-stack-expansion) - Engine Threading, JIT, Stack Expansion

---

## Monthly Scope Summary

| Month | Est. Hours | Focus Areas |
|-------|-----------|-------------|
| October 2025 | 120-150 | Foundation - initial plugins, Discord bots, relay service |
| November 2025 | 180-225 | Platform (C++ ReAPI/KTPAMXX), major plugin rewrites |
| December 2025 | 300-375 | Feature-complete push - overtime, extension mode, v1.0 releases |
| January 2026 | 120-150 | Stability, polish, explicit OT, admin tools |
| February 2026 | 240-320 | Bare metal migration, performance optimization, lag investigation, CPU isolation, bug audit, 2 new server deployments |
| March 2026 | 220-280 | JIT re-enablement, 3-round KTPAMXX code review (60+ fixes), fleet-wide plugin audit, match system performance, score persistence fix, engine profiler optimization |
| April 2026 | 220-280 | Engine threading (917-920), full-stack optimization pass, JIT activation, KTPAntiCheat launch, KTPAdminBot launch, KTPProfileAggregator launch, fleet outage recovery, AntiCheat integration phases 1-5 + 8.x, ktp_version_reporter rollout across all 9 plugins |
| **Total** | **1430-1800** | |

### Repository Breakdown

| Category | Count | Projects |
|----------|-------|----------|
| Core Engine (C++) | 4 | KTPReHLDS, KTPAMXX, KTPReAPI, KTPAmxxCurl |
| Game Plugins (Pawn) | 9 | KTPMatchHandler, KTPCvarChecker, KTPFileChecker, KTPAdminAudit, KTPHLTVRecorder, KTPPracticeMode, KTPGrenadeLoadout, KTPGrenadeDamage, KTPScoreTracker |
| Anti-Cheat (C# .NET / Avalonia + ASP.NET Core API) | 1 | KTPAntiCheat (added April 2026) |
| Discord Admin Bot (Python / discord.py) | 1 | KTPAdminBot (added April 2026) |
| Backend Services | 4 | Discord Relay, KTPFileDistributor, KTPHLStatsX, KTPProfileAggregator (added April 2026) |
| Discord Bots | 2 | KTPScoreBot-ScoreParser, KTPScoreBot-WeeklyMatches |

---

## Architecture Decision Records

Foundational architectural decisions with the analysis that drove them. These are not month-keyed because they shaped everything that followed; they live in their own section so a future reader (or future me) can find "why is the stack shaped this way" without paging through monthly progress logs.

### ADR-001: Eliminate Metamod (Extension Mode)

**Decision:** KTPAMXX loads as a ReHLDS extension via `<gamedir>/addons/extensions.ini` (`dod/addons/extensions.ini`) instead of as a Metamod plugin. Metamod is not present in any KTP deployment.

**Date:** Foundational (Oct/Nov 2025 — predates the rest of the stack).

**Why:** Wall penetration (bullets passing through surfaces) **breaks** when running ReHLDS + Metamod together — any version of Metamod. This is game-breaking for competitive Day of Defeat where wall bangs are a core mechanic.

| Configuration | Wall Penetration |
|--------------|------------------|
| ReHLDS + DoD (no Metamod) | **WORKS** |
| Vanilla HLDS + Metamod + DoD | **WORKS** |
| ReHLDS + Metamod + DoD | **BROKEN** |

**Symptoms:** Bullets stop at the first surface. No exit holes, no penetration effects.

#### Debug analysis

Debug logging added to ReHLDS's `PF_traceline_DLL` revealed identical trace inputs but divergent behavior:

**With Metamod (broken):**
```
Trace #1: frac=0.0496 ss=0 as=0  (bullet hits wall)
Trace #2: frac=0.0000 ss=1 as=0  (inside wall)
Trace #3: frac=0.0600 ss=0 as=0  (exit point found)
-- DoD stops here --
```

**Without Metamod (working):**
```
Trace #1: frac=0.0496 ss=0 as=0  (bullet hits wall)
Trace #2: frac=0.0000 ss=1 as=0  (inside wall)
Trace #3: frac=0.0600 ss=0 as=0  (exit point found)
Trace #4: frac=0.XXXX ss=0 as=0  (penetration continues)
Trace #5: frac=0.XXXX ss=0 as=0  (damage calculation)
```

Trace #1-3 are byte-identical between the two configs — same fractions, same positions, same flags. But DoD makes a different internal decision after trace #3: with Metamod present it stops; without Metamod it continues to traces #4-5 (actual penetration math).

#### What was ruled out

Systematic API-bypass testing:

| Test | Result |
|------|--------|
| Bypass individual trace wrappers | Still broken |
| Bypass ALL trace wrappers | Still broken |
| Pass original `enginefuncs_t` directly to DoD | Still broken |
| Pass original `DLL_FUNCTIONS` to engine | Still broken |
| Pass original `NEW_DLL_FUNCTIONS` to engine | Still broken |
| All three tables bypassed simultaneously | **Still broken** |

Even with complete API bypass — DoD receiving original ReHLDS functions, engine receiving original DoD functions, no Metamod wrappers in the call chain — wall penetration still fails.

#### Root cause

**The mere presence of Metamod in the DLL loading chain changes DoD's internal state.**

The issue is not in the API tables. It's in the loading process itself:

1. ReHLDS calls `GiveFnptrsToDll` to Metamod (which is presenting itself as the game DLL)
2. Metamod calls `GiveFnptrsToDll` to the real DoD
3. DoD receives the enginefuncs table from Metamod's address space

DoD appears to be making decisions based on something other than the function pointers themselves — possibly the address of the table, module addresses, initialization timing, or memory layout assumptions.

Vanilla HLDS + Metamod works because they were developed together and whatever assumptions DoD makes are satisfied. ReHLDS, as a reimplementation, has subtle differences that break that contract.

#### The decision

Bypass Metamod entirely via a KTP-ReHLDS extension loader:

```
Previous (BROKEN):           Decided (WORKING):
ReHLDS → Metamod → AMXX      ReHLDS → DoD
       → DoD                    ↓
                              KTPAMXX (loaded via extensions.ini)
```

This discovery is the load-bearing reason the entire KTP architecture is shaped the way it is. Eliminating Metamod isn't a preference — it's a technical requirement for competitive Day of Defeat on ReHLDS.

#### Downstream consequences

Every part of the stack inherited from this decision:
- **KTPAMXX** had to be forked from AMX Mod X to load as a ReHLDS extension instead of a Metamod plugin (changes AMXX_Attach signature, GetEngineFuncs sourcing, module-load lifecycle).
- **KTP-ReAPI** had to be forked from ReAPI to use KTPAMXX's `MF_GetEngineFuncs()` instead of Metamod's hook tables.
- **DODX module** had to learn to use ReHLDS hookchains (`SV_PlayerRunPreThink` etc.) instead of Metamod's PreThink hook.
- **Linux deployment** became viable for the first time — the traditional AMXX-on-Linux story required Metamod, which broke wall penetration. KTP's extension mode means Linux servers run with full feature parity.

The TECHNICAL_GUIDE describes the resulting architecture (six-layer stack, hookchain interfaces, extension loading sequence). This ADR is the why-it's-that-shape record.

---

## October 2025 - Foundation

**Initial Project Setup & Foundation**

This month established the core infrastructure for the KTP competitive server stack. Work included designing the overall architecture, setting up development environments for both Windows and Linux (WSL), and creating the foundational plugins that would later be expanded.

- **KTPMatchHandler**: Built the initial match workflow system from scratch, including the two-phase pre-start confirmation flow (captain initiates → opponent confirms), the ready system requiring minimum players per team, tactical and technical pause infrastructure with per-team budgets, map configuration loading from custom INI format, and initial Discord webhook integration for match notifications. Extensive research into DoD game mechanics and AMX Mod X plugin development.

- **KTPCvarChecker**: Adapted my existing CVAR checker for AMX 1.10. Developed versions 1.0 through 5.0 of the client variable enforcement system. Created the cvar monitoring architecture, violation detection and kick logic, player notification systems, and the configuration file format for defining monitored cvars with allowed value ranges.

- **KTPScoreBot-ScoreParser** (Discord Bot): Built a Node.js Discord bot that uses text extraction, score pattern matching, and formatted response generation to parse match scores in Discord channels.

- **KTPScoreBot-WeeklyMatches** (Discord Bot): Created a Discord bot for weekly match announcements with significant iteration - went through 4 major rewrites (v1-v4) to handle Discord embed limits, table formatting challenges, and timezone issues. Parses match schedules from web sources and generates formatted announcements.

- **Discord Relay**: Deployed a Google Cloud Run service acting as a webhook proxy between game servers and Discord API. Handles authentication, rate limiting, and provides a stable endpoint for the curl-based game server integrations. Required learning GCP deployment, Cloud Run configuration, and Discord API integration.

- **KTPFileChecker**: Adapted my existing File checker for AMX 1.10. Developed new version of client-side file consistency validation to detect modified game files (sprites, models, sounds) that could provide unfair advantages.

---

## November 2025 - Platform Development

**Focus: C++ Engine Work**

This month involved significant C++ development work on the core engine components. The focus was building custom forks of ReAPI and AMX Mod X to support features not available in upstream versions, particularly around the pause system and real-time cvar detection.

- **KTPMatchHandler v0.4.0-0.5.0**: Major pause system overhaul representing a complete rewrite of pause handling. Integrated with ReAPI for native `rh_set_server_pause()` control that works even with `pausable 0`. Implemented real-time HUD countdown updates during pause via the `RH_SV_UpdatePausedHUD` hook (required custom ReHLDS/ReAPI development). Added disconnect auto-pause with cancellable 10-second countdown. Created the match type system supporting COMPETITIVE, SCRIM, and 12MAN modes with per-type configurations and Discord channel routing. Implemented half tracking for automatic 1st/2nd half detection. Built player roster logging with SteamID and IP capture for competitive accountability.

- **KTPAMXX** (Custom AMX Mod X Fork): Forked AMX Mod X and added the `client_cvar_changed` forward that fires in real-time when clients respond to cvar queries - this required understanding the AMXX plugin callback system and the HL engine's cvar query mechanism. Set up cross-platform build system for both Windows (Visual Studio) and Linux (GCC via WSL). Created initial documentation and established the fork's divergence from upstream.

- **KTPReAPI** (ReAPI Fork): Forked ReAPI and integrated KTP-ReHLDS custom headers. Added the `RH_SV_UpdatePausedHUD` hook that fires every frame during server pause - this required reverse engineering the ReHLDS pause implementation and adding a new hook point. Ensured Windows XP compatibility for legacy server deployments. This C++ work required deep understanding of the ReHLDS/ReAPI architecture and GoldSrc engine internals.

- **KTPCvarChecker v5.4-7.5**: Achieved 60% reduction in function calls through major performance optimization pass. Implemented priority-based periodic monitoring that checks high-risk cvars more frequently. Updated for ReHLDS compatibility and the new real-time cvar detection via KTPAMXX's `client_cvar_changed` forward.

- **KTPScoreBot-WeeklyMatches v3.0-4.1**: Complete rewrite of the weekly match bot. Added playoff bracket parser for tournament phases. Fixed timezone offset issues causing wrong match dates/times. Improved week detection logic for current week window handling.

- **KTPAdminAudit**: Initial versions of the admin action logging plugin. Menu-based interface for kick/ban operations with audit trail logging to Discord.

---

## December 2025 - Feature Complete

**Focus: Feature-Complete Release Push (Largest Development Month)**

December represented the most intensive development period, pushing all major components to feature-complete status. The crown achievement was the complete overtime system in KTPMatchHandler along with the "extension mode" architecture that allows KTPAMXX to run without Metamod.

- **KTPMatchHandler v0.5.1-0.10.1**: This version range represents approximately 50 micro-releases with extensive feature development. v0.5.1-0.5.2 fixed critical bugs including a cURL header memory leak and tech pause budget integer underflow. v0.6.0 added unique match ID system (`KTP-{timestamp}-{map}`) and the `/whoneedsready` command. v0.7.0-0.7.1 integrated with HLStatsX for clean warmup vs match stats separation, added match context persistence via localinfo keys that survive map changes. v0.8.0 added match score tracking via TeamScore message hooks, Discord match-end notifications with winner announcement, and custom team name support. v0.9.0 introduced KTP season control with password protection and the DRAFT match type. v0.9.1-0.9.16 refined Discord embed formatting, periodic score saving, and score restoration after round restarts. **v0.10.1 delivered the complete Overtime System**: automatic OT trigger on tied regulation, 60-second break voting period, 5-minute OT rounds with team side swaps, tech budget reset at OT start, infinite rounds until winner, and full state persistence across map changes via localinfo.

- **KTPAMXX v2.0-2.6.1**: Massive development on the custom AMX Mod X fork. v2.0 established the KTP AMX foundation. v2.1.0 added map change support and client commands in extension mode. v2.2.0 enabled event and logevent support in extension mode. v2.4.0 was a complete rewrite of the DODX module for extension mode compatibility. v2.5.0 added HLStatsX integration natives (`dodx_flush_all_stats`, `dodx_reset_all_stats`, `dodx_set_match_id`) and fixed `get_user_msgid`. v2.6.0 added `ktp_drop_client` native and gamerules access. v2.6.1 introduced `ktp_discord.inc` shared include and the `RH_SV_Rcon` hook for RCON audit logging. The extension mode architecture allows KTPAMXX to load as a ReHLDS extension directly, bypassing Metamod entirely - this was critical because Metamod breaks wall penetration in DoD.

- **KTPReAPI v5.25-5.29**: v5.25.0 achieved "Extension Mode" - the ability to run without Metamod by loading as a ReHLDS extension. Added 10 ReHLDS extension mode hooks required for AMXX/DODX compatibility. v5.29 added the `RH_SV_Rcon` hook that fires on every RCON command for audit logging purposes.

- **KTPAmxxCurl**: Forked the upstream AMXX curl module and removed all Metamod dependencies. Integrated with KTPAMXX's `MF_RegModuleFrameFunc()` frame callback API for non-blocking HTTP operations. This enables Discord webhook calls from plugins without blocking the game server.

- **KTPHLTVRecorder v1.0.0**: Initial release of automatic HLTV recording triggered by KTPMatchHandler forwards. Sends UDP RCON commands to paired HLTV server instances. Demo files named by match type and ID for easy organization.

- **KTPCvarChecker v7.5-7.7**: Added `cl_filterstuffcmd` detection - this client cvar can be abused to ignore server cvar queries. Integrated shared Discord notification via `ktp_discord.inc`.

- **KTPAdminAudit v1.2-2.2**: v1.2.0 established initial admin audit logging. v2.1.0 added menu-based kick/ban interface with ReHLDS integration for reliable client dropping. v2.2.0 added RCON audit logging via the new `RH_SV_Rcon` hook.

- **KTPFileDistributor v1.0.0**: Initial release of the file distribution server. Node.js service that serves game files to servers clients and notifies Discord when files are downloaded. Helps track which servers have successfully received the uploads. Used for rapid deployment of updates (maps, configs, plugin updates, etc.)

- **KTPHLStatsX**: Set up HLStatsX:CE (Community Edition) with KTP-specific modifications. Added match ID tracking support so stats can be correlated to specific matches. Integrated with KTPMatchHandler's `KTP_MATCH_START` and `KTP_MATCH_END` log markers.

- **Discord Relay v1.0.1**: Bug fix for `fetchWithRetries()` argument format.

---

## January 2026 - Stability & Polish

**Focus: Production Hardening & Administrative Tools**

January focused on production stability, fixing edge cases discovered during real matches, and adding administrative tools. The explicit overtime command system was a significant rework based on player feedback.

### KTPMatchHandler v0.10.30-0.10.65

| Version Range | Key Changes |
|---------------|-------------|
| v0.10.27-28 | Changelevel hooks (`RH_PF_changelevel_I`) for reliable match state finalization |
| v0.10.30 | `.commands` help listing, HLTV reminders, 2nd half pending HUD |
| v0.10.32-34 | Critical OT recursive loop crash fix |
| v0.10.35 | Tactical pauses disabled (tech-only policy) |
| v0.10.36 | Discord channel routing for 12man/draft matches |
| v0.10.37 | Server hostname in match IDs |
| **v0.10.38** | **1.3 Community Discord 12man integration** with Queue ID |
| v0.10.41 | Map config prefix matching fix (longer keys first) |
| **v0.10.43** | **Explicit `.ktpOT` and `.draftOT` commands** (replaces automatic OT) |
| v0.10.44 | Intermission auto-DC fix |
| v0.10.45 | Dynamic server hostname reflecting match state |
| v0.10.46 | Match-type-specific ready requirements (6v6 KTP, 5v5 others) |
| **v0.10.47** | **`.forcereset` admin command** for recovering abandoned servers |
| v0.10.48 | ~190 lines dead code cleanup, compiler warnings fixed |
| v0.10.49 | Standard AMXX logging for daily rotation |
| v0.10.50-52 | Roster and ready counter bugs after halftime |
| **v0.10.53** | **Auto-DC tuning** (30s delay, competitive-only) |
| v0.10.54 | Experimental pause overlay disable (`showpause 0`) |
| **v0.10.55** | **`.cancel` during 2nd half pending**, Discord embed uniformity |
| **v0.10.59** | **Simplified match IDs** (`{timestamp}-{shortHostname}`), hostname timing fix |
| v0.10.60 | Expanded `.commands` output with admin/other plugin commands |
| **v0.10.61** | **Ready team label fix** - shows "Allies"/"Axis" not team identity in 2nd half |
| **v0.10.62** | **Draft match duration** - 15-minute halves (was 20 minutes) |
| v0.10.63 | `.grenade` in `.commands` help, hostname caching fix (1s delay) |
| v0.10.64 | Pause chat relay via `client_print` bypass |
| **v0.10.65** | **Silent pause mode** - `ktp_silent_pause` cvar hides client overlay |

### Other Component Updates

| Component | Version | Key Changes |
|-----------|---------|-------------|
| **KTP-ReHLDS** | v3.22.0.904 | Silent pause mode (`ktp_silent_pause`), hostname broadcast hooks |
| **KTPAMXX** | v2.6.7 | `dod_damage_pre` forward, grenade natives, player manipulation natives, noclip |
| **KTPReAPI** | v5.29.0.362-ktp | Map change interception hooks (`RH_PF_changelevel_I`, `RH_Host_Changelevel_f`) |
| **KTPCvarChecker** | v7.12 | Debug cleanup, Discord toggle cvar, KTP emoji branding, notification grouping |
| **KTPFileChecker** | v2.3 | Discord notification grouping, fc_checkmodels cvar |
| **KTPAdminAudit** | v2.7.3 | Map change auditing, RCON quit/exit blocking, changemap countdown fix |
| **KTPAmxxCurl** | v1.2.0-ktp | Use-after-free fix, handle allocation fix, socket map cleanup |
| **KTPFileDistributor** | v1.1.0 | Multi-channel Discord support |
| **KTPHLStatsX** | v0.2.2 | Player tracking, stats aggregation, half detection regex, debug logging |

### New Plugins (January 2026)

| Component | Version | Description |
|-----------|---------|-------------|
| **KTPPracticeMode** | v1.3.0 | Practice mode with infinite grenades, HUD indicator, `.grenade` command |
| **KTPGrenadeLoadout** | v1.0.3 | Custom grenade loadouts per class via INI config |
| **KTPGrenadeDamage** | v1.0.2 | Grenade damage reduction by configurable percentage |

### KTPHLTVRecorder v1.0.4-1.3.0

| Version | Changes |
|---------|---------|
| v1.0.4 | Config parsing fix, improved logging |
| **v1.1.0-1.1.1** | **Major rewrite: HTTP API** replaces UDP RCON via FIFO pipes |
| v1.2.0 | Match type support for all KTPMatchHandler types |
| **v1.2.1** | **`.hltvrestart` admin command** with Discord audit notification |
| **v1.2.2** | Orphaned recording cleanup on plugin startup/shutdown |
| **v1.3.0** | **Per-half demo files** - each half gets `_h1`, `_h2`, `_ot1` suffix |

- **KTPCvarChecker v7.8-7.9**: v7.8 cleaned up debug logging. v7.9 added Discord toggle cvar for enabling/disabling notifications.

- **KTPAdminAudit v2.6.0**: Added map change command auditing, server control command tracking, and console command audit logging.

- **KTPAmxxCurl**: Fixed critical segfaults in async curl handling - use-after-free bugs where raw pointers were passed to ASIO async callbacks and could be deleted before callback execution. Changed to `shared_ptr` tracking. Fixed handle allocation collision bug and stale socket map entries.

- **KTPFileDistributor v1.1.0**: Added multi-channel Discord support via `AdditionalChannelIds` configuration.

- **Server Infrastructure**: Deployed Atlanta 2-5 server cluster (ports 27016-27019) with full LinuxGSM configuration, HLStatsX integration, and KTPFileDistributor setup. Configured HLTV instances 27021-27024 with systemd services and scheduled restart timers. Diagnosed and fixed UDP buffer exhaustion issue (47k+ RcvbufErrors) by increasing kernel buffer sizes from 208KB to 25MB. Documented server setup procedures for future deployments. **Deployed Dallas game server cluster** (74.91.114.178 — historical; that VPS era is deprecated and its IPs re-leased by the provider; current Dallas is 74.91.126.55) with identical configuration. **Added nightly scheduled restarts** at 3 AM ET for both Atlanta and Dallas game servers with Discord embed notifications (live-updating: shows "In Progress" then edits to "Complete"). Fixed LinuxGSM "old type tmux session" bug that caused spurious server restarts by patching `command_monitor.sh` on all instances.

---

## February 2026 - Bare Metal & Performance

**Focus: Infrastructure Migration & Performance Optimization**

February marked the transition from VPS hosting to dedicated bare metal servers, eliminating CPU steal issues that plagued competitive matches. Significant performance optimization research led to new engine-level profiling capabilities.

### Bare Metal Deployment

| Server | IP | Hardware | Status |
|--------|-----|----------|--------|
| Denver | 66.163.114.109 | Xeon E3-1240 V2, 16GB | Deployed 01/30 |
| Atlanta | 74.91.121.9 | Xeon E3-1271v3, 32GB | Deployed 02/01 |
| Dallas | 74.91.126.55 | Xeon E3-1271v3, 32GB | Deployed 02/03 |

**Why Bare Metal:** GoldSrc's 1000 tick rate is especially vulnerable to CPU steal. A 20ms steal at 1000 tick means 20 missed ticks, while the same steal at 64 tick (CS2) only misses ~1 tick.

### KTP-ReHLDS v3.22.0.904

**Frame Profiling System:**
- `ktp_profile_frame` cvar - Enable/disable frame time profiling
- `ktp_profile_interval` cvar - Seconds between summary logs (default: 10)
- Tracks: SV_ReadPackets, SV_Physics, SV_SendClientMessages, peak edict count
- Low overhead: accumulates per-frame, logs summary every N seconds

**Host_FilterTime FPS Fix:**
- Original: `1.0f / (fps + 1.0f)` capped servers at sys_ticrate - 1
- Fixed: `1.0 / fps` allows true 1000 fps at sys_ticrate 1000
- Changed `fps` variable from float to double for precision

### KTPAMXX v2.6.8-2.6.9

**v2.6.9:**
- Runtime pdata offset detection - auto-detects Linux offsets for grenade manipulation
- Ubuntu 22.04: +5 offset adjustment, Ubuntu 24.04: +4 offset adjustment
- Eliminates need for separate binaries per OS version
- Admin flag accumulation bug fix - admin flags now accumulate correctly across multiple entries

**v2.6.8 - Extension Mode Header Stubs:**
- Complete Metamod-free compilation support for third-party modules
- Enables modules like amxxcurl to compile without Metamod SDK headers

### KTPMatchHandler v0.10.66-0.10.69

**v0.10.69:**
- `ktp_match_competitive` cvar for programmatic match state detection
- `KTP_HALF_END` log event for accurate first-half end time in HLStatsX
- Team name reset on match end (prevents stale names carrying over)

**v0.10.68:**
- Team name reset fix for match cleanup

**v0.10.67:**
- HLStatsX stats timing - Reduced KTP_MATCH_START delay from 100ms to 10ms
- Abandoned match stats fix - Added `dodx_flush_all_stats()` before KTP_MATCH_END
- Enhanced changelevel debug logging for map transition diagnostics

**v0.10.66:**
- HLStatsX first half stats fix - KTP_MATCH_START log now uses delayed task

### KTPHLTVRecorder v1.4.0

- Pre-match HLTV health check before starting recording
- Automatic recovery attempt if health check fails
- Discord + in-game chat alerts when recording may not work
- Callback failure detection for recording command errors

### KTPAmxxCurl v1.2.1-ktp

- Forward registration validation prevents silent callback failures
- Detailed callback logging with forward ID
- WriteCallback diagnostics and graceful fallback

### KTPInfrastructure v1.1.0-1.2.0

**v1.2.0:**
- Comprehensive performance optimizations in `provision-gameserver.sh`
- Ubuntu 24.04 support with auto-detection
- Memory optimizations: THP, KSM, compaction disabled
- Network optimizations: GRO/LRO/TSO disabled, conntrack bypass
- `ktp-chrt.timer` - Auto-applies real-time scheduling every 30 seconds

**v1.1.0:**
- LinuxGSM monitor bug fix documentation (HIGH PRIORITY)
- Ubuntu optimization research documentation

### Other Updates (Feb 1-6)

| Component | Version | Changes |
|-----------|---------|---------|
| KTPGrenadeLoadout | v1.0.5 | Batch spawn processing fix (196ms spike eliminated) |
| KTPHLStatsX | v0.2.5 | KTP_HALF_END handler for accurate H1 end_time |
| KTPCvarChecker | v7.12 | Emoji removal from headers, documentation cleanup |

### Codebase Review (Feb 1-6)

Systematic review across all 16+ KTP projects:
- Documentation cleanup: emoji removal from headers, stale version fixes
- Dead code removal and unused variable cleanup
- CLAUDE.md gitignore audit across all projects
- README/CHANGELOG consistency pass

### Feb 7-19: Frame Profiling & Lag Investigation

Deep investigation into recurring lag spikes reported by players during competitive matches. Built comprehensive profiling tools at the engine level.

**KTP-ReHLDS Frame Profiling:**
- 6-phase frame timing: read (SV_ReadPackets), phys (SV_Physics), misc1, send (SV_SendClientMessages), post, steam
- `[KTP_SPIKE]` log alerts when any phase exceeds configurable thresholds
- Per-opcode instrumentation for granular packet processing analysis
- SV_ParseMove CPU-time profiling to isolate per-client processing costs

**Engine Changes:**
- MAX_RATE raised from 100,000 to 1,000,000 in net.h (allows higher client rate settings)
- HLTV interp buffer reduced from 50ms to 15ms for lower latency spectating
- MAX_PROXY_UPDATERATE raised to 200

**Key Findings:**
- Discovered `clc_cvarvalue2` causing 160-185ms frame freezes (KTPCvarChecker bug - synchronous cvar queries blocking the frame loop)
- Steam API processing confirmed negligible (<0.055ms)
- Spikes are 100% in `read` phase (SV_ReadPackets) - single client packets taking 3-6ms to process
- `profiling-report.py` tool built for multi-server spike analysis across all locations

### Feb 17-19: New York & Chicago Deployments

Expanded server fleet with two new locations for scrim play.

| Server | IP | Hardware | Branding |
|--------|-----|----------|----------|
| New York 1-5 | 74.91.123.64 | Baremetal | KTPSCRIM - New York 1-5 |
| Chicago 1-5 | 172.238.176.101 | KVM VPS | KTPSCRIM - Chicago 1-5 |

- Total fleet: **25 game servers** across 5 locations (Atlanta, Dallas, Denver, New York, Chicago)
- 25 HLTV proxy instances on data server (ports 27020-27044)
- Full KTP stack deployment with clone-ktp-stack.sh provisioning
- LinuxGSM monitor bug patch applied to all new instances

### Feb 17: KTPAMXX v2.6.10 - plugin_init Memory Leak Fix

Critical extension mode bug where subsystem re-registration on every map change caused unbounded memory growth.

**Problem:** In extension mode, `plugin_init` re-registered all commands, forwards, events, log events, messages, and menus on each map change without cleanup. Growth rate: ~2ms per map change, reaching 107ms+ after 50 map changes.

**Two-pronged fix:**
1. `modules_callPluginsUnloading()` called before `plugin_init` - lets ReAPI clear hookchain vectors (100% plugin-owned)
2. Dedup-at-registration for all 7 subsystems: commands, SP forwards, multi-forwards, events, log events, messages, menus

**Result:** `plugin_init` flat at ~0.9ms regardless of map changes (120x improvement over post-leak state).

**Critical lesson learned:** No subsystem cleanup (`g_commands.clear()` etc.) is safe because C++ modules register state during `AMXX_Attach`. Dedup-at-registration is the correct approach.

### Feb 20-24: KTPMatchHandler v0.10.70-0.10.82

| Version | Key Changes |
|---------|-------------|
| v0.10.72-73 | Discord consolidated embeds with live-updating scores during match |
| **v0.10.74** | **Halftime changelevel watchdog** - fixes NY5 infinite changelevel loop |
| **v0.10.75** | **Menu crash fix** - ATL1 segfault from menu callback during map change |
| **v0.10.77** | **Discord curl use-after-free fix** - shared header slist across async requests |
| **v0.10.78** | **pfnChangeLevel rate limiting** - 6.8M daily log lines from changelevel spam |
| **v0.10.82** | **pfnChangeLevel debounce** - 26M+ calls reduced to 1 per intermission, 11 crashes fixed, ~10GB logs cleaned |

### Feb 20-24: Infrastructure Optimization

Comprehensive performance tuning across all bare metal servers.

**Rate Settings Standardized (all 25 servers):**
- `sv_maxrate 1000000` (was mixed values)
- `sv_maxupdaterate 120` (reverted from 200 - DoD client.dll clamps, breaks above 120)

**CPU Isolation & Pinning:**
- Kernel boot params: `isolcpus=2,3,5,6,7 nohz_full=2,3,5,6,7 rcu_nocbs=2,3,5,6,7`
- IRQ affinity steering to housekeeping CPUs 0,1,4 (bitmask 0x13) via rc.local
- Per-port CPU pinning: 27015→CPU2, 27016→CPU3, 27017→CPU5, 27018→CPU6, 27019→CPU7
- Chicago (4 vCPU, no isolcpus): 27015→1, 27016→2, 27017→3, 27018+27019→0
- `SCHED_FIFO` priority 50 (upgraded from `SCHED_RR` 20)
- `ktp-apply-chrt.sh` runs every 30s via `ktp-chrt.timer`
- `ktp-scheduled-restart.sh` applies pinning immediately after server start

**Result:** OS scheduling stalls reduced from 9,445 to 0.

### Feb 25-27: Systematic Bug Audit

**Phase 1 - Six Components:**

| Component | Version | Key Fixes |
|-----------|---------|-----------|
| **KTPAmxxCurl** | v1.3.0-1.3.1-ktp | `curl_get_response_body` native added, 4 bug fixes |
| **KTPAMXX** | v2.6.11 | SP forward dedup crash fix, null guards, infinite loop fix, bounds fix |
| **KTPCvarChecker** | v7.17 | Range enforcement fix (clamps to nearest valid bound instead of rejecting) |
| **KTPAdminAudit** | v2.7.5 | Changemap race condition fix, menu buffer size increase |
| **KTPHLStatsX** | v0.2.7 | 4 data integrity fixes: headshot flush timing, duplicate player handling, start_time accuracy, TK/suicide aggregation |
| **KTPHLTVRecorder** | v1.5.2 | HTTP response validation, auth header fix, demo cutoff fix |

**Phase 2 - KTPMatchHandler + Full Deploy:**

- **KTPMatchHandler v0.10.83:** Discord code extraction (~980 lines into helper functions), 6 bug fixes, ~165 lines dead code removed
- **KTPMatchHandler v0.10.84:** HTTP response validation for all curl callbacks, OT break state cleanup, additional dead code removal
- Full stack recompile + deploy to all 25 servers (325 file uploads via paramiko SFTP)

### Feb 27: Critical Crash Fix (Post-Deploy)

4 segfaults (3x New York, 1x Atlanta) traced to SP forward dedup parameter type mismatch in KTPAMXX `CForward.cpp`.

**Root Cause:** Same Pawn function registered as both a menu callback (`FP_CELL`) and a curl callback (`FP_STRING`). The dedup logic matched on function name alone, so when the curl callback fired, it found the menu forward (registered first) and passed a string pointer where an integer was expected. Integer menu selection value `1` cast to `char*` → `strlen(0x1)` → segfault.

**Fix:** Added `numParams` + `paramTypes` comparison via `memcmp` to both `registerSPForward` overloads. Forwards with the same function name but different signatures are now correctly treated as distinct forwards.

Rebuilt KTPAMXX v2.6.11, deployed to all 25 servers, verified stable.

### Other Updates (Feb 7-28)

| Component | Version | Changes |
|-----------|---------|---------|
| KTPHLTVRecorder | v1.5.2 | Demo cutoff fix, use-after-free fix, HTTP response validation |
| KTPCvarChecker | v7.17 | Fixed cvar polling, async enforcement, range correction |
| KTPAdminAudit | v2.7.5 | Changemap race condition, menu buffer increase |
| KTPAmxxCurl | v1.3.1-ktp | Response body capture native, 4 bug fixes |
| KTPHLStatsX | v0.2.7 | Headshot flush, duplicate players, TK/suicide aggregation |
| KTPInfrastructure | v1.4.0 | CPU isolation, per-port pinning, SCHED_FIFO 50 |
| KTPGrenadeLoadout | v1.0.5 | (unchanged) |
| KTPGrenadeDamage | v1.0.2 | (unchanged) |
| KTPPracticeMode | v1.3.0 | (unchanged) |

### Infrastructure Optimizations Applied

All bare metal servers (Atlanta, Dallas, Denver, New York) now have:
- Lowlatency kernel (1000Hz) + pingboost 2
- CPU mitigations disabled (`mitigations=off`)
- ALL C-states disabled (`max_cstate=0`)
- 25MB UDP buffers
- Real-time scheduling via systemd timer
- Persistent optimizations via `/etc/rc.local`
- **CPU isolation:** `isolcpus` + `nohz_full` + `rcu_nocbs` on game server CPUs
- **IRQ affinity:** All hardware interrupts steered to housekeeping CPUs (0, 1, 4)
- **Per-port CPU pinning:** Each game server instance pinned to a dedicated CPU core
- **SCHED_FIFO 50:** Real-time scheduling priority for all game server processes
- **ktp-chrt.timer:** Systemd timer re-applies CPU pinning + scheduling every 30 seconds

Chicago (KVM VPS, 4 vCPU) has all optimizations except `isolcpus` (insufficient cores) with adjusted CPU pinning layout.

---

## March 2026 - JIT & Code Review

**Focus: KTPAMXX Code Review, JIT Re-Enablement, Fleet-Wide Plugin Audit**

March centered on a comprehensive three-round code review of the KTPAMXX engine (the platform all plugins run on), producing 60+ fixes across all layers of the stack. The headline discovery was that JIT compilation had been disabled since the KTP fork was created — every plugin had been running through the slow C interpreter since launch.

### KTPAMXX v2.6.16-2.7.2 — Engine Code Review + JIT

**v2.6.16-2.6.18 (Mar 7-13):** Pre-review fixes including DODX pdata offset auto-detection rewrite (two-phase write-then-verify), halftime score zeroing fix (scores were being reset to 0 before KTPMatchHandler could read them), and DODX detection log spam cleanup.

**v2.7.0 (Mar 13) — Code Review Round 1 + JIT Re-Enablement:**

Three rounds of code review across the entire KTPAMXX codebase covering core runtime, module SDK, DODX module, and build system. All reviewed through the lens of extension mode operation (no Metamod).

| Category | Findings |
|----------|----------|
| Critical | 8 (7 fixed, 1 was not a bug) |
| Warning | 17 (12 fixed, 2 not bugs, 3 deferred) |

**JIT/ASM32 Re-Enablement (Critical #1):** The JIT compiler and x86 ASM dispatcher were disabled with a "KTP DEBUG" label since the initial fork to get extension mode working. All Pawn plugins had been running through the slow C interpreter since day one. Re-enabled native x86 JIT compilation and hand-optimized ASM dispatcher.

Measured impact — fleet-wide profiling data (~290k pre-JIT intervals vs ~65k post-JIT):
```
                    Before      After
Avg frame time      0.026ms     0.020ms   (-23%)
Worst spike         1.84ms      0.17ms    (-91%)
Min FPS floor       351         845       (+141%)
```

Other critical fixes: security hardening (`-fstack-protector-strong`, `FORTIFY_SOURCE=2`, full RELRO), module SDK double-free in `rewriteNativeLists`, stale frame callbacks after module detach, DODX weapon ID bounds checks, `C_ClientCvarChanged` player guard.

**v2.7.1 (Mar 13) — Code Review Round 2:**
5 criticals and 8 warnings. Key fix: **shot double-counting** — both button-state detection AND CurWeapon clip-decrement detection were running simultaneously, inflating HLStatsX accuracy stats since extension mode was enabled. Other fixes: SP forward null deref, `dod_weaponlist` OOB, event parser off-by-one, entity leak in `dodx_give_grenade`.

**v2.7.2 (Mar 13) — Code Review Round 3:**
CLogEvent last-char trim (silently dropped closing `"` on all DoD log events in extension mode), MessageHook_Handler null chain propagation, say/say_team prefix list separation.

### KTPAMXX — ClearPluginLibraries Crash Fix (Mar 14)

`.changemap` command intermittently crashed servers with segfault at page-aligned addresses. Core dump analysis revealed native function pointer `0xea35e000` pointed to `munmap`'d memory. Root cause: `ClearPluginLibraries()` freed executable thunk pages allocated by `register_native()` for cross-plugin natives, but `plugin_natives()` is never re-called during reload. Fix: removed `ClearPluginLibraries()` from the reload path.

### KTPMatchHandler v0.10.91-0.10.100

| Version | Key Changes |
|---------|-------------|
| v0.10.91 | Idle command hint (120s interval, suppressed during matches) |
| **v0.10.92** | **12 fixes**: OT tech budget persistence, auto-DC pause duration, stale state cleanup, pause warning timing |
| v0.10.93 | OT score display fix (`.score` showed swapped teams), auto-confirm leak |
| **v0.10.96** | **OT timing fix** (timelimit before restart), **roster SteamID exact match**, pause cache monotonic counter, roster buffer overflow fix |
| **v0.10.97** | **Deferred match start** — split ~160ms synchronous work into 3 phases across multiple frames |
| v0.10.98 | Discord channel routing (separate default channel for non-match notifications) |
| v0.10.99 | Deferred pending phase — confirm command frame reduced by ~15-20ms |
| **v0.10.100** | **Say hook fast path** — ordinary chat (~99% of say traffic) returns after reading 4 bytes |

### Fleet-Wide Plugin Code Review (Mar 14)

Systematic security/correctness review of all KTP plugins. Seven plugins scanned clean, three required fixes:

| Plugin | Version | Fixes |
|--------|---------|-------|
| KTPFileChecker | v2.4 | Command injection via player names in `server_cmd("say")`, task ID collision |
| KTPGrenadeLoadout | v1.0.6 | `log_amx` format string vuln, map change state reset, task ID safety |
| KTPPracticeMode | v1.3.1 | Task ID raw player ID → constant offset |

### Other Component Updates (Mar 7-14)

| Component | Version | Key Changes |
|-----------|---------|-------------|
| **KTPAmxxCurl** | v1.3.4-1.3.5-ktp | In-flight AMX validity checks, `CURLOPT_COPYPOSTFIELDS` auto-upgrade for async, deferred cleanup, 64KB response cap |
| **KTPCvarChecker** | v7.18-7.20 | Enforcement accuracy (rate limiter was dropping legitimate events), deferred enforcement queue, Discord task leak (doubled notifications) |
| **KTPAdminAudit** | v2.7.9-2.7.11 | Slot recycling TOCTOU fix (validates SteamID at execution), deferred ban file flush, task ID safety |
| **KTPHLTVRecorder** | v1.5.3-1.5.4 | Second half demo cutoff fix, delayed recording task ID, 35s recovery delay (was 5s), concurrent `.hltvrestart` fix |
| **KTPGrenadeDamage** | v1.0.3 | TK damage incorrectly reduced by damage reduction setting |
| **KTP-ReHLDS** | v3.22.0.908-909 | Spawn sub-phase profiling (`[KTP_SPAWN]`, `[KTP_WRITESPAWN]` log lines for HLTV connect overhead diagnosis) |
| **ktp_discord.inc** | v1.3.4 | Embed description truncation fix (383→2200 char buffer), payload buffer 1024→3072 |
| **KTPHLStatsX** | v0.3.0-0.3.2 | Major performance optimizations (drain-then-process UDP, batched frag UPDATEs, event queue 10→100), per-half stat breakdown, headshot tracking fix |
| **KTPInfrastructure** | v1.4.1-1.5.0 | Variable server count support (`--num-servers`), co-located HLTV (`--with-hltv`), `noatime` mount option, CPU pinning audit fixes |
| **KTPFileDistributor** | v1.1.1 | Shutdown Discord notification now uses embed format |

### Infrastructure Updates (Mar 11)

- **New York & Chicago rebranded** from "KTPSCRIM" to "KTP" with join password "KTP"
- **CPU isolation layout updated** on all baremetals: `isolcpus=2,3,4,5,6,7` (was 2,3,5,6,7), IRQ affinity bitmask 0x03 (was 0x13), game server pinning: 27015→CPU2, 27016→CPU5, 27017→CPU4, 27018→CPU3, 27019→CPU7 (HT-aware)
- All 5 locations rebooted with updated kernel parameters

### Mar 16-19: KTPMatchHandler v0.10.101-0.10.103

| Version | Key Changes |
|---------|-------------|
| **v0.10.101** | **Round-state filtering for HLStatsX** — hooks `RoundState` message to pause DODX stats during freeze periods, eliminating ~1% phantom kill over-counting. Three-layer defense: DODX native, log events, event-driven match context setup with 5s timeout |
| **v0.10.102** | **Periodic score save fix** — 30s repeating task was silently dying after initial one-shot due to SP forward dedup sharing the same forward handle. Split into separate one-shot/repeating functions |
| v0.10.102 | **HLTV recording fix** — Practice Mode hostname suffix broke match ID extraction, causing space in demo filename that HLTV rejected |
| v0.10.102 | **Phase 0 frame stall reduction** — Deferred roster snapshot + hostname update to Phase 2, saving ~25-60ms from `.ready` command frame |
| **v0.10.103** | **Timelimit expiry during ready-up fix** — If `mp_timelimit` expired during pending state, changelevel hook blocked indefinitely; game DLL logged `"TeamName" scored` every frame (~2000 lines/sec). NY1 incident: 35M scored lines, 5.4GB logs over 11 hours. Now detects and allows map change |

### Mar 19: KTP-ReHLDS v3.22.0.910

- Raised `sv_unlagsamples` cap from 16 to 64 (full `SV_UPDATE_BACKUP` frame buffer). At 1000Hz, the old 16-sample cap only covered 16ms of ping history — insufficient for meaningful smoothing
- Scaled jitter detection window in `SV_CalcClientTime()` to match the averaging window

> **⚠️ RETRACTED 2026-06-11:** the premise above was wrong — `cl->frames[]`
> advances per CLIENT PACKET (~100/s), not per server frame, so high sample
> counts meant ~200ms of smoothing and a 20-packet-wide jitter guard that
> silently returned zero lag compensation after a single ping spike. The
> fleet runs `sv_unlagsamples 1` (engine default) since 2026-06-11. Do NOT
> re-raise it based on this entry — see root CLAUDE.md § Lag Compensation
> Config + memory `perf-audit-2026-06-11-findings`.

### Mar 17: KTPHLTVRecorder v1.5.5

- Recording verification with in-game chat feedback after `record` command
- Curl timeout for record commands increased from 5s to 8s
- HLTV API updated to v2.1

### Mar 23-26: KTPMatchHandler v0.10.104-0.10.110

| Version | Key Changes |
|---------|-------------|
| **v0.10.104** | **Periodic score save caused 5.1ms inter-frame gaps** every 30s on isolated CPUs from `log_amx()` filesystem I/O. Increased interval to 120s, skip I/O when scores unchanged |
| **v0.10.105** | **`.scrim` duration menu** — scrims now offer 20min/15min selection like `.12man`. **Queue ID 60s auto-timeout** — prevents stuck 1.3 Community input flow. Discord embed buffer 2048→4096 for 12-player rosters. Negative 2nd-half score clamping. OT round limit (31) now fires match end forward. OT score display fix for Discord embeds. O(n²) `strlen` eliminated in roster builds |
| v0.10.106 | **`msg_TeamScore` early exit** — hoisted `!g_matchLive` guard before all work, eliminating processing during ~9000/sec intermission storm. Removed debug `log_ktp` calls from message handler and Discord routing |
| v0.10.107 | **Score tracking regression fix** — v0.10.106 early exit blocked score tracking during intermission when final TeamScore messages arrive |
| v0.10.108 | Halftime score save fix — removed `update_match_scores_from_dodx()` call (wrong diagnosis, see v0.10.110) |
| v0.10.109 | Diagnostic logging for score tracking (`PERIODIC_SCORE_DEBUG`, `HALFTIME_SCORE_DEBUG`) |
| **v0.10.110** | **Score persistence root cause found** — `dod_get_team_score()` returns 0 in extension mode because DODX's `Client_TeamScore` message handler never receives TeamScore messages. Switched to `dodx_get_team_score()` which reads directly from gamerules memory. Removed incorrect v0.10.108 fix and v0.10.109 diagnostics |

### Mar 24: KTPAMXX v2.7.4

| Fix | Details |
|-----|---------|
| **Message Hook RemoveHook wrong index** | `m_Forwards.remove(forward)` removed at position `forward` (SP forward ID) instead of position `i` (matched entry). Stale forward IDs accumulated every map change cycle |
| **Client_ObjScore stale player pointer** | Static `CPlayer*` used across message parse states without revalidation — freed edict between states corrupted memory |
| **PreThink fallback init removed** | `ENTINDEX()` engine call during early init replaced with hard guard |
| **CPlayer::Disconnect missing edict free check** | `ignoreBots(pEdict)` dereferenced freed entity flags during crash sequences |
| **Event/LogEvent dedup O(n) eliminated** | Added `m_HandleId` field for O(1) handle lookup during dedup |
| **Rank save skipped in extension mode** | Unnecessary file I/O during `ServerDeactivate` |
| **CTaskMngr::startFrame use-after-realloc** | Cached task reference invalidated if callback called `set_task()` → vector reallocation |
| **`dodx_set_stats_paused` native added** | Allows plugins to pause/unpause DODX stats collection (used for round-freeze filtering) |

### Mar 24: KTP-ReHLDS v3.22.0.911-912

**v3.22.0.912 — Profiler overhead optimization:**
- Physics sub-phase timing (separates `pfnStartFrame` from entity loop)
- Per-client send timing (identifies worst client per frame)
- Double `Sys_FloatTime()` in SV_RunCmd boundaries eliminated
- 10 unconditional global writes gated on profiling flag (10,000 cache-dirtying writes/sec eliminated on production)
- Cvar dereference consolidated into single `g_ktp_profiling_enabled` global (10,000+ reads/sec eliminated)
- Steam/frame-end profiling blocks merged (redundant syscall removed)

**v3.22.0.911 — Profiling accuracy + pause efficiency:**
- Pause force-send limited to clients with pending data (was forcing ALL clients every frame at 1000Hz)
- Rate limiter clock source unified (`Sys_FloatTime()` everywhere)
- Double `Sys_FloatTime()` eliminated in per-packet profiling
- String command rate limiter bypass scoped to current client only
- Interframe average now uses dedicated frame counter

### Mar 24: Fleet-Wide Plugin Hardening Pass

Systematic correctness review and performance optimization across all KTP plugins:

| Component | Version | Key Changes |
|-----------|---------|-------------|
| **KTPCvarChecker** | v7.21-7.22 | Trie-based cvar lookup (performance), `rate` locked to exact 100000, `cl_updaterate` max lowered to 120, `ex_interp` range adjusted 0.01-0.05, `lightgamma` floor corrected, `cl_smoothtime` enforcement removed |
| **KTPFileChecker** | v2.5 | Server broadcast no longer reveals file paths/SteamIDs, `.mdl` case-sensitive compare, `MAX_FILENAME_LEN` 64→128, `plugin_end` cancels pending Discord instead of flushing |
| **KTPAdminAudit** | v2.7.12 | Ban duration menu shows wrong name if target disconnected (fixed), `task_flush_banlist` accumulation guard, changelevel hook blocked match-end changelevel during countdown (fixed) |
| **KTPPracticeMode** | v1.3.2 | `client_death` clears noclip engine state, hostname restore race fix (1.5s vs 0.5s), British team support in `.grenade`, repeating task accumulation guard, hostname buffer 64→128 |
| **KTPHLTVRecorder** | v1.5.6 | Delayed stop preservation fix, `init_curl_headers` use-after-free fix, `g_hltvApiUrl` buffer 128→256, dead port validation guard removed |
| **KTPAmxxCurl** | v1.3.6-ktp | `curl_global_cleanup` leak on detach, `curl_formadd` params array bounds fix, `OnAmxxDetach` timeout using wall-clock timing, `CurlReset` re-binding WriteCallback |

---

---

## April 2026 - Engine Threading, JIT Activation, Stack Expansion

**Focus: Engine threading (917-920), JIT re-enablement, three new stack components (KTPAntiCheat / KTPAdminBot / KTPProfileAggregator), AntiCheat integration phases 1-5 + 8.x, ktp_version_reporter shared include rolled out across all 9 KTP plugins.**

The month started with the Apr 14 full-stack optimization pass (work for which was largely completed in March's continuous code-review effort) and ended with the JIT A/B verdict on Apr 25 confirming the fleet-wide debug-flag strip's predicted ATL:27016 σ normalization. Three previously-undocumented components shipped publicly this month — see component-overview sections below the chronological entries.

### Apr 3-5: KTPMatchHandler v0.10.111, KTPPracticeMode v1.4.0, KTPAMXX v2.7.5-2.7.6

| Version | Key Changes |
|---------|-------------|
| **v0.10.111** | **Pause chat relay fix** — `handle_pause_chat_relay` was silently broken by KTPAMXX's command registration dedup system. `registerCommand()` dedup prevents same plugin from registering two handlers for "say" — merged relay logic into `cmd_say_hook` and `cmd_say_team_hook` |
| **KTPAMXX v2.7.5** | **DODX extension mode player init** — `g_pFirstEdict` NULL on first map (SV_ActivateServer hook registered too late). Fallback `INDEXENT(0)` init. Also: `isModuleActive()` gate moved after player init in PreThink |
| **KTPAMXX v2.7.6** | **Discord TLS handshake fix** — 164ms freeze on first Discord notification. Added connection keepalive, DNS caching, prewarm health check |
| **KTPPracticeMode v1.4.0** | **`.grenade`, `.noclip`, explosion refill fixed** — all broken by DODX CPlayer not initializing on first map. `.grenade` now always calls `dodx_give_grenade` + `dodx_set_grenade_ammo` + `dodx_send_ammox` (game removes weapon entity when last grenade thrown) |

### Apr 13: KTP-ReHLDS v3.22.0.913 (Background Steam Thread)

Steam API calls (`SteamGameServer_RunCallbacks` and `GetNextOutgoingPacket`) moved to a dedicated background thread via lock-free SPSC ring buffer. Previously blocked the main game thread for 3-13ms every 100ms. Now `steam=0.000ms` across all servers. Frag update interval increased from 1s to 5s.

### Apr 14: Full Stack Optimization Pass

#### KTP-ReHLDS v3.22.0.914-916

| Version | Key Changes |
|---------|-------------|
| **v914** | **Lag compensation per-packet** — `SV_SetupMove`/`SV_RestoreMove` moved from per-cmd (SV_RunCmd) to per-packet (SV_ParseMove). ~90% reduction in lag comp overhead. **Entity early-break** in SV_SetupMove. **Nodelta during pause** limited to 3 transition frames. **IPTOS_LOWDELAY** always-on. Compiler: `-march=ivybridge -flto -fno-math-errno` |
| **v915** | **REHLDS_OPT_PEDANTIC re-enabled** with wallbang-safe overrides — `shouldCollide()` kept early, `AddToFullPack` pre-filter removed. Enables: iterative BSP traversal, model hash map, delta JIT, challenge circular buffer, usercmd delta caching, packet entity pre-allocation |
| **v916** | Per-frame cvar caching (`sv_timeout`) |

#### KTP-ReAPI v5.29.0.364-ktp

Compiler optimizations: `-march=ivybridge -flto -fno-math-errno`.

#### KTPAMXX v2.7.7-2.7.9

| Version | Key Changes |
|---------|-------------|
| **v2.7.7** | Compiler: `-O3` (was `-O2`), `-march=ivybridge`, `-flto`, `-fno-math-errno` |
| **v2.7.8** | `g_putinserver` vector → `uint32_t` bitmask. Module frame callback length cache. DODX TraceLine `strcmp` → `ALLOC_STRING` integer comparison |
| **v2.7.9** | Event vault pre-allocation (no dynamic growth). `WeaponsCheck` XOR + `__builtin_ctz` (42 iterations → ~2-3). Grenade linked list → 32-entry fixed pool |

#### KTPAmxxCurl v1.3.7-ktp

CMake migration (replaced Premake5). Compiler optimizations. 5 bug fixes: `strcpy` overflow, memory leak catch-all, `SetSock` UB (exception in libcurl callback), `AddCurl` exception safety, detach busy-spin. **Critical: missing `amx_curl_callback_class.cc` in CMakeLists.txt caused `TryInterrupt` undefined symbol — curl module failed to load, breaking all plugins using `ktp_discord.inc`.**

#### KTPMatchHandler v0.10.112

OT scores buffer overflow: `ot_scores[256]` too small for `MAX_OT_ROUNDS` (31) × ~12 bytes = 372 bytes. Increased to 512. Triggered in extended OT (round 16+).

#### KTPFileChecker v2.6

Discord slot reuse race condition (compare authid not slot ID). Log message buffer 256→512. Discord truncation `pos +=` fix.

#### KTPFileDistributor v1.1.2

`ChangeDebouncer` `async void` → `async Task` (crash prevention). `BuildRemotePath` path traversal rejection. `EnsureRemoteDirectoryExists` specific exception catching.

#### Profiler Results (Post-Optimization)

Average frame time: **0.012ms** (12 microseconds). Server FPS: 980+. Steam: 0.000ms. 2 spikes in 5.5 hours (kernel scheduling). Interframe jitter: avg 1.007ms, peak 1.134ms. **98.8% of each frame is idle.**

### Apr 17: KTP-ReHLDS v3.22.0.917 — Spike-Frame Phys Sub-Phase Instrumentation

A 158ms physics-phase spike on ATL2 during a 3-cap of Town Square exceeded what `[KTP_SPIKE]` could break down — the periodic `phys_detail` log was sampled on its own interval, stale by spike time. v917 adds a new `[KTP_SPIKE_PHYS]` alert that fires *on the spike frame* with per-frame sub-phase times: `startframe` (`pfnStartFrame()` work — game-DLL entity spawns, score cascade), `entloop` (per-entity physics iteration), and `paused_startframe`/`paused_hud` (pause-path sub-phases). Next >50ms phys spike points directly at the fix location (game DLL vs engine vs pause state). Fleet promotion on Apr 21 — see infrastructure entry below for the side story.

### Apr 18-19: KTPMatchHandler v0.10.113

Match-start `.ready`/`.rdy`/`.confirm` opcode spikes of 140-162ms were traced to synchronous `exec_map_config()` + `mp_clan_restartround 1` + `server_exec()` firing inside the chat-command handler's return path. v0.10.113 deferred these to a +0.05s task (`task_apply_match_config_and_start`) — config/restart work runs on its own frame instead of blocking the player's packet dispatch. Worst case (NY1 15:10, NY1 16:23) collapsed to single-digit ms. **Caveat: the defer only covers `will_start=1` match-start path; mid-count `will_start=0` `.rdy` spikes persisted, prompting the 0.10.114 probe a week later.**

### Apr 20: KTPPracticeMode v1.4.1

Diagnostic `log_amx` instrumentation in `dod_grenade_explosion` and `cmd_grenade` capturing entry state (`id / wpnid / practice-mode-flag / connected / alive`) and refill returns (`dodx_give_grenade()`, `dodx_set_grenade_ammo()`, `dodx_send_ammox()`, computed `ammoSlot`). Targets the 2026-04-17 ATL2 grenade auto-refill regression whose cause is still unknown. Low log volume (only fires during active practice mode), kept permanent for any future practice-mode diagnostic. Awaiting next organic reproduction.

### Apr 18-21: Fleet Configuration & `.new`-swap Implementation

| Change | Detail |
|---|---|
| **`sv_allow_dlfile "0"` fleet-wide** | Eliminates 2+-second server-wide stall when clients fall through FastDL to engine-fragment download. ReHLDS's reject-before-file-read short-circuit was already coded; just unreachable at default `1`. Applied to `dodserver.cfg` on all 25 instances. |
| **`ktp-scheduled-restart.sh` `.new`-swap finally implemented** | Documented in CLAUDE.md / MEMORY.md since February but **never actually shipped** — both deployed script + `.example` template had no `.new`/`swap`/`mv` handling. Discovered when the 917 engine `.new` files staged 2026-04-20 did not activate at the 03:00 ET 2026-04-21 auto-restart despite a clean restart run. Fix landed `e0d571c` (Apr 21 17:00 ET) — actual swap block between stop and start phases, covering `serverfiles/*.new`, `addons/ktpamx/dlls/*.new`, `addons/ktpamx/modules/*.new`. Verified Atlanta first, then rolled to Dallas/Denver/NY/Chicago sequentially. |
| **917 fleet promotion (Apr 21-22)** | All 24 active instances confirmed on 917 post-rollout (Chicago 27019 remains intentionally `.ktp-disabled`). |

### Apr 22: HPAK Crash Day (KTPAMXX v2.7.12 + KTP-ReHLDS v3.22.0.918) — Major Incident

Starting ~15:40 ET, a fleet-wide segfault pattern emerged that consumed most of the day to root-cause and fix. In parallel, the engine threading work filed as a 917 follow-up shipped as 918.

**Symptom:** 15 segfaults across the fleet over two days (ATL ×4 on Apr 21 evening, DEN ×1 on Apr 19, **NY ×10 on Apr 22**). Pattern: `Segmentation fault (core dumped)` correlated with heavy player traffic. Bug only triggers on populated servers — NY took the hit because NY was the active-play host. Multiple instances crashed in minutes-wide clusters, not random.

**Pre-condition: enabling core dumps fleet-wide.** Apport had been intercepting cores via its pipe handler (`kernel.core_pattern = |/usr/share/apport/apport ...`) and silently dropping them. Set `kernel.core_pattern = /tmp/core.%e.%p.%t` runtime + persistent `/etc/sysctl.d/99-ktp-coredump.conf` on all 5 hosts (Denver was already correct; ATL/DAL/NY/CHI had apport drift). RLIMIT_CORE was already unlimited via systemd. **First useful core dumps captured within hours of enablement** — led directly to the 2.7.12 root-cause diagnosis.

**Diagnosis path:** First three crashes caught (ATL 27017 @ 20:06, ATL 27015 @ 20:11, ATL 27019 @ 20:13), 240-280 MB cores. `gdb` resolved through `CSPForward::execute` at `KTPAMXX/amxmodx/CForward.cpp:305`. Main thread inside libc's SSE-accelerated `strlen()` (`movdqu (%edi), %xmm1`) on bogus pointer `0x3f145406` — classic use-after-free.

**Root cause:** `CForward::execute()` and `CSPForward::execute()` had a defensive check that rejected `NULL` and pointers `< 0x1000` before calling `strlen()` on `FP_STRING` / `FP_STRINGEX` parameters. Caught NULL/zero-page derefs, but not high-value integers reinterpret-cast as pointers. A scheduled AMX task fired after its backing memory was freed — the cell value stored in task params became an arbitrary integer like `0x3f145406`, passed the `< 0x1000` check, pointed to an unmapped page, and libc's `strlen` SSE loop SEGV'd on the first 16-byte load.

**Fix (KTPAMXX 2.7.12):** New helper `amxx_is_string_ptr_readable()` combines old NULL/low-page check with `mincore()` syscall to verify the containing page is mapped. Applied to all four vulnerable sites (2 read paths + 2 `FP_STRINGEX` writeback paths — the writeback paths were caught by the `ktp-code-review` agent during review; initial patch only covered reads). Built, staged, deployed fleet-wide in ~5 min via parallel SSH rollout. **0 crashes** in the following hour of heartbeat monitoring.

**`sv_send_logos "0"` hotfix** (parallel theory before gdb landed on CForward): kept in place even after the AMXX fix as defensive hardening — HPAK code path still has a latent bug whose repro path we now have core-dump infrastructure for. The 2.7.12 fix proved the real crash was AMXX, but `sv_send_logos 0` stays cosmetic-only (players don't see each other's spray/logo decals; competitive play unaffected) until the HPAK path soaks clean post-920.

**KTP-ReHLDS 3.22.0.918 — engine threading (canary on ATL 4+5):**

| Change | Detail |
|---|---|
| **E1: Steam 5s-timer → background thread** (`sv_steam3.cpp`) | The 5s block calling `SetMaxPlayerCount`/`SetServerName`/`BUpdateUserData` etc. inline on the game frame was the residual `steam=3-6ms` spike source post-913 (~26% of fleet `[KTP_SPIKE]` volume). Now: main thread snapshots state (~20µs), atomic flag flips, existing Steam background thread picks up within its 50ms cycle and publishes off-main. Critical `ktp-code-review` catch: must use `steam->BUpdateUserData()` directly — the `REHLDS_FIXES` helper routes through `m_Steam_GSBUpdateUserData` hookchain that plugin handlers (KTP-ReAPI → AMXX) use main-thread-only state in. |
| **E2: Con_DebugLog persistent fd** (`sys_dll.cpp`) | Stock opened/wrote/closed `qconsole.log` per log line (3 syscalls per line). Under `-condebug` + `mp_logecho=1` (default for HLStatsX tailing), hundreds of `open`/`close` per second. Now caches `FILE*`, flushes after each write to preserve tail-reader semantics. Incidentally fixes a latent Windows crash from missing `_open` return check. |
| **ProcessConsoleInput rate-limit** (`sys_ded.cpp`) | Stock called `ProcessConsoleInput` every iteration (→ `kbhit()` → `select()` syscall per iter). Under never-sleep pingboost (100k+ iter/sec), that syscall alone was **57% of CPU in kernel mode**. Rate-limited to 50ms (20 polls/sec) via `CLOCK_MONOTONIC`. Post-fix CPU split on never-sleep mode went from 43% usr / 57% sys → 99.67% usr / 0.33% sys — **172× syscall reduction**. Admin console latency unchanged in practice; pingboost 2-3 unaffected (already slept between iterations). |
| **Host_FilterTime 1ns tolerance** (`host.cpp`) | Check is now `(1.0/fps) - 1e-9 > realtime - oldrealtime` instead of bare `1.0/fps > ...`. IEEE 754 double comparison on the boundary was non-deterministic, rejecting ~2% of frames and capping FPS at ~979 in abs-time sleep experiments. 1ns tolerance beats the boundary while staying 1000× smaller than the double-precision ulp at 0.001. |
| **New `-pingboost 4` (never-sleep mode)** | Opt-in cmdline. `Sys_Sleep` is a no-op, main loop spins, `Host_FilterTime` rate-gates frame execution. Reaches true ~999 fps at `sys_ticrate 1000` (vs the ~977 structural ceiling of `-pingboost 2`) at the cost of **100% CPU per instance**. Existing `-pingboost 2` stays fleet default (977 fps at ~1-3% CPU is the better trade for most deployments). |
| **Abs-time `Sleep_BusyWait` (dropped)** | Full day of iteration on a hybrid mode targeting the 1000Hz grid precisely (sleep most of ms, busy-wait last ~200µs). Three attempts topped out at ~979 fps due to a kernel HZ-tick edge case in `nanosleep` causing occasional multi-millisecond overshoots. Dropped from the release. |

918 staged fleet-wide as `.new`; 23 instances pending 03:00 ET auto-swap. ATL 27018 + ATL 27019 activated immediately with `-pingboost 4` set in their dodserverN.cfg overrides — observable 100% CPU per instance confirmed.

### Apr 22: Fleet Kernel Upgrade — 6.8.0-100/101-lowlatency → 6.8.0-110-lowlatency

All 5 game hosts rebooted onto 6.8.0-110-lowlatency (skipped -106/-107). Each host carried 56-69 pending package upgrades; `apt-get upgrade` applied all of them before the reboot. Post-reboot state preserved correctly: CPU governor `performance`, isolation cmdline (isolcpus / nohz_full / rcu_nocbs / max_cstate=0 / mitigations=off), `ktp-chrt.timer` reapplied SCHED_FIFO 50 within 5 min, all sysctls held, all rc.local tuning held.

**Operational quirks surfaced:** Chicago VPS took ~30 minutes to return (vs ~60s baremetals — root cause not confirmable without Akamai console access; eventually came back cleanly). Port 27015 monitoring-lock missing after reboot — `dodserver monitor` treats it as "intentionally stopped" because the lockfile isn't recreated through any non-START/RESTART path. Workaround: manual `./dodserver start` on 27015 after each reboot. Atlanta `6.14.11-psycachy` test kernel purged (was sitting at top of GRUB submenu by version sort; explicit `grub-set-default "1>2"` used during reboot to force -110-lowlatency entry).

### Apr 23: KTP-ReHLDS v3.22.0.919-920, KTPAMXX v2.7.13, KTPMatchHandler v0.10.114, JIT Activation

Single bundled release for the 03:00 ET 2026-04-24 auto-swap.

**KTP-ReHLDS 3.22.0.919 (frame-efficiency + Linux NET_ThreadMain + Stage C experimental):**
- Hoisted `host_limitlocal.value` + `sv_failuretime.value` out of `SV_SendClientMessages` per-client loop (cvars only change via console, never mid-frame). ~120ns/frame eliminated.
- Replaced 4 sub-function reads of `ktp_profile_frame.value` with the `g_ktp_profiling_enabled` global already written once per frame in `SV_Frame_Internal`.
- Replaced 4 `Cvar_VariableString("hostname")` hash-table lookups with direct `host_name.string`.
- HPAK `FS_Read(NULL)` defensive fix (`hashpak.cpp`) — dormant SEGV-on-OOM site. Trivial one-line `break` in alloc-failure branch.
- Linux `NET_ThreadMain` port (`net_ws.cpp`) — ports the Windows `-netthread` receive-pre-queue thread to Linux. Off by default; mutually exclusive with `-pingboost 3`. Not flipped on for any fleet instance yet — profiler hasn't shown read-phase burst-traffic spikes that would motivate enabling it.
- **Stage C main-loop frame-boundary rewrite (experimental, opt-in `-absgrid`):** `clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME)` against a 1ms grid. Goal: ~999 fps at baseline CPU. Result on ATL 27019 canary: **643 fps / 1.53ms interframe / recurring 5ms peaks** at 2.8% CPU — kernel waking the SCHED_FIFO thread at ~500µs avg latency from hrtimer-fire even on isolcpus + nohz_full + max_cstate=0. Idle-CPU exit latency appears to be the floor. Gated behind `-absgrid` so plain `-pingboost 2` keeps the proven `Sleep_Select` path; research code retained for future kernel experiments.
- **Canary topology:** ATL 27018 → reverted to fleet-default `-pingboost 2`. ATL 27019 → `-absgrid` research slot. NY 27019 → new perpetual `-pingboost 4` canary (never-sleep, 999 fps @ 100% CPU).

**KTP-ReHLDS 3.22.0.920 (HPAK defensive hardening):** 3 SEGV-on-OOM sites in HPAK customization-download path, all guarded under `REHLDS_FIXES`:
- `Mem_ZeroMalloc` NULL-safety (`mem.cpp`) — universal fix benefiting every caller across the engine
- `HPAK_GetDataPointer` directory alloc NULL guard (`hashpak.cpp:104-117`)
- `HPAK_ResourceForHash` directory alloc NULL guard (`hashpak.cpp:666-677`)

5 more `Mem_Malloc + Q_memset` patterns in less-hot upload/admin paths held for follow-up release (now landed as 921 — see below).

**KTPAMXX 2.7.13 — DODX forwards-stall fix (Jimmy's PR #4):** @JimmyLockhart65616 filed a clean diagnosis: every DODX-forward-based event (kill, damage, prone_change, player_spawn, player_team_change, flag_captured, player_score) had been going silent within hours of restart on all three matchday hosts (DEN5, ATL1, NY1). Root cause: two chained bugs in `modules/dod/dodx/moduleconfig.cpp`:
- **Bug #1** — `DODX_OnSV_ActivateServer:1160` used `!FNullEnt(pWorld)`. `FNullEnt(edict 0)` returns TRUE because edict 0 IS the world entity. Same issue 2.7.5 fixed in `DODX_SetupExtensionHooks` but missed here. Every map change's `g_pFirstEdict` init was silently skipped.
- **Bug #2** — `DODX_OnPlayerPreThink:947-948` had no recovery. 2.7.4 replaced the `ENTINDEX()`-based fallback with a hard `return`. Once per-map init failed for any reason, forwards stayed silent until plugin re-attach.

Live `restart` on ATL1 confirmed attach-time fallback was what propped the stack. **Side-effect:** HLStatsX rankings and match records from 2026-04-05 (when 2.7.5 introduced the incomplete FNullEnt fix) through 2026-04-24 activation are incomplete. Events were never logged in the first place — no DB fix-up planned. Operator awareness item.

**KTPMatchHandler 0.10.114 — cmd_ready 5-helper profiling probe:** Fleet telemetry since 2026-04-17 showed recurring ~163ms `cmd_ready` spikes on the `will_start=0` mid-count `.rdy` path (6 events on NY2/NY3 clustered at 163ms ± 0.5ms). 0.10.113's defer only covered `will_start=1`. Source audit ruled out Discord; tight clustering smelled like a deterministic blocking call. Split `cmd_ready` into 5 public helpers (`_cmd_ready_prechecks`, `_cmd_ready_identity`, `_cmd_ready_track_captain`, `_cmd_ready_update_roster`, `_cmd_ready_broadcast`) so AMXX's function-level profiler names the culprit stage on the next spike. **Important caveat:** AMXX's per-function profiler is gated on the `debug` flag — which got stripped fleet-wide tonight. The probe's per-helper warnings won't fire post-JIT-restart unless `debug` is selectively re-added.

**Fleet-wide JIT activation (`debug` flag stripped):** Discovered from `modules.cpp:191-256` that **`debug` on a plugin in plugins.ini explicitly clears `AMX_FLAG_JITC`**. Every KTP plugin had `debug` set — ~9 plugins × 25 instances = 225 instances of interpreted Pawn execution on hot paths since extension mode was enabled. Python+SFTP regex transform stripped `debug` from every KTP plugin line in `plugins.ini` across all 25 instances, preserving `KTPHudObserver.amxx debug` on the three instances running cadaver's canary plugin (ATL:27015, DEN:27019, NY:27015). Backups saved as `plugins.ini.debugflag-bak-20260423` on each instance. Activates at 3 AM ET 2026-04-24 (KTPAMXX re-reads `plugins.ini` on server start).

**Pre-JIT FPS baseline captured:** 127,543 `[KTP_PROFILE]` fps samples → `KTPInfrastructure/monitoring/fps_baselines/fleet_fps_2026-04-23_pre-jit.json` for tomorrow's A/B comparison. Fleet p50=978.2, σ=13.65. Per-host σ tightest → widest: Dallas 7.96, Denver 8.89, NY 10.31, Chicago 15.09 (VPS floor), Atlanta 17.44 (inflated by ATL:27016 at σ=30.74 min=842 — flagged anomaly).

**`ktp-scheduled-restart.sh` — `-monitoring.lock` belt-and-suspenders fix:** Long-tracked TODO. After full OS reboot, port 27015 needed manual `./dodserver start` because LinuxGSM's monitor cron treated it as "intentionally stopped" when the lockfile was absent. Root-caused: `command_stop.sh:402` deletes the lockfile when `firstcommandname == "STOP"`; `command_start.sh:170` creates it only when `firstcommandname == "START" | "RESTART"`. Any out-of-flow start path leaves the lockfile absent. **Originally presented as 27015-specific but is port-agnostic** — found DAL:27015 in the broken state mid-investigation. Patched all 5 hosts: after each successful start, create `$SERVER_EXEC-monitoring.lock` with `date +%s` if missing. Idempotent.

### Apr 23 (later): Held-on-main engine releases (not fleet-deployed)

Two cleanup releases landed on `main` but were deliberately held out of the 24h bundle. Both committed; bundle into a future fleet release once 920 has soaked clean.

| Version | Detail |
|---|---|
| **3.22.0.921** | 5 additional `Mem_Malloc + Q_memset` SEGV-on-OOM sites in `hashpak.cpp` (less-hot upload/admin paths) hardened the same way as 920. Committed as `8f616a6`. |
| **3.22.0.922** | Two zero-risk `SV_Physics` entity-loop micro-hoists: `gGlobalVariables.force_retouch` cached as `const bool` before the loop; `g_psvs.maxclients` cached as `const int`. ~5-15ns/entity/frame, ~0.4-1.2µs/frame at peak. Free cleanup matching the existing 916/919 hoist patterns. Committed as `2c9f26c`. |

### Apr 24 03:00 ET — FLEET-WIDE OUTAGE from `.new`-swap losing `+x` bit

**Total outage window: 5h45m.** 03:00-08:48 ET — fleet down. Matchday hours unaffected (overnight low-traffic), but any player attempting to connect saw all 24 active KTP instances offline.

**Root cause:** `ktp-scheduled-restart.sh`'s `.new`-swap loop did `mv -f "$new_file" "$target"`. SFTP uploads with default umask produce mode `644` (no execute bit). When `mv -f` moves a 644 file on top of a 755 target, Linux preserves the source's permissions — post-swap target is 644. `hlds_linux` and `engine_i486.so` silently lost `+x`. `./dodserver start` runs `./hlds_linux` under `tmux`; with no `+x`, exec fails with `Permission denied`, tmux exits immediately, LinuxGSM reports the opaque `Unable to start NOT SET` error.

The bug was **latent in the swap script from 2026-04-21** (commit `e0d571c`). Three weeks of testing wouldn't have caught it because the failure required SFTP-uploaded files (umask 022) AND the auto-swap path running. First "cold boot" of both conditions was this morning.

**Detection was the second failure.** Monitor cron produced ~30,000 "FAIL to start" log lines over 5h45m — none surfaced as alerts because Netdata / Discord plumbing was only wired to server-crash signatures, not to LinuxGSM start-failure signatures. A "servers running count != expected" heartbeat would have caught this within minutes.

**Fix:** Permanent `chmod +x "$target"` after every successful swap in `ktp-scheduled-restart.sh`. Idempotent. Deployed in-place on all 5 hosts ~09:00. Backup saved as `.chmod-patch-bak-20260424`. Canonical source committed as `14e7612`.

**Recovery confirmed:**
- All 24 active instances running
- CPU pinning correct (applied by `ktp-chrt.timer`'s 5-min reconciliation)
- All binaries showing SCHED_FIFO priority 50
- Startup logs show `KTPMatchHandler version=0.10.114` (probe deployed)
- Plugins loading cleanly with **no `[performance issue]` warnings** — confirming JIT activation worked (Debugger hook absent = JIT active)
- Engine banner shows `Version: 3.22.0.917-dev+m` due to pre-existing `appversion.h` auto-version drift (git commit count ≠ CHANGELOG version) — binary is 920, cosmetic mismatch only

### Apr 24: KTP-ReHLDS v3.22.0.923 — HLTV `spawn` opcode alert suppression (held on main)

With fleet back up, revisited the long-standing HLTV `spawn` opcode overhead TODO. Telemetry: HLTV SPAWN n=7591 p50=4.818ms, real-client SPAWN n=522 p50=1.812ms — ~2.6× asymmetry, fully localized to `WriteSpawn`'s `gamedll` phase (HLTV p50=3.197ms vs real p50=0.062ms — ~50× asymmetry). Real clients hit a short-circuit inside `dod_i386.so`'s `WriteSpawn` callback while HLTV takes the iterate-all-entities slow path. Game-DLL cost, not KTP-controllable; HLTV legitimately needs all-entity state for demo recording.

Suppress the `[KTP_OPCODE]` alert at the threshold check when `cl->proxy != 0` AND command starts with `"spawn "`. Preserves real-client alerts; kills the noise floor (historically ~85% of all `KTP_OPCODE` alert volume was HLTV spawn). Fine-grained `[KTP_SPAWN]` / `[KTP_WRITESPAWN]` phase profiling continues for both. Committed `a2fc6ce`.

### Apr 24: Fleet Health Heartbeat Alerter (response to outage)

Direct response to the 5h45m undetected outage. `ktp-fleet-health.sh` runs as 1-minute cron on each of the 5 hosts. Checks `pgrep -c hlds_linux` against expected count (5 baremetals, 4 Chicago via per-host `~/.ktp-fleet-health/config.sh` override). Single Discord alert on state transitions — one 🚨 red DEGRADED post when count drops below expected for 3 consecutive minutes (debounce), one ✅ green RECOVERED post when it returns. Silent otherwise.

**Design choices:**
- Posts direct to test webhook channel, not via Cloud Run relay — one fewer dependency in the alert path. If the relay goes down (the scenario we care about most), alerts still fire.
- State in `~/.ktp-fleet-health/state` (per-host). Hysteresis: outages produce exactly one DOWN + one UP alert.
- `set -euo pipefail` + graceful curl-failure handling — alerter can't take down a host even if Discord is unreachable.

Verified end-to-end. Committed `535f005`. **Would have caught today's outage within ~3 min, vs the 5h45m actual window.**

### Apr 24-25: KTPAntiCheat Integration — Phases 1-5 shipped

Full plan + per-phase contracts live in the private KTPAntiCheat repo. Eight phases scoped 2026-04-24, of which phases 1-5 + 8.x shipped within ~36 hours.

Touchpoints visible in this repo's history:
- **KTPMatchHandler 0.10.115** ships the game-server-side integration handshake — match-start and match-end announcement to the AC backend, idempotent on re-fire, gated on `<configsdir>/ac.ini` so the integration is a silent no-op when absent. Internals of what AC does with those signals stay in the private repo.
- **Discord Relay 1.0.1** gained `allowed_mentions` passthrough to support the verdict-embed flow.

Subsequent rollout phases are time- and adoption-gated; detail lives in the private repo (deliberately not documented here — public repo).

### Apr 25: KTPAdminBot Phase 8 — `/ops` Cog

The Discord admin bot's `/ops` command surface (fleet-ops tooling) shipped over five sub-phases on the same day. Implementation lives in the private KTPAdminBot repo.

The one piece visible in this repo's history: a **new metrics aggregator daemon** (KTPProfileAggregator, also private) that paramiko-tails 25 game-server logs every 5 min, parses `[KTP_PROFILE]` and `[KTP_SPIKE_*]` lines, and persists to a new `ktp_telemetry_metrics` + `ktp_telemetry_watermarks` MySQL schema. First cycle clocked at ~4.1s, 24/24 servers ingested cleanly. Distinct from the existing `ktp-server-monitor.py` cron — that polls RCON `stats`; the aggregator handles engine-emitted profiler data.

### Apr 25: JIT Activation A/B Verdict

Post-JIT FPS snapshot pulled after a full matchday of stable post-restart operation. Snapshots at `KTPInfrastructure/monitoring/fps_baselines/fleet_fps_2026-04-23_pre-jit.json` (n=127,543) and `fleet_fps_2026-04-25_post-jit.json` (n=138,069). Pull/diff scripts persisted at `pull_fleet_fps.py` + `diff_fleet_fps.py`.

**Headline results:**
- **ATL:27016 normalization confirmed** — σ 30.70 → **6.90** (4× tighter), min 842.0 → 904.7. The pre-JIT anomaly WAS interpreted Pawn tail latency. Explicit test target.
- **Per-instance σ compression on 22 of 24 instances** (-0.4 to -2.0 typical). Per-host σ down on Dallas, Denver, Chicago.
- **Fleet p50 unchanged** (978.2 → 978.3) — JIT didn't move the median. Median fps was already at the structural Sleep+work cap, not Pawn execution cost.
- **Tail bias improved:** % in NFO window 998-1002 went from 3.17% → 4.34% (+37% relative).
- **cmd_ready 163ms spike rate dropped to zero** in same-day grep (~20h of current logs). Pre-JIT averaged ~1.5 events/day on NY2/NY3.

Two outliers explained as non-JIT events: NY:27015 mostly down (n=861 vs 5561 expected), ATL:27019 had a localized live-match event in hours 18-19 EDT.

**Custom-kernel research does NOT de-escalate** per the runbook gate (post-JIT p50 ≥ 990 / σ ≤ 8 not met). Kernel TODO stays at Medium priority — proceed to Experiment A (preempt=full on ATL baremetal canary) when a maintenance window opens.

### Apr 25: KTPInfrastructure PRs #3, #4, #5 — All Merged

Three PRs from @JimmyLockhart65616 landed Saturday evening:

- **#4** (`0ba7a77`) — `lint-configs` Makefile target rejects builds when `debug` is present in `config/online/plugins.ini`. Future-proofs JIT activation against regressions on plugins.ini edits.
- **#5** (`5598657`) — `make build-data` target wraps the HUD Observer compose build with `DOD_HUD_PATH` validation + optional `NO_CACHE=1`.
- **#3** (`7a758b3`) — local-prod parity: plugin/module load order matches Denver 5/ATL1:27015/NY1:27015, runtime base 22.04→24.04 (matches fleet glibc 2.39), stock-plugin compile pipeline, Makefile QoL. Required Makefile rebase against current main after #4 + #5 landed (single conflict on local-development `.PHONY` line; combined `build-data` + `refresh`/`refresh-local` cleanly).

### Apr 25: KTPAdminBot 0.8.0/0.8.1 — Multi-Guild Routing

Single Discord application token now serves multiple guilds with per-guild command-set filtering. Primary guild: full `/ac` + `/ops`; secondary guild: `/ops` only. Discord allows the same bot user across multiple guilds simultaneously — one process / one gateway / one token.

`Config.guild_id` / `admin_role_id` scalars replaced by `tuple[GuildConfig, ...]`. Helpers `role_for_guild(gid)` / `mode_for_guild(gid)` / `primary_guild`. `bot.py setup_hook` iterates guilds, uses `tree.copy_global_to(guild)` + (for ops-only guilds) `tree.remove_command("ac", guild=...)` before per-guild `tree.sync()`. Internal verdict-embed HTTP listener starts only when a full-mode guild is configured. `interaction_check` in cogs routes role lookup through `cfg.role_for_guild(interaction.guild_id)`. Legacy `GUILD_ID` / `ADMIN_ROLE_ID` accepted as back-compat aliases.

0.8.1 fixed a dataclass field-ordering crash from `default_factory=tuple` on a non-defaulted-fields-after dataclass. Deployed to a second guild (579024206931689482) for league-side fleet ops without exposing AC admin tooling.

### Apr 25: KTPAntiCheat README Rewrite

README was last meaningfully updated for v0.3.1 — since then 8 integration phases shipped (Gaps 1-4, Phases 5/8.2/8.3/8.4) all in the API (now 0.3.10) and KTPAdminBot. README still told admins to curl 4 endpoints and didn't mention the bot. Net change: +135 / -33. Committed `a0e135e`.
- Restructured for the bot-first admin workflow; per-section detail lives in
  the private repo's README (deliberately not enumerated here — public repo).

### Apr 25: ktp_version_reporter Shared Include + 9-Plugin Onboarding

First concrete deliverable for the test infrastructure plan + Tier 2 prerequisite (per-plugin live-version reporter that integration tests can assert against).

**`KTPAMXX/plugins/include/ktp_version_reporter.inc`** (391e5389): provides `KTP_RegisterVersion(name, version)` for plugins to call from `plugin_init()`. The first-loaded plugin registers the `amx_ktp_versions` rcon command (ADMIN_RCON); subsequent plugins append their info to a shared localinfo registry. When invoked, prints fixed-width table: name | version | git SHA | build time (UTC). Build-time SHA + UTC timestamp injected via temp `build_info.inc` written by each plugin's compile.sh from `git rev-parse --short HEAD` + `date -u`. Include uses `#tryinclude` with "unknown" fallback for off-toolchain compiles.

**Onboarding side-effect: discovered + fixed compile.sh `cp -r` nesting bug.** `cp -r src dst` semantics — when `dst` already exists, source contents get copied INTO it as `dst/src/...`. First-run worked; re-runs accumulated `/tmp/ktpbuild/include/include/...` layers. Pre-existing files survived from the first-ever run; new shared includes added later landed at the nested path and were invisible to amxxpc. Fixed via `rm -rf "$TEMP_BUILD"` before `mkdir`. Affected scripts: 4 patched (3 already had `rm -rf`, 2 used `mktemp -d` so unaffected).

**Adopters:** all 9 plugins onboarded in one evening. Three plugins also had non-standard version constants standardized to `PLUGIN_NAME` / `PLUGIN_VERSION` / `PLUGIN_AUTHOR` for fleet-wide convention consistency.

| Plugin | Old version | New version | Constants standardized |
|---|---|---|---|
| KTPMatchHandler | 0.10.115 | **0.10.116** | (already standard) |
| KTPHLTVRecorder | 1.5.6 | **1.5.7** | (already standard) |
| KTPCvarChecker | 7.22 | **7.23** | `gs_PLUGIN`/`gs_VERSION`/`gs_AUTHOR` → `PLUGIN_NAME`/`PLUGIN_VERSION`/`PLUGIN_AUTHOR` |
| KTPFileChecker | 2.6 | **2.7** | `gs_PLUGIN`/`gs_VERSION`/`gs_AUTHOR` → `PLUGIN_NAME`/`PLUGIN_VERSION`/`PLUGIN_AUTHOR` |
| KTPAdminAudit | 2.7.12 | **2.7.13** | `PLUGIN`/`VERSION`/`AUTHOR` → `PLUGIN_NAME`/`PLUGIN_VERSION`/`PLUGIN_AUTHOR` |
| KTPGrenadeDamage | 1.0.4 | **1.0.5** | (already standard) |
| KTPGrenadeLoadout | 1.0.7 | **1.0.8** | (already standard) |
| KTPPracticeMode | 1.4.1 | **1.4.2** | (already standard) |
| KTPScoreTracker | 1.1.0 | **1.1.1** | (already standard) |

All 9 .amxx files compile clean and are locally staged. Production deploy held to **Monday 2026-04-27** (post-playoffs) per "no fleet changes during matchday" discipline.

### Apr 25: Operational Infrastructure

| Item | Detail |
|---|---|
| **Fleet Drift Audit** | Weekly cron on data server (`/etc/cron.d/ktp-fleet-audit`, Mon 05:00 ET) SSH-fans-out `fleet-drift-snapshot.sh` to all 5 game hosts and compares against declarative expected-state files in `KTPInfrastructure/provision/`. Five categories: sysctl, binary md5, GRUB cmdline, systemd timers, rc.local. Per-host `sample_port` field lets the audit sidestep canary-occupied ports. Discord alerts state-diff based (transitions only). SSH auth migrated to dedicated ed25519 key — the shared pre-rotation dodserver password is out of audit config entirely. |
| **Data-Server Health Check** | Hourly cron (`/etc/cron.d/ktp-data-server-health`) checks `mysql`, `nginx`, `hlstatsx`, `hltv-api`, `ktp-ac-api`, `ktp-file-distributor`, `hltv-restart.timer`, plus HLTV instance count (expected 24). State transitions only. |
| **HLTV Demo Retention** | `/usr/local/bin/ktp-demo-retention.sh`. Tiered: `ktp/` + `draft/` 180 days, `12man/` + `scrim/` 90 days. Daily delete cron 04:30 ET; weekly preview alert Sunday 09:00 ET listing upcoming deletions to both KTP + 1.3 Discord channels. |
| **KTPAMXX CI Replaced** | Master CI had been red since 2026-04-16 — `support/checkout-deps.sh` cloned stock `alliedmodders/hlsdk` but `meta_api.cpp` references `pfnClientCvarChanged` which exists only in `afraznein/KTPHLSDK` fork. Replaced with KTP-native workflow on `ubuntu-22.04` (glibc 2.35 floor for backward-compat), single-compiler `gcc-9-multilib`, explicit KTPHLSDK + metamod-hl1 + ambuild checkouts. Windows MSVC dropped (no Windows build); clang-11 dropped (incompatible with `-m32 -flto` on 22.04). |
| **cadaver collaborator access** | New `cadaver:hud` account with NOPASSWD sudo provisioned across all 6 KTP hosts. Enables external collaborator deploys of `KTPHudObserver.amxx` companion plugin. |

### Apr 25: Investigations Closed

**Denver microcode — not actionable.** Denver's ~1.5× steam-phase spike magnitude vs Atlanta was hypothesized to stem from stale CPU microcode (`0x21` Denver vs `0x28` Atlanta). Tested 2026-04-22 by full reboot after confirming `intel-microcode` was already at latest Ubuntu version: microcode remained `0x21`. Ubuntu's package does not contain a newer blob for Intel Xeon E3-1240v2 (Ivy Bridge). Hardware-generation-inherent (Ivy Bridge vs Haswell), not fixable via standard channels.

**`ktp-scheduled-restart.sh` race condition — fixed.** First-instance (`27015`) startup was racing its own STOP phase's async tmux kill-session teardown with the subsequent START, producing "NOT SET is already running" aborts. Polling loop after `./dodserver stop` waits for both `hlds_linux` processes and all `dodserver` tmux sessions to terminate (max 30s) before firing the next `start`. Also consolidated: Chicago's previously-custom restart script (port 27019 exclusion) replaced by the generic one + per-instance `.ktp-disabled` marker mechanism.

---

## New Components — April 2026

Four new components joined the stack this month, forming a separate admin/ops tier alongside the game stack. The first three (KTPAntiCheat, KTPAdminBot, KTPProfileAggregator) are **private repos** — what follows is a high-level acknowledgement; design and implementation specifics live in their respective in-repo documentation. The fourth (KTPCrashReporter) ships in-tree under this repo's `monitoring/crashreporter/`.

A friendly-alias convention (`ATL1...CHI5`) was formalized this month across the admin tier — already in use in `match_id` formatting, adopted as the canonical embed key for KTPCrashReporter, and migrating into KTPAdminBot's `/ops` cog. See `TECHNICAL_GUIDE.md` § Admin Infrastructure for the mapping.

### KTPAntiCheat

League anti-cheat for competitive Day of Defeat. **100% VAC-safe**, runs as a desktop client on Windows + macOS (Avalonia UI) with a server-side ASP.NET Core API on the data server. The API exposes integration endpoints used by KTPMatchHandler (match announce/end, session upload metadata) and admin endpoints used by KTPAdminBot. Methodology and detection mechanisms live in the private KTPAntiCheat repo.

### KTPAdminBot

Discord admin/ops bot. Python / discord.py 2.x. Runs on the data server as a systemd service. Surfaces `/ac` (anti-cheat admin) and `/ops` (fleet operations) slash-command groups, gated on a configurable admin role. Multi-guild routing (0.8.0+) lets one bot user serve multiple guilds with per-guild command-set filtering. Implementation specifics are in the private KTPAdminBot repo.

### KTPProfileAggregator

Metrics aggregator daemon on the data server that paramiko-tails fleet console logs every 5 min, parses engine-emitted profiler data, and persists to MySQL for downstream querying. Implementation lives in its private repo. Distinct from the existing `ktp-server-monitor.py` cron (which polls RCON `stats` per minute) — different data source, different cadence.

### KTPCrashReporter

Per-host inotify watcher + `gdb` wrapper that turns kernel-emitted core dumps into Discord embeds in `#ktp-crashes`. Lives in this repo at `monitoring/crashreporter/` (no separate repo — it's a thin gdb wrapper with no IP worth siloing). Runs as `ktp-crashreporter.service` on every game host, fleet-deployed 2026-04-22 in conjunction with the fleet-wide `kernel.core_pattern` change. Adopts the friendly-alias convention formalized this month — embeds lead with `ATLn`/`NYn`/`CHIn` headers so operators can grep crash history alongside `match_id`. Sidecar `.bt` and `.reported` files persist next to each core for human triage; the core itself is never deleted, so any `gdb` session can be reopened later. See `TECHNICAL_GUIDE.md` § Admin Infrastructure → KTPCrashReporter for install + operate detail.

---

## Related Documentation

> For granular per-version changelogs, see the `CHANGELOG.md` in each project's repository.

- [TECHNICAL_GUIDE.md](./TECHNICAL_GUIDE.md) - Architecture and implementation details
- [README.md](./README.md) - Quick start and command reference
- [CHANGELOG.md](./CHANGELOG.md) - Detailed version history

---

*Last updated: 2026-04-25*
