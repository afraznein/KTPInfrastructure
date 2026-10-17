### `scripts`: revert the demo_coverage rewrite — the instrument it installed could not fail (2026-10-17)

Reverts #715 in full. Its central claim — that HLTV demo tails are complete and `demo_coverage.py`'s
`DEMO_T0_GAME_TIME = 3.0` was charging a head offset to the tail — **is wrong**, and the check it
replaced `loss` with **cannot detect the loss it was built to measure**.

**Why the new tail check was vacuous.** It computed `(close mtime − the YYMMDDHHMM stamp in the demo's
name) − playback length` and read `[0,60)` as a complete tail. But the proxy writes a **delayed**
stream: between wall times T₀ and T₁ it writes world state from T₀−delay to T₁−delay, so playback
length tracks the *recorder's run duration* no matter where the content ends. The missing minute is in
**world** time at the end — world state that never entered the file at all — so no duration-based or
file-internal span measure can see it. "105 of 105 complete" and "2,292 of 2,294" were a check that
could not fail, reported as a corpus-wide result.

**What actually settles it is the embedded `svc_time` netmsg**, which `docs`-adjacent notes already
specified: the live path writes `svc_time = proxyTime − (spectatorTime − frame->time)`, so
`svc_time − demo_time` sits at the delay, and content end in world time is `svc_last − delay`.
Measured on 8 recent official halves, full frame walk, with the frame chain landing exactly on
`nDirectoryOffset` on 8 of 8 plus `HLDEMO`/protocol-5 controls:

| | `svc` at first frame | `svc − demo` first → last | tail lost vs engine half end |
|---|---|---|---|
| 6 halves on unpatched proxies | 60.018–60.044 | 60.004 → 60.018, flat | **53.3–53.4 s** |
| NY5 h1, patched proxy | 60.039 | 60.007 → 60.012 | **1.1 s** |

So the first byte is written at proxy time ≈ delay, the demo's content begins at world ≈ 0 — **the head
is intact** — and the ~53 s is a genuine **tail** loss. `half_end − playback length` came out at a
median of 52.3 s, which #715 relabelled as a head offset; it is the same quantity under the wrong name.
The old `loss` column was approximately measuring the right thing all along.

**And the single most useful row is the patched one:** 1.1 s against 53.3 s on the same map in the same
week is the proxy fix working on a first half, which is the result `KTP-ReHLDS`#28 exists to produce.
#715's framing would have retired the instrument that shows it.

Three things from #715 were independently true and are **deliberately not** carried forward here, to keep
this revert a single reversible act rather than a revert plus new work: the `nDirectoryOffset = 0`
message naming a killed recording, the platform-separator fix for a local path passed to `--demos` as a
string, and the `YYMMDDHHMM` stamp decoder. They can return on their own merits; the decoder must not
return as a tail check.

`--max-loss` comes back with the revert, and the caution against it stands on its own grounds: it is a
MAX over halves, and because the fix recovers first halves while second halves stay near 53 s, no single
threshold separates patched from unpatched. Read the per-half rows.
