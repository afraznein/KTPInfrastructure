# KTP Netcode Guide: Understanding Your Rate Settings

**Last Updated:** July 9, 2026
**Author:** Nein_
**Applies to:** All KTP servers (Atlanta, Dallas, Denver, New York, Chicago)

---

## TL;DR — Recommended Client Settings

```
rate 100000          // locked by the server — anything else is auto-corrected
cl_cmdrate 101       // or match your fps_max if higher
cl_updaterate 102
ex_interp 0.01
cl_lc 1
cl_lw 1
cl_fixtimerate 7.5   // default — lower toward 0 only if weapon animations skip
cl_smoothtime 0.01   // near-instant prediction-error correction; 0.1 = high-ping comfort option
```

If you want to understand *why* these values matter, read on.

---

## How GoldSrc Networking Works

Every time you play on a KTP server, your client and the server are constantly exchanging small UDP packets. Understanding what's in those packets and how fast they flow is the key to understanding hit registration.

### The Two Directions

```
        cl_cmdrate                              cl_updaterate
    (you → server)                          (server → you)

  ┌──────────┐    UDP Packets     ┌──────────┐
  │  CLIENT   │ ───────────────►  │  SERVER   │
  │           │                   │ (1000 Hz) │
  │  Your PC  │ ◄───────────────  │           │
  └──────────┘    UDP Packets     └──────────┘

  You send:                       Server sends:
  - Your movement                 - Where everyone is
  - Your aim angles               - Who got hit
  - Your button presses           - Score updates
  - Your weapon actions           - Game events
```

---

## What Each Setting Does

### `rate` — Your Bandwidth Cap (bytes/sec)

**What it does:** `rate` is the maximum number of bytes per second the server is allowed to send you. Think of it as the width of your internet pipe.

**The problem with the old cap:** The GoldSrc engine originally hardcoded a maximum `rate` of **100,000 bytes/sec (100 KB/s)**. This limit was set in 2004 when most players were on DSL or cable connections with limited bandwidth. At 100 KB/s, the server sometimes can't fit all the entity updates into your bandwidth budget, so it **chokes** — it skips sending you updates, and you see players teleport or stutter.

**What we changed:** KTP-ReHLDS raises the engine's maximum `rate` to **1,000,000 bytes/sec (1 MB/s)**, and we trialed the full 1 MB/s fleet-wide in February 2026. After testing, **`rate` is now locked at exactly 100000 for everyone** (March 2026): at our real ceiling of 102 updates/sec with ~500-800 byte packets, peak traffic is ~96 KB/s — 100 KB/s never chokes — and locking the value means every client runs an identical bandwidth budget, removing per-client rate variance as a hit-registration variable.

**Why 100000 is enough:**
- A 12-player DoD match with delta compression uses ~50-80 KB/s
- Even 1 Mbps internet (the slowest broadband) handles 125 KB/s
- If your rate were too low, the server couldn't send you all the position updates — the 100,000 floor prevents that

**Server enforcement:** KTP servers set `sv_minrate 100000` and `sv_maxrate 100000` — the value is pinned, and KTPCvarChecker corrects any client that sets something else. You don't need to touch it beyond putting `rate 100000` in your config.

```
rate too low (30000):
  Server has update → Checks your rate budget → Budget exceeded → CHOKED
  Result: You don't get this update. Players stutter on your screen.

rate high enough (1000000):
  Server has update → Checks your rate budget → Budget fine → SENT
  Result: You get every update. Smooth player movement.
```

---

### `cl_updaterate` — How Many Updates You Request Per Second

**What it does:** This tells the server how many times per second you want to receive entity position updates. Higher = smoother player movement on your screen and more accurate positions for shooting.

**The client.dll cap:** Day of Defeat's `client.dll` silently clamps `cl_updaterate` to a maximum of **102**. You can type `cl_updaterate 500` in console — the cvar will show 500, but the engine only processes up to 102 updates per second. This is a hardcoded client-side limit.

