# KTP Cvar Recommendations for 1000-Tick Servers

**Date:** February 7, 2026
**Engine:** KTP-ReHLDS 3.22.0.904+
**Enforcer:** KTPCvarChecker 7.12
**Author:** Nein_

---

## Executive Summary

This document evaluates all 59 cvars currently enforced by KTPCvarChecker against three criteria:

1. **Does the cvar provide a competitive advantage when changed?** (Keep enforcing)
2. **Is the enforced value correct for a 1000-tick server with global players?** (Adjust if needed)
3. **Is enforcement necessary at all?** (Remove if purely cosmetic/preference)

KTP servers now run at 1000 Hz physics with 120 Hz entity updates, serving players from 15ms (US East) to 160ms (South America/Europe). This document recommends which cvars to keep, adjust, relax, or remove, and identifies engine-level changes worth pursuing.

**Key Recommendations:**
- Raise `MAX_RATE` in the engine from 100,000 to 1,000,000 (current config is silently capped)
- Raise `MAX_PROXY_UPDATERATE` from 100 to 120 for HLTV fidelity
- Lower `cl_updaterate` minimum from 100 to 80 for high-ping players
- Remove enforcement of ~15 purely cosmetic cvars
- Keep strict enforcement of all visibility/lighting exploit cvars

---

## 1. Player Ping Analysis

Data from 8 competitive scoreboards (88 player measurements, KTP Season 2025-2026):

### Ping Distribution

| Range | Count | % | Player Profile |
|-------|-------|---|----------------|
| 15-50ms | 35 | 40% | US East (Atlanta local, East Coast) |
| 50-100ms | 25 | 28% | US West/Central, Canada |
| 100-140ms | 20 | 23% | South America (Brazil, Venezuela, Argentina), Europe |
| 140-160ms | 8 | 9% | Deep South America, transatlantic |

### Key Statistics
- **Minimum:** 15ms (bb, hildebrand? — likely Atlanta area)
- **Maximum:** 160ms (ting tong — consistent across both halves)
- **Median:** ~70ms
- **Mean:** ~80ms
- **Players over 100ms:** ~32% (roughly 1 in 3 players)

### Implications for Cvar Settings
- Rate/updaterate settings must work for 160ms players without degrading 15ms players
- ex_interp tuning matters: a 160ms player with ex_interp 0.03 sees the world 190ms in the past vs 168ms with ex_interp 0
- The 50ms hardcoded HLTV interp buffer adds more latency than the entire update interval at 120 Hz (8.3ms)
- High-ping players already function well at cl_updaterate 100+ (no reports of choke or loss)

---

## 2. Network Cvars — Detailed Analysis

### cl_updaterate (Currently: 100-120)

**What it does:** Controls how many entity state updates per second the client requests from the server.

**Engine behavior:**
- Hardcoded floor: 10 UPS (in `SV_HandleClientData`)
- No hardcoded ceiling — `sv_maxupdaterate` (cvar) is the only cap
- Server config: `sv_minupdaterate 90` / `sv_maxupdaterate 120`

**Current enforcement:** KTPCvarChecker forces 100-120.

**Analysis for high-ping players:** At 160ms ping, the difference between 80 Hz and 120 Hz updaterate is:
- 80 Hz = new update every 12.5ms
- 120 Hz = new update every 8.3ms
- Delta: 4.2ms — negligible relative to 160ms transit time

However, higher updaterate gives the server more data points for lag compensation hitbox rewinding, which benefits hit registration for ALL players shooting at high-ping opponents.

**Recommendation: Keep 100-120.** The current range works for all observed ping ranges (15-160ms). No players have reported choke or loss issues at 100+ updaterate. The hit registration benefit outweighs the marginal bandwidth increase.

**Server config alignment:** Consider raising `sv_minupdaterate` from 90 to 100 to match the cvar checker floor, eliminating the gap where a player could have updaterate 90-99 if the cvar check hasn't fired yet.

---

### cl_cmdrate (Currently: 100-500)

**What it does:** Controls how many movement command packets per second the client sends to the server.

**Engine behavior:** No direct engine cap. Server-side flood protection (`sv_rehlds_movecmdrate_max_burst`) limits burst rates. Commands are processed once per server frame (1000 Hz).

**Relationship to fps_max:** Clients cannot send more commands per second than they render frames. With fps_max 100, cl_cmdrate above 100 just ensures no commands are dropped. With fps_max 500, cl_cmdrate 500 would send 500 commands/sec — but the server processes them at 1000 Hz, so no issue.

**Recommendation: Keep 100-500.** The floor of 100 ensures adequate command granularity. The ceiling of 500 matches fps_max ceiling. The current flood protection (`sv_rehlds_movecmdrate_max_burst 10000`) handles any abuse.

---

### rate (Currently: 100000-1000000)

**What it does:** Maximum bytes per second the server sends to this client.

**CRITICAL ENGINE FINDING:**

```cpp
// net.h line 108-109
const float MAX_RATE = 100000.0f;  // Hardcoded 100 KB/s ceiling
const float MIN_RATE = 1000.0f;

// sv_main.cpp line 5467
cl->netchan.rate = Q_clamp(float(i), MIN_RATE, MAX_RATE);

// sv_main.cpp line 3794-3795
if (sv_maxrate.value > MAX_RATE)
    cl->netchan.rate = MAX_RATE;  // sv_maxrate silently capped
```

**The engine hardcodes rate to a maximum of 100,000 bytes/sec.** Your `sv_maxrate 1000000` and cvar checker range up to 1,000,000 are silently ignored. Every player on KTP servers is running at exactly 100,000 bytes/sec regardless of what they set.

