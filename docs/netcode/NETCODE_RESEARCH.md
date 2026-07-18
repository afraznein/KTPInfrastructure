# GoldSrc Netcode Research: Rate Limits, Interpolation, and Tick Timing

**Research Date:** February 4, 2026 (updated February 7, 2026)
**Engine:** KTP-ReHLDS 3.22.0.904+
**Author:** Nein_

---

## Executive Summary

This document analyzes the GoldSrc engine's network timing systems, focusing on `sys_ticrate`, `cl_updaterate`, `cl_cmdrate`, and `ex_interp`. We examine hardcoded limits, the mathematics behind interpolation, and potential benefits of modifying these constraints.

**Key Findings:**
- The game server engine has **no hardcoded updaterate ceiling** — `sv_maxupdaterate` is a server admin cvar, not an engine limit. Only a hardcoded floor of 10 UPS exists.
- HLTV proxy caps (`MAX_PROXY_UPDATERATE = 100`) are **HLTV-only** and do not affect game clients.
- The theoretical minimum `ex_interp` is dominated by a hardcoded **0.05f (50ms) buffer** — raising updaterate above 100 Hz provides diminishing returns without removing this buffer.
- Valve has issued **no modern guidance** on GoldSrc netcode rates. The engine shipped in 2004 and rate defaults have never been updated.

---

## 1. Server Tick Rate (sys_ticrate)

### Definition
`sys_ticrate` controls how many times per second the server runs its main loop (physics, networking, game logic).

### Engine Implementation

**File:** `rehlds/engine/host.cpp`

```cpp
// Line 59: Default definition
cvar_t sys_ticrate = { "sys_ticrate", "100.0", 0, 0.0f, NULL };

// Lines 686-701: Usage in Host_FilterTime()
if (command_line_ticrate > 0)
    fps = Q_atof(com_argv[command_line_ticrate + 1]);
else
    fps = sys_ticrate.value;

// KTP Fix: Removed "+ 1.0f" which artificially capped fps
// Original: 1.0f / (fps + 1.0f) - at 1000 ticrate, capped at ~999 fps
// Fixed: 1.0 / fps - allows true 1000 fps at sys_ticrate 1000
if (fps > 0.0)
{
    if (1.0 / fps > realtime - oldrealtime)
        return FALSE;
}
```

### KTP Modifications

1. **Removed artificial FPS cap** - Original code used `1.0f / (fps + 1.0f)` which limited actual FPS to `sys_ticrate - 1`. Fixed to `1.0 / fps`.

2. **Changed `fps` from float to double** - Improves precision consistency with `realtime`/`oldrealtime` variables.

### Current Settings
- **Default:** 100 Hz
- **KTP Servers:** 1000 Hz (via `-sys_ticrate 1000` command line)
- **Practical Maximum:** ~1000 Hz (limited by CPU and kernel scheduling)

---

## 2. Client Update Rate (cl_updaterate)

### Definition
`cl_updaterate` controls how many entity state updates per second the client requests from the server.

### Server-Side Enforcement

**File:** `rehlds/engine/sv_main.cpp`

```cpp
// Lines 220-221: Default cvars
cvar_t sv_maxupdaterate = { "sv_maxupdaterate", "30.0", 0, 0.0f, NULL };
cvar_t sv_minupdaterate = { "sv_minupdaterate", "10.0", 0, 0.0f, NULL };

// Lines 1723-1746: SV_CheckUpdateRate()
void SV_CheckUpdateRate(double *rate)
{
    if (*rate == 0.0)
    {
        *rate = 0.05;  // Default: 20 Hz
        return;
    }

    // Enforce maximum (client can't exceed this)
    if (sv_maxupdaterate.value != 0.0f)
    {
        if (*rate < 1.0 / sv_maxupdaterate.value)
            *rate = 1.0 / sv_maxupdaterate.value;
    }

    // Enforce minimum (client can't go below this)
    if (sv_minupdaterate.value != 0.0f)
    {
        if (*rate > 1.0 / sv_minupdaterate.value)
            *rate = 1.0 / sv_minupdaterate.value;
    }
}
```

### Hardcoded Floor (Engine Limit)