**Server enforcement:** KTP servers set `sv_maxupdaterate 120` and `sv_minupdaterate 100`. The server won't send more than 120 updates/sec (but the client caps at 102 anyway), and won't send fewer than 100.

**Set it to 102.** That's the real maximum the client can use.

**What an update contains:**
Each server→client update packet carries delta-compressed entity states — only the data that changed since the last update you acknowledged. A typical update includes:
- Player positions (origin x, y, z) — only if the player moved
- Player angles (where they're looking) — only if they turned
- Animation state (running, prone, firing)
- Weapon/model changes

Delta compression means the server only sends what changed, keeping packets small (~500-800 bytes average).

---

### `cl_cmdrate` — How Many Commands You Send Per Second

**What it does:** This controls how many movement command packets your client sends to the server per second. Each packet contains your position, aim angles, button presses (fire, jump, reload), and movement inputs.

**Why higher is better:** Every time you click fire, that action is bundled into the next command packet. With `cl_cmdrate 100`, there's up to a 10ms window where your shot is waiting to be sent. With `cl_cmdrate 300`, that window shrinks to ~3.3ms.

**How commands are bundled:**
Your client bundles multiple movement commands into each UDP packet. The engine can fit up to 64 commands per packet (`CMD_MAXBACKUP`). At `cl_cmdrate 300`, you're sending ~300 packets per second, each containing 1-2 movement snapshots from the last ~3.3ms.

Each command snapshot contains:
- `msec` — time since last command (how long this movement lasted)
- `buttons` — what you're pressing (IN_ATTACK, IN_JUMP, etc.)
- `viewangles` — exactly where you're aiming (pitch, yaw, roll)
- `forwardmove`, `sidemove`, `upmove` — your movement direction
- `impulse` — weapon switches

**Backup commands for reliability:**
Every packet also includes **backup commands** — copies of recent commands the server might have missed if a packet was dropped. This is automatic and transparent. If a packet gets lost on the network, the server recovers your inputs from the next packet's backup data.

**What about the server's ticrate?** KTP servers run at 1000 Hz (`sys_ticrate 1000`), meaning the server processes game logic 1000 times per second. Setting `cl_cmdrate` higher than your FPS has no benefit (you can't generate commands faster than you render frames), but setting it significantly lower than your FPS means you're batching more commands per packet, increasing the delay between your action and the server seeing it.

**Recommended:** `cl_cmdrate 101` for the standard `fps_max 100` setup. If you run a higher frame cap, match it to your fps_max (e.g. 250 at 240fps) — values above your actual FPS are inert, since you can't generate commands faster than you render frames. Note: engine-source research indicates the Steam client caps effective cmdrate near ~100 regardless, so 101 is sufficient for most players; setting higher is harmless.

**Server enforcement:** KTP servers set `sv_mincmdrate 100` and `sv_maxcmdrate 500`. KTPCvarChecker allows 100-1000 (the ceiling above 500 exists for high-fps input-resolution testing).

```
cl_cmdrate 100 (1 packet every 10ms):
  Frame 1: You click fire ─┐
  Frame 2: Moving...        │ Waiting to send...
  Frame 3: Moving...        │
  Frame 4: Packet sent! ────┘  (up to 10ms delay)

cl_cmdrate 300 (1 packet every 3.3ms):
  Frame 1: You click fire ─┐
  Frame 2: Packet sent! ───┘  (up to 3.3ms delay)
```

---

### `ex_interp` — Entity Interpolation Time

**What it does:** `ex_interp` controls how far back in time your client renders other players. The client needs at least two position snapshots to smoothly interpolate movement between them. `ex_interp` sets how large that time buffer is.

**Why it exists:** Network packets don't arrive at perfectly even intervals. Without a buffer, players would visibly jerk whenever a packet arrived slightly late. `ex_interp` provides a cushion — by rendering players slightly in the past, your client always has enough data to draw smooth movement.