**Bandwidth vs. updaterate at MAX_RATE = 100,000 bytes/sec:**

| Updaterate | Avg packet 400B | Avg packet 600B | Avg packet 800B |
|------------|----------------|----------------|----------------|
| 120 Hz | 48 KB/s | 72 KB/s | 96 KB/s |
| 150 Hz | 60 KB/s | 90 KB/s | **120 KB/s (throttled)** |
| 200 Hz | 80 KB/s | **120 KB/s (throttled)** | **160 KB/s (throttled)** |

At 120 Hz the current rate cap provides adequate headroom. At higher updaterates, the rate limiter begins **skipping updates** to stay within the bandwidth envelope — causing irregular update delivery that is worse than a consistent lower rate. This is why `MAX_RATE` must be raised before increasing `sv_maxupdaterate` beyond 120.

**Recommendation: Raise MAX_RATE in the engine** (see Section 5). In the meantime, update the cvar checker to enforce `rate` at exactly 100000 (since that's the actual maximum) rather than the misleading 100000-1000000 range. Or raise MAX_RATE first, then keep the higher range.

---

### ex_interp (Currently: 0-0.03)

**What it does:** Sets the interpolation time window for rendering entity positions between server updates.

**Engine behavior:** The game server engine does NOT enforce any floor or ceiling on ex_interp for game clients. The 0.05f buffer formula (`(1.0f / updaterate) + 0.05f`) only exists in the HLTV Proxy code (`Proxy.cpp:749`) and only affects HLTV viewers.

**How it interacts with ping:**

| Player Ping | ex_interp 0 (auto) | ex_interp 0.03 | Total Visual Delay |
|-------------|--------------------|-----------------|--------------------|
| 15ms | 8.3ms | 30ms | 23ms / 45ms |
| 70ms | 8.3ms | 30ms | 78ms / 100ms |
| 160ms | 8.3ms | 30ms | 168ms / 190ms |

With `ex_interp 0` (auto = 1/120 = 8.3ms at 120 Hz updaterate), the interpolation window is minimal. This is optimal because:
- Entities render as close to their actual server position as possible
- Lag compensation rewinds less, producing fewer "shot around a corner" effects
- Network jitter on modern broadband is typically <5ms — well within the 8.3ms window

**Recommendation: Keep 0-0.03.** The current range is well-calibrated. The 0.03 cap prevents exploitative high interp values (which create excessive lag compensation windows). Recommend documenting that `ex_interp 0` is optimal for all ping ranges.

---

### fps_max (Currently: 60-500)

**What it does:** Caps the client's frame rate.

**Engine behavior:** The GoldSrc engine ties physics to frame rate. Internal physics processing caps at ~100.5 FPS regardless of fps_max. Higher values provide smoother rendering for high-refresh-rate monitors but don't change physics granularity. The engine has a multiplayer floor of 20 FPS.

**Analysis:**
- fps_max 60: Minimum playable. Some older machines may need this.
- fps_max 100: Standard competitive setting. Physics at full fidelity.
- fps_max 144/240/500: Smoother rendering on high-refresh monitors. No physics advantage over 100.
- The old `fps_max 99.5` convention is unnecessary on KTP servers — the Host_FilterTime fix already removed the off-by-one issue.

**Recommendation: Keep 60-500.** The current range accommodates both older hardware (60) and modern high-refresh monitors (500). No competitive advantage above 100 FPS for physics, and the server's lag compensation is authoritative regardless.

---

### cl_fixtimerate (Currently: exact 7.5)

**What it does:** Controls how aggressively the client corrects its local clock to sync with the server's timestamp. Value is in milliseconds per frame of allowed drift correction.

**Engine behavior:** Client-side only. Not found in the KTP-ReHLDS server engine code — this is processed purely by the client binary.

**At 1000 tick:** The server sends timestamps at 1ms intervals. A cl_fixtimerate of 7.5ms means the client can adjust up to 7.5ms per frame, which at 100 FPS = up to 750ms/sec of drift correction. This is more than adequate for clock sync.

**Weapon skipping issue:** The default 7.5ms is a known cause of **weapon model animation skipping** in GoldSrc. When the client corrects its clock aggressively, the frame time jumps forward or backward by several milliseconds, causing the weapon viewmodel animation to stutter or skip frames visually. Players who lower this value or set it to 0 get smoother weapon animations. Enforcing it at exactly 7.5 prevents players from fixing this visual issue on their own.

**Recommendation: Remove from enforcement.** No competitive advantage from changing this value — clock synchronization still occurs regardless, just more or less aggressively. Letting players tune this eliminates weapon skipping without affecting gameplay fairness.

---

### cl_smoothtime (Currently: 0-0.1)

**What it does:** Controls how long (in seconds) the client takes to visually correct prediction errors (the difference between where the client predicted you'd be and where the server says you actually are).

**Competitive impact:**
- `cl_smoothtime 0`: Instant correction — most accurate but can cause visual "warping"
- `cl_smoothtime 0.1`: 100ms smooth correction — visually smoother but entity positions are slightly wrong during the correction window

**For high-ping players (100-160ms):** Prediction errors are more frequent and larger. Forcing `cl_smoothtime 0` causes more visible warping for these players. Allowing up to 0.1 gives them the option to smooth it out at the cost of slight positional inaccuracy.

**Recommendation: Keep 0-0.1.** The current range is good — it lets low-ping players use 0 for maximum accuracy and high-ping players use up to 0.1 for visual comfort. The 0.1 cap prevents excessive smoothing that would significantly desync rendered positions.

---

### cl_lc and cl_lw (Currently: exact 1)

**What they do:**
- `cl_lc 1`: Enables server-side lag compensation (server rewinds hitboxes to where they were when the player fired)
- `cl_lw 1`: Enables client-side weapon prediction (client shows weapon effects immediately, server reconciles)

**Why both must be 1:** Disabling either one breaks the lag compensation system. With cl_lc 0, the server doesn't rewind hitboxes, meaning high-ping players can't hit anything. With cl_lw 0, client-side prediction is disabled, and lag compensation is also disabled as a side effect.

**Recommendation: Keep exact 1 for both. Non-negotiable.** These are the foundation of fair play in a diverse-ping environment.

---

## 3. Graphics/Rendering Cvars — Competitive Analysis

### Tier 1: Must Enforce (Competitive Integrity)

These cvars provide clear visibility or gameplay advantages when changed. Keep strict enforcement.

| Cvar | Enforced Value | Why |
|------|---------------|-----|
| `r_fullbright` | 0 | Removes all shadows — massive visibility cheat |
| `r_drawentities` | 1 | Values 2-4 show wireframe/hitboxes |
| `gl_monolights` | 0 | Value 1 flattens all lighting, removes shadows |
| `lightgamma` | 1.81-3.0 | Below 1.81 crashes DoD; above 3.0 is extreme brightness hack |
| `r_lightmap` | 0 | Non-zero values display raw lightmaps |
| `r_luminance` | 0 | Non-zero makes map look blue/green, distorts visibility |
| `fastsprites` | 0 | Value 2 makes smoke sprites near-transparent |
| `gl_nobind` | 0 | Replaces textures with alphanumeric characters |
| `gl_nocolors` | 0 | Removes all color from the game |
| `texgamma` | 2 | Lighting consistency; non-standard values alter brightness |
| `gl_clear` | 0 | Value 1 makes cracks between brushes visible |
| `gl_d3dflip` | 0 | Value 1 makes cracks between brushes visible |

**Count: 12 cvars — all essential.**

### Tier 2: Should Enforce (Moderate Impact)

These provide subtle advantages or ensure standardized visual experience.

| Cvar | Enforced Value | Why | Notes |
|------|---------------|-----|-------|
| `gl_overbright` | 0 | Can brighten dark areas beyond intended lighting | Borderline — some argue this is preference |
| `r_dynamic` | 1 | Disabling removes flashlight/muzzle flash effects | Standard enforcement |
| `r_drawviewmodel` | 1 | Hiding weapon model gives ~10-15% more screen visibility | **Consider relaxing** — many competitive players prefer 0; CS2 locks it but older leagues allowed it |
| `gl_picmip` | 0 | **No longer functional** in modern GoldSrc builds — crashed and was removed | Vestigial enforcement |
| `gl_playermip` | 0 | Player model quality; lower quality doesn't help visibility | Low impact |

**Count: 5 cvars. gl_picmip is vestigial. r_drawviewmodel is debatable.**

### Tier 3: Can Remove (Minimal/No Competitive Impact)

These cvars are purely cosmetic, performance-related, or server-controlled. Enforcing them adds cvar checker overhead without meaningful competitive benefit.

| Cvar | Current Value | Why It Can Be Removed |
|------|--------------|----------------------|
| `gl_affinemodels` | 0 | Texture perspective correction on models — purely visual quality |
| `gl_alphamin` | 0.25 | Minimum alpha blending — no visibility exploit |
| `gl_cull` | 1 | Backface culling — performance optimization, not a cheat |
| `gl_dither` | 1 | Dithering technique — rendering quality preference |
| `gl_keeptjunctions` | 1 | Texture junction rendering — visual quality |
| `gl_lightholes` | 1 | Light holes display — minor visual feature |
| `gl_palette_tex` | 1 | Paletted textures — performance/quality tradeoff |
| `gl_round_down` | 3 | Texture rounding — quality vs performance |
| `r_bmodelinterp` | 1 | Brush model interpolation — visual smoothness |
| `r_glowshellfreq` | 2.2 | Glow shell animation speed — purely cosmetic |
| `r_traceglow` | 0 | Glow sprite occlusion — minor visual feature |
| `r_wadtextures` | 0 | WAD texture loading — no gameplay impact |
| `ambient_fade` | 100 | Sound fade distance — no competitive advantage |
| `ambient_level` | 0.3 | Ambient sound volume — preference |
| `s_show` | 0 | Debug display — minor debug tool, not exploitable |

**Count: 15 cvars that could be removed from enforcement.**

Removing these would:
- Reduce cvar checker queries from ~59 to ~44
- Faster initial checks on connect (~3s instead of ~4s)
- Less bandwidth overhead (fewer cvar queries per second)
- Fewer false-positive correction events for players with custom configs
- Focus enforcement resources on cvars that actually matter

---

## 4. Movement/Input Cvars — Competitive Analysis

### Must Enforce

| Cvar | Value | Reason |
|------|-------|--------|
| `m_pitch` | ±0.022 | Standard mouse sensitivity multiplier. Non-standard values alter aim behavior. |
| `cl_lc` | 1 | Lag compensation — see Section 2 |
| `cl_lw` | 1 | Client prediction — see Section 2 |
| `cl_pitchdown` | 89 | Prevents looking straight down (potential exploit) |
| `cl_pitchup` | 89 | Prevents looking straight up (potential exploit) |

### Can Relax or Remove

| Cvar | Current | Analysis | Recommendation |
|------|---------|----------|----------------|
| `cl_yawspeed` | 210 | Only affects keyboard turning. Mouse users (100% of competitive players) are unaffected. | **Remove** — no mouse user can exploit this |
| `cl_pitchspeed` | 225 | Same as above — keyboard turning speed only. | **Remove** |
| `cl_anglespeedkey` | 0.67 | Keyboard turn speed multiplier. Mouse-irrelevant. | **Remove** |
| `cl_movespeedkey` | 0.3 | Walk/run speed multiplier. Server physics (`sv_maxspeed`) is authoritative — client value doesn't affect actual speed. | **Remove** |
| `cl_upspeed` | 320 | Vertical movement input scaling. Server physics is authoritative. | **Remove** |
| `m_side` | 0.8 | Mouse strafing sensitivity. Only affects mouse-strafe (rarely used). | **Remove** — not exploitable |
| `cl_bobcycle` | 0.8 | View bob frequency — purely cosmetic, doesn't affect hitboxes. | **Relax to range** or **remove** |
| `cl_bobup` | 0.5 | View bob upward fraction — purely cosmetic. | **Relax to range** or **remove** |
| `cl_bob` | 0-0.011 | View bob amplitude — purely cosmetic. | Already a range — fine as-is or **remove** |
| `cl_gaitestimation` | 1 | Player animation estimation — client-side visual smoothing only. | **Remove** |
| `lookspring` | 0 | Auto-center view when mlook deactivated. No competitive impact. | **Remove** |
| `lookstrafe` | 0 | Mouse strafe when mlook active. Rarely used feature. | **Remove** |
| `cl_mousegrab` | 1 | Linux/MOSS related. Listed as having no gameplay effect in docs. | **Keep** for MOSS compatibility |
| `hud_takesshots` | 1 | Auto-screenshot at map end. Important for match records. | **Keep** (already conditional) |
| `cl_showevents` | 0 | Debug event display. Minimal impact. | **Remove** |

**Summary:** 11 movement/input cvars could be removed from enforcement with zero competitive impact.

---

## 5. Engine-Level Recommendations

### 5.1 Raise MAX_RATE (Priority: HIGH)

**File:** `rehlds/engine/net.h` line 108

```cpp
// Current:
const float MAX_RATE = 100000.0f;  // 100 KB/s — 1998 dial-up era limit

// Recommended:
const float MAX_RATE = 1000000.0f;  // 1 MB/s — modern broadband
```

**Why:** The current 100 KB/s cap is from the original Half-Life release in 1998. At 120 Hz updaterate with 10+ players, peak bandwidth per client can approach 96 KB/s — dangerously close to the cap. Modern internet connections (even in South America) handle megabits easily. This is risk-free with zero downside.

**Impact:** Players with `rate 100000` continue unchanged. Players who set higher values actually get higher bandwidth allocation. `sv_maxrate 1000000` in dodserver.cfg actually works as intended.

**After this change:** Update KTPCvarChecker `rate` range to enforce a reasonable range like 100000-1000000 (now meaningful instead of illusory).

---

### 5.2 Raise MAX_PROXY_UPDATERATE for HLTV (Priority: MEDIUM)

**File:** `rehlds/HLTV/Proxy/src/Proxy.h` line 51

```cpp
// Current:
const int MAX_PROXY_UPDATERATE = 100;  // HLTV capped at 100 Hz

// Recommended:
const int MAX_PROXY_UPDATERATE = 120;  // Match game server updaterate
```

**Why:** Game clients receive 120 updates/sec, but HLTV proxies are capped at 100. HLTV recordings and live spectators are missing ~17% of entity state updates compared to in-game players. Raising to 120 gives HLTV full fidelity matching the game server.

---

### 5.3 Reduce HLTV ex_interp Buffer (Priority: LOW)

**File:** `rehlds/HLTV/Proxy/src/Proxy.cpp` line 749

```cpp
// Current:
float ex_interp = (1.0f / GetMaxUpdateRate()) + 0.05f;
// At 100 Hz: 10ms + 50ms = 60ms

// Option A: Reduce buffer
float ex_interp = (1.0f / GetMaxUpdateRate()) + 0.025f;
// At 120 Hz: 8.3ms + 25ms = 33.3ms

// Option B: Make configurable via cvar
float buffer = ktp_hltv_interp_buffer.value;
float ex_interp = (1.0f / GetMaxUpdateRate()) + buffer;
```

**Why:** The 50ms buffer was designed for unreliable 2004 internet. Modern connections to KTP's dedicated servers have <5ms jitter. The buffer adds 50ms of visual latency to HLTV playback that is no longer necessary. Reducing it improves the accuracy and responsiveness of HLTV demo playback.

**Risk:** If an HLTV proxy's connection to the game server is unstable, too small a buffer could cause visual jitter in HLTV. A 25ms buffer is conservative enough to handle typical jitter while cutting visual latency nearly in half.

---

### 5.4 No Change Needed: Updaterate Ceiling

The engine already has no hardcoded updaterate ceiling for game clients. The current `sv_maxupdaterate 120` is a server admin cvar, not an engine limit. If KTP ever wants to push to 128 or higher, it's a one-line config change — no engine modification needed.

---

## 6. Revised Cvar List — Recommended Changes

### Summary of Changes

| Action | Count | Details |
|--------|-------|---------|
| **Keep as-is** | 21 | Core competitive integrity cvars |
| **Adjust range** | 1 | `rate` — update after engine MAX_RATE change |
| **Remove from enforcement** | 27 | Cosmetic, keyboard-only, server-controlled, or weapon-skip-causing cvars |
| **Relax enforcement** | 1 | `r_drawviewmodel` — consider allowing 0 or 1 |
| **Already fine** | 9 | Priority cvars with correct ranges |

### Proposed Enforcement List (32 cvars, down from 59)

#### Priority Cvars (9) — Checked Every 2 Seconds

| Cvar | Range | Notes |
|------|-------|-------|
| `m_pitch` | ±0.022 | Dual-value (positive or negative) |
| `cl_pitchdown` | 89 | Moved to priority |
| `cl_pitchup` | 89 | Moved to priority |
| `cl_updaterate` | 100-120 | |
| `cl_cmdrate` | 100-500 | |
| `rate` | 100000-1000000 | *After engine MAX_RATE fix* |
| `ex_interp` | 0-0.03 | |
| `cl_lc` | 1 | |
| `cl_lw` | 1 | |

#### Standard Cvars (24) — Rotated Check

**Visibility/Lighting (12):**
| Cvar | Value |
|------|-------|
| `r_fullbright` | 0 |
| `r_drawentities` | 1 |
| `gl_monolights` | 0 |
| `lightgamma` | 1.81-3.0 |
| `r_lightmap` | 0 |
| `r_luminance` | 0 |
| `fastsprites` | 0 |
| `gl_nobind` | 0 |
| `gl_nocolors` | 0 |
| `texgamma` | 2 |
| `gl_clear` | 0 |
| `gl_d3dflip` | 0 |

**Rendering (4):**
| Cvar | Value |
|------|-------|
| `gl_overbright` | 0 |
| `r_dynamic` | 1 |
| `gl_playermip` | 0 |
| `r_drawviewmodel` | 1 *(or consider 0-1 range)* |

**Network/Prediction (2):**
| Cvar | Value |
|------|-------|
| `cl_smoothtime` | 0-0.1 |
| `fps_max` | 60-500 |

**Gameplay (5):**
| Cvar | Value |
|------|-------|
| `cl_mousegrab` | 1 |
| `hud_takesshots` | 1 *(competitive only)* |
| `cl_bob` | 0-0.011 |
| `cl_bobcycle` | 0.8 |
| `cl_bobup` | 0.5 |

### Cvars Removed from Enforcement (26)

| Cvar | Reason |
|------|--------|
| `gl_affinemodels` | Visual quality — no competitive impact |
| `gl_alphamin` | Alpha blending minimum — no exploit |
| `gl_cull` | Performance optimization — not a cheat |
| `gl_dither` | Rendering technique — preference |
| `gl_keeptjunctions` | Texture junction rendering — visual quality |
| `gl_lightholes` | Light holes — minor visual feature |
| `gl_palette_tex` | Paletted textures — performance/quality |
| `gl_picmip` | **No longer functional** in modern GoldSrc |
| `gl_round_down` | Texture rounding — quality vs performance |
| `r_bmodelinterp` | Brush model interpolation — visual smoothness |
| `r_glowshellfreq` | Glow animation speed — purely cosmetic |
| `r_traceglow` | Glow occlusion — minor visual |
| `r_wadtextures` | WAD textures — no gameplay impact |
| `ambient_fade` | Sound fade distance — no competitive advantage |
| `ambient_level` | Ambient volume — preference |
| `s_show` | Debug display — not exploitable |
| `cl_yawspeed` | Keyboard turning only — mouse users unaffected |
| `cl_pitchspeed` | Keyboard turning only — mouse users unaffected |
| `cl_anglespeedkey` | Keyboard turn multiplier — mouse irrelevant |
| `cl_movespeedkey` | Walk/run multiplier — server physics authoritative |
| `cl_upspeed` | Vertical input — server physics authoritative |
| `m_side` | Mouse strafe sensitivity — not exploitable |
| `cl_gaitestimation` | Animation estimation — purely cosmetic |
| `lookspring` | Auto-center view — preference |
| `lookstrafe` | Mouse strafe mode — preference |
| `cl_showevents` | Debug events — minimal impact |
| `cl_fixtimerate` | Clock drift correction — enforcing at 7.5 causes weapon model skipping; players should be free to tune |

---

## 7. Server Config Recommendations

### dodserver.cfg Changes

```
// After engine MAX_RATE fix:
sv_maxrate 1000000              // Actually works now (was silently capped at 100000)

// Align with cvar checker:
sv_minupdaterate 100            // Match cvar checker floor (currently 90)
```

### Recommended Client Settings (for KTP Cvar List documentation)

**All Players (Universal):**
```
cl_updaterate 101
cl_cmdrate 101
rate 100000
ex_interp 0
fps_max 100
cl_lc 1
cl_lw 1
```

**High-Refresh Monitor Players (144Hz+):**
```
fps_max 144    // or 240, 500 — match your monitor
cl_cmdrate 150 // match fps_max + small buffer
```

**High-Ping Players (100ms+):**
```
// Same as universal — no special settings needed
// ex_interp 0 is still optimal (auto-calculates to 1/updaterate)
// The server's lag compensation handles the rest
```

---

## 8. Modern Context: Why These Recommendations

### The Industry Has Moved to Server-Side Control

CS2 removed client networking cvars entirely. Valorant never exposed them. The modern philosophy is: **the server decides netcode parameters, not the client.**

KTP is already well-aligned with this through KTPCvarChecker's real-time enforcement. The recommendations here refine which cvars deserve that enforcement, focusing on the ~33 that actually impact competitive integrity rather than the full 59.

### The 50ms HLTV Buffer Is a 2004 Artifact

When Half-Life shipped, 56k modems with 200ms+ jitter were common. The 50ms interpolation buffer was conservative insurance. Modern broadband connections to dedicated servers have <5ms jitter. The buffer adds more visual latency than the entire update interval at 120 Hz.

### Rate Limits Are From the Dial-Up Era

`MAX_RATE = 100000` (100 KB/s) was generous for 2004. In 2026, even South American players on modest connections have 10+ Mbps available. The engine's rate cap is the single most outdated constant in the netcode.

### 1000 Hz Physics Changes Nothing for Client Cvars

Running at 1000 Hz sys_ticrate means the server processes physics at 1ms intervals, but entity updates to clients are still governed by `sv_maxupdaterate` (120 Hz). Client cvars like `cl_updaterate`, `cl_cmdrate`, and `ex_interp` operate the same way at 1000 tick as they did at 100 tick — the server just has more granular physics between the updates it sends.

The main benefit of 1000 tick for clients is more precise lag compensation (server has 1ms-resolution player position history instead of 10ms).

---

## 9. Implementation Priority

| Priority | Change | Effort | Impact |
|----------|--------|--------|--------|
| **1** | Raise MAX_RATE in engine (`net.h`) | 1 line + rebuild + deploy | Unlocks rate headroom for future updaterate increases |
| **2** | Remove 27 unnecessary cvars from KTPCvarChecker | Code change + compile | Reduces overhead, fewer false corrections |
| **3** | Update KTP Cvar List documentation | Doc update | Accurate player-facing information |
| **4** | Raise MAX_PROXY_UPDATERATE for HLTV | 1 line + rebuild HLTV | Better HLTV recording fidelity |
| **5** | Reduce HLTV interp buffer | 1 line + rebuild HLTV | Lower HLTV visual latency |
| **6** | Align sv_minupdaterate to 100 | Config change | Consistency with cvar checker |

---

## 10. Files Reference

| File | Key Content |
|------|-------------|
| `KTPCvarChecker/ktp_cvar.sma` | Cvar enforcement plugin source |
| `KTPReHLDS/rehlds/engine/net.h:108-109` | MAX_RATE/MIN_RATE hardcoded limits |
| `KTPReHLDS/rehlds/engine/sv_main.cpp:220-221` | sv_maxupdaterate/sv_minupdaterate cvars |
| `KTPReHLDS/rehlds/engine/sv_main.cpp:1723-1746` | SV_CheckUpdateRate() |
| `KTPReHLDS/rehlds/engine/sv_main.cpp:5467` | Rate clamping code |
| `KTPReHLDS/rehlds/HLTV/Proxy/src/Proxy.h:49-58` | MAX_PROXY_UPDATERATE |
| `KTPReHLDS/rehlds/HLTV/Proxy/src/Proxy.cpp:749` | ex_interp formula with 0.05f buffer |
| `KTP DoD Server/serverfiles/dod/dodserver.cfg` | Server rate configuration |
| `KTP_Documentation/KTP Cvar List.md` | Player-facing cvar requirements |

---

## 11. Sources

- KTP-ReHLDS engine source code analysis (February 2026)
- Player ping data from 8 KTP competitive scoreboards (Season 2025-2026)
- [Valve Half-Life GitHub Issue #3109](https://github.com/ValveSoftware/halflife/issues/3109) — Netcode statement request (unanswered)
- [Valve Half-Life GitHub Issue #2344](https://github.com/ValveSoftware/halflife/issues/2344) — Default rate values
- [Valve Half-Life GitHub Issue #395](https://github.com/ValveSoftware/halflife/issues/395) — ex_interp auto-calculation bug
- [CS2 Subtick System](https://blix.gg/news/cs-2/cs2-tick-rate-subtick-explained-64-hz-vs-128-tick-faceit-update-2025/)
- [Valorant 128-Tick Servers](https://technology.riotgames.com/news/valorants-128-tick-servers)
- [Steam Community Netcode Guide](https://steamcommunity.com/sharedfiles/filedetails/?id=1111287607)
- [GoldSrc.ru Rate Configuration](https://goldsrc.ru/threads/8/)
- [Source Multiplayer Networking](https://developer.valvesoftware.com/wiki/Source_Multiplayer_Networking)

---

---

## Admin Summary (Discord-Ready)

<!-- Copy everything below this line for Discord -->

**KTP Cvar & Netcode Review — 1000 Tick Servers (Feb 2026)**

Deep dive into our entire cvar enforcement list, the engine source code, and modern competitive FPS practices. Analyzed real ping data from 8 recent scoreboards (88 players, 15ms to 160ms range).

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯

**ENGINE DISCOVERIES**

**1. Engine Rate Cap (MAX_RATE = 100,000 bytes/sec)**
The engine hardcodes `MAX_RATE = 100,000 bytes/sec` in the source code. Our `sv_maxrate 1000000` in the server config is **silently ignored** — every player is capped at 100 KB/s regardless of what they set. At 120 Hz updaterate, peak bandwidth per client can hit ~96 KB/s during firefights. That's dangerously close to the cap and means we cannot raise updaterate above 120 without fixing this first — the rate limiter would start skipping updates, causing irregular delivery that's worse than consistent lower rates.

```
Bandwidth at MAX_RATE = 100,000 bytes/sec cap:

Updaterate │ Avg pkt 400B │ Avg pkt 600B          │ Avg pkt 800B
───────────┼──────────────┼───────────────────────┼───────────────────────
120 Hz     │ 48 KB/s      │ 72 KB/s               │ 96 KB/s
150 Hz     │ 60 KB/s      │ 90 KB/s               │ 120 KB/s (THROTTLED)
200 Hz     │ 80 KB/s      │ 120 KB/s (THROTTLED)  │ 160 KB/s (THROTTLED)
```

**Fix:** One-line engine change to raise the cap to 1,000,000. No risk, no downside. This is a 1998 dial-up era limit — modern connections handle megabits easily, even for our South American players.

**2. No Hardcoded Updaterate Ceiling**
The engine has no hardcoded cap on updaterate. `sv_maxupdaterate` is purely a server admin cvar. We can set it to 128, 200, or higher — the only constraint is the MAX_RATE bandwidth limit above.

**3. HLTV Is Running at Lower Fidelity Than Game Clients**
HLTV proxies are hardcoded to max 100 Hz updaterate while game clients get 120 Hz. We're losing ~17% of entity state updates in every HLTV recording and live spectator feed. One-line fix to raise to 120.

HLTV also has a hardcoded 50ms interpolation buffer from the dial-up era. This means HLTV viewers see entities 58ms behind their actual position (at 120 Hz). Reducing the buffer to 15ms would cut that to 23ms — more accurate live spectating and demo playback. Removing the buffer entirely (8.3ms at 120 Hz) would be fine for demo files but risky for live viewers, since any packet jitter over 8.3ms would cause entity snapping. A 15ms buffer is the safe middle ground.

```
HLTV Interpolation Buffer Options (at 120 Hz):

Buffer          │ ex_interp │ Visual Delay │ Risk
────────────────┼───────────┼─────────────┼──────────────────────────────
50ms (current)  │ 58.3ms    │ High        │ None — 2004 dial-up era
25ms            │ 33.3ms    │ Medium      │ Low — handles 25ms jitter
15ms (rec.)     │ 23.3ms    │ Low         │ Minimal — handles 15ms jitter
0ms (removed)   │ 8.3ms     │ Minimal     │ HIGH — jitter >8.3ms = snapping
```

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯

**UPDATERATE RECOMMENDATION: RAISE TO 128**

After the MAX_RATE fix, we recommend raising `sv_maxupdaterate` from 120 to **at least 128**. This aligns KTP with the modern competitive FPS standard (Valorant runs at 128 Hz, CS:GO competitive used 128 Hz on FACEIT/ESEA).

At 128 Hz with the MAX_RATE fix applied:
- Bandwidth per client: 128 x 600 = ~77 KB/s average — well within new 1 MB/s cap
- Update interval: 7.8ms (vs 8.3ms at 120 Hz)
- ex_interp auto at 128 Hz: 7.8ms (vs 8.3ms at 120 Hz)
- More data points for lag compensation — finer-grained position history for hitbox rewinding

Raising beyond 128 (to 150 or 200) is possible but has diminishing returns. Stock GoldSrc clients also reportedly clamp `cl_updaterate` at ~100-102 on the receive side, so players may not actually receive updates above ~100 regardless of what the server offers. We'd need a way to verify actual client receive rates before pushing much higher.

**Recommended rollout:** Fix MAX_RATE → deploy → raise `sv_maxupdaterate` to 128 → update `cl_updaterate` enforcement range to 100-128 → monitor → consider higher later.

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯

**NETWORK SETTINGS: CURRENT CONFIG IS SOLID**

- `cl_updaterate 100-120` — works for all ping ranges including 160ms; raise to 100-128 after engine fix
- `ex_interp 0-0.03` — well calibrated; ex_interp 0 (auto) is optimal for all ping ranges
- `fps_max 60-500` — engine caps physics at ~100 FPS internally; higher values just help high-refresh monitors
- `cl_cmdrate 100-500` — fine as-is
- `rate 100000-1000000` — currently meaningless above 100K due to engine cap; becomes real after fix

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯

**CVAR LIST CLEANUP: 59 → 32**

We're currently enforcing 59 cvars. After reviewing each one against the engine source, **27 can be removed** with zero competitive impact. The remaining **32 cover everything that actually matters**.

Benefits of trimming: faster connect checks (~3s vs ~4s), less bandwidth overhead, fewer false correction events for players with custom configs.

**Cvars to Remove — Graphics/Rendering (15)**

`gl_affinemodels = 0` — Texture perspective correction on models. Purely visual quality. Doesn't affect hitboxes, visibility, or server state. No competitive advantage either way.

`gl_alphamin = 0.25` — Minimum alpha blending threshold. Controls how semi-transparent sprites render at edges. Doesn't reveal hidden players or see through walls. No exploit vector.

`gl_cull = 1` — Backface culling (skip rendering polygons facing away from camera). Setting to 0 tanks FPS but doesn't reveal anything hidden. A player disabling this only hurts themselves.

`gl_dither = 1` — Color dithering for 16-bit displays. On modern 32-bit displays, has zero visible effect. No competitive impact.

`gl_keeptjunctions = 1` — T-junction rendering between brushes. When 0, tiny hairline cracks appear, but they don't reveal anything behind walls. `gl_clear` (which we keep enforcing) is the one that matters for crack visibility.

`gl_lightholes = 1` — Light bleeding through small gaps in map geometry. Purely aesthetic. Doesn't brighten dark areas or reveal players.

`gl_palette_tex = 1` — 8-bit paletted texture mode. Legacy GPU performance feature. No visible effect on modern hardware.

`gl_picmip = 0` — Texture mip-mapping quality. **No longer functional in modern GoldSrc** — was removed/disabled because it caused crashes. Checking a dead cvar wastes a query slot.

`gl_round_down = 3` — Texture resolution rounding for performance. Makes game blurrier at higher values. Doesn't improve visibility of players.

`r_bmodelinterp = 1` — Brush model interpolation (smooths doors, elevators). Purely visual smoothness for non-player entities. No competitive advantage.

`r_glowshellfreq = 2.2` — Glow shell shimmer speed on flag carriers. Purely cosmetic animation rate. Faster or slower shimmer provides zero gameplay advantage.

`r_traceglow = 0` — Glow sprite occlusion by other entities. Minor visual feature. No competitive significance.

`r_wadtextures = 0` — WAD texture loading source. Not a quality or visibility setting. No gameplay impact.

`gl_playermip = 0` — Player model polygon detail level. Lower-detail models look blockier but don't stand out more. Hitboxes are server-side and don't change based on client model detail.

`gl_overbright = 0` — Overbright lighting. Borderline — when set to 1, brightens the scene uniformly. Doesn't selectively brighten dark areas like `r_fullbright` or extreme `lightgamma` does. Some leagues regulate it, others don't. Debatable.

**Cvars to Remove — Audio (3)**

`ambient_fade = 100` — Distance at which ambient sounds (birds, wind) fade out. Not player footsteps or weapon sounds. No competitive advantage.

`ambient_level = 0.3` — Volume of ambient environmental sounds. Background ambience only, not gameplay-relevant audio. Player preference.

`s_show = 0` — Debug text display showing active sounds. Clutters screen with text. Shows sound names, not directional info. Not exploitable.

**Cvars to Remove — Movement/Input (8)**

`cl_yawspeed = 210` — Keyboard turning speed (degrees/sec). Zero effect on mouse turning. 100% of competitive players use mouse. Not exploitable.

`cl_pitchspeed = 225` — Keyboard pitch speed. Same as cl_yawspeed — only affects keyboard, not mouse.

`cl_anglespeedkey = 0.67` — Keyboard turn speed multiplier when holding speed key. Only affects keyboard turning. Mouse users unaffected.

`cl_movespeedkey = 0.3` — Walk/run speed multiplier. **Server physics is authoritative** — `sv_maxspeed` determines actual player speed regardless of client value. Not exploitable.

`cl_upspeed = 320` — Vertical movement speed (ladders, swimming). Server physics is authoritative. Client value is input scaling only. Not exploitable.

`m_side = 0.8` — Mouse strafing sensitivity. Only affects mouse-strafe (holding strafe modifier + moving mouse). Almost nobody uses this. Not exploitable.

`cl_gaitestimation = 1` — Client-side animation prediction for other players. When 0, animations look jerky. Purely cosmetic — doesn't affect hitboxes or positions.

`lookspring = 0` — Auto-center view when mouse look deactivated. Nobody toggles mouse look mid-game. No competitive advantage.

`lookstrafe = 0` — Mouse strafe instead of turn when mlook active. Enabling this makes aiming impossible. No exploit vector.

`cl_showevents = 0` — Debug event text display. Clutters screen with debug info. Not exploitable.

**Cvars to Remove — Network/Prediction (1)**

`cl_fixtimerate = 7.5` — Controls how aggressively the client corrects its local clock to sync with server timestamps (ms of drift correction per frame). At default 7.5ms, the client can adjust its clock up to 7.5ms every frame. This aggressive correction is a known cause of **weapon model skipping** — the client's time jumps during correction, causing the weapon animation to stutter or skip frames. Players who lower this value (or set to 0) get smoother weapon animations. Enforcing 7.5 prevents players from fixing this. No competitive advantage from changing it — clock sync still happens, just more gradually.

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯

**WHAT WE KEEP ENFORCING (32 cvars)**

**Priority (9) — Checked every 2 seconds:**
`m_pitch` (±0.022), `cl_pitchdown` (89), `cl_pitchup` (89), `cl_updaterate` (100-128), `cl_cmdrate` (100-500), `rate` (100000-1000000), `ex_interp` (0-0.03), `cl_lc` (1), `cl_lw` (1)

**Visibility/Lighting (12) — Anti-cheat essentials:**
`r_fullbright` (0), `r_drawentities` (1), `gl_monolights` (0), `lightgamma` (1.81-3.0), `r_lightmap` (0), `r_luminance` (0), `fastsprites` (0), `gl_nobind` (0), `gl_nocolors` (0), `texgamma` (2), `gl_clear` (0), `gl_d3dflip` (0)

**Rendering (4):**
`gl_overbright` (0), `r_dynamic` (1), `gl_playermip` (0), `r_drawviewmodel` (1)

**Network/Prediction (2):**
`cl_smoothtime` (0-0.1), `fps_max` (60-500)

**Gameplay (5):**
`cl_mousegrab` (1), `hud_takesshots` (1, competitive only), `cl_bob` (0-0.011), `cl_bobcycle` (0.8), `cl_bobup` (0.5)

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯

**NO MODERN VALVE GUIDANCE EXISTS**

Valve has never updated GoldSrc netcode recommendations. A GitHub issue asking for an official statement has been open since 2021 with zero response. CS2 took the opposite approach — removed all client networking cvars entirely. Our server-side enforcement via KTPCvarChecker is aligned with that modern philosophy.

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯

**IMPLEMENTATION PRIORITY**

```
#  Change                                    Effort                  Impact
── ───────────────────────────────────────── ─────────────────────── ────────────────────────────────────────
1  Raise MAX_RATE in engine (100K → 1M)     1 line + rebuild        Unlocks updaterate increases
2  Raise sv_maxupdaterate to 128            Config change           Match industry standard (Valorant/FACEIT)
3  Remove 27 cvars from KTPCvarChecker      Code change + compile   Less overhead, fewer false corrections
4  Raise HLTV MAX_PROXY_UPDATERATE to 120+  1 line + rebuild HLTV   Full fidelity HLTV recordings
5  Reduce HLTV interp buffer (50ms → 15ms)  1 line + rebuild HLTV   More accurate spectating/playback
6  Update cvar list documentation           Doc update              Accurate player-facing info
```

Full technical details in the document sections above.

---

*Document version 1.0 — February 7, 2026*