**File:** `rehlds/rehlds/engine/sv_main.cpp` (line ~5485)

```cpp
// In SV_HandleClientData — when client sends cl_updaterate via userinfo
i = Q_atoi(val);
if (i >= 10)
    cl->next_messageinterval = 1.0 / i;
else
    cl->next_messageinterval = 0.1;  // Floor: 10 UPS minimum
```

This is the only hardcoded updaterate limit in the game server engine. There is **no hardcoded ceiling** — `sv_maxupdaterate` can be set to any value by the server admin.

### HLTV Proxy Caps (HLTV Only — Does NOT Affect Game Clients)

These constants only apply to HLTV proxy connections, not to game clients connecting directly to the server.

**File:** `rehlds/HLTV/Proxy/src/Proxy.h`

```cpp
// Lines 49-58: Hardcoded constants (HLTV only)
#ifdef HLTV_FIXES
const int MAX_PROXY_RATE        = 100000;
const int MAX_PROXY_UPDATERATE  = 100;   // 100 Hz cap for HLTV
#else
const int MAX_PROXY_RATE        = 20000;
const int MAX_PROXY_UPDATERATE  = 40;    // 40 Hz cap (legacy HLTV)
#endif

const int MIN_PROXY_UPDATERATE  = 1;
```

**File:** `rehlds/HLTV/Proxy/src/Proxy.cpp`

```cpp
// Lines 2473-2476: Clamping function (HLTV only)
void Proxy::SetMaxUpdateRate(int updaterate)
{
    m_MaxUpdateRate = clamp(updaterate, MIN_PROXY_UPDATERATE, MAX_PROXY_UPDATERATE);
}
```

### Summary
| Parameter | Scope | Default | Minimum | Maximum |
|-----------|-------|---------|---------|---------|
| sv_maxupdaterate | Game server (cvar) | 30 Hz | - | **No hardcoded limit** |
| sv_minupdaterate | Game server (cvar) | 10 Hz | - | - |
| Hardcoded floor | Game server (engine) | - | **10 Hz** | - |
| MAX_PROXY_UPDATERATE | **HLTV only** | - | 1 Hz | 100 Hz (hardcoded) |

---

## 3. Client Command Rate (cl_cmdrate)

### Definition
`cl_cmdrate` controls how many movement commands per second the client sends to the server.

### Server-Side Monitoring

The engine monitors command rates for flood protection but doesn't directly cap `cl_cmdrate`:

**File:** `rehlds/rehlds/rehlds_security.cpp`

```cpp
// Movement command flood protection
cvar_t sv_rehlds_movecmdrate_max_avg = { "sv_rehlds_movecmdrate_max_avg", "1800", ... };
cvar_t sv_rehlds_movecmdrate_max_burst = { "sv_rehlds_movecmdrate_max_burst", "5500", ... };

// String command flood protection
cvar_t sv_rehlds_stringcmdrate_max_avg = { "sv_rehlds_stringcmdrate_max_avg", "250", ... };
cvar_t sv_rehlds_stringcmdrate_max_burst = { "sv_rehlds_stringcmdrate_max_burst", "500", ... };
```

### Relationship to sys_ticrate
- Client commands are processed once per server frame
- At 1000 Hz sys_ticrate, server can process up to 1000 commands/second
- Higher cl_cmdrate than sys_ticrate provides no benefit (commands queue)
- Optimal: `cl_cmdrate` ≈ `sys_ticrate` or slightly higher for burst handling

---

## 4. Entity Interpolation (ex_interp)

### Definition
`ex_interp` controls how far back in time the client renders entities, smoothing movement between updates.

### The Critical Formula

**File:** `rehlds/HLTV/Proxy/src/Proxy.cpp`

```cpp
// Line 749: The ex_interp calculation
float ex_interp = (1.0f / GetMaxUpdateRate()) + 0.05f;
stream->WriteByte(svc_stufftext);
stream->WriteString(COM_VarArgs("ex_interp %.2f\n", ex_interp));
```

### Mathematical Breakdown

```
ex_interp = (1.0 / updaterate) + 0.05

Where:
- 1.0 / updaterate = time between updates (seconds)
- 0.05 = hardcoded 50ms buffer (always added)
```

