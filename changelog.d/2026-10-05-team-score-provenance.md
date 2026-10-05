### `docs`: official team-score provenance states the demo ledger is authoritative (2026-10-05)

`OFFICIAL_TEAM_SCORE_TELEMETRY.md` still said the producer was always KTPHudObserver, pinned by a
CHECK constraint, and pointed at an importer that was removed in `a64f5cb`. Operator ruling
2026-10-05: for official team scores the `hltv-demo` ledger is authoritative and the in-game result
in `ktp_match_reports` is its cross-check. The doc now says so, documents the real
`import_demo_team_score` invocation and migrations 033/034, and `ANALYTICS_REPORT_DTO_CONTRACT.md`
no longer presents the HUD result as the authority. No schema or code change.