**The tradeoff:** Higher `ex_interp` = smoother visuals but you're seeing players further in the past. Lower `ex_interp` = more responsive but risk of jitter if packets arrive late.

**KTP enforcement:** `ex_interp` is enforced between 0.01 and 0.05 (10-50ms). At `cl_updaterate 102`, you receive an update every ~9.8ms. Setting `ex_interp 0.01` (10ms) — the enforced floor and the recommended value — gives you just enough buffer for one update interval with a small safety margin, so you see opponents as close to their true position as possible. The 0.05 cap blocks exploitative high-interp values.

**When is raising it justified?** Only for loss or jitter on **your own** connection — check `net_graph 1`. Each +0.01 buys one more update interval of cushion at the cost of seeing everything ~10ms later. It's a reaction-time tax, not a hit-registration one: the server rewinds by ping + interp, so you still hit what you see.

| Your connection | ex_interp |
|---|---|
| Clean — 0% loss, stable ping | **0.01** |
| Loss ~1%+ or enemies stutter at 0.01 | **0.02** — rides through a single lost packet invisibly |
| Chronically jittery route (SA/EU long-haul) | **0.02–0.03** |
| Above 0.03 | No legitimate case — the 0.05 cap is a ceiling, not a target |

**Ping alone is not a reason — yours or your opponents'.** Latency delays the update stream uniformly (a stable 160ms connection still gets a snapshot every ~9.8ms) and lag compensation accounts for it; high-ping players often do need 0.02, but because long routes tend to be jittery, not because of the ping number. Raising interp does nothing against high-ping *opponents* either: their staleness is baked in server-side before your packet is sent, the buffer applies to every entity equally, and a choppy opponent's warpy movement just plays back the same — later. The "shot me behind cover" effect is the *shooter's* rewind window (their ping + their interp, capped server-side by `sv_maxunlag 0.5`) — no client setting of yours changes it.

---

### `cl_lc` and `cl_lw` — Lag Compensation and Weapon Prediction

**`cl_lc 1`** (Lag Compensation): This enables server-side lag compensation. When you shoot, the server rewinds time to where players were on *your* screen at the moment you fired. Without this, you'd have to lead your shots by your ping.

**`cl_lw 1`** (Local Weapons): This enables client-side weapon prediction. Your weapon fires, ejects shells, and plays sounds instantly on your screen without waiting for server confirmation.

**Both should stay 1.** As of KTPCvarChecker 7.25 (April 2026) these are no longer force-enforced — an engine-source audit confirmed that setting either to 0 only handicaps *you* (no exploit surface). Leave them at 1 unless you have a specific reason to prefer server-authoritative behavior.

---

## How Lag Compensation Works (The Server's Perspective)

This is the most important part for understanding hit registration.

```
Timeline:

  [Past] ◄──────────────────────────────────────────── [Now]
         │                                              │
         │  Your ping (50ms)                            │
         │◄────────────────►                            │
         │                  │                           │
         │  + ex_interp     │                           │
         │  (10ms)          │                           │
         │◄──►              │                           │
         │                  │                           │
    ┌────┴───┐         ┌────┴───┐                  ┌────┴───┐
    │ Where  │         │ Your   │                  │ Where  │
    │ you SAW│         │ shot   │                  │ target │
    │ target │         │ arrives│                  │ is NOW │
    └────────┘         └────────┘                  └────────┘

    Server rewinds ◄───────────────────────────────────►
    opponents to where              sv_maxunlag (500ms max)
    you saw them
```

When your shot arrives at the server:

1. Server calculates your effective latency: **ping + ex_interp**
2. Server looks back through its history of player positions
3. Server moves all opponents to where they were at that point in time
4. Server runs your shot against those rewound positions
5. If your crosshair was on the target on YOUR screen, the shot hits
6. Server restores everyone to their current positions