### Calculation Table

| updaterate | 1/updaterate | + 0.05 buffer | = ex_interp |
|------------|--------------|---------------|-------------|
| 20 Hz | 0.050s | 0.05s | **0.100s (100ms)** |
| 30 Hz | 0.033s | 0.05s | **0.083s (83ms)** |
| 60 Hz | 0.017s | 0.05s | **0.067s (67ms)** |
| 100 Hz | 0.010s | 0.05s | **0.060s (60ms)** |

### Theoretical Floor
**0.06 seconds (60ms)** - Even setting `ex_interp 0` in console, the engine enforces this minimum.

---

## 5. C++ Floating Point Considerations

### Float vs Double

| Type | Size | Precision | Suffix | Use Case |
|------|------|-----------|--------|----------|
| `float` | 4 bytes | ~7 digits | `f` | Graphics, game logic |
| `double` | 8 bytes | ~15 digits | none | Time calculations, physics |

### Binary Representation Problem

Decimal values like 0.05 cannot be exactly represented in binary floating point:

```cpp
float f = 0.05f;   // Actually: 0.0500000007450580596923828125
double d = 0.05;   // Actually: 0.05000000000000000277555756156289135105907917022705078125
```

### Implications for ex_interp

```cpp
// Current code uses float
float ex_interp = (1.0f / GetMaxUpdateRate()) + 0.05f;

// At 100 Hz:
// 1.0f / 100 = 0.00999999977648258209228515625 (not exactly 0.01)
// + 0.05f    = 0.0500000007450580596923828125
// Result     ≈ 0.0599999986588954925537109375 (not exactly 0.06)
```

### KTP Fix in Host_FilterTime

```cpp
// Original: float precision
float fps;
if (1.0f / (fps + 1.0f) > realtime - oldrealtime)

// KTP Fixed: double precision
double fps;
if (1.0 / fps > realtime - oldrealtime)
```

**Benefit:** `realtime` and `oldrealtime` are doubles. Using float for fps introduced precision loss in the comparison.

---

## 6. Potential Modifications and Benefits

### Option A: Remove the 0.05f Buffer

**Change:**
```cpp
// From:
float ex_interp = (1.0f / GetMaxUpdateRate()) + 0.05f;

// To:
float ex_interp = (1.0f / GetMaxUpdateRate());
```

**New ex_interp values:**

| updaterate | ex_interp (current) | ex_interp (no buffer) | Reduction |
|------------|--------------------|-----------------------|-----------|
| 100 Hz | 60ms | 10ms | **-50ms** |
| 128 Hz | 57.8ms | 7.8ms | **-50ms** |

**Benefits:**
- 50ms less visual latency
- More responsive entity positions
- Better alignment with actual network timing

**Risks:**
- Entities may "jitter" if packets arrive late
- Requires stable, low-jitter network connection
- Original buffer exists to absorb network variance

### Option B: Raise MAX_PROXY_UPDATERATE

**Change in Proxy.h:**
```cpp
// From:
const int MAX_PROXY_UPDATERATE  = 100;

// To:
const int MAX_PROXY_UPDATERATE  = 128;  // or higher
```

**New theoretical minimum ex_interp:**

| MAX_UPDATERATE | 1/rate | + 0.05 | = ex_interp |
|----------------|--------|--------|-------------|
| 100 Hz | 10ms | 50ms | 60ms |
| 128 Hz | 7.8ms | 50ms | 57.8ms |
| 256 Hz | 3.9ms | 50ms | 53.9ms |

**Benefits:**
- More frequent entity updates
- Smoother visual movement
- Better sync with 1000 Hz sys_ticrate

**Risks:**
- Increased bandwidth usage
- Diminishing returns past ~128 Hz for human perception
- Client must support higher rates

### Option C: Combined Approach

Remove buffer AND raise updaterate cap:

| Configuration | ex_interp |
|---------------|-----------|
| Current (100 Hz + 0.05 buffer) | 60ms |
| 128 Hz + 0.05 buffer | 57.8ms |
| 100 Hz + no buffer | 10ms |
| **128 Hz + no buffer** | **7.8ms** |

