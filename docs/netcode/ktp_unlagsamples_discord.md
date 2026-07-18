# sv_unlagsamples Change — Discord Post

Post as a single message in #server-updates or similar.

---

```
⚙️ Engine Update: sv_unlagsamples raised to 20

What changed:
sv_unlagsamples controls how many recent ping measurements the server averages together when calculating lag compensation. A higher value smooths out ping jitter so a single bad frame doesn't throw off hit detection.

Why it was capped at 16 (and why that was wrong for us):
The original GoldSrc engine ran at 100 ticks/sec. Each "sample" is one server frame, so at 100Hz:
• 3 samples = 30ms of ping history
• 16 samples = 160ms — plenty of smoothing

KTP servers run at 1000 ticks/sec. At 1000Hz, each frame is only 1ms:
• 3 samples = 3ms of ping history — almost nothing
• 16 samples = 16ms — still barely smoothing

The old cap of 16 was designed for 100Hz servers. At 1000Hz, we needed to raise it. We've removed the cap so we can tune it freely.

Why 20:
Modern competitive games target ~15-20ms interpolation windows:
• CS2: ~31ms (64Hz updates)
• CS:GO 128-tick: ~16ms
• Valorant: ~8ms (128Hz)
• Overwatch 2: ~16ms

At 1000Hz, sv_unlagsamples 20 = a 20ms averaging window. This is in line with what modern engines use for smoothing — enough to absorb normal ping jitter without adding noticeable delay to hit detection.

For a player with 50ms ping who spikes to 60ms on one frame, the old setting (3 samples) would jump the lag comp target by ~10ms. With 20 samples, that spike is absorbed into the average and barely moves the needle.

This is a server-side change — no client settings need to change.
We'll monitor hit registration feedback and adjust if needed.
```