**`sv_unlagsamples 1`** (KTP setting, June 2026): The server uses your single most recent latency sample for lag compensation. KTP previously ran 20-sample averaging, but analysis showed the client frame buffer advances per client packet (~100/sec), so 20 samples smeared ~200ms of latency history — and one ping spike inside the window could silently zero out lag compensation for a shot. One fresh sample tracks your actual current latency. This also rewards a steady, unchoked packet flow — another reason the locked `rate` and cmdrate-matches-fps recommendations matter.

**`sv_maxunlag 0.5`** (KTP setting): The maximum rewind window is 500ms. If your effective latency (ping + interp) exceeds 500ms, lag compensation is disabled and you'll need to lead your shots. For US players on US servers (typical 20-80ms ping), this is never an issue.

---

## How Rate Limiting Works

The server has a bandwidth budget for each player based on their `rate` setting:

```
Your rate = 100000 bytes/sec

Server wants to send you an update (800 bytes):
  1. Check: Have I sent too much data recently? (cleartime < realtime?)
  2. If yes: SEND. Add 800/100000 = 0.008 seconds to cleartime
  3. If no: CHOKE. Skip this update. Send svc_choke to tell your client.

Your client sees svc_choke:
  → net_graph shows "choke" spikes
  → You missed an update
  → Other players may stutter on your screen
```

With `rate 100000`, the cleartime per packet (0.008 seconds for an 800-byte packet) supports ~125 packets/sec of worst-case-size updates — comfortably above the 102/sec the client can use, so **it is never the bottleneck** at KTP's update rates.

With `rate 30000` (old default), an 800-byte packet takes 0.0267 seconds of cleartime — meaning you can only receive ~37 packets per second before choking. If you have `cl_updaterate 102`, you're requesting 102 updates/sec but can only receive ~37. You'll see constant choke.

---

## Packet Structure (Technical)

For those curious about what's actually on the wire:

### Client → Server Packet (clc_move)
```
UDP Packet (~100-200 bytes typical):
├─ Netchan header (26 bytes)
│  ├─ Outgoing sequence number (4 bytes)
│  ├─ Incoming sequence + ACK (4 bytes)
│  └─ Fragment headers (18 bytes)
├─ clc_move opcode (1 byte)
├─ Checksum (1 byte)
├─ Packet loss percentage (1 byte)
├─ Number of new commands (1 byte)
├─ Number of backup commands (1 byte)
└─ Command array (variable, ~20-40 bytes per command):
   ├─ msec since last command
   ├─ View angles (pitch, yaw, roll)
   ├─ Forward/side/up movement
   ├─ Buttons pressed
   └─ Impulse (weapon switch)
```

### Server → Client Packet (entity update)
```
UDP Packet (~500-800 bytes typical, up to 4010 max):
├─ Netchan header (26 bytes)
├─ svc_time + server timestamp (5 bytes)
├─ Player HUD data (variable)
│  ├─ Health, armor, ammo
│  ├─ Weapon animations
│  └─ View angle corrections
└─ svc_deltapacketentities (bulk of packet):
   ├─ Number of entities
   ├─ Delta reference frame
   └─ Per-entity delta data:
      Only fields that CHANGED since last acknowledged update:
      ├─ Position (x,y,z) — if player moved
      ├─ Angles — if player turned
      ├─ Animation frame — if animation changed
      ├─ Model index — if weapon changed
      └─ Effects/render flags — if visual state changed
```

Delta compression is why GoldSrc packets are so small. If a player is standing still, they take near-zero bytes in the update. Only movement, angle changes, and state transitions consume bandwidth.

---

## KTP Server Settings