**Potential improvement: 60ms → 7.8ms = 52.2ms reduction**

### Option D: Use Double Precision Throughout

**Change:**
```cpp
// From:
float ex_interp = (1.0f / GetMaxUpdateRate()) + 0.05f;

// To:
double ex_interp = (1.0 / GetMaxUpdateRate()) + 0.05;
```

**Benefits:**
- More accurate calculations
- Consistency with other timing variables
- Eliminates float→double conversion errors

**Impact:** Minimal performance cost, improved precision.

---

## 7. Interaction Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        SERVER (1000 Hz)                         │
│                                                                 │
│  sys_ticrate 1000 ─────► 1ms per frame (physics)               │
│         │                                                       │
│         ▼                                                       │
│  ┌─────────────┐    sv_maxupdaterate     ┌──────────────────┐  │
│  │ Game Logic  │ ──────────────────────► │ Entity Updates   │  │
│  │ Physics     │    (cvar, no engine     │ to Clients       │  │
│  └─────────────┘     ceiling; KTP: 120)  └────────┬─────────┘  │
│                                                   │            │
└───────────────────────────────────────────────────┼────────────┘
                                                    │
                                          Network (10ms typical)
                                                    │
┌───────────────────────────────────────────────────┼────────────┐
│                         CLIENT                    ▼            │
│                                                                 │
│  cl_updaterate 120 ◄─── Requests 120 updates/sec               │
│         │                (stock clients may clamp at ~100)      │
│         ▼                                                       │
│  ex_interp 0.058 ───► Renders entities ~58ms in the past       │
│         │                (50ms hardcoded buffer dominates)      │
│         ▼                                                       │
│  cl_cmdrate 100+ ───► Sends movement commands to server        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

Total Visual Latency = Network RTT/2 + ex_interp + Render Time
                     = ~5ms + 58ms + ~16ms (60fps)
                     = ~79ms minimum
