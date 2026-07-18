# KTP Netcode Guide (Discord Version)

Post as multiple messages in a #netcode or #settings channel. Each section below is one Discord message.

---

## Message 1: Recommended Settings

```
📋 KTP Recommended Client Settings

rate 1000000
cl_cmdrate 300
cl_updaterate 102
ex_interp 0.01
cl_lc 1
cl_lw 1

Paste these into your console or autoexec.cfg.
Read below to understand what each one does and why.
```

---

## Message 2: rate

```
📡 rate — Your Bandwidth Cap

rate controls how many bytes/sec the server is allowed to send you.

The old GoldSrc engine capped this at 100,000 (100 KB/s) — a limit set in 2004 for DSL connections. A 12-player DoD match needs ~60-80 KB/s of entity updates. At rate 100000, you're right at the edge — the server starts choking (skipping updates), and players stutter on your screen.

KTP-ReHLDS raised the cap to 1,000,000 (1 MB/s). Setting rate 1000000 tells the server "send me everything." The server only sends what it needs (~60-80 KB/s), so there's zero downside — you're just removing the bottleneck.

If your rate is too low → net_graph shows choke → players teleport on your screen.

✅ Set to: 1000000
```

---

## Message 3: cl_cmdrate

```
🎮 cl_cmdrate — How Fast You Send Commands

cl_cmdrate controls how many packets per second YOUR client sends to the server. Each packet contains your aim angles, movement, and button presses (fire, jump, reload).

Why higher is better: When you click fire, that action waits in a buffer until the next packet is sent.

• cl_cmdrate 100 → up to 10ms before your shot is sent
• cl_cmdrate 300 → up to 3.3ms before your shot is sent

That's ~7ms of input lag you can eliminate just by raising this value. Every packet also includes backup copies of recent commands, so if a packet is dropped, the server recovers your inputs from the next one.

There's no benefit to setting it higher than your FPS — you can't generate commands faster than you render frames.

KTP servers accept 100-500. Match it to your typical FPS or set 300.

✅ Set to: 300 (or match your FPS)
```

---

## Message 4: cl_updaterate

```
📥 cl_updaterate — How Many Updates You Receive

cl_updaterate tells the server how many position updates per second you want to receive. Higher = smoother player movement on your screen.

Important: DoD's client.dll silently caps this at 102. You can type cl_updaterate 500 in console — it'll show 500, but the client only processes 102 per second. Don't bother setting it above 102.

Each update contains delta-compressed entity states — only what changed since the last update. If a player is standing still, they take near-zero bytes. If they moved, you get their new position, angles, and animation state.

KTP servers enforce a minimum of 90 updates/sec, so even if you forget to set this, you're getting at least 90.

✅ Set to: 102
```

---

## Message 5: ex_interp

```
⏱️ ex_interp — Interpolation Buffer

ex_interp controls how far back in time your client renders other players. Your client needs at least two position snapshots to smoothly animate movement between them — ex_interp sets the size of that buffer.

• Too high (0.1) → You see players 100ms in the past. Feels sluggish.
• Too low (0.0) → Players jitter when a packet arrives late.
• Sweet spot (0.01) → ~10ms buffer. At updaterate 102, you get an update every ~9.8ms. Just enough cushion for smooth rendering.

KTP enforces 0.0 - 0.03. Lower is more responsive but riskier if your connection has jitter.

✅ Set to: 0.01
```

---

## Message 6: How Lag Compensation Works

```
🎯 How Hit Registration Works

When you shoot, the server doesn't check your bullet against where players are NOW — it checks where they were on YOUR screen when you pulled the trigger.

1. Your shot arrives at the server
2. Server calculates: your ping + your ex_interp = total delay
3. Server rewinds all opponents to where they were [delay] ms ago
4. Server checks if your crosshair was on the target at that moment
5. If yes → hit registers
6. Server restores everyone to current positions

This is why cl_lc 1 is mandatory — without it, lag compensation is disabled and you'd need to lead your shots by your full ping.

KTP uses sv_unlagsamples 3, which averages your ping over 3 recent frames instead of 1. This smooths out ping spikes so a single bad frame doesn't throw off hit detection.

The max rewind window is 500ms (sv_maxunlag 0.5). For US players on KTP servers (20-80ms ping), you're well within range.
```

---

## Message 7: Troubleshooting

```
🔧 Common Issues

"Players are teleporting/stuttering"
→ Check rate. If below 100000, set to 1000000.
→ Run net_graph 1 — red choke spikes = rate too low.

"My shots don't register"
→ Verify cl_lc 1 (lag compensation must be on)
→ Check ex_interp — if above 0.03, lower it
→ Raise cl_cmdrate — lower = more delay between click and server

"net_graph shows choke"
→ rate is too low. Set to 1000000.

"net_graph shows loss"
→ Packet loss on your network. No setting fixes this.
→ Check your connection or try a different route.
```

---

## Message 8: KTP Server Settings (Optional/Reference)

```
⚙️ KTP Server Settings (for reference)

sys_ticrate 1000        Server runs 1000 frames/sec
sv_maxupdaterate 120    Max updates sent to clients
sv_minupdaterate 90     Minimum updates sent
sv_maxcmdrate 500       Max client commands accepted
sv_mincmdrate 100       Min client commands required
sv_maxrate 1000000      1 MB/s bandwidth cap
sv_minrate 100000       100 KB/s bandwidth floor
sv_unlag 1              Lag compensation ON
sv_maxunlag 0.5         500ms max rewind window
sv_unlagsamples 3       Averages 3 ping samples

The server physics run at 1000 Hz — 10x higher than standard GoldSrc (100 Hz). Combined with lag compensation and high update rates, KTP servers process your inputs with minimal delay.
```
