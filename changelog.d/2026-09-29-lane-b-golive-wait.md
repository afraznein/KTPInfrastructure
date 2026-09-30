### `tests`: Lane B waits for the plugin's go-live line, and accepts the `move` health stream (2026-09-29)

`run_match` slept a fixed 5 s after `.testmatch` and then applied `--shot-detail` and started the kill-switch window. KTPMatchHandler 0.10.176 goes live on the real round start, later than that, so its own shot-detail activation ran after the harness override, and the kill switch could be up before go-live. The harness now waits for this match's `KTP_MATCH_START` line (45 s bound, then the old fixed 5 s, and it logs which path ran).

The persistent `full` failures came from two causes. The kill switch had disabled capture across go-live, so the report match's manifest only arrived when capture was re-enabled (receipt latency 46-47 s against the 0..3 s policy). The census `move` health type from KTPAMXX #142 was unknown to `CAPTURE_EVENT_TYPES_OPTIONAL` and to `check_capture_health`, which failed `capture_health`, `diagnostic_capture_health`, `capture_context_isolation` and the v5 report authorization. `move` is now an optional health type.

`docs/TECHNICAL_GUIDE.md` describes the 0.10.176 go-live instead of a 5 s safety timeout.