```

---

## 8. Modern Context (2024-2026)

### Valve Has Not Updated GoldSrc Rate Guidance

Valve has issued **no official guidance** on optimal GoldSrc netcode rates since the engine shipped in 2004. A [GitHub issue (#3109)](https://github.com/ValveSoftware/halflife/issues/3109) requesting an official netcode statement has been open since 2021 with zero Valve response. A related [issue (#2344)](https://github.com/ValveSoftware/halflife/issues/2344) about default rate values being too low for modern internet was closed without response.

The Half-Life 25th Anniversary Update (late 2023) included bug fixes and engine improvements but **no netcode rate changes**.

### Industry Tick Rate Comparison (2026)

| Game | Tick Rate | Notes |
|------|-----------|-------|
| **Valorant** | 128 Hz | Riot explicitly chose 128 for competitive integrity |
| **CS2** | 64 Hz | Sub-tick interpolation (different architecture, not applicable to GoldSrc) |
| **CS:GO** (legacy) | 64/128 Hz | 128 tick universally preferred by competitive players |
| **Overwatch 2** | 63 Hz | |
| **KTP DoD (current)** | **1000 Hz physics / 120 Hz updates** | Already beyond conventional GoldSrc community |

CS2's sub-tick system (which timestamps player actions between ticks) is a fundamentally different architecture. GoldSrc has no sub-tick equivalent — update rate directly determines the granularity of entity state transmission to clients. The CS2 philosophy that "tick rate doesn't matter" does **not** apply to GoldSrc.

### Bandwidth Impact of Higher Update Rates

Higher `sv_maxupdaterate` **primarily increases bandwidth**, with minimal CPU impact (physics already runs at 1000 Hz — higher update rates just send more snapshots of already-computed state).

Estimated bandwidth per player (GoldSrc, delta-compressed, ~500-800 byte avg packets):

| Update Rate | Per-Player Downstream | Server Upload (10 players) |
|-------------|----------------------|----------------------------|
| 100 Hz | ~50-80 KB/s | ~500-800 KB/s (4-6 Mbps) |
| 120 Hz | ~60-96 KB/s | ~600-960 KB/s (5-8 Mbps) |
| 128 Hz | ~64-102 KB/s | ~640-1024 KB/s (5-8 Mbps) |

These are upper-bound estimates. DoD with 10 players (smaller maps, fewer entities than CS) typically uses 40-60% of these figures. KTP dedicated servers have ample bandwidth headroom.

### Diminishing Returns Above 100 Hz

| Factor | Impact of 100→120 Hz |
|--------|---------------------|
| ex_interp reduction | 60ms → 58.3ms (**1.7ms** — negligible, 50ms buffer dominates) |
| Visual smoothness | Marginal improvement; DoD player models move slowly compared to modern shooters |
| Hit registration | No meaningful difference — lag compensation operates on server-side hitbox rewinding |
| Client support | **Key concern:** Stock GoldSrc clients may silently clamp `cl_updaterate` at ~100-102 |
| Packet overhead | ~20% more UDP packets/sec; negligible on modern connections |

### Client-Side Updaterate Cap (Stock GoldSrc)

Multiple community sources report that stock GoldSrc/HL1 clients silently clamp `cl_updaterate` at approximately 100-102. The Russian CS 1.6 competitive community specifically recommends `sv_maxupdaterate 102` as the practical maximum.

KTP servers enforce `cl_updaterate 100-120` via KTPCvarChecker. Whether stock clients actually process updates above 100 Hz on the receive side is unverified — the server will send at up to `sv_maxupdaterate`, but the client may only consume ~100 per second regardless of what it advertises.

---

## 9. Recommendations

### Current KTP Configuration (Already Applied)
- `sv_maxupdaterate 120` / `sv_minupdaterate 90` on all servers
- `sv_mincmdrate 100` / `sv_maxcmdrate 500`
- `sv_minrate 100000` / `sv_maxrate 1000000`
- KTPCvarChecker enforces `cl_updaterate 100-120`
- `sys_ticrate 1000` via command line

### Potential Future Improvements
1. **Reduce the 0.05f ex_interp buffer** — The 50ms hardcoded buffer in `Proxy.cpp:749` dominates visual latency. Reducing it to 0.025f (25ms) or making it configurable via cvar would provide more visual latency reduction than any updaterate increase.
2. **Make ex_interp buffer a cvar** — Allow server admins to tune the interpolation buffer based on their player base's connection quality.
3. **Raise MAX_PROXY_UPDATERATE for HLTV** — Current 100 Hz HLTV cap means HLTV viewers get lower fidelity than game clients at 120 Hz.

### Not Recommended
- **Pushing sv_maxupdaterate above 128** — Diminishing returns for human perception, stock clients may not benefit, and the ex_interp buffer dominates visual latency.
- **Removing the ex_interp buffer entirely** — Would cause entity jitter on connections with any packet loss or jitter. A reduced buffer (25ms) is safer.

---

## 10. Files Reference

| File | Key Content |
|------|-------------|
| `engine/host.cpp:59` | sys_ticrate cvar definition |
| `engine/host.cpp:667-701` | Host_FilterTime() - frame timing |
| `engine/sv_main.cpp:220-221` | sv_maxupdaterate, sv_minupdaterate |
| `engine/sv_main.cpp:1723-1746` | SV_CheckUpdateRate() |
| `HLTV/Proxy/src/Proxy.h:49-58` | MAX_PROXY_UPDATERATE constant |
| `HLTV/Proxy/src/Proxy.cpp:749` | ex_interp formula with 0.05f buffer |
| `rehlds/rehlds_security.cpp` | Command rate flood protection |

---

## 11. Glossary

| Term | Definition |
|------|------------|
| **sys_ticrate** | Server main loop frequency (frames per second) |
| **cl_updaterate** | Client-requested entity update frequency |
| **cl_cmdrate** | Client movement command send frequency |
| **ex_interp** | Entity interpolation time (visual latency buffer) |
| **sv_maxupdaterate** | Server-enforced maximum update rate |
| **rate** | Bandwidth limit in bytes/second |

---

*Document version 1.1 - February 7, 2026*
*v1.0 - February 4, 2026: Initial research*
*v1.1 - February 7, 2026: Clarified engine vs HLTV limits, added modern context, updated recommendations to reflect current KTP config*
