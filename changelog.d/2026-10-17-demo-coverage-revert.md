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

| half | proxy | `svc − demo` first → last | tail lost vs engine half end |
|---|---|---|---|
| NY4 `1791140846` h1 / h2 | unpatched | flat | **53.28 / 53.33 s** |
| NY4 `1791743912` h1 / h2 | unpatched | flat | **53.33 / 53.37 s** |
| **NY5 `1791745599` h1** | **patched** | flat | **1.06 s** |
| **NY5 `1791745599` h2** | **patched** | flat | **53.27 s** |

The offset is flat at one delay (60.004–60.018) from the first frame to the last on every one of
them, and `svc` at the first frame is 60.018–60.048 throughout. **Both NY5 rows are the same match
on the same binary, 33 minutes apart** — so the first-half recovery and the second-half loss are
separated by nothing but which half it was. A third NY5 pair (2026-09-27) predates the 09-30 canary
swap and has no engine `half_end` to measure against, so it yields no loss figure and is not counted
here.

So the first byte is written at proxy time ≈ delay, the demo's content begins at world ≈ 0 — **the head
is intact** — and the ~53 s is a genuine **tail** loss. `half_end − playback length` came out at a
median of 52.3 s, which #715 relabelled as a head offset; it is the same quantity under the wrong name.
The old `loss` column was approximately measuring the right thing all along.

**And the most useful rows are the patched pair:** 1.06 s on the first half against 53.27 s on the
second, same match, same binary, half an hour apart. That is `KTP-ReHLDS`#28 doing exactly what it
exists to do on a first half and not firing at all on a second, which is the open question in that
lane rather than a defect in this measurement. #715's framing would have retired the instrument that
shows it.

Three things from #715 were independently true and are **deliberately not** carried forward here, to keep
this revert a single reversible act rather than a revert plus new work: the `nDirectoryOffset = 0`
message naming a killed recording, the platform-separator fix for a local path passed to `--demos` as a
string, and the `YYMMDDHHMM` stamp decoder. They can return on their own merits; the decoder must not
return as a tail check.

`--max-loss` comes back with the revert, and the caution against it stands on its own grounds: it is a
MAX over halves, and because the fix recovers first halves while second halves stay near 53 s, no single
threshold separates patched from unpatched. Read the per-half rows.