| Setting | Value | Purpose |
|---------|-------|---------|
| `sys_ticrate` | 1500 | Requested tick ceiling — achieves ~1000 real fps of physics/logic |
| `sv_maxupdaterate` | 120 | Max entity updates per second to clients |
| `sv_minupdaterate` | 100 | Minimum updates per second |
| `sv_maxcmdrate` | 500 | Max client command packets accepted |
| `sv_mincmdrate` | 100 | Minimum client commands required |
| `sv_maxrate` | 100000 | Bandwidth cap — locked equal to the floor since March 2026 |
| `sv_minrate` | 100000 | 100 KB/s bandwidth floor |
| `sv_unlag` | 1 | Lag compensation enabled |
| `sv_maxunlag` | 0.5 | Max 500ms rewind window |
| `sv_unlagsamples` | 1 | Latest latency sample used for lag comp (see above) |

### KTPCvarChecker Enforced Client Settings

| Setting | Enforced Range | Notes |
|---------|---------------|-------|
| `cl_updaterate` | 100 - 120 | Client.dll caps at 102 regardless — set 102 |
| `cl_cmdrate` | 100 - 1000 | Match to your FPS; server accepts max 500 |
| `rate` | locked 100000 | Auto-corrected to exactly 100000 |
| `ex_interp` | 0.01 - 0.05 | 0.01 recommended — one update interval of buffer |
| `cl_lc` | *(not enforced)* | Keep at 1 — 0 is a pure self-handicap |
| `cl_lw` | *(not enforced)* | Keep at 1 — 0 also disables lag compensation |

---

## Common Issues and Fixes

### "Players are teleporting/stuttering"
- Check `rate` — should be 100000 (the server auto-corrects it, but a config fighting the checker causes churn)
- Check `cl_updaterate` — should be 102
- Check `net_graph 1` for choke (red spikes = server can't send fast enough for your rate)

### "My shots don't register"
- Verify `cl_lc 1` — without this, you have to lead shots by your full ping
- Check `ex_interp` — if above 0.01, you're seeing players further in the past than you need to
- Check your ping — lag compensation works up to 500ms, but degrades above ~150ms
- Consider raising `cl_cmdrate` — lower cmdrate = more delay between your click and the server seeing it

### "net_graph shows high choke"
- Check `rate` is 100000 (the locked value). At KTP's update rates, 100 KB/s doesn't choke from bandwidth.
- If choke persists, it's a network issue between you and the server, not a setting problem.

### "net_graph shows high loss"
- This is packet loss on your network path. No cvar can fix this.
- Check your local network first (WiFi is the usual culprit; wire in if you can). Loss further out on the route usually clears on its own.

---

## Why KTP Raised the Rate Cap

The GoldSrc engine (circa 2004) shipped with a hardcoded maximum `rate` of 100,000 bytes/sec in `net.h`. This made sense in 2004 when broadband meant 1.5 Mbps DSL shared with your whole household.

In 2026, the average US internet connection is 200+ Mbps. The 100 KB/s cap was actively harming gameplay — at `cl_updaterate 100` with 12 active players, the server needs to send ~60-80 KB/s of entity updates. With `rate 100000` and any amount of packet overhead, you're right at the edge of choking.

KTP-ReHLDS modified `MAX_RATE` in `net.h` from `100000.0f` to `1000000.0f`, giving players 10x the bandwidth headroom. The full 1 MB/s ran fleet-wide as a February 2026 trial.

**Postscript (March 2026):** after the trial, `rate` was locked to exactly 100000 for all clients (`sv_minrate = sv_maxrate = 100000`, enforced by KTPCvarChecker). Measurement showed peak traffic at our update rates tops out ~96 KB/s — inside the original cap — and a locked value puts every player on an identical bandwidth budget, removing rate variance as a hit-registration variable. The engine's raised MAX_RATE remains in place as headroom for HLTV proxies and any future updaterate increase.

---

*This document is based on source code analysis of KTP-ReHLDS 3.22.0.909; config values verified against the live fleet July 9, 2026. For technical details and engine internals, see `docs/netcode_research.md`.*
