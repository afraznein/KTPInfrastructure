# Fleet FPS Baselines

Structured snapshots of fleet `[KTP_PROFILE] frames=N fps=X.Y` data, captured for before/after comparisons when fleet-wide changes land.

## Format

Each snapshot is a JSON file named `fleet_fps_<YYYY-MM-DD>_<label>.json` with:

```json
{
  "label": "pre-jit",
  "captured_at_utc": "2026-04-23T...",
  "description": "what was / wasn't true at capture time",
  "context": { ... relevant state flags ... },
  "fleet_stats":        { "n", "p50", "p99", "mean", "stdev", "min", "max",
                          "pct_in_nfo_window", "pct_within_10" },
  "per_host_stats":     { "<host>": { same fields } },
  "per_instance_stats": { "<host:port>": { same fields } }
}
```

## Methodology

Samples pulled via SSH+grep from each instance's `~/dod-<port>/log/console/` — the current live log plus any log rotated today. Pattern: `[KTP_PROFILE] frames=<N> fps=<X.Y>`. This fires every `ktp_profile_interval` seconds (default 10s), so each instance generates ~8640 samples/day.

Window: current + today-rotated log ≈ 12-48h depending on restart timing. Adjust the grep command if you need a specific window.

**Scripts** (added 2026-04-25, after running this twice):
- `pull_fleet_fps.py <suffix> [--label X] [--description Y]` — paramiko fan-out to all 5 game servers, greps `[KTP_PROFILE]` from each `~/dod-<port>/log/console/*-console.log`, writes `fleet_fps_<suffix>.json`. ~5-10s wall time for ~140k samples.
- `diff_fleet_fps.py <pre.json> <post.json>` — prints fleet/per-host/per-instance deltas with focus on σ compression, p50 shift, NFO-window %, and ATL:27016 normalization (the pre-JIT anomaly target).
- `check_atl27019.py` — per-hour time-series breakdown for ATL:27019 specifically (used to disambiguate fleet-aggregate σ regressions from localized live-match events).
- `check_cmd_ready.py` — fleet-wide grep for `[KTP_OPCODE] cmd_ready` and `Function _cmd_ready_*` profiler hits in current console logs.

## Snapshots

| File | Label | Captured | Purpose |
|------|-------|----------|---------|
| `fleet_fps_2026-04-23_pre-jit.json` | pre-jit | 2026-04-23 (pre-3AM restart) | Baseline before the fleet-wide `debug` flag strip activates JIT on all KTP plugins. Compare against the post-JIT snapshot to isolate the interpreted→JIT delta without other variables moving. |
| `fleet_fps_2026-04-25_post-jit.json` | post-jit | 2026-04-25 (full matchday post-JIT) | Post-JIT comparison snapshot. **Verdict:** ATL:27016 σ 30.70→6.90 (4× tighter, the predicted normalization confirms interpreted Pawn was the root cause). Per-instance σ compression on 22/24 instances. Fleet σ aggregate up due to two unrelated outliers: NY:27015 was mostly down (n=861), and ATL:27019 had a localized live-match event in hours 18-19 EDT (per-hour breakdown shows hours 03-17 normal). cmd_ready 163ms spike rate dropped to zero in same-day grep window. |

## Comparison quick-ref

When adding a new snapshot, compute deltas vs the most recent relevant baseline:

- **p50 shift** — did the median fps move?
- **stdev change** — tighter distribution (less jitter) or wider?
- **`pct_in_nfo_window` / `pct_within_10` shift** — changes to the tail of the distribution, separate from median
- **Per-instance outliers** — any instance whose delta is meaningfully different from its host's average? Flag for investigation.

For JIT A/B specifically: the most interesting instance is **ATL:27016** which pre-JIT had σ=30.74 (4× the next worst). If its σ normalizes post-JIT to ~8, that's evidence interpreted-plugin tail latency was the cause.
