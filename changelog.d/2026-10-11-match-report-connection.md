### `analytics`: every match report carries a `connection` block (schema 30, DTO v1.13.0) (2026-10-11)

Drew asked for jitter and packet loss on the match page itself, after a week of answering
"was that half me or the server?" by hand (coordination `infra-weekly-outliers`). The block
publishes, per player, the share of 10 s windows in which they were the server's worst client
for jitter / latency / drops (`ktp_net_intervals`), their own ping at each shot where the
shot-detail stream was on (`ktp_shot_events.shot_ping` — 12-mans all season, officials from
2026-10-10), and the engine session that ended in this match (`ktp_net_sessions`, with its span,
because a session covers the whole connection); per match, drops per window and lag-compensation
state. Three instruments, kept apart, each `null` where it was not recording.

- `sql/analytics/net_interval_fact.sql`, `net_worst_fact.sql`, `net_session_fact.sql`,
  `shot_ping_fact.sql`; `source_capabilities` gains `net_intervals`, `net_sessions`, `shot_ping`.
- `build_connection` in `match_analytics.py`; `_connection_block` in `analytics_report_dto.py`
  (names only; passes the forbidden-key scan). Contract section in
  `docs/ANALYTICS_REPORT_DTO_CONTRACT.md`.
- **Match page only** by drew's ruling 2026-10-11: not a general stat, not a rating input.
  The renderer is keep-the-prac's (afraznein); until it lands the block is in the payload and
  invisible.
- Schema 29 → 30 regenerates the corpus (~15 min on the data server); the contract fixture has no
  net tables, so the integration report reads the block as `unavailable`, which is the test.
- **Deploy step, before the regen**: `ktpreports`@`localhost` needs `SELECT` on
  `hlstatsx.ktp_net_intervals` and `hlstatsx.ktp_net_sessions` (runbook grant block updated;
  `check_report_grants` derives it). Without them the tables are invisible to the capability
  probe and every report publishes the block as `unavailable` with no fault anywhere — the
  exact failure the grants check exists to catch. Measured 2026-10-11: the box holds neither.
